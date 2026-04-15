"""Detect unprocessed files in raw/ based on manifest state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .manifest import scan_raw


@dataclass
class PendingFile:
    raw_path: str
    reason: str  # "new" | "modified" | "retry"
    sha256: str


def get_pending(root: Path) -> list[PendingFile]:
    """Return all raw files that need compilation.

    A file is pending if its manifest status is "pending" (new or modified)
    or "failed" (will be retried).
    """
    manifest = scan_raw(root)
    result: list[PendingFile] = []
    for raw_path, entry in sorted(manifest.items()):
        if entry.status in ("pending", "failed"):
            reason = entry.reason if entry.reason else (
                "retry" if entry.status == "failed" else "new"
            )
            result.append(PendingFile(
                raw_path=raw_path,
                reason=reason,
                sha256=entry.sha256,
            ))
    return result
