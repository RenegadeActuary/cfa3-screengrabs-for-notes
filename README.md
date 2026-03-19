# Public Screen Grabs GitHub Pages

This folder is a standalone project for a new public GitHub Pages site that hosts screen grabs.

## Goal

Keep your existing encrypted study book unchanged while serving images publicly from a separate repository.

## Suggested New Repository

- `RenegadeActuary/cfa3-screengrabs-for-notes`

## One-Time Setup

1. Create a new **public** repository named `cfa3-screengrabs-for-notes` on GitHub.
2. Copy all files from this folder into the root of that new repository.
3. In the new repo settings, set Pages source to **GitHub Actions** if needed.
4. Push to `main` or `master`.
5. Wait for the `Deploy Public Screen Grabs` workflow to complete.

Your public base URL will be:

- `https://renegadeactuary.github.io/cfa3-screengrabs-for-notes/`

## Sync Images From Your Notes Folder

In this current monorepo layout, the sync script reads from:

- `Notes Screen Grabs/`

It preserves nested topic folders and writes to:

- `docs/screen-grabs/`

Run:

```bash
python scripts/sync_screen_grabs.py
```

Then commit and push in the new public repo.

## Markdown Link Pattern For Your Review Notes

Use absolute image URLs in your private/encrypted notes:

```markdown
![LM4 Duration Matching](https://renegadeactuary.github.io/cfa3-screengrabs-for-notes/screen-grabs/LM4%20Liability-Driven%20and%20Index-Based%20Strategies/your-image-file.png)
```

Tip: Spaces in folder and file names must be URL-encoded as `%20`.

## Shopping Links Canvas Report (MVP)

You can also use this repo to track shopping links in nested folders and generate a visual report.

Input folder:

- `shopping-links/`

Run:

```bash
python scripts/build_shopping_report.py
```

Outputs:

- `shopping-report/report.html` (visual report)
- `shopping-report/items.csv` (spreadsheet-style export)
- `shopping-report/items.json` (raw structured data)

The report attempts to fetch live metadata from each URL (title, image, current price, and sometimes sizes).
Some retailers block automated requests; when that happens, provide `price` and `image_url` directly in your input lines.

The script infers categories from folders and file names.

Examples:

- `shopping-links/women/tops.txt` -> `women / tops`
- `shopping-links/home/decor.txt` -> `home / decor`

For line format details, see `shopping-links/README.md`.
