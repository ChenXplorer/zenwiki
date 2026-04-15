# Contributing to ZenWiki

Thanks for your interest. This project is small and pre-1.0; contributions of bug reports, feature ideas, and pull requests are all welcome.

## Project layout

```
src/zenwiki/       Python package (CLI + FastAPI + compiler)
  ├── cli.py       Typer entrypoint (17 subcommands)
  ├── compiler.py  Orchestrates external Agent CLI (claude / codex)
  ├── web.py       FastAPI: /tree /doc /search /query /crystallize ...
  ├── search.py    SQLite FTS5 + jieba + optional qmd vector
  ├── lint.py      9 rules, 5 block compilation
  ├── static/      Built frontend bundle (tracked on purpose — ships in the wheel)
  └── templates/   `zenwiki init` scaffold
web/               Vite + React + TS frontend source
pyproject.toml
README.md
architecture-diagrams.md
```

`my-wiki/` in the project root is **your** knowledge base and is gitignored. Every user generates their own via `zenwiki init`.

## Dev setup

**Python 3.10+** and **Node 18+** required.

```bash
git clone https://github.com/ChenXplorer/zenwiki.git
cd zenwiki

# Python side (editable install)
pip install -e .

# Frontend side
cd web
npm install
cd ..
```

Optional but recommended:

- [qmd](https://github.com/tobi/qmd) — if on `$PATH`, Ask AI gets vector search; otherwise falls back to BM25 (still works).
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) or [Codex CLI](https://github.com/openai/codex) — required for `zenwiki compile` and the Web UI's Ask AI. ZenWiki shells out to whichever it finds.

## Git identity check (important)

Before your first commit, verify you're not using a work identity by accident:

```bash
git config user.email          # should be your personal email
```

If the value looks wrong, set it per-repo:

```bash
git config --local user.name "Your Name"
git config --local user.email "your@personal.email"
```

## Running locally

```bash
# Create a demo wiki in a sibling directory and use it as the project root
zenwiki init ./demo
cd demo
# Drop a few .md or .pdf files into raw/ for something to ingest.
zenwiki serve     # starts API :3334 + Vite :5173 + compile watcher, auto-opens browser
```

Or run backend and frontend separately during development:

```bash
# Terminal 1: API only
cd demo
python -m uvicorn zenwiki.web:create_app --factory --host 127.0.0.1 --port 3334

# Terminal 2: Vite dev server (proxies to :3334)
cd web
npm run dev
```

## Rebuilding the shipped frontend bundle

The bundle under `src/zenwiki/static/` is tracked in git so that `pip install git+https://...` works without Node. Whenever you change anything under `web/src/`, rebuild before committing:

```bash
cd web
npm run build
```

This writes `src/zenwiki/static/{index.html, assets/*}`. The diff may look noisy (file hashes change) — that's expected.

## Tests

There are no unit tests yet. When adding them, prefer `tests/` at the repo root and use `pytest`.

Until tests exist, **CI checks**:

- `python -m py_compile` on all modules
- `python -c "from zenwiki import cli, compiler, web, search"` — import smoke
- `tsc --noEmit` for the frontend (type check only)
- `vite build` to confirm the frontend bundles

Run locally before pushing:

```bash
python -m py_compile src/zenwiki/*.py
python -c "from zenwiki import cli, compiler, web, search; print('ok')"
cd web && npx tsc --noEmit && npm run build
```

## Pull request checklist

- [ ] Change explained in the PR description (what + why)
- [ ] `git config user.email` is your public identity, not work
- [ ] If frontend changed: frontend bundle rebuilt (`npm run build`)
- [ ] If Python dependencies added: `pyproject.toml` updated
- [ ] README / CONTRIBUTING updated if user-visible behavior changed
- [ ] No `my-wiki/` or personal content accidentally staged

## Design principles

See README → "Design Principles". Before adding abstractions or config knobs, check whether it aligns with:

1. Agent does intelligent work; ZenWiki does deterministic work.
2. File system is truth. No database beyond SQLite FTS.
3. Incremental by default.
4. Serial by default.
5. Quality is gated by lint, not assumed.

## License

By contributing, you agree your contributions will be licensed under the MIT License (see `LICENSE`).
