"""Minimal configuration loader for ZenWiki."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ServeConfig:
    port: int = 3333
    bind: str = "127.0.0.1"


@dataclass
class CompileConfig:
    agent: str = "auto"  # "auto" | "claude" | "codex"
    debounce_seconds: int = 30
    auto_commit: bool = True
    batch_size: int = 2  # files per Agent process
    # Default 1: multiple parallel Agents racing on wiki/index.md, log.md and
    # same-name concept pages cause lost writes. Bump only if you've reviewed
    # the race conditions and accept them.
    concurrency: int = 1  # parallel Agent processes
    # Run /consolidate after every batch that compiles N+ files. 1 = after
    # every successful batch (recommended — keeps comparisons/maps current).
    # 0 = never auto-consolidate (only `zenwiki consolidate` manually).
    consolidate_threshold: int = 1
    # Wait this many hours after a raw file disappears before letting --prune
    # touch the corresponding wiki page. Protects against transient absence
    # (git checkout, file moves, accidental deletes).
    prune_grace_hours: float = 24.0
    # Reuse a successful pre-flight check for this many seconds. The pre-flight
    # call itself burns one LLM round-trip; in --watch mode without caching it
    # would fire on every debounce. 0 disables the cache.
    preflight_cache_seconds: int = 600


@dataclass
class Config:
    serve: ServeConfig = field(default_factory=ServeConfig)
    compile: CompileConfig = field(default_factory=CompileConfig)


_DEFAULT_CONFIG_NAME = "config.yaml"

WIKI_SECTIONS = ("summaries", "entities", "concepts", "comparisons", "maps", "outputs")
RAW_SECTIONS = ("papers", "articles", "notes", "docs")


def load_config(root: Path) -> Config:
    """Load config.yaml from *root*, falling back to defaults."""
    cfg_path = root / _DEFAULT_CONFIG_NAME
    if not cfg_path.exists():
        return Config()

    with cfg_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    serve_raw = raw.get("serve", {})
    compile_raw = raw.get("compile", {})

    return Config(
        serve=ServeConfig(
            port=serve_raw.get("port", 3333),
            bind=serve_raw.get("bind", "127.0.0.1"),
        ),
        compile=CompileConfig(
            agent=compile_raw.get("agent", "auto"),
            debounce_seconds=compile_raw.get("debounce_seconds", 30),
            auto_commit=compile_raw.get("auto_commit", True),
            batch_size=compile_raw.get("batch_size", 2),
            concurrency=compile_raw.get("concurrency", 1),
            consolidate_threshold=compile_raw.get("consolidate_threshold", 1),
            prune_grace_hours=float(compile_raw.get("prune_grace_hours", 24.0)),
            preflight_cache_seconds=int(compile_raw.get("preflight_cache_seconds", 600)),
        ),
    )


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from *start* looking for config.yaml or wiki/ directory."""
    p = (start or Path.cwd()).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / _DEFAULT_CONFIG_NAME).exists():
            return candidate
        if (candidate / "wiki").is_dir() and (candidate / "raw").is_dir():
            return candidate
    return p
