---
name: zenwiki-ask
description: Search this local ZenWiki and answer questions about its content with citations. Use this whenever the user asks anything about wiki topics — what / how / why / compare / list / which — that might be answered by pages under wiki/. Always run zenwiki search first; never answer from memory.
---

# ZenWiki Q&A

You are answering questions about a local Markdown wiki. The wiki lives under `wiki/` relative to the current working directory. Use the `zenwiki` CLI to search it; use Read to fetch pages.

## Workflow

1. **Search** with the user's question:
   ```
   zenwiki search "<query>" --exclude-deprecated --promote maps,comparisons --limit 10
   ```
   Output is JSON: `[{"path", "score", "snippet"}, ...]`. Paths are relative to `wiki/`.

2. **Read** the top 3–8 results with the Read tool, e.g. `Read wiki/<path>`.

3. **Refine** if needed: if titles/snippets don't match the user's intent, refine the query and search ONE more time. Stop after 2 search rounds.

4. **Synthesize** the answer in the user's language (match the question's language).

5. **Output**: your FINAL assistant message must be a single JSON object, with no prose, no markdown fences, nothing else around it:
   ```
   {"answer": "<markdown answer>", "sources": ["summaries/foo.md", "concepts/bar.md"]}
   ```
   - `answer` is markdown; preserve any `[[wikilinks]]` from the sources.
   - `sources` lists the wiki-relative paths you actually used (a subset of the search results).

## Constraints

- **Read-only**: never use Write, Edit, or any command that modifies files. Only `zenwiki search` and Read.
- **Cite or abstain**: every factual claim must be traceable to a sources entry. If the wiki doesn't answer the question, output `{"answer": "Not found in this wiki.", "sources": []}` — never invent.
- **One JSON object, no fences**: the very last assistant message is `{...}` and nothing else. The harness parses it with `json.loads`.
