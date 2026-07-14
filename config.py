# Copy this file to the ESP32 as config.py.
# Edit the Wi-Fi and app values before uploading.

WIFI_SSID = "Your Wi-Fi or phone hotspot"
WIFI_PASSWORD = "Your Wi-Fi password"

# Render URL after deployment, for example:
# APP_BASE_URL = "https://happy-polycules-v2.onrender.com"
APP_BASE_URL = "https://v2-i64p.onrender.com"
NEXT_ENDPOINT = "/api/device/next"
STATUS_ENDPOINT = "/api/device/status"
SANITY_ENDPOINT = "/api/device/sanity"
DEVICE_ID = "printer-001"
DEVICE_SECRET = "Zorombaad"
PROTOCOL_VERSION = 1
SANITY_RETRY_COUNT = 3
SANITY_RETRY_PAUSE_MS = 750
DNS_SERVER = "8.8.8.8"
WIFI_HOSTNAME = "love-adventure-unit"
WIFI_RETRY_COUNT = 3
WIFI_RETRY_PAUSE_MS = 700
WIFI_STABILIZE_MS = 400

# UART wiring: ESP32 GPIO17 TX -> printer RXD, printer TXD -> ESP32 GPIO18 RX.
PRINTER_UART_ID = 1
PRINTER_TX_PIN = 17
PRINTER_RX_PIN = 18
PRINTER_BAUD = 9600
PRINTER_TIMEOUT_MS = 1000

# Button wiring: external START/NEXT button from GPIO4 to GND.
BUTTON_PIN = 4
BUTTON_SAMPLE_MS = 5
BUTTON_DEBOUNCE_MS = 25
BUTTON_FAST_SAMPLE_MS = 5
BUTTON_FAST_DEBOUNCE_MS = 25
WIFI_CONNECT_TIMEOUT_MS = 20000
POWER_UP_DELAY_MS = 300
AFTER_REQUEST_PAUSE_MS = 50
AFTER_REQUEST_FAST_PAUSE_MS = 50
HTTP_TIMEOUT_SECONDS = 4

# Set to None if your board LED pin is different or unavailable.
STATUS_LED_PIN = 2

# Player-count switch wiring: 3-position ON-OFF-ON switch.
# Center/common leg -> GND.
# One outer leg -> PLAYER_SWITCH_PIN_A. Other outer leg -> PLAYER_SWITCH_PIN_B.
# A active = 6 players, center/off = 5 players, B active = 4 players.
PLAYER_SWITCH_PIN_A = 15
PLAYER_SWITCH_PIN_B = 16
PLAYER_SWITCH_VALUE_A = 6
PLAYER_SWITCH_CENTER_VALUE = 5
PLAYER_SWITCH_VALUE_B = 4
PLAYER_SWITCH_REVERSE = False

# Potentiometer wiring: one outside leg -> 3V3, other outside leg -> GND,
# middle/wiper leg -> configured GPIO. Values are mapped to 1-100.
# Reserved is read by firmware setup but not sent to the app yet.
# If using a classic ESP32, avoid GPIO6-11 and use ADC1 pins such as 32-35.
POT_CONTROLS = [
    {"name": "age", "pin": 5},
    {"name": "queerness", "pin": 6},
    {"name": "diversity", "pin": 7},
    {"name": "reserved", "pin": 8},
]
DEFAULT_CONTROL_SETTINGS = {
    "age": 50,
    "queerness": 50,
    "diversity": 50,
}
POT_SAMPLES = 5
POT_SAMPLE_DELAY_MS = 2
POT_REVERSE = True
POT_REVERSE_OUTPUT = False
LIVE_CONTROL_STATUS_ENABLED = True
CONTROL_STATUS_INTERVAL_MS = 1500
CONTROL_STATUS_MIN_INTERVAL_MS = 1500

# Printer text and feed settings.
PRINTER_TEXT_COLUMNS = 32
TITLE_TEXT_COLUMNS = 16
TITLE_WIDTH = 2
TITLE_HEIGHT = 2
DEFAULT_CARD_TITLE = "LOVE ADVENTURE"
DIVIDER = "--------------------------------"
FEED_LINES_AFTER_CARD = 4
PRINTER_SEND_CUT = False
PRINTER_WRITE_DELAY_MS = 5
PRINT_STARTUP_CARD = True
PRINTER_RASTER_CHUNK_BYTES = 512
PRINTER_RASTER_CHUNK_DELAY_MS = 12
RASTER_CACHE_PATH = "persona_raster.bin"
RASTER_DOWNLOAD_RETRY_COUNT = 3
RASTER_DOWNLOAD_RETRY_PAUSE_MS = 500

# Thermal intensity settings. Keep conservative if power supply is weak.
PRINTER_HEAT_DOTS = 1
PRINTER_HEAT_TIME = 200
PRINTER_HEAT_INTERVAL = 40
PRINTER_DENSITY = 15
PRINTER_BREAK_TIME = 4

# Native QR settings for QR-capable ESC/POS printers.
PRINT_NATIVE_QR = True
QR_MODULE_SIZE = 5
QR_ERROR_CORRECTION = 49
QR_PRINT_DELAY_MS = 400
