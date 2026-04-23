"""Index and log management for wiki/index.md and wiki/log.md."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import WIKI_SECTIONS
from .markdown import read_frontmatter


def rebuild_index(wiki_dir: Path) -> int:
    """Scan all wiki sub-directories and regenerate index.md.

    Returns the total number of pages cataloged.
    """
    lines: list[str] = ["# ZenWiki Index\n"]
    total = 0

    for section in WIKI_SECTIONS:
        section_dir = wiki_dir / section
        if not section_dir.is_dir():
            continue
        pages = sorted(section_dir.glob("*.md"))
        if not pages:
            continue

        lines.append(f"\n## {section}/\n")
        for page in pages:
            fm = read_frontmatter(page)
            title = fm.get("title", page.stem)
            lines.append(f"- [[{section}/{page.stem}]] — {title}")
            total += 1

    lines.append("")
    (wiki_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")
    return total


def append_log(wiki_dir: Path, message: str) -> None:
    """Append a timestamped entry to wiki/log.md."""
    log_path = wiki_dir / "log.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    if not log_path.exists():
        log_path.write_text("# ZenWiki Log\n\n", encoding="utf-8")

    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"- **[{now}]** {message}\n")


def status(wiki_dir: Path, raw_dir: Path) -> dict[str, Any]:
    """Return summary statistics about the wiki and raw directories."""
    info: dict[str, Any] = {"wiki_pages": {}, "raw_sources": {}, "total_wiki": 0, "total_raw": 0}

    for section in WIKI_SECTIONS:
        section_dir = wiki_dir / section
        count = len(list(section_dir.glob("*.md"))) if section_dir.is_dir() else 0
        info["wiki_pages"][section] = count
        info["total_wiki"] += count

    for section in ("papers", "articles", "notes", "docs"):
        section_dir = raw_dir / section
        if section_dir.is_dir():
            count = sum(
                1 for p in section_dir.iterdir()
                if p.is_file() and not p.name.startswith(".")
            )
        else:
            count = 0
        info["raw_sources"][section] = count
        info["total_raw"] += count

    info["has_index"] = (wiki_dir / "index.md").exists()
    info["has_log"] = (wiki_dir / "log.md").exists()
    return info
