# Project: Autonomous Order Support Agent with Production-Grade Harness

A resume-ready capstone project demonstrating agent orchestration and harness engineering — the core skills for a Forward Deployed Engineer role.

---

## One-line pitch (for resume/LinkedIn)

> **Built an autonomous customer support agent with a production-grade harness — including tiered permissions, sandboxed tool execution, observability tracing, guardrails against unsafe actions, and an automated eval suite — using LangGraph and the Anthropic API.**

## Resume bullet points (pick 2-3, tailor to the role)

- Designed and implemented a LangGraph-based agent orchestration system with conditional routing, structured state management, and context compaction for long-running multi-step tasks
- Built a 3-tier, context-aware permission system (auto-approve / log-only / human-confirm) that dynamically escalates risk based on action context (e.g., order status, transaction history), preventing a known fraud pattern in a shipping-address-change scenario
- Engineered idempotent, retry-safe tools with structured error surfaces and exponential backoff, eliminating duplicate-action risk under network failure conditions
- Implemented full observability (structured tracing, per-step token/latency logging) and automated guardrails (loop detection, scope-classification) to catch and prevent agent drift and unsafe autonomous actions
- Built an automated evaluation pipeline combining programmatic checks and LLM-as-judge grading across 15+ scenarios, with a held-out test set to detect and prevent harness overfitting

---

## Architecture Overview

```
                    ┌─────────────────┐
                    │   User Message    │
                    └────────┬─────────┘
                             ▼
                  ┌──────────────────────┐
                  │  Permission/Guardrail  │◄──── checks before EVERY tool call
                  │        Layer           │
                  └──────────┬───────────┘
                             ▼
        ┌────────────────────────────────────────┐
        │            LangGraph State Machine        │
        │                                            │
        │   [call_model] ──► [route: tool_use?] │
        │        ▲                    │             │
        │        │                    ▼             │
        │   [call_tool] ◄──── [permission_check]  │
        │        │                                  │
        │        ▼                                  │
        │   [sandboxed execution]                   │
        └────────────────┬───────────────────────┘
                          ▼
              ┌───────────────────────┐
              │  Trace/Log Store        │──► used by eval suite
              └───────────────────────┘
```

## Tech Stack

| Layer | Tool |
|---|---|
| LLM | Anthropic API (Claude) |
| Orchestration | LangGraph |
| Sandboxing | Docker (simulated tool execution environment) |
| Data store | SQLite (mock order database) |
| Tracing/logging | Python `logging` + structured JSON, stored to file/SQLite |
| Eval framework | Custom Python (programmatic checks + LLM-as-judge calls) |

## Core Features (mapped to what you learned)

### 1. Agent Orchestration (LangGraph)
- State object tracks: conversation messages, current order context, iteration count, risk flags
- Nodes: `call_model`, `call_tool`, `permission_check`, `human_approval`
- Conditional edges route based on: does the model want a tool? is the tool high-risk? did permission get approved?

### 2. Tools (5 total, deliberately spanning risk tiers)
| Tool | Risk Tier | Key design property |
|---|---|---|
| `search_knowledge_base` | Auto | Read-only |
| `get_order` | Auto | Read-only |
| `cancel_order` | Context-dependent (auto if unshipped, confirm if shipped) | Idempotent via order-state check |
| `update_shipping_address` | Context-dependent (auto if unshipped + verified, confirm if shipped or address anomaly) | Fraud-pattern-aware tiering |
| `send_notification_email` | Log-only | Structured error surface, retry-safe |

### 3. Permission System
- Central `TOOL_RISK_TIERS` config + a `should_require_approval(tool, input, context)` function
- Fail-safe default: unknown tools default to "confirm"
- Demonstrates the shipping-address fraud pattern explicitly (this is your best talking point in an interview)

### 4. Sandboxing
- Each tool execution simulated as running in a Docker container with capped resources and no network access (or a real Docker call if you want to go further)
- Demonstrates understanding of blast-radius containment even at small scale

### 5. Observability
- Every run produces a structured trace: step number, model decision, tool called, duration, tokens used
- A human-readable trace printer for demoing (this is your "show, don't tell" artifact for interviews)

### 6. Guardrails
- Loop detection: same tool + same input called 3x → halt and flag
- Scope guardrail: a cheap secondary model call checks if responses stay within "order support" scope, blocks off-topic compliance (e.g., refuses creative writing requests)

### 7. Evaluation Suite
- 12-15 eval cases covering: happy path, shipped-order edge case, fraud-pattern address change, off-topic scope test, tool-failure/retry scenario
- Mix of programmatic grading (tool-call verification) and LLM-as-judge (response quality)
- Held-out subset (3-4 cases) never used during iteration — run once at the end to check for overfitting
- Output: a pass-rate report you can screenshot for a portfolio

---

## Suggested build order (hand this to Claude Code, one phase at a time)

1. Mock database + the 5 tools (no agent yet — just test tools work standalone)
2. Raw agent loop wired to tools (no LangGraph yet — confirm basic reasoning works)
3. Migrate to LangGraph state machine with conditional edges
4. Add permission layer + guardrails
5. Add tracing/logging
6. Build the eval suite last, once the system is stable enough to actually test meaningfully

## What makes this a *strong* resume project (not just a toy)

Most portfolio "AI agent" projects are a single LLM call with a tool or two — no permissions, no observability, no evals. This project's differentiator, and exactly what to say in an interview, is:

> "I didn't just build an agent that works on the happy path — I built the harness around it: permission tiers that adapt to context, guardrails that catch drift, and an eval suite that proves it works and catches regressions before they ship."

That sentence is the difference between "I used an LLM API" and "I understand how to deploy agents responsibly" — which is the actual FDE skill.

---

## Next step
Take this spec to Claude Code (or paste sections here if you want me to review/explain any part as you build), and build it phase by phase. Come back here anytime to explain a concept you hit a wall on — I'll stay on the conceptual/teaching side while Claude Code handles implementation.
