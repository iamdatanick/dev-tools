# dev-tools

Reusable cross-project tooling for iamdatanick repos. Currently hosts:

- **`routing/`** — declarative repo-routing engine consumed by `cubie-*` and other Centillion repos via reusable GitHub Actions workflow.

Versioned via semver. Consumers pin to a major version tag (`@v1`); minor/patch upgrades roll automatically.

## Quick start (for consumer repos)

### 1. Add 4 files to your repo

```
tools/repo_routing_policy.yaml       # your policy (customise from starter template)
tools/auto_route.sh                  # 30-line shim, copy from routing/templates/auto_route.sh
NAVIGATION.md                        # agent entry doc, copy from routing/templates/NAVIGATION.starter.md
.github/workflows/repo_routing.yml   # 10-line workflow shim (below)
```

### 2. The CI workflow shim

`.github/workflows/repo_routing.yml`:

```yaml
name: Repo Routing Check
on: [pull_request]
jobs:
  check:
    uses: iamdatanick/dev-tools/.github/workflows/repo_routing_reusable.yml@v1
    with:
      policy-path: tools/repo_routing_policy.yaml
```

### 3. Run locally

```bash
bash tools/auto_route.sh check                  # CI parity locally
bash tools/auto_route.sh explain docs/foo.md    # "where should this go?"
bash tools/auto_route.sh apply --rule single-root-todo
bash tools/auto_route.sh list-rules
```

## Authoring a policy

Start with [`routing/templates/repo_routing_policy.starter.yaml`](routing/templates/repo_routing_policy.starter.yaml). Edit rules; each rule has:

- `id` — kebab-case, unique
- `pattern` (glob) **or** `forbid_pattern` — what files this rule governs
- `target` — destination, with template tokens like `{YYYY-MM}`, `{date-from-filename}`, `{lower-kebab-name}`, `{relative-path}`
- `reason` — required, plain English why this rule exists
- Optional: `location`, `exceptions[]`, `condition` DSL, `auto_apply` + `schedule`

Full schema: [`routing/repo_routing_policy.schema.json`](routing/repo_routing_policy.schema.json).

## Engine subcommands

| Subcommand | What it does | Exit code |
|---|---|---|
| `check` | Scan repo for files violating any applicable rule | 0 clean / 1 violations |
| `dry-run [--rule ID]` | Show what `apply` would do, no changes | 0 |
| `apply [--rule ID]` | `git mv` + atomic markdown link rewrite | 0 success |
| `explain <path>` | "Where should this go and which rule says so" | 0 |
| `list-rules` | Catalogue of every rule | 0 |
| `version` | Print engine version | 0 |

Global flags: `--policy <path>`, `--root <path>`, `--format text|json|markdown`.

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  iamdatanick/dev-tools  (this repo)                                 │
│    routing/auto_route.py             engine                         │
│    routing/repo_routing_policy.schema.json   schema                 │
│    routing/templates/                starter policy + NAVIGATION    │
│    routing/tests/                    engine self-tests              │
│    .github/workflows/                                               │
│      repo_routing_reusable.yml       reusable workflow              │
│      ci.yml                          engine self-tests in CI        │
│                                                                     │
│  Released as: v1.0.0, v1.x.y, v2.0.0   (semver)                     │
└────────────────────────────────────────────────────────────────────┘
            ▲
            │ consumed via uses: iamdatanick/dev-tools@v1
            │
┌────────────────────────────────────────────────────────────────────┐
│  Consumer repo (cubie-math, cubie-eu, RAKKIT, trustfortress, ...)   │
│    tools/repo_routing_policy.yaml    this repo's rules              │
│    tools/auto_route.sh               local invocation shim          │
│    NAVIGATION.md                     Q→A lookup table for agents    │
│    .github/workflows/repo_routing.yml   10-line shim                │
└────────────────────────────────────────────────────────────────────┘
```

## Planned consumers

- **cubie-math** — pilot (first integration)
- **cubie-eu** — second, validates engine generality across content domains
- All other tracked iamdatanick projects — opt-in over time

## Versioning policy

- `v1.x.y` — backwards-compatible additions
- `v2.0.0` — breaking schema/rule-semantics changes

Consumers pin `@v1` to get all v1.x.y patches automatically. Bumping `@v2` requires explicit consumer migration.

## Development

```bash
git clone https://github.com/iamdatanick/dev-tools.git
cd dev-tools
pip install pyyaml pytest
python3 -m pytest routing/tests/ -v
python3 routing/auto_route.py \
    --policy routing/templates/repo_routing_policy.starter.yaml \
    --root routing/tests/fixtures/sample-repo check
# Expect exit 1 — fixture intentionally violates the starter policy
```

See [`CHANGELOG.md`](CHANGELOG.md) for release notes.

## License

Apache-2.0 (see [LICENSE](LICENSE)).
