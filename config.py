# Copy this file to the ESP32 as config.py.
# Edit the Wi-Fi and app values before uploading.

WIFI_SSID = "Your Wi-Fi or phone hotspot"
WIFI_PASSWORD = "Your Wi-Fi password"

# Render URL after deployment, for example:
# APP_BASE_URL = "https://happy-polycules-v2.onrender.com"
APP_BASE_URL = "https://your-render-app-name.onrender.com"
NEXT_ENDPOINT = "/api/device/next"
DEVICE_ID = "printer-001"
DEVICE_SECRET = "change-this-shared-secret"

# UART wiring: ESP32 GPIO17 TX -> printer RXD, printer TXD -> ESP32 GPIO18 RX.
PRINTER_UART_ID = 1
PRINTER_TX_PIN = 17
PRINTER_RX_PIN = 18
PRINTER_BAUD = 9600
PRINTER_TIMEOUT_MS = 1000

# Button wiring: external START/NEXT button from GPIO4 to GND.
BUTTON_PIN = 4
BUTTON_SAMPLE_MS = 25
BUTTON_DEBOUNCE_MS = 120
POWER_UP_DELAY_MS = 1800
AFTER_REQUEST_PAUSE_MS = 500

# Set to None if your board LED pin is different or unavailable.
STATUS_LED_PIN = 2

# Printer text and feed settings.
PRINTER_TEXT_COLUMNS = 42
TITLE_TEXT_COLUMNS = 21
TITLE_WIDTH = 2
TITLE_HEIGHT = 2
DEFAULT_CARD_TITLE = "LOVE ADVENTURE"
DIVIDER = "--------------------------------"
FEED_LINES_AFTER_CARD = 4
PRINTER_SEND_CUT = False
PRINTER_WRITE_DELAY_MS = 5
PRINT_STARTUP_CARD = True

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
