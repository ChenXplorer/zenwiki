export interface TreeNode {
  name: string;
  path?: string;
  type: "file" | "dir";
  children?: TreeNode[];
}

export interface DocResponse {
  path: string;
  frontmatter: Record<string, unknown>;
  html: string;
}

export interface SearchResult {
  path: string;
  score: number;
  snippet: string;
}

export interface StatusInfo {
  wiki_pages: Record<string, number>;
  total_wiki: number;
  raw_sources: Record<string, number>;
  total_raw: number;
}

export type QueryStepKind = "searching" | "reading" | "synthesizing";

export type QueryStreamEvent =
  | { kind: "results"; results: SearchResult[] }
  | { kind: "step"; step: QueryStepKind; detail: string }
  | { kind: "done"; answer: string; sources: string[] }
  | { kind: "error"; message: string };
