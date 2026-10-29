# ooo-photowalk-xmas

Snap a pigeon on your iPhone. A minute later it's back on your phone, photorealistically dressed for Christmas. Halloween lives in its own repo, `ooo-photowalk-halloween`.

<table>
  <tr>
    <th>Before</th>
    <th>After</th>
  </tr>
  <tr>
    <td><img src="pigeons/pigeon-20261024-151001.jpg" alt="Original photo: a pigeon perched on a storefront awning" width="400"></td>
    <td><img src="transformed/pigeon-20261024-151001.png" alt="Same photo: the pigeon now wears a Fleece Navidad sweater and a Santa hat" width="400"></td>
  </tr>
</table>

## How it works

1. **Post:** The **Post Pigeon** iOS Shortcut (share sheet → Post Pigeon) converts the photo to JPEG, resizes it, strips GPS, and commits it to `pigeons/` through the GitHub Contents API.
2. **Classify:** The push triggers a GitHub Action. [Typesafe](https://docs.typesafe.ai/images) (Jev) answers three questions about the photo: is it a pigeon, where is it, and what is it doing.
3. **Gate:** Not a pigeon? You get a "Pigeon not detected." push and the run stops, so nothing is spent on image generation.
4. **Direct:** The script picks the outfit from the setting (indoors gets a light outfit, outdoors gets knitwear) and the slogan from the activity, using `themes/christmas/direction.json`.
5. **Transform:** OpenAI's image edit endpoint dresses the pigeon using `themes/christmas/prompt.md`, filled with that direction.
6. **Deliver:** The result is committed to `transformed/christmas/`, and a [Bark](https://github.com/Finb/Bark) push shows the slogan and opens the image when tapped.
7. **Browse:** Every transformed pigeon appears in the [gallery](https://vinceallenvince.github.io/ooo-photowalk-xmas/), an edge-to-edge feed served by GitHub Pages.

```
 iPhone
 ┌──────────────────────┐
 │ Photos → Share →     │
 │ "Post Pigeon"        │  JPEG · 1200px · no GPS
 │ (iOS Shortcut)       │
 └──────────┬───────────┘
            │ PUT /repos/.../contents/pigeons/pigeon-<timestamp>.jpg
            ▼
 GitHub repo ─────────────────────────────────────────────────────────────
 │  pigeons/*.jpg ──push──▶ GitHub Action: .github/workflows/transform.yml
 │                          scripts/transform.py
 │                               │
 │                               ▼
 │                     ┌───────────────────┐
 │                     │ Typesafe / Jev    │  subject · setting · activity
 │                     │ (classify)        │──▶ classifications/<name>.json
 │                     └─────────┬─────────┘
 │                    pigeon? ───┴─── no
 │                      │              │
 │                      ▼              ▼
 │           ┌───────────────────┐   Bark: "Pigeon not detected."
 │           │ pick outfit +     │     └─ tap ─▶ original photo (raw URL)
 │           │ slogan from scene │
 │           └─────────┬─────────┘
 │                     ▼
 │           ┌───────────────────┐
 │           │ OpenAI image edit │  themes/christmas/prompt.md (template)
 │           └─────────┬─────────┘
 │                     ▼
 │           transformed/christmas/<name>.png ── commit + push
 │                     │
 └─────────────────────┼───────────────────────────────────────────────────
                       ├──▶ Bark: "New Christmas pigeon 🎄 · “<slogan>”"
                       │      └─ tap ─▶ transformed image (raw URL)
                       │
                       └──▶ GitHub Pages gallery (index.html)
                              reads transformed/christmas/ via the GitHub API
                              vinceallenvince.github.io/ooo-photowalk-xmas/
```

## Repo layout

| Path | What it is |
|---|---|
| `pigeons/` | Originals, posted by the Shortcut |
| `classifications/` | Jev's answers and the chosen outfit, one JSON per photo |
| `transformed/christmas/` | Dressed-up results (PNG). PNGs directly in `transformed/` predate this layout and count as Christmas too. |
| `themes/christmas/prompt.md` | Image prompt template with `{{PLACEHOLDERS}}` |
| `themes/christmas/direction.json` | Title, outfits by setting, slogans by activity |
| `scripts/transform.py` | Classify → gate → direct → transform |
| `.github/workflows/transform.yml` | Runs the script on every push to `pigeons/`, then commits and notifies |
| `index.html` | The gallery |

## Setup

Repository secrets (Settings → Secrets and variables → Actions):

| Secret | Used for |
|---|---|
| `OPENAI_API_KEY` | Image edit |
| `TYPESAFE_API_KEY` | Classification |
| `BARK_KEY` | Push notifications (the device key only, not the URL) |
| `REPLICATE_API_KEY` | FLUX renders on Replicate |

## iOS Shortcut setup

### 1. Create a GitHub token

On your phone, open **https://github.com/settings/personal-access-tokens/new** in Safari and create a fine-grained token:

- **Expiration:** your call. Shorter is safer; when it expires, generate a new token and paste it into the `Authorization` header (action 8 below).
- **Repository access:** Only select repositories → `ooo-photowalk-xmas` (one token can cover every photowalk repo)
- **Permissions:** Repository permissions → **Contents → Read and write**

Copy the token right away, because GitHub shows it only once.

### 2. Build the Shortcut

Open **Shortcuts**, tap **+**, and name the shortcut **Post Pigeon**. In its details (ⓘ), turn on **Show in Share Sheet**.

The 📷 in each row opens a screenshot of that step, expanded to show its settings. The screenshots come from the old seasonal Shortcut, which had a theme menu between steps 5 and 6. This one doesn't, so skip the menu and **Menu Result**.

Add these actions in order, using the search bar at the bottom. Text in **bold** below means a variable pill: tap the field, then pick the variable from the bar above the keyboard. Don't type it in brackets.

| # | Action | Settings | |
|---|---|---|---|
| 1 | *Receive* (auto-added) | Receive **Apps and Images** from **Share Sheet** · If there's no input: **Ask For** **Photos** | [📷](docs/shortcut/steps-01-04.png) |
| 2 | Convert Image | Convert **Shortcut Input** to **JPEG** · Quality ~0.7 · **Preserve Metadata: off** (strips GPS) | [📷](docs/shortcut/steps-01-04.png) |
| 3 | Resize Image | Resize **Converted Image** to width **1200**, height auto | [📷](docs/shortcut/steps-01-04.png) |
| 4 | Base64 Encode | **Encode** **Resized Image** · Line Breaks: **None** | [📷](docs/shortcut/steps-04-06.png) |
| 5 | Format Date | **Current Date** · Date Format: **Custom** · `yyyyMMdd-HHmmss` | [📷](docs/shortcut/steps-04-06.png) |
| 6 | Text | `pigeons/pigeon-`**Formatted Date**`.jpg` | [📷](docs/shortcut/steps-07-08.png) |
| 7 | Get Contents of URL | see below | [📷](docs/shortcut/steps-07-08.png) |
| 8 | Get Dictionary Value | Get **Value** for `content` in **Contents of URL** | [📷](docs/shortcut/steps-08-11.png) |
| 9 | Get Dictionary Value | Get **Value** for `download_url` in **Dictionary Value** | [📷](docs/shortcut/steps-08-11.png) |
| 10 | Copy to Clipboard | **Dictionary Value** | [📷](docs/shortcut/steps-10-12.png) |
| 11 | Show Notification | `🐦 Posted` | [📷](docs/shortcut/steps-10-12.png) |

**Step 7, Get Contents of URL** ([method and headers](docs/shortcut/steps-07-08.png), [request body](docs/shortcut/steps-08-11.png)):

- **URL:** `https://api.github.com/repos/vinceallenvince/ooo-photowalk-xmas/contents/`**Text**
- **Method:** `PUT`
- **Headers:**
  - `Authorization`: `Bearer <your token>`, with the word `Bearer`, a space, then the token
  - `Accept`: `application/vnd.github+json`
- **Request Body:** JSON
  - `message`: `Add pigeon`
  - `content`: **Base64 Encoded**
  - `branch`: `main`

### 3. Use it

In Photos, tap **Share → Post Pigeon**. The raw image URL lands on your clipboard, and about a minute later a Bark push brings the dressed-up pigeon.

### Troubleshooting

- **The file is 0 bytes:** step 4's input isn't **Resized Image**. A common slip is the pill landing in the Encode/Decode slot instead of the input slot. Delete the action, re-add it, then re-link `content` in step 7.
- **The filename shows `[Formatted Date]` or `[Text]` literally:** a variable was typed instead of inserted. Clear it and insert the pill.
- **The filename is `pigeon-.jpg`:** step 5 has no date. Set it to **Current Date**.
- **The first run worked, later runs fail:** a fixed filename collided with an existing file, because GitHub rejects a PUT to a path that already exists without that file's `sha`. Fix the date variable in step 6.
- **401 or 404 from GitHub:** check the `Bearer ` prefix, the token's repo access, and that it hasn't expired.

## Tweaks

- **Outfits, slogans, and rules:** edit `themes/christmas/direction.json`.
- **Regenerate a pigeon:** delete its PNG in `transformed/christmas/` (or `transformed/` for the oldest ones) and run the workflow (Actions → Run workflow).
- **Force a rejected photo through:** delete its JSON in `classifications/` and run the workflow.
- **Compare renderers:** `RENDERERS` picks who renders, from `openai` and `flux` (a FLUX.2 model on Replicate, `flux-2-max` by default; set the repo variable `FLUX_MODEL` to try another, e.g. `black-forest-labs/flux-2-flex`). Both get the same prompt; FLUX writes `<name>--flux.png` next to the OpenAI image, and each sends its own push. Default `openai`; set the repo variable `RENDERERS` to `openai,flux` or use the Run workflow box to add FLUX.
- **Cost guard:** each run handles only the newest unprocessed photo (`MAX_PER_RUN = 1`), with one render per renderer.
