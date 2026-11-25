# Feature: Slice 1a, Talking core

Part of slice 1 (Text coach on LangChain) in `docs/ai-engineering-learning-path-v2.md`. Slice 1 is built as 1a (talking core), 1b (tracing) and 1c (seed evals). This spec covers 1a only.

## Problem

The repo has the FastAPI groundwork (config, logging, errors, Sentry, a pgvector database) but no coach. There is nothing to talk to, no managed prompts, and no numbers about how the model behaves. Every later slice (safety gate, RAG, tools, the session graph, voice) wraps around a core conversation loop that doesn't exist yet.

The only user is the developer, who is learning AI engineering by building the coach.

## Goal

A text coach that runs in the terminal, built on LangChain with Gemini (Google AI Studio). Its prompts are managed in one central, versioned registry. It keeps a conversation going, survives model failures, and records timing and token numbers locally without ever logging conversation text.

Measurable outcome: a 5-minute conversation runs, the fake-model tests pass, and the developer can state **time to first token** (TTFT) and **input tokens at turn 1 vs turn 20** from a real session.

## Project Conventions

Rule files consulted: `.claude/CLAUDE.md`, `.claude/rules/architecture.md`, `.claude/rules/ai-core.md`, plus `docs/architecture.md`. Constraints they put on this feature:

- **Placement:** the engine lives in `app/coach/`, with capability subpackages (`llm/`, `prompts/`, `conversation/`) and a composition root (`coach_factory.py`). The CLI is an entry point in `app/entrypoints/`. The engine never imports FastAPI or `app/modules`. Files are prefixed by capability (for example `prompt_registry.py`, `model_factory.py`). There are no `utils.py` files.
- **Dependency injection and factories:** collaborators are passed through constructors. The chat model is built only by a factory from its settings group, and vendor-specific code stays in `llm/`. Entry points wire the engine through `build_coach(settings)`. Tests pass fakes straight to constructors.
- **Prompts:** all prompt text comes from the registry. No prompt text in Python code.
- **Settings:** read settings only through `app.core.config`, never `os.getenv`. A new concern gets its own settings group with an env prefix and a commented section in `.env.example`. Secrets use `SecretStr`.
- **Logging:** use structlog event names with fields (`log.info("llm_call", ...)`), not sentences. Never log bodies or conversation text. Sensitive field names are redacted as a second layer.
- **Errors:** errors are categorized. A failing outside service (here, the LLM) belongs to the `external` category. Log an error once, at the edge.
- **Tests:** the test tree mirrors the source tree (`tests/coach/...`). Shared fakes, such as the spy chat model, live in `tests/fakes/`. Tests never reach real external services. ruff is the linter. The project uses Python 3.14 and `uv`.

## User Flow

1. The developer runs the coach CLI from the repo root.
2. On startup, the CLI loads settings and the prompt registry.
   - If settings are missing or invalid, it stops with a clear message.
   - If the registry is inconsistent, it stops with a clear message.
3. The CLI prints a fixed greeting, for example: "Hi, I'm an AI skills coach, not a therapist. What would you like from the next 10 minutes?"
4. The developer types a message.
5. The coach's reply streams into the terminal.
6. The conversation continues. Each turn sends the compiled prompt plus the whole conversation so far.
7. The developer can type any of these commands at any point:
   - `/stats`: shows a per-turn table of numbers, with no text.
   - `/reset`: starts a fresh conversation with the greeting.
   - `/quit`: exits.
8. When adding a new prompt version, the developer runs a registry command. The command records the new version, locks its content hash and stores a changelog note. The developer then marks the version active in the registry.

## Requirements

### Functional

**Model**
- **FR1:** The chat model is Gemini through Google AI Studio, created via LangChain. Provider, model name, API key, timeout, max output tokens, retries and temperature all come from a new `llm` settings group.
  - Model name and API key are required, with no default.
  - `.env.example` suggests a Flash-class model.
- **FR2:** Replies stream to the terminal as they are generated.

**Prompt registry**
- **FR3:** A central prompt registry is the single source of truth for prompts. It defines:
  - **Blocks:** one per prompt section: `role`, `constraints`, `task`, `input`, `output` and `capabilities` (user decision, 2026-11-24). The first four-block layout (`safety_scope`, `persona`, `principles`, `skills`) stays in the registry as history.
  - **Versions:** every version of every block. Each version records its content file, a locked content hash, a date, a changelog note (required) and its declared template variables (an empty list in 1a).
  - **Named prompt sets:** an ordered list of blocks with the active version of each. The active set is `coach_default`, ordered `role → constraints → task → input → output → capabilities`, so the identity and the safety and scope rules come first. The earlier layout is kept as set `coach_4block`.
  - **The active set:** which named set the coach uses. In 1a, only the registry decides this; there is no env override.
- **FR4:** Compiling the active set produces three things:
  - a LangChain chat prompt template (f-string format) made of:
    - a system message holding the blocks' text in the set's order
    - a placeholder for the conversation history
    - the user's message
  - a version string naming each block and version
  - a content hash of the compiled template text (with placeholders, never filled-in values)

  The registry owns versioning; the template only assembles messages. In 1a the only runtime inputs are the history and the user's text.
- **FR5:** The registry is validated at startup, and the coach refuses to start if:
  - a referenced block, version or file is missing, or
  - a file's content doesn't match its locked hash, or
  - a version is missing its date or changelog note, or
  - a block's template variables differ from the ones its version declares (for example a stray brace).

  The error names the set, block and version at fault.
- **FR6:** A registry command adds a new version of a block. It records the file, computes and locks the hash, and requires a changelog note. Hashes are never written by hand.
- **FR7:** The v1 content of each block comes from `docs/brainstorming.md`. Each block starts with its section label in plain capitals (`ROLE`, `CONSTRAINTS`, `TASK`, `INPUT`, `OUTPUT`, `CAPABILITIES`).
  - `role_v1` states that the coach is an AI skills coach, not a therapist, counselor or crisis service, with a warm, calm tone (brainstorm sections 1, 7, 11.2).
  - `constraints_v1` holds the scope and safety rules: no diagnosis, no medication advice, no trauma processing, refer out, and say they always win over the rest of the prompt (brainstorm sections 3, 7, 11.5).
  - `task_v1` states the job and holds the 10 conversation principles from the brainstorm's "System prompt block" (section 3), verbatim.
  - `input_v1` describes what the model receives and marks the user's text as data, never instructions (`.claude/rules/ai-core.md`).
  - `output_v1` holds the spoken-reply format: short, one idea per turn, plain words, no formatting (section 6).
  - `capabilities_v1` holds the 4 MVP skills (Thought Record, TIPP, Opposite Action, DEAR MAN), each with its name, what it's for and when to use it (section 4), how to offer one skill as a choice, and what the coach cannot do. It has **no step-by-step instructions**: the brainstorm doesn't define steps, and clinical content is never invented.

  The prompt text uses no markdown formatting (headings, bold, bullets) and no list-formatted example replies. Numbered rules, as in the principles block, are fine because they are instructions, not replies.

**Conversation**
- **FR8:** The core exposes one respond operation. It takes the user's text and streams back the coach's reply. It keeps conversation history in memory and resends all of it on every call. The core has no web or terminal code, so later doors (voice, API) can reuse it.
- **FR9:** The fixed greeting is shown by code, not generated by the model. It is recorded in history as the coach's first message, so the model knows it already introduced itself.

**CLI**
- **FR10:** The CLI has these commands:
  - `/reset` clears history and shows the greeting again.
  - `/quit` exits cleanly.
  - `/stats` prints, for every turn in the current conversation: turn number, TTFT, total time, input tokens, output tokens, and whether the reply was truncated.
  - Any other input starting with `/` shows "Unknown command. Try /reset, /stats or /quit." and is not sent to the model.

**Failures**
- **FR11:** If the model call fails after its configured retries (timeout, quota, network, auth), the CLI shows exactly: "I'm having trouble right now. Give me a moment and try again."
  - The failed turn is not added to history, neither the user's message nor anything else.
  - The fallback line is never stored in history or sent to the model.
  - The failure is logged once, as an `external` category error.

**Logging**
- **FR12:** Every model call writes one local `llm_call` log event with these fields:
  - prompt version string and prompt hash
  - model name, temperature and thinking level
  - turn number
  - TTFT and total time in ms
  - input and output tokens
  - input length in characters
  - flags: `truncated`, `usage_missing`, `blocked`

  The event never contains user text, reply text or prompt text.

### Non-Functional

- **NFR1 (privacy):** No conversation text appears in any log output. Conversation text is mental-health content, even in testing. It exists only in the terminal and in memory.
- **NFR2 (testability):** Tests use a fake chat model and need no API key and no network. The fake records the messages it receives, so tests can check what was sent. Slice 2's invariant test reuses the same pattern.
- **NFR3 (reproducibility):** A recorded number can always be traced back to the exact prompt that produced it, through the prompt version and hash.
- **NFR4 (swappability):** Changing the model or vendor is a settings change, not a code change, as far as LangChain supports it. Slice 6 compares models from at least two vendors.

## UX Requirements

- Startup failures (bad settings, bad registry) print one clear message naming what's wrong and how to fix it. They never print the API key.
- Streaming output appears as it arrives, not all at once at the end.
- Ctrl-C while a reply is streaming cancels that turn and returns to the prompt. Ctrl-C at the prompt exits.
- `/stats` is readable in a normal terminal width.

## Constraints

- **Stack:**
  - Python 3.14
  - `uv`
  - LangChain, with the Google GenAI integration for Gemini
  - structlog, pydantic-settings and pytest, all already in the repo
- **Scope:** no database use in 1a. History lives only in memory and is lost when the CLI exits.
- **Libraries:** LangChain and Google GenAI APIs change often. Check names and options against current docs during planning.
- **Content:** prompts must not invent clinical claims. Skill content comes from the brainstorm, which cites its sources.

## Blockers

- **B1 (resolved):** `docs/brainstorming.md` is in the repo. It provides the safety scope, the 10 principles and the 4 MVP skills with when to use each. It has no skill steps, so `skills_v1` has none either (FR7).
- **B2 (assumption, verify):** LangChain and `langchain-google-genai` install and import cleanly on Python 3.14. If they don't, the plan has to change before any other step.
- **B3 (assumption, verify):** Gemini through LangChain reports token usage while streaming. It may need an option turned on. If usage is still unavailable, EC8 applies.
- **B4 (assumption, verify):** It's not yet known how Gemini signals a safety-filter block or an empty reply through LangChain. EC9 depends on detecting it.

## Edge Cases

- **EC1:** The user enters empty or whitespace-only input -> it is ignored: no model call, nothing added to history, the prompt is shown again.
- **EC2:** The user presses Ctrl-C while a reply is streaming -> the stream stops, nothing from that turn is kept in history (neither the user message nor the partial reply), and the CLI returns to the prompt. Ctrl-C at the prompt exits cleanly.
- **EC3:** The reply hits the max output tokens limit and is cut off -> the cut-off reply is shown and kept in history as-is, and the log event has `truncated=true`.
- **EC4:** The API key or model name is missing or invalid in settings at startup -> the CLI exits before the greeting with a message naming the setting, and never prints the key. An API key that is present but rejected on the first call follows EC5.
- **EC5:** The model call fails after retries (timeout, rate limit/quota, network, rejected key) -> the CLI shows the fixed fallback line (FR11), history is unchanged, one `external` error is logged, and the session continues.
- **EC6:** A prompt file's content no longer matches its locked hash -> startup fails with a message naming the block and version and saying to add a new version instead.
- **EC7:** The active set references a block, version or file that doesn't exist, or a version lacks its date or changelog note -> startup fails with a message naming the set, block and version.
- **EC8:** A streamed reply arrives without token usage (assumption, verify) -> the turn succeeds and the log event has empty token fields and `usage_missing=true`. `/stats` shows the tokens as unknown for that turn.
- **EC9:** Gemini returns an empty reply or blocks it with its own safety filter (assumption, verify) -> the CLI shows the fallback line, nothing from the turn is kept in history, and the log event has `blocked=true` and the block reason, with no text.
- **EC10:** The user types an unknown slash command such as `/help` -> the CLI shows "Unknown command. Try /reset, /stats or /quit." and the input is not sent to the model.
- **EC11:** The user pastes a very long message (thousands of characters) -> it is sent as-is, and the log event records its length in characters only.
- **EC12:** The user runs `/stats` before any turn -> the CLI shows that there are no turns yet.
- **EC13:** The user runs `/reset` -> history holds only the greeting, `/stats` starts empty, and turn numbering restarts at 1.
- **EC14:** The registry command is run without a changelog note, or for a block that doesn't exist -> the command refuses and the registry is unchanged.
- **EC15:** A block's text contains a literal `{` or `}`, or a placeholder its version doesn't declare -> startup fails with a message naming the block, the version and the unexpected variable. A new version can escape the braces (`{{ }}`) or declare the variable.

## Acceptance Criteria

- [ ] **AC1:** Starting the CLI with valid settings and a valid registry prints the fixed greeting. A real conversation of at least 5 minutes with Gemini runs with streamed replies.
- [ ] **AC2:** The system prompt sent to the model is the compiled active set, in the order `role → constraints → task → input → output → capabilities`. It starts with the role block, followed directly by the constraints block (fake-model test).
- [ ] **AC3:** The messages sent on turn 2 contain the greeting, turn 1's user message and turn 1's reply, in order (fake-model test).
- [ ] **AC4:** Each turn writes exactly one `llm_call` event with all FR12 fields, including the prompt version string and hash (test).
- [ ] **AC5:** Across a multi-turn fake conversation, no captured log record contains any user text, reply text or prompt text (test).
- [ ] **AC6:** Changing the content of an existing prompt version without adding a new version makes startup fail with a message naming the block and version (test).
- [ ] **AC7:** The registry command adds a new version with a locked hash, date and changelog note. It refuses without a note (test).
- [ ] **AC8:** A model failure shows the exact fallback line, leaves history unchanged, logs one `external` error, and lets the next turn proceed normally (fake-model test).
- [ ] **AC9:** `/reset`, `/quit`, `/stats` and the unknown-command message behave as in FR10, EC10, EC12 and EC13 (test).
- [ ] **AC10:** Empty input, Ctrl-C mid-stream, truncation, missing usage and a blocked reply behave as in EC1, EC2, EC3, EC8 and EC9. The CLI-interaction cases are tested where practical, and verified by hand otherwise.
- [ ] **AC11:** Missing API key or model name stops startup before the greeting, without printing the key (test).
- [ ] **AC12:** All tests pass with no API key set and no network access.
- [ ] **AC13:** From one real session of at least 20 turns, `/stats` lets the developer record median and worst TTFT and input tokens at turn 1 vs turn 20. These are written down with the model name, date and prompt hash, next to a prediction made before the run.
- [ ] **AC14:** The compiled prompt is a LangChain chat prompt template. Filling it with a history and a user message gives the system text first, then the history in order, then the user message. A block whose detected variables differ from its declared variables makes startup fail (test).

## Out of Scope

- **Langfuse tracing and masking:** slice 1b. 1a records numbers in local logs only.
- **Seed evals and rule checks:** slice 1c. 1a has no quality measurement beyond the developer's own conversation.
- **The safety gate:** slice 2. Until then the coach must not be shared with anyone.
- **RAG, tools, the session graph, persistence:** slices 3, 4 and 5.
- **Choosing a prompt set from env or the command line:** slice 6 adds this when it needs A/B runs.
- **Context trimming or summaries:** history is resent in full on purpose, so its cost can be measured. The fix belongs to slice 5.
- **Skill steps and guided practice:** the coach can name and offer a skill but not walk through it. Sourced step-by-step content comes with the skills library (slice 3), and one-step-per-turn practice comes with the session graph (slice 5).
- **The auth module and other HTTP modules:** `app/modules/auth/` stays empty. Auth, profile and consent belong to slice 11.
- **Voice, API endpoints, the mobile app:** later phases.
