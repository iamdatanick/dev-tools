# NAVIGATION.md — agent entry doc

> **Read this BEFORE anything else.** This doc tells you where every kind of
> file goes and how to look up answers without exploring the entire repo.

## The 3-step file-creation protocol

Before you create any file:

1. **Look up the canonical location:**
   ```
   bash tools/auto_route.sh explain <intended_path>
   ```
2. **Create the file at the path the command outputs.**
3. **Cite the rule id in your commit message:**
   ```
   Routing: rule=<id>
   ```

If `explain` says "no rule applies", you must EITHER:
- propose a new rule (PR `tools/repo_routing_policy.yaml`), OR
- confirm you actually need a new file (most "new" files are duplicates).

## Where to find information

| If you need… | Read / run this |
|---|---|
| Project goals | `README.md` |
| Architectural constraints | `HARD_BLOCKERS.md` (if present) |
| Decision history | `docs/architecture/adr/` (or `docs/adr/`) |
| What's outstanding | `TODO.md` and/or `roadmap/unified_action_items.jsonl` |
| Active plans | `docs/planning/plans/` |
| Closed plans | `docs/planning/plans/ARCHIVE/` |
| Audit results | `docs/audits/INDEX.md` |
| Where does file X go? | `bash tools/auto_route.sh explain <path>` |
| All routing rules | `bash tools/auto_route.sh list-rules` |

## Citation rule for numbers

Every number cited in any doc must reference the script that emitted it:

> "The corpus has 1,174 theorems (source: `bash tools/corpus_metrics.sh`, run 2026-05-23)."

## What NOT to do

- Do not create files at convenient paths just because they "feel right". Run
  `bash tools/auto_route.sh explain` first.
- Do not create new TODO files at root. There is exactly one: `TODO.md`.
- Do not create versioned-duplicate files (`_v2`, `_copy`, `_backup`, `_old`).
- Do not hardcode numbers in docs. Cite the source-of-truth script.
- Do not modify files in submodules.

## CI gates that will fail if you violate routing

- `.github/workflows/repo_routing.yml` — runs `auto_route check` on every PR.

## Common rule IDs

Run `bash tools/auto_route.sh list-rules` for the live catalog. Common rules
across consumer repos:

- `single-root-todo` — only `TODO.md` at root
- `audits-consolidation` — all audits → `docs/audits/`
- `sot-data-location` — CSV/JSONL → `roadmap/`
- `no-versioned-duplicates` — `_v2`/`_copy`/`_backup` forbidden
- `dated-tracking-bench` — dated `YYYY-MM-DD` docs → `docs/benchmarks/`
