import json
import os
import random
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.getenv("GAME_CONFIG_PATH", BASE_DIR / "game_config.json"))
STATE_PATH = Path(os.getenv("GAME_STATE_PATH", BASE_DIR / "game_state.json"))


app = FastAPI(title="Love Adventure V2")


class DeviceNext(BaseModel):
    device_id: str = "printer-001"
    secret: str | None = None
    button: str = "START/NEXT"


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_config() -> dict[str, Any]:
    return read_json(CONFIG_PATH, {})


def default_state() -> dict[str, Any]:
    cfg = load_config()
    return {
        "game_id": str(uuid.uuid4())[:8],
        "cursor": 0,
        "presses": 0,
        "player_count": int(cfg.get("default_player_count", 4)),
        "captain_index": 0,
        "scores": {},
        "persona_names": [],
        "last_card": None,
        "log": [],
    }


def load_state() -> dict[str, Any]:
    return read_json(STATE_PATH, default_state())


def save_state(state: dict[str, Any]) -> None:
    write_json(STATE_PATH, state)


def reset_state(player_count: int | None = None) -> dict[str, Any]:
    state = default_state()
    if player_count:
        state["player_count"] = max(1, min(12, int(player_count)))
    save_state(state)
    return state


def load_scenario_steps(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = cfg or load_config()
    steps = cfg.get("scenario_steps") or []
    return [step for step in steps if str(step.get("text") or step.get("title") or step.get("kind") or "").strip()]


def clean_text(text: str) -> str:
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


def apply_placeholders(text: str, state: dict[str, Any], cfg: dict[str, Any]) -> str:
    names = state.get("persona_names") or cfg.get("fallback_persona_names", [])
    if names:
        text = text.replace("[persona list]", ", ".join(names[-state.get("player_count", 4):]))
    text = text.replace("[Press START/NEXT to continue]", "")
    return clean_text(text)


def prompt_text(key: str, cfg: dict[str, Any]) -> str:
    return str((cfg.get("prompts") or {}).get(key, "")).strip()


def random_persona(state: dict[str, Any], cfg: dict[str, Any], index: int) -> str:
    first_names = cfg.get("persona_name_pool", ["Alex", "Sam", "Riley", "Morgan", "Taylor", "Jordan"])
    traits = cfg.get("persona_traits", ["curious", "romantic", "restless", "tender", "bold"])
    used = set(state.get("persona_names", []))
    available = [name for name in first_names if name not in used] or first_names
    name = random.choice(available)
    used.add(name)
    state["persona_names"] = list(used)[-30:]
    desire_templates = cfg.get("desire_templates", ["Secret desire: be chosen by someone unexpected."])
    return (
        f"{index}. {name}\n"
        f"Trait: {random.choice(traits)}\n"
        f"{random.choice(desire_templates)}\n"
        f"{cfg.get('persona_fold_line', '--- fold here ---')}"
    )


def make_vote_papers(state: dict[str, Any]) -> str:
    count = int(state.get("player_count", 4))
    labels = ["C"] + [str(i) for i in range(2, count + 1)]
    return "Detach one vote token and pass it face down.\n\n" + "\n".join(f"[ {label} ]" for label in labels)


def unique_portal_url(state: dict[str, Any], cfg: dict[str, Any]) -> str:
    base = str(cfg.get("story_portal_base_url", "")).rstrip("/")
    if not base:
        public_url = str(cfg.get("public_app_url", "")).rstrip("/")
        base = public_url + "/portal" if public_url else "/portal"
    return f"{base}/{state.get('game_id')}/{state.get('presses')}"


def build_card(step: dict[str, Any], state: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    value = apply_placeholders(str(step.get("text", "")), state, cfg)
    phase = str(step.get("phase") or "Game")
    card_title = str(step.get("title") or step.get("column_name") or "Card")
    kind = str(step.get("kind") or "text").lower()
    title = f"{phase}: {card_title}"
    footer = f"Step {state.get('cursor', 0) + 1} | START/NEXT"
    lower = value.lower()

    if kind in {"persona", "vote"} or "n=number of players" in lower or "n vote papers" in lower:
        if kind == "vote" or "vote" in lower:
            body = make_vote_papers(state)
            title = f"{phase}: Vote Papers"
        else:
            count = int(state.get("player_count", 4))
            body = "\n\n".join(random_persona(state, cfg, i + 1) for i in range(count))
            body = prompt_text("persona_generation", cfg) + "\n\n" + body if prompt_text("persona_generation", cfg) else body
            title = f"{phase}: Persona Cards"
        return {"title": title, "body": body, "footer": footer}

    if kind == "qr" or "qr code" in lower or "story portal" in lower:
        qr_url = unique_portal_url(state, cfg)
        return {
            "title": f"{phase}: Story Portal",
            "body": cfg.get("qr_card_text", "Scan this to submit the winning story."),
            "footer": footer,
            "qr_url": qr_url,
        }

    if kind == "generated_title" or "[title based on prompt response]" in lower:
        title_prompt = prompt_text("round_title", cfg)
        value = cfg.get("fallback_round_title", "A new turn of the voyage")
        if title_prompt:
            value = f"{value}\n\nPrompt note: {title_prompt}"

    if kind == "generated_story" or "[story based on prompt response]" in lower:
        story_prompt = prompt_text("round_story", cfg)
        value = cfg.get("fallback_round_story", "Jim and Julia notice a strange invitation slipped under their cabin door.")
        if story_prompt:
            value = f"{value}\n\nPrompt note: {story_prompt}"

    return {"title": title, "body": value, "footer": footer}


def advance(state: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    secret = cfg.get("device_secret")
    steps = load_scenario_steps(cfg)
    if not steps:
        raise HTTPException(status_code=500, detail="No scenario steps found in game_config.json")
    cursor = int(state.get("cursor", 0))
    if cursor >= len(steps):
        cursor = len(steps) - 1
    step = steps[cursor]
    card = build_card(step, state, cfg)
    state["last_card"] = card
    state["presses"] = int(state.get("presses", 0)) + 1
    state["cursor"] = min(cursor + 1, len(steps))
    state.setdefault("log", []).append({"cursor": cursor, "step": step, "card": card})
    state["device_secret_required"] = bool(secret)
    save_state(state)
    return {"card": card, "state": public_state(state), "done": state["cursor"] >= len(steps)}


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    steps = load_scenario_steps()
    return {
        "game_id": state.get("game_id"),
        "cursor": state.get("cursor", 0),
        "total_steps": len(steps),
        "presses": state.get("presses", 0),
        "player_count": state.get("player_count", 4),
        "last_card": state.get("last_card"),
    }


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    state = public_state(load_state())
    cfg = load_config()
    return HTML.format(
        state=json.dumps(state),
        title=cfg.get("app_title", "Love Adventure V2"),
    )


@app.get("/api/state")
async def api_state() -> dict[str, Any]:
    return public_state(load_state())


@app.post("/api/next")
async def api_next() -> dict[str, Any]:
    return advance(load_state())


@app.post("/api/reset")
async def api_reset(request: Request) -> dict[str, Any]:
    payload = await request.json()
    return public_state(reset_state(payload.get("player_count")))


@app.post("/api/device/next")
async def api_device_next(payload: DeviceNext) -> JSONResponse:
    cfg = load_config()
    expected_secret = cfg.get("device_secret")
    if expected_secret and payload.secret != expected_secret:
        raise HTTPException(status_code=403, detail="Bad device secret")
    return JSONResponse(advance(load_state()))


@app.get("/portal/{game_id}/{step}", response_class=HTMLResponse)
async def portal(game_id: str, step: str) -> str:
    return PORTAL_HTML.format(game_id=game_id, step=step)


HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ font-family: Arial, sans-serif; color: #171717; background: #f6f3ee; }}
    body {{ margin: 0; }}
    main {{ max-width: 860px; margin: 0 auto; padding: 28px 18px; }}
    h1 {{ margin: 0 0 18px; font-size: 30px; }}
    .panel {{ background: white; border: 1px solid #ddd6cc; border-radius: 8px; padding: 18px; }}
    .row {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }}
    button {{ border: 0; border-radius: 8px; padding: 14px 18px; background: #111; color: white; font-weight: 700; cursor: pointer; }}
    button.secondary {{ background: #6b6258; }}
    input {{ padding: 11px; border: 1px solid #cfc7bd; border-radius: 6px; width: 80px; }}
    pre {{ white-space: pre-wrap; background: #fbfaf8; border: 1px solid #e6ded4; border-radius: 8px; padding: 14px; min-height: 180px; }}
    .muted {{ color: #655d54; }}
  </style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <section class="panel">
    <div class="row">
      <button onclick="next()">START/NEXT</button>
      <button class="secondary" onclick="resetGame()">Reset</button>
      <label>Players <input id="players" type="number" min="1" max="12"></label>
    </div>
    <p class="muted" id="progress"></p>
    <pre id="card"></pre>
  </section>
</main>
<script>
let state = {state};
function draw() {{
  document.getElementById("players").value = state.player_count || 4;
  document.getElementById("progress").textContent = `Game ${{state.game_id}} | Step ${{state.cursor}} of ${{state.total_steps}} | Presses ${{state.presses}}`;
  const card = state.last_card;
  document.getElementById("card").textContent = card ? `${{card.title}}\\n\\n${{card.body}}\\n\\n${{card.footer || ""}}${{card.qr_url ? "\\n" + card.qr_url : ""}}` : "Press START/NEXT to begin.";
}}
async function next() {{
  const res = await fetch("/api/next", {{method: "POST"}});
  const data = await res.json();
  state = data.state;
  draw();
}}
async function resetGame() {{
  const player_count = Number(document.getElementById("players").value || 4);
  const res = await fetch("/api/reset", {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify({{player_count}})}});
  state = await res.json();
  draw();
}}
draw();
</script>
</body>
</html>
"""


PORTAL_HTML = """
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Story Portal</title></head>
<body style="font-family: Arial, sans-serif; max-width: 720px; margin: 32px auto; padding: 0 16px;">
  <h1>Story Portal</h1>
  <p>Game {game_id}, step {step}</p>
  <p>This placeholder page is ready to connect to the winner submission form.</p>
</body>
</html>
"""
