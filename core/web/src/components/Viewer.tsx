import { useEffect, useState, useCallback } from "react";
import { fetchDoc, fetchStatus } from "../api";
import type { DocResponse, StatusInfo } from "../types";

type ViewMode =
  | { kind: "empty" }
  | { kind: "doc"; path: string }
  | { kind: "status" }
  | { kind: "lint" }
  | { kind: "rebuild" };

interface Props {
  mode: ViewMode;
  onNavigate: (path: string) => void;
}

export default function Viewer({ mode, onNavigate }: Props) {
  if (mode.kind === "empty") return <EmptyState />;
  if (mode.kind === "doc")
    return <DocView path={mode.path} onNavigate={onNavigate} />;
  if (mode.kind === "status") return <StatusView />;
  if (mode.kind === "lint") return <LintView />;
  return <RebuildView />;
}

function EmptyState() {
  return (
    <div className="viewer-empty">
      <div className="icon">&#x1F4DA;</div>
      <div>Select a document from the sidebar</div>
      <div style={{ fontSize: 13 }}>or use the search bar below</div>
    </div>
  );
}

function DocView({
  path,
  onNavigate,
}: {
  path: string;
  onNavigate: (p: string) => void;
}) {
  const [doc, setDoc] = useState<DocResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchDoc(path)
      .then((d) => {
        setDoc(d);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [path]);

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement;
      const anchor = target.closest("a.wikilink") as HTMLAnchorElement | null;
      if (anchor) {
        e.preventDefault();
        const path = anchor.getAttribute("data-path");
        if (path) {
          onNavigate(path);
        }
      }
    },
    [onNavigate]
  );

  if (loading)
    return (
      <div style={{ color: "var(--text-muted)", padding: 20 }}>Loading...</div>
    );
  if (error) return <div style={{ color: "var(--red)", padding: 20 }}>{error}</div>;
  if (!doc) return null;

  const fm = doc.frontmatter ?? {};
  const title =
    (fm.title as string) || path.split("/").pop()?.replace(".md", "") || path;

  const tags: string[] = [];
  if (Array.isArray(fm.tags)) tags.push(...(fm.tags as string[]));
  const metaEntries: string[] = [];
  if (fm.source_path) metaEntries.push(`source: ${fm.source_path}`);
  if (fm.date_added) metaEntries.push(String(fm.date_added));
  if (fm.date_updated) metaEntries.push(String(fm.date_updated));
  if (fm.maturity) metaEntries.push(`maturity: ${fm.maturity}`);
  if (fm.category) metaEntries.push(String(fm.category));
  if (fm.importance) metaEntries.push(`importance: ${fm.importance}`);

  return (
    <>
      <div className="doc-title">{title}</div>
      <div className="doc-meta">
        {tags.map((t) => (
          <span key={t} className="tag">
            {t}
          </span>
        ))}
        {metaEntries.map((m) => (
          <span key={m} className="tag">
            {m}
          </span>
        ))}
      </div>
      <div
        className="doc-body"
        dangerouslySetInnerHTML={{ __html: doc.html }}
        onClick={handleClick}
      />
    </>
  );
}

function StatusView() {
  const [info, setInfo] = useState<StatusInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStatus()
      .then((d) => {
        setInfo(d);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading)
    return (
      <div style={{ color: "var(--text-muted)", padding: 20 }}>Loading...</div>
    );
  if (!info) return <div style={{ color: "var(--red)", padding: 20 }}>Failed</div>;

  return (
    <div className="status-view">
      <div className="doc-title">Wiki Status</div>
      <h2>Wiki Pages</h2>
      <table>
        <thead>
          <tr>
            <th>Section</th>
            <th>Count</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(info.wiki_pages).map(([k, v]) => (
            <tr key={k}>
              <td>wiki/{k}/</td>
              <td>{v}</td>
            </tr>
          ))}
          <tr>
            <th>Total</th>
            <th>{info.total_wiki}</th>
          </tr>
        </tbody>
      </table>

      <h2>Raw Sources</h2>
      <table>
        <thead>
          <tr>
            <th>Section</th>
            <th>Count</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(info.raw_sources).map(([k, v]) => (
            <tr key={k}>
              <td>raw/{k}/</td>
              <td>{v}</td>
            </tr>
          ))}
          <tr>
            <th>Total</th>
            <th>{info.total_raw}</th>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function LintView() {
  return (
    <>
      <div className="doc-title">Lint</div>
      <div className="doc-body">
        <p style={{ color: "var(--text-muted)" }}>
          Run <code>zenwiki lint</code> from the CLI for a full health check.
        </p>
        <p style={{ color: "var(--text-muted)" }}>
          Checks: broken links, missing frontmatter, orphan pages, heading
          structure, empty sections.
        </p>
      </div>
    </>
  );
}

function RebuildView() {
  return (
    <>
      <div className="doc-title">Rebuild Index</div>
      <div className="doc-body">
        <p style={{ color: "var(--text-muted)" }}>
          Run <code>zenwiki rebuild-index</code> from the CLI to regenerate
          wiki/index.md.
        </p>
      </div>
    </>
  );
}

export type { ViewMode };
