import json

import pytest
from pydantic import ValidationError

from acme.models import FindingCode, Severity
from acme.validation.tools import TOOL_NAMES, ToolRun, build_tools


@pytest.fixture
def tools(ctx, golden):
    run = ToolRun()
    return {t.name: t for t in build_tools(golden["invoice_1002.txt"], ctx, run)}, run


def test_tool_names(tools):
    assert list(tools[0]) == TOOL_NAMES == [
        "lookup_item", "check_stock", "reconcile_math", "check_integrity", "check_duplicate",
        "check_payee_threshold", "check_vendor", "detect_prompt_injection", "fraud_signals", "check_prices",
        "report_finding"]


def test_check_tools_take_no_arguments(tools):
    by_name, _ = tools
    for name in TOOL_NAMES[:-1]:
        schema = by_name[name].tool_call_schema.model_json_schema()
        assert schema.get("required", []) == [] and schema.get("properties", {}) == {}, name


def test_check_tool_runs_its_check_and_records_it(tools):
    by_name, run = tools
    result = json.loads(by_name["check_stock"].invoke({}))
    assert [f["code"] for f in result] == ["STOCK_EXCEEDED"]
    assert list(run.results) == ["check_stock"]


def test_report_finding_schema(tools):
    by_name, run = tools
    schema = by_name["report_finding"].args_schema
    assert set(schema.model_json_schema()["required"]) == {"code", "severity", "message"}
    with pytest.raises(ValidationError):
        schema.model_validate({"code": "NOT_A_CODE", "severity": "INFO", "message": "x"})


def test_report_finding_caps_critical(tools):
    by_name, run = tools
    by_name["report_finding"].invoke({"code": "PRICE_VARIANCE", "severity": "CRITICAL", "message": "odd"})
    [f] = run.llm_findings
    assert (f.code, f.severity, f.source) == (FindingCode.PRICE_VARIANCE, Severity.WARNING, "llm")
