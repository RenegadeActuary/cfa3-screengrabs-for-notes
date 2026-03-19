# Shopping Links Input Folder

Put your shopping URLs in text files inside this folder and any nested subfolders.

## File format

Use one of these formats per line:

- URL only
- URL | title
- URL | title | price | priority | tags | notes
- URL | title | price | priority | tags | notes | image_url | sizes

Examples:

```text
https://www.cos.com/
https://www2.hm.com/ | H&M homepage
https://www.example.com/item-123 | Linen shirt | 59.99 | high | summer,work | Good with navy pants
https://www.example.com/item-456 | Cotton tee | 29.99 | medium | basics | Great reviews | https://cdn.example.com/item-456.jpg | S,M,L
```

Live metadata fetch (title, image, current price, sizes) is best effort and may fail for sites that block automated requests.
When that happens, supply `price` and `image_url` manually in the line.

## Category logic

Category is inferred from subfolders under `shopping-links/`.

Example:

- `shopping-links/women/tops.txt` -> category `women / tops`
- `shopping-links/home/decor.txt` -> category `home / decor`

## Notes

- Lines starting with `#` are ignored.
- Empty lines are ignored.
- Bullet prefixes (`- `) are allowed.
- Markdown links `[title](url)` are supported.
