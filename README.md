# Love Adventure V2

Love Adventure V2 is an online game controller for a live storytelling card game. The hosted app is the source of truth for game progress. Players or the game master press one `START/NEXT` button, the app advances to the next configured step, generates a printer-style preview, and eventually the ESP32 printer unit will request the same next print over the internet.

Live service:

- Controller: `https://v2-i64p.onrender.com/`
- Game-master dashboard: `https://v2-i64p.onrender.com/dashboard`
- GitHub repo: `https://github.com/pbizeh/V2`
- Render service: project `V2`, environment `Production`, service `V2`

## What The App Does

The controller page has:

- one `START/NEXT` button
- player count
- three 1-100 sliders: `AGE`, `QUEERNESS`, and `DIVERSITY`
- the most recent print preview
- a feed of previous print previews below it

Every `START/NEXT` press:

1. Sends the current slider values to the server.
2. Advances one entry in `game_config.json` under `scenario_steps`.
3. Builds the next printable card.
4. Uses OpenAI for configured generated steps when `OPENAI_API_KEY` is set.
5. Falls back to local configured text if OpenAI is disabled, missing, or fails.
6. Stores the latest print plus a feed of previous prints in game state.

The dashboard page is for the game master. It shows:

- game id
- progress and button press count
- player count
- whether `OPENAI_API_KEY` is configured
- current `AGE`, `QUEERNESS`, and `DIVERSITY`
- next scenario step
- last print preview
- generated persona names
- recent print log
- reset controls

Reset is intentionally only on the dashboard, not on the main controller.

## How Everything Connects

```text
GitHub repo pbizeh/V2
        |
        | Render deploys main branch
        v
Render web service https://v2-i64p.onrender.com
        |
        | Browser users open controller/dashboard
        | ESP32 later calls /api/device/next over Wi-Fi
        v
Game state + print previews + printable card JSON
```

The ESP32 printer unit does not need a computer connection during play. Once `config.py` is updated and copied to the ESP32, it connects to Wi-Fi, waits for the physical `START/NEXT` button, calls the Render app, receives one card, and prints it.

## Important Files

- `app.py` - FastAPI app deployed on Render.
- `game_config.json` - editable game flow, prompts, AI settings, defaults, print formatting, and device secret.
- `main.py` - MicroPython firmware to copy to the ESP32 as `main.py`.
- `config.py` - MicroPython settings to copy to the ESP32 as `config.py`.
- `requirements.txt` - Render Python dependencies.
- `render.yaml` - optional Render blueprint/reference config.
- `Gameplay/Scenarios.xlsx` - local reference only, ignored by Git and not read by the app.

## Configuration

Most game tuning happens in `game_config.json`.

Useful keys:

- `scenario_steps` - the ordered game flow. `START/NEXT` advances one entry at a time.
- `default_player_count` - initial player count.
- `default_settings` - initial `AGE`, `QUEERNESS`, and `DIVERSITY` values.
- `print_preview_columns` - width of online print previews.
- `print_preview_divider` - divider line used in print previews.
- `print_profile` - thermal paper profile: paper width, printable width, text columns, title sizing, divider, and preview notes.
- `raster_policy` - output policy: text stays native printer ASCII, QR stays native printer QR, and only image cards should become 1-bit raster bitmaps.
- `openai.enabled` - set `false` to disable OpenAI calls.
- `openai.text_model` - OpenAI text model.
- `openai.system_prompt` - global AI behavior.
- `prompts.persona_generation` - prompt for persona-card generation.
- `prompts.round_title` - prompt for generated round titles.
- `prompts.round_story` - prompt for generated story setups.
- `prompts.thermal_style` - shared writing rule for compact 58mm thermal-printer text.
- `fallback_round_title` and `fallback_round_story` - used if OpenAI is unavailable.
- `device_secret` - shared secret expected from the ESP32.
- `public_app_url` or `story_portal_base_url` - used for QR/story portal URLs.

Prompt templates may use:

```text
{age}
{queerness}
{diversity}
{player_count}
{persona_list}
{count}
```

## Print Output Rules

The game is designed around 58mm thermal paper.

- Text cards are sent as native printer text, not raster images.
- QR cards use the printer's native QR command.
- Only actual image content should be converted to a 1-bit black-and-white raster bitmap.
- The main controller preview uses the same configured text width as the printer preview, so the on-screen card should feel close to the printed card before paper is used.
- All prompt text and thermal-writing guidance lives in `game_config.json` under `prompts`, `openai.system_prompt`, `print_profile`, and `raster_policy`.

## OpenAI API Key On Render

Add the key in Render, not in GitHub.

1. Open Render.
2. Open project `V2`.
3. Open service `V2`.
4. Go to **Environment**.
5. Add an environment variable:

```text
Key: OPENAI_API_KEY
Value: your OpenAI API key
```

6. Save changes.
7. Redeploy if Render does not do it automatically.

The dashboard shows `OpenAI Key: Set` when the variable exists. It never shows the key value.

## ESP32 Device Secret On Render

The ESP32 and the Render app must share the same device secret. Prefer setting the real value in Render instead of committing it to GitHub.

In Render service `V2` -> **Environment**, add:

```text
Key: DEVICE_SECRET
Value: the same value used in ESP32 config.py
```

If `DEVICE_SECRET` is not set in Render, the app falls back to `device_secret` in `game_config.json`.

## Render Deployment

Current Render settings:

```text
Runtime: Python
Build command: pip install -r requirements.txt
Start command: uvicorn app:app --host 0.0.0.0 --port $PORT
Plan: Free
Project: V2
Environment: Production
Repo: pbizeh/V2
Branch: main
```

To deploy updates:

```powershell
cd C:\Users\Pooyan\Desktop\HPCodex\V2
git add .
git commit -m "Describe the change"
git push
```

Render should deploy the latest commit. If it does not, use Render service `V2` -> **Manual Deploy** -> **Deploy latest commit**.

## Local Development

```powershell
cd C:\Users\Pooyan\Desktop\HPCodex\V2
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/dashboard
```

## Web API

Main endpoints:

- `GET /` - controller page.
- `GET /dashboard` - game-master dashboard.
- `GET /api/state` - current public game state.
- `POST /api/next` - browser controller advances the game.
- `POST /api/reset` - dashboard resets the game.
- `POST /api/device/next` - ESP32 advances the game and receives the next printable card.
- `POST /api/device/status` - ESP32 health check; reports whether the app can be reached and whether the secret is accepted.
- `GET /portal/{game_id}/{step}` - placeholder story portal page for QR cards.

Example browser advance request:

```json
{
  "settings": {
    "age": 50,
    "queerness": 50,
    "diversity": 50
  }
}
```

Example ESP32 response shape:

```json
{
  "card": {
    "title": "Round 1: Story",
    "body": "Text to print",
    "footer": "Step 5 | START/NEXT",
    "qr_url": "https://example.com/portal/..."
  },
  "print": {
    "title": "Round 1: Story",
    "preview": "Printer-style text preview"
  },
  "state": {
    "cursor": 5,
    "total_steps": 25,
    "presses": 5
  }
}
```

## ESP32 Setup

Before copying files to the ESP32, edit `config.py`:

```python
WIFI_SSID = "Your Wi-Fi or phone hotspot"
WIFI_PASSWORD = "Your Wi-Fi password"
APP_BASE_URL = "https://v2-i64p.onrender.com"
DEVICE_SECRET = "same value as device_secret in game_config.json"
```

Copy these files to the MicroPython device in Thonny:

1. `main.py`
2. `config.py`

Wire the thermal printer UART:

| ESP32 | Printer |
| --- | --- |
| GPIO17 / TX | RXD |
| GPIO18 / RX | TXD |
| GND | GND |

Wire the physical `START/NEXT` button between GPIO4 and GND.

Important button note: the button must use `GPIO4 / IO4`, not `EN`, `RST`, `BOOT`, `3V3`, `5V`, or `VIN`. If pressing `START/NEXT` prints the startup `PRINTER STATUS` card again, the ESP32 is rebooting and the button is wired to reset/power instead of GPIO4.

Wire the 3-position player-count switch:

Use a 3-leg `ON-OFF-ON` switch. The center position should connect neither outer leg.

| Switch Leg | ESP32 |
| --- | --- |
| Center/common | GND |
| Outer leg A | GPIO15 |
| Outer leg B | GPIO16 |

The firmware reads this as:

| Switch Position | Player Count |
| --- | --- |
| GPIO15 connected to GND | 4 |
| Center/off | 5 |
| GPIO16 connected to GND | 6 |

Wire the four potentiometers:

| Control | Pot Leg 1 | Pot Middle/Wiper | Pot Leg 3 |
| --- | --- | --- | --- |
| AGE | 3V3 | GPIO5 | GND |
| QUEERNESS | 3V3 | GPIO6 | GND |
| DIVERSITY | 3V3 | GPIO7 | GND |
| RESERVED | 3V3 | GPIO8 | GND |

The reserved potentiometer is wired and readied in `config.py`, but it is not sent to the app yet.

Board warning: on many classic ESP32 boards, GPIO6-11 are connected to flash memory and cannot be used for pots. If your board is a classic ESP32, move the pot wipers to ADC1 pins such as GPIO32, GPIO33, GPIO34, and GPIO35, then update `POT_CONTROLS` in `config.py`. If your board is ESP32-S3-style and GPIO5-8 are exposed ADC pins, the table above is fine.

The ESP32 sends live control updates to `/api/device/status` while it waits for START/NEXT. The main web page polls `/api/state` twice per second, so turning the physical potentiometers or moving the player switch should visibly update the online sliders and player count without advancing the game. These values can change throughout the whole game; the next generated or printed card uses the latest received physical controls.

All printer tuning values live in ESP32 `config.py`, including baud rate, heat settings, density, line width, feed lines, QR settings, and button timing.

## Current Hardware Flow

The online app is already usable without hardware. It creates and stores print previews in the browser and dashboard.

When hardware is attached:

1. ESP32 connects to Wi-Fi.
2. Physical button is pressed.
3. ESP32 reads AGE, QUEERNESS, DIVERSITY, and player count from the physical controls.
4. ESP32 posts to `https://v2-i64p.onrender.com/api/device/next`.
5. Render app advances the same game state using those hardware values.
6. ESP32 receives the next card JSON.
7. ESP32 prints the card on the thermal printer.

## Hardware Troubleshooting

The startup status card is the first thing to read.

Good startup:

```text
Online. Press START/NEXT.
App check: OK
Progress: 0/25
```

This means Wi-Fi, Render, the device endpoint, and the device secret are working. A `DNS lookup: FAILED` line can appear on some MicroPython builds even when the real app request succeeds. Trust `App check: OK`.

Button test:

```python
from machine import Pin
b = Pin(4, Pin.IN, Pin.PULL_UP)
b.value()
```

Expected values:

```text
1 when not pressed
0 when pressed
```

If the value never changes, check the wire to `GPIO4 / IO4` and `GND`. If pressing the button restarts the ESP32 or prints the startup status card again, the button is wired to `EN`, `RST`, `BOOT`, or power instead of `GPIO4`.

Dashboard check:

- `Printer Unit` shows `Status: startup` when the ESP32 boots and checks in.
- `Printer Unit` shows `Status: controls` when live hardware control updates are reaching the app.
- `Printer Unit` shows `Status: next` when the physical button successfully advances the game.
- `Accepted: no` means the ESP32 secret does not match Render/game config.

## Notes

- `Scenarios.xlsx` is not connected to the app. It is reference only.
- Do not commit API keys.
- The online state is stored in `game_state.json` on the Render instance. Free Render instances may reset local disk state when redeployed or restarted.
- If the dashboard shows `OpenAI Key: Missing`, add `OPENAI_API_KEY` in Render Environment settings.
- If the printer startup card says `App check: FAILED` and `Detail: Bad device secret`, set Render `DEVICE_SECRET` to match ESP32 `config.py`.
- If the printer says Wi-Fi is connected but the dashboard still shows `No device check yet`, check `APP_BASE_URL`, Wi-Fi internet access, and the Render service status.
