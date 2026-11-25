# Implementation Plan: Slice 1b, Tracing

## Overview

Send one masked trace per coach call to Langfuse cloud (tokens, latency, prompt version, hash, session id) behind an explicit off-by-default switch, and move the LangSmith "never on" guard into the engine so every door gets it.

## Architecture & Design

A new `app/coach/tracing/` package holds a small tracing object built from the new `langfuse` settings group. It hands Coach LangChain callbacks and a flush. `build_coach` builds it only when enabled, and always forces LangSmith off. Coach passes the callbacks and per-call metadata (version, hash, model, session id, turn) to its existing `stream` call and gains `close()`. Masking is one pure function registered with the Langfuse client's export-stage hook: it keeps an allowlist of attributes, sets input and output to a placeholder and deletes everything else, error text included.

## Approaches Considered

Findings from reading the installed SDK (Langfuse 5.2.0): it exports OpenTelemetry spans, has an input/output `mask`, a whole-batch export-stage `mask_otel_spans` that drops the batch if it raises or returns something invalid, and a `span_exporter` argument usable as a test sink.

| Approach | Trade-offs | Chosen? |
|----------|-----------|---------|
| A. Export-stage allowlist only | One layer, one pure function, fails closed by SDK design. Text exists in process memory until export, never leaves. Cannot patch span events or status description (see risks). | **Yes**: user-confirmed. Leanest design that meets FR8/FR9 (ponytail). |
| B. A + early input/output `mask` | Text never sits in span memory, but two maskers must agree. | No: extra layer, no new guarantee about what leaves the machine. |
| C. Subclass the Langfuse LangChain handler | Strongest at source, couples to handler internals that change per version. | No: fragile across upgrades. |

Wiring: user chose a tracing object plus `Coach.close()` over callbacks-only with `atexit` (explicit, testable, works with Ctrl-C paths).

## Spec Requirements -> Implementation

- FR1, FR2 (settings, enable flag) -> Step 2
- FR3 (missing key stops startup) -> Step 4
- FR4, FR5, FR7 (trace per call, allowed fields, same sources as `llm_call`) -> Steps 5, 6
- FR6 (session id, rotates on reset) -> Step 5
- FR8, FR9, FR10 (mask everything, fail closed, no debug mode) -> Steps 3, 6
- FR11 (Langfuse failure never affects a turn) -> Steps 4, 6
- FR12 (flush with 5 s cap) -> Steps 4, 5, 8
- FR13 (LangSmith forced off, CLI line removed) -> Steps 4, 7, 8

## Implementation Steps

Checkpoint interval: none.

Gate commands (run after every step): `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run python -m app.scripts.prompts check`. In Git Bash prefix pytest with `env -u API_V1_PREFIX`.

1. **Spike (throwaway, nothing committed)** — Files: a scratch script in the scratchpad only; `pyproject.toml` and `uv.lock` change via `uv add langfuse` — Verify: findings written into `task.md`, then gate commands — Test: skip (exploration; the later steps carry the tests). Must answer: (a) does `mask_otel_spans` run when a `span_exporter` is injected; (b) the exact exported attribute keys for a Coach-shaped call, to fix the allowlist; (c) do span events or the OTel status description carry error text, which the hook cannot patch; (d) can the call outcome (cancelled, blocked) be attached to the trace, and how; (e) do streamed usage numbers reach the trace; (f) does constructing the client touch the network; (g) the client is shared per public key, so tests need distinct keys or a reset; (h) how SDK failures are logged and how often.
2. **Settings group** — Files: `app/core/config/langfuse.py`, `app/core/config/settings.py`, `.env.example`, `tests/test_config.py` — Verify: `uv run pytest tests/test_config.py` + gates — Test: first (seam 4). Prefix `LANGFUSE_`: enabled (default false), public and secret keys (`SecretStr`), base_url (default cloud). Group registered in `Settings` and `load_settings()`. `.env.example` gets a section and a pointer from the LangSmith note.
3. **Mask function** — Files: `app/coach/tracing/__init__.py`, `app/coach/tracing/tracing_masking.py`, `tests/coach/tracing/test_tracing_masking.py` — Verify: `uv run pytest tests/coach/tracing/test_tracing_masking.py` + gates — Test: first (seam 1). Thin slices: allowlisted attributes pass; input and output become the placeholder; error status text is removed; unknown or non-scalar attributes are deleted; an unexpected shape never raises text into the result.
4. **Tracing object, factory and LangSmith guard** — Files: `app/coach/tracing/tracing_factory.py`, `app/coach/tracing/tracing_handler.py`, `tests/coach/tracing/test_tracing_factory.py` — Verify: `uv run pytest tests/coach/tracing` + gates — Test: first (seams 2, 3). Thin slices: disabled gives no client (even with keys); enabled with a missing, empty or whitespace key raises a config error naming the setting without values; enabled registers the mask; `start_call(session_id, metadata)` returns a per-call handler config with a generated trace id, where the handler is a subclass whose error status text is only the error class name (deviation D1); `finish(outcome)` attaches a categorical `outcome` score to that trace (deviation D2); `close()` delivers pending data, and with a blocking sink returns within 5 s; the guard forces both LangSmith variables to "false" whatever they were.
5. **Coach plumbing** — Files: `app/coach/conversation/coach.py`, `tests/coach/conversation/test_coach.py`, `tests/fakes/fake_tracing.py` — Verify: `uv run pytest tests/coach/conversation` + gates — Test: first (seam 3). Thin slices: callbacks and metadata reach the chain; version, hash, model and thinking level come from the existing prompt and `ModelInfo`; session id is stable within a conversation, new after `reset()`, never from text; `close()` flushes the tracing object; no tracing object leaves behavior as in 1a.
6. **No-text test through the real handler** — Files: `tests/fakes/memory_span_sink.py`, `tests/coach/conversation/test_coach_tracing.py` — Verify: `uv run pytest tests/coach/conversation/test_coach_tracing.py` + gates — Test: first (seam 3, the privacy gate). Real Langfuse client and handler, in-memory exporter, spy model. A sentinel in the user message, history, reply and error message must appear in nothing the sink receives, for outcomes ok, failed, blocked and cancelled. Also: forced mask failure, failing sink, a sink blocking 5 s not delaying the turn, missing usage numbers, a clean second turn after a sink failure.
7. **Wire `build_coach`** — Files: `app/coach/coach_factory.py`, `tests/coach/test_coach_factory.py` — Verify: `uv run pytest tests/coach/test_coach_factory.py` + gates — Test: first (seam 2). Guard runs on every build, tracing is built only when enabled, a pre-set "true" is overridden, keys never appear in errors.
8. **CLI cleanup and close** — Files: `app/entrypoints/cli.py`, `tests/entrypoints/test_cli.py` — Verify: `uv run pytest tests/entrypoints/test_cli.py` + gates — Test: after. Remove the two env lines from `main()`, call `close()` on every exit path (`/quit`, EOF, Ctrl-C at the prompt). Replace `test_main_turns_langsmith_tracing_off` with a test that the guard comes from `build_coach` and that `close()` is called.
9. **Real trace check and concept 14 write-up** — Files: `docs/features/slice-1b-tracing/task.md` — Verify: the developer runs the CLI with `LANGFUSE_ENABLED=true`, a short conversation and one forced failure, then checks the trace by eye; gates stay green — Test: skip (manual by design; AC13, AC14, EC11).
10. **Close-out** — Files: `docs/features/slice-1a-talking-core/task.md` (mark R2 fixed), graph refresh with `graphify update .` — Verify: gates — Test: skip.
11. **Text capture by environment (added 2026-11-25, FR14, AC15, AC16, EC17-EC20, user-approved; changed from opt-in flag to environment-driven the same day)** — Files: `app/core/config/langfuse.py` (`capture_text` becomes true, false or unset), `app/coach/coach_factory.py` (decides the effective value: explicit setting, else on in `local` and `staging`; refuses explicit true in `production`), `app/coach/tracing/tracing_factory.py` (takes the decided value), `app/entrypoints/cli.py`, `.env.example`, matching tests in `tests/test_config.py`, `tests/coach/tracing/`, `tests/coach/conversation/test_coach_tracing.py`, `tests/coach/test_coach_factory.py`, `tests/entrypoints/test_cli.py` — Verify: those test files + gates — Test: first. Thin slices: setting defaults to unset; a second mask keeps only input and output verbatim; the factory uses it only when told to; `build_coach` decides per environment (on in local and staging, off in production, explicit false wins, explicit true in production refused, ignored when tracing is off); real-path test with positive control and the error echo still masked; the CLI notice shows only when tracing is enabled and text is captured.

## Affected Files & Patterns

- `app/core/config/llm.py` — pattern to copy for the new group; `settings.py` registers it in two places.
- `app/coach/conversation/coach.py` — `_stream` already owns the chain call, and the `llm_call` event already gathers version, hash and model (reuse `_call_fields` data).
- `app/coach/coach_factory.py` — composition root; `CoachConfigError` is the error to reuse.
- `tests/fakes/spy_chat_model.py` — scripted replies and errors already cover ok, blocked, failed.
- Risks:
  - **R-a (resolved by spike, user-approved, deviation D1):** the export hook cannot patch the span status description, and the SDK copies raw provider error text into it from one private handler method. Fix: a handler subclass overriding that method to return only the error class name. The allowlist still deletes the status attribute. The real-path sentinel test catches an SDK change.
  - **R-b (resolved by spike, user-approved, deviation D2):** outcome is known only after the call. A per-call trace id is generated and `finish(outcome)` attaches a categorical `outcome` score. Scores are not spans, so that test uses a recording fake.
  - **R-c:** the Langfuse client is shared per public key, so test isolation needs care.
  - **R-d:** new dependency `langfuse` (5.x), pulls in OpenTelemetry packages.

## Testing Strategy

- Framework & command: pytest. Tests per step as listed. No network, no real keys.
- Gate commands: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run python -m app.scripts.prompts check`.
- Coverage map:

| Spec ID | Step | Test mode | Notes |
|---------|------|-----------|-------|
| AC1, EC2, EC15 | 4, 7 | first | disabled: no client even with keys |
| AC2 | 5, 6 | first | fields on exported trace |
| AC3, EC4, EC5, EC6 | 3, 6 | first | sentinel, four outcomes, real path |
| AC4, EC9 | 3, 6 | first | forced mask failure |
| AC5, EC3 | 4, 7 | first | |
| AC6, EC7, EC8 | 6 | first | EC8 repeat rate: see open questions |
| AC7, EC16 | 6 | first | sink blocking 5 s |
| AC8, EC13 | 5 | first | |
| AC9, EC12 | 4, 5, 8 | first / after | |
| AC10, EC14 | 7, 8, 10 | first / after | |
| AC11, EC1 | 2 | first | |
| AC12 | every step | gates | |
| EC10 | 6 | first | spy reply with no usage |
| AC13, EC11, AC14 | 9 | skip (manual) | recorded in `task.md` |

- Must verify, not assume: everything in spike items (a) to (h); that streamed usage reaches the trace; that Langfuse shows no cost for an unknown model name; that nothing is sent when disabled.
- Open questions: **B2/EC8** how often a Langfuse-failure warning is logged. Default proposed: use the SDK's own logger at WARNING, no extra rate limit, confirm in the spike.
- Known baseline failures: none seen; the 1a baseline was 211 passing.

## Blockers & Resolutions

- B1 (SDK hooks) -> mostly resolved by reading the 5.2.0 source (hooks, signatures, fail-closed behavior); the rest is spike step 1.
- B2 (warning frequency) -> proposed default above; confirm after the spike.
- EC10, EC11 (assumptions) -> verified in steps 6 and 9.

## Trade-offs & Rationale

- Allowlist over denylist: unknown attributes are deleted, so a new SDK attribute can never leak by default.
- One masking layer: the guarantee is about what leaves the machine, and the export hook is the last point before that.
- Tracing object injected, not global: matches the constructor-injection rule and keeps tests off the factory.
- No LangSmith setting: nothing could ever want it.

## Project Rules Applied

- `.claude/rules/ai-core.md` (Privacy, Testing) -> masking before leaving the machine, synthetic sentinel, fakes only.
- `.claude/rules/architecture.md` (Factories, DI, Imports, Naming, Tests) -> factory builds the vendor client, files prefixed `tracing_`, constructor injection, test tree mirrors source.
- `.claude/CLAUDE.md` non-negotiables -> settings only through `app.core.config`, `SecretStr`, tests never reach real services.

## Skills Consulted

| Skill | Contribution |
|-------|-------------|
| lean-ctx | read coach, factory, CLI, settings, spy model, tests tree |
| graphify | query on tracing and callbacks: no existing tracing code, only the CLI LangSmith guard and its test |
| grilling | masking design, wiring and close(), test seams (all confirmed) |
| ponytail | one masking layer, no new settings beyond the four, no LangSmith switch |
| llm-security | OWASP LLM02 shaped the allowlist and fail-closed rules |

## Ready to Implement

- All spec requirements mapped to steps; every step tagged; every AC and EC mapped (EC8 repeat rate is the one open question, with a default)
- Gate commands listed; exact files and verification per step
- Checkpoint interval none; Approaches Considered filled
- Blockers: B1 largely resolved, finished by step 1
- Deviation risk: R-b could force a spec change to FR5/AC2; it will be raised after the spike, not assumed
