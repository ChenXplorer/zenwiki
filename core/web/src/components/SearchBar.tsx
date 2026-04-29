import { useEffect, useRef, useState } from "react";
import { streamQuery, crystallize } from "../api";
import type { QueryStepKind, SearchResult } from "../types";

interface Props {
  onSelect: (path: string) => void;
}

interface ProgressStep {
  kind: QueryStepKind;
  detail: string;
}

const STEP_LABEL: Record<QueryStepKind, string> = {
  searching: "🔍 Searching",
  reading: "📄 Reading",
  synthesizing: "✍️ Synthesizing",
};

function toDocPath(path: string): string {
  return path.startsWith("wiki/") ? path : `wiki/${path}`;
}

function shortenDetail(kind: QueryStepKind, detail: string): string {
  if (!detail) return "";
  if (kind === "reading") {
    // Read tool reports absolute paths; trim to wiki-relative for display.
    const idx = detail.lastIndexOf("/wiki/");
    if (idx >= 0) return detail.slice(idx + 1);
    return detail;
  }
  // searching: shorten the bash command to just the query argument.
  const m = detail.match(/zenwiki search\s+"([^"]+)"/);
  if (m) return m[1];
  return detail.length > 80 ? detail.slice(0, 77) + "..." : detail;
}

export default function SearchBar({ onSelect }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  const [answerSources, setAnswerSources] = useState<string[]>([]);
  const [answeredQuestion, setAnsweredQuestion] = useState<string>("");
  const [asking, setAsking] = useState(false);
  const [crystallizing, setCrystallizing] = useState(false);
  const [crystallizedPath, setCrystallizedPath] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressStep[]>([]);
  const cancelRef = useRef<(() => void) | null>(null);

  // If the component unmounts mid-stream, close the EventSource so it
  // doesn't keep firing handlers on dead state setters.
  useEffect(() => () => cancelRef.current?.(), []);

  const doAsk = () => {
    const q = query.trim();
    if (!q) return;

    // Cancel any in-flight stream from a previous click.
    cancelRef.current?.();

    setAsking(true);
    setAnswer(null);
    setAnswerSources([]);
    setAnsweredQuestion("");
    setCrystallizedPath(null);
    setMessage(null);
    setResults([]);
    setProgress([]);

    cancelRef.current = streamQuery(q, (ev) => {
      if (ev.kind === "results") {
        setResults(ev.results);
      } else if (ev.kind === "step") {
        setProgress((p) => [...p, { kind: ev.step, detail: ev.detail }]);
      } else if (ev.kind === "done") {
        setAnswer(ev.answer || null);
        setAnswerSources(ev.sources);
        setAnsweredQuestion(q);
        setAsking(false);
        if (!ev.answer) {
          setMessage("No answer returned");
        }
      } else {
        // error
        setMessage(ev.message);
        setAsking(false);
      }
    });
  };

  const doCrystallize = async () => {
    if (!answer || !answeredQuestion) return;
    setCrystallizing(true);
    try {
      const data = await crystallize(answeredQuestion, answer, answerSources);
      setCrystallizedPath(data.path);
    } catch (err) {
      setMessage(`Crystallize failed: ${(err as Error).message}`);
    } finally {
      setCrystallizing(false);
    }
  };

  return (
    <div className="search-bar">
      <div className="search-input-row">
        <input
          type="text"
          placeholder="Ask a question about the wiki..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") doAsk();
          }}
        />
        <button onClick={doAsk} disabled={asking} className="ask-btn">
          {asking ? "Thinking..." : "Ask AI"}
        </button>
      </div>

      {asking && progress.length > 0 && !answer && (
        <div className="ai-progress">
          {progress.map((s, i) => (
            <div key={i} className="ai-progress-step">
              <span className="ai-progress-label">{STEP_LABEL[s.kind]}</span>
              {s.detail && (
                <span className="ai-progress-detail">{shortenDetail(s.kind, s.detail)}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {answer && (
        <div className="ai-answer">
          <div className="ai-answer-header">AI Answer</div>
          <div className="ai-answer-body">{answer}</div>
          {answerSources.length > 0 && (
            <div className="ai-answer-sources">
              Sources:{" "}
              {answerSources.map((s, i) => (
                <span key={s}>
                  {i > 0 && ", "}
                  <a
                    href="#"
                    onClick={(e) => {
                      e.preventDefault();
                      onSelect(toDocPath(s));
                    }}
                  >
                    {s}
                  </a>
                </span>
              ))}
            </div>
          )}
          <div className="ai-answer-actions">
            {crystallizedPath ? (
              <span className="crystallize-success">
                ✓ Saved to{" "}
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    onSelect(crystallizedPath);
                  }}
                >
                  {crystallizedPath}
                </a>
              </span>
            ) : (
              <button
                className="crystallize-btn"
                onClick={doCrystallize}
                disabled={crystallizing}
              >
                {crystallizing ? "Saving..." : "💎 Crystallize to Wiki"}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="search-results">
        {message && (
          <div
            style={{
              color: "var(--text-muted)",
              padding: "6px 12px",
              fontSize: 13,
            }}
          >
            {message}
          </div>
        )}
        {results.map((r) => (
          <div
            key={r.path}
            className="search-result"
            onClick={() => onSelect(toDocPath(r.path))}
          >
            <span className="path">{r.path}</span>
            {r.snippet && <span className="snippet">{r.snippet}</span>}
            <span className="score">{r.score.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
