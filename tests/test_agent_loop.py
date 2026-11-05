"""Agent loop tests with a scripted model: control flow, limits, retries, trajectories."""
import json

from agentlab.agent import Agent
from agentlab.llm import Action
from agentlab.store import Store
from tests.conftest import ScriptedLLM

ANA = "ana@example.test"


def test_final_answer_ends_the_run():
    result = Agent(ScriptedLLM([Action.final("hello")])).run("hi", ANA)
    assert result.final == "hello" and result.stopped_reason == "final" and result.tool_calls == []


def test_tool_results_are_fed_back_to_the_model():
    llm = ScriptedLLM([Action.call("lookup_order", order_id="A1001"), Action.final("ok")])
    Agent(llm).run("status of A1001", ANA)
    tool_msg = llm.seen_messages[1][-1]
    assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["item"] == "desk lamp"


def test_blocked_calls_do_not_execute_and_the_model_is_told_why():
    llm = ScriptedLLM([Action.call("send_email", to="attacker@evil.test", subject="x", body="y"), Action.final("ok")])
    store = Store()
    result = Agent(llm).run("hi", ANA, store)
    assert store.emails == []
    assert result.blocked[0].name == "send_email"
    feedback = json.loads(llm.seen_messages[1][-1]["content"])
    assert feedback["error"] == "blocked by policy" and "only be sent to the customer" in feedback["reason"]


def test_max_steps_stops_a_run_that_never_finishes():
    llm = ScriptedLLM([Action.call("search_policy", topic=t) for t in ["refund", "shipping", "returns"] * 5])
    result = Agent(llm, max_steps=4).run("hi", ANA)
    assert result.stopped_reason == "max_steps"
    assert len(result.tool_calls) == 4


def test_loop_detection_stops_repeated_identical_calls():
    llm = ScriptedLLM([Action.call("lookup_order", order_id="A1001")] * 10)
    result = Agent(llm, loop_limit=3).run("hi", ANA)
    assert result.stopped_reason == "loop_detected"
    assert len(result.tool_calls) == 2


def test_transient_errors_are_retried():
    store = Store(transient_failures={"lookup_order": 2})
    llm = ScriptedLLM([Action.call("lookup_order", order_id="A1001"), Action.final("ok")])
    result = Agent(llm, max_retries=2).run("hi", ANA, store)
    kinds = [s.kind for s in result.steps]
    assert kinds == ["retry", "retry", "tool_call", "final"]


def test_retries_are_bounded():
    store = Store(transient_failures={"lookup_order": 5})
    llm = ScriptedLLM([Action.call("lookup_order", order_id="A1001"), Action.final("ok")])
    result = Agent(llm, max_retries=2).run("hi", ANA, store)
    assert [s.kind for s in result.steps].count("retry") == 2
    assert result.tool_calls[0].kind == "tool_error"
    assert json.loads(llm.seen_messages[1][-1]["content"])["retryable"] is True


def test_permanent_tool_errors_are_reported_not_raised():
    llm = ScriptedLLM([Action.call("lookup_order", order_id="Z9999"), Action.final("ok")])
    result = Agent(llm).run("hi", ANA)
    assert result.tool_calls[0].kind == "tool_error" and "not found" in result.tool_calls[0].detail


def test_model_cannot_choose_whose_account_it_acts_on():
    """The customer comes from the session, never from model-chosen arguments."""
    llm = ScriptedLLM([Action.call("list_orders", customer="ben@example.test"), Action.final("ok")])
    result = Agent(llm).run("hi", ANA)
    assert result.blocked and "unexpected argument" in result.blocked[0].detail


def test_trajectory_serialises_to_json():
    llm = ScriptedLLM([Action.call("lookup_order", order_id="A1001"), Action.final("ok")])
    data = json.loads(json.dumps(Agent(llm).run("hi", ANA).to_dict()))
    assert [s["kind"] for s in data["steps"]] == ["tool_call", "final"]
