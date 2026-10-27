# CLAUDE.md

Guidance for coding agents working in this repo. See `README.md` for what the app does and `PLAN-themes.md` for the multi-theme design.

## Ownership and style

- The owner is Vince. He's experienced, prefers tight and punchy prose, and often works from his phone.
- Keep answers and commit messages short.
- Edits often get pasted into github.com on mobile. Prefer small, self-contained changes, and say exactly which file and line changed.

## Architecture in one breath

iOS Shortcut ("Post Pigeon") → GitHub Contents API → `pigeons/pigeon-yyyyMMdd-HHmmss.jpg` → push triggers `.github/workflows/transform.yml` → `scripts/transform.py`:

1. Classify with Typesafe/Jev: subject, setting, activity.
2. Gate: if it's not a pigeon, send a Bark push and stop.
3. Choose the theme (photo subfolder, then `THEME`, then the date against each theme's `season`), then the outfit and slogan from `themes/<theme>/direction.json`.
4. Run the OpenAI image edit with `themes/<theme>/prompt.md`, filled in. The theme is validated first.
5. Write `transformed/<theme>/<stem>.png`.

The workflow then commits, pushes, and sends the success push through Bark, using the step outputs from the script. `index.html`, served by GitHub Pages, lists `transformed/` and each theme folder through the GitHub API.

## Key facts

- **No creative content in Python.** Outfits, slogans, and costumes live in `themes/`. Adding a theme means adding a folder.
- **Legacy PNGs:** files directly in `transformed/` predate themes and count as Christmas. They stay put so old notification links and the README keep working.
- **Secrets:**
  - `OPENAI_API_KEY`, `TYPESAFE_API_KEY`, `BARK_KEY`, and `REPLICATE_API_KEY` are used.
  - `NTFY_TOPIC` is obsolete; ntfy was dropped because iOS banners didn't work.
  - Never print secrets. Action logs are public.
- **Models:**
  - Image edit uses `IMAGE_MODEL`, set in the workflow, currently `gpt-image-2.5-sunburst`.
  - FLUX renders use `FLUX_MODEL` on Replicate, currently `black-forest-labs/flux-2-max`; override with the repo variable `FLUX_MODEL` (FLUX.2 models only: they share the `input_images` input). The photo goes in as its raw GitHub URL; output becomes `<stem>--flux.png`.
  - `RENDERERS` (default `openai`; add `flux` to compare) picks which run. A photo is done when every renderer's output exists; a retry renders only what's missing.
  - Classification uses `jev-latest`.
- **Typesafe image API:**
  - Every request needs the `TypeSafe-Danger-Zone-Images: true` header.
  - Images must be PNG or JPEG, 280–1568 px per side; the API rejects rather than resizes. `jpeg_for_typesafe()` handles this.
  - Choice answers come back as `{"type":"choice","choice":"<option>","confidence":...,"probabilities":{...}}`.
  - Docs: https://docs.typesafe.ai/images (marked "Dreamer-ready", so the format may change).
- **Bark:**
  - POST to `https://api.day.app/<BARK_KEY>` with form fields `title`, `body`, `url` (opens on tap), `group`, `level=timeSensitive`.
  - No image attachments.
- **Idempotency:**
  - A photo is done for a theme once `transformed/<theme>/<stem>.png` exists, or once its `classifications/<stem>.json` says it isn't a pigeon.
  - To regenerate, delete the PNG. Old classifications with a top-level `direction` are read as `directions.christmas`. To force a rejected photo through, delete the JSON.
- **Publishing (vinceallen.com):** the gallery's Publish link opens an issue titled `publish transformed/halloween/pigeon-….png` (or `unpublish …`). `.github/workflows/publish.yml` (owner's issues only) runs `scripts/publish.py`, which copies the render to `published/` and records it in `published.json`, newest first. vinceallen.com reads that manifest. `transformed/` is never touched.
- **Cost guard:** `MAX_PER_RUN = 1`, newest photo first, one render per renderer. Don't raise it without asking, since every OpenAI and FLUX render costs money.
- **Determinism:** choices are seeded by theme plus filename, so re-runs pick the same direction.
- **No loops:** bot commits use `GITHUB_TOKEN`, so they don't retrigger the workflow. The workflow does `git pull --rebase` before pushing, because the Shortcut may commit at the same time.
- **Hardcoded repo path:** `vinceallenvince/walk-and-hack` appears in `index.html`, `scripts/transform.py`, the workflow, and the iOS Shortcut. Update all of them on a rename.
- **Gallery limits:**
  - The Contents API allows 60 unauthenticated requests per hour per viewer, and lists at most 1,000 files per directory.
  - Raw URLs can be cached briefly by GitHub's CDN, so never overwrite a filename; write new ones.

## Working on it

- **Syntax checks before handing off:** `python3 -m py_compile scripts/transform.py` and `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/transform.yml'))"`.
- **Local dry runs:** stub `openai` (or skip stage 3), then exercise `pick_direction()` and `build_prompt()`. Assert that no `{{` placeholders remain.
- **Real runs:** they happen in Actions. Trigger one by posting a photo, or with Actions → Run workflow (`workflow_dispatch`).
- **Prompt files are creative direction owned by Vince.** Keep his wording; change structure only when asked.
- **Don't** add snow, decorations, or scene changes to prompts. "Preserve the original photo" is the top rule.
