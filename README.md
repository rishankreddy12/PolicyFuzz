# PolicyFuzz — SOP Divergence Auditor

PolicyFuzz takes a written policy, generates boundary-hugging test cases, has three
*independent* interpreter agents rule on each case with clause citations, measures where
their verdicts diverge, makes a **human adjudicate** the divergences, drafts clause
rewrites plus a decision table plus regression cases, and **re-runs the panel to prove
divergence dropped**.

## Scope

### Goals

- **G1.** Ingest one plain-text policy (≤ 20 KB, numbered clauses).
- **G2.** Produce ~30 boundary-targeted cases (accepted range 24–36).
- **G3.** Run **3 isolated interpreters × every case**; each returns verdict + clause citations + confidence.
- **G4.** Compute divergence **deterministically in Python** (not by an LLM); cluster divergent cases into loophole candidates.
- **G5.** **Human adjudication UI**: rule on each cluster (ALLOW / DENY / ESCALATE / SKIP).
- **G6.** Patcher drafts clause edits + decision table + sibling test cases; **human approves each edit**; patched policy saved as a *new* version.
- **G7.** Verifier re-runs the panel on the patched policy and reports the divergence delta and regressions.
- **G8.** Everything visible: every LLM call, state transition, and human action in an SQLite-backed event log shown in the UI.
- **G9.** A **fully deterministic, offline demo** (scripted provider) plus an optional **live mode** (Ollama).

### Non-goals (explicitly cut)

PDF/DOCX/OCR ingestion · multi-document cross-checking · multi-user auth/storage ·
embeddings or fancy clustering (LLM labels + deterministic validation) · hosted LLM
provider adapters · per-case rulings inside a cluster (rulings are per cluster) ·
statistical significance testing · LangGraph/agent frameworks · Docker · async job queue ·
deployment beyond `streamlit run`.

### Honesty rule

When `provider = scripted`, outputs are **replayed fixtures**. The UI shows a persistent
banner:

> *"Scripted demo mode: LLM outputs are replayed from fixtures. This demonstrates the
> pipeline, not model behaviour. Use Live mode (Ollama) for real divergence numbers."*

Numbers from scripted mode must never be presented as measured model results.

## Quickstart

```bash
# 1. Clone and install
git clone <repo-url> && cd policyfuzz
make install          # creates .venv and installs the package

# 2. Run tests
make test

# 3. Run the headless demo (scripted mode, no network needed)
make demo

# 4. Launch the interactive UI
make app
```

Requires **Python 3.11+**. No Ollama needed for the scripted demo.

## Policy Format Requirements

To ensure deterministic parsing, policies must conform to this format:
- Must be pure text.
- Must use top-level numeric sections (e.g., `1. Section Title`).
- Must use decimal clause numbering underneath (e.g., `1.1 Clause text...`).
- Blank lines and unrecognized formats before the first section are ignored.

Example:
```text
1. Returns Policy
1.1 Customers may return items within 30 days.
1.2 Used items cannot be returned.
```

## Demo

```bash
make demo
```

Runs a complete end-to-end pipeline in scripted (replay) mode: parses the demo policy,
generates 30 test cases, runs the 3-interpreter panel, detects divergence, applies
pre-configured rulings, patches the policy, and verifies that divergence dropped.

For the interactive demo, run `make app` and follow `docs/DEMO_SCRIPT.md`.

## Architecture

```
              ┌──────────── Streamlit UI (ui/app.py) ────────────┐
              │ stage tracker · matrix · loopholes · patch · verify│
              └──────▲──────────────────────────────┬─────────────┘
                     │ reads (SQLite)                │ calls
              ┌──────┴──────────────────────────────▼──────┐
              │           Orchestrator (state machine)      │
              └──┬──────┬───────┬────────┬───────┬──────┬──┘
                 │      │       │        │       │      │
           Parser CaseGen Interpreter Divergence Patcher Verifier
                 └──────┴───────┴───┬────┴───────┴──────┘
                                    │ structured_call()
                          ┌─────────┴─────────┐
                          │    LLMProvider     │
                          │ Scripted │ Ollama  │
                          └───────────────────┘
   SQLite: runs · clauses · cases · verdicts · clusters · rulings · patches · verifications · events
```

## Limits

- Divergence among LLM readers is a *signal* of ambiguity, not proof.
- Unanimous verdicts can still be wrong.
- This tool is not legal advice.
- Novelty is in the *application* (interpretation-divergence audit → human adjudication →
  regression loop), not in invention of new techniques.

## Testing

```bash
make test    # runs all unit, integration, and e2e tests (offline)
```

Tests use a `ScriptedProvider` (replay from fixtures) so they run without network or
Ollama. Live tests (Ollama) are gated behind `POLICYFUZZ_LIVE=1`.

## Layout

```
policyfuzz/                  # python package
├── config.py                # settings + constants
├── models.py                # Pydantic contracts
├── db.py                    # SQLite persistence
├── events.py                # event log
├── prompts.py               # prompt templates
├── llm/                     # LLM provider abstraction
├── agents/                  # parser, casegen, interpreter, divergence, patcher, verifier
├── patching.py              # edit application + diff
├── orchestrator.py          # state machine + human gates
├── report.py                # report + regression-case builders
└── ui/app.py                # Streamlit UI
fixtures/demo/               # demo policy + scripted LLM responses
scripts/                     # build_fixtures, run_demo, check_ollama
tests/                       # unit / integration / e2e
docs/                        # demo script
```

## Deviations

None.
