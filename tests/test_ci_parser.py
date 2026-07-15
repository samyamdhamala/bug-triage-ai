import pytest
from backend.ci_parser import parse_junit_xml, build_bug_description

# --- Fixtures ---

SINGLE_SUITE_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="tests/test_auth.py" tests="3" failures="1" errors="1">
  <testcase classname="tests.test_auth" name="test_login_flow" time="0.12">
    <failure message="AssertionError: expected 200 got 500">
Traceback (most recent call last):
  File "tests/test_auth.py", line 45, in test_login_flow
    assert response.status_code == 200
AssertionError: expected 200 got 500
    </failure>
  </testcase>
  <testcase classname="tests.test_auth" name="test_session_refresh" time="0.05">
    <error message="ConnectionError: DB unavailable">
DB connection pool exhausted
    </error>
  </testcase>
  <testcase classname="tests.test_auth" name="test_logout" time="0.01"/>
</testsuite>"""

MULTI_SUITE_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="tests/test_auth.py" tests="1" failures="1">
    <testcase classname="tests.test_auth" name="test_login">
      <failure message="Login returned 403">403 Forbidden</failure>
    </testcase>
  </testsuite>
  <testsuite name="tests/test_payment.py" tests="1" errors="1">
    <testcase classname="tests.test_payment" name="test_checkout">
      <error message="Timeout after 30s">Request timed out</error>
    </testcase>
  </testsuite>
</testsuites>"""

ALL_PASSING_XML = """<testsuite name="tests/test_smoke.py" tests="2">
  <testcase classname="tests.test_smoke" name="test_health" time="0.01"/>
  <testcase classname="tests.test_smoke" name="test_home" time="0.02"/>
</testsuite>"""

SKIPPED_XML = """<testsuite name="tests/test_misc.py" tests="2">
  <testcase classname="tests.test_misc" name="test_skipped">
    <skipped message="not implemented yet"/>
  </testcase>
  <testcase classname="tests.test_misc" name="test_pass" time="0.01"/>
</testsuite>"""


# --- parse_junit_xml ---

class TestParseJunitXml:
    def test_parses_failure_from_single_suite(self):
        results = parse_junit_xml(SINGLE_SUITE_XML)
        failure = next(r for r in results if r["failure_type"] == "failure")
        assert failure["test_name"] == "test_login_flow"
        assert failure["classname"] == "tests.test_auth"
        assert "expected 200 got 500" in failure["failure_message"]

    def test_parses_error_from_single_suite(self):
        results = parse_junit_xml(SINGLE_SUITE_XML)
        error = next(r for r in results if r["failure_type"] == "error")
        assert error["test_name"] == "test_session_refresh"
        assert "DB unavailable" in error["failure_message"]

    def test_skips_passing_tests(self):
        results = parse_junit_xml(SINGLE_SUITE_XML)
        names = [r["test_name"] for r in results]
        assert "test_logout" not in names

    def test_returns_two_failures_from_single_suite(self):
        results = parse_junit_xml(SINGLE_SUITE_XML)
        assert len(results) == 2

    def test_parses_multi_suite_xml(self):
        results = parse_junit_xml(MULTI_SUITE_XML)
        assert len(results) == 2
        names = {r["test_name"] for r in results}
        assert "test_login" in names
        assert "test_checkout" in names

    def test_multi_suite_failure_types(self):
        results = parse_junit_xml(MULTI_SUITE_XML)
        types = {r["test_name"]: r["failure_type"] for r in results}
        assert types["test_login"] == "failure"
        assert types["test_checkout"] == "error"

    def test_all_passing_returns_empty(self):
        results = parse_junit_xml(ALL_PASSING_XML)
        assert results == []

    def test_skipped_tests_not_included(self):
        results = parse_junit_xml(SKIPPED_XML)
        assert results == []

    def test_stack_trace_captured(self):
        results = parse_junit_xml(SINGLE_SUITE_XML)
        failure = next(r for r in results if r["test_name"] == "test_login_flow")
        assert "assert response.status_code == 200" in failure["stack_trace"]

    def test_raises_on_invalid_xml(self):
        with pytest.raises(ValueError, match="Invalid JUnit XML"):
            parse_junit_xml("not xml at all")

    def test_raises_on_wrong_root_tag(self):
        with pytest.raises(ValueError, match="Unexpected XML root tag"):
            parse_junit_xml("<results><test/></results>")

    def test_handles_missing_classname(self):
        xml = '<testsuite><testcase name="test_foo"><failure message="oops"/></testcase></testsuite>'
        results = parse_junit_xml(xml)
        assert results[0]["classname"] == "unknown_class"

    def test_handles_missing_message_attribute(self):
        xml = '<testsuite><testcase classname="c" name="t"><failure>stack trace here</failure></testcase></testsuite>'
        results = parse_junit_xml(xml)
        assert results[0]["failure_message"] == ""
        assert "stack trace here" in results[0]["stack_trace"]


# --- build_bug_description ---

class TestBuildBugDescription:
    def _failure(self, **kwargs):
        base = {
            "test_name": "test_login_flow",
            "classname": "tests.test_auth",
            "failure_type": "failure",
            "failure_message": "AssertionError: expected 200 got 500",
            "stack_trace": "assert response.status_code == 200",
        }
        base.update(kwargs)
        return base

    def test_includes_test_name_and_classname(self):
        desc = build_bug_description(self._failure())
        assert "tests.test_auth::test_login_flow" in desc

    def test_includes_failure_message(self):
        desc = build_bug_description(self._failure())
        assert "AssertionError: expected 200 got 500" in desc

    def test_includes_stack_trace(self):
        desc = build_bug_description(self._failure())
        assert "assert response.status_code == 200" in desc

    def test_includes_branch_when_provided(self):
        desc = build_bug_description(self._failure(), branch="feature/login-fix")
        assert "feature/login-fix" in desc

    def test_includes_commit_sha_truncated(self):
        desc = build_bug_description(self._failure(), commit_sha="abc123def456789")
        assert "abc123def456" in desc

    def test_includes_run_url(self):
        desc = build_bug_description(self._failure(), run_url="https://github.com/org/repo/actions/runs/99")
        assert "https://github.com/org/repo/actions/runs/99" in desc

    def test_omits_branch_when_empty(self):
        desc = build_bug_description(self._failure(), branch="")
        assert "Branch:" not in desc

    def test_omits_run_url_when_empty(self):
        desc = build_bug_description(self._failure(), run_url="")
        assert "CI run:" not in desc

    def test_includes_ci_pipeline_header(self):
        desc = build_bug_description(self._failure())
        assert "CI pipeline" in desc

    def test_error_type_reflected(self):
        desc = build_bug_description(self._failure(failure_type="error"))
        assert "error" in desc
