"""Deterministic lint rules for wiki health checks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .config import WIKI_SECTIONS
from .dedup import _jaccard, _tokenize as _dedup_tokenize
from .markdown import extract_wikilinks, read_frontmatter, write_frontmatter

RuleName = Literal[
    "broken_link",
    "missing_frontmatter",
    "orphan",
    "heading_structure",
    "empty_section",
    "thin_summary",
    "missing_backlink",
    "unverified_dedup",
    "link_to_deprecated",
    "thin_map",
    "incomparable_subjects",
]


@dataclass
class LintIssue:
    rule: RuleName
    path: str
    message: str
    fixable: bool = False


@dataclass
class LintReport:
    issues: list[LintIssue] = field(default_factory=list)
    fixed: int = 0

    @property
    def ok(self) -> bool:
        return len(self.issues) == 0


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _collect_pages(wiki_dir: Path) -> dict[str, Path]:
    """Map ``section/stem`` -> file path for all wiki pages."""
    pages: dict[str, Path] = {}
    for section in WIKI_SECTIONS:
        section_dir = wiki_dir / section
        if not section_dir.is_dir():
            continue
        for md in section_dir.glob("*.md"):
            pages[f"{section}/{md.stem}"] = md
    return pages


def _check_broken_links(pages: dict[str, Path]) -> list[LintIssue]:
    """Wikilinks pointing to non-existent pages."""
    all_stems = set(pages.keys())
    # Also index by bare stem for short-form links
    bare_stems = {key.split("/")[-1] for key in all_stems}
    issues: list[LintIssue] = []

    for key, path in pages.items():
        text = path.read_text(encoding="utf-8")
        for link in extract_wikilinks(text):
            if link in all_stems or link in bare_stems:
                continue
            issues.append(LintIssue(
                rule="broken_link",
                path=key,
                message=f"broken wikilink [[{link}]]",
            ))
    return issues


def _check_missing_frontmatter(pages: dict[str, Path]) -> list[LintIssue]:
    """Pages missing required ``title`` in frontmatter."""
    issues: list[LintIssue] = []
    for key, path in pages.items():
        fm = read_frontmatter(path)
        if not fm.get("title"):
            issues.append(LintIssue(
                rule="missing_frontmatter",
                path=key,
                message="missing or empty 'title' in frontmatter",
                fixable=True,
            ))
    return issues


def _check_orphan(pages: dict[str, Path]) -> list[LintIssue]:
    """Pages with zero inbound wikilinks (excluding index.md, log.md)."""
    inbound: dict[str, int] = {key: 0 for key in pages}
    bare_to_full: dict[str, str] = {}
    for key in pages:
        bare = key.split("/")[-1]
        bare_to_full[bare] = key

    for path in pages.values():
        text = path.read_text(encoding="utf-8")
        for link in extract_wikilinks(text):
            if link in inbound:
                inbound[link] += 1
            elif link in bare_to_full:
                inbound[bare_to_full[link]] += 1

    return [
        LintIssue(rule="orphan", path=key, message="no inbound wikilinks (orphan page)")
        for key, count in inbound.items()
        if count == 0
    ]


def _check_heading_structure(pages: dict[str, Path]) -> list[LintIssue]:
    """Heading levels that skip (e.g. # then ###)."""
    issues: list[LintIssue] = []
    for key, path in pages.items():
        text = path.read_text(encoding="utf-8")
        headings = _HEADING_RE.findall(text)
        prev_level = 0
        for hashes, title in headings:
            level = len(hashes)
            if prev_level > 0 and level > prev_level + 1:
                issues.append(LintIssue(
                    rule="heading_structure",
                    path=key,
                    message=f"heading level jumps from h{prev_level} to h{level} at '{title.strip()}'",
                ))
            prev_level = level
    return issues


def _check_empty_section(pages: dict[str, Path]) -> list[LintIssue]:
    """Heading followed immediately by another heading with no content."""
    issues: list[LintIssue] = []
    for key, path in pages.items():
        text = path.read_text(encoding="utf-8")
        headings = list(_HEADING_RE.finditer(text))
        for i, m in enumerate(headings[:-1]):
            next_m = headings[i + 1]
            between = text[m.end():next_m.start()].strip()
            if not between:
                issues.append(LintIssue(
                    rule="empty_section",
                    path=key,
                    message=f"empty section '{m.group(2).strip()}'",
                ))
    return issues


# --- New quality rules (P0-1) ---------------------------------------------

_TECH_DETAILS_HEADING_RE = re.compile(
    r"^##\s+(?:Technical Details|技术细节)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_NEXT_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_THIN_SUMMARY_MIN_CHARS = 200


def _check_thin_summary(pages: dict[str, Path]) -> list[LintIssue]:
    """summaries/{x}.md whose `## Technical Details` body is shorter than
    _THIN_SUMMARY_MIN_CHARS characters (CJK + ASCII counted alike)."""
    issues: list[LintIssue] = []
    for key, path in pages.items():
        if not key.startswith("summaries/"):
            continue
        text = path.read_text(encoding="utf-8")
        m = _TECH_DETAILS_HEADING_RE.search(text)
        if not m:
            issues.append(LintIssue(
                rule="thin_summary",
                path=key,
                message="missing '## Technical Details' section",
            ))
            continue
        rest = text[m.end():]
        next_h = _NEXT_HEADING_RE.search(rest)
        body = (rest[: next_h.start()] if next_h else rest).strip()
        chars = len(re.sub(r"\s+", "", body))  # ignore whitespace
        if chars < _THIN_SUMMARY_MIN_CHARS:
            issues.append(LintIssue(
                rule="thin_summary",
                path=key,
                message=(
                    f"'## Technical Details' has only {chars} non-whitespace "
                    f"chars (need >= {_THIN_SUMMARY_MIN_CHARS})"
                ),
            ))
    return issues


def _check_missing_backlink(pages: dict[str, Path]) -> list[LintIssue]:
    """When a forward link exists from A to B, B's frontmatter must record A:

      - summary A → concept/entity B  ⇒  B.key_sources contains A
      - concept A → concept B         ⇒  B.related_concepts contains A
    """
    issues: list[LintIssue] = []
    bare_to_full: dict[str, str] = {key.split("/")[-1]: key for key in pages}

    fm_cache: dict[str, dict] = {}
    def _fm(key: str) -> dict:
        if key not in fm_cache:
            fm_cache[key] = read_frontmatter(pages[key])
        return fm_cache[key]

    for src_key, src_path in pages.items():
        src_section = src_key.split("/", 1)[0]
        src_stem = src_key.split("/", 1)[1]
        text = src_path.read_text(encoding="utf-8")
        for link in extract_wikilinks(text):
            tgt_key = link if link in pages else bare_to_full.get(link)
            if tgt_key is None:
                continue  # broken link is a separate rule
            if tgt_key == src_key:
                continue
            tgt_section = tgt_key.split("/", 1)[0]
            tgt_fm = _fm(tgt_key)

            need: tuple[str, str] | None = None  # (frontmatter field, expected value)
            if src_section == "summaries" and tgt_section in ("concepts", "entities"):
                need = ("key_sources", src_stem)
            elif src_section == "concepts" and tgt_section == "concepts":
                need = ("related_concepts", src_stem)

            if need is None:
                continue

            field_name, expected = need
            actual = tgt_fm.get(field_name, []) or []
            if isinstance(actual, str):
                actual = [actual]
            normalized = {str(v).split("/")[-1] for v in actual}
            if expected not in normalized:
                # Report on the source page — that's the page that introduced
                # the unmatched forward link, so the lint-gate fires on the
                # page being compiled in the current batch.
                issues.append(LintIssue(
                    rule="missing_backlink",
                    path=src_key,
                    message=(
                        f"forward link to {tgt_key}, but {tgt_key}.{field_name} "
                        f"does not list '{src_stem}'"
                    ),
                ))
    return issues


def _check_unverified_dedup(
    pages: dict[str, Path], audit_log: Path,
) -> list[LintIssue]:
    """concepts/* and entities/* whose creation has no matching find-similar
    audit entry. Only flags pages newer than the first audit entry — so
    pre-audit pages aren't false positives."""
    if not audit_log.exists():
        return []  # no audit history yet — can't tell

    audit_entries: list[dict] = []
    audit_start_iso = ""
    with audit_log.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            audit_entries.append(e)
            if not audit_start_iso:
                audit_start_iso = e.get("ts", "")

    if not audit_entries:
        return []

    # Pre-tokenize every audit query for fast Jaccard comparison.
    query_tokens = [
        (e.get("query", ""), _dedup_tokenize(e.get("query", "")), e.get("dir", ""))
        for e in audit_entries
    ]

    issues: list[LintIssue] = []
    audit_start_date = audit_start_iso[:10]  # YYYY-MM-DD prefix

    for key, path in pages.items():
        section = key.split("/", 1)[0]
        if section not in ("concepts", "entities"):
            continue
        fm = read_frontmatter(path)
        page_date = str(fm.get("date_updated") or fm.get("date_added") or "")
        # Only check pages added after audit started (avoid pre-audit FPs).
        if page_date and audit_start_date and page_date < audit_start_date:
            continue

        title = str(fm.get("title", "") or "")
        aliases = fm.get("aliases", []) or []
        if isinstance(aliases, str):
            aliases = [aliases]
        candidates = [t for t in [title, *aliases] if t]
        if not candidates:
            continue

        page_token_sets = [_dedup_tokenize(c) for c in candidates]

        matched = False
        for _q_text, q_tokens, q_dir in query_tokens:
            if q_dir and q_dir != section:
                continue
            for cand_tokens in page_token_sets:
                if _jaccard(q_tokens, cand_tokens) >= 0.3:
                    matched = True
                    break
            if matched:
                break

        if not matched:
            issues.append(LintIssue(
                rule="unverified_dedup",
                path=key,
                message=(
                    f"page created after audit start but no matching "
                    f"find-similar query for title='{title}' — dedup may "
                    f"have been skipped"
                ),
            ))
    return issues


# --- Synthesis-page quality rules -----------------------------------------

_MAP_MIN_MEMBERS = 5
_COMPARISON_MIN_SUBJECTS = 2


def _as_list(value) -> list:
    """Normalize a frontmatter value that may be a list, scalar, or None."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _check_thin_map(pages: dict[str, Path]) -> list[LintIssue]:
    """maps/*.md whose declared coverage is below _MAP_MIN_MEMBERS.

    A map page exists to aggregate 5+ related pages; with fewer members it's
    an over-eager synthesis — the Agent created it to satisfy the ingest
    ritual, not because the knowledge landscape warrants a map yet.
    """
    issues: list[LintIssue] = []
    for key, path in pages.items():
        if not key.startswith("maps/"):
            continue
        fm = read_frontmatter(path)
        concepts = _as_list(fm.get("key_concepts"))
        entities = _as_list(fm.get("key_entities"))
        total = len(concepts) + len(entities)
        if total < _MAP_MIN_MEMBERS:
            issues.append(LintIssue(
                rule="thin_map",
                path=key,
                message=(
                    f"map lists only {total} member(s) across key_concepts + "
                    f"key_entities (need >= {_MAP_MIN_MEMBERS})"
                ),
            ))
    return issues


def _check_incomparable_subjects(pages: dict[str, Path]) -> list[LintIssue]:
    """comparisons/*.md whose `subjects` frontmatter has fewer than 2 entries.

    A comparison requires at least two things to compare. Fewer than 2
    subjects means the page doesn't meet the bar for the comparisons/
    directory — it should be a concept or summary instead.
    """
    issues: list[LintIssue] = []
    for key, path in pages.items():
        if not key.startswith("comparisons/"):
            continue
        fm = read_frontmatter(path)
        subjects = _as_list(fm.get("subjects"))
        if len(subjects) < _COMPARISON_MIN_SUBJECTS:
            issues.append(LintIssue(
                rule="incomparable_subjects",
                path=key,
                message=(
                    f"comparison declares only {len(subjects)} subject(s) in "
                    f"frontmatter (need >= {_COMPARISON_MIN_SUBJECTS})"
                ),
            ))
    return issues


def _check_link_to_deprecated(pages: dict[str, Path]) -> list[LintIssue]:
    """Forward links pointing to a page whose frontmatter has deprecated: true.

    Reported on the SOURCE page so callers fix the dangling reference.
    """
    deprecated: set[str] = set()
    for key, path in pages.items():
        fm = read_frontmatter(path)
        if fm.get("deprecated") is True:
            deprecated.add(key)
    if not deprecated:
        return []

    bare_to_full: dict[str, str] = {key.split("/")[-1]: key for key in pages}
    deprecated_bare = {k.split("/")[-1] for k in deprecated}

    issues: list[LintIssue] = []
    for src_key, src_path in pages.items():
        if src_key in deprecated:
            continue  # deprecated pages can link wherever; not our concern
        text = src_path.read_text(encoding="utf-8")
        seen: set[str] = set()
        for link in extract_wikilinks(text):
            tgt = link if link in deprecated else (
                bare_to_full[link] if link in bare_to_full
                and link in deprecated_bare else None
            )
            if tgt and tgt not in seen:
                seen.add(tgt)
                issues.append(LintIssue(
                    rule="link_to_deprecated",
                    path=src_key,
                    message=f"links to deprecated page [[{link}]] → {tgt}",
                ))
    return issues


# --- Auto-fix --------------------------------------------------------------


def _fix_missing_frontmatter(pages: dict[str, Path], issues: list[LintIssue]) -> int:
    """Auto-fix: set title from filename for pages missing it."""
    fixed = 0
    for issue in issues:
        if issue.rule != "missing_frontmatter":
            continue
        path = pages.get(issue.path)
        if path is None:
            continue
        fm = read_frontmatter(path)
        fm["title"] = path.stem.replace("-", " ").title()
        write_frontmatter(path, fm)
        fixed += 1
    return fixed


def lint(wiki_dir: Path, *, fix: bool = False) -> LintReport:
    """Run all lint rules and optionally fix what can be fixed.

    `wiki_dir` is the wiki/ directory; the dedup audit log is expected at
    `<project_root>/.zenwiki/dedup-audit.jsonl` (project_root = wiki_dir.parent).
    """
    pages = _collect_pages(wiki_dir)
    if not pages:
        return LintReport()

    audit_log = wiki_dir.parent / ".zenwiki" / "dedup-audit.jsonl"

    issues: list[LintIssue] = []
    issues.extend(_check_broken_links(pages))
    issues.extend(_check_missing_frontmatter(pages))
    issues.extend(_check_orphan(pages))
    issues.extend(_check_heading_structure(pages))
    issues.extend(_check_empty_section(pages))
    issues.extend(_check_thin_summary(pages))
    issues.extend(_check_missing_backlink(pages))
    issues.extend(_check_unverified_dedup(pages, audit_log))
    issues.extend(_check_link_to_deprecated(pages))
    issues.extend(_check_thin_map(pages))
    issues.extend(_check_incomparable_subjects(pages))

    fixed = 0
    if fix:
        fixed = _fix_missing_frontmatter(pages, issues)
        issues = [i for i in issues if i.rule != "missing_frontmatter" or not i.fixable]

    return LintReport(issues=issues, fixed=fixed)
