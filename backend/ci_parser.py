"""
JUnit XML parser for CI test failure ingestion.

Handles both <testsuite> (single) and <testsuites> (multi-suite) root elements,
which covers pytest, JUnit, TestNG, Mocha, and most CI frameworks.
"""

import xml.etree.ElementTree as ET
from typing import List, Dict, Any


def parse_junit_xml(xml_string: str) -> List[Dict[str, Any]]:
    """Parse JUnit XML and return a list of failure dicts.

    Each dict has:
      test_name, classname, failure_type ("failure"|"error"),
      failure_message, stack_trace
    """
    try:
        root = ET.fromstring(xml_string.strip())
    except ET.ParseError as e:
        raise ValueError(f"Invalid JUnit XML: {e}")

    # Normalise: collect all <testcase> elements regardless of root tag
    if root.tag == "testsuites":
        testcases = root.findall(".//testcase")
    elif root.tag == "testsuite":
        testcases = root.findall("testcase")
    else:
        raise ValueError(f"Unexpected XML root tag: <{root.tag}>. Expected <testsuite> or <testsuites>.")

    failures = []
    for tc in testcases:
        failure_el = tc.find("failure")
        error_el = tc.find("error")
        node = failure_el if failure_el is not None else error_el
        if node is None:
            continue  # passing or skipped test

        failures.append({
            "test_name":       tc.get("name", "unknown_test"),
            "classname":       tc.get("classname", "unknown_class"),
            "failure_type":    "failure" if failure_el is not None else "error",
            "failure_message": node.get("message", "").strip(),
            "stack_trace":     (node.text or "").strip(),
        })

    return failures


def build_bug_description(
    failure: Dict[str, Any],
    branch: str = "",
    commit_sha: str = "",
    run_url: str = "",
) -> str:
    """Convert a parsed test failure into a natural-language bug description for the LLM."""
    lines = [
        "Automated test failure detected in CI pipeline.",
        "",
        f"Test:         {failure['classname']}::{failure['test_name']}",
        f"Failure type: {failure['failure_type']}",
    ]

    if branch:
        lines.append(f"Branch:       {branch}")
    if commit_sha:
        lines.append(f"Commit:       {commit_sha[:12]}")
    if run_url:
        lines.append(f"CI run:       {run_url}")

    lines += [
        "",
        "Error message:",
        failure["failure_message"] or "(no message)",
    ]

    if failure["stack_trace"]:
        lines += [
            "",
            "Stack trace:",
            failure["stack_trace"],
        ]

    return "\n".join(lines)
