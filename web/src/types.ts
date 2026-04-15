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

export interface QueryResponse {
  answer: string;
  sources: string[];
  results: SearchResult[];
  error?: string;
}
