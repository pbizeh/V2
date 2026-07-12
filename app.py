import json
import os
import random
import base64
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Thread
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.getenv("GAME_CONFIG_PATH", BASE_DIR / "game_config.json"))
STATE_PATH = Path(os.getenv("GAME_STATE_PATH", BASE_DIR / "game_state.json"))


app = FastAPI(title="Love Adventure V2")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class DeviceNext(BaseModel):
    device_id: str = "printer-001"
    secret: str | None = None
    button: str = "START/NEXT"
    settings: dict[str, int] | None = None
    player_count: int | None = None


class DeviceStatus(BaseModel):
    device_id: str = "printer-001"
    secret: str | None = None
    status: str | None = None
    message: str | None = None
    settings: dict[str, int] | None = None
    player_count: int | None = None


class NextRequest(BaseModel):
    settings: dict[str, int] | None = None
    player_count: int | None = None


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(path)


def load_config() -> dict[str, Any]:
    return read_json(CONFIG_PATH, {})


def load_raster_payload(path_value: str | None) -> dict[str, Any] | None:
    if not path_value:
        return None
    path = BASE_DIR / path_value
    if not path.exists():
        return None
    return read_json(path, {})


def device_secret(cfg: dict[str, Any] | None = None) -> str | None:
    return os.getenv("DEVICE_SECRET") or (cfg or load_config()).get("device_secret")


def default_state() -> dict[str, Any]:
    cfg = load_config()
    default_settings = cfg.get("default_settings", {})
    return {
        "game_id": str(uuid.uuid4())[:8],
        "cursor": 0,
        "presses": 0,
        "player_count": int(cfg.get("default_player_count", 4)),
        "player_count_locked": False,
        "settings": {
            "age": int(default_settings.get("age", 50)),
            "queerness": int(default_settings.get("queerness", 50)),
            "diversity": int(default_settings.get("diversity", 50)),
        },
        "captain_index": 0,
        "scores": {},
        "persona_names": [],
        "persona_queue": [],
        "last_card": None,
        "last_print": None,
        "prints": [],
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


def clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = fallback
    return max(minimum, min(maximum, number))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_device_secret(secret: str | None, cfg: dict[str, Any]) -> None:
    expected_secret = device_secret(cfg)
    if expected_secret and secret != expected_secret:
        raise HTTPException(status_code=403, detail="Bad device secret")


def record_device_status(
    state: dict[str, Any],
    device_id: str,
    status: str,
    message: str | None = None,
    accepted: bool = True,
) -> dict[str, Any]:
    hardware = {
        "device_id": device_id,
        "status": status,
        "message": message or "",
        "accepted": accepted,
        "last_seen": utc_now(),
    }
    state["hardware"] = hardware
    save_state(state)
    return hardware


def apply_hardware_controls(
    state: dict[str, Any],
    settings: dict[str, Any] | None = None,
    player_count: int | None = None,
) -> dict[str, Any]:
    if settings:
        state["settings"] = normalize_settings(settings, state.get("settings", {}))
    if player_count and not state.get("player_count_locked"):
        state["player_count"] = max(4, min(6, int(player_count)))
    return state


def normalize_settings(settings: dict[str, Any] | None, fallback: dict[str, Any] | None = None) -> dict[str, int]:
    fallback = fallback or {}
    return {
        "age": clamp_int((settings or {}).get("age"), 1, 100, clamp_int(fallback.get("age"), 1, 100, 50)),
        "queerness": clamp_int((settings or {}).get("queerness"), 1, 100, clamp_int(fallback.get("queerness"), 1, 100, 50)),
        "diversity": clamp_int((settings or {}).get("diversity"), 1, 100, clamp_int(fallback.get("diversity"), 1, 100, 50)),
    }


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


def render_template(text: str, state: dict[str, Any], cfg: dict[str, Any], extra: dict[str, Any] | None = None) -> str:
    values = {
        "age": state.get("settings", {}).get("age", 50),
        "queerness": state.get("settings", {}).get("queerness", 50),
        "diversity": state.get("settings", {}).get("diversity", 50),
        "player_count": state.get("player_count", 4),
        "persona_list": ", ".join(state.get("persona_names") or cfg.get("fallback_persona_names", [])),
    }
    if extra:
        values.update(extra)
    try:
        return text.format(**values)
    except (KeyError, ValueError):
        return text


def openai_chat(prompt: str, cfg: dict[str, Any]) -> str | None:
    openai_cfg = cfg.get("openai", {})
    if not openai_cfg.get("enabled", True):
        return None
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    payload = {
        "model": openai_cfg.get("text_model", "gpt-4.1-mini"),
        "messages": [
            {"role": "system", "content": openai_cfg.get("system_prompt", "You write concise printable game cards.")},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(openai_cfg.get("temperature", 0.8)),
        "max_tokens": int(openai_cfg.get("max_tokens", 600)),
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=int(openai_cfg.get("timeout_seconds", 25))) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError, json.JSONDecodeError, TimeoutError):
        return None


def ai_or_fallback(prompt_key: str, fallback_key: str, state: dict[str, Any], cfg: dict[str, Any], extra: dict[str, Any] | None = None) -> str:
    prompt = render_template(prompt_text(prompt_key, cfg), state, cfg, extra)
    generated = openai_chat(prompt, cfg) if prompt else None
    if generated:
        return clean_text(generated)
    return clean_text(render_template(str(cfg.get(fallback_key, "")), state, cfg, extra))


def parse_json_array(text: str | None) -> list[dict[str, Any]]:
    if not text:
        return []
    raw = text.strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        raw = raw[start:end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def parse_json_object(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    raw = text.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start:end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def normalize_hashtags(value: Any, cfg: dict[str, Any]) -> list[str]:
    if isinstance(value, list):
        words = [str(item) for item in value]
    else:
        words = str(value or "").replace(",", " ").split()
    tags: list[str] = []
    for word in words:
        tag = word if word.startswith("#") else "#" + word
        tag = "#" + "".join(ch for ch in tag[1:] if ch.isalnum() or ch == "_")
        if 1 < len(tag) <= 18 and tag not in tags:
            tags.append(tag)
        if len(tags) >= 4:
            break
    for tag in cfg.get("persona_fallback_hashtags", ["#open_heart", "#soft_risk", "#new_story"]):
        if len(tags) >= 3:
            break
        if tag not in tags:
            tags.append(tag)
    return tags[:4]


def clean_name(value: Any) -> str:
    name = clean_text(str(value or "")).strip()
    name = "".join(ch for ch in name if ch.isalnum() or ch in " -'")
    return name.strip()[:24]


def avoided_persona_names(state: dict[str, Any], cfg: dict[str, Any], extra: list[str] | None = None) -> list[str]:
    names = [str(item) for item in state.get("persona_names", [])]
    names.extend(str(item.get("name", "")) for item in (cfg.get("static_personas") or {}).values())
    if extra:
        names.extend(extra)
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        cleaned = clean_name(name)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def fallback_generated_persona(index: int, cfg: dict[str, Any], avoid_names: list[str] | None = None) -> dict[str, Any]:
    names = cfg.get("persona_name_pool", ["Alex", "Sam", "Riley", "Morgan"])
    traits = cfg.get("persona_traits", ["curious", "tender", "bold"])
    genders = cfg.get("persona_gender_pool", ["woman", "man", "non-binary"])
    sexualities = cfg.get("persona_sexuality_pool", ["bi", "queer", "pan"])
    avoided = {name.casefold() for name in (avoid_names or [])}
    available = [name for name in names if str(name).casefold() not in avoided] or names
    name = str(available[(index - 1) % len(available)])
    trait = random.choice(traits)
    gender = random.choice(genders)
    sexuality = random.choice(sexualities)
    age = random.randint(28, 52)
    return {
        "name": name,
        "age": age,
        "sexuality": sexuality,
        "gender": gender,
        "hashtags": normalize_hashtags([trait, "open_heart", "soft_risk"], cfg),
        "desire": random.choice(cfg.get("desire_templates", ["Secret desire: be invited into a risky plan."])),
        "image_prompt": render_template(str(cfg.get("fallback_persona_image_prompt", "")), {}, cfg, {
            "name": name,
            "age": age,
            "sexuality": sexuality,
            "gender": gender,
            "hashtags": " ".join([trait]),
        }),
    }


def openai_image(prompt: str, cfg: dict[str, Any]):
    api_key = os.getenv("OPENAI_API_KEY")
    openai_cfg = cfg.get("openai", {})
    if not api_key or not prompt:
        return None
    payload = {
        "model": openai_cfg.get("image_model", "gpt-image-1-mini"),
        "prompt": prompt,
        "size": openai_cfg.get("image_size", "1024x1024"),
        "quality": openai_cfg.get("image_quality", "low"),
        "n": 1,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=int(openai_cfg.get("image_timeout_seconds", 90))) as response:
            data = json.loads(response.read().decode("utf-8"))
        image_data = data["data"][0]
        if image_data.get("b64_json"):
            raw = base64.b64decode(image_data["b64_json"])
        else:
            with urllib.request.urlopen(image_data["url"], timeout=90) as image_response:
                raw = image_response.read()
        from PIL import Image
        return Image.open(BytesIO(raw)).convert("RGB")
    except Exception:
        return None


def image_to_card_payload(image, cfg: dict[str, Any]) -> dict[str, Any] | None:
    if image is None:
        return None
    from PIL import ImageOps
    raster_cfg = cfg.get("persona_raster", {})
    width = int(raster_cfg.get("width", 384))
    height = int(raster_cfg.get("height", 320))
    threshold = int(raster_cfg.get("threshold", 180))
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    gray = ImageOps.fit(gray, (width, height), centering=(0.5, 0.42))
    bw = gray.point(lambda p: 255 if p > threshold else 0, "1")
    pixels = bw.load()
    raw = bytearray()
    for y in range(height):
        for xb in range(0, width, 8):
            byte = 0
            for bit in range(8):
                if pixels[xb + bit, y] == 0:
                    byte |= 1 << (7 - bit)
            raw.append(byte)
    preview = BytesIO()
    bw.convert("L").save(preview, format="PNG")
    return {
        "image_raster": {
            "width": width,
            "height": height,
            "mode": "1bit_msb",
            "bytes_hex": raw.hex(),
        },
        "image_data_url": "data:image/png;base64," + base64.b64encode(preview.getvalue()).decode("ascii"),
    }


def persona_card_from_data(data: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    styles = cfg.get("print_text_styles", {})
    name = clean_text(str(data.get("name") or "PERSONA")).upper()
    hashtags = normalize_hashtags(data.get("hashtags"), cfg)
    metadata = " | ".join(
        clean_text(str(data.get(key, "")))
        for key in ("age", "sexuality", "gender")
        if str(data.get(key, "")).strip()
    )
    fold_line = str(cfg.get("persona_fold_line", "--- fold here ---"))
    desire_title = str(cfg.get("persona_desire_title", "DESIRE"))
    desire = clean_text(str(data.get("desire") or random.choice(cfg.get("desire_templates", ["Secret desire: be chosen."]))))
    body = "\n\n".join(part for part in [
        metadata,
        " ".join(hashtags),
        fold_line,
        desire_title,
        desire,
    ] if part)
    card = {
        "title": name,
        "body": body,
        "footer": "",
        "styles": styles,
        "show_divider": False,
    }
    image_payload = image_to_card_payload(openai_image(str(data.get("image_prompt", "")), cfg), cfg)
    if image_payload:
        card.update(image_payload)
    return card


def persona_batch_key(state: dict[str, Any], step: dict[str, Any] | None = None) -> str:
    profile = str((step or {}).get("persona_profile", "average"))
    return f"{state.get('game_id')}:{state.get('player_count', 4)}:{profile}"


def generate_one_persona(
    state: dict[str, Any],
    cfg: dict[str, Any],
    index: int,
    avoid_names: list[str],
    step: dict[str, Any] | None = None,
) -> dict[str, Any]:
    count = max(1, min(12, int(state.get("player_count", 4))))
    profile = str((step or {}).get("persona_profile", "average"))
    controls = {"age": 50, "queerness": 50, "diversity": 50} if profile == "average" else state.get("settings", {})
    prompt_state = {**state, "settings": controls}
    prompt = render_template(
        prompt_text("persona_single_generation", cfg),
        prompt_state,
        cfg,
        {
            "index": index,
            "count": count,
            "avoid_names": ", ".join(avoid_names) or "none",
            "persona_profile": profile,
        },
    )
    data = parse_json_object(openai_chat(prompt, cfg) if prompt else None)
    name = clean_name(data.get("name"))
    if not name or name.casefold() in {item.casefold() for item in avoid_names}:
        data = fallback_generated_persona(index, cfg, avoid_names)
    else:
        data["name"] = name
    if not str(data.get("image_prompt", "")).strip():
        data["image_prompt"] = render_template(str(cfg.get("fallback_persona_image_prompt", "")), prompt_state, cfg, data)
    return persona_card_from_data(data, cfg)


def generate_persona_batch(state: dict[str, Any], cfg: dict[str, Any], step: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    count = max(1, min(12, int(state.get("player_count", 4))))
    avoid_names = avoided_persona_names(state, cfg)
    cards = []
    for index in range(1, count + 1):
        card = generate_one_persona(state, cfg, index, avoid_names, step)
        cards.append(card)
        name = clean_name(card.get("title", "")).title()
        if name:
            avoid_names.append(name)
    names = [clean_name(card.get("title", "")).title() for card in cards if card.get("title")]
    if names:
        state["persona_names"] = (state.get("persona_names", []) + names)[-30:]
    return cards


def prepare_persona_batch(state: dict[str, Any], cfg: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    key = persona_batch_key(state, step)
    if state.get("persona_queue_key") == key and len(state.get("persona_queue", [])) >= int(state.get("player_count", 4)):
        return state
    state["persona_generation_status"] = {
        "status": "generating",
        "started_at": utc_now(),
        "count": int(state.get("player_count", 4)),
        "profile": str(step.get("persona_profile", "average")),
    }
    cards = generate_persona_batch(state, cfg, step)
    state["persona_queue"] = cards
    state["persona_queue_key"] = key
    state["persona_generation_status"] = {
        "status": "ready",
        "finished_at": utc_now(),
        "count": len(cards),
        "profile": str(step.get("persona_profile", "average")),
    }
    return state


def start_persona_batch_preparation(state: dict[str, Any], cfg: dict[str, Any], step: dict[str, Any]) -> None:
    key = persona_batch_key(state, step)
    if state.get("persona_queue_key") == key and state.get("persona_queue"):
        return
    status = state.get("persona_generation_status") or {}
    if status.get("status") == "generating" and status.get("key") == key:
        return
    state["persona_generation_status"] = {
        "status": "generating",
        "started_at": utc_now(),
        "count": int(state.get("player_count", 4)),
        "profile": str(step.get("persona_profile", "average")),
        "key": key,
    }
    save_state(state)

    state_snapshot = json.loads(json.dumps(state))
    step_snapshot = json.loads(json.dumps(step))

    def worker() -> None:
        cfg_snapshot = load_config()
        generated_state = prepare_persona_batch(state_snapshot, cfg_snapshot, step_snapshot)
        latest_state = load_state()
        if latest_state.get("game_id") != state_snapshot.get("game_id"):
            return
        latest_state["persona_queue"] = generated_state.get("persona_queue", [])
        latest_state["persona_queue_key"] = generated_state.get("persona_queue_key")
        latest_state["persona_names"] = generated_state.get("persona_names", latest_state.get("persona_names", []))
        latest_state["persona_generation_status"] = generated_state.get("persona_generation_status")
        save_state(latest_state)

    Thread(target=worker, daemon=True).start()


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


def make_persona_cards(state: dict[str, Any], cfg: dict[str, Any]) -> str:
    count = int(state.get("player_count", 4))
    prompt = render_template(prompt_text("persona_generation", cfg), state, cfg, {"count": count})
    generated = openai_chat(prompt, cfg) if prompt else None
    if generated:
        names = []
        for line in generated.splitlines():
            stripped = line.strip()
            if stripped and stripped[0].isdigit() and "." in stripped:
                candidate = stripped.split(".", 1)[1].strip().split(" ", 1)[0].strip(":,-")
                if candidate:
                    names.append(candidate)
        if names:
            state["persona_names"] = (state.get("persona_names", []) + names)[-30:]
        return clean_text(generated)
    return "\n\n".join(random_persona(state, cfg, i + 1) for i in range(count))


def make_vote_papers(state: dict[str, Any]) -> str:
    count = int(state.get("player_count", 4))
    labels = ["C"] + [str(i) for i in range(2, count + 1)]
    return "Detach one vote token and pass it face down.\n\n" + "\n".join(f"[ {label} ]" for label in labels)


def center_text(text: str, width: int) -> str:
    return clean_text(text).strip().center(width)


def wrap_text(text: str, width: int) -> list[str]:
    words = clean_text(text).replace("\n", " \n ").split()
    lines: list[str] = []
    current = ""
    for word in words:
        if word == "\n":
            lines.append(current)
            current = ""
        elif not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def render_print_preview(card: dict[str, Any], state: dict[str, Any], cfg: dict[str, Any]) -> str:
    print_profile = cfg.get("print_profile") or {}
    width = int(print_profile.get("text_columns", cfg.get("print_preview_columns", 42)))
    divider = str(print_profile.get("divider", cfg.get("print_preview_divider", "-" * min(width, 42))))
    lines = []
    title = str(card.get("title") or "").strip()
    if title:
        lines.extend(wrap_text(title, width))
        lines.append("")
    for paragraph in str(card.get("body", "")).split("\n"):
        if paragraph.strip():
            lines.extend(wrap_text(paragraph, width))
        else:
            lines.append("")
    if card.get("qr_url"):
        lines.append("")
        lines.append(center_text("QR", width))
        lines.extend(wrap_text(card["qr_url"], width))
    footer = card.get("footer")
    if footer:
        lines.append("")
        lines.extend(wrap_text(footer, width))
    if card.get("show_divider"):
        lines.append(divider[:width])
    return "\n".join(lines).rstrip() + "\n"


def build_print(card: dict[str, Any], step: dict[str, Any], state: dict[str, Any], cfg: dict[str, Any], cursor: int) -> dict[str, Any]:
    print_profile = cfg.get("print_profile") or {}
    preview = render_print_preview(card, state, cfg)
    return {
        "id": str(uuid.uuid4())[:8],
        "number": int(state.get("presses", 0)) + 1,
        "step_index": cursor,
        "title": card.get("title", "PRINT"),
        "preview": preview,
        "columns": int(print_profile.get("text_columns", cfg.get("print_preview_columns", 42))),
        "paper_width_mm": float(print_profile.get("paper_width_mm", 58)),
        "printable_width_mm": float(print_profile.get("printable_width_mm", 48)),
        "raster_policy": cfg.get("raster_policy", {}),
        "card": card,
        "step": step,
        "settings": state.get("settings", {}),
    }


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
    styles = cfg.get("print_text_styles", {})

    if kind == "static_persona":
        persona_id = str(step.get("persona_id", "")).strip()
        persona = (cfg.get("static_personas") or {}).get(persona_id, {})
        hashtags = " ".join(persona.get("hashtags", []))
        metadata = " | ".join(
            str(persona.get(key, "")).strip()
            for key in ("age", "sexuality", "gender")
            if str(persona.get(key, "")).strip()
        )
        body_lines = [line for line in [metadata, hashtags] if line]
        return {
            "title": str(persona.get("name", card_title)).upper(),
            "body": "\n\n".join(body_lines),
            "footer": str(persona.get("footer", "")),
            "image_url": str(persona.get("image_url", "")),
            "image_raster": load_raster_payload(persona.get("raster_path")),
            "styles": styles,
            "show_divider": bool(step.get("show_divider", False)),
        }

    if kind in {"persona", "vote"} or "n=number of players" in lower or "n vote papers" in lower:
        if kind == "vote" or "vote" in lower:
            body = make_vote_papers(state)
            title = f"{phase}: Vote Papers"
        else:
            body = make_persona_cards(state, cfg)
            title = f"{phase}: Persona Cards"
        return {"title": title, "body": body, "footer": footer, "styles": styles}

    if kind == "qr" or "qr code" in lower or "story portal" in lower:
        qr_url = unique_portal_url(state, cfg)
        return {
            "title": f"{phase}: Story Portal",
            "body": cfg.get("qr_card_text", "Scan this to submit the winning story."),
            "footer": footer,
            "qr_url": qr_url,
            "styles": styles,
        }

    if kind == "generated_title" or "[title based on prompt response]" in lower:
        value = ai_or_fallback("round_title", "fallback_round_title", state, cfg)

    if kind == "generated_story" or "[story based on prompt response]" in lower:
        value = ai_or_fallback("round_story", "fallback_round_story", state, cfg)

    return {
        "title": apply_placeholders(str(step.get("print_title", title)), state, cfg),
        "body": apply_placeholders(str(step.get("print_body", value)), state, cfg),
        "footer": apply_placeholders(str(step.get("print_footer", footer)), state, cfg) if step.get("print_footer") is not None else footer,
        "styles": styles,
        "show_divider": bool(step.get("show_divider", False)),
    }


def wait_for_persona_queue(state: dict[str, Any], cfg: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    key = persona_batch_key(state, step)
    wait_seconds = int(cfg.get("persona_queue_wait_seconds", 8))
    deadline = time.time() + max(0, wait_seconds)
    while time.time() < deadline:
        latest = load_state()
        if latest.get("game_id") != state.get("game_id"):
            return latest
        if latest.get("persona_queue_key") == key and latest.get("persona_queue"):
            return latest
        time.sleep(0.5)
    return state


def persona_batch_step_for_prepare(cfg: dict[str, Any], current_step: dict[str, Any]) -> dict[str, Any]:
    for step in load_scenario_steps(cfg):
        if str(step.get("kind", "")).lower() == "generated_persona_batch":
            prepared = dict(step)
            prepared["persona_profile"] = current_step.get("persona_profile", prepared.get("persona_profile", "average"))
            return prepared
    return {"kind": "generated_persona_batch", "title": "Persona Cards", "persona_profile": current_step.get("persona_profile", "average")}


def patience_card(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(cfg.get("patience_card_title", "")),
        "body": str(cfg.get("patience_card_text", "Please be patient while cards are being generated.")),
        "footer": "",
        "styles": cfg.get("print_text_styles", {}),
        "show_divider": False,
    }


def record_print_without_advancing(
    card: dict[str, Any],
    step: dict[str, Any],
    state: dict[str, Any],
    cfg: dict[str, Any],
    cursor: int,
    secret_required: bool,
) -> dict[str, Any]:
    print_item = build_print(card, step, state, cfg, cursor)
    state["last_card"] = card
    state["last_print"] = print_item
    state["prints"] = (state.get("prints", []) + [print_item])[-50:]
    state["presses"] = int(state.get("presses", 0)) + 1
    state.setdefault("log", []).append({"cursor": cursor, "step": step, "card": card, "print": print_item, "blocked": True})
    state["device_secret_required"] = secret_required
    save_state(state)
    return {"card": card, "print": print_item, "state": public_state(state), "done": False}


def advance(state: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_config()
    secret = device_secret(cfg)
    steps = load_scenario_steps(cfg)
    if not steps:
        raise HTTPException(status_code=500, detail="No scenario steps found in game_config.json")
    state["settings"] = normalize_settings(settings, state.get("settings", {}))
    cursor = int(state.get("cursor", 0))
    if cursor >= len(steps):
        cursor = len(steps) - 1
    step = steps[cursor]
    if step.get("lock_player_count"):
        state["player_count_locked"] = True

    if str(step.get("kind", "")).lower() == "generated_persona_batch":
        state = wait_for_persona_queue(state, cfg, step)
        if not state.get("persona_queue"):
            start_persona_batch_preparation(state, cfg, step)
            return record_print_without_advancing(
                patience_card(cfg),
                {"phase": "System", "title": "Generating Cards", "kind": "patience"},
                load_state(),
                cfg,
                cursor,
                bool(secret),
            )
        queue = list(state.get("persona_queue", []))
        card = queue.pop(0)
        print_item = build_print(card, step, state, cfg, cursor)
        state["persona_queue"] = queue
        state["last_card"] = card
        state["last_print"] = print_item
        state["prints"] = (state.get("prints", []) + [print_item])[-50:]
        state["presses"] = int(state.get("presses", 0)) + 1
        state["cursor"] = cursor if queue else min(cursor + 1, len(steps))
        state.setdefault("log", []).append({"cursor": cursor, "step": step, "card": card, "print": print_item})
        state["device_secret_required"] = bool(secret)
        save_state(state)
        return {"card": card, "print": print_item, "state": public_state(state), "done": state["cursor"] >= len(steps)}

    card = build_card(step, state, cfg)
    print_item = build_print(card, step, state, cfg, cursor)
    state["last_card"] = card
    state["last_print"] = print_item
    state["prints"] = (state.get("prints", []) + [print_item])[-50:]
    state["presses"] = int(state.get("presses", 0)) + 1
    state["cursor"] = min(cursor + 1, len(steps))
    state.setdefault("log", []).append({"cursor": cursor, "step": step, "card": card, "print": print_item})
    state["device_secret_required"] = bool(secret)
    save_state(state)
    if step.get("prepare_persona_batch_after"):
        start_persona_batch_preparation(state, cfg, persona_batch_step_for_prepare(cfg, step))
    return {"card": card, "print": print_item, "state": public_state(state), "done": state["cursor"] >= len(steps)}


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    steps = load_scenario_steps()
    cursor = int(state.get("cursor", 0))
    next_step = steps[cursor] if cursor < len(steps) else None
    return {
        "game_id": state.get("game_id"),
        "cursor": cursor,
        "total_steps": len(steps),
        "presses": state.get("presses", 0),
        "player_count": state.get("player_count", 4),
        "player_count_locked": bool(state.get("player_count_locked")),
        "captain_index": state.get("captain_index", 0),
        "scores": state.get("scores", {}),
        "settings": normalize_settings(state.get("settings", {})),
        "persona_names": state.get("persona_names", []),
        "persona_queue_remaining": len(state.get("persona_queue", [])),
        "persona_generation_status": state.get("persona_generation_status"),
        "last_card": state.get("last_card"),
        "last_print": state.get("last_print"),
        "prints": state.get("prints", [])[-50:],
        "next_step": next_step,
        "recent_log": state.get("log", [])[-10:],
        "hardware": state.get("hardware"),
        "done": cursor >= len(steps),
        "openai_api_key_configured": bool(os.getenv("OPENAI_API_KEY")),
    }


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    state = public_state(load_state())
    cfg = load_config()
    return HTMLResponse(
        HTML.format(
            state=json.dumps(state),
            title=cfg.get("app_title", "Love Adventure V2"),
        ),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/state")
async def api_state() -> dict[str, Any]:
    return public_state(load_state())


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    cfg = load_config()
    return DASHBOARD_HTML.format(title=cfg.get("app_title", "Love Adventure V2"))


@app.post("/api/next")
async def api_next(payload: NextRequest | None = None) -> dict[str, Any]:
    state = load_state()
    if payload:
        state = apply_hardware_controls(state, payload.settings, payload.player_count)
        save_state(state)
    return advance(load_state(), payload.settings if payload else None)


@app.post("/api/reset")
async def api_reset(request: Request) -> dict[str, Any]:
    payload = await request.json()
    return public_state(reset_state(payload.get("player_count")))


@app.post("/api/device/next")
async def api_device_next(payload: DeviceNext) -> JSONResponse:
    cfg = load_config()
    state = load_state()
    try:
        validate_device_secret(payload.secret, cfg)
    except HTTPException:
        record_device_status(state, payload.device_id, "rejected", "Bad device secret", accepted=False)
        raise
    state = apply_hardware_controls(state, payload.settings, payload.player_count)
    record_device_status(
        state,
        payload.device_id,
        "next",
        f"START/NEXT accepted; players={state.get('player_count')}",
    )
    return JSONResponse(advance(load_state(), payload.settings))


@app.post("/api/device/status")
async def api_device_status(payload: DeviceStatus) -> dict[str, Any]:
    cfg = load_config()
    state = load_state()
    try:
        validate_device_secret(payload.secret, cfg)
    except HTTPException:
        hardware = record_device_status(
            state,
            payload.device_id,
            "rejected",
            "Bad device secret",
            accepted=False,
        )
        return {
            "ok": False,
            "detail": "Bad device secret",
            "hardware": hardware,
            "state": public_state(load_state()),
        }

    hardware = record_device_status(
        apply_hardware_controls(state, payload.settings, payload.player_count),
        payload.device_id,
        payload.status or "online",
        payload.message or "Device status check accepted",
    )
    public = public_state(load_state())
    return {
        "ok": True,
        "detail": "Device accepted",
        "hardware": hardware,
        "state": {
            "game_id": public["game_id"],
            "cursor": public["cursor"],
            "total_steps": public["total_steps"],
            "presses": public["presses"],
            "next_step": public["next_step"],
        },
    }


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
    main {{ max-width: 920px; margin: 0 auto; padding: 28px 18px 46px; }}
    h1 {{ margin: 0 0 18px; font-size: 30px; }}
    .panel {{ background: white; border: 1px solid #ddd6cc; border-radius: 8px; padding: 18px; }}
    .row {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }}
    button {{ border: 0; border-radius: 8px; padding: 14px 18px; background: #111; color: white; font-weight: 700; cursor: pointer; }}
    input[type="number"] {{ padding: 11px; border: 1px solid #cfc7bd; border-radius: 6px; width: 80px; }}
    input[type="range"] {{ width: min(240px, 70vw); }}
    label.slider {{ display: grid; gap: 5px; min-width: 220px; font-weight: 700; }}
    label.slider span {{ font-weight: 400; color: #655d54; }}
    pre {{ white-space: pre-wrap; margin: 0; }}
    .muted {{ color: #655d54; }}
    .print-feed {{ display: grid; gap: 12px; margin-top: 16px; }}
    .print-feed article {{ border-top: 1px solid #e6ded4; padding-top: 12px; }}
    .print-feed h3 {{ margin: 0 0 8px; font-size: 16px; }}
    .current-label {{ margin: 18px 0 8px; font-weight: 700; }}
    .thermal-paper {{
      width: min(100%, 360px);
      min-height: 180px;
      box-sizing: border-box;
      background: #fff;
      color: #000;
      border-radius: 2px;
      border: 1px solid #d8d2c8;
      padding: 16px 14px;
      box-shadow: 0 8px 20px rgba(0,0,0,.08);
      font-family: "Courier New", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      line-height: 1.18;
      letter-spacing: 0;
      image-rendering: pixelated;
      overflow-wrap: anywhere;
    }}
    .thermal-paper pre {{ min-height: 0; background: transparent; border: 0; padding: 0; }}
    .thermal-paper.empty {{ color: #555; }}
    .paper-part {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
    .paper-title {{ text-align: center; font-weight: 700; margin-bottom: 10px; }}
    .paper-image {{ display: block; width: 100%; max-width: 320px; margin: 0 auto 10px; image-rendering: pixelated; filter: grayscale(1) contrast(1.15); }}
    .paper-body {{ margin-bottom: 8px; }}
    .paper-footer {{ margin-top: 10px; opacity: .86; }}
    .thermal-feed {{ display: grid; gap: 10px; }}
  </style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <section class="panel">
    <div class="row">
      <button onclick="next()">START/NEXT</button>
      <label>Players <input id="players" type="number" min="4" max="6"></label>
    </div>
    <div class="row" style="margin-top: 16px;">
      <label class="slider">AGE <input id="age" type="range" min="1" max="100"><span id="ageValue"></span></label>
      <label class="slider">QUEERNESS <input id="queerness" type="range" min="1" max="100"><span id="queernessValue"></span></label>
      <label class="slider">DIVERSITY <input id="diversity" type="range" min="1" max="100"><span id="diversityValue"></span></label>
    </div>
    <p class="muted" id="progress"></p>
    <p class="muted" id="hardwareLive">Waiting for hardware controls...</p>
    <p class="current-label">Most recent print</p>
    <div id="cardPaper" class="thermal-paper empty"><pre id="card"></pre></div>
    <div id="feed" class="print-feed"></div>
  </section>
</main>
<script>
let state = {state};
const sliderIds = ["age", "queerness", "diversity"];
function currentSettings() {{
  return {{
    age: Number(document.getElementById("age").value || 50),
    queerness: Number(document.getElementById("queerness").value || 50),
    diversity: Number(document.getElementById("diversity").value || 50)
  }};
}}
function currentPlayerCount() {{
  return Number(document.getElementById("players").value || state.player_count || 4);
}}
function syncSliderLabels() {{
  for (const id of sliderIds) {{
    document.getElementById(id + "Value").textContent = document.getElementById(id).value;
  }}
}}
function printText(item) {{
  if (!item) return "Press START/NEXT to create the first print.";
  return item.preview || `${{item.card?.title || ""}}\\n\\n${{item.card?.body || ""}}`;
}}
function escapeHtml(text) {{
  return String(text || "").replace(/[&<>]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;"}}[c]));
}}
function styleAttr(style, fallbackScale) {{
  const scale = Number(style?.preview_scale || fallbackScale || 1);
  const weight = style?.bold ? "font-weight:700;" : "";
  const align = style?.align ? `text-align:${{style.align}};` : "";
  return `font-size:${{scale}}em;${{weight}}${{align}}`;
}}
function cardHtml(item) {{
  const card = item?.card || null;
  if (!card) return `<pre>${{escapeHtml(printText(item))}}</pre>`;
  const styles = card.styles || {{}};
  const title = card.title ? `<div class="paper-part paper-title" style="${{styleAttr(styles.title, 1.65)}}">${{escapeHtml(card.title)}}</div>` : "";
  const imageSrc = card.image_data_url || card.image_url || "";
  const image = imageSrc ? `<img class="paper-image" alt="" src="${{escapeHtml(imageSrc)}}">` : "";
  const body = card.body ? `<div class="paper-part paper-body" style="${{styleAttr(styles.body, 1)}}">${{escapeHtml(card.body)}}</div>` : "";
  const footer = card.footer ? `<div class="paper-part paper-footer" style="${{styleAttr(styles.footer, .9)}}">${{escapeHtml(card.footer)}}</div>` : "";
  const qr = card.qr_url ? `<div class="paper-part paper-footer">[native printer QR]\\n${{escapeHtml(card.qr_url)}}</div>` : "";
  return title + image + body + footer + qr;
}}
function draw() {{
  document.getElementById("players").value = state.player_count || 4;
  const settings = state.settings || {{}};
  for (const id of sliderIds) {{
    const el = document.getElementById(id);
    el.value = settings[id] || 50;
  }}
  syncSliderLabels();
  document.getElementById("progress").textContent = `Game ${{state.game_id}} | Step ${{state.cursor}} of ${{state.total_steps}} | Presses ${{state.presses}}`;
  const hardware = state.hardware || {{}};
  document.getElementById("hardwareLive").textContent = hardware.last_seen
    ? `Hardware: ${{hardware.status || "online"}} | Last update ${{hardware.last_seen}} | Players ${{state.player_count || 4}} | AGE ${{settings.age || 50}} | QUEERNESS ${{settings.queerness || 50}} | DIVERSITY ${{settings.diversity || 50}}`
    : "Waiting for hardware controls...";
  document.getElementById("cardPaper").innerHTML = cardHtml(state.last_print);
  document.getElementById("cardPaper").classList.toggle("empty", !state.last_print);
  const older = (state.prints || []).slice(0, -1).reverse();
  document.getElementById("feed").innerHTML = older.map(item => `<article><h3>Print ${{item.number}}: ${{item.title}}</h3><div class="thermal-paper">${{cardHtml(item)}}</div></article>`).join("");
}}
async function next() {{
  const res = await fetch("/api/next", {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify({{settings: currentSettings(), player_count: currentPlayerCount()}})}});
  const data = await res.json();
  state = data.state;
  draw();
}}
async function loadState() {{
  const res = await fetch("/api/state", {{cache: "no-store"}});
  state = await res.json();
  draw();
}}
for (const id of sliderIds) {{
  document.addEventListener("input", event => {{
    if (event.target && event.target.id === id) {{
      syncSliderLabels();
    }}
  }});
}}
draw();
setInterval(loadState, 500);
</script>
</body>
</html>
"""


DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} Dashboard</title>
  <style>
    :root {{ font-family: Arial, sans-serif; color: #171717; background: #f6f3ee; }}
    body {{ margin: 0; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 26px 18px 42px; }}
    header {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 18px; }}
    h1 {{ margin: 0; font-size: 30px; }}
    h2 {{ margin: 0 0 10px; font-size: 18px; }}
    a {{ color: #111; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .panel {{ background: white; border: 1px solid #ddd6cc; border-radius: 8px; padding: 16px; }}
    .wide {{ grid-column: span 2; }}
    .full {{ grid-column: 1 / -1; }}
    .metric {{ font-size: 30px; font-weight: 700; margin-top: 8px; }}
    .muted {{ color: #655d54; }}
    pre {{ white-space: pre-wrap; background: #fbfaf8; border: 1px solid #e6ded4; border-radius: 8px; padding: 12px; margin: 0; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; border-bottom: 1px solid #eee6dc; padding: 8px; vertical-align: top; }}
    th {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #655d54; }}
    button {{ border: 0; border-radius: 8px; padding: 10px 13px; background: #111; color: white; font-weight: 700; cursor: pointer; }}
    input {{ padding: 9px; border: 1px solid #cfc7bd; border-radius: 6px; width: 72px; }}
    @media (max-width: 800px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .wide, .full {{ grid-column: auto; }}
      header {{ display: block; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>{title} Dashboard</h1>
      <p class="muted">Live game-master view. Refreshes automatically.</p>
    </div>
    <p><a href="/">Open controller</a></p>
  </header>
  <section class="grid">
    <div class="panel"><h2>Game ID</h2><div class="metric" id="gameId">-</div></div>
    <div class="panel"><h2>Progress</h2><div class="metric" id="progress">-</div></div>
    <div class="panel"><h2>Button Presses</h2><div class="metric" id="presses">-</div></div>
    <div class="panel"><h2>Players</h2><div class="metric" id="playersMetric">-</div></div>
    <div class="panel"><h2>OpenAI Key</h2><div class="metric" id="openaiKey">-</div></div>
    <div class="panel wide">
      <h2>Printer Unit</h2>
      <pre id="hardwareStatus">No device check yet.</pre>
    </div>
    <div class="panel wide">
      <h2>Controls</h2>
      <pre id="controlSettings">-</pre>
    </div>
    <div class="panel wide">
      <h2>Next Step</h2>
      <pre id="nextStep">Loading...</pre>
    </div>
    <div class="panel wide">
      <h2>Last Printed Card</h2>
      <pre id="lastCard">No card yet.</pre>
    </div>
    <div class="panel wide">
      <h2>Persona Names</h2>
      <pre id="personaNames">-</pre>
    </div>
    <div class="panel wide">
      <h2>Reset Game</h2>
      <p class="muted">Use this when starting a new run.</p>
      <label>Players <input id="playersInput" type="number" min="1" max="12"></label>
      <button onclick="resetGame()">Reset</button>
    </div>
    <div class="panel full">
      <h2>Recent Print Log</h2>
      <table>
        <thead><tr><th>Step</th><th>Scenario</th><th>Printed Card</th></tr></thead>
        <tbody id="logRows"></tbody>
      </table>
    </div>
  </section>
</main>
<script>
function cardText(card) {{
  if (!card) return "No card yet.";
  return `${{card.title || ""}}\\n\\n${{card.body || ""}}\\n\\n${{card.footer || ""}}${{card.qr_url ? "\\n" + card.qr_url : ""}}`;
}}
function printText(item) {{
  if (!item) return "No print yet.";
  return item.preview || cardText(item.card);
}}
function stepText(step) {{
  if (!step) return "The configured scenario is complete.";
  return `${{step.phase || "Game"}}: ${{step.title || "Step"}}\\nKind: ${{step.kind || "text"}}\\n\\n${{step.text || ""}}`;
}}
async function loadState() {{
  const res = await fetch("/api/state", {{cache: "no-store"}});
  const state = await res.json();
  document.getElementById("gameId").textContent = state.game_id || "-";
  document.getElementById("progress").textContent = `${{state.cursor}}/${{state.total_steps}}`;
  document.getElementById("presses").textContent = state.presses || 0;
  document.getElementById("playersMetric").textContent = state.player_count || 0;
  document.getElementById("openaiKey").textContent = state.openai_api_key_configured ? "Set" : "Missing";
  const hardware = state.hardware || null;
  document.getElementById("hardwareStatus").textContent = hardware
    ? `Device: ${{hardware.device_id || "-"}}\\nStatus: ${{hardware.status || "-"}}\\nAccepted: ${{hardware.accepted ? "yes" : "no"}}\\nLast seen: ${{hardware.last_seen || "-"}}\\nMessage: ${{hardware.message || ""}}`
    : "No device check yet.";
  const settings = state.settings || {{}};
  document.getElementById("controlSettings").textContent = `AGE: ${{settings.age || 50}}\\nQUEERNESS: ${{settings.queerness || 50}}\\nDIVERSITY: ${{settings.diversity || 50}}`;
  document.getElementById("playersInput").value = state.player_count || 4;
  document.getElementById("nextStep").textContent = stepText(state.next_step);
  document.getElementById("lastCard").textContent = printText(state.last_print);
  document.getElementById("personaNames").textContent = (state.persona_names || []).join(", ") || "-";
  const rows = document.getElementById("logRows");
  rows.innerHTML = "";
  for (const item of (state.recent_log || []).slice().reverse()) {{
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${{Number(item.cursor) + 1}}</td><td>${{item.step?.phase || ""}}: ${{item.step?.title || ""}}</td><td><pre>${{printText(item.print)}}</pre></td>`;
    rows.appendChild(tr);
  }}
}}
async function resetGame() {{
  const player_count = Number(document.getElementById("playersInput").value || 4);
  await fetch("/api/reset", {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify({{player_count}})}});
  await loadState();
}}
loadState();
setInterval(loadState, 2500);
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
