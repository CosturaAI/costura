"""Write llms.txt at the repository root from the documentation pages.

Each entry is the first `# ` heading of a Markdown page and its first non-empty paragraph,
grouped by directory. `--check` regenerates to memory and exits 1 when `llms.txt` differs.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "llms.txt"
BASE_URL = "https://github.com/CosturaAI/costura/blob/main/"
ROOT_FILES = ("README.md", "CONTRIBUTING.md", "SECURITY.md", "SUPPORT.md")
SUMMARY = (
    "Costura is self-hosted AI spend attribution: it imports read-only billing data from "
    "AI providers, attributes each dollar to a key, workspace or person, and checks the "
    "totals against each provider's own report. These pages are the project's "
    "documentation, served from the GitHub repository."
)
GROUP_TITLES = {
    ".": "Project",
    "docs": "Docs",
    "docs/architecture": "Architecture",
    "docs/operations": "Operations",
    "docs/product": "Product",
    "docs/security": "Security",
}
HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
TAG = re.compile(r"<[^>]+>")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
MAX_DESCRIPTION = 300
MIN_SENTENCE = 12


def pages() -> list[Path]:
    found = [ROOT / name for name in ROOT_FILES if (ROOT / name).exists()]
    found.extend(sorted((ROOT / "docs").rglob("*.md")))
    return found


def title_of(text: str, path: Path) -> str:
    match = HEADING.search(text)
    if match:
        return clean(match.group(1))
    return path.stem.replace("-", " ").replace("_", " ")


def clean(text: str) -> str:
    text = IMAGE.sub("", text)
    text = LINK.sub(r"\1", text)
    text = TAG.sub("", text)
    text = text.replace("`", "").replace("\u2026", "...")
    return " ".join(text.split())


def shorten(paragraph: str) -> str:
    kept: list[str] = []
    for sentence in SENTENCE.split(paragraph):
        if not kept and len(sentence) < MIN_SENTENCE:
            continue
        if kept and len(" ".join([*kept, sentence])) > MAX_DESCRIPTION:
            break
        kept.append(sentence)
    return " ".join(kept).rstrip(":")


def description_of(text: str) -> str:
    body = HEADING.split(text, maxsplit=1)[-1]
    for block in re.split(r"\n\s*\n", body):
        lines = [line.strip() for line in block.strip().splitlines()]
        if not lines:
            continue
        first = lines[0]
        if first.startswith(("#", "|", "```", "-", "*", ">", "<", "!", "Date:")):
            continue
        paragraph = clean(" ".join(lines))
        if paragraph:
            return shorten(paragraph)
    return ""


def group_of(path: Path) -> str:
    relative = path.relative_to(ROOT)
    if len(relative.parts) == 1:
        return "."
    return relative.parent.as_posix()


def render() -> str:
    groups: dict[str, list[str]] = {}
    for path in pages():
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT).as_posix()
        title = title_of(text, path)
        description = description_of(text)
        line = f"- [{title}]({BASE_URL}{relative})"
        if description:
            line += f": {description}"
        groups.setdefault(group_of(path), []).append(line)
    out = ["# Costura", "", f"> {SUMMARY}", ""]
    for group in sorted(groups, key=lambda key: (key != ".", key)):
        out.append(f"## {GROUP_TITLES.get(group, group)}")
        out.append("")
        out.extend(groups[group])
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 when llms.txt is stale")
    args = parser.parse_args(argv)
    content = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != content:
            print("llms.txt is stale: run `just docs::llms`", file=sys.stderr)
            return 1
        print("llms.txt is current")
        return 0
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
