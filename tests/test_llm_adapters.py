"""Provider adapters tested with httpx.MockTransport: no network, no key."""
import json

import httpx
import pytest

from agentlab.llm import AnthropicAgentLLM, FakeAgentLLM, LLMError, OpenAIAgentLLM, get_llm

MESSAGES = [
    {"role": "user", "content": "status of A1001"},
    {"role": "assistant", "tool_call": {"id": "c1", "name": "lookup_order", "arguments": {"order_id": "A1001"}}},
    {"role": "tool", "tool_call_id": "c1", "name": "lookup_order", "content": "{\"status\": \"delivered\"}"},
]
TOOLS = [{"name": "lookup_order", "description": "d", "parameters": {"type": "object", "properties": {}}}]


def test_openai_request_mapping_and_tool_call_parsing():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
            {"id": "x1", "function": {"name": "issue_refund", "arguments": "{\"order_id\": \"A1001\"}"}}]}}]})

    action = OpenAIAgentLLM("k", transport=httpx.MockTransport(handler)).next_action("sys", MESSAGES, TOOLS, "ana@example.test")
    assert action.type == "tool_call" and action.name == "issue_refund" and action.id == "x1"
    assert seen["messages"][0]["role"] == "system" and "ana@example.test" in seen["messages"][0]["content"]
    assert seen["messages"][2]["tool_calls"][0]["function"]["arguments"] == "{\"order_id\": \"A1001\"}"
    assert seen["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "{\"status\": \"delivered\"}"}
    assert seen["tools"][0]["type"] == "function" and seen["temperature"] == 0


def test_openai_final_answer():
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "Hi"}}]}))
    assert OpenAIAgentLLM("k", transport=t).next_action("s", MESSAGES[:1], TOOLS, "a").content == "Hi"


def test_anthropic_request_mapping_and_tool_use_parsing():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"content": [
            {"type": "text", "text": "Let me check."},
            {"type": "tool_use", "id": "tu1", "name": "lookup_order", "input": {"order_id": "A1001"}}]})

    action = AnthropicAgentLLM("k", transport=httpx.MockTransport(handler)).next_action("sys", MESSAGES, TOOLS, "ana@example.test")
    assert action.type == "tool_call" and action.arguments == {"order_id": "A1001"} and action.id == "tu1"
    assert seen["messages"][1]["content"][0]["type"] == "tool_use"
    assert seen["messages"][2]["content"][0] == {"type": "tool_result", "tool_use_id": "c1", "content": "{\"status\": \"delivered\"}"}
    assert seen["tools"][0]["input_schema"] == TOOLS[0]["parameters"]


def test_provider_errors_are_wrapped():
    t = httpx.MockTransport(lambda r: httpx.Response(529))
    with pytest.raises(LLMError):
        AnthropicAgentLLM("k", transport=t).next_action("s", MESSAGES[:1], TOOLS, "a")


def test_get_llm(monkeypatch):
    monkeypatch.delenv("AGENT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert get_llm().name == "fake-agent:faithful"
    assert get_llm(behavior="loopy").name == "fake-agent:loopy"
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        get_llm("openai")
    with pytest.raises(ValueError):
        FakeAgentLLM("creative")
