# CLAUDE.md

Guidance for coding agents working in this repo. See `README.md` for what the app does and `PLAN-themes.md` for the planned multi-theme refactor.

## Ownership and style

- The owner is Vince. He's experienced, prefers tight and punchy prose, and often works from his phone.
- Keep answers and commit messages short.
- Edits often get pasted into github.com on mobile. Prefer small, self-contained changes, and say exactly which file and line changed.

## Architecture in one breath

iOS Shortcut ("Post Pigeon") → GitHub Contents API → `pigeons/pigeon-yyyyMMdd-HHmmss.jpg` → push triggers `.github/workflows/tramsform.yml` → `scripts/transform.py`:

1. Classify with Typesafe/Jev: subject, setting, activity.
2. Gate: if it's not a pigeon, send a Bark push and stop.
3. Pick the outfit and slogan from the scene.
4. Run the OpenAI image edit with `prompts/christmas-pigeon.md`, filled in.
5. Write `transformed/<stem>.png`.

The workflow then commits, pushes, and sends the success push through Bark. `index.html`, served by GitHub Pages, lists `transformed/` through the GitHub API.

## Key facts

- **Workflow filename:** it really is `tramsform.yml`, a typo. Renaming it is in the plan; until then, don't create a second workflow by accident.
- **Stray file:** the empty `[Text]` at the root is junk from Shortcut debugging and is safe to delete.
- **Secrets:**
  - `OPENAI_API_KEY`, `TYPESAFE_API_KEY`, and `BARK_KEY` are used.
  - `NTFY_TOPIC` is obsolete; ntfy was dropped because iOS banners didn't work.
  - Never print secrets. Action logs are public.
- **Models:**
  - Image edit uses `IMAGE_MODEL`, set in the workflow, currently `gpt-image-2.5-sunburst`.
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
  - A photo is done once `transformed/<stem>.png` exists, or once its `classifications/<stem>.json` says it isn't a pigeon.
  - To regenerate, delete the PNG. To force a rejected photo through, delete the JSON.
- **Cost guard:** `MAX_PER_RUN = 1`, newest photo first. Don't raise it without asking, since every OpenAI edit costs money.
- **Determinism:** outfit choices are seeded by filename, so re-runs pick the same outfit.
- **No loops:** bot commits use `GITHUB_TOKEN`, so they don't retrigger the workflow. The workflow does `git pull --rebase` before pushing, because the Shortcut may commit at the same time.
- **Hardcoded repo path:** `vinceallenvince/walk-and-hack` appears in `index.html`, `scripts/transform.py`, the workflow, and the iOS Shortcut. Update all of them on a rename.
- **Gallery limits:**
  - The Contents API allows 60 unauthenticated requests per hour per viewer, and lists at most 1,000 files per directory.
  - Raw URLs can be cached briefly by GitHub's CDN, so never overwrite a filename; write new ones.

## Working on it

- **Syntax checks before handing off:** `python3 -m py_compile scripts/transform.py` and `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/tramsform.yml'))"`.
- **Local dry runs:** stub `openai` (or skip stage 3), then exercise `pick_direction()` and `build_prompt()`. Assert that no `{{` placeholders remain.
- **Real runs:** they happen in Actions. Trigger one by posting a photo, or with Actions → Run workflow (`workflow_dispatch`).
- **Prompt files are creative direction owned by Vince.** Keep his wording; change structure only when asked.
- **Don't** add snow, decorations, or scene changes to prompts. "Preserve the original photo" is the top rule.
