"""FastAPI backend for ZenWiki — pure API endpoints."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import RAW_SECTIONS, WIKI_SECTIONS
from .index import append_log, rebuild_index, status as wiki_status
from .markdown import parse_frontmatter, slugify_unique, strip_frontmatter

import datetime
import yaml

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    return obj


def _render_markdown(text: str, current_path: str = "") -> str:
    import markdown as md

    current_section = current_path.split("/")[0] if "/" in current_path else ""

    def _replace_wikilink(m: re.Match) -> str:
        target = m.group(1).strip()
        display = (m.group(2) or target).strip()
        if "/" in target:
            doc_path = f"wiki/{target}.md"
        elif current_section:
            doc_path = f"wiki/{current_section}/{target}.md"
        else:
            doc_path = f"wiki/{target}.md"
        return f'<a class="wikilink" href="#" data-path="{doc_path}">{display}</a>'

    text = _WIKILINK_RE.sub(_replace_wikilink, text)
    return md.markdown(text, extensions=["tables", "fenced_code", "toc"])


def _build_tree(base: Path, prefix: str, sections: tuple[str, ...]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for section in sections:
        section_dir = base / section
        if not section_dir.is_dir():
            continue
        children: list[dict[str, Any]] = []
        for item in sorted(section_dir.iterdir()):
            if item.name.startswith("."):
                continue
            children.append({
                "name": item.name,
                "path": f"{prefix}/{section}/{item.name}",
                "type": "file",
            })
        nodes.append({
            "name": section,
            "path": f"{prefix}/{section}",
            "type": "dir",
            "children": children,
        })
    return nodes


def create_app(root: Path) -> FastAPI:
    from .config import load_config
    from .search import WikiIndex
    load_config(root)  # parse config.yaml (currently unused here but validates it)
    _wiki_index = WikiIndex(root / "wiki")
    _wiki_index.refresh()

    api = FastAPI(title="ZenWiki", version="0.1.0")

    @api.get("/tree")
    async def tree() -> JSONResponse:
        wiki_tree = _build_tree(root / "wiki", "wiki", WIKI_SECTIONS)
        raw_tree = _build_tree(root / "raw", "raw", RAW_SECTIONS)

        top_level_wiki: list[dict[str, Any]] = []
        for name in ("index.md", "log.md"):
            if (root / "wiki" / name).exists():
                top_level_wiki.append({"name": name, "path": f"wiki/{name}", "type": "file"})

        return JSONResponse([
            {"name": "wiki", "type": "dir", "children": top_level_wiki + wiki_tree},
            {"name": "raw", "type": "dir", "children": raw_tree},
        ])

    @api.get("/doc")
    async def doc(path: str = Query(..., description="Relative path to document")) -> JSONResponse:
        safe = Path(path)
        if ".." in safe.parts:
            return JSONResponse({"error": "invalid path"}, status_code=400)
        full = root / safe
        if not full.exists() or not full.is_file():
            return JSONResponse({"error": "not found"}, status_code=404)

        text = full.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        body = strip_frontmatter(text)
        wiki_rel = str(safe).removeprefix("wiki/").removesuffix(".md")
        html = _render_markdown(body, current_path=wiki_rel)
        return JSONResponse({"path": path, "frontmatter": _jsonable(fm), "html": html})

    @api.get("/search")
    async def search_endpoint(q: str = Query(..., min_length=1)) -> JSONResponse:
        results = _wiki_index.hybrid_search(q)
        return JSONResponse([{"path": r.path, "score": r.score, "snippet": r.snippet} for r in results])

    @api.get("/query")
    async def query_endpoint(q: str = Query(..., min_length=1)) -> JSONResponse:
        """Search + AI answer: spawn the Agent CLI with the zenwiki-ask
        skill so it does its own search, reads pages, and synthesizes."""
        # Local retrieval populates the "results" panel below the answer.
        # The skill independently re-runs the same search inside the agent;
        # this duplicate is cheap and keeps the UI's transparency list
        # working without coupling it to the skill's output schema.
        local_results = _wiki_index.hybrid_search(q, limit=10, exclude_deprecated=True)
        results_payload = [
            {"path": r.path, "score": r.score, "snippet": r.snippet}
            for r in local_results
        ]

        agent = _detect_query_agent()
        if agent is None:
            return JSONResponse({
                "answer": "", "sources": [], "results": results_payload,
                "error": "No Agent CLI found (install claude or codex)",
            })

        # `/zenwiki-ask` forces the skill to load even in -p / exec mode,
        # where description-based auto-trigger is unreliable. Verified via
        # claude -p experiment in stage 0.
        prompt = f"/zenwiki-ask {q}"

        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                agent.argv(prompt),
                capture_output=True, text=True, timeout=180,
                cwd=str(root), stdin=subprocess.DEVNULL,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return JSONResponse({
                "answer": "", "sources": [], "results": results_payload,
                "error": f"Agent failed: {exc.__class__.__name__}",
            })

        if proc.returncode != 0:
            return JSONResponse({
                "answer": "", "sources": [], "results": results_payload,
                "error": f"Agent exit {proc.returncode}: {proc.stderr[:200]}",
            })

        parsed = agent.parse(proc.stdout)
        return JSONResponse({
            "answer": parsed.get("answer", ""),
            "sources": parsed.get("sources", []),
            "results": results_payload,
        })

    @api.get("/status")
    async def status_endpoint() -> JSONResponse:
        info = wiki_status(root / "wiki", root / "raw")
        return JSONResponse(info)

    @api.post("/rebuild-index")
    async def rebuild_index_endpoint() -> JSONResponse:
        result = _wiki_index.rebuild()
        return JSONResponse(result)

    @api.post("/refresh-index")
    async def refresh_index_endpoint() -> JSONResponse:
        result = _wiki_index.refresh()
        return JSONResponse(result)

    @api.post("/crystallize")
    async def crystallize_endpoint(payload: dict = Body(...)) -> JSONResponse:
        """Persist an Ask-AI answer as a wiki/outputs/{slug}.md page.

        Body: {question: str, answer: str, sources: list[str]}
        Writes immediately and refreshes the search index so the page is searchable.
        """
        question = (payload.get("question") or "").strip()
        answer = (payload.get("answer") or "").strip()
        sources = payload.get("sources") or []

        if not question or not answer:
            return JSONResponse(
                {"error": "question and answer are required"}, status_code=400
            )

        outputs_dir = root / "wiki" / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        existing = {p.stem for p in outputs_dir.glob("*.md")}
        slug = slugify_unique(question[:80], existing)
        if not slug:
            slug = slugify_unique(
                f"query-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}",
                existing,
            )

        out_path = outputs_dir / f"{slug}.md"
        title = question if len(question) <= 120 else question[:117] + "..."
        frontmatter = {
            "title": title,
            "date_added": datetime.date.today().isoformat(),
            "citations": list(sources),
            "crystallized_from_query": True,
        }
        body_text = f"## Question\n\n{question}\n\n## Answer\n\n{answer}\n"
        yaml_str = yaml.dump(
            frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False,
        ).rstrip("\n")
        out_path.write_text(f"---\n{yaml_str}\n---\n{body_text}", encoding="utf-8")

        # Make the new page visible to (a) Agent ingest workflows that read index.md
        # and (b) the audit trail in log.md. Without these calls /crystallize is a
        # half-loop — the page exists but the rest of the system can't see it.
        rebuild_index(root / "wiki")
        append_log(root / "wiki", f"crystallize | outputs/{slug} | from query")
        _wiki_index.refresh()

        rel = str(out_path.relative_to(root))
        return JSONResponse({"path": rel, "slug": slug})

    # Serve the bundled Web UI (Vite build output) when present. Mounted last so
    # all JSON endpoints above take precedence. In dev mode (Vite on :5173) this
    # is unused.
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir() and (static_dir / "index.html").is_file():
        api.mount(
            "/",
            StaticFiles(directory=str(static_dir), html=True),
            name="ui",
        )

    return api


class _Agent:
    __slots__ = ("cmd", "pre", "post", "parse")

    def __init__(self, cmd: str, pre: list[str], post: list[str], parse):
        self.cmd = cmd
        self.pre = pre   # flags BEFORE the prompt positional
        self.post = post  # flags AFTER the prompt positional
        self.parse = parse

    def argv(self, prompt: str) -> list[str]:
        return [self.cmd, *self.pre, prompt, *self.post]


def _detect_query_agent() -> "_Agent | None":
    """Find an Agent CLI for Q&A and return a parser bound to its output
    format. Claude is preferred because --allowed-tools gives a precise
    command-level whitelist; codex is a fallback (--full-auto opens the
    whole workspace and prompt-injection surface is wider — see README's
    "Security model" section).

    Claude's --allowed-tools is variadic and would greedily consume any
    positional arg (including the prompt) that follows it. Putting the
    prompt right after `-p` and the variadic flag last keeps argv
    unambiguous.
    """
    if claude := shutil.which("claude"):
        return _Agent(
            cmd=claude,
            pre=["-p"],
            post=[
                "--output-format", "json",
                "--allowed-tools", "Bash(zenwiki:*),Read",
            ],
            parse=_parse_claude_json,
        )

    if codex := shutil.which("codex"):
        # Codex path is untested locally — see README warning. Skill
        # bundle is mirrored at .agents/skills/, but exec output schema
        # has not been validated against this parser.
        return _Agent(
            cmd=codex,
            pre=["exec", "--full-auto"],
            post=[],
            parse=_parse_codex_text,
        )

    return None


def _parse_claude_json(stdout: str) -> dict[str, Any]:
    """Parse `claude -p --output-format json`. The envelope's `result`
    field carries the model's final assistant message as a string. The
    zenwiki-ask skill is instructed to emit a JSON object as that
    message, so we json-load it once more. If the model violated that
    contract, fall back to using the raw text as the answer."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return {"answer": "", "sources": []}

    inner = (envelope.get("result") or "").strip()
    if not inner:
        return {"answer": "", "sources": []}

    try:
        parsed = json.loads(inner)
        if isinstance(parsed, dict):
            return {
                "answer": str(parsed.get("answer", "")),
                "sources": list(parsed.get("sources") or []),
            }
    except json.JSONDecodeError:
        pass

    return {"answer": inner, "sources": []}


def _parse_codex_text(stdout: str) -> dict[str, Any]:
    """Codex exec output parser — UNTESTED on this machine. Until the
    skill round-trip is validated against codex, treat the entire stdout
    as plain answer text with no sources. Safe degradation."""
    return {"answer": stdout.strip(), "sources": []}
