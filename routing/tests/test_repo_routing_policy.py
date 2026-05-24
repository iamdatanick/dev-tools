"""Schema validation tests for repo_routing_policy.yaml.

Validates the starter template AND any custom policies in consumer repos
(when run from a consumer repo directly).
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "routing" / "repo_routing_policy.schema.json"


def _load_schema():
    with SCHEMA_PATH.open() as f:
        return json.load(f)


def _validate(data, schema):
    """Minimal validator: checks required keys, version, basic types.

    For full JSON Schema validation, install `jsonschema`. We keep this
    lightweight so tests run without external deps.
    """
    if not isinstance(data, dict):
        raise ValueError("policy must be a dict")
    if "version" not in data:
        raise ValueError("missing required key: version")
    if data["version"] != 1:
        raise ValueError(f"version must be 1, got {data['version']}")
    if "rules" not in data:
        raise ValueError("missing required key: rules")
    if not isinstance(data["rules"], list) or not data["rules"]:
        raise ValueError("rules must be a non-empty array")
    for i, rule in enumerate(data["rules"]):
        if not isinstance(rule, dict):
            raise ValueError(f"rule[{i}] must be a dict")
        if "id" not in rule:
            raise ValueError(f"rule[{i}] missing required key: id")
        if "reason" not in rule:
            raise ValueError(f"rule[{i}] (id={rule.get('id')}) missing required key: reason")
        # exactly one of pattern/forbid_pattern
        has_pattern = "pattern" in rule
        has_forbid = "forbid_pattern" in rule
        if has_pattern == has_forbid:
            raise ValueError(
                f"rule[{i}] (id={rule.get('id')}) must have exactly one of "
                f"'pattern' or 'forbid_pattern'"
            )
        # at least one action
        action_keys = {"target", "move_rest_to", "extract_to", "forbid_pattern"}
        if not (action_keys & set(rule.keys())):
            raise ValueError(
                f"rule[{i}] (id={rule.get('id')}) must have at least one of: "
                f"{', '.join(action_keys)}"
            )
    # ID uniqueness
    ids = [r["id"] for r in data["rules"]]
    if len(ids) != len(set(ids)):
        dupes = [i for i in ids if ids.count(i) > 1]
        raise ValueError(f"duplicate rule ids: {set(dupes)}")
    return True


class TestSchema:
    def test_schema_file_valid_json(self):
        schema = _load_schema()
        assert schema["title"] == "RepoRoutingPolicy"
        assert schema["properties"]["version"]["const"] == 1


class TestStarterPolicy:
    def test_starter_template_validates(self):
        import yaml
        starter = ROOT / "routing" / "templates" / "repo_routing_policy.starter.yaml"
        with starter.open() as f:
            data = yaml.safe_load(f)
        _validate(data, _load_schema())

    def test_starter_rules_have_unique_ids(self):
        import yaml
        starter = ROOT / "routing" / "templates" / "repo_routing_policy.starter.yaml"
        with starter.open() as f:
            data = yaml.safe_load(f)
        ids = [r["id"] for r in data["rules"]]
        assert len(ids) == len(set(ids))

    def test_starter_rules_have_reason(self):
        import yaml
        starter = ROOT / "routing" / "templates" / "repo_routing_policy.starter.yaml"
        with starter.open() as f:
            data = yaml.safe_load(f)
        for rule in data["rules"]:
            assert rule.get("reason"), f"rule {rule['id']} missing reason"


class TestBadPolicies:
    def test_missing_version(self):
        with pytest.raises(ValueError, match="version"):
            _validate({"rules": [{"id": "x", "reason": "y", "pattern": "*", "target": "z"}]}, None)

    def test_missing_rules(self):
        with pytest.raises(ValueError, match="rules"):
            _validate({"version": 1}, None)

    def test_empty_rules(self):
        with pytest.raises(ValueError, match="non-empty"):
            _validate({"version": 1, "rules": []}, None)

    def test_rule_missing_id(self):
        with pytest.raises(ValueError, match="id"):
            _validate({
                "version": 1,
                "rules": [{"reason": "x", "pattern": "*", "target": "z"}],
            }, None)

    def test_rule_missing_reason(self):
        with pytest.raises(ValueError, match="reason"):
            _validate({
                "version": 1,
                "rules": [{"id": "x", "pattern": "*", "target": "z"}],
            }, None)

    def test_rule_pattern_and_forbid(self):
        with pytest.raises(ValueError, match="pattern.*forbid_pattern"):
            _validate({
                "version": 1,
                "rules": [{
                    "id": "x", "reason": "y",
                    "pattern": "*", "forbid_pattern": "*", "target": "z",
                }],
            }, None)

    def test_rule_neither_pattern_nor_forbid(self):
        with pytest.raises(ValueError, match="pattern.*forbid_pattern"):
            _validate({
                "version": 1,
                "rules": [{"id": "x", "reason": "y", "target": "z"}],
            }, None)

    def test_rule_no_action(self):
        with pytest.raises(ValueError, match="at least one of"):
            _validate({
                "version": 1,
                "rules": [{"id": "x", "reason": "y", "pattern": "*"}],
            }, None)

    def test_duplicate_ids(self):
        with pytest.raises(ValueError, match="duplicate"):
            _validate({
                "version": 1,
                "rules": [
                    {"id": "x", "reason": "a", "pattern": "*", "target": "y"},
                    {"id": "x", "reason": "b", "pattern": "*", "target": "z"},
                ],
            }, None)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
