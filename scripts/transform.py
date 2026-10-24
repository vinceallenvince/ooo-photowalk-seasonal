"""Classify, then transform, every pigeon photo that hasn't been handled yet.

Stage 1 (Typesafe / Jev): classify pigeons/<name>.jpg with a Choice question.
    Result saved to classifications/<name>.json.
Stage 2 (OpenAI): only if the subject is a pigeon, edit the photo with
    prompts/christmas-pigeon.md and write transformed/<name>.png.

Idempotent: a photo is done once it has a transform, or once it has been
classified as not-a-pigeon. Anything else is retried on the next run.
"""

import base64
import io
import json
import os
import pathlib
import sys
import uuid

import requests
from openai import OpenAI
from PIL import Image, ImageOps

MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-2.5-sunburst")
SRC = pathlib.Path("pigeons")
OUT = pathlib.Path("transformed")
CLS = pathlib.Path("classifications")
PROMPT = pathlib.Path("prompts/christmas-pigeon.md").read_text()
MAX_PER_RUN = 1  # cost guard: newest photo only

TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
TYPESAFE_KEY = os.environ.get("TYPESAFE_API_KEY")

# Edit these to change what gets classified. Option names are what comes back.
SUBJECT_OPTIONS = {
    "pigeon": "A pigeon or rock dove is the main subject of the photo.",
    "other_bird": "A bird is the main subject, but it is not a pigeon.",
    "no_bird": "There is no bird in the photo.",
}

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
    """Pull the chosen option name out of an answer, whatever its shape."""
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
            "subject": {
                "type": "choice",
                "instructions": "What is the main subject of `photo`?",
                "criteria": SUBJECT_OPTIONS,
            }
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
    print(f"   typesafe answers: {json.dumps(answers)[:500]}")
    return {"subject": choice_value(answers.get("subject")), "raw": answers}


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
        # Stage 1: classify (skipped if no key, or already classified)
        cls_file = CLS / f"{src.stem}.json"
        if cls_file.exists():
            result = json.loads(cls_file.read_text())
        elif TYPESAFE_KEY:
            result = classify(src)
            cls_file.write_text(json.dumps(result, indent=2))
        else:
            result = {"subject": None}

        subject = result.get("subject")
        print(f"   subject: {subject}")
        if subject is not None and subject != "pigeon":
            print("   not a pigeon, skipping transform")
            continue
        if subject is None:
            print("   no classification, transforming anyway")

        # Stage 2: transform
        with open(src, "rb") as f:
            out = openai_client.images.edit(model=MODEL, image=f, prompt=PROMPT)
        dest = OUT / f"{src.stem}.png"
        dest.write_bytes(base64.b64decode(out.data[0].b64_json))
        print(f"   ok: {dest}")
    except Exception as e:
        failed += 1
        print(f"   failed: {type(e).__name__}: {e}")

sys.exit(1 if failed == len(todo) else 0)
