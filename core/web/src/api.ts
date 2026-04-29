import type {
  TreeNode,
  DocResponse,
  StatusInfo,
  QueryStreamEvent,
  QueryStepKind,
} from "./types";

const BASE = "";

export async function fetchTree(): Promise<TreeNode[]> {
  const res = await fetch(`${BASE}/tree`);
  if (!res.ok) throw new Error(`GET /tree failed: ${res.status}`);
  return res.json();
}

export async function fetchDoc(path: string): Promise<DocResponse> {
  const res = await fetch(
    `${BASE}/doc?path=${encodeURIComponent(path)}`
  );
  if (!res.ok) throw new Error(`GET /doc failed: ${res.status}`);
  return res.json();
}

/**
 * Open an SSE stream for /query. Returns a cancel function.
 *
 * Backend emits four event types: `results` (initial top-K from local
 * search), `step` (searching/reading/synthesizing progress), `done`
 * (final answer + sources), `error` (terminal failure). EventSource
 * surfaces both server-sent error events and transport errors on the
 * same handler — distinguished by whether `.data` is present.
 */
export function streamQuery(
  query: string,
  onEvent: (ev: QueryStreamEvent) => void,
): () => void {
  const es = new EventSource(`${BASE}/query?q=${encodeURIComponent(query)}`);

  es.addEventListener("results", (e) => {
    const data = JSON.parse((e as MessageEvent).data);
    onEvent({ kind: "results", results: data.results ?? [] });
  });

  es.addEventListener("step", (e) => {
    const data = JSON.parse((e as MessageEvent).data);
    onEvent({
      kind: "step",
      step: data.kind as QueryStepKind,
      detail: data.detail ?? "",
    });
  });

  es.addEventListener("done", (e) => {
    const data = JSON.parse((e as MessageEvent).data);
    onEvent({
      kind: "done",
      answer: data.answer ?? "",
      sources: data.sources ?? [],
    });
    es.close();
  });

  es.addEventListener("error", (e) => {
    const me = e as MessageEvent;
    if (me.data) {
      // Server-sent error frame.
      try {
        const data = JSON.parse(me.data);
        onEvent({ kind: "error", message: data.message ?? "Unknown error" });
      } catch {
        onEvent({ kind: "error", message: "Stream parse failed" });
      }
    } else {
      // Transport-level error (connection dropped). EventSource auto-reconnects
      // by default; close it so we don't keep retrying after a fatal failure.
      onEvent({ kind: "error", message: "Connection lost" });
    }
    es.close();
  });

  return () => es.close();
}

export async function fetchStatus(): Promise<StatusInfo> {
  const res = await fetch(`${BASE}/status`);
  if (!res.ok) throw new Error(`GET /status failed: ${res.status}`);
  return res.json();
}

export async function crystallize(
  question: string,
  answer: string,
  sources: string[],
): Promise<{ path: string; slug: string }> {
  const res = await fetch(`${BASE}/crystallize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, answer, sources }),
  });
  if (!res.ok) throw new Error(`POST /crystallize failed: ${res.status}`);
  return res.json();
}
