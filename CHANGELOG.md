# Changelog

All notable changes to ZenWiki are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-04-15

### Added
- **Per-batch `/consolidate`.** Every batch that compiles ≥ `consolidate_threshold` files now triggers a consolidation pass, so `comparisons/` and `maps/` grow continuously — previously the pass only fired once at the end of a compile run, which meant watch mode (one file per debounce) never consolidated.
- **Semantic-field FTS indexing.** `tags`, `key_concepts`, `key_entities`, `subjects`, `key_sources`, `related_concepts`, and `category` are now indexed into the SQLite FTS title column (BM25 weight 5.0). Previously only `title + aliases` made it into the index, so a map titled "FICC AI Research Landscape" tagged `[ficc, ai投研]` was invisible to the query "FICC AI 投研".
- **Hard-slot promotion for `maps/` and `comparisons/` in hybrid search.** If neither prefix is represented in the RRF top-N but either matches the query, the best per-prefix hit is swapped in for the lowest-ranked non-privileged slot. Directory-style pages (short body, long frontmatter lists) no longer lose on raw BM25 to long summaries for cross-cutting questions.
- **`.zenwiki/compile-runs.jsonl`.** Every Agent subprocess invocation appends a structured record (`ts / label / cmd / returncode / elapsed_s / outcome`). Replaces the black-box failure mode where `compile` could silently fail with no forensic trail.
- **Prune verification.** `compile --prune` now only drops a manifest entry after verifying the Agent actually removed or deprecated the corresponding summary file. Previously a failed prune would be "forgotten" and never retry.
- **`CHANGELOG.md` and `CONTRIBUTING.md`.** Dev setup, PR checklist, and release log.
- **Public Web UI screenshots** under `docs/screenshots/`, embedded in README.

### Changed
- `consolidate_threshold` default `3 → 1`. Combined with per-batch triggering, this means watch mode gets a consolidation pass after every successful compile instead of never.
- `/query` retrieves top-10 (was top-5) to give the hard-slot promoted pages room to land without displacing primary matches.
- Install instructions rewritten for a zero-clone path: `pip install git+https://github.com/ChenXplorer/zenwiki.git` is now the primary install command. `npm install` is a contributor-only step (the built bundle ships with the wheel).
- `consolidate_threshold > 1` still works — it's just no longer the default. Set to `0` to disable auto-consolidate entirely.

### Fixed
- **Web UI wikilinks were dead links.** The click handler searched the `onclick` attribute for `loadDoc('...')`, but the backend emits `data-path="..."`. Inline `[[wikilinks]]` now navigate.
- **Static bundle was never served.** `create_app()` had no `StaticFiles` mount, so `pip install`-ed users got API-only with no UI. Bundle now mounts at `/` when `src/zenwiki/static/index.html` exists, and the package artifact spec (`pyproject.toml`) ships the bundle.
- **Vite dev-mode proxy missing `/crystallize`, `/rebuild-index`, `/refresh-index`.** Added.
- **Preflight cache keyed only on `agent_cmd`.** Now also includes `agent_args`, so switching between `claude` and `codex` (or changing CLI flags) invalidates stale cache entries.
- **Concurrency clamp removed.** The previous version hard-clamped `compile.concurrency` to 1 regardless of config, violating the README design principle "serial by default, parallel by config". Configured values are now honoured with a warning.

### Removed
- `search.hybrid` and `search.qmd_path` config keys. `qmd` is auto-detected on `$PATH`; there's no opt-out. Everything still works in BM25-only mode when `qmd` isn't installed.
- README's unimplemented claims about a three-tier search mode (BM25 / Hybrid / Full rerank), `retrieval_mode`/`qmd_index` config keys, auto-installed qmd, and sidebar auto-refresh on compile.

## [0.1.0] - 2026-04-14

### Added
- Initial public release.
- **CLI (17 subcommands)** via Typer: `init`, `doctor`, `serve`, `status`, `pending`, `compile`, `consolidate`, `search`, `find-similar`, `slug`, `rebuild-index`, `refresh`, `log`, `retract`, `deprecate`, `lint`, `provenance`.
- **Compiler orchestration** — detects `claude` / `codex` on `$PATH`, batches pending raw files (default 2 per batch), invokes the Agent via subprocess, verifies output by scanning `wiki/summaries/{slug}.md` for matching `source_path` frontmatter.
- **Lint gate** (5 blocking rules of 9 total): `missing_frontmatter`, `empty_section`, `thin_summary`, `missing_backlink`, `link_to_deprecated` demote newly "compiled" files back to `failed`, forcing the Agent to retry.
- **Incremental compilation** — two-level change detection (mtime + size fast-path → SHA-256 thorough check) in `manifest.py`. Source removals get a 24-hour grace period before `--prune` acts.
- **Dedup audit trail** — every `find-similar` call is recorded to `.zenwiki/dedup-audit.jsonl`; the `unverified_dedup` lint rule flags pages created without a corresponding audit entry.
- **Hybrid search** — SQLite FTS5 (BM25 with jieba Chinese tokenization) + optional `qmd` vector search, merged via Reciprocal Rank Fusion.
- **FastAPI backend** with endpoints `/tree`, `/doc`, `/search`, `/query`, `/status`, `/rebuild-index`, `/refresh-index`, `/crystallize`.
- **React + Vite Web UI** with tree navigation, doc view, Ask AI, and one-click Crystallize back to `wiki/outputs/`.
- **Watcher mode** — `watchdog` monitors `raw/`, 30-second debounce, exponential retry backoff on failure.
- **Auto git commit** after successful compile (when `auto_commit: true`).
- **`zenwiki init`** scaffolds `CLAUDE.md` (367-line Agent contract), `config.yaml`, `raw/{papers,articles,notes,docs}/`, `wiki/{summaries,entities,concepts,comparisons,maps,outputs}/`.
- **MIT License**, **CI** (Python 3.10/3.11/3.12 × Node 18/20 matrix), and **`CONTRIBUTING.md`**.

[0.1.1]: https://github.com/ChenXplorer/zenwiki/releases/tag/v0.1.1
[0.1.0]: https://github.com/ChenXplorer/zenwiki/releases/tag/v0.1.0
