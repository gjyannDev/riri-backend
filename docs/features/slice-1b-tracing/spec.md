# Feature: Slice 1b, Tracing

Part of slice 1 (Text coach on LangChain) in `docs/ai-engineering-learning-path-v2.md` (row "1b. Tracing" and the "1b done when" list). Slice 1a (talking core) is done; 1c (seed evals) follows. This spec covers 1b only.

## Problem

The coach runs, but the only visibility into a call is a local log line. The developer cannot see, in a trace viewer, where the time goes inside a turn, or list the calls the framework made. A normal tracing setup would send the whole conversation (system prompt, history, user message, reply) to a third party. Conversation text is health data, so that is not acceptable, even when the data is the developer's own.

The only user is the developer, who is learning AI engineering by building the coach (concept 14: what the framework hides).

## Goal

Every coach call appears in Langfuse cloud with tokens, latency, prompt version, prompt hash and session id, and never with any message text. Tracing is off unless explicitly turned on. LangSmith can never turn on, from any door.

Measurable outcome (from "1b done when"):
- a masked trace, checked by eye, shows no message text
- the no-text test passes
- the developer can list every LLM call in one turn and name the v1 code each piece replaced

## Project Conventions

Rule files consulted: `.claude/CLAUDE.md`, `.claude/rules/architecture.md`, `.claude/rules/ai-core.md`. Constraints they put on this feature:

- **Privacy (ai-core, Privacy):** never log, trace or store user text, coach text or prompt text. Tracing masks content before it leaves the machine. Test data is synthetic.
- **Settings:** only through `app.core.config`, never `os.getenv`. A new concern gets its own prefixed settings group, registered in `settings.py` and `load_settings()`, with a commented section in `.env.example`. Secrets use `SecretStr`.
- **One core, every door:** tracing and the LangSmith guard belong to the engine, wired in the composition root `build_coach(settings)`, so no door can skip them.
- **Factories and vendors:** anything chosen by configuration is built by one factory from its settings group. Vendor-specific code (Langfuse) stays in the factory and its small adapter next to it.
- **Dependency injection:** collaborators arrive through constructors. Tests pass fakes straight to constructors and skip the factory.
- **Reuse:** the existing `llm_call` event, `ModelInfo` and `CompiledPrompt.version` / `.hash` are the source for per-call fields. They are not recomputed.
- **Tests:** mirror the source tree, shared fakes in `tests/fakes/`, never reach real external services (LLM, STT, TTS, tracing).
- **Workflow:** spec first. Update spec and plan before changing behavior. The user commits manually.

## User Flow

1. The developer adds `LANGFUSE_ENABLED=true`, the public and secret keys and (optionally) the base URL to `.env`.
2. The developer starts the CLI. If tracing is enabled and a key is missing, the CLI stops with a message naming the missing setting. Otherwise it starts as in 1a.
3. The developer has a conversation. Nothing visible changes in the terminal.
4. Each coach call shows up in Langfuse as a trace, grouped under a session. Input and output panels show a placeholder, not text. Tokens, latency, model, prompt version, prompt hash, turn number and outcome are visible.
5. `/reset` starts a new session id, so the next conversation appears as a separate session.
6. The developer quits (`/quit`, EOF or Ctrl-C at the prompt). Pending traces are sent, waiting at most a few seconds, then the CLI exits.
7. With tracing off (the default), none of this happens and no network call to Langfuse is made.

## Requirements

### Functional

**Settings**
- **FR1:** A new `langfuse` settings group (prefix `LANGFUSE_`) holds: `enabled` (default false), `public_key`, `secret_key` (`SecretStr`) and `base_url` (default `https://cloud.langfuse.com`). `.env.example` documents it.
- **FR2:** Tracing is on only when `enabled` is true. Keys present without `enabled` do nothing.
- **FR3:** Enabled with a missing or blank key stops startup with an error that names the setting and never shows a value.

**What is traced**
- **FR4:** Every model call made by the coach produces one trace, whatever its outcome: ok, cancelled, blocked or failed.
- **FR5:** Each trace carries only these values besides tokens and latency: prompt version, prompt hash, session id, turn number, model name, thinking level, temperature and outcome. No input length, no text.
- **FR6:** The session id is generated for each conversation, is not derived from any text or user data, and changes on `/reset`.
- **FR7:** Prompt version, prompt hash and model info come from the same sources as the `llm_call` log event.

**Masking**
- **FR8:** Before anything leaves the machine, all content is replaced by a fixed placeholder: system prompt, history, user message, reply and error text. Only numbers, ids and the metadata in FR5 pass through.
- **FR9:** Masking fails closed. If it cannot process a value, that content is replaced by the placeholder or dropped, never sent as is.
- **FR10:** There is no unmasked mode by default. Text capture exists only as the opt-in in FR14 (added 2026-11-25 at the developer's request, to read conversations in the Langfuse preview).

**Failure and lifecycle**
- **FR11:** A Langfuse failure (unreachable, rejected keys, slow) never breaks, delays or changes a coach turn, and nothing appears in the chat. It is logged as an event with no text.
- **FR12:** On exit, pending traces are sent, waiting at most 5 seconds. If Langfuse is unreachable, the CLI still exits within that limit.

**LangSmith (closes review finding R2)**
- **FR13:** Building the coach always forces LangSmith tracing off, whatever the environment says, so it holds for every door. The CLI no longer sets this itself. There is no setting that turns LangSmith on.

**Opt-in text capture (added 2026-11-25)**
- **FR14:** Input and output text reach Langfuse (so the preview shows it) when tracing is enabled and `ENVIRONMENT` is `local` or `staging`. In `production` text is always masked. `LANGFUSE_CAPTURE_TEXT` overrides the environment default: `false` masks text everywhere; `true` is refused in `production` (startup stops with an error naming both settings). It changes nothing else: error text, prompt-internal fields and unknown attributes stay masked. While text is captured, the CLI prints one line at startup saying message text is being sent to Langfuse. Changed 2026-11-25 at the developer's request (first an opt-in flag, then environment-driven). Staging must therefore hold synthetic conversations only.

### Non-Functional

- **Privacy:** the no-text guarantee is proven by a test that follows the real handler path, not only by a unit test of the masking function.
- **Latency:** tracing adds no blocking network call to the turn path.
- **Security:** keys never appear in logs, errors, `repr` or test output.
- **Compliance:** Langfuse cloud is a third-party processor of health-adjacent metadata. The no-text rule is what makes that acceptable. Naming it on the consent screen is a later slice.

## UX Requirements

- No new CLI commands and no new terminal output on the normal path.
- A startup config error follows the 1a pattern: one line starting with "Cannot start the coach:", naming the setting (for example `LANGFUSE_SECRET_KEY`), never its value.
- `/stats` and the local `llm_call` log work exactly as in 1a.

## Constraints

- Langfuse cloud (EU, `cloud.langfuse.com`), SDK added as a dependency.
- One LLM call per turn in 1a (no tools, retrieval or graph yet), so a trace tree will be small. The concept 14 exercise says so honestly and notes what later slices will add.
- No new database tables, no HTTP routes.
- Tests never reach Langfuse, with or without real keys in `.env`.

## Blockers

- **B1 (assumption — verify):** the exact SDK hooks for masking, an in-memory sink for tests, and what gets masked (including error status text) must be confirmed in the installed Langfuse version before the plan fixes the approach.
- **B2 (EC8):** how often a Langfuse failure warning is logged (once per session, or per failure) is undecided.

## Edge Cases

Format: condition -> expected outcome.

- **EC1:** `LANGFUSE_ENABLED` is true, both keys set, `base_url` blank or unset -> the default cloud URL is used.
- **EC2:** keys are set but `enabled` is false or unset -> no tracing, no client created, no network call, no warning.
- **EC3:** enabled and a key is an empty or whitespace string -> treated as missing, startup stops (FR3).
- **EC4:** the provider's error message contains user text -> the trace shows the placeholder for the error text.
- **EC5:** Ctrl-C mid-reply -> the call is traced with outcome cancelled, content masked, partial reply not stored.
- **EC6:** the reply is blocked or empty -> the call is traced with outcome blocked.
- **EC7:** Langfuse unreachable during a session -> turns work as normal, nothing in the chat, a text-free warning logged.
- **EC8:** Langfuse rejects the keys -> same as EC7. How often the warning repeats: expected: unknown (B2).
- **EC9:** the masking step raises or meets an unexpected value shape -> that content becomes the placeholder (or is dropped); the turn is unaffected (FR9).
- **EC10:** streamed chunks carry no usage numbers -> the trace has no token counts but is otherwise complete, and the local log keeps its `usage_missing` flag (assumption — verify).
- **EC11:** Langfuse shows no cost for the model name (unknown to its price table) -> not an error, no action (assumption — verify).
- **EC12:** exit while Langfuse is unreachable -> the CLI exits within 5 seconds and the unsent traces are lost.
- **EC13:** `/reset` mid-session -> the next call has a new session id; earlier traces keep the old one.
- **EC14:** `LANGSMITH_TRACING` or `LANGCHAIN_TRACING_V2` is "true" in the environment before startup -> building the coach forces both to "false".
- **EC15:** a developer machine has real Langfuse keys in `.env` and runs the tests -> nothing is sent; the tests use a fake sink.
- **EC16:** the Langfuse sink blocks for several seconds during a turn -> the turn still completes without waiting for it.
- **EC17:** `LANGFUSE_CAPTURE_TEXT=true` with tracing enabled and `ENVIRONMENT=production` -> startup stops, naming `LANGFUSE_CAPTURE_TEXT` and `ENVIRONMENT`, no values.
- **EC18:** text capture would be on but tracing is not enabled -> nothing is sent, no error, no banner.
- **EC19:** text capture on and the provider error echoes the request -> the trace still carries only the error class name, never the echoed text.
- **EC20:** `LANGFUSE_CAPTURE_TEXT` unset -> text is captured in `local` and `staging`, masked in `production`. `LANGFUSE_CAPTURE_TEXT=false` -> masked in every environment.

## Acceptance Criteria

- [ ] **AC1:** With `enabled` unset or false (including keys set), building and running the coach creates no tracing client and makes no call to Langfuse. (EC2, EC15)
- [ ] **AC2:** With tracing enabled and a fake sink, one coach call yields one trace carrying prompt version, prompt hash, session id, turn, model, thinking level, temperature, outcome, token counts and latency, and nothing else. (FR4, FR5, FR7)
- [ ] **AC3:** No-text test: a sentinel string placed in the user message, the history, the fake model's reply and the fake model's error message appears in no field the fake sink receives, for outcomes ok, failed, blocked and cancelled. The check runs through the real handler path. (FR8, EC4, EC5, EC6)
- [ ] **AC4:** When the masking step is forced to raise, the sentinel still does not reach the sink and the turn completes normally. (FR9, EC9)
- [ ] **AC5:** Enabled with a missing, empty or whitespace key stops startup with an error that names the setting and does not contain any key value. (FR3, EC3)
- [ ] **AC6:** A sink that raises or rejects the keys never changes a turn's reply or history, shows nothing in the CLI output, and produces a log event containing no text. (FR11, EC7, EC8)
- [ ] **AC7:** A sink that blocks for 5 seconds does not delay the turn's streamed reply or its completion. (EC16)
- [ ] **AC8:** The session id is constant across turns in one conversation, differs after `/reset`, and is not equal to or derived from message text. (FR6, EC13)
- [ ] **AC9:** On exit with a reachable fake sink, all pending traces have been delivered. With an unreachable sink, exit completes within 5 seconds. (FR12, EC12)
- [ ] **AC10:** After building the coach with `LANGSMITH_TRACING=true` and `LANGCHAIN_TRACING_V2=true` in the environment, both read "false". The CLI sets neither itself. Review finding R2 is marked fixed in `task.md` of slice 1a. (FR13, EC14)
- [ ] **AC11:** `langfuse` settings: `secret_key` and `public_key` are `SecretStr`, `.env.example` documents all four variables, and no key value appears in `repr`, logs or error output. (FR1, FR2)
- [ ] **AC12:** The 1a gates stay green: full test suite, `ruff check`, `ruff format --check`, `pyright` with 0 errors, and `prompts check`. `/stats` and the `llm_call` event are unchanged.
- [ ] **AC13:** Manual check recorded in `task.md`: in a real Langfuse trace from the CLI, the input panel, the output panel, the metadata, the tags and the error status of a deliberately failed call contain no message text.
- [ ] **AC14:** Concept 14 write-up recorded in `task.md`: for one real turn, every LLM call listed with tokens and latency taken from the trace, and the v1 code each piece replaced. It states that 1a makes one call per turn and what later slices will add.
- [ ] **AC15:** With `LANGFUSE_CAPTURE_TEXT=false`, or `ENVIRONMENT=production`, every AC above holds unchanged: no text is sent. (FR14, EC20)
- [ ] **AC16:** With tracing enabled and text capture on (default in `local` and `staging`), a sentinel in the user message and the reply reaches the sink in the input and output attributes, while an error message echoing the sentinel, the status text and unknown attributes still do not. An explicit `LANGFUSE_CAPTURE_TEXT=true` in `production` fails the build as in EC17. The CLI prints the one-line notice only when tracing is enabled and text is captured. (FR14, EC17-EC20)

## Out of Scope

- **Unmasked / debug tracing mode in production:** privacy is the point of the slice. Text capture exists only in `local` and `staging` (FR14), never in `production`, and `LANGFUSE_CAPTURE_TEXT=false` turns it off anywhere.
- **Self-hosted Langfuse:** decided to use cloud for 1b; masking carries the guarantee.
- **User ids and profile data in traces:** no accounts yet, and they would be new personal data.
- **Evals and scores in Langfuse, Langfuse prompt management:** slice 1c and the prompt registry cover these.
- **Tracing for voice and HTTP doors:** they reuse the same wiring when they exist; nothing door-specific is built now.
- **Masking for Sentry or other sinks:** not part of this slice.
- **Consent screen and processor disclosure:** later slice.
- **Dashboards and alerts in Langfuse:** the developer reads traces by hand.
- **A LangSmith switch:** there is no scenario where it is wanted.
