import json
import pytest
from unittest.mock import patch, mock_open


# --- save_feedback / load_recent_feedback ---

class TestFeedbackStore:
    def _patch_store(self, entries=None):
        """Context manager that mocks the feedback JSON file."""
        from unittest.mock import patch
        return patch("backend.feedback_store._load", return_value=entries or []), \
               patch("backend.feedback_store._save")

    def test_save_feedback_appends_entry(self):
        from backend.feedback_store import save_feedback
        saved = []

        def fake_save(entries):
            saved.extend(entries)

        with patch("backend.feedback_store._load", return_value=[]), \
             patch("backend.feedback_store._save", side_effect=fake_save):
            save_feedback("BT-42", "Severity should be P1", corrected_by="U123")

        assert len(saved) == 1
        assert saved[0]["jira_key"] == "BT-42"
        assert saved[0]["comment"] == "Severity should be P1"
        assert saved[0]["corrected_by"] == "U123"
        assert "timestamp" in saved[0]

    def test_save_feedback_uppercases_jira_key(self):
        from backend.feedback_store import save_feedback
        saved = []
        with patch("backend.feedback_store._load", return_value=[]), \
             patch("backend.feedback_store._save", side_effect=lambda e: saved.extend(e)):
            save_feedback("bt-7", "wrong team")
        assert saved[0]["jira_key"] == "BT-7"

    def test_save_feedback_strips_whitespace(self):
        from backend.feedback_store import save_feedback
        saved = []
        with patch("backend.feedback_store._load", return_value=[]), \
             patch("backend.feedback_store._save", side_effect=lambda e: saved.extend(e)):
            save_feedback("BT-1", "  trailing spaces  ")
        assert saved[0]["comment"] == "trailing spaces"

    def test_save_feedback_preserves_existing_entries(self):
        from backend.feedback_store import save_feedback
        existing = [{"jira_key": "BT-1", "comment": "old", "corrected_by": "x", "timestamp": "t"}]
        saved = []
        with patch("backend.feedback_store._load", return_value=existing), \
             patch("backend.feedback_store._save", side_effect=lambda e: saved.extend(e)):
            save_feedback("BT-2", "new correction")
        assert len(saved) == 2
        assert saved[0]["jira_key"] == "BT-1"
        assert saved[1]["jira_key"] == "BT-2"

    def test_load_recent_feedback_returns_newest_first(self):
        from backend.feedback_store import load_recent_feedback
        entries = [
            {"jira_key": "BT-1", "comment": "oldest"},
            {"jira_key": "BT-2", "comment": "middle"},
            {"jira_key": "BT-3", "comment": "newest"},
        ]
        with patch("backend.feedback_store._load", return_value=entries):
            result = load_recent_feedback(n=3)
        assert result[0]["jira_key"] == "BT-3"
        assert result[1]["jira_key"] == "BT-2"
        assert result[2]["jira_key"] == "BT-1"

    def test_load_recent_feedback_respects_n_limit(self):
        from backend.feedback_store import load_recent_feedback
        entries = [{"jira_key": f"BT-{i}", "comment": f"c{i}"} for i in range(10)]
        with patch("backend.feedback_store._load", return_value=entries):
            result = load_recent_feedback(n=3)
        assert len(result) == 3

    def test_load_recent_feedback_returns_empty_when_no_store(self):
        from backend.feedback_store import load_recent_feedback
        with patch("backend.feedback_store._load", return_value=[]):
            result = load_recent_feedback()
        assert result == []


# --- format_feedback_for_prompt ---

class TestFormatFeedbackForPrompt:
    def test_returns_empty_string_when_no_feedback(self):
        from backend.feedback_store import format_feedback_for_prompt
        with patch("backend.feedback_store._load", return_value=[]):
            result = format_feedback_for_prompt()
        assert result == ""

    def test_includes_jira_key_and_comment(self):
        from backend.feedback_store import format_feedback_for_prompt
        entries = [{"jira_key": "BT-42", "comment": "Should be P1"}]
        with patch("backend.feedback_store._load", return_value=entries):
            result = format_feedback_for_prompt()
        assert "BT-42" in result
        assert "Should be P1" in result

    def test_includes_correction_header(self):
        from backend.feedback_store import format_feedback_for_prompt
        entries = [{"jira_key": "BT-1", "comment": "Wrong team"}]
        with patch("backend.feedback_store._load", return_value=entries):
            result = format_feedback_for_prompt()
        assert "RECENT QA CORRECTIONS" in result

    def test_formats_multiple_entries(self):
        from backend.feedback_store import format_feedback_for_prompt
        entries = [
            {"jira_key": "BT-1", "comment": "wrong severity"},
            {"jira_key": "BT-2", "comment": "wrong team"},
        ]
        with patch("backend.feedback_store._load", return_value=entries):
            result = format_feedback_for_prompt()
        assert "BT-1" in result
        assert "BT-2" in result
        assert result.count("- [") == 2

    def test_ends_with_double_newline(self):
        from backend.feedback_store import format_feedback_for_prompt
        entries = [{"jira_key": "BT-1", "comment": "fix this"}]
        with patch("backend.feedback_store._load", return_value=entries):
            result = format_feedback_for_prompt()
        assert result.endswith("\n\n")


# --- prompt injection in triage.py ---

class TestFeedbackPromptInjection:
    def test_feedback_injected_before_bug_report(self):
        from backend.triage import triage_bug
        from unittest.mock import MagicMock

        fake_triage_json = json.dumps({
            "title": "Login broken", "severity": "P2", "component": "Auth",
            "bug_type": "functional", "affected_users": "some",
            "reproduction_steps": [], "expected_behavior": "works",
            "actual_behavior": "500 error", "suggested_labels": [],
            "priority_reasoning": "major", "suggested_assignee_team": "Auth Team",
            "confidence": "High",
        })

        captured_prompts = []

        def capture_prompt(prompt):
            captured_prompts.append(prompt)
            return fake_triage_json

        correction = [{"jira_key": "BT-1", "comment": "Severity was wrong"}]

        with patch("backend.triage.generate_structured_ticket", side_effect=capture_prompt), \
             patch("backend.feedback_store._load", return_value=correction):
            triage_bug("Login button is broken")

        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "RECENT QA CORRECTIONS" in prompt
        assert "BT-1" in prompt
        bug_report_pos = prompt.index("BUG REPORT:")
        corrections_pos = prompt.index("RECENT QA CORRECTIONS")
        assert corrections_pos < bug_report_pos

    def test_no_injection_when_no_feedback(self):
        from backend.triage import triage_bug

        fake_triage_json = json.dumps({
            "title": "Login broken", "severity": "P2", "component": "Auth",
            "bug_type": "functional", "affected_users": "some",
            "reproduction_steps": [], "expected_behavior": "works",
            "actual_behavior": "500 error", "suggested_labels": [],
            "priority_reasoning": "major", "suggested_assignee_team": "Auth Team",
            "confidence": "High",
        })

        captured_prompts = []

        with patch("backend.triage.generate_structured_ticket", side_effect=lambda p: (captured_prompts.append(p), fake_triage_json)[1]), \
             patch("backend.feedback_store._load", return_value=[]):
            triage_bug("Login button is broken")

        assert "RECENT QA CORRECTIONS" not in captured_prompts[0]
