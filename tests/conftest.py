import pytest

from agentlab.llm import Action
from agentlab.store import Store
from agentlab.tools import Session


class ScriptedLLM:
    """Returns a fixed list of actions, one per call. Lets loop tests control the model exactly."""

    name = "scripted"

    def __init__(self, actions: list[Action]):
        self.actions = list(actions)
        self.seen_messages: list[list[dict]] = []

    def next_action(self, system, messages, tools, customer):
        self.seen_messages.append([dict(m) for m in messages])
        return self.actions.pop(0) if self.actions else Action.final("(script exhausted)")


@pytest.fixture
def store() -> Store:
    return Store()


@pytest.fixture
def ana(store) -> Session:
    return Session("ana@example.test", store)


@pytest.fixture
def ben(store) -> Session:
    return Session("ben@example.test", store)
