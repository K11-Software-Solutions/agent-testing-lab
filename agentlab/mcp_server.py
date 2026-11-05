"""Expose the same tools as a Model Context Protocol (MCP) server.

MCP is the open protocol many agents use to discover and call tools. Serving
our tools over MCP lets any MCP client use them, and lets us test the server
contract (tool list, schemas, errors, policy enforcement) independently of
any model. See tests/test_mcp_server.py.

Run over stdio:  python -m agentlab.mcp_server --customer ana@example.test
"""
from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError

from agentlab.policy import Policy
from agentlab.store import Store
from agentlab.tools import TOOLS, Session, ToolError


def build_server(session: Session, policy: Policy | None = None) -> MCPServer:
    policy = policy or Policy()
    server = MCPServer("shopassist")

    def guarded(name: str, **arguments):
        decision = policy.check(session, name, arguments)
        if not decision.allowed:
            raise MCPToolError(f"blocked by policy: {decision.reason}")
        try:
            return TOOLS[name].func(session, **arguments)
        except ToolError as exc:  # anticipated failure: pass the message to the client
            raise MCPToolError(str(exc)) from exc

    @server.tool(description=TOOLS["lookup_order"].description)
    def lookup_order(order_id: str) -> dict:
        return guarded("lookup_order", order_id=order_id)

    @server.tool(description=TOOLS["list_orders"].description)
    def list_orders() -> list[dict]:
        return guarded("list_orders")

    @server.tool(description=TOOLS["search_policy"].description)
    def search_policy(topic: str) -> str:
        return guarded("search_policy", topic=topic)

    @server.tool(description=TOOLS["issue_refund"].description)
    def issue_refund(order_id: str, amount: float, reason: str) -> dict:
        return guarded("issue_refund", order_id=order_id, amount=amount, reason=reason)

    @server.tool(description=TOOLS["send_email"].description)
    def send_email(to: str, subject: str, body: str) -> dict:
        return guarded("send_email", to=to, subject=subject, body=body)

    @server.tool(description=TOOLS["escalate_to_human"].description)
    def escalate_to_human(summary: str) -> dict:
        return guarded("escalate_to_human", summary=summary)

    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", default="ana@example.test")
    args = parser.parse_args()
    build_server(Session(args.customer, Store())).run()
