# Changelog

All notable changes documented here. Semver: `vMAJOR.MINOR.PATCH`.

Consumers pin to `@v1` for all v1.x.y patches automatically.
Bumping to `@v2` requires explicit consumer migration.

## [v1.1.2] — 2026-05-24

### Fixed

- `auto_route_apply_reusable.yml` was using `git add -A` to stage routing moves, which also swept in the `.dev-tools/` engine checkout directory as an implicit submodule gitlink. Now uses `git add -A -- . ':!.dev-tools'` with matching `git status -- . ':!.dev-tools'` pre-check. The engine checkout is invisible to consumer commits.

## [v1.1.1] — 2026-05-24

### Fixed

- `auto_route_apply_reusable.yml` had invalid YAML in the bot-comment step (multi-line JavaScript array with backtick markdown fences confused the YAML parser, causing the workflow to fail at parse time with "found character ` that cannot start any token"). Dropped the bot-comment step entirely — the auto-applied commit on the PR branch is sufficient feedback. PR author sees the `chore(routing): auto-apply rules` commit directly. Workflow now passes YAML validation. Verified with `python3 -c "import yaml; yaml.safe_load(open(path))"`.

## [v1.1.0] — 2026-05-24

### Added

- New reusable workflow `auto_route_apply_reusable.yml` (Pattern B: auto-route on PR). Runs `apply --allow-unrelated-dirty` against the PR branch, pushes corrections back to the PR branch, comments on the PR with what moved, exits 0 (non-blocking). Author can place files anywhere; engine corrects them automatically on next CI run. Skips on PRs from forks (no write permission).
- README now advertises both Pattern B (auto-route, recommended) and Pattern A (check-only blocking) as consumer options.

### Notes

- Pattern B requires consumers enable "Read and write permissions" under Settings → Actions → General → Workflow permissions.
- Existing Pattern A workflow (`repo_routing_reusable.yml`) is unchanged and remains supported for consumers who want blocking enforcement.

## [v1.0.4] — 2026-05-24

### Fixed

- When a rule's `target` used `{strip-prefix:...}` (added in v1.0.3), the engine still appended the file basename on top, producing doubled paths like `docs/planning/plans/foo.md/foo.md`. Engine now recognises `{strip-prefix:` as a path-containing token (alongside `{lower-kebab-name}` and `{relative-path}`). 1 new regression test.

## [v1.0.3] — 2026-05-24

### Added

- New `{strip-prefix:foo/bar/}` template token strips the given leading prefix from `{relative-path}`. Use case: rename rules like `docs/superpowers/**` → `docs/planning/**` where you want only the path-under-the-pattern, not the full source path. Without strip-prefix, `target: docs/planning/{relative-path}` would resolve to `docs/planning/docs/superpowers/...`. With strip-prefix, `target: docs/planning/{strip-prefix:docs/superpowers/}` resolves correctly to `docs/planning/...`. 2 new tests.

## [v1.0.2] — 2026-05-24

### Fixed

- `{date-from-filename}` token regex was too greedy: matched any 4-digit sequence as a year. Now requires 4-digit years starting with `2` (range 2000-2999). Filenames like `v1.10_FormalCertificate_0427.txt` (where `0427` is MM-DD, not year 0427) now correctly fall back to current `YYYY-MM`. 3 new tests added.

### Added

- New `--allow-unrelated-dirty` flag on `apply` subcommand: skips the working-tree-clean check IF dirty files don't intersect the rule's prospective move set. Lets routing apply proceed when a concurrent session is writing to unrelated paths (e.g. proof corpora when the rule moves docs).

## [v1.0.1] — 2026-05-24

### Changed

- Repo visibility flipped to public; reusable workflow no longer requires `DEV_TOOLS_PAT` secret. Consumers can now invoke without configuring any secrets.
- README + workflow header comment updated to reflect public-access flow.

## [v1.0.0] — 2026-05-23

Initial release.

### Added

- `routing/auto_route.py` — declarative routing engine with 6 subcommands (`check`, `dry-run`, `apply`, `explain`, `list-rules`, `version`)
- `routing/repo_routing_policy.schema.json` — JSON Schema for policy YAML
- `routing/templates/repo_routing_policy.starter.yaml` — starter rule set (5 rules: single-root-todo, no-versioned-duplicates, audits-consolidation, dated-tracking-bench, sot-data-location)
- `routing/templates/NAVIGATION.starter.md` — agent entry doc template for consumer repos
- `routing/templates/auto_route.sh` — consumer-side shim that downloads and invokes the engine
- `routing/tests/test_auto_route.py` + `test_repo_routing_policy.py` — 48 unit + integration tests
- `routing/tests/fixtures/sample-repo/` — intentionally-misplaced fixture for integration tests
- `.github/workflows/repo_routing_reusable.yml` — reusable workflow for consumer repos
- `.github/workflows/ci.yml` — engine self-tests
- `README.md` — consumer integration guide

### Engine capabilities

- Pattern matching: glob (with `{}` brace expansion and `**` recursive), location-constrained, exception lists
- Template tokens: `{YYYY-MM}`, `{YYYY-MM-DD}`, `{date-from-filename}`, `{lower-kebab-name}`, `{relative-path}`
- Condition DSL: `all_checkboxes_checked`, `any_checkbox_unchecked`, `age > Nd`, `has_keyword(...)`, `matches_regex(...)`, `referenced_by_count > N`, combinable with `and` / `or`
- Atomic apply: `git mv` preserves history; in-repo markdown links rewritten in same commit
- Submodule exclusion: `.gitmodules` parsed; never enters submodule paths
- Default-excluded dirs: `.git`, `target`, `node_modules`, `__pycache__`, `.venv`, `venv`, `dist`, `build`, `artifacts`, `.cache`, `.pytest_cache`, `.mypy_cache`
- Refuses `apply` with dirty working tree
- Output formats: text, json, markdown
