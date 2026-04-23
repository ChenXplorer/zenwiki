"""ZenWiki CLI — all commands in one Typer app."""

from __future__ import annotations

import json
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import find_project_root, load_config
from .markdown import slugify as _slugify

app = typer.Typer(help="ZenWiki — An implementation of Karpathy's LLM wiki idea: raw sources → agent-compiled wiki → Ask AI.", no_args_is_help=True)
console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _root(path: Optional[Path] = None) -> Path:
    return find_project_root(path)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@app.command()
def status(
    path: Optional[Path] = typer.Argument(None, help="Project root (auto-detected if omitted)"),
) -> None:
    """Show wiki statistics."""
    root = _root(path)
    from .index import status as _status
    info = _status(root / "wiki", root / "raw")

    table = Table(title="ZenWiki Status")
    table.add_column("Section", style="cyan")
    table.add_column("Pages", justify="right")

    for section, count in info["wiki_pages"].items():
        table.add_row(f"wiki/{section}/", str(count))
    table.add_row("[bold]Total wiki[/bold]", f"[bold]{info['total_wiki']}[/bold]")
    table.add_row("", "")
    for section, count in info["raw_sources"].items():
        table.add_row(f"raw/{section}/", str(count))
    table.add_row("[bold]Total raw[/bold]", f"[bold]{info['total_raw']}[/bold]")

    console.print(table)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

@app.command(name="search")
def search_cmd(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root"),
) -> None:
    """Search wiki pages using hybrid BM25 + vector search (returns JSON)."""
    root = _root(path)
    from .search import WikiIndex
    index = WikiIndex(root / "wiki")
    results = index.hybrid_search(query, limit=limit)
    typer.echo(json.dumps([{"path": r.path, "score": r.score, "snippet": r.snippet} for r in results], ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# find-similar
# ---------------------------------------------------------------------------

@app.command(name="find-similar")
def find_similar_cmd(
    name: str = typer.Argument(..., help="Name to check for duplicates"),
    dir: Optional[str] = typer.Option(None, "--dir", "-d", help="Limit to a specific wiki section"),
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root"),
) -> None:
    """Check for existing wiki pages similar to a given name (returns JSON)."""
    root = _root(path)
    from .dedup import find_similar
    target_dirs = [dir] if dir else None
    matches = find_similar(name, root / "wiki", target_dirs=target_dirs)

    # Audit log: every Agent-issued find-similar call is recorded so the
    # `unverified_dedup` lint rule can detect new pages that bypassed dedup.
    _append_dedup_audit(root, name, dir, matches)

    typer.echo(json.dumps([{"path": m.path, "title": m.title, "score": m.score} for m in matches], ensure_ascii=False, indent=2))


def _append_dedup_audit(
    root: Path,
    query: str,
    target_dir: Optional[str],
    matches: list,
) -> None:
    """Append a JSONL entry recording this find-similar invocation."""
    from datetime import datetime, timezone

    audit_dir = root / ".zenwiki"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "dedup-audit.jsonl"
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "dir": target_dir or "",
        "match_count": len(matches),
        "top_score": matches[0].score if matches else 0.0,
    }
    with audit_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# slug
# ---------------------------------------------------------------------------

@app.command()
def slug(
    title: str = typer.Argument(..., help="Title to slugify"),
) -> None:
    """Generate a kebab-case slug from a title."""
    typer.echo(_slugify(title))


# ---------------------------------------------------------------------------
# rebuild-index
# ---------------------------------------------------------------------------

@app.command(name="rebuild-index")
def rebuild_index_cmd(
    path: Optional[Path] = typer.Argument(None, help="Project root"),
) -> None:
    """Scan wiki/ and regenerate index.md + search index + vector embeddings."""
    root = _root(path)
    from .index import rebuild_index
    total = rebuild_index(root / "wiki")
    console.print(f"[green]✓[/green] index.md rebuilt — {total} pages cataloged")

    from .search import WikiIndex
    index = WikiIndex(root / "wiki")
    result = index.rebuild()
    console.print(f"[green]✓[/green] Search index rebuilt — {result.get('indexed', 0)} pages indexed")

    if result.get("qmd_embed") == "ok":
        console.print("[green]✓[/green] Vector embeddings updated via qmd")
    elif "qmd_error" in result:
        console.print(f"[yellow]⊘[/yellow] qmd embedding skipped: {result['qmd_error']}")


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------

@app.command()
def refresh(
    path: Optional[Path] = typer.Argument(None, help="Project root"),
) -> None:
    """Refresh the search index + vector embeddings (incremental — only new/changed files)."""
    root = _root(path)
    from .search import WikiIndex
    index = WikiIndex(root / "wiki")
    result = index.refresh()
    console.print(f"[green]✓[/green] Search index refreshed — {result.get('updated', 0)} updated, {result.get('deleted', 0)} deleted")

    if result.get("qmd_embed") == "ok":
        console.print("[green]✓[/green] Vector embeddings updated via qmd")
    elif "qmd_error" in result:
        console.print(f"[yellow]⊘[/yellow] qmd embedding skipped: {result['qmd_error']}")


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

@app.command(name="log")
def log_cmd(
    message: str = typer.Argument(..., help="Log message to append"),
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root"),
) -> None:
    """Append an entry to wiki/log.md."""
    root = _root(path)
    from .index import append_log
    append_log(root / "wiki", message)
    console.print(f"[green]✓[/green] Log entry added")


# ---------------------------------------------------------------------------
# retract / deprecate — lifecycle for outputs (and any wiki page)
# ---------------------------------------------------------------------------

def _resolve_wiki_target(root: Path, target: str) -> Path:
    """Validate and resolve a wiki/* path. Raises typer.Exit on invalid input."""
    rel = Path(target)
    if rel.is_absolute():
        rel = rel.relative_to(root) if str(rel).startswith(str(root)) else rel
    full = (root / rel).resolve()
    try:
        full.relative_to((root / "wiki").resolve())
    except ValueError:
        console.print(f"[red]✗[/red] Path must live under wiki/: {target}")
        raise typer.Exit(code=2)
    if not full.is_file():
        console.print(f"[red]✗[/red] File not found: {target}")
        raise typer.Exit(code=2)
    return full


@app.command(name="retract")
def retract_cmd(
    target: str = typer.Argument(..., help="Path to the wiki page (e.g. wiki/outputs/foo.md)"),
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root"),
) -> None:
    """Hard-delete a wiki page (use for clearly wrong content). Logged in log.md."""
    root = _root(path)
    full = _resolve_wiki_target(root, target)
    rel = str(full.relative_to(root))

    full.unlink()

    from .index import append_log, rebuild_index
    rebuild_index(root / "wiki")
    append_log(root / "wiki", f"retract | {rel} | hard-deleted")

    from .search import WikiIndex
    WikiIndex(root / "wiki").refresh()

    console.print(f"[green]✓[/green] Retracted {rel}")


@app.command(name="deprecate")
def deprecate_cmd(
    target: str = typer.Argument(..., help="Path to the wiki page (e.g. wiki/concepts/foo.md)"),
    reason: str = typer.Argument(..., help="Why this page is being deprecated"),
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root"),
) -> None:
    """Soft-delete a wiki page (sets deprecated: true). The file stays so
    inbound links remain visible and lint can warn callers."""
    from datetime import datetime, timezone
    from .markdown import read_frontmatter, write_frontmatter

    root = _root(path)
    full = _resolve_wiki_target(root, target)
    rel = str(full.relative_to(root))

    fm = read_frontmatter(full)
    fm["deprecated"] = True
    fm["deprecated_reason"] = reason
    fm["deprecated_at"] = datetime.now(timezone.utc).date().isoformat()
    write_frontmatter(full, fm)

    from .index import append_log, rebuild_index
    rebuild_index(root / "wiki")
    append_log(root / "wiki", f"deprecate | {rel} | reason: {reason}")

    from .search import WikiIndex
    WikiIndex(root / "wiki").refresh()

    console.print(f"[yellow]⊘[/yellow] Deprecated {rel}: {reason}")


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------

@app.command(name="lint")
def lint_cmd(
    fix: bool = typer.Option(False, "--fix", help="Auto-fix fixable issues"),
    path: Optional[Path] = typer.Argument(None, help="Project root"),
) -> None:
    """Run deterministic health checks on the wiki."""
    root = _root(path)
    from .lint import lint
    report = lint(root / "wiki", fix=fix)

    if report.fixed:
        console.print(f"[green]✓[/green] Auto-fixed {report.fixed} issue(s)")

    if report.ok:
        console.print("[bold green]All checks passed.[/bold green]")
        return

    table = Table(title="Lint Issues")
    table.add_column("Rule", style="yellow")
    table.add_column("Page", style="cyan")
    table.add_column("Message")

    for issue in report.issues:
        table.add_row(issue.rule, issue.path, issue.message)

    console.print(table)
    console.print(f"\n[yellow]{len(report.issues)} issue(s) found[/yellow]")
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# pending
# ---------------------------------------------------------------------------

@app.command()
def pending(
    path: Optional[Path] = typer.Argument(None, help="Project root (auto-detected if omitted)"),
) -> None:
    """Show raw files that need compilation."""
    root = _root(path)
    from .pending import get_pending
    files = get_pending(root)

    if not files:
        console.print("[green]All raw files are up to date.[/green]")
        return

    table = Table(title=f"{len(files)} Pending File(s)")
    table.add_column("Path", style="cyan")
    table.add_column("Reason", style="yellow")
    table.add_column("SHA-256", style="dim")

    for pf in files:
        table.add_row(pf.raw_path, pf.reason, pf.sha256[:8])

    console.print(table)


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------

@app.command(name="compile")
def compile_cmd(
    watch_mode: bool = typer.Option(False, "--watch", "-w", help="Watch raw/ for changes"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show pending files without compiling"),
    prune: bool = typer.Option(False, "--prune", help="Handle deleted source files"),
    path: Optional[Path] = typer.Argument(None, help="Project root"),
) -> None:
    """Compile pending raw files into wiki pages via Agent CLI."""
    root = _root(path)
    cfg = load_config(root)
    from .compiler import compile_once, watch
    if watch_mode:
        watch(root, dry_run=dry_run)
    else:
        compile_once(
            root,
            dry_run=dry_run,
            prune=prune,
            auto_commit=cfg.compile.auto_commit,
        )


# ---------------------------------------------------------------------------
# consolidate
# ---------------------------------------------------------------------------

@app.command()
def consolidate(
    path: Optional[Path] = typer.Argument(None, help="Project root"),
) -> None:
    """Review the full wiki and create missing comparisons/maps pages via Agent CLI."""
    root = _root(path)
    cfg = load_config(root)
    from .compiler import (
        build_consolidate_prompt,
        detect_agent,
        AgentNotFoundError,
        _run_agent,
        _COMPILE_TIMEOUT,
    )
    try:
        agent_cmd, agent_args = detect_agent(cfg.compile)
    except AgentNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    prompt = build_consolidate_prompt(root)
    console.print(f"[bold]Consolidating wiki via {agent_cmd}...[/bold]")
    ok, elapsed = _run_agent(
        [agent_cmd, *agent_args, prompt],
        cwd=root,
        timeout=_COMPILE_TIMEOUT,
        label="consolidate",
    )
    if ok:
        console.print(f"[green]✓ Consolidation completed ({elapsed:.0f}s)[/green]")
    else:
        console.print(f"[red]✗ Consolidation failed ({elapsed:.0f}s)[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

@app.command()
def doctor(
    path: Optional[Path] = typer.Argument(None, help="Project root (auto-detected if omitted)"),
) -> None:
    """Check environment readiness: external CLIs and optional search tools."""
    root = _root(path)
    ok_count = 0
    fail_count = 0

    def _check(condition: bool, label: str, detail: str = "") -> None:
        nonlocal ok_count, fail_count
        if condition:
            ok_count += 1
            console.print(f"  [green]✓[/green] {label}" + (f"  [dim]({detail})[/dim]" if detail else ""))
        else:
            fail_count += 1
            console.print(f"  [red]✗[/red] {label}" + (f"  [dim]({detail})[/dim]" if detail else ""))

    console.print(f"[bold]ZenWiki Doctor — {root}[/bold]\n")

    claude_path = shutil.which("claude")
    codex_path = shutil.which("codex")
    _check(
        claude_path is not None or codex_path is not None,
        "Agent CLI (claude or codex)",
        f"claude={claude_path or '—'}, codex={codex_path or '—'}",
    )

    qmd_path = shutil.which("qmd")
    _check(qmd_path is not None, "qmd CLI (vector search)", qmd_path or "not found — hybrid search disabled")

    console.print(f"\n[bold]{ok_count} passed, {fail_count} failed[/bold]")


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

@app.command()
def provenance(
    target: str = typer.Argument(..., help="Path to a raw source or wiki page (e.g. raw/papers/xxx.pdf)"),
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root"),
) -> None:
    """Show source-to-article provenance mappings."""
    root = _root(path)
    from .manifest import get_provenance
    info = get_provenance(root, target)

    if info.direction == "forward":
        console.print(f"[bold]Source:[/bold] {info.target}")
        if info.summary:
            console.print(f"  → Summary: [cyan]{info.summary}[/cyan]")
        else:
            console.print("  → [dim]No summary found[/dim]")
        if info.linked_pages:
            console.print(f"  → Links to: {', '.join(f'[cyan]{p}[/cyan]' for p in info.linked_pages)}")
    else:
        console.print(f"[bold]Page:[/bold] {info.target}")
        if info.raw_source:
            console.print(f"  ← Source: [cyan]{info.raw_source}[/cyan]")
        else:
            console.print("  ← [dim]No raw source found[/dim]")
        if info.referenced_by:
            console.print(f"  ← Referenced by:")
            for ref in info.referenced_by:
                console.print(f"      [cyan]{ref}[/cyan]")


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------

@app.command()
def serve(
    port: int = typer.Option(3334, "--port", help="API server port"),
    watch: bool = typer.Option(True, "--watch/--no-watch", help="Watch raw/ and auto-compile (default: on)"),
    no_ui: bool = typer.Option(False, "--no-ui", help="API only, skip starting the frontend dev server"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser automatically (default: on)"),
    path: Optional[Path] = typer.Argument(None, help="Project root"),
) -> None:
    """Start ZenWiki — API server + Web UI + auto-compile watcher."""
    import atexit
    import signal

    root = _root(path)

    if watch:
        from .compiler import start_watcher
        observer = start_watcher(root)
        if observer:
            console.print("[green]✓[/green] Compile watcher started")

    # ── Start Vite dev server as subprocess ──
    vite_proc = None
    web_dir = Path(__file__).parent.parent.parent / "web"

    if not no_ui and web_dir.is_dir() and (web_dir / "package.json").exists():
        npx = shutil.which("npx")
        if npx:
            env = {**__import__("os").environ, "FORCE_COLOR": "1"}
            vite_proc = subprocess.Popen(
                [npx, "vite", "--port", "5173", "--strictPort"],
                cwd=str(web_dir),
                env=env,
            )

            def _kill_vite():
                if vite_proc and vite_proc.poll() is None:
                    vite_proc.terminate()
                    try:
                        vite_proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        vite_proc.kill()

            atexit.register(_kill_vite)
            console.print(f"[green]✓[/green] Frontend dev server: [bold]http://localhost:5173[/bold]")
        else:
            console.print("[yellow]⊘[/yellow] npx not found, skipping frontend dev server")
    elif not no_ui:
        console.print("[yellow]⊘[/yellow] web/ directory not found, API-only mode")

    # ── Start API server ──
    import uvicorn
    from .web import create_app
    app_instance = create_app(root)

    console.print(f"[dim]  API server: http://127.0.0.1:{port}[/dim]")

    browser_url = "http://localhost:5173" if vite_proc else f"http://127.0.0.1:{port}"
    if open_browser:
        import threading
        threading.Timer(2.0, lambda: webbrowser.open(browser_url)).start()

    def _shutdown(signum, frame):
        if vite_proc and vite_proc.poll() is None:
            vite_proc.terminate()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    uvicorn.run(app_instance, host="127.0.0.1", port=port, log_level="info")


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
) -> None:
    if version:
        typer.echo(f"zenwiki {__version__}")
        raise typer.Exit()
