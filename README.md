# ZenWiki

[![CI](https://github.com/ChenXplorer/zenwiki/actions/workflows/ci.yml/badge.svg)](https://github.com/ChenXplorer/zenwiki/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
![Status: alpha](https://img.shields.io/badge/status-alpha-orange)

Agent-driven enterprise knowledge wiki toolkit. Drop files into `raw/`, let an AI agent compile them into a structured, interlinked wiki.

ZenWiki does not call any LLM API. It provides deterministic tools (search, dedup, lint, index) that an external Agent (Claude Code or Codex CLI) uses to build and maintain the wiki.

## Screenshots

|  |  |
|---|---|
| **Browse** — sidebar tree, rendered markdown, frontmatter tags | ![doc view](docs/screenshots/02-doc-view.png) |
| **Ask AI** — hybrid retrieval + Agent synthesizes with citations | ![ask ai](docs/screenshots/03-ask-ai.png) |
| **Crystallize** — one-click save Q&A back into `wiki/outputs/` | ![crystallize](docs/screenshots/04-crystallize.png) |

## How It Works

```
raw/ (your source files)
  │
  ▼
zenwiki serve  ──→  Agent CLI (claude / codex)
                      │
                      ├─ reads CLAUDE.md (schema + workflows)
                      ├─ reads source files from raw/
                      ├─ calls zenwiki tools (find-similar, rebuild-index, ...)
                      └─ writes structured pages to wiki/
                            │
                            ▼
                      wiki/ (browsable in Web UI, Obsidian, or Git)
```

## Install

```bash
pip install -e .
cd web && npm install   # frontend dependencies
```

Requirements:
- Python 3.10+
- Node.js 18+ (for frontend and qmd)
- One of: [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) or [Codex CLI](https://github.com/openai/codex) (for compilation)
- [qmd](https://github.com/tobi/qmd) — optional; if installed on `$PATH`, Ask AI uses it for vector search. Without qmd, Ask AI falls back to BM25 only.

## Quickstart

### 1. Initialize a project

```bash
mkdir my-wiki && cd my-wiki
zenwiki init .
git init && git add -A && git commit -m "init"
```

This creates:

```
my-wiki/
├── CLAUDE.md           # Schema for AI agents
├── config.yaml         # Configuration
├── .zenwiki/           # Internal state (manifest)
├── raw/                # Source files (you put files here)
│   ├── papers/
│   ├── articles/
│   ├── notes/
│   └── docs/
└── wiki/               # Knowledge layer (agent-maintained)
    ├── index.md
    ├── log.md
    ├── summaries/
    ├── entities/
    ├── concepts/
    ├── comparisons/
    ├── maps/
    └── outputs/
```

### 2. Check environment

```bash
zenwiki doctor
```

Verifies that config, directories, Agent CLI, qmd, and git are ready.

### 3. Add source files

```bash
cp ~/papers/*.pdf raw/papers/
cp ~/tech-docs/*.md raw/articles/
cp ~/meeting-notes/*.docx raw/notes/
```

### 4. Start ZenWiki

```bash
zenwiki serve
```

One command does everything:
- **API server** (FastAPI) on port 3334
- **Web UI** (Vite + React) on http://localhost:5173 — auto-opens in browser
- **Compile watcher** — monitors `raw/` and auto-compiles on file changes

Click the refresh button in the sidebar after compilation finishes to see new pages.

The search bar is **Ask AI**: type a question, press Enter (or click **Ask AI**), and ZenWiki retrieves the top relevant wiki pages then calls the Agent CLI to synthesize an answer with source citations.

After the answer returns, a **💎 Crystallize to Wiki** button appears under it. One click writes the Q&A as a new page under `wiki/outputs/` (with citations), updates `index.md` and `log.md`, and refreshes the search index — so the answer is immediately available to future Ask AI queries. See [Crystallizing Ask AI answers](#crystallizing-ask-ai-answers) for the trade-offs.

### 5. Manual compile (optional)

`serve` already auto-compiles on file changes. These commands are for manual control:

```bash
# See what needs processing
zenwiki pending

# Compile all pending files now
zenwiki compile

# Preview without compiling
zenwiki compile --dry-run

# Handle deleted source files
zenwiki compile --prune

# Watch mode: auto-compile on file changes (blocking)
zenwiki compile --watch
```

Compilation is **incremental** — only new or modified files are processed. File changes are detected via mtime + SHA-256 hash, so scanning thousands of files is instant.

Compilation runs **serially by default** (1 worker, 2 files per batch). Concurrency is configurable in `config.yaml`, but raising it above 1 risks lost writes on shared files (`wiki/index.md`, `wiki/log.md`, same-name concept pages) — only do so if you accept that risk or your batches don't overlap.

Each compiled summary is also passed through a **lint gate** before being marked successful — see [Quality gates](#quality-gates).

### 6. Search and explore

```bash
# Search wiki content (requires qmd)
zenwiki search "flash attention memory optimization"

# Trace a source file to its wiki pages
zenwiki provenance raw/papers/flash-attention.pdf

# Check wiki health
zenwiki lint
```

## Manual Agent Usage

Instead of auto-compile, you can work interactively with an Agent:

```bash
cd my-wiki

# Claude Code
claude
# > "ingest raw/papers/flash-attention.pdf"

# Codex CLI
codex
# > "ingest raw/papers/flash-attention.pdf"
```

The Agent reads `CLAUDE.md` for rules and calls `zenwiki` tools as needed.

## Commands

| Command | Description |
|---------|-------------|
| `zenwiki init [path]` | Create a new project |
| `zenwiki doctor` | Check environment readiness |
| `zenwiki serve [--port] [--no-watch] [--no-ui] [--no-open]` | Start API + Web UI + compile watcher |
| `zenwiki status` | Show wiki statistics |
| `zenwiki pending` | Show unprocessed files in raw/ |
| `zenwiki compile [--watch] [--dry-run] [--prune]` | Manual compile (serve already auto-compiles) |
| `zenwiki search "<query>"` | Search wiki (requires qmd) |
| `zenwiki find-similar "<name>"` | Check for duplicate pages |
| `zenwiki provenance <path>` | Show source-to-article provenance |
| `zenwiki slug "<title>"` | Generate kebab-case slug |
| `zenwiki rebuild-index` | Regenerate wiki/index.md |
| `zenwiki refresh` | Refresh search index |
| `zenwiki log "<message>"` | Append to wiki/log.md |
| `zenwiki lint [--fix]` | Run wiki health checks |
| `zenwiki deprecate <path> "<reason>"` | Soft-delete a page (sets `deprecated: true`); excluded from Ask AI, lint flags inbound links |
| `zenwiki retract <path>` | Hard-delete a page; logged in `log.md` |

## Configuration

`config.yaml`:

```yaml
serve:
  port: 3333
  bind: "127.0.0.1"
compile:
  agent: "auto"                   # auto / claude / codex
  debounce_seconds: 30            # watch mode debounce
  auto_commit: true               # git commit after compile
  batch_size: 2                   # files per Agent process
  concurrency: 1                  # parallel Agent processes (>1 risks racing on wiki/index.md, log.md)
  consolidate_threshold: 3        # run /consolidate after N+ files compiled in a single pass (0 = never)
  prune_grace_hours: 24           # wait this long after a raw file disappears before --prune touches the wiki page
  preflight_cache_seconds: 600    # reuse a successful preflight result for 10 min (saves an LLM call per debounce)
```

A `.gitignore` is also generated by `zenwiki init` to keep local caches (`search.db`, `preflight.json`, `dedup-audit.jsonl`) out of git while tracking `manifest.json`.

## Wiki Structure

The Agent creates 6 types of wiki pages:

| Type | Directory | Purpose |
|------|-----------|---------|
| Summaries | `wiki/summaries/` | Deep-dive of each source file |
| Entities | `wiki/entities/` | People, companies, products, tools |
| Concepts | `wiki/concepts/` | Theories, methods, technologies |
| Comparisons | `wiki/comparisons/` | Cross-source analysis |
| Maps | `wiki/maps/` | Topic navigation, domain overviews |
| Outputs | `wiki/outputs/` | Query write-back, generated analysis |

All pages use YAML frontmatter and `[[wikilinks]]`, compatible with Obsidian.

## Search & Retrieval

ZenWiki has two retrieval paths:

### Path 1: Agent queries (Karpathy pattern)

When an LLM Agent answers questions or compiles sources, it follows the original [Karpathy LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern:

```
Agent reads index.md (catalog)
  → identifies relevant pages
  → reads wiki/ pages (compiled summaries)
  → if more detail needed, follows source_path back to raw/
```

No search engine required. The Agent itself is the retriever. This works well at moderate scale (~100 sources, hundreds of wiki pages) because `index.md` fits in the context window.

### Path 2: Web UI Ask AI

The search bar in the Web UI is a single **Ask AI** flow:

```
User question
  → SQLite FTS5 (BM25) + qmd vsearch (if qmd is installed), merged via RRF
  → top-5 wiki pages fetched (deprecated pages filtered out)
  → Agent CLI synthesizes an answer via subprocess (codex exec | claude -p --bare)
  → returned with source citations
```

There is no separate keyword-search button: every query goes through Ask AI. A plain `zenwiki search "<q>"` CLI remains available for scripting.

### qmd is optional

If [qmd](https://github.com/tobi/qmd) is on `$PATH`, ZenWiki uses it for the vector leg of hybrid retrieval. If it isn't, ZenWiki silently falls back to BM25 only — everything still works, results are just keyword-only. There is no config knob for this; it is auto-detected.

qmd stores indexes under `~/.cache/qmd/`. If you run multiple ZenWiki projects on the same machine they currently share a `wiki` collection — good enough for single-user single-project use, not for running several projects side by side.

## Crystallizing Ask AI answers

The "💎 Crystallize to Wiki" button under each Ask AI answer writes the Q&A as `wiki/outputs/{slug}.md` with this frontmatter:

```yaml
---
title: "<the question>"
date_added: YYYY-MM-DD
citations: [...]              # the source pages used to synthesize the answer
crystallized_from_query: true # marker for future filtering / review tooling
---
```

After writing, ZenWiki refreshes the search index, rebuilds `index.md`, and appends to `log.md`. The page is **immediately** searchable and immediately retrievable by the next Ask AI query.

There is intentionally **no draft / review state** in the MVP — clicking save is a single act. If a wrong answer gets in, retract or deprecate it (next section). The `crystallized_from_query` field is left in place as a hook in case you ever want to add a review pipeline (e.g. exclude unreviewed crystallizations from Ask AI context).

## Page lifecycle: deprecate / retract

Wiki pages can be soft-removed without deleting them:

```bash
# Soft-remove (preferred when other pages link to it)
zenwiki deprecate wiki/outputs/wrong-answer.md "Cited a hallucinated number"

# Hard-remove (use when no other pages reference it)
zenwiki retract wiki/outputs/wrong-answer.md
```

`deprecate` adds `deprecated: true` + `deprecated_reason` + `deprecated_at` to the frontmatter. The page stays in the file tree so inbound `[[wikilinks]]` don't break, but:

- **Ask AI** filters deprecated pages out of its context — wrong content can't pollute future answers
- **Lint** flags every page that still links to deprecated content (`link_to_deprecated` rule), prompting cleanup

`retract` deletes the file outright, rebuilds the index, and logs the removal.

## Quality gates

Compilation isn't done when the Agent finishes — every batch goes through deterministic lint rules, and a subset will **demote a "compiled" file back to "failed"** so the watcher retries it. The full rule set:

| Rule | What it checks | Blocks compile? |
|------|----------------|-----------------|
| `broken_link` | wikilink to non-existent page | warn |
| `missing_frontmatter` | missing `title` field | block |
| `orphan` | page with no inbound wikilinks | warn |
| `heading_structure` | heading levels skip (`#` → `###`) | warn |
| `empty_section` | heading with no content under it | block |
| `thin_summary` | `## Technical Details` shorter than 200 non-whitespace chars | block |
| `missing_backlink` | A links to B but B's `key_sources` / `related_concepts` doesn't list A | block |
| `unverified_dedup` | new concept/entity created without a matching `find-similar` audit entry | warn |
| `link_to_deprecated` | wikilink to a `deprecated: true` page | block |

The dedup audit log lives at `.zenwiki/dedup-audit.jsonl` — every `zenwiki find-similar` call is recorded with timestamp, query, and top score. The `unverified_dedup` rule only flags pages created **after** the audit log started, so existing wiki content isn't retroactively marked.

Run lint manually any time:

```bash
zenwiki lint            # report all issues
zenwiki lint --fix      # auto-fix what can be auto-fixed (currently: missing title)
```

## Design Principles

1. **Agent does all intelligent work** -- reading sources, writing wiki pages, answering questions. ZenWiki calls no LLM API.
2. **ZenWiki does what agents can't** -- local search, deterministic dedup, structural lint, file system watching, lifecycle (deprecate / retract).
3. **File system is truth** -- no database. Markdown files + `index.md` is the entire state. Git is version control. Local caches (search.db, preflight, audit log) live under `.zenwiki/` and are gitignored; `.zenwiki/manifest.json` is the only tracked file in there.
4. **Incremental by default** -- mtime + SHA-256 change detection, only recompile what changed. Source removals get a 24h grace period so transient absences (git checkout, file moves) don't trigger prune.
5. **Serial by default, parallel by config** -- batch size and concurrency are tunable, but the default (1 worker) avoids races on shared files. Bump only after reviewing the trade-offs.
6. **Quality is gated, not assumed** -- nine deterministic lint rules; four of them block a "compiled" file from being marked successful, forcing the Agent to retry. See [Quality gates](#quality-gates).

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  zenwiki serve                                               │
│                                                              │
│  ┌──────────┐  ┌──────────────────┐  ┌────────────────────┐  │
│  │ API      │  │ Compile Watcher  │  │ Vite Dev Server    │  │
│  │ (FastAPI)│  │ raw/ → Agent CLI │  │ (React frontend)   │  │
│  │ :3334    │  │  → lint gate     │  │ :5173              │  │
│  └──────────┘  └──────────────────┘  └────────────────────┘  │
│       ▲                 │                    │ proxy /tree   │
│       │                 ▼                    │ proxy /doc    │
│       │           Agent CLI                  │ proxy /search │
│       │           (1 worker default;         │ proxy /query  │
│       │            cached preflight)         │ proxy /status │
│       │                                      │ /crystallize  │
│       └──────────────────────────────────────┘               │
└──────────────────────────────────────────────────────────────┘
```

## References

- [Karpathy LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) -- the original idea
- [OmegaWiki](https://github.com/skyllwt/OmegaWiki) -- academic implementation
- [sage-wiki](https://github.com/xoai/sage-wiki) -- self-contained Go implementation
- [qmd](https://github.com/tobi/qmd) -- local Markdown search engine

## License

MIT
