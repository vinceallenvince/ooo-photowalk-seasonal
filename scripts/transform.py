"""Transform every pigeon photo that doesn't have a transformed version yet.

Reads pigeons/*.jpg, sends each to the OpenAI image edit endpoint with the
prompt in prompts/christmas-pigeon.md, and writes transformed/<name>.png.
Idempotent: re-running only processes photos that are still missing output,
so failed images get retried on the next push.
"""

import base64
import os
import pathlib
import sys

from openai import OpenAI

MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-2.5-sunburst")
SRC = pathlib.Path("pigeons")
OUT = pathlib.Path("transformed")
PROMPT = pathlib.Path("prompts/christmas-pigeon.md").read_text()
MAX_PER_RUN = 5  # cost guard

client = OpenAI()
OUT.mkdir(exist_ok=True)

todo = [
    p
    for p in sorted(SRC.glob("*.jpg"))
    if p.stat().st_size > 0 and not (OUT / f"{p.stem}.png").exists()
][:MAX_PER_RUN]

if not todo:
    print("Nothing to transform.")
    sys.exit(0)

failed = 0
for src in todo:
    print(f"-> {src.name}")
    try:
        with open(src, "rb") as f:
            result = client.images.edit(model=MODEL, image=f, prompt=PROMPT)
        out = OUT / f"{src.stem}.png"
        out.write_bytes(base64.b64decode(result.data[0].b64_json))
        print(f"   ok: {out}")
    except Exception as e:
        failed += 1
        print(f"   failed: {type(e).__name__}: {e}")

# Fail the run only if nothing succeeded, so partial successes still commit.
sys.exit(1 if failed == len(todo) else 0)
