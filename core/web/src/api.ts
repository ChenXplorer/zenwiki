import type { TreeNode, DocResponse, StatusInfo, QueryResponse } from "./types";

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

export async function fetchQuery(query: string): Promise<QueryResponse> {
  const res = await fetch(
    `${BASE}/query?q=${encodeURIComponent(query)}`
  );
  if (!res.ok) throw new Error(`GET /query failed: ${res.status}`);
  return res.json();
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
