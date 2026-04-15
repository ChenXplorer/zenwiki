import { useState } from "react";
import { fetchQuery, crystallize } from "../api";
import type { SearchResult } from "../types";

interface Props {
  onSelect: (path: string) => void;
}

function toDocPath(path: string): string {
  return path.startsWith("wiki/") ? path : `wiki/${path}`;
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

  const doAsk = async () => {
    const q = query.trim();
    if (!q) return;
    setAsking(true);
    setAnswer(null);
    setAnswerSources([]);
    setAnsweredQuestion("");
    setCrystallizedPath(null);
    setMessage("Thinking...");
    setResults([]);
    try {
      const data = await fetchQuery(q);
      setResults(data.results || []);
      if (data.answer) {
        setAnswer(data.answer);
        setAnswerSources(data.sources || []);
        setAnsweredQuestion(q);
        setMessage(null);
      } else if (data.error) {
        setMessage(data.error);
      } else {
        setMessage(data.results?.length ? null : "No results found");
      }
    } catch (err) {
      setMessage(`Error: ${(err as Error).message}`);
    } finally {
      setAsking(false);
    }
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
