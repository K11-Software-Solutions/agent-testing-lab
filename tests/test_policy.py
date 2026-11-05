"""Policy tests: the deterministic guard around every tool call."""
import pytest

from agentlab.policy import Policy, validate_arguments
from agentlab.tools import TOOLS, issue_refund

REFUND_SCHEMA = TOOLS["issue_refund"].parameters


@pytest.mark.parametrize("args, error", [
    ({"order_id": "A1001", "amount": 10, "reason": "broken"}, None),
    ({"order_id": "A1001", "amount": 10}, "missing required argument 'reason'"),
    ({"order_id": "a1001", "amount": 10, "reason": "broken"}, "invalid format"),
    ({"order_id": "A1001", "amount": "10", "reason": "broken"}, "must be a number"),
    ({"order_id": "A1001", "amount": True, "reason": "broken"}, "must be a number"),
    ({"order_id": "A1001", "amount": 0, "reason": "broken"}, "greater than 0"),
    ({"order_id": "A1001", "amount": -5, "reason": "broken"}, "greater than 0"),
    ({"order_id": "A1001", "amount": 10, "reason": "x"}, "too short"),
    ({"order_id": "A1001", "amount": 10, "reason": "broken", "customer": "ben@example.test"}, "unexpected argument"),
])
def test_argument_validation(args, error):
    errors = validate_arguments(REFUND_SCHEMA, args)
    if error is None:
        assert errors == []
    else:
        assert any(error in e for e in errors), errors


def test_enum_validation():
    assert validate_arguments(TOOLS["search_policy"].parameters, {"topic": "warranty"})


@pytest.fixture
def policy():
    return Policy()


def test_unknown_and_forbidden_tools(ana):
    assert not Policy().check(ana, "delete_database", {}).allowed
    readonly = Policy(allowed_tools={"lookup_order", "list_orders", "search_policy"})
    decision = readonly.check(ana, "issue_refund", {"order_id": "A1001", "amount": 5, "reason": "test"})
    assert not decision.allowed and "not permitted" in decision.reason


@pytest.mark.parametrize("customer, order_id, amount, allowed, reason", [
    ("ana@example.test", "A1001", 45, True, ""),
    ("ana@example.test", "A1001", 45.01, False, "exceeds refundable balance"),
    ("ana@example.test", "A1002", 100, True, ""),                      # at the limit
    ("ana@example.test", "A1002", 100.01, False, "need human approval"),  # just over the limit
    ("ben@example.test", "B2001", 10, False, "only delivered orders"),
    ("cara@example.test", "C3001", 10, False, "only delivered orders"),
    ("ben@example.test", "A1001", 10, False, "not found"),             # someone else's order
])
def test_refund_rules(store, policy, customer, order_id, amount, allowed, reason):
    from agentlab.tools import Session
    decision = policy.check(Session(customer, store), "issue_refund",
                            {"order_id": order_id, "amount": amount, "reason": "customer request"})
    assert decision.allowed is allowed
    assert reason in decision.reason


def test_refund_balance_accounts_for_previous_refunds(ana, policy):
    issue_refund(ana, "A1001", 40, "partial")
    assert not policy.check(ana, "issue_refund", {"order_id": "A1001", "amount": 10, "reason": "again"}).allowed
    assert policy.check(ana, "issue_refund", {"order_id": "A1001", "amount": 5, "reason": "again"}).allowed


def test_human_approval_unlocks_large_refunds(ana):
    approved = []
    policy = Policy(approver=lambda name, args: approved.append(args) or True)
    assert policy.check(ana, "issue_refund", {"order_id": "A1002", "amount": 250, "reason": "faulty"}).allowed
    assert approved, "the approver must be consulted"


@pytest.mark.parametrize("to, allowed", [
    ("ana@example.test", True),
    ("ANA@example.test", True),
    ("attacker@evil.test", False),
    ("ben@example.test", False),
])
def test_email_only_to_signed_in_customer(ana, policy, to, allowed):
    assert policy.check(ana, "send_email", {"to": to, "subject": "s", "body": "b"}).allowed is allowed
