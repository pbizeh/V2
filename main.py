import gc
import time
import json
import network
import socket
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

player_switch_a = Pin(getattr(config, "PLAYER_SWITCH_PIN_A", 15), Pin.IN, Pin.PULL_UP)
player_switch_b = Pin(getattr(config, "PLAYER_SWITCH_PIN_B", 16), Pin.IN, Pin.PULL_UP)

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
    if bool(getattr(config, "POT_REVERSE", False)):
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
    if left_active and not right_active:
        return int(getattr(config, "PLAYER_SWITCH_VALUE_A", 4))
    if right_active and not left_active:
        return int(getattr(config, "PLAYER_SWITCH_VALUE_B", 6))
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


def wrap_line(line, width):
    words = line.split()
    out = []
    current = ""
    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            out.append(current)
            current = word
    if current:
        out.append(current)
    return out or [""]


def print_wrapped(text, width=None):
    width = int(width or config.PRINTER_TEXT_COLUMNS)
    for raw in normalize_text(text).split("\n"):
        for line in wrap_line(raw, width):
            write(line + "\n")


def print_card(card):
    printer_init()
    center()
    bold(True)
    size(config.TITLE_WIDTH, config.TITLE_HEIGHT)
    print_wrapped(card.get("title", config.DEFAULT_CARD_TITLE), config.TITLE_TEXT_COLUMNS)
    size(1, 1)
    bold(False)
    left()
    write(config.DIVIDER + "\n")

    body = card.get("body") or card.get("text") or ""
    print_wrapped(body)

    footer = card.get("footer")
    if footer:
        write("\n")
        print_wrapped(footer)

    qr_url = card.get("qr_url")
    if qr_url and config.PRINT_NATIVE_QR:
        write("\n")
        print_qr(qr_url)

    write("\n" + config.DIVIDER + "\n")
    feed()
    cut_if_available()


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to Wi-Fi:", config.WIFI_SSID)
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        deadline = time.ticks_add(time.ticks_ms(), config.WIFI_CONNECT_TIMEOUT_MS)
        while not wlan.isconnected() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            led(not (status_led and status_led.value()))
            time.sleep_ms(300)
    led(wlan.isconnected())
    if wlan.isconnected():
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


def wait_for_button_release():
    while button.value() == 0:
        time.sleep_ms(config.BUTTON_SAMPLE_MS)
    time.sleep_ms(config.BUTTON_DEBOUNCE_MS)


def wait_for_press():
    while True:
        if button.value() == 0:
            time.sleep_ms(config.BUTTON_DEBOUNCE_MS)
            if button.value() == 0:
                wait_for_button_release()
                return
        time.sleep_ms(config.BUTTON_SAMPLE_MS)


def button_pressed():
    if button.value() == 0:
        time.sleep_ms(config.BUTTON_DEBOUNCE_MS)
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


def post_json(path, payload):
    url = config.APP_BASE_URL.rstrip("/") + path
    headers = {"Content-Type": "application/json"}
    response = None
    try:
        print("POST:", url)
        response = urequests.post(url, data=json.dumps(payload), headers=headers)
        status_code = getattr(response, "status_code", 0)
        try:
            data = response.json()
        except Exception:
            data = {"detail": getattr(response, "text", "")}
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


def control_payload(status="controls", message=None):
    payload = device_payload(status, message)
    payload["settings"] = read_control_settings()
    payload["player_count"] = read_player_count()
    return payload


def short_detail(data):
    if isinstance(data, dict):
        detail = data.get("detail") or data.get("error") or data.get("message")
        if detail:
            return str(detail)
    return str(data)[:160]


def check_app_status(status="online", message=None):
    path = getattr(config, "STATUS_ENDPOINT", "/api/device/status")
    return post_json(path, device_payload(status, message))


def post_control_status(status="controls", message="Live controls"):
    path = getattr(config, "STATUS_ENDPOINT", "/api/device/status")
    return post_json(path, control_payload(status, message))


def wait_for_press_with_live_controls(wlan):
    live_enabled = bool(getattr(config, "LIVE_CONTROL_STATUS_ENABLED", True))
    interval = int(getattr(config, "CONTROL_STATUS_INTERVAL_MS", 500))
    next_status_at = time.ticks_ms()
    while True:
        if button_pressed():
            return wlan

        if live_enabled and wlan.isconnected() and time.ticks_diff(time.ticks_ms(), next_status_at) >= 0:
            try:
                result = post_control_status()
                data = result.get("data")
                if not (result.get("ok") and isinstance(data, dict) and data.get("ok")):
                    print("Control status failed:", result.get("status_code"), short_detail(data))
            except Exception as exc:
                print("Control status error:", exc)
            next_status_at = time.ticks_add(time.ticks_ms(), interval)

        if not wlan.isconnected():
            wlan = connect_wifi()
            next_status_at = time.ticks_ms()

        time.sleep_ms(config.BUTTON_SAMPLE_MS)


def main():
    time.sleep_ms(config.POWER_UP_DELAY_MS)
    printer_init()
    wlan = connect_wifi()
    if config.PRINT_STARTUP_CARD:
        status = "Online. Press START/NEXT." if wlan.isconnected() else "No Wi-Fi. Check config.py."
        status += "\nReset cause: " + str(reset_cause())
        status += "\nBoot ms: " + str(boot_ms)
        if wlan.isconnected():
            status += "\n" + network_report(wlan)
            try:
                result = post_control_status("startup", "Startup check")
                data = result.get("data")
                if result.get("ok") and isinstance(data, dict) and data.get("ok"):
                    state = data.get("state") or {}
                    status += "\nApp check: OK"
                    status += "\nProgress: " + str(state.get("cursor")) + "/" + str(state.get("total_steps"))
                else:
                    status += "\nApp check: FAILED"
                    status += "\nHTTP: " + str(result.get("status_code"))
                    status += "\nDetail: " + short_detail(data)
            except Exception as exc:
                status += "\nApp check error: " + str(exc)
        status += "\n" + control_report()
        print_status_card(status)

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
            if result.get("ok") and card:
                print_card(card)
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
            time.sleep_ms(config.AFTER_REQUEST_PAUSE_MS)


main()
