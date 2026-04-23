# Contributing to ZenWiki

Thanks for your interest. This project is small and pre-1.0; contributions of bug reports, feature ideas, and pull requests are all welcome.

## Repository layout

```
zenwiki/
├── README.md
├── LICENSE
├── CHANGELOG.md
├── Makefile                    One-command install / serve / clean
├── CLAUDE.md                   Dev instructions for Claude Code in this repo
├── docs/                       README screenshots
├── my-wiki/                    Content directory (tracked — this is the demo wiki)
│   ├── raw/                      Source materials (drop files here)
│   ├── wiki/                     Agent-compiled pages
│   ├── CLAUDE.md                 Schema + workflows for the compiling Agent
│   ├── config.yaml               Per-wiki config
│   └── .gitignore                Ignores local caches (.zenwiki/search.db, etc.)
└── core/                       Program (this directory)
    ├── pyproject.toml
    ├── src/zenwiki/            Python package (CLI + FastAPI + compiler)
    │   ├── cli.py              Typer entrypoint
    │   ├── compiler.py         Orchestrates external Agent CLI (claude / codex)
    │   ├── web.py              FastAPI: /tree /doc /search /query /crystallize ...
    │   ├── search.py           SQLite FTS5 + jieba + optional qmd vector
    │   ├── lint.py             Deterministic quality rules
    │   └── static/             Built frontend bundle (tracked — ships in the wheel)
    ├── web/                    Vite + React + TS frontend source
    ├── CONTRIBUTING.md
    └── architecture-diagrams.md
```

`my-wiki/` is the **content** directory. It's tracked along with the code — this repo ships with an empty scaffold (the sub-directories plus `CLAUDE.md` and `config.yaml`). Drop sources into `my-wiki/raw/` and `make serve` will compile them into `my-wiki/wiki/`.

## Dev setup

**Python 3.10+** and **Node 18+** required.

```bash
git clone https://github.com/ChenXplorer/zenwiki.git
cd zenwiki
make install                         # pip install -e ./core + npm install/build
```

What `make install` does:
- `pip install -e ./core` — editable install of the Python package
- `cd core/web && npm install && npm run build` — install frontend deps and produce the bundle under `core/src/zenwiki/static/`

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

From the repo root:

```bash
make serve           # starts API :3334 + Vite :5173 + compile watcher (runs against my-wiki/)
```

Or split the processes for iterative dev on the frontend:

```bash
# Terminal 1: API only (run from inside my-wiki so find_project_root resolves)
cd my-wiki
python -m uvicorn zenwiki.web:create_app --factory --host 127.0.0.1 --port 3334

# Terminal 2: Vite dev server (proxies to :3334)
cd core/web
npm run dev
```

## Rebuilding the shipped frontend bundle

The bundle under `core/src/zenwiki/static/` is tracked in git so that `pip install git+https://...` works without Node. Whenever you change anything under `core/web/src/`, rebuild before committing:

```bash
cd core/web
npm run build
```

This writes `core/src/zenwiki/static/{index.html, assets/*}`. The diff may look noisy (file hashes change) — that's expected.

## Tests

There are no unit tests yet. When adding them, prefer `core/tests/` and use `pytest`.

Until tests exist, **CI checks**:

- `python -m py_compile` on all modules
- `python -c "from zenwiki import cli, compiler, web, search"` — import smoke
- `tsc --noEmit` for the frontend (type check only)
- `vite build` to confirm the frontend bundles

Run locally before pushing:

```bash
python -m py_compile core/src/zenwiki/*.py
python -c "from zenwiki import cli, compiler, web, search; print('ok')"
cd core/web && npx tsc --noEmit && npm run build
```

## Pull request checklist

- [ ] Change explained in the PR description (what + why)
- [ ] `git config user.email` is your public identity, not work
- [ ] If frontend changed: frontend bundle rebuilt (`cd core/web && npm run build`)
- [ ] If Python dependencies added: `core/pyproject.toml` updated
- [ ] README / CONTRIBUTING updated if user-visible behavior changed

## Design principles

See README → "Design Principles". Before adding abstractions or config knobs, check whether it aligns with:

1. Agent does intelligent work; ZenWiki does deterministic work.
2. File system is truth. No database beyond SQLite FTS.
3. Incremental by default.
4. Serial by default.
5. Quality is gated by lint, not assumed.

## License

By contributing, you agree your contributions will be licensed under the MIT License (see `LICENSE`).
