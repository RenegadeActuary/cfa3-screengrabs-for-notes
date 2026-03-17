from pathlib import Path
import shutil
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = PROJECT_ROOT / "docs"
TARGET_ROOT = DOCS_ROOT / "screen-grabs"

# Default source for this monorepo layout.
DEFAULT_SOURCE = PROJECT_ROOT / "notes-screengrabs"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def list_images(source_root: Path) -> list[Path]:
    images: list[Path] = []
    for path in source_root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(path)
    images.sort(key=lambda p: p.as_posix().lower())
    return images


def copy_images(source_root: Path, target_root: Path, images: list[Path]) -> list[Path]:
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for image_path in images:
        relative_path = image_path.relative_to(source_root)
        destination = target_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_path, destination)
        copied.append(destination)
    return copied


def encoded_docs_path(path: Path) -> str:
    relative = path.relative_to(DOCS_ROOT).as_posix()
    return quote(relative, safe="/.-_")


def build_index(copied_images: list[Path]) -> str:
    lines: list[str] = []
    lines.append("# CFA Level III Screen Grabs")
    lines.append("")
    lines.append("Public image host for review markdown files.")
    lines.append("")

    if not copied_images:
        lines.append("No images found. Add files under your source folder and run the sync script again.")
        lines.append("")
        return "\n".join(lines)

    current_topic = None
    for path in copied_images:
        topic = path.parent.relative_to(TARGET_ROOT)
        topic_name = topic.as_posix() if str(topic) != "." else "root"
        if topic_name != current_topic:
            lines.append(f"## {topic_name}")
            lines.append("")
            current_topic = topic_name

        alt_text = path.stem.replace("_", " ")
        image_url = encoded_docs_path(path)
        lines.append(f"### [{path.name}]({image_url})")
        lines.append("")
        lines.append(f"![{alt_text}]({image_url})")
        lines.append("")
        lines.append(f"[Open full size]({image_url})")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    source_root = DEFAULT_SOURCE
    if not source_root.exists():
        raise FileNotFoundError(
            "Source folder not found. Expected at: "
            f"{source_root}. Create it or update DEFAULT_SOURCE."
        )

    DOCS_ROOT.mkdir(parents=True, exist_ok=True)
    images = list_images(source_root)
    copied = copy_images(source_root, TARGET_ROOT, images)

    index_content = build_index(copied)
    (DOCS_ROOT / "index.md").write_text(index_content, encoding="utf-8")

    print(f"Copied {len(copied)} images to {TARGET_ROOT}")
    print("Updated docs/index.md")


if __name__ == "__main__":
    main()
