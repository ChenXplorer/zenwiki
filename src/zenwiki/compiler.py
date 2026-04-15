"""Compiler orchestration: detect Agent CLI, build prompts, run headless compilation.

This module does NOT call LLM APIs directly. It orchestrates external Agent CLIs
(Claude Code or Codex) to perform the actual knowledge compilation.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

from .config import CompileConfig, load_config
from .manifest import (
    get_removed,
    load_manifest,
    mark_compiled,
    mark_failed,
    save_manifest,
)
from .lint import lint as run_lint
from .markdown import read_frontmatter
from .pending import PendingFile, get_pending

console = Console()

_manifest_lock = threading.Lock()

_LINT_GATE_BLOCKING: set[str] = {
    "missing_frontmatter",
    "empty_section",
    "thin_summary",         # Technical Details too short → reject
    "missing_backlink",     # forward link without backlink → reject
    "link_to_deprecated",   # citing deprecated content → reject
    # Note: unverified_dedup is warn-only (not in this set)
}

# ── Subprocess tuning ──────────────────────────────────────────────
_COMPILE_TIMEOUT = 1200     # 20 min per batch
_PREFLIGHT_TIMEOUT = 60     # 1 min for health check
_FAST_FAIL_THRESHOLD = 60   # exit this fast with error → likely API-level failure

# Shared abort flag: set on fatal errors so queued batches skip immediately.
_abort_event = threading.Event()

# ── Watcher retry backoff (seconds) ───────────────────────────────
_RETRY_BACKOFF = [120, 300, 600]  # 2 min, 5 min, 10 min then cap


# ─── Data ──────────────────────────────────────────────────────────

@dataclass
class CompileResult:
    pending_count: int = 0
    compiled: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    aborted: bool = False


class AgentNotFoundError(Exception):
    pass


# ─── Agent detection ───────────────────────────────────────────────

def detect_agent(config: CompileConfig) -> tuple[str, list[str]]:
    """Find an available Agent CLI, respecting the config preference.

    Returns (command, args_list).
    Raises AgentNotFoundError if no agent is found.
    """
    candidates: list[tuple[str, list[str]]] = []

    if config.agent in ("auto", "claude"):
        candidates.append(("claude", ["-p", "--dangerously-skip-permissions"]))
    if config.agent in ("auto", "codex"):
        candidates.append(("codex", ["exec", "--full-auto"]))

    for cmd, args in candidates:
        if shutil.which(cmd):
            return cmd, args

    install_hints = (
        "Install one of the following Agent CLIs:\n"
        "  - Claude Code: https://docs.anthropic.com/en/docs/claude-code\n"
        "  - Codex CLI:   https://github.com/openai/codex\n"
    )
    raise AgentNotFoundError(
        f"No Agent CLI found (looked for: {config.agent}).\n{install_hints}"
    )


# ─── Prompt builders ──────────────────────────────────────────────

def build_prompt(batch: list[PendingFile]) -> str:
    """Assemble the prompt for a batch of files (typically 1-5)."""
    file_list = "\n".join(
        f"  {i}. {pf.raw_path}" for i, pf in enumerate(batch, 1)
    )
    return (
        "You are a knowledge-base compilation agent. "
        "Read CLAUDE.md in the project root to understand all rules and workflows.\n\n"
        f"There are {len(batch)} source file(s) to process. "
        "For EACH file, execute the /ingest workflow from CLAUDE.md (Steps 1-8):\n\n"
        f"{file_list}\n\n"
        "Requirements:\n"
        "- Follow every step in the /ingest workflow strictly.\n"
        "- Run `zenwiki find-similar` before creating any new page.\n"
        "- After processing each file, run `zenwiki rebuild-index` and `zenwiki refresh`.\n"
        "- After all files are done, report: pages created, pages updated, open questions.\n"
    )


def build_prune_prompt(removed: list[tuple[str, str]]) -> str:
    """Assemble the prompt for handling deleted source files."""
    file_list = "\n".join(
        f"  - {raw_path} → wiki/summaries/{slug}.md"
        for raw_path, slug in removed
        if slug
    )
    return (
        "You are a knowledge-base maintenance agent. "
        "Read CLAUDE.md in the project root to understand all rules.\n\n"
        "The following source files have been DELETED from raw/. "
        "Their corresponding wiki summaries may now be orphaned:\n\n"
        f"{file_list}\n\n"
        "For each deleted source:\n"
        "1. Read the summary page and check if it is referenced by other pages.\n"
        "2. If no other pages reference it, delete the summary.\n"
        "3. If other pages reference it, add a deprecation notice to the summary frontmatter.\n"
        "4. Clean up any broken wikilinks in other pages.\n"
        "5. Run `zenwiki rebuild-index` and `zenwiki refresh` when done.\n"
        "6. Run `zenwiki log \"prune | removed: <list>\"` to record the operation.\n"
    )


def _wiki_stats(root: Path) -> dict[str, int]:
    """Count .md files in each wiki subdirectory."""
    wiki = root / "wiki"
    stats: dict[str, int] = {}
    for section in ("summaries", "entities", "concepts", "comparisons", "maps", "outputs"):
        d = wiki / section
        stats[section] = len(list(d.glob("*.md"))) if d.is_dir() else 0
    return stats


def build_consolidate_prompt(root: Path) -> str:
    """Assemble the prompt for the /consolidate workflow."""
    stats = _wiki_stats(root)
    stats_line = ", ".join(f"{v} {k}" for k, v in stats.items())
    return (
        "You are a knowledge-base consolidation agent. "
        "Read CLAUDE.md in the project root to understand all rules and workflows.\n\n"
        "Execute the /consolidate workflow from CLAUDE.md (Steps 1-6).\n\n"
        f"Current wiki stats: {stats_line}.\n\n"
        "Your goal is to review the FULL wiki and create missing comparisons/ and maps/ pages. "
        "The wiki has accumulated enough content that higher-order synthesis pages are overdue.\n\n"
        "Requirements:\n"
        "- Read wiki/index.md and scan concept/entity frontmatter to find opportunities.\n"
        "- Run `zenwiki find-similar` before creating any new page.\n"
        "- Create substantive pages — not stubs.\n"
        "- After all pages are created, run `zenwiki rebuild-index` and `zenwiki refresh`.\n"
        "- Report: comparisons created, maps created/updated.\n"
    )


# ─── Helpers ──────────────────────────────────────────────────────

def _verify_single(root: Path, pf: PendingFile) -> str | None:
    """Check if a single file was compiled by scanning wiki/summaries/ for its source_path."""
    summaries_dir = root / "wiki" / "summaries"
    if not summaries_dir.is_dir():
        return None
    for md in summaries_dir.glob("*.md"):
        fm = read_frontmatter(md)
        if fm.get("source_path", "") == pf.raw_path:
            return md.stem
    return None


def _append_run_log(
    cwd: Path,
    *,
    label: str,
    cmd: list[str],
    returncode: int | None,
    elapsed: float,
    ok: bool,
    outcome: str,
) -> None:
    """Persist one Agent subprocess result to .zenwiki/compile-runs.jsonl.

    stdout/stderr are not captured (terminal passthrough), so this log keeps
    the metadata useful for post-hoc debugging: timing, returncode, launch
    command, terminal outcome (ok / nonzero / timeout / launch_error).
    """
    import json
    from datetime import datetime, timezone

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "cmd": cmd[0] if cmd else "",
        "argv_len": len(cmd),
        "returncode": returncode,
        "elapsed_s": round(elapsed, 2),
        "ok": ok,
        "outcome": outcome,
    }
    try:
        log_dir = cwd / ".zenwiki"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "compile-runs.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        # Logging must never break compilation.
        pass


def _run_agent(
    cmd: list[str],
    cwd: Path,
    timeout: int,
    label: str,
) -> tuple[bool, float]:
    """Run an Agent CLI subprocess.

    stdout/stderr go to the terminal (no piping — CLI hangs if it detects
    non-TTY).  stdin is /dev/null to prevent interactive prompts.

    Returns (success, elapsed_seconds).
    """
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=cwd,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
        elapsed = time.monotonic() - start
        if proc.returncode != 0:
            console.print(
                f"  [red]{label}[/red] exited with code {proc.returncode} "
                f"({elapsed:.0f}s)"
            )
            _append_run_log(
                cwd, label=label, cmd=cmd,
                returncode=proc.returncode, elapsed=elapsed,
                ok=False, outcome="nonzero_exit",
            )
            return False, elapsed
        _append_run_log(
            cwd, label=label, cmd=cmd,
            returncode=0, elapsed=elapsed,
            ok=True, outcome="ok",
        )
        return True, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        console.print(
            f"  [red]{label}[/red] timed out after {timeout}s"
        )
        _append_run_log(
            cwd, label=label, cmd=cmd,
            returncode=None, elapsed=elapsed,
            ok=False, outcome="timeout",
        )
        return False, elapsed
    except OSError as exc:
        elapsed = time.monotonic() - start
        console.print(
            f"  [red]{label}[/red] failed to launch: {exc}"
        )
        _append_run_log(
            cwd, label=label, cmd=cmd,
            returncode=None, elapsed=elapsed,
            ok=False, outcome=f"launch_error: {exc}",
        )
        return False, elapsed


_PREFLIGHT_CACHE_FILE = "preflight.json"


def _preflight_cache_path(root: Path) -> Path:
    return root / ".zenwiki" / _PREFLIGHT_CACHE_FILE


def _read_preflight_cache(
    root: Path, agent_cmd: str, agent_args: list[str], ttl_seconds: int,
) -> bool | None:
    """Return cached preflight result if fresh and matches the same agent.
    Match is keyed on (agent_cmd, agent_args) so switching between
    claude/codex or changing CLI flags invalidates stale entries.
    Only positive results are cached — failures must be re-checked."""
    if ttl_seconds <= 0:
        return None
    cache_path = _preflight_cache_path(root)
    if not cache_path.is_file():
        return None
    try:
        import json
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("agent_cmd") != agent_cmd or not data.get("ok"):
        return None
    if list(data.get("agent_args") or []) != list(agent_args):
        return None
    ts = float(data.get("ts", 0))
    if time.time() - ts > ttl_seconds:
        return None
    return True


def _write_preflight_cache(
    root: Path, agent_cmd: str, agent_args: list[str], ok: bool,
) -> None:
    """Persist a successful preflight result. Failures are not cached so
    transient outages are re-tested promptly."""
    if not ok:
        return
    import json
    cache_path = _preflight_cache_path(root)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({
            "ts": time.time(),
            "agent_cmd": agent_cmd,
            "agent_args": list(agent_args),
            "ok": True,
        }),
        encoding="utf-8",
    )


def _preflight_check(
    root: Path,
    agent_cmd: str,
    agent_args: list[str],
    cache_ttl_seconds: int = 0,
) -> bool:
    """Quick health check — verify the Agent CLI can reach its API.

    With cache_ttl_seconds > 0, a recent successful result is reused without
    spending another LLM round-trip. Failures are never cached.
    """
    cached = _read_preflight_cache(root, agent_cmd, agent_args, cache_ttl_seconds)
    if cached:
        console.print(f"[dim]Pre-flight: cache hit ({agent_cmd})[/dim]")
        return True

    console.print("[dim]Pre-flight: checking agent connectivity...[/dim]")
    ok, elapsed = _run_agent(
        [agent_cmd, *agent_args, "respond with: OK"],
        cwd=root,
        timeout=_PREFLIGHT_TIMEOUT,
        label="preflight",
    )
    if ok:
        console.print("[green]Pre-flight: OK[/green]")
        _write_preflight_cache(root, agent_cmd, agent_args, True)
    else:
        console.print(
            "[red]Pre-flight: agent unreachable — skipping compilation[/red]"
        )
    return ok


# ─── Batch compilation ────────────────────────────────────────────

def _run_consolidate(
    root: Path,
    agent_cmd: str,
    agent_args: list[str],
) -> bool:
    """Run the /consolidate workflow — Agent reviews the full wiki and
    creates missing comparisons/maps pages. Soft-fails: returns False but
    does not abort compilation. Called per-batch from compile_once."""
    console.print("[bold]Consolidating wiki (comparisons/maps)...[/bold]")
    consolidate_prompt = build_consolidate_prompt(root)
    ok, _ = _run_agent(
        [agent_cmd, *agent_args, consolidate_prompt],
        cwd=root,
        timeout=_COMPILE_TIMEOUT,
        label="consolidate",
    )
    if ok:
        console.print("[green]✓ Consolidation pass completed[/green]")
    else:
        console.print("[yellow]⚠ Consolidation pass failed (continuing)[/yellow]")
    return ok


def _compile_batch(
    root: Path,
    agent_cmd: str,
    agent_args: list[str],
    batch: list[PendingFile],
    batch_idx: int,
) -> list[tuple[str, bool, str | None]]:
    """Compile a single batch via Agent CLI, then verify output.

    Returns list of (raw_path, ok, summary_slug).
    """
    # Fast-skip if a fatal error was already detected by another batch.
    if _abort_event.is_set():
        results: list[tuple[str, bool, str | None]] = []
        for pf in batch:
            with _manifest_lock:
                mark_failed(root, pf.raw_path)
            results.append((pf.raw_path, False, None))
        return results

    prompt = build_prompt(batch)
    label = f"batch {batch_idx}"

    ok, elapsed = _run_agent(
        [agent_cmd, *agent_args, prompt],
        cwd=root,
        timeout=_COMPILE_TIMEOUT,
        label=label,
    )

    if not ok and elapsed < _FAST_FAIL_THRESHOLD:
        _abort_event.set()

    results = []
    for pf in batch:
        slug = _verify_single(root, pf) if ok else None
        with _manifest_lock:
            if slug:
                mark_compiled(root, pf.raw_path, slug)
            else:
                mark_failed(root, pf.raw_path)
        results.append((pf.raw_path, slug is not None, slug))
    return results


# ─── Git ──────────────────────────────────────────────────────────

def _auto_git_commit(root: Path, result: CompileResult) -> None:
    """Stage wiki/ and .zenwiki/ changes, then commit."""
    if not (root / ".git").is_dir():
        return
    parts: list[str] = []
    if result.compiled:
        parts.append(f"{len(result.compiled)} compiled")
    if result.failed:
        parts.append(f"{len(result.failed)} failed")
    if result.pruned:
        parts.append(f"{len(result.pruned)} pruned")
    msg = f"compile: {', '.join(parts)}" if parts else "compile: no changes"

    subprocess.run(
        ["git", "add", "wiki/", ".zenwiki/"],
        cwd=root, capture_output=True,
    )
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=root, capture_output=True,
    )
    if diff.returncode != 0:
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=root, capture_output=True,
        )


# ─── Main entry: compile_once ─────────────────────────────────────

def compile_once(
    root: Path,
    *,
    dry_run: bool = False,
    prune: bool = False,
    auto_commit: bool = True,
) -> CompileResult:
    """Run a single compilation pass with parallel batch processing."""
    cfg = load_config(root)
    pending_files = get_pending(root)
    removed = (
        get_removed(root, grace_hours=cfg.compile.prune_grace_hours)
        if prune else []
    )

    result = CompileResult(pending_count=len(pending_files))

    if not pending_files and not removed:
        console.print("[green]All raw files are up to date. Nothing to compile.[/green]")
        return result

    batch_size = cfg.compile.batch_size
    concurrency = cfg.compile.concurrency
    # Parallel Agent processes can race on wiki/index.md, wiki/log.md and
    # same-name concept pages — no cross-process locking yet. Honour the
    # user's configured value (README calls this out as a known trade-off)
    # but warn loudly so they don't raise it by accident.
    if concurrency > 1:
        console.print(
            f"[yellow]⚠ compile.concurrency={concurrency}: parallel Agents "
            f"may race on wiki/index.md and wiki/log.md.[/yellow]"
        )

    batches = [
        pending_files[i : i + batch_size]
        for i in range(0, len(pending_files), batch_size)
    ]

    if dry_run:
        if pending_files:
            console.print(
                f"[bold]{len(pending_files)} file(s) pending "
                f"({len(batches)} batches x {batch_size}, concurrency={concurrency}):[/bold]"
            )
            for pf in pending_files:
                console.print(f"  {pf.reason:10s} {pf.raw_path}  [{pf.sha256[:8]}]")
        if removed:
            console.print(f"\n[bold]{len(removed)} source(s) removed:[/bold]")
            for rm in removed:
                console.print(f"  deleted   {rm.raw_path}  → summaries/{rm.summary_slug}")
        return result

    try:
        agent_cmd, agent_args = detect_agent(cfg.compile)
    except AgentNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        return result

    # ── Pre-flight health check ──────────────────────────────────
    if batches and not _preflight_check(
        root, agent_cmd, agent_args,
        cache_ttl_seconds=cfg.compile.preflight_cache_seconds,
    ):
        result.aborted = True
        for pf in pending_files:
            result.failed.append(pf.raw_path)
            with _manifest_lock:
                mark_failed(root, pf.raw_path)
        console.print(
            f"\n[yellow]✗ {len(pending_files)} file(s) marked failed "
            f"(agent unreachable)[/yellow]"
        )
        return result

    # ── Parallel batch compilation ───────────────────────────────
    threshold = cfg.compile.consolidate_threshold
    if batches:
        total = len(pending_files)
        _abort_event.clear()
        console.print(
            f"[bold]Compiling {total} file(s) via {agent_cmd} "
            f"({len(batches)} batches x {batch_size}, "
            f"concurrency={concurrency})...[/bold]"
        )

        done_count = 0
        compiled_slugs: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(
                    _compile_batch, root, agent_cmd, agent_args, batch, idx
                ): batch
                for idx, batch in enumerate(batches)
            }
            for future in as_completed(futures):
                batch_compiled_count = 0
                for raw_path, ok, slug in future.result():
                    done_count += 1
                    ts = time.strftime("%H:%M:%S")
                    if ok:
                        result.compiled.append(raw_path)
                        batch_compiled_count += 1
                        if slug:
                            compiled_slugs[slug] = raw_path
                        console.print(
                            f"[dim][{ts}][/dim] [{done_count:3d}/{total}] "
                            f"[green]compiled[/green]  {raw_path}"
                        )
                    else:
                        result.failed.append(raw_path)
                        console.print(
                            f"[dim][{ts}][/dim] [{done_count:3d}/{total}] "
                            f"[red]FAILED[/red]    {raw_path}"
                        )

                # Per-batch consolidate: each batch that contributed N+ compiled
                # files triggers a consolidation pass so comparisons/maps grow
                # continuously rather than only once at the end of a bulk run.
                # Skipped on abort; lint gate still runs once at the end.
                if (
                    threshold > 0
                    and batch_compiled_count >= threshold
                    and not _abort_event.is_set()
                ):
                    _run_consolidate(root, agent_cmd, agent_args)

        if _abort_event.is_set():
            result.aborted = True
            console.print(
                "[red bold]Fatal error detected — "
                "remaining batches were skipped[/red bold]"
            )

        # ── Lint gate ────────────────────────────────────────────
        if compiled_slugs:
            report = run_lint(root / "wiki")
            demoted: list[str] = []
            for issue in report.issues:
                if not issue.path.startswith("summaries/"):
                    continue
                stem = issue.path.split("/", 1)[1]
                if stem not in compiled_slugs:
                    continue
                raw_path = compiled_slugs[stem]
                if issue.rule in _LINT_GATE_BLOCKING:
                    if raw_path not in demoted:
                        demoted.append(raw_path)
                        result.compiled.remove(raw_path)
                        result.failed.append(raw_path)
                        with _manifest_lock:
                            mark_failed(root, raw_path)
                    console.print(
                        f"  [yellow]lint-gate ✗[/yellow] {issue.path}: "
                        f"{issue.message}"
                    )
                else:
                    console.print(
                        f"  [dim]lint-gate ⚠[/dim] {issue.path}: "
                        f"{issue.message}"
                    )
            if demoted:
                console.print(
                    f"[yellow]{len(demoted)} file(s) demoted to failed "
                    f"by lint gate[/yellow]"
                )

    # Note: consolidation now runs per-batch inside the executor loop above,
    # not once at end-of-pass. See _run_consolidate.

    # ── Prune deleted sources ────────────────────────────────────
    if removed:
        try:
            agent_cmd, agent_args = detect_agent(cfg.compile)
        except AgentNotFoundError:
            pass
        else:
            prune_items = [(rm.raw_path, rm.summary_slug) for rm in removed]
            prune_prompt = build_prune_prompt(prune_items)
            console.print(
                f"[bold]Pruning {len(removed)} removed source(s) "
                f"via {agent_cmd}...[/bold]"
            )
            ok, _ = _run_agent(
                [agent_cmd, *agent_args, prune_prompt],
                cwd=root,
                timeout=_COMPILE_TIMEOUT,
                label="prune",
            )
            # Only drop a manifest entry if the Agent actually removed (or
            # deprecated) the corresponding summary file. Otherwise we'd
            # forget the raw_path and re-issue the same prune prompt forever.
            summaries_dir = root / "wiki" / "summaries"
            manifest = load_manifest(root)
            prune_skipped: list[str] = []
            for rm in removed:
                if rm.raw_path not in manifest:
                    continue
                summary_path = summaries_dir / f"{rm.summary_slug}.md"
                agent_handled = not summary_path.exists()
                if not agent_handled:
                    # Accept "deprecated" as a valid prune outcome too.
                    try:
                        fm = read_frontmatter(summary_path)
                        agent_handled = bool(fm.get("deprecated"))
                    except OSError:
                        agent_handled = False
                if agent_handled:
                    del manifest[rm.raw_path]
                    result.pruned.append(rm.raw_path)
                else:
                    prune_skipped.append(rm.raw_path)
            save_manifest(root, manifest)
            if prune_skipped:
                console.print(
                    f"[yellow]⚠ {len(prune_skipped)} prune target(s) still "
                    f"present in wiki/summaries — will retry next run.[/yellow]"
                )
                for p in prune_skipped:
                    console.print(f"    [yellow]·[/yellow] {p}")

    # ── Summary ──────────────────────────────────────────────────
    console.print()
    if result.compiled:
        console.print(f"[green]✓ {len(result.compiled)} file(s) compiled[/green]")
    if result.failed:
        console.print(f"[yellow]✗ {len(result.failed)} file(s) failed[/yellow]")
    if result.pruned:
        console.print(f"[cyan]⊘ {len(result.pruned)} source(s) pruned[/cyan]")

    if auto_commit:
        _auto_git_commit(root, result)

    return result


# ─── File watcher with retry ──────────────────────────────────────

def start_watcher(root: Path, *, dry_run: bool = False):
    """Start a non-blocking file watcher on raw/. Returns the Observer instance."""
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    cfg = load_config(root)
    debounce = cfg.compile.debounce_seconds
    raw_dir = root / "raw"

    if not raw_dir.is_dir():
        console.print("[red]raw/ directory not found.[/red]")
        return None

    console.print(
        f"[bold]Watching {raw_dir} for changes "
        f"(debounce: {debounce}s)...[/bold]"
    )

    timer: threading.Timer | None = None
    retry_timer: threading.Timer | None = None
    retry_count = 0
    lock = threading.Lock()

    def _schedule_retry() -> None:
        nonlocal retry_timer, retry_count
        delay = _RETRY_BACKOFF[min(retry_count, len(_RETRY_BACKOFF) - 1)]
        retry_count += 1
        console.print(
            f"[dim][{time.strftime('%H:%M:%S')}] "
            f"Retry #{retry_count} scheduled in {delay}s...[/dim]"
        )
        retry_timer = threading.Timer(delay, _retry_trigger)
        retry_timer.daemon = True
        retry_timer.start()

    def _cancel_retry() -> None:
        nonlocal retry_timer
        if retry_timer is not None:
            retry_timer.cancel()
            retry_timer = None

    def _compile_and_maybe_retry(reason: str) -> None:
        nonlocal retry_count
        console.print(
            f"\n[dim][{time.strftime('%H:%M:%S')}] {reason}[/dim]"
        )
        result = compile_once(
            root, dry_run=dry_run, auto_commit=cfg.compile.auto_commit,
        )
        if result.failed and not result.aborted:
            # Non-fatal failures → retry with backoff
            with lock:
                _schedule_retry()
        else:
            with lock:
                retry_count = 0
                _cancel_retry()
            if result.aborted:
                console.print(
                    f"[dim][{time.strftime('%H:%M:%S')}] "
                    f"Auto-retry disabled until next file change[/dim]"
                )
        console.print(
            f"[dim][{time.strftime('%H:%M:%S')}] Watching...[/dim]\n"
        )

    def _trigger() -> None:
        """Called after debounce when raw/ files change."""
        nonlocal timer, retry_count
        with lock:
            timer = None
            retry_count = 0
            _cancel_retry()
        _compile_and_maybe_retry("Change detected, compiling...")

    def _retry_trigger() -> None:
        """Called by the retry timer for non-fatal failures."""
        with lock:
            if retry_timer is None:
                return
        _compile_and_maybe_retry(
            f"Retrying failed files (attempt #{retry_count + 1})..."
        )

    class _Handler(FileSystemEventHandler):
        def on_any_event(self, event) -> None:  # type: ignore[override]
            if event.is_directory:
                return
            nonlocal timer
            with lock:
                if timer is not None:
                    timer.cancel()
                _cancel_retry()
                timer = threading.Timer(debounce, _trigger)
                timer.start()

    observer = Observer()
    observer.schedule(_Handler(), str(raw_dir), recursive=True)
    observer.daemon = True
    observer.start()

    # Startup check: compile any pending/failed files from previous runs.
    pending = get_pending(root)
    if pending:
        startup = threading.Timer(
            2.0,
            _compile_and_maybe_retry,
            args=[
                f"Startup: {len(pending)} pending/failed file(s) found, "
                f"compiling...",
            ],
        )
        startup.daemon = True
        startup.start()

    return observer


def watch(root: Path, *, dry_run: bool = False) -> None:
    """Watch raw/ for changes and auto-compile on file events (blocking)."""
    observer = start_watcher(root, dry_run=dry_run)
    if observer is None:
        return

    console.print("Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopping watcher...[/dim]")
        observer.stop()
    observer.join()
