import json
from pathlib import Path

PERSONAS_DIR = Path(__file__).parent


def load_persona(persona_id: str) -> dict | None:
    path = PERSONAS_DIR / f"{persona_id}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_personas() -> list[dict]:
    personas = []
    for path in sorted(PERSONAS_DIR.glob("*.json")):
        with open(path, "r", encoding="utf-8") as f:
            p = json.load(f)
        personas.append({
            "id": p["id"],
            "name": p["name"],
            "avatar": p["avatar"],
            "tagline": p["tagline"],
            "description": p["description"],
            "theme_color": p["theme_color"],
            "welcome_message": p.get("welcome_message", ""),
        })
    return personas
