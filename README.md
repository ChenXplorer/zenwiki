# ZenWiki

[![CI](https://github.com/ChenXplorer/zenwiki/actions/workflows/ci.yml/badge.svg)](https://github.com/ChenXplorer/zenwiki/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
![Status: alpha](https://img.shields.io/badge/status-alpha-orange)

An implementation of Karpathy's LLM wiki idea — raw sources → agent-compiled wiki → Ask AI. Drop files into `raw/`, let an AI agent compile them into a structured, interlinked wiki.

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

## Repository Layout

ZenWiki ships with two top-level directories:

- `core/` — the program (Python package, web frontend). You only touch this if you're modifying ZenWiki itself.
- `my-wiki/` — your content. Drop sources into `my-wiki/raw/`, the Agent compiles them into `my-wiki/wiki/`. Open `my-wiki/` in Obsidian to read, or with `claude` / `codex` to ask questions.

## Quickstart

### Prerequisites

- Python 3.10+
- Node.js 18+ (for the web frontend build)
- An Agent CLI: [Claude Code](https://docs.anthropic.com/en/docs/claude-code) **or** [Codex CLI](https://github.com/openai/codex) — logged in (`claude /login` or `codex login`).
- Optional: [qmd](https://github.com/tobi/qmd) on `$PATH` for hybrid BM25 + vector search. Without qmd, ZenWiki falls back to BM25-only; everything still works.

### Install and run

```bash
git clone https://github.com/ChenXplorer/zenwiki.git
cd zenwiki
make install                             # pip install core + npm install/build
# drop your source files under my-wiki/raw/papers, /articles, /notes, /docs
make serve                               # starts API + Web UI, opens browser
```

`make serve` launches:
- **API + Web UI** on `http://127.0.0.1:3334` (bundled UI served by FastAPI)
- **Compile watcher** on `my-wiki/raw/` — auto-compiles new/changed files via the Agent CLI

**No sources handy?** Grab a public paper to try it end-to-end:

```bash
curl -L -o my-wiki/raw/papers/attention-is-all-you-need.pdf \
  https://arxiv.org/pdf/1706.03762.pdf
```

Watch `make serve`'s output — each file takes a minute or two (the Agent actually reads it). Then:
- Open a compiled summary page in the Web UI or in Obsidian (`my-wiki/` is already a valid Obsidian vault).
- Use the **Ask AI** search bar to query the wiki — BM25 + vector retrieval merged via RRF, answer synthesized by the Agent CLI with citations.
- Click **💎 Crystallize to Wiki** to save a good answer into `my-wiki/wiki/outputs/` for future retrieval.

### Troubleshooting the first run

| Symptom | Cause | Fix |
|---|---|---|
| `zenwiki: command not found` | pip's scripts dir not on PATH | `python -m zenwiki --help`, or add pip's user bin to PATH |
| Compile hangs silently, no files appear in `my-wiki/wiki/summaries/` | Agent CLI not logged in | `claude /login` or `codex login` — ZenWiki inherits their auth |
| Compile errors with `Not inside a trusted directory` | Using codex, but `my-wiki/` not in a git repo | `make serve` from the repo root works (it's a git repo); or switch to `claude` |
| Browser tab opens but Ask AI returns nothing | Agent CLI failed silently | Check `my-wiki/.zenwiki/compile-runs.jsonl`, or `zenwiki doctor` |
| `qmd` shown red in `zenwiki doctor` | Not installed | Ignore — BM25-only still works |

### Manual compile (optional)

`make serve` already auto-compiles on file changes. These commands are for manual control — run them from inside `my-wiki/`:

```bash
cd my-wiki
zenwiki pending               # See what needs processing
zenwiki compile               # Compile all pending files now
zenwiki compile --dry-run     # Preview without compiling
zenwiki compile --prune       # Handle deleted source files
zenwiki compile --watch       # Watch mode: auto-compile on file changes (blocking)
```

Compilation is **incremental** — only new or modified files are processed. File changes are detected via mtime + SHA-256 hash, so scanning thousands of files is instant.

Compilation runs **serially by default** (1 worker, 2 files per batch). Concurrency is configurable in `config.yaml`, but raising it above 1 risks lost writes on shared files (`wiki/index.md`, `wiki/log.md`, same-name concept pages) — only do so if you accept that risk or your batches don't overlap.

Each compiled summary is also passed through a **lint gate** before being marked successful — see [Quality gates](#quality-gates).

### Search and explore

All CLI commands work from inside `my-wiki/`:

```bash
cd my-wiki
zenwiki search "flash attention memory optimization"   # BM25 (hybrid if qmd installed)
zenwiki provenance raw/papers/flash-attention.pdf      # Source → wiki pages
zenwiki lint                                           # Wiki health check
```

## Manual Agent Usage

Instead of auto-compile, you can work interactively with an Agent directly in the content directory:

```bash
cd my-wiki
claude          # or: codex
# > "ingest raw/papers/flash-attention.pdf"
```

The Agent reads `my-wiki/CLAUDE.md` for rules and calls `zenwiki` tools as needed.

## Commands

| Command | Description |
|---------|-------------|
| `zenwiki doctor` | Check environment readiness (Agent CLI, qmd) |
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
  consolidate_threshold: 1        # run /consolidate after every batch with N+ compiled files (0 = never auto-consolidate)
  prune_grace_hours: 24           # wait this long after a raw file disappears before --prune touches the wiki page
  preflight_cache_seconds: 600    # reuse a successful preflight result for 10 min (saves an LLM call per debounce)
```

`my-wiki/.gitignore` keeps local caches (`search.db`, `preflight.json`, `dedup-audit.jsonl`) out of git while tracking `.zenwiki/manifest.json` — the compile state needed across machines.

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

The search bar in the Web UI is a single **Ask AI** flow. It does **not** stuff a prompt server-side — it spawns the Agent CLI and lets the `zenwiki-ask` skill drive the loop:

```
User question
  → /query (SSE stream)
       ├─ frame 1: results       — local hybrid search seeds the panel
       ├─ frame 2..N: step       — searching / reading / synthesizing
       │                           (translated from claude stream-json events)
       └─ frame N+1: done        — {answer, sources}
  → spawn:  claude -p "/zenwiki-ask <q>" --output-format stream-json
            --allowed-tools "Bash(zenwiki:*),Read"
       └─ skill internally calls:
            zenwiki search "<q>" --exclude-deprecated --promote maps,comparisons
            Read wiki/<top-K>.md
            (synthesize, emit JSON {answer, sources})
```

No keyword-only search button: every query goes through Ask AI. Plain `zenwiki search "<q>" --json` is available for scripting.

The skill bundle ships under `my-wiki/.claude/skills/zenwiki-ask/SKILL.md` and is mirrored at `my-wiki/.agents/skills/` (symlink) so Codex CLI finds it too. The browser shows live progress as `🔍 Searching → 📄 Reading wiki/foo.md → ✍️ Synthesizing` — about 17 seconds of previously-blank wait becomes visible.

> **`/zenwiki-ask` prefix is mandatory** for non-interactive runs. Stage-0 testing showed `claude -p "<q>"` does NOT auto-trigger the skill from description alone (1 turn, no tool use, generic answer). The slash prefix forces invocation deterministically.

**Retrieval biases tuned for the Karpathy pattern:**
- Semantic frontmatter fields (`tags`, `key_concepts`, `key_entities`, `subjects`, `key_sources`, `related_concepts`, `category`) are folded into the FTS title column (BM25 weight 5.0). This fixes the common case where a map page has an English title but Chinese tags (or vice versa) — its declared coverage becomes searchable.
- `maps/` and `comparisons/` pages get a **hard slot** in hybrid search results: if at least one matches the query but neither made the RRF top-10, the best match of each prefix is swapped in. This corrects for the structural BM25 disadvantage of directory-style pages (short body, long frontmatter lists) and ensures cross-cutting questions reach the pages designed to answer them. Specific-entity queries don't match these prefixes → no promotion → ordering unchanged.

### Security model — Claude vs Codex

Both agents are supported (BYOA), but they don't carry the same risk profile when spawned non-interactively from the Web UI subprocess. Pick what matters to you:

| | Claude Code | Codex CLI |
|---|---|---|
| Tool whitelist | `--allowed-tools "Bash(zenwiki:*),Read"` — **command-level** allowlist | `--full-auto` — workspace-wide write, no command granularity |
| trusted-directory check | none | enforced (must be a git repo) |
| Output schema | `--output-format stream-json` — validated, used for live progress | not validated locally; falls back to a single `done` frame after completion |
| Prompt-injection blast radius | bounded to `zenwiki *` + Read | wide (any file write / shell command) |
| Default in `_detect_query_agent` | preferred | fallback |

**Claude is the recommended path.** Codex works but is marked experimental in the code: the parser is a stub (`_parse_codex_text`) returning raw stdout as the answer with no sources, and there are no fine-grained tool restrictions to absorb a malicious prompt. If you run Codex against an untrusted wiki (e.g. raw sources you don't fully trust), do it knowing the agent has workspace-wide write access for the duration of the call.

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
| `thin_map` | `maps/` page with fewer than 5 members in `key_concepts + key_entities` | block |
| `incomparable_subjects` | `comparisons/` page with fewer than 2 entries in `subjects` | block |

Plus a non-page gate in the compiler: `/consolidate` is **skipped** when the wiki has fewer than 5 total pages. Below that floor there's not enough breadth to find genuine cross-source overlap, and the Agent tends to invent maps/comparisons to satisfy the ritual.

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
6. **Quality is gated, not assumed** -- eleven deterministic lint rules; seven of them block a "compiled" file from being marked successful, forcing the Agent to retry. See [Quality gates](#quality-gates).

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  zenwiki serve                                                   │
│                                                                  │
│  ┌──────────────┐  ┌────────────────┐  ┌────────────────────┐    │
│  │ API          │  │ Compile        │  │ Vite Dev Server    │    │
│  │ (FastAPI)    │  │ Watcher        │  │ (React frontend)   │    │
│  │ :3334        │  │ raw/ → Agent   │  │ :5173              │    │
│  │              │  │  → lint gate   │  │                    │    │
│  └──────┬───────┘  └────────────────┘  └────────┬───────────┘    │
│         │ /query (SSE)                          │ proxy *        │
│         ▼                                       ▼                │
│  ┌─────────────────────────────────┐  EventSource consumes:      │
│  │ spawn agent CLI:                │   results, step, done       │
│  │   claude -p "/zenwiki-ask <q>"  │                             │
│  │   --allowed-tools "Bash(zenwiki:*),Read"                      │
│  │   --output-format stream-json   │                             │
│  └──────────────┬──────────────────┘                             │
│                 │ skill orchestrates:                            │
│                 ▼  zenwiki search → Read → synthesize → JSON     │
└──────────────────────────────────────────────────────────────────┘
```

## References

- [Karpathy LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) -- the original idea
- [OmegaWiki](https://github.com/skyllwt/OmegaWiki) -- academic implementation
- [sage-wiki](https://github.com/xoai/sage-wiki) -- self-contained Go implementation
- [qmd](https://github.com/tobi/qmd) -- local Markdown search engine

## License

MIT
