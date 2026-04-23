# ZenWiki Schema

> This file defines the rules for AI agents working on this wiki.
> Agents (Claude Code, Codex CLI, etc.) read this file to understand
> how to ingest sources, write wiki pages, and maintain quality.

---

## Directory Structure

```
raw/                    # Source materials (READ-ONLY for agents)
├── papers/             #   PDF / academic papers
├── articles/           #   Markdown articles
├── notes/              #   Meeting notes / reading notes
└── docs/               #   Technical docs / PPT / Word

wiki/                   # Knowledge layer (agent-maintained)
├── index.md            #   Content catalog (update after every operation)
├── log.md              #   Operation log (append-only)
├── summaries/          #   Source summary pages
├── entities/           #   Entity pages (person / company / product / tool)
├── concepts/           #   Concept pages (theory / method / technology)
├── comparisons/        #   Comparison pages
├── maps/               #   Topic navigation / domain overview
└── outputs/            #   Generated outputs (query write-back)
```

---

## Page Types and Templates

### summaries/{slug}.md — Source deep-dive

```yaml
---
title: ""
source_path: ""           # path under raw/
tags: []
importance: 3             # 1-5
date_added: YYYY-MM-DD
---
```

Sections: `## Core Problem` / `## Key Ideas` / `## Technical Details` / `## Key Results` / `## Limitations` / `## Open Questions` / `## Related`

### entities/{slug}.md — Person / Company / Product / Tool

```yaml
---
title: ""
aliases: []
tags: []
category: ""              # person / company / product / tool
key_sources: []
date_updated: YYYY-MM-DD
---
```

Sections: `## Overview` / `## Key Facts` / `## Sources` / `## Related`

### concepts/{slug}.md — Theory / Framework / Method / Technology

```yaml
---
title: ""
aliases: []
tags: []
maturity: active          # stable / active / emerging / deprecated
key_sources: []
related_concepts: []
date_updated: YYYY-MM-DD
---
```

Sections: `## Definition` / `## Intuition` / `## Technical Details` / `## Variants & Comparisons` / `## Use Cases` / `## Known Limitations` / `## Open Questions` / `## Key Sources`

### comparisons/{slug}.md — Cross-source comparison

```yaml
---
title: ""
tags: []
subjects: []              # slugs of compared concepts/entities
sources: []
date_updated: YYYY-MM-DD
---
```

Sections: `## Background` / `## Dimensions` / `## Analysis` / `## Conclusion` / `## Sources`

### maps/{slug}.md — Topic navigation / domain overview

```yaml
---
title: ""
tags: []
key_concepts: []
key_entities: []
date_updated: YYYY-MM-DD
---
```

Sections: `## Overview` / `## Core Concepts` / `## Core Entities` / `## Timeline` / `## Open Questions`

### outputs/{slug}.md — Query write-back / generated analysis

```yaml
---
title: ""
tags: []
citations: []
date_added: YYYY-MM-DD
---
```

Body: free-form (from query answers).

---

## Cross-referencing Rules

- Use `[[slug]]` for all internal links (Obsidian-compatible wikilinks).
- When adding a forward link, update the target page with a backlink.
- Red links (links to non-existent pages) are fine — they signal future work.
- Naming: all-lowercase, hyphen-separated (e.g. `flash-attention`).

---

## Workflows

### /ingest — Add a new source to the wiki

> Core skill. All knowledge flows in through ingest. Read the source deeply,
> then compile it into structured wiki pages with full cross-references.

#### Step 1: Read and Understand the Source

1. Read the source file from `raw/` (PDF, Markdown, Word, etc.).
2. Identify: What is this document about? What are its core arguments? Who are the key actors?
3. Assess importance (1-5): 1=niche, 2=useful, 3=standard reference, 4=influential, 5=critical.

#### Step 2: Dedup Check — MANDATORY

Before creating ANY new page, run the dedup tool:

```bash
zenwiki find-similar "<source title>"
```

- If a summary for this source already exists → notify user, stop.
- If a highly similar source exists (score >= 0.85) → ask user whether to merge or create new.

#### Step 3: Write the Summary Page

Create `wiki/summaries/{slug}.md`. Generate slug:

```bash
zenwiki slug "<source title>"
```

**Content depth guidelines — this is the most important step:**

| Section | What to write | Depth |
|---------|---------------|-------|
| Core Problem | What question/need does this source address? | 2-3 sentences |
| Key Ideas | The core arguments, methods, or insights | 1 paragraph per key idea; preserve the author's reasoning chain |
| Technical Details | **Write everything that might be queried later.** Specific configurations, parameters, code snippets, API signatures, architecture diagrams described in text, step-by-step procedures, formulas, data formats. This section should be LONG. | As detailed as the source allows |
| Key Results | Concrete numbers, benchmarks, before/after comparisons, outcomes. Quote directly when possible. | Specific data points, not vague summaries |
| Limitations | What the source doesn't cover, acknowledged weaknesses, known caveats | Bullet list |
| Open Questions | Unanswered questions raised by this source — these drive future ingests | Bullet list |
| Related | `[[wikilinks]]` to all related concepts, entities, other summaries | Link list |

**Anti-patterns for summary writing:**
- ❌ One-paragraph overview that loses all detail — this defeats the purpose of the wiki
- ❌ Copying the source verbatim without restructuring — add structure and cross-references
- ❌ Skipping Technical Details because "it's too detailed" — detail IS the value
- ❌ Writing "see original document" instead of including the information

#### Step 4: Extract and Match Concepts — FIND first, CREATE as last resort

For each technical concept, method, or framework mentioned significantly in the source:

1. Run the dedup tool — **MANDATORY before creating any concept page**:
   ```bash
   zenwiki find-similar "<concept name>" --dir concepts
   ```

2. Branch on the result:

   **Branch A (score >= 0.85):** Same concept exists. Do NOT create a new page.
   - Read the existing concept page
   - Append this source to its `key_sources` list
   - If the source adds new detail, append to the relevant section (e.g. new use case → `## Use Cases`)
   - Add `[[concept-slug]]` to the summary's `## Related`

   **Branch B (score 0.40-0.85):** Similar but unclear. Read the existing concept page.
   - If it's the same idea with different wording → treat as Branch A
   - If it's genuinely different → treat as Branch C
   - **Default: merge (Branch A).** Over-merging is cheaper than wiki bloat.

   **Branch C (score < 0.40 or empty):** No match. Create `wiki/concepts/{slug}.md`:
   - Set `maturity: emerging`
   - Fill all sections with what this source provides
   - Set `key_sources: [summaries/<source-slug>]`
   - Be generous with `aliases` — list every name variant the source uses

**Hard limit:** At most 2 new concept pages per ingest (3 for importance=5). All other concepts must match existing pages. If you hit the limit, force-merge remaining candidates into the closest existing match.

#### Step 5: Extract and Match Entities

For each person, company, product, or tool mentioned significantly:

1. Run `zenwiki find-similar "<entity name>" --dir entities`
2. Same branching logic as Step 4 (Branch A/B/C)
3. **Hard limit:** At most 2 new entity pages per ingest.

#### Step 6: Cross-References

1. Add `[[wikilinks]]` from the summary to all related concepts and entities
2. **Bidirectional rule:** For every forward link you write, update the target page with a backlink:
   - summary links to concept → concept's `key_sources` gets the summary slug
   - summary links to entity → entity's `key_sources` gets the summary slug
   - concept links to concept → both get each other in `related_concepts`
3. **Comparison check (MANDATORY):** Read `wiki/index.md`. If two or more concepts from DIFFERENT sources address the same problem space (e.g. competing architectures, alternative approaches, overlapping workflows), create a `comparisons/` page. This does NOT count toward the concept/entity hard limit.
4. **Map check (MANDATORY):** Read `wiki/index.md`. If a tag or domain now has >= 5 related pages (summaries + concepts + entities combined), create or update a `maps/` page. This does NOT count toward the concept/entity hard limit.

#### Step 7: Finalize

```bash
zenwiki rebuild-index
zenwiki refresh
zenwiki log "ingest | added summaries/<slug> | new: <list> | updated: <list>"
```

#### Step 8: Self-check — MANDATORY

Review what you did:
- How many new pages created vs. existing pages updated?
- Did you run `find-similar` before every new page? If not, go back.
- Are all bidirectional links in place?
- Is Technical Details in the summary substantive (not a shallow overview)?

Report to the user: pages created, pages updated, open questions discovered.

---

### /query — Answer a question from the wiki

> Search the wiki, read relevant pages, synthesize an answer. Good answers
> can be crystallized back into the wiki so exploration compounds like ingestion.

#### Step 1: Search

```bash
zenwiki search "<question>"
```

Read the top results. If the question involves specific concepts or entities, also read those pages directly.

#### Step 2: Gather Context

1. Read the matching wiki pages (summaries, concepts, entities)
2. For summaries, check `source_path` — if the wiki page doesn't have enough detail, read the original source from `raw/` for supplementary information
3. Follow `[[wikilinks]]` to gather related context (e.g. a concept page may link to relevant comparisons)

#### Step 3: Synthesize

1. Answer the question based on wiki content
2. Requirements:
   - **Cite sources:** use `[[slug]]` wikilinks for every factual claim
   - **Be specific:** include concrete data, configurations, numbers from the wiki
   - **Acknowledge gaps:** if the wiki doesn't fully cover the question, say so explicitly
   - **Suggest ingests:** if relevant raw sources exist that haven't been ingested, recommend `/ingest`

#### Step 4: Assess Crystallize Value

Recommend writing the answer back to wiki if:
- It synthesizes information from **multiple** sources (cross-source insight)
- It reveals a concept not yet recorded in the wiki
- It addresses a known open question from any page's `## Open Questions`

Do NOT crystallize if:
- It merely restates a single page
- It's a simple factual lookup
- The answer relies on inference rather than wiki evidence

#### Step 5: Crystallize (if user confirms)

1. Generate slug: `zenwiki slug "<answer title>"`
2. Write to `wiki/outputs/{slug}.md` with frontmatter including `citations` list
3. If the answer reveals a new concept → create under `wiki/concepts/` (follow Step 4 dedup rules from /ingest)
4. Update index and log:
   ```bash
   zenwiki rebuild-index
   zenwiki log "query | <question summary> | crystallized: outputs/<slug>"
   ```

---

### /consolidate — Build comparisons and maps from existing wiki

> After enough sources have been ingested, the wiki accumulates concepts and
> entities that overlap, compete, or belong to the same domain. Consolidation
> reviews the full wiki and creates the higher-order pages that individual
> ingests cannot easily produce.

#### Step 1: Inventory

1. Read `wiki/index.md` to get the full page listing.
2. Read every concept page's frontmatter (`key_sources`, `related_concepts`, `tags`).
3. Read every entity page's frontmatter (`key_sources`, `tags`, `category`).

#### Step 2: Identify Comparison Opportunities

Find concept pairs/groups where:
- Two or more concepts share **overlapping `key_sources`** (same source discusses both)
- Two or more concepts address the **same problem space** but propose different approaches
- Two or more entities are **competitors or alternatives** in the same category

For each candidate group, check `wiki/comparisons/` — if a comparison already covers those subjects, skip.

#### Step 3: Create Comparison Pages

For each new comparison opportunity:

1. Run `zenwiki find-similar "<comparison title>" --dir comparisons` to avoid duplicates.
2. Create `wiki/comparisons/{slug}.md` following the comparisons template.
3. Read the relevant concept/entity/summary pages to populate all sections substantively.
4. Add `[[wikilinks]]` from compared concepts/entities back to the new comparison page.

#### Step 4: Identify Map Opportunities

Find domains/tags where:
- **>= 5 related pages** exist (summaries + concepts + entities sharing a tag or topic cluster)
- No existing `maps/` page covers that domain

#### Step 5: Create or Update Map Pages

For each domain:

1. Run `zenwiki find-similar "<domain name>" --dir maps` to avoid duplicates.
2. Create or update `wiki/maps/{slug}.md` following the maps template.
3. List all related concepts in `## Core Concepts`, all related entities in `## Core Entities`.
4. Write a substantive `## Overview` that synthesizes the domain's knowledge landscape.
5. Add `## Timeline` if the domain has temporal progression across sources.

#### Step 6: Finalize

```bash
zenwiki rebuild-index
zenwiki refresh
zenwiki log "consolidate | new comparisons: <list> | new/updated maps: <list>"
```

---

### /lint — Wiki health check

> Run deterministic checks, review issues, improve wiki quality.

#### Step 1: Automated Checks

```bash
zenwiki lint
```

This checks: broken links, missing frontmatter, orphan pages, heading structure, empty sections.

#### Step 2: Fix Deterministic Issues

```bash
zenwiki lint --fix
```

Auto-fixes missing frontmatter defaults. For broken links and orphans, fix manually:
- **Broken link:** either create the missing page or fix the link target
- **Orphan:** add inbound links from related pages, or reconsider if the page is needed
- **Empty section:** fill it or remove the heading

#### Step 3: Content Quality Review

Scan the wiki for non-deterministic issues:
- **Thin summaries:** Technical Details section shorter than 200 words → needs more detail
- **Stale pages:** `date_updated` older than 6 months → may need refresh
- **Frequently-linked red links:** concepts referenced by multiple pages but no page exists → suggest creating
- **Concept near-duplicates:** two concepts with similar titles/aliases → suggest merging

Report findings and suggest actions to the user.

---

## Constraints

- **raw/ is read-only.** Never modify, overwrite, or delete files under raw/.
- **Deduplicate before creating.** ALWAYS run `zenwiki find-similar` before creating any new concept or entity page. Skipping this is the #1 cause of wiki bloat.
- **Hard limits per ingest.** At most 2 new concepts + 2 new entities per source (3+3 for importance=5). Force-merge when over the limit.
- **Synthesis pages have lint-enforced thresholds.** `comparisons/*` must declare ≥ 2 entries in `subjects` (otherwise `incomparable_subjects` rule blocks the compile). `maps/*` must declare ≥ 5 entries across `key_concepts + key_entities` (otherwise `thin_map` blocks). Do not create these pages until the wiki has enough real material — the compiler will also skip `/consolidate` entirely when total wiki pages < 5.
- **Default to merge, not create.** When `find-similar` returns a score between 0.40-0.85, default to merging into the existing page. Over-merging is a smaller mistake than over-creating.
- **Cite sources.** Every factual statement in the wiki must reference its source via `[[wikilink]]` or `source_path`.
- **Bidirectional links.** When writing a forward link, always update the target page with a backlink.
- **Keep index and log current.** Run `zenwiki rebuild-index` and `zenwiki log` after every operation.
- **Technical Details is sacred.** The `## Technical Details` section of summaries must be substantive — it's the primary carrier of queryable knowledge. Never write a shallow overview here.
- **Preserve original data.** When a source contains specific numbers, configurations, code, or procedures, include them verbatim in the wiki. Don't paraphrase away precision.

---

## Tool Reference

| Command | Purpose |
|---------|---------|
| `zenwiki search "<query>"` | Search wiki pages (returns JSON) |
| `zenwiki find-similar "<name>"` | Check for duplicate pages |
| `zenwiki slug "<title>"` | Generate kebab-case slug |
| `zenwiki rebuild-index` | Regenerate wiki/index.md |
| `zenwiki refresh` | Refresh qmd search index |
| `zenwiki log "<message>"` | Append to wiki/log.md |
| `zenwiki lint [--fix]` | Run deterministic health checks |
| `zenwiki status` | Show wiki statistics |
| `zenwiki pending` | Show unprocessed files in raw/ |
| `zenwiki compile [--watch] [--dry-run] [--prune]` | Auto-compile via Agent CLI |
| `zenwiki consolidate` | Build comparisons & maps from existing wiki |
| `zenwiki doctor` | Check environment readiness |
| `zenwiki provenance <path>` | Show source-to-article provenance |
| `zenwiki web` | Start the Web UI browser |
