# Implementation Plan: Slice 1a, Talking core

## Overview

Build the AI engine's first working loop in `app/coach/`. Gemini (Google AI Studio) is called through LangChain, prompts come from a central JSON prompt registry with locked hashes, and a terminal CLI in `app/entrypoints/` streams replies, keeps history in memory, survives model failures and logs one text-free `llm_call` event per model call. This is the core every later slice wraps around (spec: `docs/features/slice-1a-talking-core/spec.md`).

## Architecture & Design

Three engine capabilities, wired by one composition root:

- **`app/coach/prompts/`:** the registry (load, validate, compile, add, activate) plus the prompt block files. It knows nothing about LangChain.
- **`app/coach/llm/`:** the chat model factory and a small adapter that reads vendor-specific stream metadata: usage, finish reason, block signal. This is the only code that knows Gemini.
- **`app/coach/conversation/`:** `Coach`. It takes a chat model, a compiled prompt and a clock through its constructor. It streams replies, commits history only when a turn completes, keeps per-turn stats, logs `llm_call`, and owns the fixed greeting and fallback line.

Wiring:

- **`app/coach/coach_factory.py`:** `build_coach(settings)` validates the LLM settings, loads the registry and builds the model.
- **`app/entrypoints/cli.py`:** a thin door. A `CliSession` handles one input line at a time; `main()` owns the terminal loop and Ctrl-C.
- **`app/scripts/prompts.py`:** wraps the registry's add, activate and check functions as a command.

## Approaches Considered

| Approach | Trade-offs | Chosen? |
|----------|-----------|---------|
| A. Plain LangChain chat model (`init_chat_model` + `.stream()`) inside an own `Coach` class | Every step stays visible, which is the point of concept 14. Retries and timeouts come from the model. Nothing hides a loop | **Yes.** Smallest design that meets every AC, and it matches `.claude/rules/ai-core.md` (model only from the factory) |
| B. `create_agent` with no tools | Adds an agent loop with nothing to loop over and hides the call. Tools are slice 4 | No. YAGNI |
| C. LangGraph graph now | Brings in state, a checkpointer and nodes before any problem needs them | No. That's slice 5's scope |

**Registry format:** a JSON manifest, chosen over TOML and a Python module.
- JSON is read and written with the standard library, so no new dependency.
- The registry command writes it, so hand-editing is rare.
- TOML needs `tomli-w` to write. A Python module would have to rewrite its own source.

**Prompt assembly:** the registry versions the text, and a LangChain `ChatPromptTemplate` assembles the messages (user decision).
- The alternative, a plain string plus hand-built message lists, was rejected.
- Templates teach the LangChain idiom and give history a placeholder.
- Slices 3, 5 and 10 add variables without changing code.
- f-string format is guarded by a declared-variables check (EC15). Mustache was considered; f-string is the common LangChain form.

**Failures:** reuse the existing `external` error classes rather than adding a new one.
- `ExternalTimeoutError`, `ExternalRateLimitedError`, `ExternalServiceError` and `ExternalBadResponseError` all take `service="llm"`.
- The fallback line is a constant owned by the core, so every door shows the same line.
- No new error code means `docs/error-codes.md` doesn't change. (ponytail)

## Spec Requirements -> Implementation

- FR1 (model from settings), NFR4 -> Steps 1, 5
- FR2 (streaming) -> Steps 6, 8
- FR3, FR4, FR5 (registry, compile to a chat prompt template, validation including declared variables) -> Step 2
- FR6 (registry command) -> Step 3
- FR7 (v1 content from the brainstorm, no skill steps) -> Step 4
- FR8, FR9 (respond, history, greeting in history) -> Step 6
- FR10 (`/reset`, `/quit`, `/stats`, unknown command) -> Step 8
- FR11 (fallback line, failed turn not kept, logged once) -> Steps 6, 8
- FR12 (`llm_call` fields, outcome per call) -> Step 6
- NFR1 (no text in logs) -> Steps 6, 9
- NFR2 (fakes, no network) -> Steps 6, 7, 8
- NFR3 (prompt version and hash on every number) -> Steps 2, 6

## Implementation Steps

Checkpoint interval: every 3 steps.

Gate commands for every step: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`

1. **Dependencies and the `llm` settings group.**
   - Add `langchain` and `langchain-google-genai` with `uv add`.
   - Create `LLMSettings` with prefix `LLM_`: `provider` (default `google_genai`), `model` (no default, optional at load time), `api_key` (`SecretStr`, no default, optional at load time), `timeout_s`, `max_tokens`, `max_retries`, `temperature`, `thinking_level` (`minimal | low | medium | high`, default `minimal`: lowest TTFT on Gemini 3.x; the factory passes it only when the provider is `google_genai`, so other vendors are unaffected).
   - Slice (d): `thinking_level` defaults to `minimal` and rejects unknown values.
   - Register the group on `Settings` and in `load_settings()`.
   - Add a commented `LLM_*` section to `.env.example`. It suggests a Flash-class model and sets `LANGSMITH_TRACING=false` with a note that LangChain must never send traces to LangSmith.
   - Files: `pyproject.toml`, `uv.lock`, `app/core/config/llm.py`, `app/core/config/settings.py`, `.env.example`, `tests/test_config.py`.
   - Verify: `uv run python -c "import langchain, langchain_google_genai"`, `uv run pytest tests/test_config.py`, plus the gates.
   - Test: first. Seam: settings via `load_settings` with a temp env file (user-confirmed). Slices, in order:
     - (a) LLM values load from the env file
     - (b) model and key are absent and the settings still load
     - (c) the key is a `SecretStr` and never shows in `repr`
2. **Prompt registry core.**
   - One manifest holds blocks → versions (file, `sha256`, date, note, declared variables) → named sets (an ordered list of block@version) → the active set.
   - Functions: load from a path, validate, compile, add a version, activate a version in a set.
   - Compiling the active set gives `CompiledPrompt(template, version, hash)`:
     - `template` is a LangChain `ChatPromptTemplate` (f-string) with a system message holding the joined blocks, a `{history}` placeholder and a human `{user_text}` message.
     - The hash covers the template text, never filled-in values.
   - Validation compares each block's detected template variables with its declared ones.
   - Every failure raises `PromptRegistryError`, naming the set, block and version. The manifest is written only after the change validates.
   - Files: `app/coach/__init__.py`, `app/coach/prompts/__init__.py`, `app/coach/prompts/prompt_registry.py`, `tests/coach/prompts/test_prompt_registry.py`.
   - Verify: `uv run pytest tests/coach/prompts`, plus the gates.
   - Test: first. Seam: the registry's public functions on a `tmp_path` manifest (user-confirmed). Slices, in order:
     - (a) compile gives a template whose filled messages are system (blocks in set order), then the history, then the user message, plus a version string and hash (AC14)
     - (b) changed content without a new version fails, naming the block and version (EC6)
     - (c) a missing block, version or file fails (EC7)
     - (d) a missing date or note fails (EC7)
     - (e) a stray brace or an undeclared variable fails (EC15)
     - (f) add locks the hash, date, note and declared variables (AC7)
     - (g) add with no note, or for an unknown block, refuses and leaves the manifest unchanged (EC14)
     - (h) activate switches the version and re-validates
3. **Registry command.**
   - `uv run python -m app.scripts.prompts` with `add <block> <file> --note "..."`, `activate <set> <block> <version>` and `check`.
   - Thin argument parsing that calls step 2's functions, prints one line per result and exits non-zero on `PromptRegistryError`.
   - Files: `app/scripts/prompts.py`, `tests/scripts/test_prompts_command.py`.
   - Verify: `uv run pytest tests/scripts`, plus the gates.
   - Test: after. It is wiring over tested logic; one test per subcommand runs against a `tmp_path` manifest.
4. **v1 prompt content and the shipped registry.**
   - **Revised 2026-11-24 (user decision):** the prompt uses six section blocks, `role → constraints → task → input → output → capabilities`, each starting with its label in plain capitals. The first four-block layout below is kept in the registry as set `coach_4block`. Content is redistributed from it: identity and tone go to role; scope, safety and refer-out go to constraints; the 10 principles go verbatim into task; spoken format goes to output; the skills go to capabilities; input is new and marks user text as data.
   - `safety_scope_v1` comes from brainstorm sections 1, 3 and 7: an AI skills coach, not a therapist; no diagnosis, medication advice or trauma processing; refer out.
   - `persona_v1`: a short, warm, calm, plain-words default.
   - `principles_v1`: the 10 principles from brainstorm section 3, verbatim.
   - `skills_v1`: the 4 MVP skills from section 4, each with what it's for and when to use it, plus how to offer one as a choice. No steps.
   - No markdown formatting in any block.
   - Register every block through step 3's command with notes, then activate set `coach_default` in the order safety_scope → persona → principles → skills.
   - Files: `app/coach/prompts/blocks/safety_scope_v1.md`, `persona_v1.md`, `principles_v1.md`, `skills_v1.md`, `app/coach/prompts/prompt_registry.json`, `tests/coach/prompts/test_shipped_registry.py`.
   - Verify: `uv run python -m app.scripts.prompts check`, `uv run pytest tests/coach/prompts`, plus the gates.
   - Test: after. The shipped registry validates and compiles, and the compiled text starts with the safety block (AC2, part).
5. **LLM factory and Gemini adapter.**
   - First, a throwaway spike with your real key, kept uncommitted and run once. It streams a short reply and prints only the chunk metadata keys and types, never text. Record three facts in `task.md`:
     - whether usage arrives while streaming, and which option enables it (B3)
     - how the finish reason marks truncation
     - how an empty or blocked reply is signalled (B4)
   - Then build the factory: `init_chat_model` with provider, model, key, timeout, max tokens, retries and temperature from `settings.llm`.
   - The adapter turns the last chunk's metadata into usage, `truncated`, `blocked` and a block reason. It also maps vendor exceptions to `ExternalTimeoutError`, `ExternalRateLimitedError` or `ExternalServiceError` with `service="llm"`.
   - Files: `app/coach/llm/__init__.py`, `app/coach/llm/model_factory.py`, `app/coach/llm/llm_response.py`, `tests/coach/llm/test_llm_response.py`.
   - Verify: `uv run pytest tests/coach/llm`, plus the gates.
   - Test: after. It depends on real Gemini behavior. Tests use synthetic metadata dicts shaped like what the spike observed, never recorded text.
6. **`Coach` core.**
   - `Coach(model, prompt, clock)` owns `GREETING` and `FALLBACK_LINE`. History starts with the greeting as an `AIMessage`.
   - `respond(text)` fills the compiled template with the history and the user's text (`template | model`, streamed). It yields chunks and records TTFT and total time with the injected clock. It commits user and AI messages to history only after the stream completes, so closing the iterator early (Ctrl-C) commits nothing.
   - On any external error, or a blocked or empty reply, it raises an `external` error with history unchanged.
   - It writes exactly one `llm_call` event per call with outcome `ok`, `cancelled`, `failed` or `blocked` and the FR12 fields. The failed event carries the error code and is the single error log for that turn.
   - `reset()` clears history back to the greeting and clears the stats. `stats()` returns `TurnStats` for completed turns. History is exposed read-only.
   - The shared spy chat model in `tests/fakes/` wraps `GenericFakeChatModel`, records every message list it receives, and can be scripted to raise, return usage, truncate, or return empty/blocked metadata.
   - Files: `app/coach/conversation/__init__.py`, `app/coach/conversation/coach.py`, `app/coach/conversation/turn_stats.py`, `tests/fakes/__init__.py`, `tests/fakes/spy_chat_model.py`, `tests/coach/conversation/test_coach.py`.
   - Verify: `uv run pytest tests/coach/conversation`, plus the gates.
   - Test: first. Seam: `Coach` public interface (`respond`, `reset`, `stats`, `history`) (user-confirmed). Slices, in order:
     - (a) the system message is the compiled prompt, safety first (AC2)
     - (b) the greeting is history's first message (FR9)
     - (c) turn 2 receives the greeting, user 1 and reply 1 in order (AC3)
     - (d) one `llm_call` with all FR12 fields (plus `thinking_level`) and outcome `ok` (AC4)
     - (e) TTFT and total come from the clock
     - (f) a model error raises `external`, leaves history unchanged, writes one `failed` event, and the next turn works (AC8, EC5)
     - (g) closing the iterator after one chunk leaves history unchanged and logs `cancelled` (EC2)
     - (h) truncation is kept and flagged (EC3)
     - (i) missing usage still succeeds, with `usage_missing` (EC8)
     - (j) a blocked or empty reply raises, keeps nothing, and logs `blocked` with its reason (EC9)
     - (k) a long input is sent as-is and the event records its length (EC11)
     - (l) `reset` (EC13)
     - (m) no captured log contains user, reply or prompt text over a multi-turn run (AC5)
7. **Composition root.**
   - `build_coach(settings)` checks `settings.llm.model` and `api_key`, then raises `CoachConfigError` naming the missing setting, never its value.
   - It loads and validates the registry from the shipped manifest path. A `PromptRegistryError` passes through.
   - It builds the model through the factory and returns a `Coach` with the real clock.
   - Files: `app/coach/coach_factory.py`, `tests/coach/test_coach_factory.py`.
   - Verify: `uv run pytest tests/coach/test_coach_factory.py`, plus the gates.
   - Test: after. It is wiring; `build_coach` wasn't confirmed as a TDD seam. Tests cover:
     - missing model and missing key each give a message naming the setting, without the key (AC11, EC4)
     - a broken manifest fails (EC6, EC7)
     - valid settings return a `Coach`, with the model factory patched so there is no network
8. **CLI.**
   - `CliSession(coach, write)` exposes `greet()` and `handle(line)`, which returns whether to continue:
     - empty or whitespace input does nothing (EC1)
     - `/reset` resets the coach and greets again (EC13)
     - `/quit` returns false
     - `/stats` prints a table of turn, TTFT, total, input tokens, output tokens and truncated, or "no turns yet" (EC12). Unknown tokens show as `?` (EC8)
     - any other `/` input prints the unknown-command line (EC10)
     - other text streams `coach.respond` to `write`; an `external` error prints `FALLBACK_LINE` (AC8)
   - `main()`:
     - sets `LANGSMITH_TRACING=false` in the process environment before building
     - calls `configure_logging`
     - (deviation, approved 2026-11-24) sends logs to `logs/cli.log` through a new optional `stream` argument on `configure_logging`, and sets the httpx, httpx2 and google_genai loggers to WARNING, so log lines don't interleave with the streamed chat
     - turns `CoachConfigError` or `PromptRegistryError` into one clear message and exit code 1, before any greeting (AC11)
     - loops on `input()`
     - on Ctrl-C mid-stream, closes the response iterator and returns to the prompt; on Ctrl-C or EOF at the prompt, exits cleanly
   - Files: `app/entrypoints/__init__.py`, `app/entrypoints/cli.py`, `tests/entrypoints/test_cli.py`.
   - Verify: `uv run pytest tests/entrypoints`, plus the gates.
   - Test: first for `CliSession`. Seam: `CliSession.handle` and `greet` with a fake coach and a captured `write` (user-confirmed). Slices: EC1, `/reset` (EC13), `/quit`, `/stats` with and without turns (EC12, EC8), unknown command (EC10), fallback (AC8), streaming text. `main()`'s Ctrl-C handling is checked by hand in step 9.
9. **Real run and the numbers.**
   - With your key in `.env`, run `uv run python -m app.entrypoints.cli`.
   - Before running, write down predictions in `task.md`: input tokens at turn 20, and the TTFT range.
   - Hold a real 5-minute conversation and run at least 20 turns (AC1).
   - Check by hand: Ctrl-C mid-reply returns to the prompt and `/stats` shows no new turn (EC2); `/stats` and `/reset` work; a run with a bad key shows the fallback line (EC5).
   - Read the log output and confirm no text appears (AC5, NFR1).
   - Record from `/stats` the median and worst TTFT, and input tokens at turn 1 vs turn 20, with model, date and prompt hash (AC13).
   - Files: `docs/features/slice-1a-talking-core/task.md` (the numbers and the spike findings).
   - Verify: the manual checklist above, plus the gates.
   - Test: after (manual, real provider).
10. **Docs.**
    - Add the CLI and prompt command lines to the command tables in `README.md` and `.claude/CLAUDE.md`.
    - Add the `llm` group to the Configuration section of `docs/architecture.md`.
    - Files: `README.md`, `.claude/CLAUDE.md`, `docs/architecture.md`.
    - Verify: the gates.
    - Test: skip (docs only); the existing suite must still pass.

## Affected Files & Patterns

- New: `app/coach/**`, `app/entrypoints/**`, `app/scripts/prompts.py`, `app/core/config/llm.py`, `tests/coach/**`, `tests/entrypoints/**`, `tests/fakes/**`, `tests/scripts/**`.
- Changed: `app/core/config/settings.py` (new group), `.env.example`, `pyproject.toml`, `uv.lock`, `tests/test_config.py`, `README.md`, `.claude/CLAUDE.md`, `docs/architecture.md`.
- Patterns to follow:
  - Settings groups: the `SentrySettings` pattern (`env_config(prefix)`, `SecretStr`, `_from_env_file` in `load_settings`).
  - Errors: the existing `external` classes in `app/core/errors/types.py`.
  - Logging: `structlog.get_logger(__name__)` with event names; check logs in tests with structlog's log capture.
  - Scripts: the `app/scripts/gen_error_docs.py` style (`python -m app.scripts.<name>`).
- Risks:
  - `tests/conftest.py` sets env vars before settings load. LLM settings are optional at load time, so no change is needed there. Confirm in step 1.
  - `gen_error_docs` only discovers `app/modules/*/errors.py`, while the new naming rule is `<feature>_errors.py`. 1a adds no error classes, so it's unaffected. The first module that adds `*_errors.py` must update the discovery.
  - LangChain pulls in `langsmith`. If `LANGSMITH_TRACING` or `LANGCHAIN_TRACING_V2` were ever true, conversation text would leave the machine. Step 8 forces it off, and step 1's `.env.example` documents it.

## Testing Strategy

- **Framework and command:** pytest, `uv run pytest` (paths per step). No test needs network or an API key (AC12): the spy chat model and a patched model factory cover everything.
- **Gate commands:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` (from `.claude/CLAUDE.md`). No architecture checker yet (import-linter is deferred by the rules discussion).
- **Coverage map:**

| Spec ID | Step | Test mode | Notes |
|---------|------|-----------|-------|
| AC1 | 9 | after | Real 5-minute session |
| AC2 | 6, 4 | first, after | Fake: system message order; shipped registry starts with safety |
| AC3 | 6 | first | |
| AC4 | 6 | first | Outcome field included |
| AC5 | 6, 9 | first, after | Captured logs; real logs by eye |
| AC6 | 2 | first | |
| AC7 | 2, 3 | first, after | Logic in 2; command wiring in 3 |
| AC8 | 6, 8 | first | Core raises; CLI prints the line |
| AC9 | 8 | first | |
| AC10 | 6, 8, 9 | first, after | EC2's Ctrl-C loop checked by hand |
| AC11 | 7, 8 | after, first | Factory message; CLI exits before greeting |
| AC12 | all | — | Run the suite with no `LLM_*` env set |
| AC13 | 9 | after | Numbers recorded in task.md |
| EC1 | 8 | first | |
| EC2 | 6, 9 | first, after | Iterator close in core; real Ctrl-C by hand |
| EC3 | 6, 5 | first, after | Signal shape from the spike |
| EC4 | 7, 8 | after, first | |
| EC5 | 6, 9 | first, after | Bad key by hand |
| EC6 | 2, 7 | first, after | |
| EC7 | 2, 7 | first, after | |
| EC8 | 6, 8 | first | Depends on B3 from the spike |
| EC9 | 6, 5 | first, after | Depends on B4 from the spike |
| EC10 | 8 | first | |
| EC11 | 6 | first | |
| EC12 | 8 | first | |
| EC13 | 6, 8 | first | |
| EC14 | 2 | first | |
| EC15 | 2 | first | Stray brace or undeclared variable |
| AC14 | 2, 6 | first | Template message order; Coach uses the template |

- **Must verify, not assume:**
  - LangChain imports cleanly on Python 3.14 (B2; resolution checked, imports not yet)
  - Gemini returns streamed usage (B3)
  - how Gemini signals truncation and blocks (B4)
  - LangSmith tracing stays off
- **Open questions:** none. Every EC has an expected outcome in the spec.
- **Known baseline failures:** none seen. Run `uv run pytest` before step 1 to confirm.

## Blockers & Resolutions

- B1 (brainstorm) -> Resolved. `docs/brainstorming.md` provides the safety scope, the 10 principles and the 4 skills, without steps.
- B2 (Python 3.14) -> Resolution passed on 2026-11-24 (`uv pip compile`: langchain 1.5.2, langchain-core 1.8.4, langchain-google-genai). Imports are checked in step 1.
- B3, B4 (Gemini usage and block signals) -> Step 5's spike checks them against the real API before the adapter is written.
- An LLM key is required only when the coach starts -> confirmed with the user (see Trade-offs).

## Trade-offs & Rationale

- **The LLM key and model are optional in `Settings` but required by `build_coach`** (user-approved reading of FR1). The FastAPI app, Alembic and the test suite don't need an LLM key. EC4 and AC11 still hold at coach startup.
- **History is committed only after a complete stream.** That one rule gives EC2, EC5 and EC9 their "nothing kept" behavior without special cases.
- **One `llm_call` event per call, with an outcome** (user decision). The numbers include cancelled and failed calls, and the failed event is the single error log.
- **The core owns the greeting and fallback line** (user decision), so the slice 7 voice door reuses them.
- **The JSON manifest and an add/activate/check command** (user decision). There's no new dependency, and hashes are never hand-written.
- **The clock is injected into `Coach`,** so TTFT tests are exact rather than timing-dependent.

## Project Rules Applied

- `.claude/rules/architecture.md`:
  - the engine is in `app/coach/` with capability subpackages and prefixed files
  - the composition root is `coach_factory.py`
  - the CLI door is in `app/entrypoints/`
  - constructor injection
  - tests mirror the source, with shared fakes in `tests/fakes/`
  - no `utils.py`
  - the command goes in `app/scripts/`
- `.claude/rules/ai-core.md`:
  - only `llm/` knows Gemini
  - all prompt text comes from the registry
  - versions are never edited in place
  - every call records the prompt version and hash
  - no text in logs
  - no invented clinical content
  - fake models in tests
- `.claude/CLAUDE.md`: settings only via `app.core.config`; tests never reach real services; conversation text is health data.
- `docs/architecture.md`: the settings group pattern, structlog event naming, the `external` error category, and the "log an error once" rule.
- Memory: no auth or other HTTP modules are built.

## Skills Consulted

| Skill | Contribution |
|-------|-------------|
| lean-ctx | Settings group pattern (`SentrySettings`, `load_settings`), `external` error classes, `gen_error_docs` discovery limit, conftest env setup, redaction keys in logging |
| grilling | Registry format (JSON), command scope (add/activate/check), fallback ownership, the 4 test seams, the outcome field on `llm_call`, API key availability, the FR1 "required" reading |
| ponytail | Reuse the existing external errors instead of a new class; no DI or registry libraries; no agent or graph in 1a |
| tdd | Seams named and confirmed for the `Test: first` steps (1, 2, 6, 8) |
| uv (shell) | Dependency resolution on Python 3.14 (B2) |

## Ready to Implement

- All spec requirements are mapped to steps.
- Every step has a Test tag, and every AC and EC is mapped (no uncovered IDs).
- Gate commands are listed.
- Every step names its exact files and a verification command.
- Approaches Considered is filled, and the checkpoint interval is every 3 steps.
- Affected files are identified, blockers have resolutions, and edge cases are handled.
- One approved interpretation of the spec: the LLM key is required when the coach starts, not in `Settings`.
