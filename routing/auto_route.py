#!/usr/bin/env python3
"""auto_route.py — declarative repo routing engine

Reads a policy YAML, enforces or applies routing rules across a repo tree.

Subcommands:
  check       Scan for violations. Exit 1 if any. CI gate.
  dry-run     Show what apply would do, no changes.
  apply       Move files per rules (git mv + link rewrite).
  explain     Tell user what rule applies to a path.
  list-rules  Catalog of rules in this policy.
  version     Print engine version and exit.

Documentation: https://github.com/iamdatanick/dev-tools/blob/master/README.md
"""

import argparse
import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# === Constants ============================================================

VERSION = "1.0.3"

DEFAULT_EXCLUDED_DIRS = {
    ".git", "target", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "artifacts", ".cache", ".pytest_cache", ".mypy_cache",
}

DATE_FROM_FILENAME_RE = re.compile(r"(2\d{3}-\d{2}-\d{2})|(2\d{3}-\d{2})|(2\d{3})")


# === Data classes =========================================================

@dataclass
class Rule:
    id: str
    reason: str
    description: str = ""
    pattern: Optional[str] = None
    forbid_pattern: Optional[str] = None
    location: str = "any"
    exceptions: list = field(default_factory=list)
    target: Optional[str] = None
    keep: list = field(default_factory=list)
    move_rest_to: Optional[str] = None
    extract_to: Optional[str] = None
    then_archive_to: Optional[str] = None
    redirect_to: Optional[str] = None
    keep_basename: bool = True
    condition: Optional[str] = None
    auto_apply: bool = False
    schedule: Optional[str] = None


@dataclass
class Violation:
    path: str
    rule_id: str
    current_location: str
    suggested_target: str
    reason: str


# === Policy loader ========================================================

def load_policy(policy_path: Path) -> list:
    with policy_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "rules" not in data:
        raise ValueError(f"policy {policy_path} missing 'rules' key")
    if data.get("version") != 1:
        raise ValueError(f"policy {policy_path} has unsupported version: {data.get('version')}")
    rules = []
    for rule_dict in data["rules"]:
        valid_fields = set(Rule.__dataclass_fields__.keys())
        filtered = {k: v for k, v in rule_dict.items() if k in valid_fields}
        rules.append(Rule(**filtered))
    return rules


# === File walker ==========================================================

def get_submodule_paths(repo_root: Path) -> set:
    gitmodules = repo_root / ".gitmodules"
    if not gitmodules.exists():
        return set()
    paths = set()
    with gitmodules.open(encoding="utf-8") as f:
        for line in f:
            m = re.match(r"\s*path\s*=\s*(.+)", line)
            if m:
                paths.add(m.group(1).strip())
    return paths


def walk_repo(repo_root: Path, submodule_paths: Optional[set] = None) -> list:
    submodule_paths = submodule_paths or set()
    files = []
    for root, dirs, filenames in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS]
        rel_root = Path(root).relative_to(repo_root)
        rel_root_str = str(rel_root).replace("\\", "/")
        if rel_root_str == ".":
            rel_root_str = ""
        if any(rel_root_str == sm or rel_root_str.startswith(sm + "/") for sm in submodule_paths):
            dirs[:] = []
            continue
        for fn in filenames:
            full = Path(root) / fn
            rel = full.relative_to(repo_root)
            files.append(rel)
    return sorted(files)


# === Pattern matcher ======================================================

def _expand_braces(pattern: str) -> list:
    """Expand {a,b,c} into multiple patterns. Simple single-level expansion."""
    m = re.search(r"\{([^{}]+)\}", pattern)
    if not m:
        return [pattern]
    alternatives = m.group(1).split(",")
    expanded = []
    for alt in alternatives:
        expanded.extend(_expand_braces(pattern[:m.start()] + alt + pattern[m.end():]))
    return expanded


def _pattern_to_regex(pattern: str) -> "re.Pattern":
    """Convert a glob with ** support to a compiled regex.

    Differs from fnmatch.translate(): supports '**' (any depth including 0 dirs).
    """
    parts = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*" and i + 1 < len(pattern) and pattern[i + 1] == "*":
            # '**' or '**/'
            if i + 2 < len(pattern) and pattern[i + 2] == "/":
                parts.append("(?:.*/)?")
                i += 3
            else:
                parts.append(".*")
                i += 2
        elif c == "*":
            parts.append("[^/]*")
            i += 1
        elif c == "?":
            parts.append("[^/]")
            i += 1
        elif c == ".":
            parts.append(r"\.")
            i += 1
        else:
            parts.append(re.escape(c) if c not in "[]" else c)
            i += 1
    return re.compile("^" + "".join(parts) + "$")


def matches_pattern(path: Path, pattern: str, location: str = "any") -> bool:
    """Match path against glob pattern, respecting location constraint."""
    path_str = str(path).replace("\\", "/")
    if location == "/":
        if "/" in path_str:
            return False
        candidates = [path.name]
    elif location != "any":
        loc_norm = location.rstrip("/").replace("\\", "/")
        if not (path_str == loc_norm or path_str.startswith(loc_norm + "/")):
            return False
        candidates = [path_str, path.name]
    else:
        candidates = [path_str, path.name]

    expanded = _expand_braces(pattern)
    for expanded_pat in expanded:
        # Use ** -aware regex if pattern contains it, else fnmatch.
        if "**" in expanded_pat:
            regex = _pattern_to_regex(expanded_pat)
            for candidate in candidates:
                if regex.match(candidate):
                    return True
        else:
            for candidate in candidates:
                if fnmatch.fnmatchcase(candidate, expanded_pat):
                    return True
    return False


# === Target renderer ======================================================

def render_target(target_template: str, source_path: Path, repo_root: Path) -> str:
    full = repo_root / source_path
    now = datetime.datetime.now()
    yyyy_mm = now.strftime("%Y-%m")
    yyyy_mm_dd = now.strftime("%Y-%m-%d")

    date_from_fn = ""
    m = DATE_FROM_FILENAME_RE.search(source_path.name)
    if m:
        token = m.group(0)
        if len(token) == 4:
            date_from_fn = f"{token}-01"
        else:
            date_from_fn = token

    lower_kebab_name = re.sub(r"[_\s]+", "-", source_path.name.lower())
    relative_path = str(source_path).replace("\\", "/")

    result = target_template
    result = result.replace("{YYYY-MM-DD}", yyyy_mm_dd)
    result = result.replace("{YYYY-MM}", yyyy_mm)
    result = result.replace("{date-from-filename}", date_from_fn or yyyy_mm)
    result = result.replace("{lower-kebab-name}", lower_kebab_name)

    # {strip-prefix:foo/bar/} -- strip leading "foo/bar/" from relative_path
    strip_re = re.compile(r"\{strip-prefix:([^}]+)\}")
    def _strip_sub(m):
        prefix = m.group(1)
        if relative_path.startswith(prefix):
            return relative_path[len(prefix):]
        return relative_path
    result = strip_re.sub(_strip_sub, result)

    result = result.replace("{relative-path}", relative_path)
    return result


# === Condition evaluator ==================================================

def evaluate_condition(condition: str, file_path: Path, repo_root: Path) -> bool:
    if not condition:
        return True
    full = repo_root / file_path
    if not full.exists():
        return False

    def eval_clause(clause: str) -> bool:
        clause = clause.strip()
        if clause == "all_checkboxes_checked":
            text = full.read_text(encoding="utf-8", errors="replace")
            checkboxes = re.findall(r"^\s*-\s*\[([xX ])\]", text, re.MULTILINE)
            if not checkboxes:
                return False
            return all(c.lower() == "x" for c in checkboxes)
        if clause == "any_checkbox_unchecked":
            text = full.read_text(encoding="utf-8", errors="replace")
            return bool(re.search(r"^\s*-\s*\[ \]", text, re.MULTILINE))
        m = re.match(r"age\s*>\s*(\d+)d", clause)
        if m:
            days = int(m.group(1))
            age_days = (datetime.datetime.now().timestamp() - full.stat().st_mtime) / 86400
            return age_days > days
        m = re.match(r"has_keyword\(['\"]([^'\"]+)['\"]\)", clause)
        if m:
            keyword = m.group(1).lower()
            return keyword in full.read_text(encoding="utf-8", errors="replace").lower()
        m = re.match(r"matches_regex\(['\"]([^'\"]+)['\"]\)", clause)
        if m:
            return bool(re.search(m.group(1), full.read_text(encoding="utf-8", errors="replace")))
        m = re.match(r"referenced_by_count\s*>\s*(\d+)", clause)
        if m:
            count = count_inbound_references(file_path, repo_root)
            return count > int(m.group(1))
        raise ValueError(f"Unknown condition clause: {clause!r}")

    tokens = re.split(r"\s+(and|or)\s+", condition.strip())
    result = eval_clause(tokens[0])
    i = 1
    while i < len(tokens) - 1:
        op = tokens[i]
        nxt = eval_clause(tokens[i + 1])
        if op == "and":
            result = result and nxt
        elif op == "or":
            result = result or nxt
        i += 2
    return result


def count_inbound_references(file_path: Path, repo_root: Path) -> int:
    target_basename = file_path.name
    count = 0
    for root, dirs, filenames in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS]
        for fn in filenames:
            if not fn.endswith((".md", ".rst")):
                continue
            full = Path(root) / fn
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if target_basename in text:
                count += 1
    return count


# === Engine core ==========================================================

class Engine:
    def __init__(self, policy_path: Path, repo_root: Path):
        self.policy_path = policy_path
        self.repo_root = repo_root
        self.rules = load_policy(policy_path)
        self.submodule_paths = get_submodule_paths(repo_root)

    def find_applicable_rule(self, path: Path) -> Optional[Rule]:
        for rule in self.rules:
            if any(matches_pattern(path, ex, "any") for ex in rule.exceptions):
                continue
            if rule.forbid_pattern:
                if matches_pattern(path, rule.forbid_pattern, rule.location):
                    return rule
                continue
            if not rule.pattern:
                continue
            if not matches_pattern(path, rule.pattern, rule.location):
                continue
            if rule.condition:
                try:
                    if not evaluate_condition(rule.condition, path, self.repo_root):
                        continue
                except ValueError:
                    continue
            return rule
        return None

    def suggest_target(self, path: Path, rule: Rule) -> Optional[str]:
        if rule.forbid_pattern:
            if rule.redirect_to:
                return render_target(rule.redirect_to, path, self.repo_root)
            return "(file should not exist)"
        if rule.keep and rule.move_rest_to:
            if path.name in rule.keep:
                return None
            return f"{render_target(rule.move_rest_to, path, self.repo_root).rstrip('/')}/{path.name}"
        if rule.target:
            rendered = render_target(rule.target, path, self.repo_root)
            if "{lower-kebab-name}" in rule.target or "{relative-path}" in rule.target:
                return rendered
            if rule.keep_basename:
                return f"{rendered.rstrip('/')}/{path.name}"
            return rendered
        if rule.extract_to and rule.then_archive_to:
            return f"{render_target(rule.then_archive_to, path, self.repo_root).rstrip('/')}/{path.name}"
        return None

    def scan(self, staged_only: bool = False) -> list:
        if staged_only:
            files = self._staged_files()
        else:
            files = walk_repo(self.repo_root, submodule_paths=self.submodule_paths)
        violations = []
        for path in files:
            rule = self.find_applicable_rule(path)
            if rule is None:
                continue
            target = self.suggest_target(path, rule)
            if target is None:
                continue
            current = str(path).replace("\\", "/")
            target_norm = target.replace("\\", "/")
            if current == target_norm:
                continue
            violations.append(Violation(
                path=current,
                rule_id=rule.id,
                current_location=current,
                suggested_target=target_norm,
                reason=rule.reason,
            ))
        return violations

    def _staged_files(self) -> list:
        try:
            out = subprocess.check_output(
                ["git", "diff", "--cached", "--name-only"],
                cwd=self.repo_root, text=True,
            )
        except subprocess.CalledProcessError:
            return []
        return [Path(p) for p in out.strip().splitlines() if p]

    def explain(self, path_str: str) -> dict:
        path = Path(path_str)
        rule = self.find_applicable_rule(path)
        if rule is None:
            return {
                "path": path_str,
                "rule_id": None,
                "verdict": "no rule applies; file is unconstrained by policy",
            }
        target = self.suggest_target(path, rule)
        current_norm = str(path).replace("\\", "/")
        target_norm = (target or "").replace("\\", "/")
        verdict = "compliant" if current_norm == target_norm else "should move"
        return {
            "path": path_str,
            "rule_id": rule.id,
            "reason": rule.reason,
            "suggested_target": target,
            "verdict": verdict,
        }


# === Apply ================================================================

def _compute_moves(engine: Engine, rule_id: Optional[str]) -> list:
    """Returns list of (src_path, dst_path) for the given rule (or all rules)."""
    rules_to_apply = engine.rules if rule_id is None else [r for r in engine.rules if r.id == rule_id]
    moves = []
    for rule in rules_to_apply:
        if rule.forbid_pattern:
            continue
        for path in walk_repo(engine.repo_root, submodule_paths=engine.submodule_paths):
            applicable = engine.find_applicable_rule(path)
            if applicable is None or applicable.id != rule.id:
                continue
            target = engine.suggest_target(path, rule)
            if target is None:
                continue
            current = str(path).replace("\\", "/")
            target_norm = target.replace("\\", "/")
            if current == target_norm:
                continue
            moves.append((current, target_norm))
    return moves


def _dirty_files_in_set(repo_root: Path, moves: list) -> set:
    """Returns set of paths from `moves` that are currently dirty in working tree."""
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=repo_root, text=True,
        )
    except subprocess.CalledProcessError:
        return set()
    dirty = set()
    for line in out.strip().splitlines():
        if len(line) < 3:
            continue
        path = line[3:].strip()
        # Handle "old -> new" rename notation
        if " -> " in path:
            path = path.split(" -> ")[-1]
        dirty.add(path.replace("\\", "/"))
    move_srcs = {src for src, _ in moves}
    return dirty & move_srcs




def apply_rule(engine: Engine, rule_id: Optional[str], dry_run: bool = False, allow_unrelated_dirty: bool = False) -> dict:
    if not dry_run:
        # First compute the move set so we can do a selective dirty check.
        prospective_moves = _compute_moves(engine, rule_id)
        if allow_unrelated_dirty:
            conflicting = _dirty_files_in_set(engine.repo_root, prospective_moves)
            if conflicting:
                return {"error": f"working tree dirty in files this rule would move: {sorted(conflicting)}", "moved": [], "would_move": []}
        else:
            if is_working_tree_dirty(engine.repo_root):
                return {"error": "working tree dirty; commit or stash first (or pass --allow-unrelated-dirty)", "moved": [], "would_move": []}

    if rule_id is not None and not [r for r in engine.rules if r.id == rule_id]:
        return {"error": f"no rule with id={rule_id}", "moved": [], "would_move": []}

    moves = _compute_moves(engine, rule_id)

    if dry_run:
        return {"would_move": moves, "rule_id": rule_id, "count": len(moves)}

    if not moves:
        return {"moved": [], "rule_id": rule_id, "count": 0}

    moved = []
    for src, dst in moves:
        dst_full = engine.repo_root / dst
        if dst_full.exists():
            print(f"SKIP {src} -> {dst}: destination exists", file=sys.stderr)
            continue
        dst_full.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(["git", "mv", src, dst], cwd=engine.repo_root)
        moved.append((src, dst))

    rewrite_links(engine.repo_root, moved)
    return {"moved": moved, "rule_id": rule_id, "count": len(moved)}


def is_working_tree_dirty(repo_root: Path) -> bool:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=repo_root, text=True,
        )
    except subprocess.CalledProcessError:
        return True
    return bool(out.strip())


def rewrite_links(repo_root: Path, moves: list) -> None:
    move_map = {src: dst for src, dst in moves}
    if not move_map:
        return
    for root, dirs, filenames in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS]
        for fn in filenames:
            if not fn.endswith((".md", ".rst", ".txt")):
                continue
            full = Path(root) / fn
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            new_text = text
            for src, dst in move_map.items():
                new_text = re.sub(
                    r"(\[[^\]]+\]\()" + re.escape(src) + r"(\))",
                    r"\g<1>" + dst + r"\g<2>",
                    new_text,
                )
            if new_text != text:
                full.write_text(new_text, encoding="utf-8")
                subprocess.check_call(
                    ["git", "add", str(full.relative_to(repo_root))],
                    cwd=repo_root,
                )


# === Output helpers =======================================================

def _output_violations(violations: list, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps([v.__dict__ for v in violations], indent=2))
    elif fmt == "markdown":
        print(f"# Routing violations ({len(violations)})\n")
        print("| Path | Rule | Suggested target | Reason |")
        print("|---|---|---|---|")
        for v in violations:
            print(f"| `{v.path}` | `{v.rule_id}` | `{v.suggested_target}` | {v.reason} |")
    else:
        print(f"FAIL -- {len(violations)} violations:\n")
        for v in violations:
            print(f"  {v.path}")
            print(f"    rule:      {v.rule_id}")
            print(f"    suggested: {v.suggested_target}")
            print(f"    reason:    {v.reason}")
            print()


def _output_list_rules(engine: Engine, fmt: str) -> int:
    if fmt == "json":
        rules_dict = [r.__dict__ for r in engine.rules]
        print(json.dumps({"version": 1, "rules": rules_dict}, indent=2, default=str))
    elif fmt == "markdown":
        print(f"# Routing rules ({len(engine.rules)})\n")
        print("| ID | Pattern / Forbid | Target | Reason |")
        print("|---|---|---|---|")
        for r in engine.rules:
            pat = r.pattern or f"FORBID: {r.forbid_pattern}"
            tgt = r.target or r.move_rest_to or r.redirect_to or "(see config)"
            print(f"| `{r.id}` | `{pat}` | `{tgt}` | {r.reason} |")
    else:
        print(f"{len(engine.rules)} rules:\n")
        for r in engine.rules:
            pat = r.pattern or f"FORBID: {r.forbid_pattern}"
            tgt = r.target or r.move_rest_to or r.redirect_to or "(see config)"
            print(f"  [{r.id}]")
            print(f"    pattern: {pat}")
            print(f"    target:  {tgt}")
            print(f"    reason:  {r.reason}")
            print()
    return 0


# === CLI ==================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Declarative repo routing engine (iamdatanick/dev-tools)",
        epilog=f"Engine version: {VERSION}",
    )
    parser.add_argument("--policy", default="tools/repo_routing_policy.yaml",
                        help="Path to policy YAML (default: tools/repo_routing_policy.yaml)")
    parser.add_argument("--root", default=".", help="Repo root (default: cwd)")
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text",
                        help="Output format")

    sub = parser.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check", help="Scan repo for violations; exit 1 if any. CI gate.")
    p_check.add_argument("--staged-only", action="store_true",
                         help="Only check git-staged files (for pre-commit hook)")
    p_dry = sub.add_parser("dry-run", help="Show what apply would do, no changes.")
    p_dry.add_argument("--rule", help="Limit to single rule id")
    p_apply = sub.add_parser("apply", help="Move files per rules (git mv + link rewrite).")
    p_apply.add_argument("--rule", help="Limit to single rule id")
    p_apply.add_argument("--allow-unrelated-dirty", action="store_true",
                         help="Skip working-tree-clean check IF dirty files don't intersect the rule's move set. "
                              "Useful when concurrent sessions are writing to unrelated paths.")
    p_explain = sub.add_parser("explain", help="Tell agent what rule applies to a path.")
    p_explain.add_argument("path", help="Intended or current file path")
    sub.add_parser("list-rules", help="Catalog of rules in this policy.")
    sub.add_parser("version", help="Print engine version and exit.")

    args = parser.parse_args()

    if args.cmd == "version":
        print(VERSION)
        return 0

    repo_root = Path(args.root).resolve()
    # Resolve policy path: try as-given (relative to CWD) first, then under repo_root.
    policy_path = Path(args.policy)
    if not policy_path.is_absolute() and not policy_path.exists():
        candidate = repo_root / args.policy
        if candidate.exists():
            policy_path = candidate
    policy_path = policy_path.resolve() if policy_path.exists() else policy_path
    if not policy_path.exists():
        print(f"ERROR: policy file not found: tried '{args.policy}' (cwd-relative) and '{repo_root / args.policy}' (root-relative)", file=sys.stderr)
        return 2

    try:
        engine = Engine(policy_path, repo_root)
    except yaml.YAMLError as e:
        print(f"ERROR: invalid policy YAML: {e}", file=sys.stderr)
        return 2
    except (ValueError, TypeError) as e:
        print(f"ERROR: invalid policy: {e}", file=sys.stderr)
        return 2

    if args.cmd == "list-rules":
        return _output_list_rules(engine, args.format)

    if args.cmd == "explain":
        result = engine.explain(args.path)
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print(f"Path:    {result['path']}")
            print(f"Rule:    {result.get('rule_id') or '(no match)'}")
            if result.get("rule_id"):
                print(f"Reason:  {result['reason']}")
                print(f"Target:  {result.get('suggested_target')}")
            print(f"Verdict: {result['verdict']}")
        return 0

    if args.cmd == "check":
        violations = engine.scan(staged_only=getattr(args, "staged_only", False))
        if not violations:
            print(f"OK -- {len(engine.rules)} rules, all files compliant.")
            return 0
        _output_violations(violations, args.format)
        return 1

    if args.cmd == "dry-run":
        result = apply_rule(engine, getattr(args, "rule", None), dry_run=True)
        if "error" in result:
            print(f"ERROR: {result['error']}", file=sys.stderr)
            return 1
        if not result.get("would_move"):
            print(f"No moves needed for rule={result.get('rule_id') or 'ALL'}.")
            return 0
        print(f"# Dry run (rule={result.get('rule_id') or 'ALL'}): {result['count']} moves\n")
        for src, dst in result["would_move"]:
            print(f"  {src} -> {dst}")
        return 0

    if args.cmd == "apply":
        result = apply_rule(engine, getattr(args, "rule", None), dry_run=False,
                            allow_unrelated_dirty=getattr(args, "allow_unrelated_dirty", False))
        if "error" in result:
            print(f"ERROR: {result['error']}", file=sys.stderr)
            return 1
        print(f"Applied rule={result.get('rule_id') or 'ALL'}: {result['count']} files moved.")
        for src, dst in result["moved"]:
            print(f"  {src} -> {dst}")
        if result["moved"]:
            print()
            print("Next: review the changes and commit with subject:")
            print(f"  chore(routing): apply rule={result.get('rule_id')} -- {result['count']} files moved")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
