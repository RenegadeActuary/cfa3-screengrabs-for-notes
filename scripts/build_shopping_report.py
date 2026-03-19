from __future__ import annotations

import argparse
import csv
import html
import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "shopping-links"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "shopping-report"
SUPPORTED_EXTENSIONS = {".txt"}

URL_PATTERN = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)", re.IGNORECASE)
JSON_LD_PATTERN = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
TITLE_TAG_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class ShoppingItem:
    item_id: int
    url: str
    title: str
    store: str
    category: str
    list_name: str
    price: str
    priority: str
    tags: str
    notes: str
    source_file: str
    line_number: int
    current_price: str
    currency: str
    image_url: str
    sizes: str
    fetch_error: str


@dataclass
class ParseResult:
    url: str
    title: str
    price: str
    priority: str
    tags: str
    notes: str
    image_url: str
    sizes: str


@dataclass
class ProductMetadata:
    title: str
    price: str
    currency: str
    image_url: str
    sizes: str
    error: str


def humanize_name(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip()


def clean_host(url: str) -> str:
    host = urlparse(url).netloc.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def infer_store_name(url: str) -> str:
    host = clean_host(url)
    if "cos.com" in host or "cosstores" in host:
        return "COS"
    if "hm.com" in host:
        return "H&M"

    parts = host.split(".") if host else []
    if not parts:
        return "Unknown"

    candidate = parts[0]
    if candidate in {"www", "www2", "m"} and len(parts) > 1:
        candidate = parts[1]

    return candidate.upper()


def is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def parse_markdown_link(text: str) -> tuple[str, str] | None:
    match = MARKDOWN_LINK_PATTERN.fullmatch(text.strip())
    if not match:
        return None
    title, url = match.group(1).strip(), match.group(2).strip()
    return url, title


def parse_first_segment(segment: str) -> tuple[str, str]:
    segment = segment.strip()

    markdown = parse_markdown_link(segment)
    if markdown:
        url, title = markdown
        return url, title

    url_match = URL_PATTERN.search(segment)
    if not url_match:
        raise ValueError("No URL found")

    url = url_match.group(0).strip()
    remainder = (segment[: url_match.start()] + segment[url_match.end() :]).strip(" -")
    return url, remainder


def parse_line(raw_line: str) -> ParseResult | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None

    if line.startswith("- "):
        line = line[2:].strip()

    if "|" in line:
        parts = [part.strip() for part in line.split("|")]
        url, inferred_title = parse_first_segment(parts[0])
        title = parts[1] if len(parts) > 1 and parts[1] else inferred_title
        price = parts[2] if len(parts) > 2 else ""
        priority = parts[3] if len(parts) > 3 else ""
        tags = parts[4] if len(parts) > 4 else ""
        notes = parts[5] if len(parts) > 5 else ""
        image_url = parts[6] if len(parts) > 6 else ""
        sizes = parts[7] if len(parts) > 7 else ""
    else:
        url, inferred_title = parse_first_segment(line)
        title = inferred_title
        price = ""
        priority = ""
        tags = ""
        notes = ""
        image_url = ""
        sizes = ""

    if not is_valid_url(url):
        raise ValueError(f"Invalid URL: {url}")

    if not title:
        parsed = urlparse(url)
        title = parsed.path.strip("/").split("/")[-1] or parsed.netloc

    return ParseResult(
        url=url,
        title=title,
        price=price,
        priority=priority.lower(),
        tags=tags,
        notes=notes,
        image_url=image_url,
        sizes=sizes,
    )


def generated_title_from_url(url: str) -> str:
    parsed = urlparse(url)
    tail = parsed.path.strip("/").split("/")[-1]
    return tail or parsed.netloc


def is_generated_title(title: str, url: str) -> bool:
    return title.strip().lower() == generated_title_from_url(url).strip().lower()


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def extract_meta_content(document: str, key: str) -> str:
    escaped_key = re.escape(key)
    patterns = [
        rf"<meta[^>]+(?:property|name|itemprop)\s*=\s*['\"]{escaped_key}['\"][^>]+content\s*=\s*['\"]([^'\"]+)['\"][^>]*>",
        rf"<meta[^>]+content\s*=\s*['\"]([^'\"]+)['\"][^>]+(?:property|name|itemprop)\s*=\s*['\"]{escaped_key}['\"][^>]*>",
    ]

    for pattern in patterns:
        match = re.search(pattern, document, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(1))
    return ""


def extract_html_title(document: str) -> str:
    match = TITLE_TAG_PATTERN.search(document)
    if not match:
        return ""
    return clean_text(match.group(1))


def parse_json_ld(document: str) -> list[Any]:
    parsed_nodes: list[Any] = []
    for raw_blob in JSON_LD_PATTERN.findall(document):
        blob = raw_blob.strip()
        if not blob:
            continue
        blob = blob.replace("<!--", "").replace("-->", "").strip()
        try:
            parsed_nodes.append(json.loads(blob))
        except json.JSONDecodeError:
            continue
    return parsed_nodes


def normalize_type(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.lower()]
    if isinstance(value, list):
        return [str(item).lower() for item in value]
    return []


def iter_product_nodes(node: Any):
    if isinstance(node, dict):
        node_types = normalize_type(node.get("@type"))
        if "product" in node_types:
            yield node

        for child in node.values():
            yield from iter_product_nodes(child)

    elif isinstance(node, list):
        for child in node:
            yield from iter_product_nodes(child)


def first_non_empty(values: list[str]) -> str:
    for value in values:
        if value:
            return value
    return ""


def stringify_size_values(raw: Any) -> list[str]:
    if isinstance(raw, str):
        cleaned = clean_text(raw)
        return [cleaned] if cleaned else []
    if isinstance(raw, list):
        values: list[str] = []
        for entry in raw:
            values.extend(stringify_size_values(entry))
        return values
    return []


def extract_sizes_from_product(product: dict[str, Any]) -> str:
    collected: list[str] = []

    for key in ["size", "sizes", "availableSize", "availableSizes"]:
        if key in product:
            collected.extend(stringify_size_values(product.get(key)))

    offers = product.get("offers")
    if isinstance(offers, list):
        offer_list = offers
    elif isinstance(offers, dict):
        offer_list = [offers]
    else:
        offer_list = []

    for offer in offer_list:
        if not isinstance(offer, dict):
            continue
        for key in ["size", "sizes", "availableSize", "availableSizes"]:
            if key in offer:
                collected.extend(stringify_size_values(offer.get(key)))

    deduped = list(dict.fromkeys(value for value in collected if value))
    return ", ".join(deduped)


def extract_price_and_currency_from_product(product: dict[str, Any]) -> tuple[str, str]:
    offers = product.get("offers")
    if isinstance(offers, list):
        offer_list = offers
    elif isinstance(offers, dict):
        offer_list = [offers]
    else:
        offer_list = []

    for offer in offer_list:
        if not isinstance(offer, dict):
            continue

        price = first_non_empty(
            [
                clean_text(str(offer.get("price", ""))),
                clean_text(str(offer.get("lowPrice", ""))),
                clean_text(str(offer.get("highPrice", ""))),
            ]
        )
        currency = clean_text(str(offer.get("priceCurrency", "")))
        if price:
            return price, currency

    return "", ""


def extract_image_from_product(product: dict[str, Any]) -> str:
    image = product.get("image")
    if isinstance(image, str):
        return clean_text(image)
    if isinstance(image, list):
        for candidate in image:
            if isinstance(candidate, str) and candidate.strip():
                return clean_text(candidate)
            if isinstance(candidate, dict) and candidate.get("url"):
                return clean_text(str(candidate["url"]))
    if isinstance(image, dict) and image.get("url"):
        return clean_text(str(image["url"]))
    return ""


def fetch_html(url: str, timeout_seconds: float = 20.0) -> tuple[str, str]:
    request = urllib.request.Request(url, headers=HTTP_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw_bytes = response.read()
            encoding = response.headers.get_content_charset() or "utf-8"
            try:
                text = raw_bytes.decode(encoding, errors="replace")
            except LookupError:
                text = raw_bytes.decode("utf-8", errors="replace")
            return text, ""
    except urllib.error.HTTPError as exc:
        return "", f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return "", f"URL error: {exc.reason}"
    except TimeoutError:
        return "", "Request timed out"


def resolve_metadata(url: str) -> ProductMetadata:
    document, error = fetch_html(url)
    if error:
        return ProductMetadata(title="", price="", currency="", image_url="", sizes="", error=error)

    meta_title = first_non_empty(
        [
            extract_meta_content(document, "og:title"),
            extract_meta_content(document, "twitter:title"),
            extract_html_title(document),
        ]
    )

    meta_price = first_non_empty(
        [
            extract_meta_content(document, "product:price:amount"),
            extract_meta_content(document, "price"),
        ]
    )

    meta_currency = first_non_empty(
        [
            extract_meta_content(document, "product:price:currency"),
            extract_meta_content(document, "priceCurrency"),
        ]
    )

    meta_image = first_non_empty(
        [
            extract_meta_content(document, "og:image"),
            extract_meta_content(document, "twitter:image"),
        ]
    )

    meta_sizes = ""

    for parsed_node in parse_json_ld(document):
        for product in iter_product_nodes(parsed_node):
            meta_title = first_non_empty([meta_title, clean_text(str(product.get("name", "")))])
            product_image = extract_image_from_product(product)
            if product_image:
                meta_image = first_non_empty([meta_image, product_image])

            product_price, product_currency = extract_price_and_currency_from_product(product)
            if product_price:
                meta_price = first_non_empty([meta_price, product_price])
                meta_currency = first_non_empty([meta_currency, product_currency])

            product_sizes = extract_sizes_from_product(product)
            if product_sizes:
                meta_sizes = first_non_empty([meta_sizes, product_sizes])

    if meta_image:
        meta_image = urljoin(url, meta_image)

    if meta_title:
        for separator in [" | ", " - "]:
            if separator in meta_title:
                meta_title = meta_title.split(separator, 1)[0].strip()
                break

    return ProductMetadata(
        title=meta_title,
        price=meta_price,
        currency=meta_currency,
        image_url=meta_image,
        sizes=meta_sizes,
        error="",
    )


def discover_input_files(input_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in input_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)
    files.sort(key=lambda p: p.as_posix().lower())
    return files


def category_from_file(input_dir: Path, file_path: Path) -> tuple[str, str]:
    relative = file_path.relative_to(input_dir)
    folder_parts = [humanize_name(part) for part in relative.parts[:-1]]
    list_name = humanize_name(relative.stem) or "General"

    category_parts = folder_parts.copy()
    if not category_parts or category_parts[-1].lower() != list_name.lower():
        category_parts.append(list_name)

    category = " / ".join(part for part in category_parts if part) or "General"
    return category, list_name


def collect_items(input_dir: Path, fetch_metadata: bool) -> tuple[list[ShoppingItem], list[str]]:
    items: list[ShoppingItem] = []
    warnings: list[str] = []
    next_id = 1

    metadata_cache: dict[str, ProductMetadata] = {}
    warned_url_failures: set[str] = set()

    for file_path in discover_input_files(input_dir):
        category, list_name = category_from_file(input_dir, file_path)
        lines = file_path.read_text(encoding="utf-8").splitlines()

        for line_number, raw_line in enumerate(lines, start=1):
            try:
                parsed = parse_line(raw_line)
            except ValueError as exc:
                if raw_line.strip() and not raw_line.strip().startswith("#"):
                    relative = file_path.relative_to(input_dir).as_posix()
                    warnings.append(f"{relative}:{line_number} - {exc}")
                continue

            if parsed is None:
                continue

            metadata = ProductMetadata("", "", "", "", "", "")
            if fetch_metadata:
                if parsed.url not in metadata_cache:
                    metadata_cache[parsed.url] = resolve_metadata(parsed.url)
                metadata = metadata_cache[parsed.url]

                if metadata.error and parsed.url not in warned_url_failures:
                    relative = file_path.relative_to(input_dir).as_posix()
                    warnings.append(
                        f"{relative}:{line_number} - Could not fetch metadata ({metadata.error})"
                    )
                    warned_url_failures.add(parsed.url)

            resolved_title = parsed.title
            if metadata.title and is_generated_title(parsed.title, parsed.url):
                resolved_title = metadata.title

            resolved_price = parsed.price or metadata.price
            resolved_image_url = parsed.image_url or metadata.image_url
            resolved_sizes = parsed.sizes or metadata.sizes

            items.append(
                ShoppingItem(
                    item_id=next_id,
                    url=parsed.url,
                    title=resolved_title,
                    store=infer_store_name(parsed.url),
                    category=category,
                    list_name=list_name,
                    price=parsed.price,
                    priority=parsed.priority,
                    tags=parsed.tags,
                    notes=parsed.notes,
                    source_file=file_path.relative_to(input_dir).as_posix(),
                    line_number=line_number,
                    current_price=resolved_price,
                    currency=metadata.currency,
                    image_url=resolved_image_url,
                    sizes=resolved_sizes,
                    fetch_error=metadata.error,
                )
            )
            next_id += 1

    return items, warnings


def write_csv(items: list[ShoppingItem], path: Path) -> None:
    fieldnames = list(asdict(items[0]).keys()) if items else [
        "item_id",
        "url",
        "title",
        "store",
        "category",
        "list_name",
        "price",
        "priority",
        "tags",
        "notes",
        "source_file",
        "line_number",
        "current_price",
        "currency",
        "image_url",
        "sizes",
        "fetch_error",
    ]

    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for item in items:
            writer.writerow(asdict(item))


def write_json(items: list[ShoppingItem], path: Path) -> None:
    payload = [asdict(item) for item in items]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_summary_counts(items: list[ShoppingItem], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = getattr(item, key)
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0].lower())))


def format_price_label(price: str, currency: str) -> str:
    cleaned_price = clean_text(price)
    cleaned_currency = clean_text(currency).upper()
    if not cleaned_price:
        return ""
    if cleaned_currency and cleaned_currency not in cleaned_price.upper():
        return f"{cleaned_price} {cleaned_currency}"
    return cleaned_price


def html_card(item: ShoppingItem) -> str:
    title = html.escape(item.title)
    store = html.escape(item.store)
    category = html.escape(item.category)
    list_name = html.escape(item.list_name)
    price_label = html.escape(format_price_label(item.current_price, item.currency))
    priority = html.escape(item.priority)
    tags = html.escape(item.tags)
    notes = html.escape(item.notes)
    sizes = html.escape(item.sizes)
    url = html.escape(item.url)
    image_url = html.escape(item.image_url)

    store_attr = html.escape(item.store.lower())
    category_attr = html.escape(item.category.lower())
    priority_attr = html.escape(item.priority.lower())

    badges: list[str] = [f'<span class="badge">{store}</span>', f'<span class="badge">{category}</span>']
    if price_label:
        badges.append(f'<span class="badge badge-price">price: {price_label}</span>')
    if priority:
        badges.append(f'<span class="badge badge-priority">priority: {priority}</span>')

    details: list[str] = [f"<p><strong>List:</strong> {list_name}</p>"]
    if sizes:
        details.append(f"<p><strong>Sizes:</strong> {sizes}</p>")
    if tags:
        details.append(f"<p><strong>Tags:</strong> {tags}</p>")
    if notes:
        details.append(f"<p><strong>Notes:</strong> {notes}</p>")

    if image_url:
        image_block = (
            f'<a class="thumb-link" href="{url}" target="_blank" rel="noopener noreferrer">'
            f'<img class="thumb" src="{image_url}" alt="{title}" loading="lazy" referrerpolicy="no-referrer" />'
            "</a>"
        )
    else:
        image_block = '<div class="thumb thumb-empty">No image found</div>'

    return "".join(
        [
            (
                f'<article class="card" data-store="{store_attr}" '
                f'data-category="{category_attr}" data-priority="{priority_attr}">'
            ),
            image_block,
            f'<h3><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></h3>',
            f'<div class="badges">{"".join(badges)}</div>',
            f'<div class="details">{"".join(details)}</div>',
            "</article>",
        ]
    )


def write_html(items: list[ShoppingItem], path: Path) -> None:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    stores = sorted({item.store for item in items}, key=lambda value: value.lower())
    categories = sorted({item.category for item in items}, key=lambda value: value.lower())

    store_options = "".join(
        f'<option value="{html.escape(store.lower())}">{html.escape(store)}</option>' for store in stores
    )
    category_options = "".join(
        f'<option value="{html.escape(category.lower())}">{html.escape(category)}</option>'
        for category in categories
    )

    store_summary_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>"
        for name, count in build_summary_counts(items, "store").items()
    )
    category_summary_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>"
        for name, count in build_summary_counts(items, "category").items()
    )

    cards_html = "".join(html_card(item) for item in items)

    html_content = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Shopping Canvas Report</title>
  <style>
    :root {{
      --bg-top: #f9efe4;
      --bg-bottom: #e6f0f4;
      --ink: #1f2630;
      --muted: #4f5d6c;
      --panel: #ffffffcc;
      --line: #ccd6df;
      --accent: #14698a;
      --accent-soft: #d3eef7;
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      font-family: \"Trebuchet MS\", \"Segoe UI\", sans-serif;
      color: var(--ink);
      background: linear-gradient(160deg, var(--bg-top), var(--bg-bottom));
      min-height: 100vh;
    }}

    .wrap {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px 16px 40px;
    }}

    .hero {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 20px;
      box-shadow: 0 12px 24px rgba(31, 38, 48, 0.08);
      margin-bottom: 18px;
    }}

    h1 {{ margin: 0 0 8px; font-size: 1.8rem; }}
    p {{ margin: 6px 0; color: var(--muted); }}

    .controls {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }}

    input, select, button {{
      width: 100%;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 10px;
      font-size: 0.95rem;
    }}

    button {{
      cursor: pointer;
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
      font-weight: 600;
    }}

    .stats {{
      margin-top: 10px;
      font-size: 0.95rem;
      color: var(--muted);
    }}

    .summary {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin: 18px 0;
    }}

    .summary-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
    }}

    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 6px; border-bottom: 1px solid var(--line); }}

    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
      gap: 12px;
    }}

    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      box-shadow: 0 10px 20px rgba(31, 38, 48, 0.06);
    }}

    .thumb-link {{ display: block; }}
    .thumb {{
      width: 100%;
      aspect-ratio: 4 / 5;
      object-fit: cover;
      border-radius: 10px;
      border: 1px solid var(--line);
      margin-bottom: 10px;
      background: #fff;
    }}

    .thumb-empty {{
      display: grid;
      place-items: center;
      font-size: 0.85rem;
      color: var(--muted);
      background: #f8fbfd;
    }}

    .card h3 {{ margin: 0 0 10px; font-size: 1rem; line-height: 1.3; }}
    .card h3 a {{ color: var(--ink); text-decoration: none; }}
    .card h3 a:hover {{ color: var(--accent); text-decoration: underline; }}

    .badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }}
    .badge {{
      font-size: 0.75rem;
      background: var(--accent-soft);
      color: #0c3f52;
      padding: 4px 8px;
      border-radius: 999px;
      border: 1px solid #acdff0;
    }}

    .badge-priority {{
      background: #f8e7d1;
      border-color: #f0c98d;
      color: #7d4c00;
    }}

    .badge-price {{
      background: #dff5e6;
      border-color: #b4e4c4;
      color: #184f2c;
    }}

    .details p {{ margin: 4px 0; font-size: 0.9rem; color: var(--muted); }}

    @media (max-width: 820px) {{
      .controls {{ grid-template-columns: 1fr 1fr; }}
      .summary {{ grid-template-columns: 1fr; }}
    }}

    @media (max-width: 520px) {{
      .controls {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 1.5rem; }}
    }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <section class=\"hero\">
      <h1>Shopping Canvas Report</h1>
      <p>Generated from local link files on {generated_at}</p>
      <p>Total items: <strong id=\"totalCount\">{len(items)}</strong> | Visible after filter: <strong id=\"visibleCount\">{len(items)}</strong></p>

      <div class=\"controls\">
        <input id=\"searchInput\" placeholder=\"Search title, tags, notes\" />
        <select id=\"storeFilter\">
          <option value=\"\">All stores</option>
          {store_options}
        </select>
        <select id=\"categoryFilter\">
          <option value=\"\">All categories</option>
          {category_options}
        </select>
        <button id=\"resetButton\" type=\"button\">Reset filters</button>
      </div>

      <div class=\"stats\">
        Live price/image fetch is best effort and may fail for blocked or JavaScript-only pages.
      </div>
    </section>

    <section class=\"summary\">
      <div class=\"summary-card\">
        <h2>By Store</h2>
        <table>
          <thead><tr><th>Store</th><th>Count</th></tr></thead>
          <tbody>{store_summary_rows}</tbody>
        </table>
      </div>
      <div class=\"summary-card\">
        <h2>By Category</h2>
        <table>
          <thead><tr><th>Category</th><th>Count</th></tr></thead>
          <tbody>{category_summary_rows}</tbody>
        </table>
      </div>
    </section>

    <section class=\"grid\" id=\"itemGrid\">
      {cards_html}
    </section>
  </div>

  <script>
    const searchInput = document.getElementById('searchInput');
    const storeFilter = document.getElementById('storeFilter');
    const categoryFilter = document.getElementById('categoryFilter');
    const resetButton = document.getElementById('resetButton');
    const visibleCount = document.getElementById('visibleCount');
    const cards = Array.from(document.querySelectorAll('.card'));

    function applyFilters() {{
      const query = searchInput.value.trim().toLowerCase();
      const store = storeFilter.value;
      const category = categoryFilter.value;

      let count = 0;

      cards.forEach((card) => {{
        const text = card.innerText.toLowerCase();
        const matchesQuery = !query || text.includes(query);
        const matchesStore = !store || card.dataset.store === store;
        const matchesCategory = !category || card.dataset.category === category;

        const show = matchesQuery && matchesStore && matchesCategory;
        card.style.display = show ? '' : 'none';
        if (show) count += 1;
      }});

      visibleCount.textContent = String(count);
    }}

    searchInput.addEventListener('input', applyFilters);
    storeFilter.addEventListener('change', applyFilters);
    categoryFilter.addEventListener('change', applyFilters);

    resetButton.addEventListener('click', () => {{
      searchInput.value = '';
      storeFilter.value = '';
      categoryFilter.value = '';
      applyFilters();
    }});
  </script>
</body>
</html>
"""

    path.write_text(html_content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a shopping report from URL lists")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="Folder containing URL list files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Folder where report files are written",
    )
    parser.add_argument(
        "--skip-url-fetch",
        action="store_true",
        help="Skip fetching URLs for live metadata (image, price, sizes)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = args.input.resolve()
    output_dir = args.output.resolve()

    if not input_dir.exists():
        raise FileNotFoundError(
            f"Input folder not found: {input_dir}. Create it and add URL files first."
        )

    items, warnings = collect_items(input_dir, fetch_metadata=not args.skip_url_fetch)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "items.csv"
    json_path = output_dir / "items.json"
    html_path = output_dir / "report.html"

    write_csv(items, csv_path)
    write_json(items, json_path)
    write_html(items, html_path)

    print(f"Scanned input folder: {input_dir}")
    print(f"Valid items: {len(items)}")
    print(f"URL metadata fetch enabled: {not args.skip_url_fetch}")
    print(f"CSV written: {csv_path}")
    print(f"JSON written: {json_path}")
    print(f"HTML report written: {html_path}")

    if warnings:
        print("\nWarnings:")
        for warning in warnings[:40]:
            print(f"- {warning}")
        if len(warnings) > 40:
            print(f"- ... {len(warnings) - 40} more")


if __name__ == "__main__":
    main()
