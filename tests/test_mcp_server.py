"""MCP server contract tests, using the SDK's in-process client (no network)."""
import asyncio
import json

from mcp import Client

from agentlab.mcp_server import build_server
from agentlab.store import Store
from agentlab.tools import TOOLS, Session


def run(coro):
    return asyncio.run(coro)


async def _list(session):
    async with Client(build_server(session)) as client:
        return (await client.list_tools()).tools


async def _call(session, name, args):
    async with Client(build_server(session)) as client:
        return await client.call_tool(name, args)


def ana():
    return Session("ana@example.test", Store())


def test_server_advertises_exactly_our_tools():
    assert sorted(t.name for t in run(_list(ana()))) == sorted(TOOLS)


def test_advertised_required_arguments_match_internal_schemas():
    for tool in run(_list(ana())):
        assert sorted(tool.input_schema.get("required", [])) == sorted(TOOLS[tool.name].parameters["required"]), tool.name


def test_known_contract_gap_constraints_are_not_advertised():
    """Documented finding: type hints alone drop our pattern/minLength constraints from the
    MCP schema. The policy still enforces them server-side (next test), but a client cannot
    see them. Fixing this (e.g. with Annotated[..., Field(pattern=...)]) is an exercise."""
    refund = next(t for t in run(_list(ana())) if t.name == "issue_refund")
    assert "pattern" not in refund.input_schema["properties"]["order_id"]


def test_successful_call_returns_json_content():
    result = run(_call(ana(), "lookup_order", {"order_id": "A1001"}))
    assert result.is_error is False
    assert json.loads(result.content[0].text)["item"] == "desk lamp"


def test_policy_is_enforced_behind_mcp():
    session = ana()
    result = run(_call(session, "issue_refund", {"order_id": "A1002", "amount": 250, "reason": "faulty"}))
    assert result.is_error is True and "human approval" in result.content[0].text
    assert session.store.refunds == []


def test_invalid_arguments_rejected_by_policy_behind_mcp():
    result = run(_call(ana(), "lookup_order", {"order_id": "not-an-id"}))
    assert result.is_error is True and "invalid format" in result.content[0].text


def test_authorisation_error_is_returned_as_tool_error():
    result = run(_call(ana(), "lookup_order", {"order_id": "B2001"}))
    assert result.is_error is True and "not found" in result.content[0].text
