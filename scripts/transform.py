"""Classify, then transform, every pigeon photo that hasn't been handled yet.

This repo is the Christmas mode: every photo gets THEME ("christmas").

Stage 1 (Typesafe / Jev): one request, three Choice questions about
    pigeons/<name>.jpg — subject, setting, activity.
Stage 2 (script): pick the theme's direction (style from the setting, phrase
    from the activity) using themes/<theme>/direction.json. Saved with the
    classification in classifications/<name>.json under directions.<theme>.
Stage 3 (renderers): only if the subject is a pigeon, fill
    themes/<theme>/prompt.md and edit the photo with each renderer in
    RENDERERS (default "openai"): OpenAI writes transformed/<theme>/<name>.png,
    FLUX on Replicate writes transformed/<theme>/<name>--flux.png. Same prompt,
    so the two can be compared side by side.

Idempotent: a photo is done for a theme once every renderer's output exists,
or once it has been classified as not-a-pigeon. Only missing outputs render.
"""

import base64
import io
import json
import os
import pathlib
import random
import re
import sys
import time
import uuid

import requests
from openai import OpenAI
from PIL import Image, ImageOps

MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-2.5-sunburst")
SRC = pathlib.Path("pigeons")
OUT = pathlib.Path("transformed")
CLS = pathlib.Path("classifications")
THEMES = pathlib.Path("themes")
THEME = "christmas"  # the one theme this repo renders
LEGACY_THEME = THEME  # PNGs directly in transformed/ predate themes
MAX_PER_RUN = 1  # cost guard: newest photo only (one render per renderer)
RENDERERS = [r.strip() for r in os.environ.get("RENDERERS", "openai").split(",") if r.strip()]
SUFFIX = {"openai": "", "flux": "--flux"}  # output filename suffix per renderer
if not RENDERERS or set(RENDERERS) - set(SUFFIX):
    raise SystemExit(f"RENDERERS must be a list of {sorted(SUFFIX)}, got {RENDERERS}")

REPLICATE_KEY = os.environ.get("REPLICATE_API_KEY")
FLUX_MODEL = os.environ.get("FLUX_MODEL", "black-forest-labs/flux-2-max")
RAW = "https://raw.githubusercontent.com/vinceallenvince/ooo-photowalk-xmas/main"

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


def output_path(stem: str, theme: str, renderer: str = "openai") -> pathlib.Path:
    return OUT / theme / f"{stem}{SUFFIX[renderer]}.png"


def has_output(stem: str, theme: str, renderer: str) -> bool:
    if output_path(stem, theme, renderer).exists():
        return True
    return renderer == "openai" and theme == LEGACY_THEME and (OUT / f"{stem}.png").exists()


def read_classification(cls_file: pathlib.Path) -> dict:
    """Read a classification, migrating the pre-theme `direction` key."""
    result = json.loads(cls_file.read_text())
    if "direction" in result:
        result.setdefault("directions", {}).setdefault(LEGACY_THEME, result.pop("direction"))
    return result


def is_done(p: pathlib.Path, theme: str) -> bool:
    if all(has_output(p.stem, theme, r) for r in RENDERERS):
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


def render_openai(src: pathlib.Path, prompt: str) -> bytes:
    with open(src, "rb") as f:
        out = openai_client.images.edit(model=MODEL, image=f, prompt=prompt)
    return base64.b64decode(out.data[0].b64_json)


def render_flux(src: pathlib.Path, prompt: str) -> bytes:
    """Run FLUX_MODEL on Replicate with the photo's raw GitHub URL as input."""
    if not REPLICATE_KEY:
        raise RuntimeError("REPLICATE_API_KEY is not set")
    auth = {"Authorization": f"Bearer {REPLICATE_KEY}"}
    r = requests.post(
        f"https://api.replicate.com/v1/models/{FLUX_MODEL}/predictions",
        json={"input": {
            "prompt": prompt,
            "input_images": [f"{RAW}/{src.as_posix()}"],
            "aspect_ratio": "match_input_image",
        }},
        headers={**auth, "Prefer": "wait=60"},
        timeout=90,
    )
    if not r.ok:
        raise RuntimeError(f"Replicate {r.status_code}: {r.text[:500]}")
    pred = r.json()
    poll = pred["urls"]["get"]
    deadline = time.time() + 300
    while pred["status"] not in ("succeeded", "failed", "canceled"):
        if time.time() > deadline:
            raise TimeoutError(f"Replicate prediction {pred.get('id')} still {pred['status']}")
        time.sleep(3)
        pred = requests.get(poll, headers=auth, timeout=30).json()
    if pred["status"] != "succeeded":
        raise RuntimeError(f"Replicate {pred['status']}: {pred.get('error')}")
    out = pred["output"]
    img = requests.get(out[0] if isinstance(out, list) else out, timeout=60)
    img.raise_for_status()
    buf = io.BytesIO()
    Image.open(io.BytesIO(img.content)).save(buf, format="PNG")
    return buf.getvalue()


RENDER = {"openai": render_openai, "flux": render_flux}


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
    photo_url = f"{RAW}/{path.as_posix()}"
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


load_theme(THEME)  # validate before anything else
photos = sorted(SRC.glob("*.jpg"), key=lambda p: p.name, reverse=True)  # newest first
todo = [(p, THEME) for p in photos if p.stat().st_size > 0 and not is_done(p, THEME)]
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

        # Stage 3: render with each renderer that hasn't produced output yet
        prompt = build_prompt(theme, direction)
        made, errors = [], 0
        for renderer in RENDERERS:
            if has_output(src.stem, theme_name, renderer):
                continue
            try:
                dest = output_path(src.stem, theme_name, renderer)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(RENDER[renderer](src, prompt))
                print(f"   ok ({renderer}): {dest}")
                made.append(dest.as_posix())
            except Exception as e:
                errors += 1
                print(f"   {renderer} failed: {type(e).__name__}: {e}")
        if made:
            set_output(theme=theme_name, title=theme["title"],
                       phrase=direction[direction["phrase"]], paths=" ".join(made))
        elif errors:
            raise RuntimeError("every renderer failed")
    except Exception as e:
        failed += 1
        print(f"   failed: {type(e).__name__}: {e}")

sys.exit(1 if failed == len(todo) else 0)
