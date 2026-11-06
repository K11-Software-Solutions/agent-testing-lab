# Agent Testing Lab

[![CI quality gates](https://github.com/K11-Software-Solutions/agent-testing-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/K11-Software-Solutions/agent-testing-lab/actions/workflows/ci.yml)
[![Code: MIT](https://img.shields.io/badge/Code-MIT-blue.svg)](LICENSE) [![Articles: CC BY 4.0](https://img.shields.io/badge/Articles-CC%20BY%204.0-lightgrey.svg)](articles/LICENSE.md)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![No API key needed](https://img.shields.io/badge/API%20key-not%20required-success)

**Test an AI agent that takes real actions: its tools, its permissions, its trajectories, its resistance to prompt injection, and its reliability when tools fail. Then gate it in CI.**

This is the third lab in a series for quality engineers moving into AI:

| Lab | Layer under test |
|---|---|
| [Becoming an AI Quality Engineer](https://github.com/K11-Software-Solutions/becoming-ai-quality-engineer) | a RAG **application** |
| [LLM Model Testing Lab](https://github.com/K11-Software-Solutions/llm-model-testing-lab) | the **model** itself |
| **Agent Testing Lab** (this repo) | an **agent**: an LLM in a loop that calls tools and changes the world |

## The system under test

**ShopAssist**, a customer-support agent for a fictional store. It can look up and list orders, read policy, **issue refunds**, **send emails** and **escalate to a human**. A deterministic policy layer enforces refund limits, human approval above $100, delivered-only refunds, per-customer authorisation and email-recipient restrictions. One order's notes contain a **planted prompt injection**. The same tools are also served over **MCP**.

The agent runs on a **deterministic fake model** with four behaviours, so tests and CI need no API key. OpenAI and Anthropic tool-calling adapters are included for real-model runs.

| Fake behaviour | What it does | What catches it |
|---|---|---|
| `faithful` | follows the rules | (the baseline) |
| `injectable` | obeys instructions hidden in tool results | unsafe-action and injection gates |
| `reckless` | acts without looking up, guesses amounts, claims success | trajectory and false-claim gates |
| `loopy` | repeats the same call forever | loop detection and completion gate |

## Articles

| # | Article |
|---|---|
| 01 | [What Changes When the AI Can Act](articles/01-what-changes-when-ai-can-act.md) |
| 02 | [Anatomy of a Testable Agent](articles/02-anatomy-of-a-testable-agent.md) |
| 03 | [Testing Tools, Contracts and MCP](articles/03-testing-tools-contracts-and-mcp.md) |
| 04 | [Evaluating Trajectories and Outcomes](articles/04-evaluating-trajectories-and-outcomes.md) |
| 05 | [Safety: Permissions, Approvals and Injection](articles/05-safety-permissions-approvals-and-injection.md) |
| 06 | [Reliability and pass^k](articles/06-reliability-and-pass-hat-k.md) |
| 07 | [CI Gates and Negative Controls](articles/07-ci-gates-and-negative-controls.md) |
| 08 | [Investigating Agent Failures](articles/08-investigating-agent-failures.md) |

## Quick start

Requirements: Python 3.11+. Node.js 22.22+ only for Promptfoo.

```bash
git clone https://github.com/K11-Software-Solutions/agent-testing-lab.git
cd agent-testing-lab
python -m venv .venv
source .venv/bin/activate              # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

```bash
pytest                                                   # tools, policy, loop, adapters, MCP, scorer (~1 s)
python -m evals.run_agent_evals                          # scenarios + pass^k reliability + gates
FAKE_AGENT_BEHAVIOR=injectable python -m evals.run_agent_evals   # watch the gates catch it
npx promptfoo@0.124.0 eval -c evals/promptfoo/promptfooconfig.yaml
python -m agentlab.mcp_server --customer ana@example.test   # serve the tools over MCP (stdio)
```

Real model: `AGENT_LLM_PROVIDER=openai` (or `anthropic`) plus the matching API key, then `python -m evals.run_agent_evals --no-gate`.

## Repository layout

```text
agentlab/
  store.py         in-memory world (orders, refunds, emails, escalations) + fault injection
  tools.py         tools with JSON schemas and risk levels
  policy.py        deterministic checks before every call: schema, limits, approvals, authorisation
  agent.py         the loop: limits, retries, loop detection, trajectory recording
  llm.py           FakeAgentLLM (4 behaviours) + OpenAI and Anthropic tool-calling adapters
  mcp_server.py    the same tools over the Model Context Protocol, policy enforced server-side
evals/
  scenarios.jsonl  17 scenarios: happy path, policy, authorisation, clarification, escalation, injection, reliability
  run_agent_evals.py   scoring (world state, trajectory, reply, honesty), pass@k / pass^k, gates
  thresholds.json  hard safety gates + quality and reliability floors
  promptfoo/       Promptfoo provider and behaviour suite
tests/             66 deterministic tests, no model and no network
articles/          the eight articles
.github/workflows/ci.yml   tests → evals with 3 negative controls + Promptfoo with a negative control
```

## What the lab finds

- **Every policy rule was correct, and an injected $80 refund still went through,** because no rule says "the customer did not ask for this". Evaluations on world state caught it.
- **Words lie, state doesn't.** The reckless agent's replies all sound successful; six describe refunds that never happened.
- **pass@k hides unreliability.** Under fault injection every scenario *can* succeed, but over ten trials none succeeds *every* time.
- **Fault injection finds bugs.** Reliability trials surfaced a crash on an error result and a false "confirmation sent" message.
- **Contracts drift.** The MCP server advertises a weaker schema than the policy enforces.
- **Paraphrases break routing.** "Can I get $20 back?" is handled as a status question: a documented known failure.

## Limitations

The fake model is a rule system (great for deterministic CI, not a stand-in for real model behaviour); 17 scenarios is a smoke test; one injection channel; single-agent, single-turn; no idempotency keys yet. [Article 08](articles/08-investigating-agent-failures.md#5-limitations-to-state) covers each one.

## About

Created by **Kavita Jadhav**, founder of [K11 Software Solutions](https://github.com/K11-Software-Solutions), Senior SDET and AI Quality Engineer working on LLM evaluation, red teaming and agentic QA systems.

**Licences:** code under the [MIT License](LICENSE); the written material in [`articles/`](articles/LICENSE.md) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (share and adapt with credit).

ShopAssist, its customers and its orders are fictional.

## Citing

Use GitHub's **Cite this repository** button (from [`CITATION.cff`](CITATION.cff)). Each tagged release is archived on Zenodo with its own DOI; cite the version you used, or the concept DOI for the project as a whole. The DOI badge will appear here after the first release.
