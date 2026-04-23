"""Manifest tracking for raw/ → wiki/ compilation state.

The manifest lives at .zenwiki/manifest.json and records the SHA-256 hash
and compilation status of every file under raw/.  It enables:

- Incremental compilation (skip unchanged files)
- Change detection (new files + modified files)
- Crash recovery (failed files are retried on next compile)
- Source removal detection (deleted raw files flagged for pruning)
- Provenance queries (raw → summary → concepts/entities)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import RAW_SECTIONS
from .markdown import extract_wikilinks, read_frontmatter

MANIFEST_DIR = ".zenwiki"
MANIFEST_FILE = "manifest.json"


@dataclass
class ManifestEntry:
    sha256: str
    status: str = "pending"  # pending | compiled | failed | source_removed
    summary_slug: str = ""
    compiled_at: str = ""
    reason: str = ""  # new | modified (set during scan)
    mtime: float = 0.0
    size: int = 0
    # ISO timestamp set when scan_raw first sees the file missing.
    # Used by get_removed() with the prune_grace_hours config to avoid
    # acting on transient disappearances (git checkout, file moves, etc.).
    # Cleared when the file reappears.
    removed_at: str = ""


@dataclass
class RemovedSource:
    raw_path: str
    summary_slug: str


@dataclass
class ProvenanceInfo:
    target: str
    direction: str  # "forward" (raw→wiki) or "reverse" (wiki→raw)
    summary: str = ""
    raw_source: str = ""
    linked_pages: list[str] = field(default_factory=list)
    referenced_by: list[str] = field(default_factory=list)


def _manifest_path(root: Path) -> Path:
    return root / MANIFEST_DIR / MANIFEST_FILE


def _ensure_dir(root: Path) -> None:
    (root / MANIFEST_DIR).mkdir(parents=True, exist_ok=True)


def load_manifest(root: Path) -> dict[str, ManifestEntry]:
    mp = _manifest_path(root)
    if not mp.exists():
        return {}
    with mp.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = json.load(f)
    result: dict[str, ManifestEntry] = {}
    for path_key, entry_dict in raw.items():
        result[path_key] = ManifestEntry(
            sha256=entry_dict.get("sha256", ""),
            status=entry_dict.get("status", "pending"),
            summary_slug=entry_dict.get("summary_slug", ""),
            compiled_at=entry_dict.get("compiled_at", ""),
            reason=entry_dict.get("reason", ""),
            mtime=float(entry_dict.get("mtime", 0.0)),
            size=int(entry_dict.get("size", 0)),
            removed_at=entry_dict.get("removed_at", ""),
        )
    return result


def save_manifest(root: Path, manifest: dict[str, ManifestEntry]) -> None:
    _ensure_dir(root)
    mp = _manifest_path(root)
    serializable = {k: asdict(v) for k, v in manifest.items()}
    with mp.open("w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
        f.write("\n")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_changed(fpath: Path, entry: ManifestEntry) -> bool:
    """Quick check: mtime or size changed since last scan."""
    stat = fpath.stat()
    return stat.st_mtime != entry.mtime or stat.st_size != entry.size


def _stat_fields(fpath: Path) -> tuple[float, int]:
    stat = fpath.stat()
    return stat.st_mtime, stat.st_size


def scan_raw(root: Path) -> dict[str, ManifestEntry]:
    """Scan raw/ and reconcile with the existing manifest.

    Uses a two-tier check for speed:
      1. Compare mtime + size (instant, no I/O beyond stat)
      2. Only compute SHA-256 if mtime/size changed

    With 5000 files this completes in milliseconds instead of minutes.
    """
    manifest = load_manifest(root)
    raw_dir = root / "raw"
    seen: set[str] = set()

    for section in RAW_SECTIONS:
        section_dir = raw_dir / section
        if not section_dir.is_dir():
            continue
        for fpath in sorted(section_dir.iterdir()):
            if fpath.is_dir() or fpath.name.startswith("."):
                continue
            rel = str(fpath.relative_to(root))
            seen.add(rel)
            mtime, size = _stat_fields(fpath)

            if rel not in manifest:
                manifest[rel] = ManifestEntry(
                    sha256=file_sha256(fpath), status="pending",
                    reason="new", mtime=mtime, size=size,
                )
                continue

            entry = manifest[rel]
            # File is back: lift the source_removed flag and restore status.
            # If we still have a summary_slug, treat as compiled; otherwise
            # treat as pending (will be re-compiled).
            if entry.status == "source_removed":
                entry.status = "compiled" if entry.summary_slug else "pending"
                entry.removed_at = ""

            if mtime != entry.mtime or size != entry.size:
                new_hash = file_sha256(fpath)
                if new_hash != entry.sha256:
                    entry.sha256 = new_hash
                    entry.status = "pending"
                    entry.reason = "modified"
                entry.mtime = mtime
                entry.size = size
            # else: mtime + size unchanged → skip hash, keep status

    now_iso = datetime.now(timezone.utc).isoformat()
    for rel in list(manifest.keys()):
        if rel in seen:
            continue
        if manifest[rel].status != "source_removed":
            manifest[rel].status = "source_removed"
            manifest[rel].removed_at = now_iso
        elif not manifest[rel].removed_at:
            # Backfill for entries that were marked removed before grace
            # tracking existed — start the clock now.
            manifest[rel].removed_at = now_iso

    save_manifest(root, manifest)
    return manifest


def mark_compiled(root: Path, raw_path: str, summary_slug: str) -> None:
    manifest = load_manifest(root)
    if raw_path in manifest:
        manifest[raw_path].status = "compiled"
        manifest[raw_path].summary_slug = summary_slug
        manifest[raw_path].compiled_at = datetime.now(timezone.utc).isoformat()
        manifest[raw_path].reason = ""
        save_manifest(root, manifest)


def mark_failed(root: Path, raw_path: str) -> None:
    manifest = load_manifest(root)
    if raw_path in manifest:
        manifest[raw_path].status = "failed"
        manifest[raw_path].reason = ""
        save_manifest(root, manifest)


def get_removed(root: Path, grace_hours: float = 0.0) -> list[RemovedSource]:
    """Return source-removed entries whose removed_at is older than grace_hours.

    grace_hours=0 (default) keeps the legacy behavior — return everything.
    Callers that want safe pruning should pass cfg.compile.prune_grace_hours.
    """
    manifest = load_manifest(root)
    if grace_hours <= 0:
        return [
            RemovedSource(raw_path=k, summary_slug=v.summary_slug)
            for k, v in manifest.items()
            if v.status == "source_removed"
        ]

    cutoff = datetime.now(timezone.utc).timestamp() - grace_hours * 3600
    out: list[RemovedSource] = []
    for k, v in manifest.items():
        if v.status != "source_removed":
            continue
        if not v.removed_at:
            # No timestamp → can't enforce grace; conservative: skip.
            continue
        try:
            removed_ts = datetime.fromisoformat(v.removed_at).timestamp()
        except ValueError:
            continue
        if removed_ts <= cutoff:
            out.append(RemovedSource(raw_path=k, summary_slug=v.summary_slug))
    return out


def rebuild_manifest(root: Path) -> dict[str, ManifestEntry]:
    """Rebuild manifest from scratch by scanning wiki/summaries/ source_path fields."""
    raw_dir = root / "raw"
    summaries_dir = root / "wiki" / "summaries"

    source_to_slug: dict[str, str] = {}
    if summaries_dir.is_dir():
        for md in summaries_dir.glob("*.md"):
            fm = read_frontmatter(md)
            sp = fm.get("source_path", "")
            if sp:
                source_to_slug[sp] = md.stem

    manifest: dict[str, ManifestEntry] = {}
    for section in RAW_SECTIONS:
        section_dir = raw_dir / section
        if not section_dir.is_dir():
            continue
        for fpath in sorted(section_dir.iterdir()):
            if fpath.is_dir() or fpath.name.startswith("."):
                continue
            rel = str(fpath.relative_to(root))
            h = file_sha256(fpath)
            mtime, size = _stat_fields(fpath)
            if rel in source_to_slug:
                manifest[rel] = ManifestEntry(
                    sha256=h,
                    status="compiled",
                    summary_slug=source_to_slug[rel],
                    compiled_at="",
                    reason="",
                    mtime=mtime,
                    size=size,
                )
            else:
                manifest[rel] = ManifestEntry(
                    sha256=h,
                    status="pending",
                    reason="new",
                    mtime=mtime,
                    size=size,
                )

    save_manifest(root, manifest)
    return manifest


def get_provenance(root: Path, target: str) -> ProvenanceInfo:
    """Query provenance for a raw source or wiki page path."""
    wiki_dir = root / "wiki"
    manifest = load_manifest(root)

    if target.startswith("raw/"):
        entry = manifest.get(target)
        info = ProvenanceInfo(target=target, direction="forward")
        if not entry or not entry.summary_slug:
            return info
        info.summary = f"wiki/summaries/{entry.summary_slug}.md"
        summary_path = wiki_dir / "summaries" / f"{entry.summary_slug}.md"
        if summary_path.exists():
            text = summary_path.read_text(encoding="utf-8")
            info.linked_pages = extract_wikilinks(text)
        return info

    info = ProvenanceInfo(target=target, direction="reverse")
    target_path = root / target
    if target_path.exists():
        fm = read_frontmatter(target_path)
        sp = fm.get("source_path", "")
        if sp:
            info.raw_source = sp
        ks = fm.get("key_sources", [])
        if isinstance(ks, list):
            for s in ks:
                src_path = wiki_dir / "summaries" / f"{s}.md"
                if src_path.exists():
                    src_fm = read_frontmatter(src_path)
                    src_sp = src_fm.get("source_path", "")
                    if src_sp:
                        info.raw_source = src_sp

    for section in ("summaries", "entities", "concepts", "comparisons", "maps", "outputs"):
        section_dir = wiki_dir / section
        if not section_dir.is_dir():
            continue
        for md in section_dir.glob("*.md"):
            text = md.read_text(encoding="utf-8")
            links = extract_wikilinks(text)
            target_stem = Path(target).stem
            rel_target = str(Path(target).relative_to("wiki")) if target.startswith("wiki/") else target
            target_no_ext = rel_target.removesuffix(".md") if rel_target.endswith(".md") else rel_target
            for link in links:
                if link == target_stem or link == target_no_ext or link.endswith(f"/{target_stem}"):
                    info.referenced_by.append(str(md.relative_to(root)))
                    break

    return info
