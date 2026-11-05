"""Promptfoo provider: runs one agent conversation and returns the whole run as JSON.

The output includes the final reply, the tools attempted and the side effects,
so Promptfoo assertions can check behaviour, not just wording.
Test vars: `message` (rendered into the prompt) and `customer`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentlab.agent import Agent  # noqa: E402
from agentlab.llm import get_llm  # noqa: E402
from agentlab.store import Store  # noqa: E402


def call_api(prompt: str, options: dict, context: dict) -> dict:
    customer = (context.get("vars") or {}).get("customer", "ana@example.test")
    result = Agent(get_llm()).run(prompt, customer, Store())
    tools = [s.name for s in result.steps if s.kind in ("tool_call", "tool_error", "blocked")]
    return {"output": json.dumps({"final": result.final, "stopped": result.stopped_reason,
                                  "tools": tools, "side_effects": result.side_effects})}
