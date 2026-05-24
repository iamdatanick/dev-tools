#!/usr/bin/env bash
# auto_route.sh — consumer-side shim that downloads and invokes the routing engine
# from iamdatanick/dev-tools at the pinned version.
#
# Usage (in any consumer repo):
#   bash tools/auto_route.sh check
#   bash tools/auto_route.sh explain docs/foo.md
#   bash tools/auto_route.sh apply --rule single-root-todo
#   bash tools/auto_route.sh list-rules
#
# Pin the engine version below. Bump explicitly when ready to upgrade.
set -euo pipefail

ENGINE_VERSION="v1.0.0"
ENGINE_REPO="iamdatanick/dev-tools"
CACHE_DIR="${HOME}/.cache/dev-tools/routing/${ENGINE_VERSION}"
ENGINE_PATH="${CACHE_DIR}/auto_route.py"
POLICY_PATH="${POLICY_PATH:-tools/repo_routing_policy.yaml}"

if [[ ! -f "${ENGINE_PATH}" ]]; then
    echo "Fetching routing engine ${ENGINE_VERSION} from ${ENGINE_REPO}..." >&2
    mkdir -p "${CACHE_DIR}"
    # Requires gh CLI authenticated. Private repo => PAT or gh auth.
    if command -v gh &>/dev/null; then
        gh api "repos/${ENGINE_REPO}/contents/routing/auto_route.py?ref=${ENGINE_VERSION}" \
            --jq '.content' \
            | base64 -d > "${ENGINE_PATH}"
    else
        echo "ERROR: gh CLI not found. Install: https://cli.github.com/" >&2
        exit 2
    fi
    chmod +x "${ENGINE_PATH}"
fi

# Verify Python + PyYAML available
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found." >&2
    exit 2
fi
if ! python3 -c "import yaml" 2>/dev/null; then
    echo "ERROR: PyYAML required. Install: pip install pyyaml" >&2
    exit 2
fi

exec python3 "${ENGINE_PATH}" --policy "${POLICY_PATH}" --root "$(pwd)" "$@"
