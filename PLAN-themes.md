# Plan: multiple themes

## Goal

Make the pipeline theme-agnostic, so the same repo can dress pigeons for Halloween, Christmas, or anything else. Ship **Halloween** first, since it's Oct 31, and keep Christmas working as it does today.

## What stays the same

- The iOS Shortcut upload to `pigeons/`
- Jev's classification of subject, setting, and activity. It's theme-independent, so it runs once per photo.
- The not-a-pigeon gate and its notification
- OpenAI image edit, Bark notifications, GitHub Pages gallery
- Idempotency: work out what's done from the files on disk, retry the rest

## Target layout

```
themes/
  christmas/
    prompt.md         # template, moved from prompts/christmas-pigeon.md
    direction.json    # outfits, accessories, slogans, rules (moved out of transform.py)
  halloween/
    prompt.md
    direction.json
pigeons/              # unchanged
classifications/      # one JSON per photo; Jev's answers + per-theme directions
transformed/
  christmas/          # existing PNGs move here
  halloween/
scripts/transform.py  # loads the active theme; no creative content in code
```

## Theme definition (`direction.json`)

Move the Christmas tables now in `transform.py` into data. Draft schema:

```json
{
  "name": "christmas",
  "title": "New Christmas pigeon 🎄",
  "placeholders": ["GARMENT", "SLOGAN", "ACCESSORIES"],
  "styles": {
    "light": { "when_setting": ["indoors"], "garments": ["..."], "accessories": ["..."], "count": 1 },
    "warm":  { "default": true,             "garments": ["..."], "accessories": ["..."], "count": 2 }
  },
  "slogans": {
    "eating": ["Merry Crumbmas", "..."],
    "walking": ["..."],
    "perched": ["..."],
    "flying": ["..."]
  }
}
```

- A style is chosen by matching `when_setting`, falling back to the `default` style.
- A slogan is chosen by activity, falling back to all slogans.
- Choices stay seeded by filename plus theme, so re-runs are stable.
- The script validates the theme on load: every placeholder in `prompt.md` must be fillable. If one isn't, fail loudly before calling OpenAI.

## Halloween theme (draft content)

The premise carries over unchanged: an ordinary pigeon, inexplicably in costume. The rule about warmer clothes outdoors is dropped, and costume is chosen by setting instead.

| Setting | Costume ideas |
|---|---|
| subway | bedsheet ghost, Phantom of the Opera mask and cape |
| street | witch hat and cape, pirate tricorn |
| park | scarecrow (straw hat, patched vest) |
| ledge | vampire cape with high collar, gargoyle |
| indoors | pumpkin costume, skeleton onesie |

Captions are chosen by activity, for example "Trick or Tweet", "Coo-dini", "Beak-a-Boo", "Feather Frightening", "The Coo-ning", "Bird of Prey-tend".

Write `themes/halloween/prompt.md` by adapting the Christmas prompt. Keep sections 1 (preservation), 2 (natural behavior), 5 (realism), and 7 (output) nearly verbatim. Rewrite 3 (costume) and 4 (props). Halloween costumes may not carry text, so make the caption optional per costume, or show it as a small tag or sign.

## Theme selection

Precedence, highest first:

1. **Per photo, from the path:** `pigeons/<theme>/pigeon-*.jpg`. The Shortcut gets an optional "Choose from Menu" step that sets the subfolder. Files directly in `pigeons/` use rule 2.
2. **Repo variable** `THEME`, overridable from GitHub settings on the phone.
3. **By date:** through Oct 31 it's Halloween, Nov 1 through Dec 31 it's Christmas, otherwise the repo default. Uses the photo's timestamp from its filename, in New York time, not the run time.

Ship rule 3 plus rule 2 first. Rule 1 needs a change to the Shortcut, so it can come later.

## Classification record

One file per photo; the directions are keyed by theme:

```json
{
  "subject": "pigeon",
  "setting": "ledge",
  "activity": "perched",
  "raw": { },
  "directions": {
    "christmas": { "garment": "...", "accessories": ["..."], "slogan": "..." },
    "halloween": { "costume": "...", "props": ["..."], "caption": "..." }
  }
}
```

Migration: rename the existing top-level `direction` to `directions.christmas`. The script should read both shapes during the transition.

## Done-ness

A photo is done **for a theme** when `transformed/<theme>/<stem>.png` exists, or when its classification says it isn't a pigeon. Re-theming an old photo then just means running with a different theme.

## Gallery (`index.html`)

- Read `transformed/<theme>/` for each theme from the Contents API, so multiple requests.
- Newest first across all themes, with an optional `?theme=halloween` filter.
- Optional small caption overlay with the theme or slogan, read from the classification JSON.
- Watch the limits: the Contents API lists at most 1,000 files per directory, and allows 60 unauthenticated requests per hour per viewer. If either starts to bite, have the workflow write a `gallery.json` manifest on each commit, and point the gallery at that.

## Notifications

- The title comes from `direction.json` (`title`).
- The body shows the slogan or caption, and tapping opens the image, same as today.

## Migration steps

1. Housekeeping:
   - Rename `.github/workflows/tramsform.yml` to `transform.yml`.
   - Delete the empty `[Text]` file at the repo root.
   - Remove the unused `NTFY_TOPIC` secret.
2. Move `prompts/christmas-pigeon.md` to `themes/christmas/prompt.md`.
3. Extract the Christmas tables from `transform.py` into `themes/christmas/direction.json`.
4. Refactor `transform.py` to load the theme, choose it (date, then `THEME`), and write to `transformed/<theme>/`.
5. `git mv transformed/*.png transformed/christmas/`. Update the classification JSON shape, keeping the old shape readable.
6. Update the workflow's notify step: theme-aware title, and find the new PNG in `transformed/**`.
7. Update `index.html` for the per-theme folders.
8. Add `themes/halloween/`.
9. Test:
   - Post a non-pigeon: get the rejection push and no transform.
   - Post a pigeon: get the Halloween output, push, and gallery entry.
   - Run with `THEME=christmas`: the same photo gets a Christmas version too.

## Acceptance criteria

- No creative content (outfits, slogans, costumes) left in Python.
- Adding a theme means adding a folder and nothing else.
- Existing Christmas images still show in the gallery, and their notification links still work.
- Re-running a photo for the same theme reproduces the same direction.
- Cost guard intact: at most one OpenAI call per run.

## Open questions

- Should one post produce every in-season theme, or just one? The default is just one.
- Should the Shortcut theme menu ship now or later?
- Rename the repo to something generic, like `pigeon-post`? It's deferred for now. If it happens, update the hardcoded repo path in `index.html`, `transform.py`, the workflow, and the Shortcut. The Pages URL changes too, so the home screen web app has to be re-added.
