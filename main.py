import gc
import time
import json
import os
import network
import socket
import ubinascii
import urequests
from machine import ADC, Pin, UART, reset_cause

import config


printer = UART(
    config.PRINTER_UART_ID,
    baudrate=config.PRINTER_BAUD,
    bits=8,
    parity=None,
    stop=1,
    tx=config.PRINTER_TX_PIN,
    rx=config.PRINTER_RX_PIN,
    timeout=config.PRINTER_TIMEOUT_MS,
)

button = Pin(config.BUTTON_PIN, Pin.IN, Pin.PULL_UP)
status_led = Pin(config.STATUS_LED_PIN, Pin.OUT) if config.STATUS_LED_PIN is not None else None
boot_ms = time.ticks_ms()
button_event = False
button_pressed_at = 0
button_irq_debounce_ms = int(getattr(config, "BUTTON_FAST_DEBOUNCE_MS", min(getattr(config, "BUTTON_DEBOUNCE_MS", 120), 25)))

player_switch_a = Pin(getattr(config, "PLAYER_SWITCH_PIN_A", 15), Pin.IN, Pin.PULL_UP)
player_switch_b = Pin(getattr(config, "PLAYER_SWITCH_PIN_B", 16), Pin.IN, Pin.PULL_UP)


def button_irq(pin):
    global button_event, button_pressed_at
    now = time.ticks_ms()
    if time.ticks_diff(now, button_pressed_at) > button_irq_debounce_ms:
        button_event = True
        button_pressed_at = now


try:
    button.irq(trigger=Pin.IRQ_FALLING, handler=button_irq)
except Exception as exc:
    print("Button IRQ setup failed:", exc)

setup_errors = []
pot_adcs = {}
for control in getattr(config, "POT_CONTROLS", []):
    try:
        adc = ADC(Pin(control["pin"]))
        if hasattr(adc, "atten"):
            adc.atten(getattr(ADC, "ATTN_11DB", 3))
        if hasattr(adc, "width"):
            adc.width(getattr(ADC, "WIDTH_12BIT", 3))
        pot_adcs[control["name"]] = adc
    except Exception as exc:
        message = "Pot setup failed: " + str(control.get("name")) + " GPIO" + str(control.get("pin")) + " " + str(exc)
        setup_errors.append(message)
        print(message)


def led(value):
    if status_led:
        status_led.value(1 if value else 0)


def write(data, delay_ms=None):
    if isinstance(data, str):
        data = data.encode("utf-8")
    if data:
        printer.write(data)
        time.sleep_ms(config.PRINTER_WRITE_DELAY_MS if delay_ms is None else delay_ms)


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, int(value)))


def map_range(value, in_min, in_max, out_min, out_max):
    value = clamp(value, in_min, in_max)
    return out_min + ((value - in_min) * (out_max - out_min)) // max(1, in_max - in_min)


def read_adc_value(adc):
    if hasattr(adc, "read_u16"):
        return adc.read_u16()
    return adc.read()


def read_pot_percent(name):
    adc = pot_adcs.get(name)
    if not adc:
        return None
    samples = int(getattr(config, "POT_SAMPLES", 5))
    total = 0
    for _ in range(max(1, samples)):
        total += int(read_adc_value(adc))
        time.sleep_ms(int(getattr(config, "POT_SAMPLE_DELAY_MS", 2)))
    raw = total // max(1, samples)
    raw_max = 65535 if raw > 4095 else 4095
    if bool(getattr(config, "POT_REVERSE_OUTPUT", True)) or bool(getattr(config, "POT_REVERSE", False)):
        raw = raw_max - raw
    return map_range(raw, 0, raw_max, 1, 100)


def read_control_settings():
    defaults = getattr(config, "DEFAULT_CONTROL_SETTINGS", {
        "age": 50,
        "queerness": 50,
        "diversity": 50,
    })
    settings = dict(defaults)
    for key in ("age", "queerness", "diversity"):
        value = read_pot_percent(key)
        if value is not None:
            settings[key] = value
    return settings


def read_player_count():
    left_active = player_switch_a.value() == 0
    right_active = player_switch_b.value() == 0
    value_a = int(getattr(config, "PLAYER_SWITCH_VALUE_A", 4))
    value_b = int(getattr(config, "PLAYER_SWITCH_VALUE_B", 6))
    if bool(getattr(config, "PLAYER_SWITCH_REVERSE", True)):
        value_a, value_b = value_b, value_a
    if left_active and not right_active:
        return value_a
    if right_active and not left_active:
        return value_b
    return int(getattr(config, "PLAYER_SWITCH_CENTER_VALUE", 5))


def control_report():
    settings = read_control_settings()
    report = (
        "Players: " + str(read_player_count())
        + "\nAGE: " + str(settings.get("age"))
        + "\nQUEERNESS: " + str(settings.get("queerness"))
        + "\nDIVERSITY: " + str(settings.get("diversity"))
    )
    if setup_errors:
        report += "\n" + "\n".join(setup_errors[:4])
    return report


def printer_init():
    write(b"\x1b\x40", 250)
    write(b"\x1b\x37" + bytes((
        clamp(config.PRINTER_HEAT_DOTS, 1, 255),
        clamp(config.PRINTER_HEAT_TIME, 1, 255),
        clamp(config.PRINTER_HEAT_INTERVAL, 1, 255),
    )))
    write(b"\x12\x23" + bytes(((clamp(config.PRINTER_BREAK_TIME, 0, 7) << 5) | clamp(config.PRINTER_DENSITY, 0, 31),)))
    write(b"\x1b\x61\x00")
    write(b"\x1d\x21\x00")
    write(b"\x1b\x45\x00")


def feed(lines=None):
    write(b"\n" * int(lines if lines is not None else config.FEED_LINES_AFTER_CARD), 60)


def feed_dots(dots):
    dots = clamp(int(dots or 0), 0, 255)
    if dots:
        write(b"\x1b\x4a" + bytes((dots,)), 20)


def center():
    write(b"\x1b\x61\x01")


def left():
    write(b"\x1b\x61\x00")


def bold(on=True):
    write(b"\x1b\x45" + (b"\x01" if on else b"\x00"))


def size(width=1, height=1):
    width = clamp(width, 1, 8)
    height = clamp(height, 1, 8)
    write(b"\x1d\x21" + bytes((((width - 1) << 4) | (height - 1),)))


def cut_if_available():
    if config.PRINTER_SEND_CUT:
        write(b"\x1d\x56\x00", 120)


def print_qr(payload):
    if not payload:
        return
    data = payload.encode("utf-8")
    store_len = len(data) + 3
    p_l = store_len & 0xFF
    p_h = (store_len >> 8) & 0xFF
    center()
    write(b"\x1d\x28\x6b\x04\x00\x31\x41\x32\x00")
    write(b"\x1d\x28\x6b\x03\x00\x31\x43" + bytes((clamp(config.QR_MODULE_SIZE, 1, 16),)))
    write(b"\x1d\x28\x6b\x03\x00\x31\x45" + bytes((clamp(config.QR_ERROR_CORRECTION, 48, 51),)))
    write(b"\x1d\x28\x6b" + bytes((p_l, p_h)) + b"\x31\x50\x30" + data)
    write(b"\x1d\x28\x6b\x03\x00\x31\x51\x30", config.QR_PRINT_DELAY_MS)
    left()


def normalize_text(text):
    text = str(text or "")
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def print_wrapped(text, width=None):
    width = max(1, int(width or config.PRINTER_TEXT_COLUMNS))
    for raw in normalize_text(text).split("\n"):
        words = raw.split()
        if not words:
            write("\n")
            continue
        line = ""
        for word in words:
            while len(word) > width:
                if line:
                    write(line + "\n")
                    line = ""
                write(word[:width] + "\n")
                word = word[width:]
            candidate = word if not line else line + " " + word
            if len(candidate) <= width:
                line = candidate
            else:
                write(line + "\n")
                line = word
        if line:
            write(line + "\n")


def print_text_part(text, style, fallback_columns=None):
    if not text:
        return
    align = style.get("align", "left")
    width_multiplier = max(1, int(style.get("width", 1)))
    physical_columns = max(1, int(config.PRINTER_TEXT_COLUMNS) // width_multiplier)
    configured_columns = int(style.get("columns", fallback_columns or physical_columns))
    wrap_columns = min(configured_columns, physical_columns)
    center() if align == "center" else left()
    bold(bool(style.get("bold", False)))
    size(width_multiplier, int(style.get("height", 1)))
    print_wrapped(text, wrap_columns)
    size(1, 1)
    bold(False)
    left()


def print_raster_image(image):
    if not image:
        return
    width = int(image.get("width", 0))
    height = int(image.get("height", 0))
    data_hex = image.get("bytes_hex", "")
    if width <= 0 or height <= 0 or not data_hex:
        return
    width_bytes = (width + 7) // 8
    data = ubinascii.unhexlify(data_hex)
    center()
    header = b"\x1dv0\x00" + bytes((
        width_bytes & 0xFF,
        (width_bytes >> 8) & 0xFF,
        height & 0xFF,
        (height >> 8) & 0xFF,
    ))
    printer.write(header)
    time.sleep_ms(20)
    chunk_size = int(getattr(config, "PRINTER_RASTER_CHUNK_BYTES", 512))
    delay_ms = int(getattr(config, "PRINTER_RASTER_CHUNK_DELAY_MS", 12))
    for offset in range(0, len(data), chunk_size):
        printer.write(data[offset:offset + chunk_size])
        time.sleep_ms(delay_ms)
    left()
    write("\n")


def remove_file_if_present(path):
    try:
        os.remove(path)
    except OSError:
        pass


def download_raster_file_once(image):
    if not image:
        return None
    width = int(image.get("width", 0))
    height = int(image.get("height", 0))
    url = image.get("url", "")
    if width <= 0 or height <= 0 or not url:
        return None
    expected_bytes = ((width + 7) // 8) * height
    final_path = str(getattr(config, "RASTER_CACHE_PATH", "persona_raster.bin"))
    temp_path = final_path + ".tmp"
    response = None
    received = 0
    remove_file_if_present(temp_path)
    try:
        gc.collect()
        response = urequests.get(url, headers={"X-Device-Secret": config.DEVICE_SECRET})
        status_code = int(getattr(response, "status_code", 0))
        if status_code < 200 or status_code >= 300:
            raise RuntimeError("Raster HTTP " + str(status_code))
        chunk_size = int(getattr(config, "PRINTER_RASTER_CHUNK_BYTES", 512))
        with open(temp_path, "wb") as raster_file:
            while received < expected_bytes:
                chunk = response.raw.read(min(chunk_size, expected_bytes - received))
                if not chunk:
                    break
                raster_file.write(chunk)
                received += len(chunk)
    finally:
        if response:
            response.close()
    if received != expected_bytes:
        remove_file_if_present(temp_path)
        raise RuntimeError(
            "Incomplete raster: " + str(received) + "/" + str(expected_bytes)
        )
    remove_file_if_present(final_path)
    os.rename(temp_path, final_path)
    print("Raster downloaded:", received, "bytes")
    return {
        "path": final_path,
        "width": width,
        "height": height,
        "bytes": expected_bytes,
    }


def download_raster_file(image):
    retries = max(1, int(getattr(config, "RASTER_DOWNLOAD_RETRY_COUNT", 3)))
    pause_ms = int(getattr(config, "RASTER_DOWNLOAD_RETRY_PAUSE_MS", 500))
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            print("Downloading raster: attempt", attempt)
            return download_raster_file_once(image)
        except Exception as exc:
            last_error = exc
            print("Raster download failed: attempt", attempt, str(exc))
            if attempt < retries:
                time.sleep_ms(pause_ms)
    raise RuntimeError("Raster download failed: " + str(last_error))


def print_raster_file(raster):
    if not raster:
        return
    path = raster.get("path", "")
    width = int(raster.get("width", 0))
    height = int(raster.get("height", 0))
    expected_bytes = int(raster.get("bytes", 0))
    actual_bytes = int(os.stat(path)[6])
    if actual_bytes != expected_bytes:
        raise RuntimeError(
            "Raster file size changed: " + str(actual_bytes) + "/" + str(expected_bytes)
        )
    width_bytes = (width + 7) // 8
    center()
    header = b"\x1dv0\x00" + bytes((
        width_bytes & 0xFF,
        (width_bytes >> 8) & 0xFF,
        height & 0xFF,
        (height >> 8) & 0xFF,
    ))
    printer.write(header)
    time.sleep_ms(20)
    chunk_size = int(getattr(config, "PRINTER_RASTER_CHUNK_BYTES", 512))
    delay_ms = int(getattr(config, "PRINTER_RASTER_CHUNK_DELAY_MS", 12))
    sent = 0
    with open(path, "rb") as raster_file:
        while sent < expected_bytes:
            chunk = raster_file.read(min(chunk_size, expected_bytes - sent))
            if not chunk:
                break
            printer.write(chunk)
            sent += len(chunk)
            time.sleep_ms(delay_ms)
    if sent != expected_bytes:
        raise RuntimeError("Incomplete raster print: " + str(sent) + "/" + str(expected_bytes))
    left()
    write("\n")


def print_card(card):
    printer_init()
    styles = card.get("styles") or {}
    title_style = styles.get("title", {})
    body_style = styles.get("body", styles.get("text", {}))
    footer_style = styles.get("footer", {})
    has_image = bool(card.get("image_raster") or card.get("image_raster_stream"))

    title = card.get("title")
    if title:
        print_text_part(title, title_style, config.TITLE_TEXT_COLUMNS)
        if not card.get("compact_title_spacing"):
            write("\n")
        if has_image:
            feed_dots(card.get("title_image_gap_dots", 0))

    print_raster_image(card.get("image_raster"))
    raster_stream = card.get("image_raster_stream")
    if raster_stream:
        print_raster_file(download_raster_file(raster_stream))
    if has_image:
        feed_dots(card.get("image_text_gap_dots", 0))

    body = card.get("body") or card.get("text")
    if body:
        print_text_part(body, body_style, config.PRINTER_TEXT_COLUMNS)

    for part in card.get("text_parts") or []:
        if part.get("blank_before"):
            write("\n")
        part_style = dict(body_style)
        part_style.update(part.get("style") or {})
        print_text_part(part.get("text", ""), part_style, config.PRINTER_TEXT_COLUMNS)

    qr_url = card.get("qr_url")
    if qr_url and config.PRINT_NATIVE_QR:
        write("\n")
        print_qr(qr_url)

    footer = card.get("footer")
    if footer:
        write("\n")
        print_text_part(footer, footer_style, config.PRINTER_TEXT_COLUMNS)

    if card.get("show_divider"):
        write("\n" + config.DIVIDER + "\n")
    feed()
    cut_if_available()


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    try:
        wlan.disconnect()
    except Exception:
        pass
    try:
        wlan.active(False)
        time.sleep_ms(250)
    except Exception:
        pass
    wlan.active(True)
    try:
        wlan.config(dhcp_hostname=getattr(config, "WIFI_HOSTNAME", "love-adventure-unit"))
    except Exception:
        pass

    retries = int(getattr(config, "WIFI_RETRY_COUNT", 3))
    for attempt in range(1, max(1, retries) + 1):
        if wlan.isconnected():
            break
        print("Connecting to Wi-Fi:", config.WIFI_SSID, "attempt", attempt)
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        deadline = time.ticks_add(time.ticks_ms(), int(getattr(config, "WIFI_CONNECT_TIMEOUT_MS", 20000)))
        while not wlan.isconnected() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            led(not (status_led and status_led.value()))
            time.sleep_ms(150)
        if not wlan.isconnected():
            try:
                print("Wi-Fi status:", wlan.status())
            except Exception:
                pass
            try:
                wlan.disconnect()
            except Exception:
                pass
            time.sleep_ms(int(getattr(config, "WIFI_RETRY_PAUSE_MS", 700)))

    led(wlan.isconnected())
    if wlan.isconnected():
        time.sleep_ms(int(getattr(config, "WIFI_STABILIZE_MS", 400)))
        apply_dns_override(wlan)
        print("Connected:", wlan.ifconfig())
    else:
        print("Wi-Fi connection failed")
    return wlan


def apply_dns_override(wlan):
    dns_server = getattr(config, "DNS_SERVER", "8.8.8.8")
    if not dns_server:
        return
    try:
        ip, subnet, gateway, dns = wlan.ifconfig()
        if dns != dns_server:
            wlan.ifconfig((ip, subnet, gateway, dns_server))
            print("DNS set to:", dns_server)
    except Exception as exc:
        print("DNS override failed:", exc)


def app_host():
    url = config.APP_BASE_URL.strip()
    if "://" in url:
        url = url.split("://", 1)[1]
    return url.split("/", 1)[0].split(":", 1)[0]


def network_report(wlan):
    lines = []
    try:
        ip, subnet, gateway, dns = wlan.ifconfig()
        lines.append("IP: " + str(ip))
        lines.append("Gateway: " + str(gateway))
        lines.append("DNS: " + str(dns))
    except Exception as exc:
        lines.append("ifconfig error: " + str(exc))

    host = app_host()
    lines.append("Host: " + host)
    try:
        addr = socket.getaddrinfo(host, 443)[0][-1][0]
        lines.append("DNS lookup: OK")
        lines.append("Host IP: " + str(addr))
    except Exception as exc:
        lines.append("DNS lookup: FAILED")
        lines.append("DNS error: " + str(exc))
    return "\n".join(lines)


def fast_button_sample_ms():
    return int(getattr(config, "BUTTON_FAST_SAMPLE_MS", min(getattr(config, "BUTTON_SAMPLE_MS", 25), 5)))


def fast_button_debounce_ms():
    return int(getattr(config, "BUTTON_FAST_DEBOUNCE_MS", min(getattr(config, "BUTTON_DEBOUNCE_MS", 120), 25)))


def wait_for_button_release():
    while button.value() == 0:
        time.sleep_ms(fast_button_sample_ms())


def wait_for_press():
    while True:
        if button.value() == 0:
            time.sleep_ms(fast_button_debounce_ms())
            if button.value() == 0:
                wait_for_button_release()
                return
        time.sleep_ms(fast_button_sample_ms())


def button_pressed():
    global button_event
    if button_event:
        button_event = False
        if button.value() == 0:
            wait_for_button_release()
        return True
    if button.value() == 0:
        time.sleep_ms(fast_button_debounce_ms())
        if button.value() == 0:
            wait_for_button_release()
            return True
    return False


def print_status_card(message):
    print_card({
        "title": "PRINTER STATUS",
        "body": message,
        "footer": "Device: " + config.DEVICE_ID,
    })


def print_unit_message(message):
    print_card({
        "title": "",
        "body": message,
        "footer": "",
    })


def post_json(path, payload):
    url = config.APP_BASE_URL.rstrip("/") + path
    headers = {"Content-Type": "application/json"}
    response = None
    try:
        try:
            socket.setdefaulttimeout(int(getattr(config, "HTTP_TIMEOUT_SECONDS", 4)))
        except Exception:
            pass
        print("POST:", url)
        response = urequests.post(url, data=json.dumps(payload), headers=headers)
        status_code = getattr(response, "status_code", 0)
        try:
            data = response.json()
        except Exception as exc:
            data = {"detail": "Invalid JSON response: " + str(exc)}
        return {
            "ok": 200 <= int(status_code) < 300,
            "status_code": status_code,
            "data": data,
        }
    finally:
        if response:
            response.close()


def device_payload(status=None, message=None):
    payload = {
        "device_id": config.DEVICE_ID,
        "secret": config.DEVICE_SECRET,
    }
    if status:
        payload["status"] = status
    if message:
        payload["message"] = message
    return payload


def control_payload(status="controls", message=None, lite=False):
    payload = device_payload(status, message)
    payload["settings"] = read_control_settings()
    payload["player_count"] = read_player_count()
    if lite:
        payload["lite"] = True
    return payload


def short_detail(data):
    if isinstance(data, dict):
        detail = data.get("detail") or data.get("error") or data.get("message")
        if detail:
            return str(detail)
    return str(data)[:160]


def app_status_accepted(result):
    if not result.get("ok"):
        return False
    data = result.get("data")
    if isinstance(data, dict) and data.get("ok") is False:
        return False
    return True


def check_app_status(status="online", message=None):
    path = getattr(config, "STATUS_ENDPOINT", "/api/device/status")
    return post_json(path, device_payload(status, message))


def post_control_status(status="controls", message="Live controls", lite=False):
    path = getattr(config, "STATUS_ENDPOINT", "/api/device/status")
    return post_json(path, control_payload(status, message, lite))


def sanity_challenge():
    return config.DEVICE_ID + "-" + str(time.ticks_ms())


def check_device_sanity():
    protocol_version = int(getattr(config, "PROTOCOL_VERSION", 1))
    challenge = sanity_challenge()
    path = getattr(config, "SANITY_ENDPOINT", "/api/device/sanity")
    result = post_json(path, {
        "device_id": config.DEVICE_ID,
        "secret": config.DEVICE_SECRET,
        "protocol_version": protocol_version,
        "challenge": challenge,
        "settings": read_control_settings(),
        "player_count": read_player_count(),
    })
    data = result.get("data")
    accepted = (
        result.get("ok")
        and isinstance(data, dict)
        and data.get("ok") is True
        and data.get("protocol_version") == protocol_version
        and data.get("challenge") == challenge
    )
    return accepted, result


def run_startup_sanity_check():
    retries = max(1, int(getattr(config, "SANITY_RETRY_COUNT", 3)))
    pause_ms = int(getattr(config, "SANITY_RETRY_PAUSE_MS", 750))
    for attempt in range(1, retries + 1):
        try:
            accepted, result = check_device_sanity()
            if accepted:
                print("Startup sanity check successful on attempt", attempt)
                return True
            print(
                "Startup sanity check failed:",
                "attempt", attempt,
                "HTTP", result.get("status_code"),
                short_detail(result.get("data")),
            )
        except Exception as exc:
            print("Startup sanity check error: attempt", attempt, str(exc))
        if attempt < retries:
            time.sleep_ms(pause_ms)
    return False


def wait_for_press_with_live_controls(wlan):
    live_enabled = bool(getattr(config, "LIVE_CONTROL_STATUS_ENABLED", True))
    interval = max(int(getattr(config, "CONTROL_STATUS_INTERVAL_MS", 500)), int(getattr(config, "CONTROL_STATUS_MIN_INTERVAL_MS", 1500)))
    next_status_at = time.ticks_ms()
    while True:
        if button_pressed():
            return wlan

        if live_enabled and wlan.isconnected() and time.ticks_diff(time.ticks_ms(), next_status_at) >= 0:
            try:
                result = post_control_status()
                data = result.get("data")
                if not app_status_accepted(result):
                    print("Control status failed:", result.get("status_code"), short_detail(data))
                elif isinstance(data, dict):
                    card = data.get("card")
                    if card:
                        print_card(card)
            except Exception as exc:
                print("Control status error:", exc)
            next_status_at = time.ticks_add(time.ticks_ms(), interval)

        if not wlan.isconnected():
            wlan = connect_wifi()
            next_status_at = time.ticks_ms()

        time.sleep_ms(fast_button_sample_ms())


def main():
    time.sleep_ms(config.POWER_UP_DELAY_MS)
    printer_init()
    wlan = connect_wifi()
    if config.PRINT_STARTUP_CARD:
        successful = False
        if wlan.isconnected():
            successful = run_startup_sanity_check()
            if not successful:
                print(network_report(wlan))
        else:
            print("Startup Wi-Fi failed")
        print_unit_message("SUCCESSFUL" if successful else "FAILED")

    while True:
        print("Waiting for START/NEXT...")
        wlan = wait_for_press_with_live_controls(wlan)
        if not wlan.isconnected():
            wlan = connect_wifi()
        if not wlan.isconnected():
            print_status_card("No Wi-Fi. Cannot reach game app.")
            continue

        led(False)
        try:
            settings = read_control_settings()
            player_count = read_player_count()
            result = post_json(config.NEXT_ENDPOINT, {
                "device_id": config.DEVICE_ID,
                "secret": config.DEVICE_SECRET,
                "button": "START/NEXT",
                "settings": settings,
                "player_count": player_count,
            })
            data = result.get("data")
            card = data.get("card") if isinstance(data, dict) else None
            no_print = bool(isinstance(data, dict) and data.get("no_print"))
            if result.get("ok") and card:
                print_card(card)
            elif result.get("ok") and no_print:
                print("No print:", data.get("reason", "app requested silence"))
            else:
                print_status_card(
                    "No card returned by app."
                    + "\nHTTP: " + str(result.get("status_code"))
                    + "\nDetail: " + short_detail(data)
                )
        except Exception as exc:
            print("App request failed:", exc)
            print_status_card(
                "App request failed. Try again."
                + "\n" + network_report(wlan)
                + "\nError: " + str(exc)[:120]
            )
        finally:
            led(True)
            gc.collect()
            time.sleep_ms(int(getattr(config, "AFTER_REQUEST_FAST_PAUSE_MS", min(getattr(config, "AFTER_REQUEST_PAUSE_MS", 500), 50))))


main()
