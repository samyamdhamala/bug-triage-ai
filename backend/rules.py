from typing import Dict, Any, List

RULE_MAPPINGS = {
    # Team routing keywords -> team
    'auth': 'Auth Team',
    'login': 'Auth Team',
    'credential': 'Auth Team',
    'sign in': 'Auth Team',
    'billing': 'Billing Team',
    'invoice': 'Billing Team',
    'payment': 'Billing Team',
    'subscription': 'Billing Team',
    'button': 'Frontend Team',
    'modal': 'Frontend Team',
    'layout': 'Frontend Team',
    'alignment': 'Frontend Team',
    'mobile ui': 'Frontend Team',
    'api': 'Backend Team',
    'export': 'Backend Team',
    'sync': 'Backend Team',
    'timeout': 'Backend Team',
    'data': 'Backend Team',
    'backend': 'Backend Team',
    # QA-specific signals -> QA Team
    'regression': 'QA Team',
    'flaky': 'QA Team',
    'flake': 'QA Team',
    'automation failure': 'QA Team',
    'test failure': 'QA Team',
    'test case': 'QA Team',
    'smoke test': 'QA Team',
    'e2e': 'QA Team',
    'end-to-end': 'QA Team',
    'ci failure': 'QA Team',
    'pipeline failure': 'QA Team',
    'blocker': 'QA Team',
}

# Maps assigned team -> relevant test suites a QA engineer should check/rerun
TEAM_TEST_AREAS: Dict[str, List[str]] = {
    'Auth Team':     ['auth_login_flow', 'session_management', 'password_reset', 'sso_flow'],
    'Billing Team':  ['payment_checkout_flow', 'invoice_generation', 'subscription_upgrade_downgrade'],
    'Frontend Team': ['ui_smoke_tests', 'cross_browser_compat', 'responsive_layout'],
    'Backend Team':  ['api_contract_tests', 'data_integrity', 'performance_regression'],
    'QA Team':       ['full_regression_suite', 'automation_health_check', 'flaky_test_audit'],
}

def apply_team_routing(triage: Dict[str, Any]) -> str:
    """Deterministic team routing based on keywords in title/actual_behavior."""
    text = (triage.get('title', '') + ' ' + triage.get('actual_behavior', '')).lower()
    for keyword, team in RULE_MAPPINGS.items():
        if keyword in text:
            return team
    return triage.get('suggested_assignee_team', 'Triage Team')

def apply_severity_hints(triage: Dict[str, Any]) -> tuple[str, str]:
    """Gentle severity adjustment hints based on keywords."""
    severity = triage.get('severity', 'P3')
    reasoning = triage.get('priority_reasoning', '')
    
    text = (triage.get('title', '') + ' ' + reasoning).lower()
    
    # Bump hints (never downgrade)
    if any(word in text for word in ['widespread', 'all users', 'production down', 'revenue']) and severity != 'P1':
        severity = 'P1'
        reasoning += " [rule: high impact keywords]"
    elif any(word in text for word in ['intermittent', 'no workaround', 'enterprise']) and severity == 'P4':
        severity = 'P2'
        reasoning += " [rule: business impact]"
    
    return severity, reasoning

def add_review_labels(triage: Dict[str, Any]) -> List[str]:
    """Add deterministic labels for human review."""
    labels = triage.get('suggested_labels', [])
    confidence = triage.get('confidence', 'Medium')
    severity = triage.get('severity', 'P3')
    
    if confidence == 'Low':
        if 'needs-human-review' not in labels:
            labels.append('needs-human-review')
    if severity == 'P1':
        if 'urgent-review' not in labels:
            labels.append('urgent-review')
    
    return labels

def suggest_test_areas(triage: Dict[str, Any]) -> List[str]:
    """Return test suites a QA engineer should rerun, based on routed team."""
    team = triage.get('suggested_assignee_team', '')
    return TEAM_TEST_AREAS.get(team, ['smoke_tests'])

def enhance_triage(triage: Dict[str, Any]) -> Dict[str, Any]:
    """Apply all rules post-LLM."""
    triage['suggested_assignee_team'] = apply_team_routing(triage)
    triage['severity'], triage['priority_reasoning'] = apply_severity_hints(triage)
    triage['suggested_labels'] = add_review_labels(triage)
    triage['related_test_areas'] = suggest_test_areas(triage)
    return triage

