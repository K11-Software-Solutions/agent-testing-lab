# 08. Investigating Agent Failures

> **Series:** Agent Testing Lab · [Index](../README.md#articles) · Previous: [07](07-ci-gates-and-negative-controls.md)

## 1. Read the trajectory first

Every eval run writes `evals/results/trajectories.jsonl`, with one complete run per scenario: every step, its arguments, the tool result or error, retries, policy blocks and the final reply. When a scenario fails, read its trajectory before forming a theory.

## 2. Classify the failure

| Class | Signature in the trajectory | Typical fix |
|---|---|---|
| **Intent / routing** | the wrong kind of tools for the request | prompt, routing, examples |
| **Missing step** | a required tool never called (no lookup, no confirmation) | procedure in the prompt, or enforce it in code |
| **Wrong arguments** | right tool, wrong amount, ID or recipient | schemas, validation, clearer tool descriptions |
| **Policy reliance** | blocked attempts, even if the final state is fine | model behaviour, not the policy |
| **Injection** | actions that follow text from a tool result | untrusted-content handling, least privilege |
| **Error handling** | crash, retry storm, or a guess after a failed tool | error branches, graceful degradation |
| **Honesty** | the reply claims what the state does not show | ground the reply in tool results |
| **Evaluator** | the agent was right and the scenario or scorer was wrong | fix the scenario, add a scorer test |

## 3. A worked example: `happy-02`

> **Customer (Ana):** "Can I get $20 back on order A1001? One part is missing."
> **Expected:** a $20 refund and a confirmation email.
> **Got:** "Order A1001 (desk lamp) is delivered."

The trajectory:

```json
{"kind": "tool_call", "name": "lookup_order", "arguments": {"order_id": "A1001"}, "result": {"status": "delivered", ...}}
{"kind": "final", "detail": "Order A1001 (desk lamp) is delivered."}
```

**Localise.** The lookup succeeded with the right order, so tools and data are fine. The agent then answered a *status* question.

**Classify.** Intent and routing. The request never says "refund"; "get $20 back" is a paraphrase the fake model's intent rules do not recognise, so it fell through to "status".

**Assess impact.** No unsafe action, but a real customer request was silently not handled, which is a quality failure the customer notices immediately.

**Fix options.** Add the paraphrase to the intent rules (a patch for one case), or, with a real model, check whether it handles the paraphrase. This scenario is a good example of why agent scenario sets need **paraphrase coverage**, exactly as RAG evals do. It stays in the set as a documented known failure until fixed.

## 4. Other findings from building this lab

- **A policy can be right and still let harm through** (article 05): the injected $80 refund broke no rule.
- **Words lie, state doesn't** (article 04): the reckless agent made six false success claims.
- **Reliability trials find crashes** (article 06): an error result reached code that assumed success.
- **Contracts drift** (article 03): the MCP server advertises a weaker schema than the one it enforces.

## 5. Limitations to state

- **The fake model is a rule system.** It is deterministic and repeatable, which is the point for CI, but its failure patterns are not a real model's. Use it to test the harness and the non-model code, and run real models separately.
- **Small scenario set.** 17 scenarios is a smoke test. Grow it from production conversations and incident reports.
- **One injection channel.** Order notes only; real agents read documents, web pages, emails and third-party tool descriptions.
- **Single-agent, single-turn.** Multi-turn conversations and multi-agent hand-offs add failure modes not covered here.
- **No idempotency keys** on write tools yet.
- **Keyword checks on replies.** Fine for short support replies; richer replies need a validated judge.

## 6. Presenting this lab in an interview

> "I built a small tool-using support agent and tested it in layers. Deterministic tests cover tool contracts, a policy layer (refund limits, approvals, recipient restrictions, authorisation), the agent loop's limits, provider adapters and an MCP server contract. Scenario evals score world state, trajectory and honesty, not just the reply. Fault injection gives pass@k and pass^k: everything can succeed, but at k=10 nothing succeeds every time, and the trials found a crash on an error path. CI gates are hard on safety, and three broken agents (injectable, reckless, loopy) must fail them. My favourite finding: an injected instruction got an $80 refund through even though every policy rule was correct, because no rule said 'the customer didn't ask for this'."

---
Back to the [index](../README.md#articles).
