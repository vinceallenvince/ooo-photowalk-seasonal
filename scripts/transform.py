"""Classify, then transform, every pigeon photo that hasn't been handled yet.

Stage 1 (Typesafe / Jev): one request, three Choice questions about
    pigeons/<name>.jpg — subject, setting, activity. Theme-independent.
Stage 2 (script): pick the theme's direction (style from the setting, phrase
    from the activity) using themes/<theme>/direction.json. Saved with the
    classification in classifications/<name>.json under directions.<theme>.
Stage 3 (OpenAI): only if the subject is a pigeon, fill
    themes/<theme>/prompt.md and edit the photo into
    transformed/<theme>/<name>.png.

Theme, highest precedence first: the photo's subfolder
(pigeons/<theme>/pigeon-*.jpg), the THEME env var, the theme whose "season"
covers the photo's date, then DEFAULT_THEME.

Idempotent: a photo is done for a theme once it has that theme's transform,
or once it has been classified as not-a-pigeon. Anything else is retried.
"""

import base64
import io
import json
import os
import pathlib
import random
import re
import sys
import uuid

import requests
from openai import OpenAI
from PIL import Image, ImageOps

MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-2.5-sunburst")
SRC = pathlib.Path("pigeons")
OUT = pathlib.Path("transformed")
CLS = pathlib.Path("classifications")
THEMES = pathlib.Path("themes")
DEFAULT_THEME = "christmas"
LEGACY_THEME = "christmas"  # PNGs directly in transformed/ predate themes
MAX_PER_RUN = 1  # cost guard: newest photo only

TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
TYPESAFE_KEY = os.environ.get("TYPESAFE_API_KEY")

# --- What Jev classifies. Option names are what come back. -----------------

QUESTIONS = {
    "subject": {
        "instructions": "What is the main subject of `photo`?",
        "criteria": {
            "pigeon": "A pigeon or rock dove is the main subject of the photo.",
            "other_bird": "A bird is the main subject, but it is not a pigeon.",
            "no_bird": "There is no bird in the photo.",
        },
    },
    "setting": {
        "instructions": "Where is the bird in `photo`?",
        "criteria": {
            "indoors": "Inside a building, store, mall, or other enclosed, heated space.",
            "subway": "A subway platform, train car, or underground station.",
            "street": "A city street, sidewalk, plaza, or parking lot.",
            "park": "A park, garden, lawn, or other green space.",
            "ledge": "A rooftop, ledge, windowsill, railing, sign, or wire.",
        },
    },
    "activity": {
        "instructions": "What is the bird in `photo` doing?",
        "criteria": {
            "eating": "Eating, pecking at food, or foraging.",
            "walking": "Walking or strutting.",
            "perched": "Standing still, resting, or perched.",
            "flying": "Taking off, landing, or in flight.",
        },
    },
}

# ---------------------------------------------------------------------------

openai_client = OpenAI()
OUT.mkdir(exist_ok=True)
CLS.mkdir(exist_ok=True)

_themes = {}


def load_theme(name: str) -> dict:
    """Load and validate themes/<name>/. Fails loudly before any OpenAI call."""
    if name in _themes:
        return _themes[name]
    folder = THEMES / name
    if not (folder / "direction.json").exists():
        raise SystemExit(f"Unknown theme {name!r}: no {folder}/direction.json")
    theme = json.loads((folder / "direction.json").read_text())
    theme["name"] = name
    theme["template"] = (folder / "prompt.md").read_text()

    used = set(re.findall(r"\{\{(\w+)\}\}", theme["template"]))
    declared = set(theme["placeholders"])
    if used != declared:
        raise SystemExit(f"Theme {name}: prompt uses {sorted(used)}, "
                         f"direction.json declares {sorted(declared)}")
    styles = theme["styles"]
    defaults = [k for k, st in styles.items() if st.get("default")]
    if len(defaults) != 1:
        raise SystemExit(f"Theme {name}: need exactly one default style, got {defaults}")
    if not any(theme["phrases"].values()):
        raise SystemExit(f"Theme {name}: no phrases")
    for key, st in styles.items():
        fills = set(st.get("pick", {})) | set(st.get("sample", {})) | {theme["phrase"]}
        for outfit in st.get("outfits") or [{}]:
            missing = {ph for ph in declared if ph.lower() not in fills | set(outfit)}
            if missing:
                raise SystemExit(f"Theme {name}, style {key}: can't fill {sorted(missing)}")
    _themes[name] = theme
    return theme


def theme_names() -> list:
    return sorted(d.name for d in THEMES.iterdir() if (d / "direction.json").exists())


def choose_theme(p: pathlib.Path) -> str:
    if p.parent != SRC:
        return p.parent.name
    if os.environ.get("THEME"):
        return os.environ["THEME"]
    m = re.match(r"pigeon-\d{4}(\d{2})(\d{2})-", p.name)
    if m:
        mmdd = f"{m[1]}-{m[2]}"  # Shortcut stamps local (New York) time
        for name in theme_names():
            season = load_theme(name).get("season")
            if season and season[0] <= mmdd <= season[1]:
                return name
    return DEFAULT_THEME


def output_path(stem: str, theme: str) -> pathlib.Path:
    return OUT / theme / f"{stem}.png"


def read_classification(cls_file: pathlib.Path) -> dict:
    """Read a classification, migrating the pre-theme `direction` key."""
    result = json.loads(cls_file.read_text())
    if "direction" in result:
        result.setdefault("directions", {}).setdefault(LEGACY_THEME, result.pop("direction"))
    return result


def is_done(p: pathlib.Path, theme: str) -> bool:
    if output_path(p.stem, theme).exists():
        return True
    if theme == LEGACY_THEME and (OUT / f"{p.stem}.png").exists():
        return True
    cls_file = CLS / f"{p.stem}.json"
    if cls_file.exists():
        subject = json.loads(cls_file.read_text()).get("subject")
        return subject is not None and subject != "pigeon"
    return False


def jpeg_for_typesafe(path: pathlib.Path) -> str:
    """Return base64 JPEG that fits Typesafe's 280–1568px per-side limits."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((1568, 1568))
    if min(img.size) < 280:
        scale = 280 / min(img.size)
        img = img.resize((round(img.width * scale), round(img.height * scale)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def choice_value(answer):
    """Pull the chosen option name out of an answer."""
    if isinstance(answer, str):
        return answer
    if isinstance(answer, dict):
        for key in ("choice", "answer", "value", "option", "result"):
            if isinstance(answer.get(key), str):
                return answer[key]
    return None


def classify(path: pathlib.Path) -> dict:
    ref = f"{uuid.uuid4()}-photo"
    body = {
        "model": "jev-latest",
        "state": {"photo": ref},
        "assets": {
            ref: {"type": "image", "format": "jpg", "data_base64": jpeg_for_typesafe(path)}
        },
        "questions": {
            name: {"type": "choice", **q} for name, q in QUESTIONS.items()
        },
    }
    r = requests.post(
        TYPESAFE_URL,
        json=body,
        headers={
            "Authorization": f"Bearer {TYPESAFE_KEY}",
            "TypeSafe-Danger-Zone-Images": "true",
        },
        timeout=120,
    )
    if not r.ok:
        raise RuntimeError(f"Typesafe {r.status_code}: {r.text[:500]}")
    answers = r.json().get("answers", {})
    print(f"   typesafe answers: {json.dumps(answers)[:800]}")
    result = {name: choice_value(answers.get(name)) for name in QUESTIONS}
    result["raw"] = answers
    return result


def pick_direction(theme: dict, stem: str, setting, activity) -> dict:
    """Choose the theme's style, picks, and phrase. Seeded by theme + filename
    so re-runs match."""
    rng = random.Random(f"{theme['name']}/{stem}")
    styles = theme["styles"]
    style = next(
        (k for k, st in styles.items() if setting in st.get("when_setting", [])),
        next(k for k, st in styles.items() if st.get("default")),
    )
    d = {"style": style}
    # An outfit bundles fields: a string is used as is, a list is sampled
    # (`counts` sets how many, default 1).
    if styles[style].get("outfits"):
        outfit = rng.choice(styles[style]["outfits"])
        counts = styles[style].get("counts", {})
        for key, value in sorted(outfit.items()):
            d[key] = value if isinstance(value, str) else rng.sample(value, counts.get(key, 1))
    for key, options in sorted(styles[style].get("pick", {}).items()):
        d[key] = rng.choice(options)
    for key, spec in sorted(styles[style].get("sample", {}).items()):
        d[key] = rng.sample(spec["from"], spec["count"])
    phrases = theme["phrases"]
    pool = phrases.get(activity) or [s for p in phrases.values() for s in p]
    d[theme["phrase"]] = rng.choice(pool)
    d["phrase"] = theme["phrase"]
    return d


def build_prompt(theme: dict, d: dict) -> str:
    prompt = theme["template"]
    for ph in theme["placeholders"]:
        value = d[ph.lower()]
        if isinstance(value, list):
            value = " and ".join(value)
        prompt = prompt.replace("{{" + ph + "}}", value)
    if "{{" in prompt:
        raise RuntimeError("unfilled placeholder in prompt")
    return prompt


def set_output(**values) -> None:
    """Hand results to later workflow steps."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a") as f:
        for k, v in values.items():
            f.write(f"{k}={str(v).replace(chr(10), ' ')}\n")


def notify_no_pigeon(path: pathlib.Path) -> None:
    key = os.environ.get("BARK_KEY")
    if not key:
        return
    photo_url = (
        "https://raw.githubusercontent.com/vinceallenvince/walk-and-hack/main/"
        f"pigeons/{path.name}"
    )
    try:
        r = requests.post(
            f"https://api.day.app/{key}",
            data={
                "title": "Pigeon not detected.",
                "body": "Tap to see the photo.",
                "url": photo_url,
                "group": "pigeons",
                "level": "timeSensitive",
            },
            timeout=15,
        )
        print(f"   sent no-pigeon notification ({r.status_code})")
    except Exception as e:
        print(f"   notification failed: {e}")


photos = sorted(
    [*SRC.glob("*.jpg"), *SRC.glob("*/*.jpg")], key=lambda p: p.name, reverse=True
)  # newest first
todo = []
for p in photos:
    if p.stat().st_size == 0:
        continue
    theme = choose_theme(p)
    load_theme(theme)
    if not is_done(p, theme):
        todo.append((p, theme))
todo = todo[:MAX_PER_RUN]

if not todo:
    print("Nothing to do.")
    sys.exit(0)

failed = 0
for src, theme_name in todo:
    theme = load_theme(theme_name)
    print(f"-> {src.name} ({theme_name})")
    try:
        # Stage 1: classify (reuse a saved result if there is one)
        cls_file = CLS / f"{src.stem}.json"
        if cls_file.exists():
            result = read_classification(cls_file)
        elif TYPESAFE_KEY:
            result = classify(src)
        else:
            result = {"subject": None}

        subject = result.get("subject")
        print(f"   subject: {subject}, setting: {result.get('setting')}, "
              f"activity: {result.get('activity')}")

        if subject is not None and subject != "pigeon":
            cls_file.write_text(json.dumps(result, indent=2))
            print("   not a pigeon, skipping transform")
            notify_no_pigeon(src)
            continue
        if subject is None:
            print("   no classification, transforming with defaults")

        # Stage 2: creative direction
        direction = pick_direction(
            theme, src.stem, result.get("setting"), result.get("activity")
        )
        result.setdefault("directions", {})[theme_name] = direction
        cls_file.write_text(json.dumps(result, indent=2))
        print(f"   direction: {json.dumps(direction)}")

        # Stage 3: transform
        prompt = build_prompt(theme, direction)
        with open(src, "rb") as f:
            out = openai_client.images.edit(model=MODEL, image=f, prompt=prompt)
        dest = output_path(src.stem, theme_name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(out.data[0].b64_json))
        print(f"   ok: {dest}")
        set_output(theme=theme_name, title=theme["title"],
                   phrase=direction[direction["phrase"]], path=dest)
    except Exception as e:
        failed += 1
        print(f"   failed: {type(e).__name__}: {e}")

sys.exit(1 if failed == len(todo) else 0)
