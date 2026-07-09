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
- `openai.enabled` - set `false` to disable OpenAI calls.
- `openai.text_model` - OpenAI text model.
- `openai.system_prompt` - global AI behavior.
- `prompts.persona_generation` - prompt for persona-card generation.
- `prompts.round_title` - prompt for generated round titles.
- `prompts.round_story` - prompt for generated story setups.
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

All printer tuning values live in ESP32 `config.py`, including baud rate, heat settings, density, line width, feed lines, QR settings, and button timing.

## Current Hardware Flow

The online app is already usable without hardware. It creates and stores print previews in the browser and dashboard.

When hardware is attached:

1. ESP32 connects to Wi-Fi.
2. Physical button is pressed.
3. ESP32 posts to `https://v2-i64p.onrender.com/api/device/next`.
4. Render app advances the same game state.
5. ESP32 receives the next card JSON.
6. ESP32 prints the card on the thermal printer.

## Notes

- `Scenarios.xlsx` is not connected to the app. It is reference only.
- Do not commit API keys.
- The online state is stored in `game_state.json` on the Render instance. Free Render instances may reset local disk state when redeployed or restarted.
- If the dashboard shows `OpenAI Key: Missing`, add `OPENAI_API_KEY` in Render Environment settings.
- If the printer startup card says `App check: FAILED` and `Detail: Bad device secret`, set Render `DEVICE_SECRET` to match ESP32 `config.py`.
- If the printer says Wi-Fi is connected but the dashboard still shows `No device check yet`, check `APP_BASE_URL`, Wi-Fi internet access, and the Render service status.
