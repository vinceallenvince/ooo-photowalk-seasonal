"""Publish or unpublish a render for vinceallen.com.

COMMAND is "publish <path>" or "unpublish <path>", where <path> is a render
under transformed/ (e.g. transformed/halloween/pigeon-20261025-090554.png).
It comes from an issue title (the gallery's Publish link) or workflow_dispatch.

Publishing copies the render to published/<theme>/<name> and records it in
published.json, newest first. transformed/ is never touched, so the render
still counts as done and old notification links keep working.
"""

import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "published.json"
LEGACY_THEME = "christmas"  # PNGs directly in transformed/ predate themes
COMMAND = re.compile(
    r"^(publish|unpublish)\s+"
    r"(transformed/(?:([a-z0-9-]+)/)?(pigeon-(\d{8})-(\d{6})(?:--(\w+))?\.png))\s*$"
)


def output(key, value):
    print(value)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"{key}={value}\n")


def phrase(stem, theme):
    """The slogan or caption chosen for this photo and theme, if any."""
    path = ROOT / "classifications" / f"{stem}.json"
    if not path.exists():
        return None
    c = json.loads(path.read_text())
    d = c.get("directions", {}).get(theme) or (theme == LEGACY_THEME and c.get("direction")) or {}
    return d.get(d.get("phrase", "slogan"))


def main():
    m = COMMAND.match(os.environ.get("COMMAND", "").strip())
    if not m:
        output("result", "Expected: publish|unpublish transformed/<theme>/pigeon-yyyyMMdd-HHmmss.png")
        sys.exit(1)
    action, src, theme, name, day, time, renderer = m.groups()
    theme = theme or LEGACY_THEME
    dest = f"published/{theme}/{name}"

    items = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []
    items = [i for i in items if i["file"] != dest]

    if action == "publish":
        if not (ROOT / src).exists():
            output("result", f"Not found: {src}")
            sys.exit(1)
        (ROOT / dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / src, ROOT / dest)
        stem = name.split("--")[0].removesuffix(".png")
        items.append({
            "file": dest,
            "created": f"{day[:4]}-{day[4:6]}-{day[6:]}T{time[:2]}:{time[2:4]}:{time[4:]}",
            "theme": theme,
            "renderer": renderer or "openai",
            "phrase": phrase(stem, theme),
        })
        result = f"Published {dest}"
    else:
        (ROOT / dest).unlink(missing_ok=True)
        result = f"Unpublished {dest}"

    items.sort(key=lambda i: (i["created"], i["file"]), reverse=True)
    MANIFEST.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n")
    output("result", result)


if __name__ == "__main__":
    main()
