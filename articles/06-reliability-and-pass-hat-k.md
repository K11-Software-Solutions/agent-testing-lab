# 06. Reliability and pass^k

> **Series:** Agent Testing Lab · [Index](../README.md#articles) · Previous: [05](05-safety-permissions-approvals-and-injection.md) · Next: [07. CI Gates and Negative Controls](07-ci-gates-and-negative-controls.md)

Agents depend on tools, and tools fail: timeouts, rate limits, 503s, partial outages. An agent that works when everything is up is a demo. A product has to behave sensibly when things break.

## 1. Fault injection

The store can inject three kinds of failure:

```python
Store(transient_failures={"lookup_order": 2})   # first two calls time out, then succeed
Store(unavailable_tools={"lookup_order"})        # permanent outage
Store(failure_rate=0.5, rng=random.Random(seed)) # each call fails with probability 0.5
```

Deterministic scenarios cover the first two:

- `reliab-01`: two timeouts, then success. The loop retries and the refund still completes.
- `reliab-02`: the order system is down. The agent must **not guess**; it apologises and escalates to a human.

## 2. pass@k versus pass^k

With random faults, one run tells you little. Run each scenario *k* times with different seeds and report two numbers:

- **pass@k:** the share of scenarios that succeeded **at least once** in k trials. This is how code-generation benchmarks report results: it measures what the agent *can* do.
- **pass^k** ("pass hat k"): the share of scenarios that succeeded in **all k** trials. This is the metric popularised by agent benchmarks such as τ-bench (Yao et al., 2024): it measures what the agent does *reliably*, which is what a customer experiences.

Results for the faithful agent, with a 50% per-call failure rate and up to two retries per call (at time of writing):

| k | pass@k | pass^k | Trial success rate |
|---|---|---|---|
| 5 | 1.0 | 0.5 | 0.73 |
| 10 | 1.0 | **0.0** | 0.70 |

Every scenario *can* succeed (pass@k stays at 1.0), but with ten trials **not one scenario succeeds every time**. Scenarios with more tool calls (refund and confirm) degrade fastest, because each extra call is another chance to fail. Reporting only pass@k, or a single run, would hide this completely.

## 3. Two bugs that only reliability trials found

**Bug 1: a crash on an error result.** The first time the trials ran, the agent crashed. When `list_orders` still failed after its retries, the result was an error object, and the code that formats the order list expected a list. No deterministic scenario had made `list_orders` fail, so nothing else caught it. The fix was twofold: handle error results in every branch, and contain model exceptions in the loop (`stopped_reason="model_error"`) so a bug in one conversation cannot take down the service. Both have tests.

**Bug 2: a false confirmation.** Reviewing the same code path showed a sibling bug: if the refund succeeded but the confirmation email failed, the reply still said "and emailed you a confirmation". The scorer now checks for this (`claims_unsent_email`), and the agent reports the failed email honestly.

**Lesson:** fault injection is not only for measuring reliability. It is one of the best bug-finding techniques for agents, because error paths are where untested code lives.

## 4. Designing for reliability (what to look for in reviews)

- **Retries with limits**, only for errors that are actually transient.
- **Idempotency** for write tools: a retried refund must not refund twice. (This lab retries only before a write succeeds; adding idempotency keys is an exercise.)
- **Graceful degradation:** escalate or apologise rather than guess.
- **Honest replies about partial failure.**
- **Budgets:** step, time and cost limits that hold under retries.

## Try it

```bash
python -m evals.run_agent_evals --k 10 --no-gate
python -m evals.run_agent_evals --failure-rate 0.2 --no-gate
```

How does pass^k change with the failure rate? What retry count would you need for pass^10 ≥ 0.9 at a 20% failure rate?

---
Next: [07. CI Gates and Negative Controls](07-ci-gates-and-negative-controls.md)
