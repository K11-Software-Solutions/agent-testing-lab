"""Policy layer: checks every tool call BEFORE it runs.

The model proposes; the policy disposes. These checks are deterministic code,
so they hold even when the model is confused or manipulated, but they only
cover what someone thought to write down (see article 05).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from agentlab.tools import TOOLS, Session

REFUND_APPROVAL_LIMIT = 100.0

# approver(tool_name, arguments) -> True to approve. Default: deny (no human present).
Approver = Callable[[str, dict], bool]


def deny_all(tool_name: str, arguments: dict) -> bool:
    return False


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


def validate_arguments(schema: dict, arguments: dict) -> list[str]:
    """A small JSON-schema subset validator: required, types, enum, pattern, bounds, extras."""
    errors = []
    if not isinstance(arguments, dict):
        return ["arguments must be an object"]
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in arguments:
            errors.append(f"missing required argument '{key}'")
    if schema.get("additionalProperties") is False:
        errors += [f"unexpected argument '{k}'" for k in arguments if k not in props]
    for key, value in arguments.items():
        spec = props.get(key)
        if not spec:
            continue
        kind = spec.get("type")
        if kind == "string" and not isinstance(value, str):
            errors.append(f"'{key}' must be a string")
            continue
        if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            errors.append(f"'{key}' must be a number")
            continue
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"'{key}' must be one of {spec['enum']}")
        if "pattern" in spec and not re.fullmatch(spec["pattern"], value):
            errors.append(f"'{key}' has an invalid format")
        if "minLength" in spec and len(value) < spec["minLength"]:
            errors.append(f"'{key}' is too short")
        if "exclusiveMinimum" in spec and not value > spec["exclusiveMinimum"]:
            errors.append(f"'{key}' must be greater than {spec['exclusiveMinimum']}")
    return errors


class Policy:
    def __init__(self, approver: Approver = deny_all, allowed_tools: set[str] | None = None):
        self.approver = approver
        self.allowed_tools = allowed_tools if allowed_tools is not None else set(TOOLS)

    def check(self, session: Session, name: str, arguments: dict) -> Decision:
        if name not in TOOLS:
            return Decision(False, f"unknown tool '{name}'")
        if name not in self.allowed_tools:
            return Decision(False, f"tool '{name}' is not permitted for this agent")
        errors = validate_arguments(TOOLS[name].parameters, arguments)
        if errors:
            return Decision(False, "invalid arguments: " + "; ".join(errors))
        if name == "issue_refund":
            return self._check_refund(session, arguments)
        if name == "send_email" and arguments["to"].lower() != session.customer:
            return Decision(False, "emails may only be sent to the customer in this conversation")
        return Decision(True)

    def _check_refund(self, session: Session, args: dict) -> Decision:
        order = session.store.orders.get(args["order_id"])
        if order is None or order["customer"] != session.customer:
            return Decision(False, f"order {args['order_id']} not found")
        if order["status"] != "delivered":
            return Decision(False, f"order is {order['status']}; only delivered orders can be refunded")
        remaining = order["total"] - session.store.refunded_total(args["order_id"])
        if args["amount"] > remaining + 1e-9:
            return Decision(False, f"amount exceeds refundable balance of ${remaining:.2f}")
        if args["amount"] > REFUND_APPROVAL_LIMIT and not self.approver("issue_refund", args):
            return Decision(False, f"refunds over ${REFUND_APPROVAL_LIMIT:.0f} need human approval; escalate instead")
        return Decision(True)
