"""Tool contract tests: each tool on its own, no model involved."""
import pytest

from agentlab.store import Store
from agentlab.tools import (TOOLS, ToolError, TransientToolError, escalate_to_human, issue_refund,
                            list_orders, lookup_order, search_policy, send_email)


def test_every_tool_has_a_strict_schema_and_a_risk_level():
    for tool in TOOLS.values():
        assert tool.parameters["type"] == "object"
        assert tool.parameters["additionalProperties"] is False
        assert set(tool.parameters["required"]) <= set(tool.parameters["properties"])
        assert tool.risk in {"read", "write"}
        assert tool.description


def test_write_tools_are_exactly_the_ones_that_change_the_world():
    assert {n for n, t in TOOLS.items() if t.risk == "write"} == {"issue_refund", "send_email", "escalate_to_human"}


def test_lookup_own_order(ana):
    order = lookup_order(ana, "A1001")
    assert order["status"] == "delivered" and order["total"] == 45.0 and order["refunded"] == 0


def test_another_customers_order_looks_like_a_missing_order(ana):
    """Authorisation: do not reveal that B2001 exists."""
    with pytest.raises(ToolError, match="not found"):
        lookup_order(ana, "B2001")
    with pytest.raises(ToolError, match="not found"):
        lookup_order(ana, "Z9999")


def test_list_orders_only_returns_own_orders(ben):
    assert [o["order_id"] for o in list_orders(ben)] == ["B2001", "B2002"]


def test_untrusted_notes_are_returned_as_data(ben):
    assert "SYSTEM INSTRUCTION" in lookup_order(ben, "B2002")["customer_notes"]


def test_refund_changes_state(ana, store):
    issue_refund(ana, "A1001", 20, "damaged")
    assert store.side_effects()["refunds"] == [{"order_id": "A1001", "amount": 20.0}]
    assert lookup_order(ana, "A1001")["refunded"] == 20.0


def test_email_and_escalation_are_recorded(ana, store):
    send_email(ana, "ana@example.test", "Hi", "Body")
    assert escalate_to_human(ana, "needs help")["ticket"] == "T001"
    assert store.side_effects() == {"refunds": [], "emails_to": ["ana@example.test"], "escalated": True}


def test_unknown_policy_topic(ana):
    assert search_policy(ana, "warranty") == "No policy found for that topic."


def test_fault_injection_transient_then_success():
    store = Store(transient_failures={"lookup_order": 1})
    from agentlab.tools import Session
    s = Session("ana@example.test", store)
    with pytest.raises(TransientToolError):
        lookup_order(s, "A1001")
    assert lookup_order(s, "A1001")["order_id"] == "A1001"


def test_fault_injection_unavailable():
    from agentlab.tools import Session
    s = Session("ana@example.test", Store(unavailable_tools={"lookup_order"}))
    with pytest.raises(ToolError, match="unavailable"):
        lookup_order(s, "A1001")


def test_each_run_starts_from_a_fresh_store():
    a, b = Store(), Store()
    a.orders["A1001"]["status"] = "lost"
    assert b.orders["A1001"]["status"] == "delivered"
