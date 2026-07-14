import time
import network
import socket
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
    timeout=getattr(config, "PRINTER_TIMEOUT_MS", 1000),
)

button = Pin(config.BUTTON_PIN, Pin.IN, Pin.PULL_UP)

switch_a = Pin(getattr(config, "PLAYER_SWITCH_PIN_A", 15), Pin.IN, Pin.PULL_UP)
switch_b = Pin(getattr(config, "PLAYER_SWITCH_PIN_B", 16), Pin.IN, Pin.PULL_UP)

setup_errors = []
pot_adcs = {}


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, int(value)))


def write(data, delay_ms=None):
    if isinstance(data, str):
        data = data.encode("utf-8")
    if data:
        printer.write(data)
        time.sleep_ms(delay_ms if delay_ms is not None else getattr(config, "PRINTER_WRITE_DELAY_MS", 5))


def printer_init():
    write(b"\x1b\x40", 250)
    write(b"\x1b\x37" + bytes((
        clamp(getattr(config, "PRINTER_HEAT_DOTS", 1), 1, 255),
        clamp(getattr(config, "PRINTER_HEAT_TIME", 200), 1, 255),
        clamp(getattr(config, "PRINTER_HEAT_INTERVAL", 40), 1, 255),
    )))
    density = clamp(getattr(config, "PRINTER_DENSITY", 15), 0, 31)
    break_time = clamp(getattr(config, "PRINTER_BREAK_TIME", 4), 0, 7)
    write(b"\x12\x23" + bytes(((break_time << 5) | density,)))
    write(b"\x1b\x61\x00")
    write(b"\x1d\x21\x00")
    write(b"\x1b\x45\x00")


def feed(lines=2):
    write(b"\n" * int(lines), 60)


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
    if getattr(config, "PRINTER_SEND_CUT", False):
        write(b"\x1d\x56\x00", 120)


def clean_text(text):
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
    words = clean_text(line).split()
    lines = []
    current = ""
    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def print_wrapped(text, width=None):
    width = int(width or getattr(config, "PRINTER_TEXT_COLUMNS", 42))
    for raw_line in clean_text(text).split("\n"):
        for line in wrap_line(raw_line, width):
            write(line + "\n")


def print_header(title):
    center()
    bold(True)
    size(2, 2)
    print_wrapped(title, getattr(config, "TITLE_TEXT_COLUMNS", 21))
    size(1, 1)
    bold(False)
    left()


def print_event(title, body="", feed_lines=2):
    printer_init()
    print_header(title)
    if body:
        write("\n")
        print_wrapped(body)
    feed(feed_lines)
    cut_if_available()


def print_line_event(line):
    printer_init()
    print_wrapped(line)
    feed(1)


def adc_read(adc):
    if hasattr(adc, "read_u16"):
        return adc.read_u16()
    return adc.read()


def setup_pots():
    for control in getattr(config, "POT_CONTROLS", []):
        name = str(control.get("name", "pot"))
        pin = control.get("pin")
        try:
            adc = ADC(Pin(pin))
            if hasattr(adc, "atten"):
                adc.atten(getattr(ADC, "ATTN_11DB", 3))
            if hasattr(adc, "width"):
                adc.width(getattr(ADC, "WIDTH_12BIT", 3))
            pot_adcs[name] = adc
        except Exception as exc:
            setup_errors.append("Pot setup failed: " + name + " GPIO" + str(pin) + " " + str(exc))


def read_pot(name):
    adc = pot_adcs.get(name)
    if not adc:
        return None
    samples = int(getattr(config, "POT_SAMPLES", 5))
    total = 0
    for _ in range(max(1, samples)):
        total += int(adc_read(adc))
        time.sleep_ms(int(getattr(config, "POT_SAMPLE_DELAY_MS", 2)))
    raw = total // max(1, samples)
    raw_max = 65535 if raw > 4095 else 4095
    mapped_raw = raw_max - raw if getattr(config, "POT_REVERSE", False) else raw
    percent = 1 + (clamp(mapped_raw, 0, raw_max) * 99) // max(1, raw_max)
    return {"raw": raw, "percent": percent}


def read_all_pots():
    readings = {}
    for name in pot_adcs:
        readings[name] = read_pot(name)
    return readings


def switch_label():
    a_active = switch_a.value() == 0
    b_active = switch_b.value() == 0
    if a_active and not b_active:
        return "A / " + str(getattr(config, "PLAYER_SWITCH_VALUE_A", 4)) + " players"
    if b_active and not a_active:
        return "B / " + str(getattr(config, "PLAYER_SWITCH_VALUE_B", 6)) + " players"
    if a_active and b_active:
        return "BOTH ACTIVE / wiring check"
    return "CENTER / " + str(getattr(config, "PLAYER_SWITCH_CENTER_VALUE", 5)) + " players"


def app_host():
    url = getattr(config, "APP_BASE_URL", "").strip()
    if not url:
        return "example.com"
    if "://" in url:
        url = url.split("://", 1)[1]
    return url.split("/", 1)[0].split(":", 1)[0]


def apply_dns_override(wlan):
    dns_server = getattr(config, "DNS_SERVER", "8.8.8.8")
    if not dns_server:
        return ""
    try:
        ip, subnet, gateway, dns = wlan.ifconfig()
        if dns != dns_server:
            wlan.ifconfig((ip, subnet, gateway, dns_server))
            return "DNS changed to " + dns_server
    except Exception as exc:
        return "DNS change failed: " + str(exc)
    return ""


def check_internet(wlan):
    lines = []
    if not wlan.isconnected():
        lines.append("Wi-Fi: not connected")
        return "\n".join(lines)

    try:
        ip, subnet, gateway, dns = wlan.ifconfig()
        lines.append("Wi-Fi: connected")
        lines.append("IP: " + str(ip))
        lines.append("Gateway: " + str(gateway))
        lines.append("DNS: " + str(dns))
    except Exception as exc:
        lines.append("ifconfig failed: " + str(exc))

    host = app_host()
    lines.append("Internet host: " + host)
    try:
        addr = socket.getaddrinfo(host, 443)[0][-1]
        lines.append("DNS lookup: OK")
        lines.append("Host IP: " + str(addr[0]))
        sock = socket.socket()
        sock.settimeout(5)
        try:
            sock.connect(addr)
            lines.append("TCP 443: OK")
        finally:
            sock.close()
    except Exception as exc:
        lines.append("Internet check failed: " + str(exc))
    return "\n".join(lines)


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        dns_message = apply_dns_override(wlan)
        body = "Already connected.\n" + check_internet(wlan)
        if dns_message:
            body += "\n" + dns_message
        print_event("INTERNET CHECK", body)
        return wlan

    print_event("WIFI", "Connecting to:\n" + str(getattr(config, "WIFI_SSID", "")), 1)
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    deadline = time.ticks_add(time.ticks_ms(), int(getattr(config, "WIFI_CONNECT_TIMEOUT_MS", 20000)))
    dot_count = 0
    while not wlan.isconnected() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
        dot_count += 1
        if dot_count % 5 == 0:
            print_line_event("Wi-Fi still connecting...")
        time.sleep_ms(500)

    dns_message = apply_dns_override(wlan)
    body = check_internet(wlan)
    if dns_message:
        body += "\n" + dns_message
    print_event("INTERNET CHECK", body)
    return wlan


def startup_report(wlan):
    body = "Reset cause: " + str(reset_cause())
    body += "\nButton GPIO: " + str(config.BUTTON_PIN)
    body += "\nSwitch GPIOs: " + str(getattr(config, "PLAYER_SWITCH_PIN_A", 15))
    body += ", " + str(getattr(config, "PLAYER_SWITCH_PIN_B", 16))
    body += "\nSwitch: " + switch_label()
    if pot_adcs:
        readings = read_all_pots()
        for name in readings:
            reading = readings[name]
            body += "\n" + name.upper() + ": " + str(reading["percent"]) + "% raw " + str(reading["raw"])
    else:
        body += "\nNo pots configured."
    if setup_errors:
        body += "\n\nSETUP ERRORS:"
        for error in setup_errors:
            body += "\n" + error
    body += "\n\n" + check_internet(wlan)
    print_event("HARDWARE CHECK", body)


def button_was_pressed():
    if button.value() != 0:
        return False
    time.sleep_ms(int(getattr(config, "BUTTON_DEBOUNCE_MS", 120)))
    if button.value() != 0:
        return False
    while button.value() == 0:
        time.sleep_ms(int(getattr(config, "BUTTON_SAMPLE_MS", 25)))
    time.sleep_ms(int(getattr(config, "BUTTON_DEBOUNCE_MS", 120)))
    return True


def print_pot_change(name, old_reading, new_reading):
    body = name.upper() + " knob turned"
    body += "\nNow: " + str(new_reading["percent"]) + "%"
    body += "\nRaw: " + str(new_reading["raw"])
    if old_reading:
        body += "\nWas: " + str(old_reading["percent"]) + "%"
    print_event("KNOB", body, 1)


def main():
    time.sleep_ms(int(getattr(config, "POWER_UP_DELAY_MS", 1800)))
    printer_init()
    setup_pots()
    wlan = connect_wifi()
    startup_report(wlan)

    last_wifi_connected = wlan.isconnected()
    last_switch = switch_label()
    last_pots = read_all_pots()
    pot_threshold = int(getattr(config, "HARDWARE_CHECK_POT_THRESHOLD", 4))
    next_wifi_check = time.ticks_add(time.ticks_ms(), 10000)

    print_event("READY", "Press button, turn knobs, or move switch.", 2)

    while True:
        if button_was_pressed():
            print_event("BUTTON", "START/NEXT button pressed.", 1)

        current_switch = switch_label()
        if current_switch != last_switch:
            print_event("SWITCH", "Player switch moved.\nNow: " + current_switch + "\nWas: " + last_switch, 1)
            last_switch = current_switch

        current_pots = read_all_pots()
        for name in current_pots:
            old = last_pots.get(name)
            new = current_pots[name]
            if old is None or abs(int(new["percent"]) - int(old["percent"])) >= pot_threshold:
                print_pot_change(name, old, new)
                last_pots[name] = new

        if time.ticks_diff(time.ticks_ms(), next_wifi_check) >= 0:
            wifi_connected = wlan.isconnected()
            if wifi_connected != last_wifi_connected:
                title = "WIFI ONLINE" if wifi_connected else "WIFI LOST"
                print_event(title, check_internet(wlan), 1)
                last_wifi_connected = wifi_connected
            if not wifi_connected:
                wlan = connect_wifi()
                last_wifi_connected = wlan.isconnected()
            next_wifi_check = time.ticks_add(time.ticks_ms(), 10000)

        time.sleep_ms(int(getattr(config, "BUTTON_SAMPLE_MS", 25)))


main()
