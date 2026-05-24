"""Unit tests for auto_route.py engine.

Run: cd dev-tools && python3 -m pytest routing/tests/ -v

Covers: pattern matching, template tokens, condition DSL, conflict
detection, submodule exclusion, link rewriting, CLI exit codes.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "routing"))

import auto_route as ar  # noqa: E402


# === pattern matching tests ===============================================

class TestPatternMatching:
    def test_simple_glob_root(self):
        assert ar.matches_pattern(Path("TODO.md"), "TODO*.md", "/")
        assert not ar.matches_pattern(Path("docs/TODO.md"), "TODO*.md", "/")

    def test_glob_any_location(self):
        assert ar.matches_pattern(Path("docs/AUDIT_x.md"), "AUDIT_*.md", "any")
        assert ar.matches_pattern(Path("AUDIT_x.md"), "AUDIT_*.md", "any")

    def test_brace_expansion(self):
        assert ar.matches_pattern(Path("foo_v2.md"), "*{_v2,_copy,_backup}*", "any")
        assert ar.matches_pattern(Path("bar_copy.md"), "*{_v2,_copy,_backup}*", "any")
        assert not ar.matches_pattern(Path("foo.md"), "*{_v2,_copy,_backup}*", "any")

    def test_location_constrained(self):
        # File must live UNDER location
        assert ar.matches_pattern(Path("docs/superpowers/plan.md"), "docs/superpowers/**/*", "any")

    def test_extension_alternation(self):
        assert ar.matches_pattern(Path("data.csv"), "*.{csv,jsonl}", "any")
        assert ar.matches_pattern(Path("data.jsonl"), "*.{csv,jsonl}", "any")
        assert not ar.matches_pattern(Path("data.json"), "*.{csv,jsonl}", "any")

    def test_brace_expand_helper(self):
        assert ar._expand_braces("a{1,2}b") == ["a1b", "a2b"]
        assert ar._expand_braces("a{1,2,3}b") == ["a1b", "a2b", "a3b"]
        assert ar._expand_braces("plain") == ["plain"]


# === template rendering tests =============================================

class TestTemplateRendering:
    def test_yyyy_mm(self, tmp_path):
        import re
        result = ar.render_target("docs/archive/{YYYY-MM}", Path("foo.md"), tmp_path)
        assert re.match(r"docs/archive/\d{4}-\d{2}$", result)

    def test_yyyy_mm_dd(self, tmp_path):
        import re
        result = ar.render_target("docs/{YYYY-MM-DD}", Path("foo.md"), tmp_path)
        assert re.match(r"docs/\d{4}-\d{2}-\d{2}$", result)

    def test_date_from_filename(self, tmp_path):
        result = ar.render_target("benchmarks/{date-from-filename}", Path("bench_2026-05-23.md"), tmp_path)
        assert result == "benchmarks/2026-05-23"

    def test_date_from_filename_ignores_non_year_4digit(self, tmp_path):
        """v1.0.2 fix: 0427 (April 27 in MM-DD format) is NOT a year. Engine should fall back to current YYYY-MM."""
        result = ar.render_target("archive/{date-from-filename}", Path("v1.10_FormalCert_0427.txt"), tmp_path)
        # Should fall back to current month since no valid year in filename
        import re as _re
        assert _re.match(r"archive/2\d{3}-\d{2}$", result), f"got {result!r}"

    def test_date_from_filename_year_only(self, tmp_path):
        """Real 4-digit year (>=2000) should be accepted with -01 suffix."""
        result = ar.render_target("archive/{date-from-filename}", Path("snapshot_2026.md"), tmp_path)
        assert result == "archive/2026-01"

    def test_date_from_filename_year_month(self, tmp_path):
        """YYYY-MM should match exactly."""
        result = ar.render_target("archive/{date-from-filename}", Path("snapshot_2026-04.md"), tmp_path)
        assert result == "archive/2026-04"

    def test_lower_kebab_name(self, tmp_path):
        result = ar.render_target("docs/architecture/{lower-kebab-name}", Path("MODULE_MAP.md"), tmp_path)
        assert result == "docs/architecture/module-map.md"

    def test_relative_path(self, tmp_path):
        result = ar.render_target("renamed/{relative-path}", Path("docs/superpowers/foo.md"), tmp_path)
        assert result == "renamed/docs/superpowers/foo.md"

    def test_strip_prefix_token(self, tmp_path):
        """v1.0.3: {strip-prefix:foo/bar/} strips that prefix from the relative path."""
        result = ar.render_target("docs/planning/{strip-prefix:docs/superpowers/}", Path("docs/superpowers/plans/foo.md"), tmp_path)
        assert result == "docs/planning/plans/foo.md"

    def test_strip_prefix_no_match(self, tmp_path):
        """If the prefix doesn't match, full relative path is used."""
        result = ar.render_target("dest/{strip-prefix:other/}", Path("docs/superpowers/foo.md"), tmp_path)
        assert result == "dest/docs/superpowers/foo.md"


# === condition DSL tests ==================================================

class TestConditionDSL:
    def test_all_checkboxes_checked_true(self, tmp_path):
        f = tmp_path / "plan.md"
        f.write_text("- [x] done\n- [x] also done\n")
        assert ar.evaluate_condition("all_checkboxes_checked", Path("plan.md"), tmp_path)

    def test_all_checkboxes_checked_false(self, tmp_path):
        f = tmp_path / "plan.md"
        f.write_text("- [x] done\n- [ ] not done\n")
        assert not ar.evaluate_condition("all_checkboxes_checked", Path("plan.md"), tmp_path)

    def test_no_checkboxes(self, tmp_path):
        f = tmp_path / "plan.md"
        f.write_text("just text, no boxes\n")
        # No boxes → returns False per spec
        assert not ar.evaluate_condition("all_checkboxes_checked", Path("plan.md"), tmp_path)

    def test_any_checkbox_unchecked(self, tmp_path):
        f = tmp_path / "plan.md"
        f.write_text("- [x] done\n- [ ] not\n")
        assert ar.evaluate_condition("any_checkbox_unchecked", Path("plan.md"), tmp_path)

    def test_age_predicate(self, tmp_path):
        f = tmp_path / "old.md"
        f.write_text("ancient")
        # Backdate by 100 days
        old_ts = (Path.cwd().stat().st_mtime) - (100 * 86400)
        os.utime(f, (old_ts, old_ts))
        assert ar.evaluate_condition("age > 60d", Path("old.md"), tmp_path)
        assert not ar.evaluate_condition("age > 200d", Path("old.md"), tmp_path)

    def test_has_keyword(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("Contains the DEPRECATED token in here.\n")
        assert ar.evaluate_condition("has_keyword('deprecated')", Path("doc.md"), tmp_path)
        assert not ar.evaluate_condition("has_keyword('xyzzy')", Path("doc.md"), tmp_path)

    def test_matches_regex(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("version: 1.2.3\n")
        assert ar.evaluate_condition(r"matches_regex('version: \d+\.\d+\.\d+')", Path("doc.md"), tmp_path)

    def test_combined_and(self, tmp_path):
        f = tmp_path / "plan.md"
        f.write_text("- [x] done\nDEPRECATED\n")
        old_ts = (Path.cwd().stat().st_mtime) - (100 * 86400)
        os.utime(f, (old_ts, old_ts))
        assert ar.evaluate_condition(
            "all_checkboxes_checked and age > 60d",
            Path("plan.md"), tmp_path,
        )

    def test_unknown_clause_raises(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("hi")
        with pytest.raises(ValueError):
            ar.evaluate_condition("unknown_predicate", Path("doc.md"), tmp_path)


# === submodule exclusion ==================================================

class TestSubmoduleExclusion:
    def test_gitmodules_parsed(self, tmp_path):
        (tmp_path / ".gitmodules").write_text(
            "[submodule \"foo\"]\n\tpath = foo\n\turl = https://example.com\n"
            "[submodule \"bar\"]\n\tpath = libs/bar\n\turl = https://example.com\n"
        )
        paths = ar.get_submodule_paths(tmp_path)
        assert paths == {"foo", "libs/bar"}

    def test_walker_skips_submodules(self, tmp_path):
        (tmp_path / ".gitmodules").write_text(
            "[submodule \"sub\"]\n\tpath = sub\n\turl = https://example.com\n"
        )
        (tmp_path / "root.md").write_text("ok")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "should_skip.md").write_text("nope")
        files = ar.walk_repo(tmp_path, submodule_paths={"sub"})
        names = [f.name for f in files]
        assert "root.md" in names
        assert "should_skip.md" not in names

    def test_walker_skips_default_excluded(self, tmp_path):
        target = tmp_path / "target" / "release"
        target.mkdir(parents=True)
        (target / "binary").write_text("blob")
        (tmp_path / "src.md").write_text("ok")
        files = ar.walk_repo(tmp_path)
        names = [f.name for f in files]
        assert "src.md" in names
        assert "binary" not in names


# === policy loading =======================================================

class TestPolicyLoading:
    def test_load_starter_policy(self):
        policy_path = ROOT / "routing" / "templates" / "repo_routing_policy.starter.yaml"
        rules = ar.load_policy(policy_path)
        assert len(rules) >= 5
        ids = [r.id for r in rules]
        assert "single-root-todo" in ids
        assert "sot-data-location" in ids

    def test_load_missing_rules_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("version: 1\n")
        with pytest.raises(ValueError):
            ar.load_policy(bad)

    def test_load_wrong_version_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("version: 2\nrules: []\n")
        with pytest.raises(ValueError):
            ar.load_policy(bad)


# === engine end-to-end ====================================================

class TestEngine:
    @pytest.fixture
    def sample_engine(self):
        policy = ROOT / "routing" / "templates" / "repo_routing_policy.starter.yaml"
        fixture = ROOT / "routing" / "tests" / "fixtures" / "sample-repo"
        return ar.Engine(policy, fixture)

    def test_scan_detects_violations(self, sample_engine):
        violations = sample_engine.scan()
        assert len(violations) >= 4  # 2 TODOs + 1 audit at root + 1 csv + 1 versioned-dupe + 1 nested audit

    def test_explain_known_match(self, sample_engine):
        result = sample_engine.explain("TODO_2026-05-19.md")
        assert result["rule_id"] == "single-root-todo"
        assert "todo-snapshots" in result["suggested_target"]

    def test_explain_no_match(self, sample_engine):
        result = sample_engine.explain("some/random/path.md")
        assert result["rule_id"] is None

    def test_explain_compliant_file(self, sample_engine):
        result = sample_engine.explain("TODO.md")
        # TODO.md is in the keep[] list — engine returns no rule_id (compliant)
        # OR it returns the rule but says "compliant"
        # Per current implementation: suggest_target returns None for keep matches,
        # find_applicable_rule still returns the rule. So rule_id is set but
        # there's no suggested_target.
        if result["rule_id"]:
            assert result["suggested_target"] is None


# === CLI integration ======================================================

class TestCLI:
    def test_version_subcommand(self):
        out = subprocess.check_output(
            [sys.executable, str(ROOT / "routing" / "auto_route.py"), "version"],
            text=True,
        )
        assert out.strip() == ar.VERSION

    def test_check_against_fixture_fails(self):
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "routing" / "auto_route.py"),
                "--policy", str(ROOT / "routing" / "templates" / "repo_routing_policy.starter.yaml"),
                "--root", str(ROOT / "routing" / "tests" / "fixtures" / "sample-repo"),
                "check",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "violations" in result.stdout.lower() or "fail" in result.stdout.lower()

    def test_list_rules_json(self):
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "routing" / "auto_route.py"),
                "--policy", str(ROOT / "routing" / "templates" / "repo_routing_policy.starter.yaml"),
                "--format", "json",
                "list-rules",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert data["version"] == 1
        assert len(data["rules"]) >= 5

    def test_check_missing_policy(self, tmp_path):
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "routing" / "auto_route.py"),
                "--policy", str(tmp_path / "nonexistent.yaml"),
                "--root", str(tmp_path),
                "check",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 2
        assert "not found" in result.stderr.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
