import pytest
from backend.triage import parse_llm_response
from backend.llm_client import TRIAGE_JSON_SCHEMA


# --- parse_llm_response ---

class TestParseLlmResponse:
    def _valid_json(self, **overrides):
        base = {
            "title": "Login button not working",
            "severity": "P2",
            "component": "Auth",
            "bug_type": "functional",
            "affected_users": "all users",
            "reproduction_steps": ["Go to login page", "Click submit"],
            "expected_behavior": "User logs in",
            "actual_behavior": "500 error returned",
            "suggested_labels": ["auth", "p2"],
            "priority_reasoning": "Major feature broken",
            "suggested_assignee_team": "Auth Team",
            "confidence": "High",
        }
        base.update(overrides)
        import json
        return json.dumps(base)

    def test_parses_clean_json(self):
        result = parse_llm_response(self._valid_json())
        assert result["title"] == "Login button not working"
        assert result["severity"] == "P2"

    def test_raises_on_invalid_json(self):
        with pytest.raises(ValueError, match="invalid JSON"):
            parse_llm_response("not json at all")

    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError, match="invalid JSON"):
            parse_llm_response("")

    def test_raises_on_markdown_wrapped_json(self):
        # With structured outputs this should never happen, but if it does we
        # surface a clear error instead of silently scraping.
        md = "```json\n{\"title\": \"test\"}\n```"
        with pytest.raises(ValueError, match="invalid JSON"):
            parse_llm_response(md)

    def test_parses_json_with_extra_fields(self):
        # extra fields are ignored by Pydantic (extra='ignore') — parse should succeed
        import json
        payload = json.loads(self._valid_json())
        payload["unknown_field"] = "should be ignored"
        result = parse_llm_response(json.dumps(payload))
        assert "unknown_field" in result  # parse_llm_response returns raw dict; Pydantic ignores it later

    def test_parses_empty_arrays(self):
        result = parse_llm_response(self._valid_json(reproduction_steps=[], suggested_labels=[]))
        assert result["reproduction_steps"] == []
        assert result["suggested_labels"] == []


# --- TRIAGE_JSON_SCHEMA structure ---

class TestTriageJsonSchema:
    def test_schema_has_correct_name(self):
        assert TRIAGE_JSON_SCHEMA["name"] == "triage_output"

    def test_schema_is_strict(self):
        assert TRIAGE_JSON_SCHEMA["strict"] is True

    def test_schema_has_no_additional_properties(self):
        assert TRIAGE_JSON_SCHEMA["schema"]["additionalProperties"] is False

    def test_all_required_fields_present(self):
        required = set(TRIAGE_JSON_SCHEMA["schema"]["required"])
        expected = {
            "title", "severity", "component", "bug_type", "affected_users",
            "reproduction_steps", "expected_behavior", "actual_behavior",
            "suggested_labels", "priority_reasoning", "suggested_assignee_team", "confidence",
        }
        assert required == expected

    def test_severity_enum_values(self):
        severity_schema = TRIAGE_JSON_SCHEMA["schema"]["properties"]["severity"]
        assert set(severity_schema["enum"]) == {"P1", "P2", "P3", "P4"}

    def test_confidence_enum_values(self):
        confidence_schema = TRIAGE_JSON_SCHEMA["schema"]["properties"]["confidence"]
        assert set(confidence_schema["enum"]) == {"High", "Medium", "Low"}

    def test_array_fields_have_string_items(self):
        props = TRIAGE_JSON_SCHEMA["schema"]["properties"]
        for field in ("reproduction_steps", "suggested_labels"):
            assert props[field]["type"] == "array"
            assert props[field]["items"] == {"type": "string"}
