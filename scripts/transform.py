"""Classify, then transform, every pigeon photo that hasn't been handled yet.

Stage 1 (Typesafe / Jev): one request, three Choice questions about
    pigeons/<name>.jpg — subject, setting, activity.
Stage 2 (script): pick the outfit from the setting (indoors = light, outdoors
    = knitwear) and the slogan from the activity. Saved with the
    classification in classifications/<name>.json.
Stage 3 (OpenAI): only if the subject is a pigeon, fill the prompt template
    and edit the photo into transformed/<name>.png.

Idempotent: a photo is done once it has a transform, or once it has been
classified as not-a-pigeon. Anything else is retried on the next run.
"""

import base64
import io
import json
import os
import pathlib
import random
import sys
import uuid

import requests
from openai import OpenAI
from PIL import Image, ImageOps

MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-2.5-sunburst")
SRC = pathlib.Path("pigeons")
OUT = pathlib.Path("transformed")
CLS = pathlib.Path("classifications")
TEMPLATE = pathlib.Path("prompts/christmas-pigeon.md").read_text()
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

# --- Creative direction. Edit freely. --------------------------------------

# Settings that get a light outfit instead of knitwear.
WARM_INSIDE = {"indoors"}

OUTFITS = {
    "light": {
        "garments": [
            "a lightweight red-and-green cotton holiday tee with a small printed Christmas pattern",
            "a festive red velvet vest with gold trim",
        ],
        "accessories": [
            "an oversized plaid Christmas bow tie",
            "a small jingle-bell collar",
            "a tiny red velvet ribbon bow",
        ],
        "count": 1,
    },
    "warm": {
        "garments": [
            "a chunky hand-knitted Christmas sweater with snowflake and tree patterns",
            "a red-and-green Fair Isle knitted Christmas sweater",
        ],
        "accessories": [
            "a striped knitted Christmas scarf",
            "miniature red earmuffs",
            "a Santa hat with white fur trim",
            "a plush reindeer antler headband",
        ],
        "count": 2,
    },
}

SLOGANS = {
    "eating": ["Merry Crumbmas", "All I Want for Christmas Is Crumbs", "All I Want for Christmas Is Coo"],
    "walking": ["Rockin' Around the Chirpmas Tree", "Coo Ho Ho!", "We Wish You a Merry Chirpmas"],
    "perched": ["Silent Flight, Holy Flight", "Season's Tweetings", "Merry Birdmas"],
    "flying": ["Jingle Birds", "Let It Crow", "Fleece Navidad"],
}

# ---------------------------------------------------------------------------

openai_client = OpenAI()
OUT.mkdir(exist_ok=True)
CLS.mkdir(exist_ok=True)


def is_done(p: pathlib.Path) -> bool:
    if (OUT / f"{p.stem}.png").exists():
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


def pick_direction(stem: str, setting, activity) -> dict:
    """Choose garment, accessories, and slogan. Seeded by filename so re-runs match."""
    rng = random.Random(stem)
    style = "light" if setting in WARM_INSIDE else "warm"
    outfit = OUTFITS[style]
    accessories = rng.sample(outfit["accessories"], outfit["count"])
    slogans = SLOGANS.get(activity) or [s for pool in SLOGANS.values() for s in pool]
    return {
        "style": style,
        "garment": rng.choice(outfit["garments"]),
        "accessories": accessories,
        "slogan": rng.choice(slogans),
    }


def build_prompt(d: dict) -> str:
    return (
        TEMPLATE.replace("{{GARMENT}}", d["garment"])
        .replace("{{SLOGAN}}", d["slogan"])
        .replace("{{ACCESSORIES}}", " and ".join(d["accessories"]))
    )


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


todo = [
    p
    for p in sorted(SRC.glob("*.jpg"), reverse=True)  # newest first
    if p.stat().st_size > 0 and not is_done(p)
][:MAX_PER_RUN]

if not todo:
    print("Nothing to do.")
    sys.exit(0)

failed = 0
for src in todo:
    print(f"-> {src.name}")
    try:
        # Stage 1: classify (reuse a saved result if there is one)
        cls_file = CLS / f"{src.stem}.json"
        if cls_file.exists():
            result = json.loads(cls_file.read_text())
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
        result["direction"] = pick_direction(
            src.stem, result.get("setting"), result.get("activity")
        )
        cls_file.write_text(json.dumps(result, indent=2))
        print(f"   direction: {json.dumps(result['direction'])}")

        # Stage 3: transform
        with open(src, "rb") as f:
            out = openai_client.images.edit(
                model=MODEL, image=f, prompt=build_prompt(result["direction"])
            )
        dest = OUT / f"{src.stem}.png"
        dest.write_bytes(base64.b64decode(out.data[0].b64_json))
        print(f"   ok: {dest}")
    except Exception as e:
        failed += 1
        print(f"   failed: {type(e).__name__}: {e}")

sys.exit(1 if failed == len(todo) else 0)
