# Love Adventure V2

V2 is a hosted game controller plus an internet-connected ESP32 thermal-printer unit.

The game flow comes from `scenario_steps` in `game_config.json`. Each START/NEXT press advances to the next config entry. `Gameplay/Scenarios.xlsx` is reference only and is not read by the app. The hosted app returns one printable card as JSON. The ESP32 calls the app over Wi-Fi and prints the card directly, so the printer unit does not need a computer connection during play.

## Files

- `app.py` - FastAPI web app for Render.
- `game_config.json` - editable scenario steps, prompts, instructions, device secret, defaults, and generated-card text.
- `main.py` - copy this to the ESP32 as `main.py`.
- `config.py` - copy this to the ESP32 as `config.py` after editing Wi-Fi, Render URL, and printer settings.
- `requirements.txt` - Python dependencies for Render.
- `render.yaml` - optional Render blueprint.

## Run Locally

```powershell
cd C:\Users\Pooyan\Desktop\HPCodex\V2
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Push To GitHub

This folder is set up as a Git repo for `pbizeh/V2`.

```powershell
cd C:\Users\Pooyan\Desktop\HPCodex\V2
git init
git add .
git commit -m "Add Love Adventure V2 web app and ESP32 firmware"
git branch -M main
git remote add origin https://github.com/pbizeh/V2.git
git push -u origin main
```

## Deploy On Render

1. In Render, choose **New** then **Web Service**.
2. Connect the `pbizeh/V2` GitHub repo.
3. Use these settings:
   - Runtime: `Python`
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Open the Render service's **Environment** page.
5. Add your OpenAI key:
   - Key: `OPENAI_API_KEY`
   - Value: paste your OpenAI API key
   - Click **Save Changes**.
   - Render will redeploy or ask you to redeploy. Let it redeploy.
6. After deploy, copy the Render URL.
7. Edit `game_config.json`:
   - set `public_app_url` to the Render URL
   - set `device_secret` to a private shared secret
8. Edit ESP32 `config.py`:
   - set `APP_BASE_URL` to the Render URL
   - set `DEVICE_SECRET` to the same value as `game_config.json`

The game-master dashboard is available at:

```text
/dashboard
```

For example:

```text
https://your-render-app-name.onrender.com/dashboard
```

The dashboard shows progress, next step, last printed card, recent print log, player count, generated persona names, and whether `OPENAI_API_KEY` is set. It never displays the key itself.

## ESP32 Setup

In Thonny, copy these two files to the MicroPython device:

1. `main.py`
2. `config.py`

Wire the thermal printer UART:

| ESP32 | Printer |
| --- | --- |
| GPIO17 / TX | RXD |
| GPIO18 / RX | TXD |
| GND | GND |

Wire the START/NEXT button between GPIO4 and GND.

The ESP32 posts to:

```text
/api/device/next
```

The app responds with:

```json
{
  "card": {
    "title": "Round 1: Story",
    "body": "Text to print",
    "footer": "Step 5 | START/NEXT",
    "qr_url": "https://example.com/portal/..."
  }
}
```

All printer tuning values live in ESP32 `config.py`.
