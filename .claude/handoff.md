# Handoff: slice 1a (Talking core), ready to implement

Written 2026-11-24 at the end of a planning session. Read this first in a fresh session, then run `/implement` on the plan.

## Where things stand

- **Phase 1, slice 1, sub-slice 1a** of `docs/ai-engineering-learning-path-v2.md`. Slice 1 is split into 1a (talking core), 1b (tracing) and 1c (seed evals).
- Spec and plan are done and agreed. No code has been written yet.
  - `docs/features/slice-1a-talking-core/spec.md`: FR1-FR12, NFR1-NFR4, EC1-EC15, AC1-AC14
  - `docs/features/slice-1a-talking-core/plan.md`: 10 steps, checkpoint every 3, gate commands listed
- Branch is `main`, and everything below is uncommitted. Branch before implementing; commit only when the user asks.

## Uncommitted work from the planning session

| File | Change |
| --- | --- |
| `.claude/CLAUDE.md` | New: project summary, commands, non-negotiables, pointers to rules |
| `.claude/rules/architecture.md` | New: layers (router → controller → service → repository), feature modules with prefixed files (`auth_service.py`), DI via constructors + FastAPI `Depends`, factories, import boundaries, no `utils.py`, tests mirror source |
| `.claude/rules/ai-core.md` | New: engine rules for `app/coach/` (model only from the factory, prompts only from the registry, f-string `ChatPromptTemplate` with declared variables, no text in logs, safety gate from slice 2, fakes in tests) |
| `docs/architecture.md` | Layout, layers, DI and imports sections updated to the new structure |
| `README.md` | Project structure lists `shared/`, `coach/`, `entrypoints/` |
| `docs/ai-engineering-learning-path-v2.md` | Slice 1 split into 1a/1b/1c; paths point to `app/coach/` and `app/entrypoints/` |
| `docs/brainstorming.md` | Added by the user: source of the 10 principles and the 4 MVP skills |
| `docs/features/slice-1a-talking-core/` | spec.md and plan.md |

## Decisions already made (don't re-ask)

- **Provider:** Gemini via Google AI Studio (`langchain-google-genai`), a Flash-class model. The model name and API key are optional in `Settings` but required by `build_coach()`.
- **Structure:**
  - the engine goes in `app/coach/` (`prompts/`, `llm/`, `conversation/`, `coach_factory.py`)
  - the CLI goes in `app/entrypoints/cli.py`
  - the prompt command goes in `app/scripts/prompts.py`
- **Prompt registry:**
  - A JSON manifest (`app/coach/prompts/prompt_registry.json`) with block files in `app/coach/prompts/blocks/*.md`.
  - Each version has a locked hash, a date, a required changelog note and declared variables.
  - Named ordered sets (`coach_default`). The registry alone picks the active set.
  - The `add`/`activate`/`check` command.
  - Hash drift, missing references or variable mismatches stop startup.
- **LangChain usage:**
  - `prompt_registry.py` builds the `ChatPromptTemplate` (system blocks + `MessagesPlaceholder("history")` + human `{user_text}`). It's the only file that creates one.
  - `coach.py` streams the chain `template | model`, with no output parser, because it needs chunk metadata.
- **Coach:**
  - The model, compiled prompt and clock are injected.
  - It owns `GREETING` and `FALLBACK_LINE` ("I'm having trouble right now. Give me a moment and try again.").
  - History is committed only after a completed stream.
  - It raises the existing `external` error classes (`service="llm"`); there is no new error class.
- **Logging:** one `llm_call` event per call with an outcome (`ok`, `cancelled`, `failed`, `blocked`) and numbers only, never text.
- **Skills block:** name, purpose and when to use each of the 4 skills. No steps (none in the brainstorm, and no invented clinical content).
- **Test seams (user-confirmed):** registry public functions, the `Coach` public interface, `CliSession.handle`/`greet`, and `load_settings` with a temp env file.
- **Do not build auth** or any other HTTP module. `app/modules/auth/` stays empty (also saved in memory).

## Verified facts

- On Python 3.14: langchain 1.5.2, langchain-core 1.8.4 and langchain-google-genai 4.5.2 resolve. Imports are still checked in plan step 1.
- `ChatGoogleGenerativeAI` fields: `google_api_key` (alias `api_key`), `max_output_tokens` (alias `max_tokens`), `timeout` (alias `request_timeout`), `max_retries`, `temperature`, `thinking_budget`, `safety_settings`.
- `AIMessage.text` is a property and handles list content. Chunks merge with `+`, and `usage_metadata` sums across chunks.
- `GenericFakeChatModel(messages=iter([...]))` streams by splitting on whitespace and consumes one message per call.
- `app/scripts/gen_error_docs.py` only discovers `app/modules/*/errors.py`, not `*_errors.py`. 1a adds no error classes; the first module that does must fix the discovery.

## Open, optional suggestions (the user hasn't answered)

1. Add Gemini `thinking_budget` to the `llm` settings and log it in `llm_call`. It affects TTFT and tokens, the closing numbers.
2. Make `Coach.respond` async (`astream`) now so slice 7's LiveKit worker doesn't need a rewrite. Costs a dev dependency for async tests.
3. Move the message layout (system/history/user) into the manifest. The recommendation is to wait for slice 2, when a second layout appears.

Ask about 1 and 2 at the start of `/implement` if they still matter; otherwise follow the plan as written.

## What the user does by hand

- Put the Google AI Studio key in `.env` (`LLM_API_KEY`, `LLM_MODEL`) before step 5.
- Write the v1 prompt text in step 4, from `docs/brainstorming.md`.
- Step 5: the spike with the real key. Step 9: the real session, predictions written first, numbers recorded in `task.md`.

## Other context

- **Tracker artifact:** https://claude.ai/artifact/SAEx1ohwU5GgWasg7oHZXY. A per-slice checklist stored in the artifact's database (collection `progress`, docs `s1`…`s12`). Slice 1's checks are grouped by 1a/1b/1c. Its HTML source was in a session scratchpad that `/clear` doesn't keep; re-read the artifact before changing it.
- **The user is learning AI engineering:** they like explanations of the why, LangChain syntax and trade-offs before building.
