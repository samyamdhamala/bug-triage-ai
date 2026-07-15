import pytest
from backend.rules import apply_team_routing, apply_severity_hints, add_review_labels, enhance_triage, suggest_test_areas


# --- Fixtures ---

def make_triage(**kwargs):
    base = {
        "title": "Something broke",
        "actual_behavior": "",
        "severity": "P3",
        "priority_reasoning": "",
        "suggested_labels": [],
        "confidence": "Medium",
        "suggested_assignee_team": "Triage Team",
    }
    base.update(kwargs)
    return base


# --- Team routing ---

class TestApplyTeamRouting:
    def test_auth_keyword_in_title(self):
        t = make_triage(title="Login button not working")
        assert apply_team_routing(t) == "Auth Team"

    def test_billing_keyword_in_actual_behavior(self):
        t = make_triage(actual_behavior="Payment fails at checkout")
        assert apply_team_routing(t) == "Billing Team"

    def test_frontend_keyword(self):
        t = make_triage(title="Modal closes unexpectedly")
        assert apply_team_routing(t) == "Frontend Team"

    def test_backend_keyword(self):
        t = make_triage(title="API timeout on data export")
        assert apply_team_routing(t) == "Backend Team"

    def test_no_match_falls_back_to_suggested_team(self):
        t = make_triage(title="Weird glitch", suggested_assignee_team="Platform Team")
        assert apply_team_routing(t) == "Platform Team"

    def test_no_match_no_suggestion_falls_back_to_triage(self):
        t = make_triage(title="Weird glitch")
        assert apply_team_routing(t) == "Triage Team"

    def test_case_insensitive(self):
        t = make_triage(title="BILLING INVOICE NOT SENT")
        assert apply_team_routing(t) == "Billing Team"


# --- Severity hints ---

class TestApplySeverityHints:
    def test_all_users_bumps_to_p1(self):
        t = make_triage(title="Crash affecting all users", severity="P2")
        severity, _ = apply_severity_hints(t)
        assert severity == "P1"

    def test_production_down_bumps_to_p1(self):
        t = make_triage(title="Production down", severity="P3")
        severity, _ = apply_severity_hints(t)
        assert severity == "P1"

    def test_revenue_keyword_bumps_to_p1(self):
        t = make_triage(priority_reasoning="This is blocking revenue", severity="P2")
        severity, _ = apply_severity_hints(t)
        assert severity == "P1"

    def test_already_p1_stays_p1(self):
        t = make_triage(title="all users affected", severity="P1")
        severity, _ = apply_severity_hints(t)
        assert severity == "P1"

    def test_intermittent_p4_bumps_to_p2(self):
        t = make_triage(title="intermittent crash", severity="P4")
        severity, _ = apply_severity_hints(t)
        assert severity == "P2"

    def test_enterprise_p4_bumps_to_p2(self):
        t = make_triage(title="enterprise dashboard broken", severity="P4")
        severity, _ = apply_severity_hints(t)
        assert severity == "P2"

    def test_no_keywords_no_change(self):
        t = make_triage(title="Minor tooltip misalignment", severity="P4")
        severity, _ = apply_severity_hints(t)
        assert severity == "P4"

    def test_reasoning_appended_on_bump(self):
        t = make_triage(title="all users locked out", severity="P3", priority_reasoning="Reported by customer")
        _, reasoning = apply_severity_hints(t)
        assert "[rule:" in reasoning


# --- Review labels ---

class TestAddReviewLabels:
    def test_low_confidence_adds_human_review_label(self):
        t = make_triage(confidence="Low")
        labels = add_review_labels(t)
        assert "needs-human-review" in labels

    def test_p1_adds_urgent_review_label(self):
        t = make_triage(severity="P1")
        labels = add_review_labels(t)
        assert "urgent-review" in labels

    def test_high_confidence_p3_no_extra_labels(self):
        t = make_triage(confidence="High", severity="P3")
        labels = add_review_labels(t)
        assert "needs-human-review" not in labels
        assert "urgent-review" not in labels

    def test_no_duplicate_labels(self):
        t = make_triage(confidence="Low", suggested_labels=["needs-human-review"])
        labels = add_review_labels(t)
        assert labels.count("needs-human-review") == 1


# --- Full enhance_triage pipeline ---

class TestEnhanceTriage:
    def test_full_pipeline_p1_low_confidence(self):
        t = make_triage(
            title="Login broken for all users",
            actual_behavior="Cannot sign in",
            severity="P2",
            confidence="Low",
        )
        result = enhance_triage(t)
        assert result["suggested_assignee_team"] == "Auth Team"
        assert result["severity"] == "P1"
        assert "urgent-review" in result["suggested_labels"]
        assert "needs-human-review" in result["suggested_labels"]

    def test_full_pipeline_no_rules_triggered(self):
        t = make_triage(
            title="Tooltip text is slightly off",
            severity="P4",
            confidence="High",
        )
        result = enhance_triage(t)
        assert result["severity"] == "P4"
        assert result["suggested_labels"] == []

    def test_full_pipeline_populates_related_test_areas(self):
        t = make_triage(title="Payment times out at checkout", severity="P2", confidence="High")
        result = enhance_triage(t)
        assert result["related_test_areas"] != []


# --- QA team routing ---

class TestQATeamRouting:
    def test_regression_routes_to_qa(self):
        t = make_triage(title="Regression in checkout flow after deploy")
        assert apply_team_routing(t) == "QA Team"

    def test_flaky_routes_to_qa(self):
        t = make_triage(title="Flaky test causing CI to fail randomly")
        assert apply_team_routing(t) == "QA Team"

    def test_flake_routes_to_qa(self):
        t = make_triage(title="Intermittent flake on nightly run")
        assert apply_team_routing(t) == "QA Team"

    def test_automation_failure_routes_to_qa(self):
        t = make_triage(actual_behavior="automation failure on nightly run")
        assert apply_team_routing(t) == "QA Team"

    def test_smoke_test_routes_to_qa(self):
        t = make_triage(title="Smoke test suite failing on staging")
        assert apply_team_routing(t) == "QA Team"

    def test_e2e_routes_to_qa(self):
        t = make_triage(title="E2E tests broken after merge")
        assert apply_team_routing(t) == "QA Team"

    def test_blocker_routes_to_qa(self):
        t = make_triage(title="Blocker preventing release sign-off")
        assert apply_team_routing(t) == "QA Team"

    def test_ci_failure_routes_to_qa(self):
        t = make_triage(actual_behavior="ci failure on every PR since yesterday")
        assert apply_team_routing(t) == "QA Team"


# --- Test area suggestions ---

class TestSuggestTestAreas:
    def test_auth_team_gets_auth_test_areas(self):
        t = make_triage(suggested_assignee_team="Auth Team")
        areas = suggest_test_areas(t)
        assert "auth_login_flow" in areas
        assert "session_management" in areas

    def test_billing_team_gets_payment_test_areas(self):
        t = make_triage(suggested_assignee_team="Billing Team")
        areas = suggest_test_areas(t)
        assert "payment_checkout_flow" in areas

    def test_frontend_team_gets_ui_test_areas(self):
        t = make_triage(suggested_assignee_team="Frontend Team")
        areas = suggest_test_areas(t)
        assert "ui_smoke_tests" in areas
        assert "cross_browser_compat" in areas

    def test_backend_team_gets_api_test_areas(self):
        t = make_triage(suggested_assignee_team="Backend Team")
        areas = suggest_test_areas(t)
        assert "api_contract_tests" in areas

    def test_qa_team_gets_regression_suite(self):
        t = make_triage(suggested_assignee_team="QA Team")
        areas = suggest_test_areas(t)
        assert "full_regression_suite" in areas
        assert "flaky_test_audit" in areas

    def test_unknown_team_falls_back_to_smoke(self):
        t = make_triage(suggested_assignee_team="Platform Team")
        areas = suggest_test_areas(t)
        assert areas == ["smoke_tests"]

    def test_enhance_triage_sets_related_test_areas(self):
        t = make_triage(title="Flaky E2E test in auth suite", severity="P3", confidence="Medium")
        result = enhance_triage(t)
        assert "related_test_areas" in result
        assert isinstance(result["related_test_areas"], list)
        assert len(result["related_test_areas"]) > 0
