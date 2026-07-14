# Love Adventure V2

Love Adventure V2 is the online controller for a live thermal-printer storytelling game. The Render app is the source of truth for game progress. The browser controller, dashboard, and ESP32 printer unit all talk to the same hosted app state.

Live links:

- Controller: `https://v2-i64p.onrender.com/`
- Game-master dashboard: `https://v2-i64p.onrender.com/dashboard`
- GitHub repo: `https://github.com/pbizeh/V2`
- Render service: project `V2`, environment `Production`, service `V2`

## Current Game Flow

The active flow is stored in `game_config.json` under `scenario_steps`. `Scenarios.xlsx` is reference only and is not read by the app.

The current configured flow has 23 steps:

1. Welcome card.
2. First-captain instructions.
3. Jim and Julia intro card.
4. Static Jim persona card.
5. Static Julia persona card.
6. First Round Setup.
7. N generated player persona cards.
8. `A night at the bar`.
9. Storytelling instructions.
10. Vote setup.
11. N ballot cards.
12. Voting instructions.
13. Story submission QR card.
14. Submission gate until the winner submits the story.
15. Round 2 captain setup.
16. N generated Round 2 persona cards.
17. Generated Round 2 title.
18. Generated Round 2 story.
19. Round 2 vote cards.
20. Round 2 voting instructions.
21. Round 2 QR placeholder step.
22. Round 3 placeholder.
23. Round 4 placeholder.

The first button press locks the player count for that game and starts preparing the first generated persona batch in the background. Later changes to the player switch do not change the locked player count for the active game.

If the game reaches a generated card that is not ready yet, it prints the configured patience card and does not advance. While waiting, further button presses do nothing. When the cards are ready, the app prints the configured ready notice and the next button press resumes normal play.

## Controller

The main controller page has:

- one `START/NEXT` button
- player count input
- three 1-100 controls: `AGE`, `QUEERNESS`, and `DIVERSITY`
- the most recent print preview
- a feed of previous print previews below it
- live hardware status/control text when the ESP32 checks in

Every browser `START/NEXT` press sends the current player/settings values to the server, advances the game, creates the next printable card, and stores that print in the shared game state.

## Dashboard

The dashboard is for the game master. It shows:

- game id
- progress and press count
- player count
- whether `OPENAI_API_KEY` is configured
- current `AGE`, `QUEERNESS`, and `DIVERSITY`
- printer-unit status
- next scenario step
- last print
- generated persona names
- story submission values
- recent print log
- reset controls

Reset is only available from the dashboard. Restarting or power-cycling the ESP32 does not reset the game.

## How Everything Connects

```text
GitHub repo pbizeh/V2
        |
        | Render deploys main branch
        v
Render web app https://v2-i64p.onrender.com
        |
        | Browser controller and dashboard use /api/state, /api/next, /api/reset
        | ESP32 uses /api/device/status and /api/device/next
        v
Shared game state + print feed + printable card JSON
        |
        v
Thermal printer output
```

The ESP32 printer unit does not need a computer connection during play. It only needs power, Wi-Fi, the physical controls, and the thermal printer.

## Important Files

- `app.py` - FastAPI app deployed on Render.
- `game_config.json` - editable game flow, prompts, static text, AI settings, thermal profile, and fallback data.
- `main.py` - MicroPython firmware to copy to the ESP32 as `main.py`.
- `config.py` - MicroPython hardware/Wi-Fi/printer settings to copy to the ESP32 as `config.py`.
- `requirements.txt` - Render Python dependencies.
- `render.yaml` - Render blueprint/reference config.
- `static/personas/*` - static Jim and Julia thermal images/raster payloads.
- `Gameplay/Scenarios.xlsx` - local reference only, not used by the app.

## Editable App Config

Most gameplay editing should happen in `game_config.json`.

Useful keys:

- `scenario_steps` - ordered game flow. `START/NEXT` advances through this list.
- `default_player_count` - initial player count before hardware or browser input.
- `default_settings` - initial `AGE`, `QUEERNESS`, and `DIVERSITY`.
- `print_profile` - 58mm thermal paper profile and print-preview rules.
- `print_text_styles` - title/body/footer font sizing and alignment.
- `print_content` - shared generated-card labels, default titles, vote text, and footer templates.
- `raster_policy` - text stays native printer text, QR stays native printer QR, only image content is raster.
- `static_personas` - Jim and Julia cards.
- `persona_name_pool`, `persona_traits`, `persona_gender_pool`, `persona_sexuality_pool` - fallback persona generation data.
- `desire_templates` - fallback desires for generated persona cards.
- `openai` - model names, timeouts, temperature, and system prompt.
- `prompts` - all editable AI prompts.
- `patience_card_text` - printed when a required generated card is not ready.
- `ready_notice_card_text` - printed when waiting generated cards are ready.
- `story_submission_apology_text` - printed while the game waits for a story portal submission.
- `device_secret` - fallback ESP32 shared secret if Render `DEVICE_SECRET` is not set.

Prompt templates may use values such as:

```text
{age}
{queerness}
{diversity}
{player_count}
{persona_list}
{count}
{index}
{avoid_names}
```

## OpenAI

The app can run without OpenAI by using configured fallback data, but generated cards and generated round text are better when `OPENAI_API_KEY` is set.

Add the key in Render, not in GitHub:

1. Open Render.
2. Open project `V2`.
3. Open service `V2`.
4. Go to **Environment**.
5. Add:

```text
Key: OPENAI_API_KEY
Value: your OpenAI API key
```

6. Save changes.
7. Redeploy if Render does not do it automatically.

The dashboard shows `OpenAI Key: Set` when the variable exists. It never displays the key value.

## Device Secret

The ESP32 and the Render app must share the same secret.

On Render service `V2` -> **Environment**, add:

```text
Key: DEVICE_SECRET
Value: the same value used in ESP32 config.py
```

If Render `DEVICE_SECRET` is not set, the app falls back to `device_secret` in `game_config.json`.

## Print Rules

The app is designed around 58mm thermal paper.

- Text cards are native printer text.
- QR codes use the printer's native QR command.
- Only persona images are raster payloads.
- The browser preview mimics narrow thermal paper using the configured print profile.
- Title/body/footer font sizes are controlled by `game_config.json` for the app preview and by ESP32 `config.py` for physical output.

## Story Portal

The Round 1 QR card links to:

```text
/portal/{game_id}/01
```

The portal is a one-time story submission page for the round winner. It asks for:

- winning character name, chosen from the generated personas for that round
- what happened, up to 1000 characters

After submission, the app stores:

- `Character_winner_01`
- `Story_01`
- `story_submissions["01"]`

Until the submission is complete, the next `START/NEXT` press prints:

```text
Sorry, but you should first submit the story.
```

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

To deploy code updates:

```powershell
cd C:\Users\Pooyan\Desktop\HPCodex\V2
git add .
git commit -m "Describe the change"
git push
```

If Render does not auto-deploy, use Render service `V2` -> **Manual Deploy** -> **Deploy latest commit**.

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
- `POST /api/device/status` - ESP32 health/control check-in. It can also deliver a ready notice card.
- `POST /api/device/sanity` - startup challenge-response check for Wi-Fi, app, authentication, protocol, and physical controls.
- `GET /api/device/raster/{game_id}/{presses}` - authenticated binary persona-image stream for the ESP32.
- `GET /portal/{game_id}/{step}` - story portal form.
- `POST /portal/{game_id}/{step}` - story portal submission.

Example browser advance request:

```json
{
  "settings": {
    "age": 50,
    "queerness": 50,
    "diversity": 50
  },
  "player_count": 4
}
```

Example ESP32 response shape:

```json
{
  "card": {
    "title": "A night at the bar",
    "body": "Text to print",
    "footer": "",
    "qr_url": "https://v2-i64p.onrender.com/portal/abcd1234/01"
  },
  "print": {
    "title": "A night at the bar",
    "preview": "Printer-style text preview"
  },
  "state": {
    "cursor": 8,
    "total_steps": 23,
    "presses": 8
  }
}
```

## ESP32 Setup

Before copying files to the ESP32, edit `config.py`:

```python
WIFI_SSID = "Your Wi-Fi or phone hotspot"
WIFI_PASSWORD = "Your Wi-Fi password"
APP_BASE_URL = "https://v2-i64p.onrender.com"
DEVICE_SECRET = "same value as Render DEVICE_SECRET or game_config.json device_secret"
```

Copy these files to the MicroPython device:

1. `main.py`
2. `config.py`

Wire the thermal printer UART:

| ESP32 | Printer |
| --- | --- |
| GPIO17 / TX | RXD |
| GPIO18 / RX | TXD |
| GND | GND |

Wire the physical `START/NEXT` button between GPIO4 and GND.

Important: the button must use `GPIO4 / IO4`, not `EN`, `RST`, `BOOT`, `3V3`, `5V`, or `VIN`. If pressing `START/NEXT` prints the startup status card again, the ESP32 is rebooting and the button is wired to reset/power instead of GPIO4.

## Physical Controls

Wire the 3-position player-count switch as an `ON-OFF-ON` switch:

| Switch Leg | ESP32 |
| --- | --- |
| Center/common | GND |
| Outer leg A | GPIO15 |
| Outer leg B | GPIO16 |

The current firmware reads this as:

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

The reserved potentiometer is configured in ESP32 `config.py`, but it is not sent to the app yet.

Board warning: on many classic ESP32 boards, GPIO6-11 are connected to flash memory and cannot be used for pots. If your board is a classic ESP32, move the pot wipers to ADC1 pins such as GPIO32, GPIO33, GPIO34, and GPIO35, then update `POT_CONTROLS` in `config.py`. If your board is ESP32-S3-style and GPIO5-8 are exposed ADC pins, the table above is fine.

The ESP32 sends live control updates to `/api/device/status` while it waits for `START/NEXT`. The main page polls `/api/state`, so physical knob/switch changes should appear online without advancing the game. The locked player count rule still applies after the first game press.

## Hardware Flow

1. ESP32 boots and prints a startup status card.
2. ESP32 connects to Wi-Fi.
3. ESP32 sends a challenge-response startup check to `/api/device/sanity`.
4. While waiting for the button, ESP32 keeps sending live controls to `/api/device/status`.
5. When the physical button is pressed, ESP32 reads controls and posts to `/api/device/next`.
6. The Render app advances the shared game state.
7. ESP32 receives one card JSON.
8. ESP32 prints the card.

## Hardware Troubleshooting

The startup status card is the first thing to read.

The startup card prints only:

```text
SUCCESSFUL
```

This means Wi-Fi, HTTPS, the Render app, the device secret, the firmware protocol version, the response challenge, and the physical control readings all passed. The unit makes up to three attempts before printing `FAILED`. Detailed failure information is written to the ESP32 serial console and the dashboard hardware status.

If startup says:

```text
FAILED
```

inspect the ESP32 serial console and dashboard. Typical causes are Wi-Fi/DNS failure, an unreachable app, a mismatched `DEVICE_SECRET`, or a mismatched `PROTOCOL_VERSION`.

Button test on the ESP32:

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

Dashboard hardware meanings:

- `Status: sanity_successful` means the startup handshake passed.
- `Status: sanity_failed` means the app received but rejected the startup handshake.
- `Status: controls` means live hardware control updates are reaching the app.
- `Status: next` means the physical button advanced the game.
- `Accepted: no` means the device secret was rejected.

## Notes

- Do not commit API keys.
- `Scenarios.xlsx` is not connected to the app.
- The online state is stored in `game_state.json` on the Render instance. Free Render instances may reset local disk state when redeployed or restarted.
- All current app prompts live in `game_config.json`.
- All current ESP32 printer, Wi-Fi, button, switch, and potentiometer settings live in `config.py`.
