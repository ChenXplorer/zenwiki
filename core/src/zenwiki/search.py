"""Full-text search engine using SQLite FTS5 + jieba Chinese tokenization,
with optional qmd vector search for hybrid (BM25 + semantic) retrieval."""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

import jieba

from .markdown import parse_frontmatter, strip_frontmatter

jieba.setLogLevel(20)
log = logging.getLogger(__name__)


@dataclass
class SearchResult:
    path: str
    score: float
    snippet: str


_STOP_WORDS = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 "
    "没有 看 好 自己 这 他 她 它 吗 呢 吧 啊 呀 嘛 哦 哈 么 什么 怎么 如何 "
    "为什么 哪里 哪个 谁 多少 几 这个 那个 这些 那些 什么样 怎样 "
    "the a an is are was were be been being have has had do does did "
    "will would shall should can could may might must and or but if then "
    "than that this these those of in on at to for with from by as".split()
)

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")


def _tokenize(text: str) -> list[str]:
    """Tokenize text with jieba, filtering stop words and short tokens."""
    text = _WIKILINK_RE.sub(lambda m: m.group(2) or m.group(1), text)
    tokens = jieba.cut_for_search(text)
    return [t.strip().lower() for t in tokens if t.strip() and t.strip().lower() not in _STOP_WORDS and len(t.strip()) > 0]


def _make_snippet(text: str, max_len: int = 300) -> str:
    """Extract first max_len chars as snippet."""
    clean = text.replace("\n", " ").strip()
    if len(clean) > max_len:
        return clean[:max_len] + "..."
    return clean


_QMD_VSEARCH_TIMEOUT = 30
_QMD_COLLECTION_NAME = "wiki"
_RRF_K = 60


def _find_qmd(qmd_path: str = "qmd") -> str | None:
    """Return absolute path to the qmd binary, or None if not found."""
    return shutil.which(qmd_path)


def _qmd_collection_exists(qmd: str, cwd: Path) -> bool:
    """Check whether the 'wiki' collection already exists in qmd."""
    try:
        r = subprocess.run(
            [qmd, "collection", "show", _QMD_COLLECTION_NAME],
            capture_output=True, text=True, timeout=10, cwd=str(cwd),
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _qmd_setup_and_embed(qmd: str, wiki_dir: Path) -> dict:
    """Ensure the wiki collection exists in qmd, update index, and generate embeddings."""
    project_root = wiki_dir.parent
    cwd = str(project_root)

    if not _qmd_collection_exists(qmd, project_root):
        subprocess.run(
            [qmd, "collection", "add", _QMD_COLLECTION_NAME, str(wiki_dir), "--pattern", "**/*.md"],
            capture_output=True, text=True, timeout=15, cwd=cwd,
        )

    r_update = subprocess.run(
        [qmd, "update"],
        capture_output=True, text=True, timeout=120, cwd=cwd,
    )

    r_embed = subprocess.run(
        [qmd, "embed"],
        capture_output=True, text=True, timeout=300, cwd=cwd,
    )

    return {
        "qmd_update": "ok" if r_update.returncode == 0 else "error",
        "qmd_embed": "ok" if r_embed.returncode == 0 else "error",
    }


def _qmd_update_only(qmd: str, wiki_dir: Path) -> dict:
    """Run incremental qmd update + embed (only processes changed files)."""
    cwd = str(wiki_dir.parent)
    r_update = subprocess.run(
        [qmd, "update"],
        capture_output=True, text=True, timeout=120, cwd=cwd,
    )
    r_embed = subprocess.run(
        [qmd, "embed"],
        capture_output=True, text=True, timeout=300, cwd=cwd,
    )
    return {
        "qmd_update": "ok" if r_update.returncode == 0 else "error",
        "qmd_embed": "ok" if r_embed.returncode == 0 else "error",
    }


def _rrf_merge(
    bm25_results: list[SearchResult],
    vec_results: list[SearchResult],
    limit: int = 10,
) -> list[SearchResult]:
    """Merge two ranked lists using Reciprocal Rank Fusion (k=60)."""
    scores: dict[str, float] = {}
    best_snippet: dict[str, str] = {}

    for rank, r in enumerate(bm25_results):
        scores[r.path] = scores.get(r.path, 0.0) + 1.0 / (_RRF_K + rank + 1)
        if r.path not in best_snippet:
            best_snippet[r.path] = r.snippet

    for rank, r in enumerate(vec_results):
        scores[r.path] = scores.get(r.path, 0.0) + 1.0 / (_RRF_K + rank + 1)
        if r.path not in best_snippet:
            best_snippet[r.path] = r.snippet

    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [
        SearchResult(path=path, score=round(score, 4), snippet=best_snippet[path])
        for path, score in merged
    ]


class WikiIndex:
    """SQLite FTS5 search index with jieba Chinese tokenization
    and optional qmd vector search for hybrid retrieval."""

    def __init__(
        self,
        wiki_dir: Path,
        db_path: Path | None = None,
    ):
        self._wiki_dir = wiki_dir.resolve()
        if db_path is None:
            db_dir = self._wiki_dir.parent / ".zenwiki"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = db_dir / "search.db"
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        # Hybrid (BM25 + qmd vector) when qmd is on PATH, BM25-only otherwise.
        # No user-visible knob: we just use whatever is available.
        self._qmd: str | None = _find_qmd()
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self._db_path), check_same_thread=False,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS wiki_meta (
                path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                snippet TEXT NOT NULL DEFAULT ''
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
                path,
                title,
                tokens,
                tokenize='unicode61'
            );
        """)
        conn.commit()

    # Frontmatter fields that declare what a page is ABOUT. Maps list the
    # concepts/entities they cover; comparisons list subjects; concepts list
    # related concepts; summaries list key_sources. Without folding these
    # into the FTS index, a map titled "FICC AI Research Landscape" tagged
    # [ficc, ai投研] won't surface for the query "FICC AI 投研" because the
    # body is just wikilinks. Including them fixes cross-lingual titles and
    # raises map/comparison recall without per-path boosting.
    _SEMANTIC_FRONTMATTER_FIELDS = (
        "tags",
        "aliases",
        "key_concepts",
        "key_entities",
        "subjects",
        "key_sources",
        "related_concepts",
        "category",
    )

    def _index_file(self, rel_path: str, full_path: Path, conn: sqlite3.Connection) -> None:
        text = full_path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        body = strip_frontmatter(text)

        title = fm.get("title", "")

        # Flatten semantic frontmatter fields into a space-separated string
        # that joins the raw title. This text is fed to BOTH the title column
        # (5x BM25 weight) and the tokens column (full-text).
        semantic_terms: list[str] = []
        for key in self._SEMANTIC_FRONTMATTER_FIELDS:
            val = fm.get(key)
            if isinstance(val, list):
                semantic_terms.extend(str(v) for v in val if v)
            elif isinstance(val, str) and val:
                semantic_terms.append(val)

        title_text = " ".join([title] + semantic_terms).strip() if semantic_terms else title
        indexable = f"{title_text}\n{body}"
        tokens = _tokenize(indexable)
        token_str = " ".join(tokens)

        title_tokens = " ".join(_tokenize(title_text)) if title_text else ""
        snippet = _make_snippet(body)
        mtime = full_path.stat().st_mtime

        conn.execute("DELETE FROM wiki_fts WHERE path = ?", (rel_path,))
        conn.execute("DELETE FROM wiki_meta WHERE path = ?", (rel_path,))

        conn.execute(
            "INSERT INTO wiki_fts (path, title, tokens) VALUES (?, ?, ?)",
            (rel_path, title_tokens, token_str),
        )
        conn.execute(
            "INSERT INTO wiki_meta (path, mtime, title, snippet) VALUES (?, ?, ?, ?)",
            (rel_path, mtime, title, snippet),
        )

    def rebuild(self) -> dict[str, str | int]:
        """Full rebuild: drop and re-index all .md files, then update qmd embeddings."""
        conn = self._get_conn()
        conn.execute("DELETE FROM wiki_fts")
        conn.execute("DELETE FROM wiki_meta")

        count = 0
        for md_file in sorted(self._wiki_dir.rglob("*.md")):
            if md_file.name.startswith("."):
                continue
            rel = str(md_file.relative_to(self._wiki_dir))
            self._index_file(rel, md_file, conn)
            count += 1

        conn.commit()

        result: dict[str, str | int] = {"status": "ok", "indexed": count}

        if self._qmd:
            try:
                qmd_result = _qmd_setup_and_embed(self._qmd, self._wiki_dir)
                result.update(qmd_result)
            except Exception as exc:
                log.warning("qmd setup/embed failed: %s", exc)
                result["qmd_error"] = str(exc)

        return result

    def refresh(self) -> dict[str, str | int]:
        """Incremental update: only re-index new/changed files, remove deleted.
        Also triggers qmd update+embed for vector index."""
        conn = self._get_conn()

        existing: dict[str, float] = {}
        for row in conn.execute("SELECT path, mtime FROM wiki_meta"):
            existing[row[0]] = row[1]

        current_files: set[str] = set()
        updated = 0

        for md_file in sorted(self._wiki_dir.rglob("*.md")):
            if md_file.name.startswith("."):
                continue
            rel = str(md_file.relative_to(self._wiki_dir))
            current_files.add(rel)
            mtime = md_file.stat().st_mtime

            if rel not in existing or existing[rel] < mtime:
                self._index_file(rel, md_file, conn)
                updated += 1

        deleted = set(existing.keys()) - current_files
        for rel in deleted:
            conn.execute("DELETE FROM wiki_fts WHERE path = ?", (rel,))
            conn.execute("DELETE FROM wiki_meta WHERE path = ?", (rel,))

        conn.commit()

        result: dict[str, str | int] = {"status": "ok", "updated": updated, "deleted": len(deleted)}

        if self._qmd and updated > 0:
            try:
                qmd_result = _qmd_update_only(self._qmd, self._wiki_dir)
                result.update(qmd_result)
            except Exception as exc:
                log.warning("qmd update failed: %s", exc)
                result["qmd_error"] = str(exc)

        return result

    def search(
        self,
        query: str,
        limit: int = 10,
        path_prefix: str | None = None,
    ) -> list[SearchResult]:
        """Search the wiki, returning ranked results.

        `path_prefix` restricts to paths starting with the given prefix
        (e.g. "maps/"). Used by hybrid_search to guarantee map/comparison
        representation.
        """
        tokens = _tokenize(query)
        if not tokens:
            return []

        fts_query = " OR ".join(f'"{t}"' for t in tokens)

        sql = """
            SELECT f.path, bm25(wiki_fts, 5.0, 3.0, 1.0) AS rank,
                   m.snippet
            FROM wiki_fts f
            JOIN wiki_meta m ON f.path = m.path
            WHERE wiki_fts MATCH ?
        """
        params: list[object] = [fts_query]
        if path_prefix:
            sql += " AND f.path LIKE ?"
            params.append(f"{path_prefix}%")
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        conn = self._get_conn()
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []

        results = []
        for path, rank, snippet in rows:
            score = round(max(0.0, min(1.0, 1.0 + rank / 10.0)), 2)
            results.append(SearchResult(path=path, score=score, snippet=snippet))
        return results

    def vsearch(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Vector similarity search via qmd vsearch subprocess."""
        if not self._qmd:
            return []

        try:
            r = subprocess.run(
                [
                    self._qmd, "vsearch", query,
                    "-c", _QMD_COLLECTION_NAME,
                    "-n", str(limit),
                    "--json",
                ],
                capture_output=True, text=True,
                timeout=_QMD_VSEARCH_TIMEOUT,
                cwd=str(self._wiki_dir.parent),
            )
            if r.returncode != 0:
                log.warning("qmd vsearch failed (rc=%d): %s", r.returncode, r.stderr[:200])
                return []

            items = json.loads(r.stdout)
            results: list[SearchResult] = []
            for item in items[:limit]:
                file_uri: str = item.get("file", "")
                rel_path = file_uri.removeprefix(f"qmd://{_QMD_COLLECTION_NAME}/")
                score = item.get("score", 0.0)
                snippet = item.get("snippet", "").replace("\n", " ")[:300]
                results.append(SearchResult(path=rel_path, score=round(score, 2), snippet=snippet))
            return results
        except subprocess.TimeoutExpired:
            log.warning("qmd vsearch timed out after %ds", _QMD_VSEARCH_TIMEOUT)
            return []
        except (json.JSONDecodeError, FileNotFoundError, KeyError) as exc:
            log.warning("qmd vsearch error: %s", exc)
            return []

    def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        promote_prefixes: tuple[str, ...] | None = None,
        exclude_deprecated: bool = False,
    ) -> list[SearchResult]:
        """Hybrid search: BM25 keyword + vector semantic, merged via RRF.
        Falls back to BM25-only if qmd is unavailable or fails.

        After the merge, reserves at most one slot per prefix in
        `promote_prefixes` (default: maps/ and comparisons/) when such a
        page matches the query. Map and comparison pages are "directory-
        style" (short body, long frontmatter) and consistently under-rank
        on raw BM25, yet they're the highest-value sources for cross-
        cutting questions. Pass an empty tuple to disable promotion.

        `exclude_deprecated=True` drops pages whose frontmatter has
        `deprecated: true`. The check happens after promotion, so a
        promoted-then-stripped slot may shrink the result list below
        `limit` — acceptable since promoted candidates are rarely
        deprecated.
        """
        prefixes = self._PROMOTE_PREFIXES if promote_prefixes is None else promote_prefixes

        bm25_results = self.search(query, limit=limit * 2)

        if not self._qmd:
            base = bm25_results[:limit]
        else:
            vec_results = self.vsearch(query, limit=limit * 2)
            if not vec_results:
                base = bm25_results[:limit]
            else:
                base = _rrf_merge(bm25_results, vec_results, limit=limit)

        promoted = self._promote_type_pages(base, query, limit, prefixes)

        if exclude_deprecated:
            promoted = [r for r in promoted if not self._is_deprecated(r.path)]

        return promoted

    # Default page prefixes that earn a guaranteed slot in hybrid_search
    # results when they match the query at all. Order matters: the first
    # promoted type displaces the last non-privileged slot, the second
    # displaces the next-last, and so on.
    _PROMOTE_PREFIXES = ("maps/", "comparisons/")

    def _is_deprecated(self, rel_path: str) -> bool:
        p = self._wiki_dir / rel_path
        if not p.is_file():
            return False
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return False
        return parse_frontmatter(text).get("deprecated") is True

    def _promote_type_pages(
        self,
        base: list[SearchResult],
        query: str,
        limit: int,
        prefixes: tuple[str, ...],
    ) -> list[SearchResult]:
        """If `base` lacks any page under one of `prefixes`, and such a
        page matches the query, swap it in for the lowest-ranked non-
        privileged slot. Idempotent — already-present privileged pages
        are untouched. Empty `prefixes` is a no-op."""
        if not prefixes:
            return base[:limit]

        have_paths = {r.path for r in base}
        promoted = list(base)

        for prefix in prefixes:
            if any(p.startswith(prefix) for p in have_paths):
                continue
            top = self.search(query, limit=1, path_prefix=prefix)
            if not top:
                continue
            candidate = top[0]
            # Find the lowest-ranked slot NOT held by a privileged prefix,
            # walking from the bottom. This preserves higher-ranked normal
            # results and still caps total size at `limit`.
            for idx in range(len(promoted) - 1, -1, -1):
                if not any(
                    promoted[idx].path.startswith(p)
                    for p in prefixes
                ):
                    promoted[idx] = candidate
                    have_paths.add(candidate.path)
                    break
            else:
                # Base is shorter than limit or all slots privileged — append.
                if len(promoted) < limit:
                    promoted.append(candidate)
                    have_paths.add(candidate.path)

        return promoted[:limit]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
