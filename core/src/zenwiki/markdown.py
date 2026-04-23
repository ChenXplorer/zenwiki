"""Markdown utilities: frontmatter I/O, wikilink extraction, slugify."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

_FM_FENCE = "---"
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

def read_frontmatter(path: Path) -> dict[str, Any]:
    """Return the YAML frontmatter dict from a Markdown file (empty dict if none)."""
    text = path.read_text(encoding="utf-8")
    return parse_frontmatter(text)


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse YAML frontmatter from raw Markdown text."""
    stripped = text.lstrip("\ufeff")  # BOM
    if not stripped.startswith(_FM_FENCE):
        return {}
    end = stripped.find(f"\n{_FM_FENCE}", len(_FM_FENCE))
    if end == -1:
        return {}
    yaml_block = stripped[len(_FM_FENCE) + 1 : end]
    try:
        data = yaml.safe_load(yaml_block)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def write_frontmatter(path: Path, data: dict[str, Any]) -> None:
    """Rewrite the frontmatter of *path* in-place, preserving the body."""
    if path.exists():
        text = path.read_text(encoding="utf-8")
        body = strip_frontmatter(text)
    else:
        body = ""

    yaml_str = yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip("\n")
    new_text = f"---\n{yaml_str}\n---\n{body}"
    path.write_text(new_text, encoding="utf-8")


def strip_frontmatter(text: str) -> str:
    """Return the body of a Markdown file (everything after the frontmatter)."""
    stripped = text.lstrip("\ufeff")
    if not stripped.startswith(_FM_FENCE):
        return text
    end = stripped.find(f"\n{_FM_FENCE}", len(_FM_FENCE))
    if end == -1:
        return text
    after = end + 1 + len(_FM_FENCE)
    return stripped[after:].lstrip("\n")


# ---------------------------------------------------------------------------
# Wikilinks
# ---------------------------------------------------------------------------

def extract_wikilinks(text: str) -> list[str]:
    """Extract all ``[[target]]`` wikilinks from Markdown text (unique, ordered)."""
    seen: set[str] = set()
    result: list[str] = []
    for m in _WIKILINK_RE.finditer(text):
        target = m.group(1).strip()
        if target and target not in seen:
            seen.add(target)
            result.append(target)
    return result


# ---------------------------------------------------------------------------
# Slugify
# ---------------------------------------------------------------------------

_SLUG_UNSAFE = re.compile(r"[^a-z0-9\u4e00-\u9fff\u3400-\u4dbf]+")


def slugify(title: str) -> str:
    """Convert a title to a kebab-case slug suitable for filenames.

    Keeps CJK characters intact; strips accents from Latin chars.
    """
    s = unicodedata.normalize("NFKD", title)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = _SLUG_UNSAFE.sub("-", s)
    return s.strip("-")


def slugify_unique(title: str, existing: set[str]) -> str:
    """Generate a slug that doesn't collide with *existing* slugs."""
    base = slugify(title)
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"
