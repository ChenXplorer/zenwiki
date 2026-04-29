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
from fastapi.responses import JSONResponse, StreamingResponse
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
    async def query_endpoint(q: str = Query(..., min_length=1)) -> StreamingResponse:
        """Server-sent event stream for Ask AI. Spawns the Agent CLI with
        the zenwiki-ask skill, then translates the agent's stream-json
        events into UI-level progress steps. Codex (no streaming schema
        validated locally) falls back to a single done event after the
        subprocess finishes.

        Event sequence (claude path):
          results  → {results: [{path, score, snippet}, ...]}
          step     → {kind: 'searching' | 'reading' | 'synthesizing', detail?}
          done     → {answer, sources}
          error    → {message}   (terminal; replaces done)
        """
        # Local retrieval seeds the results panel before the agent even
        # starts. The skill re-runs the same search internally; this
        # duplicate is cheap and keeps transparency working without
        # coupling UI to the skill's output schema.
        local_results = _wiki_index.hybrid_search(q, limit=10, exclude_deprecated=True)
        results_payload = [
            {"path": r.path, "score": r.score, "snippet": r.snippet}
            for r in local_results
        ]

        return StreamingResponse(
            _stream_query(q, results_payload, root),
            media_type="text/event-stream",
            headers={
                # Disable buffering at proxies; SSE needs immediate flush.
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

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
    __slots__ = ("cmd", "pre", "post", "parse", "streaming")

    def __init__(
        self,
        cmd: str,
        pre: list[str],
        post: list[str],
        parse,
        streaming: bool,
    ):
        self.cmd = cmd
        self.pre = pre   # flags BEFORE the prompt positional
        self.post = post  # flags AFTER the prompt positional
        self.parse = parse
        self.streaming = streaming

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
                "--output-format", "stream-json",
                # --verbose is required when stream-json is used with -p,
                # otherwise claude exits with a usage error.
                "--verbose",
                "--allowed-tools", "Bash(zenwiki:*),Read",
            ],
            parse=_translate_claude_stream,
            streaming=True,
        )

    if codex := shutil.which("codex"):
        # Codex path is untested locally — see README warning. Skill
        # bundle is mirrored at .agents/skills/, but exec output schema
        # has not been validated against this parser. Stays non-streaming
        # until the schema is verified.
        return _Agent(
            cmd=codex,
            pre=["exec", "--full-auto"],
            post=[],
            parse=_parse_codex_text,
            streaming=False,
        )

    return None


def _parse_codex_text(stdout: str) -> dict[str, Any]:
    """Codex exec output parser — UNTESTED on this machine. Until the
    skill round-trip is validated against codex, treat the entire stdout
    as plain answer text with no sources. Safe degradation."""
    return {"answer": stdout.strip(), "sources": []}


def _sse(event: str, data: dict[str, Any]) -> str:
    """Serialize a single SSE frame. Two newlines terminate the frame
    per the spec; missing them causes the browser EventSource to buffer
    indefinitely."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_query(q: str, results_payload: list[dict], root: Path):
    """Async generator yielding SSE frames for /query. Three phases:
    (1) results panel; (2) live progress from the agent's stream-json;
    (3) terminal done/error. Errors at any phase produce a single
    `error` frame and the stream ends.
    """
    yield _sse("results", {"results": results_payload})

    agent = _detect_query_agent()
    if agent is None:
        yield _sse("error", {"message": "No Agent CLI found (install claude or codex)"})
        return

    # `/zenwiki-ask` is mandatory: Stage-0 confirmed claude -p does NOT
    # auto-trigger the skill from description alone.
    prompt = f"/zenwiki-ask {q}"
    argv = agent.argv(prompt)

    if not agent.streaming:
        # Codex path: run sync, emit a single done event with the parsed
        # output. No intermediate progress until codex stream-json schema
        # is validated.
        yield _sse("step", {"kind": "searching", "detail": ""})
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                argv, capture_output=True, text=True, timeout=180,
                cwd=str(root), stdin=subprocess.DEVNULL,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            yield _sse("error", {"message": f"Agent failed: {exc.__class__.__name__}"})
            return
        if proc.returncode != 0:
            yield _sse("error", {"message": f"Agent exit {proc.returncode}: {proc.stderr[:200]}"})
            return
        parsed = agent.parse(proc.stdout)
        yield _sse("done", {"answer": parsed.get("answer", ""), "sources": parsed.get("sources", [])})
        return

    # Claude streaming path.
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(root),
        stdin=asyncio.subprocess.DEVNULL,
    )

    final_envelope: dict[str, Any] | None = None
    synth_emitted = False

    try:
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            ui_event = _translate_claude_event(ev, synth_emitted)
            if ui_event is None:
                continue
            kind, payload = ui_event
            if kind == "synthesizing":
                synth_emitted = True
            if kind == "result":
                final_envelope = ev
                continue
            yield _sse("step", payload)
    except asyncio.CancelledError:
        proc.kill()
        raise

    rc = await proc.wait()
    if rc != 0 and final_envelope is None:
        err = (await proc.stderr.read()).decode("utf-8", errors="replace")[:200]
        yield _sse("error", {"message": f"Agent exit {rc}: {err}"})
        return

    if final_envelope is None:
        yield _sse("error", {"message": "Agent finished without a result event"})
        return

    parsed = _translate_claude_stream(final_envelope)
    yield _sse("done", {"answer": parsed.get("answer", ""), "sources": parsed.get("sources", [])})


def _translate_claude_event(
    ev: dict[str, Any],
    synth_emitted: bool,
) -> tuple[str, dict[str, Any]] | None:
    """Map one stream-json event to a UI-level (kind, payload) pair.
    Returns None for events that have no UI value (rate-limit pings,
    hook lifecycle, init handshakes, intermediate tool results). The
    `result` event is mapped to `("result", {})` so the caller knows
    to capture the envelope from outside this function.

    Probed schema (stage-0):
      type=system,subtype=init|hook_started|hook_response  → skip
      type=rate_limit_event                                → skip
      type=assistant, content[0].type=thinking             → skip
      type=assistant, content[0].type=tool_use,name=Bash   → ("searching", {detail})
      type=assistant, content[0].type=tool_use,name=Read   → ("reading", {detail})
      type=assistant, content[0].type=text                 → ("synthesizing", {})  (first only)
      type=user (tool_result)                              → skip
      type=result                                          → ("result", {})
    """
    t = ev.get("type")
    if t == "result":
        return "result", {}
    if t != "assistant":
        return None

    content = (ev.get("message") or {}).get("content") or []
    if not isinstance(content, list) or not content:
        return None

    first = content[0]
    kind = first.get("type")
    if kind == "tool_use":
        name = first.get("name", "")
        inp = first.get("input") or {}
        if name == "Bash":
            return "searching", {
                "kind": "searching",
                "detail": str(inp.get("command", ""))[:200],
            }
        if name == "Read":
            return "reading", {
                "kind": "reading",
                "detail": str(inp.get("file_path", ""))[:200],
            }
        return None
    if kind == "text" and not synth_emitted:
        return "synthesizing", {"kind": "synthesizing", "detail": ""}
    return None


def _translate_claude_stream(envelope: dict[str, Any]) -> dict[str, Any]:
    """Pull the final {answer, sources} out of a stream-json result
    event. Same envelope shape as `claude -p --output-format json`:
    `result` is the model's last assistant message as a string, and
    the skill is instructed to emit that as a JSON object."""
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
