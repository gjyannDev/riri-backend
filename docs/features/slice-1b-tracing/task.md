# Implementation: Slice 1b, Tracing

## Status
Steps 1-8 and 10 done. **Step 9 pending: needs you** (real Langfuse keys, one real conversation, one by-eye check). Not ready for PR until step 9 is recorded.
Health Check: all present (extra: installed `langfuse/skills@langfuse`, official Langfuse org, 21.9K installs, for docs lookups). Review health check: code-review, security-review, llm-security, simplify, verification-before-completion all present; run inline without sub-agents.
Branch: feat/slice-1a-talking-core (user asked to stay on it; no new branch). Nothing committed by me.

## Completed Steps
- [x] 1. Spike (throwaway; findings below)
- [x] 2. Settings group
- [x] 3. Mask function
- [x] 4. Tracing object, factory, LangSmith guard
- [x] 5. Coach plumbing
- [x] 6. No-text test through the real handler
- [x] 7. Wire `build_coach`
- [x] 8. CLI cleanup and close
- [ ] 9. Real trace check and concept 14 write-up (needs the developer)
- [x] 10. Close-out (R2 marked fixed in slice 1a `task.md`, `graphify update .` run)
- [x] 11. Text capture by environment (added 2026-11-25 at the developer's request; first an opt-in flag, then changed the same day to: on in local and staging, off in production, `LANGFUSE_CAPTURE_TEXT` overrides; spec FR14, AC15, AC16, EC17-EC20)

## Current Step
### 9. Real trace check and concept 14 write-up: waiting on you
`.env` has no `LANGFUSE_*` lines yet (checked names only, no values printed). To run it:
1. Add to `.env`: `LANGFUSE_ENABLED=true`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL=https://cloud.langfuse.com`.
2. `uv run python -m app.entrypoints.cli`: 3 or 4 turns, `/reset`, one more turn, `/quit`. For the failure case, run once more with a wrong `LLM_API_KEY` and send one message.
3. In Langfuse (Tracing, Sessions): open one trace and confirm by eye that the input panel, output panel, metadata, tags and the error status of the failed call show no text from the conversation. Record the result under AC13 below.
4. Concept 14 (AC14): for one turn, list every LLM call with tokens and latency from the trace and name the v1 code each piece replaced. Expect one model call in 1a (plus the prompt-template and chain steps), say so, and say what later slices add.
5. Check EC11 (cost shown or blank for `gemini-3.5-flash-lite`), the model name appears (the "not able to parse the LLM model" warning only appeared with the fake model), `outcome` score visible on the trace, and the CLI exits promptly.

## Spike findings (step 1)
- (a) `mask_otel_spans` runs even with an injected `span_exporter`.
- (b) Exported keys: `langfuse.observation.{input,output,metadata.*,usage_details,model.name,model.parameters,level,status_message,cost_details,completion_start_time,type}`, `langfuse.trace.metadata.*`, `session.id`, `langfuse.internal.*`. Metadata values are JSON text. Session id passes through the metadata key `langfuse_session_id`.
- (c) The provider's error text lands in the OTel span status description (not an attribute), set only from the LangChain handler's `_get_error_level_and_status_message`. No span events carried text. -> D1.
- (d) Cancelled calls show as ERROR with an empty message; blocked and ok look the same. -> D2.
- (e) Usage tokens reach the trace. (f) Client construction makes no network call. (g) A second client with the same public key reuses the first one's resources, so tests use a distinct key each.
- (h) Failure logging frequency (B2): the SDK and OpenTelemetry log through Python logging; our own `tracing_failed` and `tracing_flush_timeout` events carry only the operation and error class. Default kept: no extra rate limit. Check how noisy it is during step 9 with a wrong base URL.

## Changes Made
- (user commits manually) Suggested groups, one line each, no trailer:
  1. `git add pyproject.toml uv.lock app/core/config/langfuse.py app/core/config/settings.py .env.example tests/test_config.py tests/conftest.py && git commit -m "feat(config): add Langfuse settings group, off by default"`
  2. `git add app/coach/tracing tests/coach/tracing tests/fakes/memory_span_sink.py && git commit -m "feat(tracing): add export-stage allowlist mask, handler and tracing factory"`
  3. `git add app/coach/conversation/coach.py tests/coach/conversation tests/fakes/fake_tracing.py && git commit -m "feat(coach): trace each call with session id, outcome and close()"`
  4. `git add app/coach/coach_factory.py app/entrypoints/cli.py tests/coach/test_coach_factory.py tests/entrypoints/test_cli.py && git commit -m "feat(coach): force LangSmith off in build_coach and flush traces on CLI exit"`
  5. `git add docs/features/slice-1b-tracing docs/features/slice-1a-talking-core/task.md && git commit -m "docs(slice-1b): spec, plan and task; mark R2 fixed"`
  (`graphify-out/` changed too; commit it with whichever group you prefer, or leave it ignored as before.)

## Test Results
Baseline before this slice: 211 passing. After: **329 passing** (`env -u API_V1_PREFIX uv run pytest -q`), ruff check clean, pyright 0 errors, `prompts check` OK (hash `aa5966c524f5`, unchanged). `ruff format --check`: one failure, the baseline file below.
Mutation checks on the privacy gate (temporary, reverted, files back to their original hashes): removing the error-text scrub fails 2 tests; making the mask a no-op fails 7.

## Tests Pending
- Step 9 (manual, AC13, AC14, EC11).
- Real-run checks of AC9 (exit within 5 s with a wrong base URL) are covered by a fake-sink test; confirm on the real CLI once.

## Test Cases
| ID | Step | Case | Tag | Source | Status |
|----|------|------|-----|--------|--------|
| T1 | 2 | Langfuse off by default even with keys | spec | AC1, EC2 | pass |
| T2 | 2 | settings read from env file; keys are SecretStr and absent from reprs | spec | AC11, FR1 | pass |
| T3 | 2 | blank or unset base_url gives the EU cloud default | spec | EC1 | pass |
| T4 | 3 | allowlisted ids, numbers, version and hash pass | spec | FR5 | pass |
| T5 | 3 | input and output become `[masked]`; status text deleted; unknown keys deleted | spec | FR8, EC4 | pass |
| T6 | 3 | non-scalar or non-numeric values under allowed keys deleted | inferred | risk: unexpected shape | pass |
| T7 | 4 | disabled builds no client; missing, empty, whitespace key names the setting | spec | AC1, AC5, EC3 | pass |
| T8 | 4 | outcome score attached to the call's trace; score failure never raises, logs type only | spec | FR11, EC7 | pass |
| T9 | 4 | close delivers pending traces; gives up after its limit when the sink blocks | spec | AC9, EC12 | pass |
| T10 | 4, 7 | LangSmith forced off whatever the environment says, also when the build fails | spec | AC10, EC14 | pass |
| T11 | 5 | metadata = version, hash, model, thinking level, temperature, turn only; config reaches the chain | spec | FR5, FR7 | pass |
| T12 | 5 | session id stable within a conversation, new after `/reset`, random hex | spec | AC8, EC13 | pass |
| T13 | 5 | outcome recorded for ok, failed, blocked, cancelled | spec | FR4, EC5, EC6 | pass |
| T14 | 6 | sentinel in user text, history, reply, error and prompt reaches nothing the sink gets (ok, failed, blocked, empty, cancelled) | spec | AC3, EC4-EC6 | pass |
| T15 | 6 | failed call carries only the error class name as status | spec | FR8 (D1) | pass |
| T16 | 6 | forced mask failure: nothing sent, turns unaffected | spec | AC4, EC9 | pass |
| T17 | 6 | raising sink and blocked sink never change or delay a turn | spec | AC6, AC7, EC7, EC16 | pass |
| T18 | 6 | reply without usage numbers still traced | spec | EC10 | pass |
| T19 | 7 | enabled builds the client with the mask hook; disabled never touches Langfuse | spec | AC1, FR2 | pass |
| T20 | 7 | enabled with a missing key stops the build without echoing any key | spec | AC5 | pass |
| T21 | 8 | `close()` called on /quit, EOF, Ctrl-C at the prompt, and after a turn | spec | AC9, FR12 | pass |
| T22 | 8 | CLI no longer sets LangSmith variables itself | spec | AC10 | pass |
| AC13, AC14, EC11 | 9 | by-eye trace check, concept 14 write-up, cost display | spec | | pending (manual) |
| T23 | 11 | `capture_text` is unset by default and can be forced true or false | spec | FR14, AC15 | pass |
| T24 | 11 | keeping-text mask passes input/output only; status text, tags, unknown keys, non-numeric usage still removed | spec | FR14, EC19 | pass |
| T25 | 11 | factory picks the keeping-text mask only when the flag is on | spec | FR14 | pass |
| T26 | 11 | text captured by default in local and staging, masked in production; explicit false wins everywhere; explicit true refused in production when tracing is on; ignored when tracing is off; the factory builds the matching mask | spec | EC17, EC18, EC20 | pass |
| T27 | 11 | real path: sentinel visible in input/output (positive control), echoed provider error and status stay masked, hash still sent | spec | AC16, EC19 | pass |
| T28 | 11 | CLI notice shows only when tracing is on and text is captured (local and staging default, not production, not when forced false) | spec | AC16 | pass |
| EC8 | 9 | repeat rate of Langfuse failure warnings | | B2 | open, default chosen |

## Open Questions
- B2/EC8: warning frequency for Langfuse failures. Default in place (SDK logging, no extra rate limit). Confirm in step 9.

## Baseline Failures
- `uv run ruff format --check .` reports `app/coach/llm/llm_response.py` (unchanged since commit 4cec437; one extra line in the module docstring). Not touched by this slice. I accidentally reformatted it twice while running the formatter over directories and reverted both times with `git checkout`. Fix whenever you like with `uv run ruff format app/coach/llm/llm_response.py`.

## Known Issues
- Langfuse registers its own `atexit` shutdown. After a flush timeout, interpreter exit may wait for that second shutdown, so a blackholed Langfuse could delay exit past the 5 s cap (worst case roughly another export timeout). Connection-refused fails fast. Not fixed (would need SDK internals); measure in step 9.
- Langfuse logs "not able to parse the LLM model" for the fake test model only; confirm the real model name shows in step 9.
- No `learnings.md` for 1b by decision: the concept 14 write-up lives here and merges into the single slice learnings in 1c (user choice in the spec grilling; the learning path says one learnings file at the end of 1c).
- `.env` currently has no Langfuse lines, so nothing has been sent to Langfuse by this work.

## Deviations from Plan
- D1: error text reaches the OTel span status description (not patchable by `mask_otel_spans`). -> plan.md step 4 and R-a updated: handler subclass returns the error class name only. -> Approved by: user (2026-11-25).
- D2: outcome only known after the call. -> plan.md step 4 and R-b updated: generated per-call trace id plus a categorical `outcome` score; handler is per call. -> Approved by: user (2026-11-25).
- D3 (small, not user-asked): the missing-key check lives in `build_tracing` (`TracingConfigError`) and `build_coach` converts it to `CoachConfigError`, instead of a second check in `build_coach`. Same behavior and messages. Plan step 4 listed it under the factory, so this follows the plan.
- D4 (small): `build_tracing` accepts `flush_interval_s`, `close_timeout_s` and `capture_text` so tests can make a slow sink bite (AC7) and shorten the close wait. Defaults unchanged. Plan files list also gained `tracing_call.py` (protocols and the untraced call) and `tracing_handler.py` (D1).

## Debug Log
No `/debug` invocation was needed. Two test-code mistakes (duplicate keyword, JSON-encoded metadata expectation) and typing fixes were fixed on the first retry.

## Review
Written by `/review-feature` on 2026-11-25, as one inline pass (no sub-agents, at the developer's request). Lenses applied by hand: code-review, security-review, llm-security, simplify (report only). Scope: the uncommitted working tree against `HEAD` (the slice 1a commits are already committed; `main..HEAD` still lists them, so a PR would carry both slices).

| ID | Severity | Source | File:line | Finding | Status |
|----|----------|--------|-----------|---------|--------|
| R1 | blocker | traceability | task.md Step 9 | AC13 (a real trace checked by eye shows no message text), AC14 (the concept 14 write-up from a real trace) and EC11 (cost shown or blank for the real model) have no recorded verification, because `.env` had no Langfuse keys when the slice was built. Every other AC and EC has a passing test (see the table above). The AC13 check must be run with `LANGFUSE_CAPTURE_TEXT=false` (or `ENVIRONMENT=production`), since local runs now show text by default. Fix: run the Step 9 checklist and record the results. | open (needs the developer) |
| R2 | should-fix | project rules, llm-security | `.claude/rules/ai-core.md:38`, `.claude/CLAUDE.md` non-negotiables | The binding rules still say "Tracing (slice 1b on) masks message content before it leaves the machine" and "never trace user or coach text unless a spec says so explicitly, with consent". Spec FR14 (added after the build, at the developer's request) now sends text to Langfuse cloud in `local` and `staging`. The spec does say so explicitly, but the rule file was not updated, so a future session reading only the rules would treat the behavior as a violation or, worse, not know the exception exists. Fix: amend the Privacy section of `ai-core.md` to state the exception (FR14: local and staging only, synthetic conversations only, never production) and who decided it. | fixed: `ai-core.md` Privacy now states the FR14 exception |
| R3 | should-fix | llm-security (LLM02), project rules | `app/coach/coach_factory.py:20-30`, `app/core/config/settings.py:21` | Text capture is on by default whenever `ENVIRONMENT` is `local` or `staging`, and `ENVIRONMENT` itself defaults to `local`. A real deployment that enables tracing but forgets to set `ENVIRONMENT=production` would silently send every conversation to Langfuse. Only the CLI prints a notice; the future HTTP and voice doors would say nothing. Tracing still needs `LANGFUSE_ENABLED=true`, which limits the exposure. Fix (keeps your choice for staging): have `build_coach` log one text-free warning event whenever capture is active, so every door surfaces it. Stronger alternatives: capture on by default only in `local`, or refuse to start with tracing enabled unless `ENVIRONMENT` was set explicitly. | fixed: `build_coach` logs `tracing_text_capture_active` (environment only) on every door; tests in `tests/coach/test_coach_factory.py` |
| R4 | should-fix | automated check (AC12) | `app/coach/llm/llm_response.py:1` | AC12 requires `ruff format --check` to stay green, but it fails on this file. It is unchanged since commit 4cec437 and not part of this slice's diff, so it is a baseline failure, but it fails the gate on every run. Fix: `uv run ruff format app/coach/llm/llm_response.py` (one blank line in the module docstring). | fixed: `llm_response.py` formatted, `ruff format --check` green |
| R5 | nit | security-review | `app/core/config/langfuse.py:17` | `base_url` accepts any string, including a plain `http://` URL. The SDK sends the keys (basic auth header) and the traces to it, so a typo or a pasted `http://` address would send them unencrypted. Fix: validate that the URL is `https`, or `http` only for localhost (tests use `http://127.0.0.1:9`). | fixed: `base_url` must be https, or http only for localhost; tests in `tests/test_config.py` |
| R6 | nit | code-review | `app/coach/tracing/tracing_factory.py:119` | Langfuse keeps one client per public key for the whole process, and a second `Langfuse(...)` with the same key returns the first one, ignoring the new mask, exporter and settings. After `close()` it would return a client that has already shut down. This is harmless for the CLI (one coach per process) but matters for an HTTP or voice door that builds a coach more than once. The tests work around it with a unique key per test. Fix: build the client once per process in the door, or document the limit in the factory's docstring. | fixed: limit documented in the `build_tracing` docstring |
| R7 | nit | code-review, simplify | `app/coach/tracing/tracing_call.py:28` | `UntracedCall.config` is a class-level dict shared by every instance. It is safe today because `Coach` passes `call.config or None`, so an empty config never reaches LangChain, but any future code that adds a key to it would leak state into every untraced call. Fix: make `config` a property returning a fresh dict. | open (not selected; safe today) |
| R8 | nit | traceability, code-review | `tests/coach/tracing/test_tracing_factory.py:121`, `tests/coach/conversation/test_coach_tracing.py:209` | Two issues. The AC9 limit of 5 seconds is never asserted: the tests override the wait to 0.3 s, so changing `DEFAULT_CLOSE_TIMEOUT_S` would not fail anything. And the blocked-sink test relies on `sleep(0.3)` and a 1 s threshold, which could flake on a loaded machine. Fix: assert `DEFAULT_CLOSE_TIMEOUT_S == 5.0`, and synchronize the blocked-sink test on an event instead of a sleep. | fixed: default 5 s asserted; blocked-sink and raising-sink tests wait on an event, not a sleep |
| R9 | nit | code-review | `app/coach/conversation/coach.py:80` | `turn` counts only completed turns, so a failed or blocked attempt and its retry both carry the same `turn` in their traces. That is the existing 1a meaning, but it makes two traces in a session look like the same turn when reading them in Langfuse. Fix: none needed if intended; otherwise add an `attempt` field. | won't fix (existing 1a meaning of `turn`) |

Counts when written: 1 blocker, 3 should-fix, 5 nits. After the fixes the developer selected: R2, R3, R4, R5, R6 and R8 are fixed. Still open: R1 (blocker, the manual real-trace check) and R7 (nit); R9 won't fix.

Project-rules checklist: layers and imports (`app/core` does not import `app/coach`; `app/coach` has no fastapi) ok; constructor injection and factory-built vendor client ok; settings only through `app.core.config` ok, with the one documented `os.environ` write for LangSmith; secrets as `SecretStr` and absent from reprs, logs and errors ok; no text in logs (only `tracing_failed` with operation and error type) ok; tests never reach real services (conftest pins `LANGFUSE_ENABLED=false`, fake sink) ok; file naming and test layout ok. Only violation: R2 (rule text out of date).

Check results:
- `env -u API_V1_PREFIX uv run pytest -q` -> pass: 329 passed (313 before the review fixes)
- `uv run ruff check .` -> pass
- `uv run ruff format --check .` -> pass after R4 (109 files already formatted)
- `uv run pyright` -> pass: 0 errors
- `uv run python -m app.scripts.prompts check` -> pass (hash `aa5966c524f5`, unchanged)
- static security scan (`ruff check --select S` on the changed app files) -> pass
- dependency audit -> not run: no audit tool in the project, and installing one needs permission. New dependencies: `langfuse` 5.2.0 (+ `backoff`, `wrapt`, OpenTelemetry packages), from the official Langfuse project.
- migration round-trip -> not run: this slice has no database changes
- LangSmith guard, mask and no-text tests -> mutation-checked earlier (see Test Results)

## Skills Consulted During Implementation
| Step | Skill | Why |
|------|-------|-----|
| all | lean-ctx, graphify | reads, edits, shell, graph refresh |
| 1 | find-skills, langfuse (installed) | current Langfuse docs: handler, metadata keys, flush and shutdown |
| 2-8 | test, tdd, ponytail (applied) | red then green per slice, smallest code |
| 6 | llm-security (applied) | LLM02 allowlist, sentinel across outcomes, fail closed |

## Links
- Spec: docs/features/slice-1b-tracing/spec.md
- Plan: docs/features/slice-1b-tracing/plan.md

---

## Validation Checklist (before PR)
- [ ] All plan.md steps complete (step 9 pending)
- [x] Full test suite green (288 passed); build N/A for this project
- [x] Gate commands green on every step (one baseline format failure recorded)
- [x] Every `/debug` invocation logged (none needed); no step blocked
- [ ] Every spec acceptance criterion met by code and test (AC13, AC14 pending manual)
- [ ] Open Questions resolved or surfaced (B2 default chosen, confirm in step 9)
- [x] No skipped, deleted, or loosened tests; baseline failure listed separately
- [x] task.md updated
- [ ] learnings: deliberately merged into slice 1c per the user's decision
- [x] Commits documented (suggestions above; user commits)
- [ ] No open blockers (step 9 needs your keys)
- [x] Code follows project `.claude/rules`
- [x] No unresolved plan deviations (D1, D2 approved; D3, D4 small)
