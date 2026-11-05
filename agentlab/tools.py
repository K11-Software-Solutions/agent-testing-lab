"""Tools the agent can call. Each has a JSON schema, a risk level and a function.

Read tools only look things up. Write tools change the world (money, email,
tickets), so the policy layer checks them before they run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agentlab.store import POLICY_TEXT, Store


class ToolError(Exception):
    """A tool failed permanently (bad input, not found, not allowed)."""


class TransientToolError(ToolError):
    """A tool failed in a way that may succeed on retry (timeout, 503)."""


@dataclass
class Session:
    """Who the agent is acting for. Tools never accept a customer id from the model."""
    customer: str
    store: Store


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    risk: str  # "read" | "write"
    func: Callable[..., Any]

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


def _fault_injection(session: Session, name: str) -> None:
    store = session.store
    if name in store.unavailable_tools:
        raise ToolError(f"{name} is unavailable (service down)")
    if store.transient_failures.get(name, 0) > 0:
        store.transient_failures[name] -= 1
        raise TransientToolError(f"{name} timed out")
    if store.failure_rate and store.rng.random() < store.failure_rate:
        raise TransientToolError(f"{name} returned 503 (random fault)")


def _own_order(session: Session, order_id: str) -> dict:
    order = session.store.orders.get(order_id)
    # Authorisation: another customer's order looks exactly like a missing one.
    if order is None or order["customer"] != session.customer:
        raise ToolError(f"order {order_id} not found")
    return order


def lookup_order(session: Session, order_id: str) -> dict:
    _fault_injection(session, "lookup_order")
    order = _own_order(session, order_id)
    return {"order_id": order_id, "item": order["item"], "total": order["total"], "status": order["status"],
            "refunded": session.store.refunded_total(order_id), "customer_notes": order["notes"]}


def list_orders(session: Session) -> list[dict]:
    _fault_injection(session, "list_orders")
    return [{"order_id": oid, "item": o["item"], "status": o["status"]}
            for oid, o in sorted(session.store.orders.items()) if o["customer"] == session.customer]


def search_policy(session: Session, topic: str) -> str:
    _fault_injection(session, "search_policy")
    return POLICY_TEXT.get(topic, "No policy found for that topic.")


def issue_refund(session: Session, order_id: str, amount: float, reason: str) -> dict:
    _fault_injection(session, "issue_refund")
    _own_order(session, order_id)
    refund = {"order_id": order_id, "amount": round(float(amount), 2), "reason": reason}
    session.store.refunds.append(refund)
    return {"status": "refunded", **refund}


def send_email(session: Session, to: str, subject: str, body: str) -> dict:
    _fault_injection(session, "send_email")
    session.store.emails.append({"to": to, "subject": subject, "body": body})
    return {"status": "sent", "to": to}


def escalate_to_human(session: Session, summary: str) -> dict:
    _fault_injection(session, "escalate_to_human")
    ticket = f"T{len(session.store.escalations) + 1:03d}"
    session.store.escalations.append({"ticket": ticket, "summary": summary})
    return {"status": "escalated", "ticket": ticket}


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


ORDER_ID = {"type": "string", "pattern": "^[A-Z][0-9]{4}$", "description": "Order number, e.g. A1001"}

TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("lookup_order", "Look up one of the current customer's orders by order number.",
         _schema({"order_id": ORDER_ID}, ["order_id"]), "read", lookup_order),
    Tool("list_orders", "List the current customer's orders.", _schema({}, []), "read", list_orders),
    Tool("search_policy", "Read store policy on a topic.",
         _schema({"topic": {"type": "string", "enum": sorted(POLICY_TEXT)}}, ["topic"]), "read", search_policy),
    Tool("issue_refund", "Refund money for a delivered order. Moves real money.",
         _schema({"order_id": ORDER_ID, "amount": {"type": "number", "exclusiveMinimum": 0},
                  "reason": {"type": "string", "minLength": 3}}, ["order_id", "amount", "reason"]),
         "write", issue_refund),
    Tool("send_email", "Send an email to the current customer.",
         _schema({"to": {"type": "string"}, "subject": {"type": "string", "minLength": 1},
                  "body": {"type": "string", "minLength": 1}}, ["to", "subject", "body"]),
         "write", send_email),
    Tool("escalate_to_human", "Hand the conversation to a human support agent.",
         _schema({"summary": {"type": "string", "minLength": 5}}, ["summary"]), "write", escalate_to_human),
]}
