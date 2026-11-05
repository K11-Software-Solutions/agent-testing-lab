# 03. Testing Tools, Contracts and MCP

> **Series:** Agent Testing Lab · [Index](../README.md#articles) · Previous: [02](02-anatomy-of-a-testable-agent.md) · Next: [04. Evaluating Trajectories and Outcomes](04-evaluating-trajectories-and-outcomes.md)

Most agent bugs that reach production are not "the model was clever in a bad way". They are ordinary bugs in tools, schemas, permissions and error handling. Those can be tested deterministically, without a model, and that is where to start.

```bash
pytest -v      # 66 tests, under 2 seconds
```

## 1. Tool contract tests ([`tests/test_tools.py`](../tests/test_tools.py))

Treat each tool like an API endpoint:

- **Schema hygiene:** every tool declares an object schema with `additionalProperties: false`, required fields that exist, a description and a risk level.
- **Risk classification:** exactly the tools that change the world are marked `write`. If someone adds a write tool and forgets to mark it, this test fails.
- **Authorisation:** another customer's order behaves exactly like a missing order.
- **Untrusted data is returned as data:** the injected order note is present in the result. The defence belongs elsewhere, and hiding the data in tests would hide the risk.
- **State changes are visible:** a refund appears in `side_effects()`, and refunded balances are tracked.
- **Fault injection works:** transient failures recover; unavailable tools fail permanently.
- **Isolation:** each run starts from a fresh store.

## 2. Policy tests ([`tests/test_policy.py`](../tests/test_policy.py))

The policy layer is where boundary-value analysis pays off:

| Case | Expected |
|---|---|
| refund $45.00 of a $45 order | allowed |
| refund $45.01 of a $45 order | blocked: exceeds balance |
| refund $100.00 (at the approval limit) | allowed |
| refund $100.01 | blocked: needs human approval |
| refund a shipped or processing order | blocked |
| refund someone else's order | blocked: not found |
| `amount: "10"`, `amount: true`, `amount: 0`, `amount: -5` | blocked: type or bounds |
| an extra `customer` argument | blocked: unexpected argument |
| email to `ANA@example.test` | allowed (case-insensitive) |
| email to `attacker@evil.test` | blocked |

`amount: true` matters: in Python `True` is an integer, and a naive type check would accept it.

Also tested: previous refunds reduce the refundable balance, and a human approver *is consulted* for large refunds and can unlock them.

## 3. Agent loop tests with a scripted model ([`tests/test_agent_loop.py`](../tests/test_agent_loop.py))

A `ScriptedLLM` returns a fixed list of actions, so loop behaviour can be tested exactly:

- tool results are fed back to the model in the right format;
- **blocked calls never execute**, and the model receives the reason;
- `max_steps` and loop detection stop runaway agents;
- transient errors are retried, but retries are bounded, and the model is told an error is retryable;
- permanent tool errors are reported to the model, not raised;
- the model cannot choose whose account it acts on;
- trajectories serialise to JSON for storage and review.

## 4. Provider adapter tests ([`tests/test_llm_adapters.py`](../tests/test_llm_adapters.py))

OpenAI and Anthropic use different tool-calling formats. Mapping bugs (a lost tool-call ID, arguments sent as an object instead of a JSON string, a tool result sent with the wrong role) break agents in confusing ways. `httpx.MockTransport` captures the outgoing request and returns canned responses, so these tests run offline with no key.

## 5. MCP server contract tests ([`tests/test_mcp_server.py`](../tests/test_mcp_server.py))

The **Model Context Protocol** lets agents discover and call tools from separate servers. An MCP server is an API, and it deserves contract tests. The MCP Python SDK can connect a client to a server in-process, so these tests need no network:

- the server advertises exactly our tools;
- each advertised tool's required arguments match the internal schema;
- successful calls return JSON content;
- the policy is **enforced behind MCP**: a $250 refund comes back as an error and the store is unchanged;
- authorisation errors return `is_error=True` with a useful message rather than a crash.

### A real finding: the advertised schema is weaker than the real one

The server builds its advertised schema from Python type hints, so the constraints in our internal schema (the order-ID pattern, minimum lengths, `amount > 0`) are **not advertised** to clients. The policy still enforces them on the server, so nothing unsafe gets through, but a client cannot see the rules and will learn them only by failing. The test `test_known_contract_gap_constraints_are_not_advertised` documents the gap instead of hiding it. Closing it with `Annotated[..., Field(pattern=...)]` is an exercise.

**Lesson:** when the same tool is defined in two places, test that the definitions agree. Schema drift between layers is a classic integration bug.

---
Next: [04. Evaluating Trajectories and Outcomes](04-evaluating-trajectories-and-outcomes.md)
