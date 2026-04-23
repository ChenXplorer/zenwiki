"""Token Jaccard deduplication — find wiki pages similar to a given name."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .markdown import read_frontmatter


@dataclass
class SimilarMatch:
    path: str
    title: str
    score: float


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff\u3400-\u4dbf]+", re.UNICODE)


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _phrase_bonus(query_lower: str, candidate_lower: str) -> float:
    """Boost score when one string fully contains the other."""
    if query_lower == candidate_lower:
        return 1.0
    if query_lower in candidate_lower or candidate_lower in query_lower:
        return 0.85
    return 0.0


def find_similar(
    name: str,
    wiki_dir: Path,
    target_dirs: list[str] | None = None,
    threshold: float = 0.3,
    limit: int = 10,
) -> list[SimilarMatch]:
    """Find wiki pages whose title/aliases are similar to *name*.

    Scans frontmatter ``title`` and ``aliases`` fields.
    Uses token Jaccard similarity with a phrase-containment bonus.
    """
    from .config import WIKI_SECTIONS  # avoid circular at module level

    dirs = target_dirs or list(WIKI_SECTIONS)
    query_tokens = _tokenize(name)
    query_lower = name.strip().lower()

    matches: list[SimilarMatch] = []

    for section in dirs:
        section_dir = wiki_dir / section
        if not section_dir.is_dir():
            continue
        for md in section_dir.glob("*.md"):
            fm = read_frontmatter(md)
            title = fm.get("title", md.stem)
            aliases: list[str] = fm.get("aliases", []) or []
            candidates = [title, *aliases]

            best_score = 0.0
            for candidate in candidates:
                if not candidate:
                    continue
                cand_lower = candidate.strip().lower()
                phrase = _phrase_bonus(query_lower, cand_lower)
                if phrase > 0:
                    best_score = max(best_score, phrase)
                else:
                    jaccard = _jaccard(query_tokens, _tokenize(candidate))
                    best_score = max(best_score, jaccard)

            if best_score >= threshold:
                rel = f"{section}/{md.stem}"
                matches.append(SimilarMatch(path=rel, title=title, score=round(best_score, 3)))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches[:limit]
