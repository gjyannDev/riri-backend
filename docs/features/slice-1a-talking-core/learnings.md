# Learn: The talking core (slice 1a)

**Concepts:** LangChain chat models and `init_chat_model`, streaming with `.stream()`, `ChatPromptTemplate` + `MessagesPlaceholder`, a versioned prompt registry, stateless models with resent history, TTFT and token cost per turn, text-free observability. **Status:** built and verified 2026-11-24 (211 tests after the review fixes, ruff clean, short live runs). The real 20-turn session (step 9) is **pending**, so the TTFT median/worst and turn-20 token numbers are not in yet.

## 1. Why it exists

Every later slice (safety gate, RAG, tools, the session graph, voice) wraps one core: take the user's text, ask a model, stream the reply back. Slice 1a builds only that core, so its cost and speed can be measured before anything is added on top.

The first real numbers already show the main cost driver. On turn 1, the model received **1065 input tokens** for an 8-character message with the six-section prompt (915 with the first four-block prompt) (`uv run python -m app.entrypoints.cli`, `gemini-3.5-flash-lite`, prompt hashes `aa5966c524f5` and `8246e52b30a1`, 2026-11-24). Almost all of that is the system prompt plus the greeting. The model is stateless, so every turn resends the system prompt and the whole history.

## 2. What it is

A `Coach` object holds the conversation in memory and has one operation: `respond(text)`, which streams the reply. Its prompt comes from a registry of versioned text blocks with locked hashes, compiled into a LangChain chat template. The model comes from one factory that reads `LLM_*` settings. Every model call writes one `llm_call` log event with numbers only, never text.

```
CLI line ──> CliSession.handle ──> Coach.respond(text)
                                     │  template.invoke({history, user_text})
                                     │    = [system: ROLE, CONSTRAINTS, TASK, INPUT, OUTPUT, CAPABILITIES]
                                     │      + history (greeting, user 1, reply 1, ...)
                                     │      + human: text
                                     ├─> model.stream(...)  ── chunks ──> CLI prints them
                                     └─> after the last chunk: commit history, log llm_call
```

## 3. When to use it

| Do this | When | Why / limit |
|---|---|---|
| Call `build_coach(settings)` | Any new door (voice worker, HTTP) | It checks settings and the registry before any model call, so every door gets the same core |
| Add a prompt version with `app.scripts.prompts add` | Any prompt text change | Editing a registered file in place breaks the hash check, so startup stops |
| Read `/stats` or `logs/cli.log` | Measuring TTFT and tokens | Numbers carry the prompt version and hash, so a number always traces back to its prompt |
| Use `SpyChatModel` from `tests/fakes/` | Any engine test | No key, no network; it records what the model received |

**I'd revisit this when** a voice door needs async streaming (slice 7: add an async `respond` beside the sync one), or input tokens grow enough per turn that resending all history is too slow or costly (slice 5: trimming or summaries).

## 4. How it works

| Option | Trade-off | Chosen |
|---|---|---|
| Plain chat model + own `Coach` class | Every step visible; retries and timeouts come from the model | Yes |
| `create_agent` with no tools | An agent loop with nothing to loop over | No (tools are slice 4) |
| LangGraph now | State, checkpointer, nodes before any need | No (slice 5) |
| JSON manifest for the registry | Standard library reads and writes it | Yes (TOML needs a writer dependency) |
| `ChatPromptTemplate` for assembly | Teaches the LangChain idiom; a history placeholder | Yes, with a declared-variables check against stray braces |
| Six section blocks (role, constraints, task, input, output, capabilities) | Each section versions on its own; about 150 more input tokens per turn than the first four-block layout | Yes (user decision), constraints placed second so safety and scope still lead; the four-block layout stays as set `coach_4block` |

One turn through the real code:

1. `app/entrypoints/cli.py:80`: `CliSession._reply` wraps `coach.respond(text)` in `contextlib.closing`, so Ctrl-C closes the stream.
2. `app/coach/conversation/coach.py:73`: `respond` delegates to `_stream` with `yield from`; `_stream` (`coach.py:115`) runs `(template | model).stream({"history": ..., "user_text": ...})`, merges chunks with `+` and records TTFT at the first chunk with text.
3. The template was built once in `app/coach/prompts/prompt_registry.py:55` (`ChatPromptTemplate.from_messages`: system, `MessagesPlaceholder("history")`, human `{user_text}`). Startup validation checks every block's hash (`prompt_registry.py:159`) and template variables, and `compile_active_set` (`prompt_registry.py:38`) refuses a variable nothing supplies.
4. The model came from `app/coach/llm/model_factory.py:27` (`init_chat_model`); `thinking_level` is added only for `google_genai` (`model_factory.py:31`).
5. After the stream ends, `read_reply` (`app/coach/llm/llm_response.py:49`) turns the merged chunk's `usage_metadata` and `response_metadata` into tokens, `truncated` and a block reason.
6. A blocked or empty reply raises (`coach.py:76`). Otherwise the turn is committed to history (`coach.py:87`) and stats.
7. Provider exceptions become the app's `external` errors, raised `from None` so the provider's message never travels with them (`coach.py:101`-`111`). The single `llm_call` event is written in `finally` (`coach.py:113`), so ok, cancelled (`coach.py:98`), failed, blocked and error (an unexpected bug) each log exactly once. A failed event carries `error_type`, the exception class name, never its message.

## 5. What can go wrong

| Failure | What the user sees | What the code does | Proof (test name) |
|---|---|---|---|
| Timeout, quota, network, bad key | "I'm having trouble right now. Give me a moment and try again." | Maps to `ExternalTimeoutError` / `ExternalRateLimitedError` / `ExternalServiceError`, keeps history, logs one `failed` event | `test_model_error_raises_external_keeps_history_and_logs_one_failure`, `test_a_model_failure_shows_the_fallback_line_and_the_session_continues`, `test_provider_errors_map_to_external_errors` |
| Ctrl-C mid-reply | Back at the prompt | Stream closed, nothing kept, `cancelled` logged | `test_closing_the_stream_early_keeps_nothing_and_logs_cancelled`, `test_ctrl_c_mid_stream_cancels_the_turn` |
| Reply hits max tokens | The cut-off reply | Kept in history, `truncated=True` | `test_truncated_reply_is_kept_and_flagged` |
| Safety block or empty reply | The fallback line | Nothing kept, `blocked` logged with the reason | `test_blocked_or_empty_reply_raises_keeps_nothing_and_logs_blocked` |
| Prompt file edited in place | Startup refuses, naming set, block and version | Hash mismatch raises `PromptRegistryError` | `test_edited_content_without_a_new_version_fails` |
| Stray `{` in a prompt | Startup refuses, naming the brace | Declared-variables check | `test_undeclared_variables_and_stray_braces_fail` |
| Missing key or model | One message naming the setting, no greeting | `CoachConfigError`, never prints the key | `test_missing_setting_is_named_without_the_key`, `test_main_exits_before_the_greeting_when_settings_are_missing` |
| A bad value in `.env`, for example `LLM_THINKING_LEVEL=max` | One line: `Cannot start the coach: invalid setting LLMSettings.thinking_level: ...`, exit code 1, no greeting | The CLI guards the imports that load settings and turns the validation error into that one message | `test_an_invalid_setting_prints_one_clear_line_instead_of_a_traceback` |
| A bug in our own code during a reply | The traceback | Logged as outcome `error` at error level, not `cancelled` | `test_a_bug_inside_respond_is_logged_as_an_error_not_a_cancel` |
| A prompt block declares a variable nothing supplies | Startup refuses, naming set, block, version and variable | `compile_active_set` checks declared variables against `allowed_variables` | `test_compile_refuses_variables_the_caller_does_not_supply` |
| Conversation text in logs | — | Only numbers and codes are logged | `test_no_log_record_contains_conversation_or_prompt_text` |
| Wrong vendor option (`thinking_budget` on Gemini 3.x) | Every call fails with HTTP 400 | Factory now sends `thinking_level` | `test_gemini_gets_every_setting_plus_thinking_level` |

## 6. Try it yourself

1. Predict the input tokens on turn 2 of a short chat: turn 1's 1065 plus what? Then run `uv run python -m app.entrypoints.cli`, send two short messages, run `/stats`, and compare.
2. Predict what happens if you change one word in `app/coach/prompts/blocks/output_v1.md` and run `uv run python -m app.scripts.prompts check`. Run it, then undo the edit with `git checkout -- app/coach/prompts/blocks/output_v1.md` (or retype the word, since the file is not committed yet).
3. Predict the TTFT with `LLM_THINKING_LEVEL=low` compared with `minimal`. Run ten turns of each and compare the `/stats` medians.
4. Set `LLM_MAX_TOKENS=5` in `.env`, send a message, and predict what `/stats` shows in the `truncated` column.

## 7. What surprised me

- **Gemini 3.x rejects `thinking_budget`.** Any request with it fails with 400 INVALID_ARGUMENT, so the setting became `thinking_level` (spike, `gemini-3.5-flash-lite`, 2026-11-24).
- **The model ignores temperature.** The library warns that this model uses fixed sampling; the configured value is still logged.
- **A bad API key returns HTTP 400, not 401** (`ModelInvalidRequestError`).
- **Timeouts are not LangChain errors.** They surface as `httpx2.ConnectTimeout` from google-genai's transport, so the adapter maps those too.
- **Model names get retired.** `gemini-2.5-flash`, the example I first wrote into `.env.example`, now answers 404 "no longer available" (checked 2026-11-24). Docs should call a model name an example and say names change.
- **My own fix broke the normal path.** In the review I defaulted the log level to `error` so unexpected bugs would stop looking like cancelled turns; every successful turn then logged at error level. An existing test failed at once. That is the value of testing log behaviour: it catches changes that look harmless in the code.
- **Usage arrives without asking.** Each chunk carries delta `usage_metadata`; `chunk + chunk` sums them.
- **TTFT is almost the total time for short replies.** Two smoke runs: TTFT 973.3 ms / total 974.5 ms, and 1063.2 ms / 1064.4 ms (`gemini-3.5-flash-lite`, hash `8246e52b30a1`, 2026-11-24). A short reply arrives as essentially one chunk.
- **The six-section prompt costs about 150 tokens a turn.** Turn 1 went from 915 to 1065 input tokens (TTFT 896.5 ms, hash `aa5966c524f5`, 2026-11-24). Because the system prompt is resent every turn, that is about 150 extra tokens on every turn, not once.
- **History cost grows in a straight line, total cost faster.** First real run, 6 turns (`gemini-3.5-flash-lite`, hash `aa5966c524f5`, 2026-11-24): input tokens 1068 -> 1341, about +55 per turn (the previous reply plus the new message). Projected turn 20: about 2,100. The 6 calls together sent 7207 input tokens, because every call resends everything.
- **TTFT stayed flat at about 1 second** (median 1023.7 ms, best 892.4, worst 1150.9) while input grew from 1068 to 1341 tokens. At this size, waiting time is the round trip and model start, not prompt length.
- **Short replies barely stream.** On 3 of 6 turns the whole reply arrived within 2 ms of the first token; on the others, within 80 ms. Worth remembering for voice: streaming helps long replies, not 30-50-token ones.
- **Logs and streaming fight over stdout.** The coach logs when the stream ends, which is before the CLI prints its newline, so log lines were glued to replies. The CLI now logs to `logs/cli.log`.
- **Pending (step 9):** the full session of 20+ turns with predictions written first (median and worst TTFT, input tokens at turn 1 vs turn 20), and the Ctrl-C, `/reset` and bad-key checks by hand. Done so far: a 6-turn run (above) and the real-log privacy check (no text in `logs/cli.log`).

### Eval log (AI features only)

| # | Run (date, session) | What changed | Versions | Pass | Errors | Task metrics | Tokens in / out | Failures → type | Decision |
|---|---|---|---|---|---|---|---|---|---|

- No eval runs yet. Seed evals are slice 1c; the first row will be the baseline for `coach_default:role@v1,constraints@v1,task@v1,input@v1,output@v1,capabilities@v1` (hash `aa5966c524f5`).

## 8. Check your understanding

1. Why: why is history committed only after the stream completes?
2. When: when must you add a new prompt version instead of editing the file?
3. How: how does the coach know a reply was cut off, and where is that vendor detail read?
4. What if: what if a bug in our code raised `KeyError` inside the stream? Would the user see the fallback line?

<details>
<summary>Reference answers (write yours first)</summary>

1. So that a failed, blocked or cancelled turn leaves no trace: no half-reply in history, and the next turn's prompt is exactly as if the failed turn never happened (EC2, EC5, EC9).
2. Always, for any change to a registered version, even one word. The hash locks the text so every recorded number traces back to the exact prompt; editing in place stops startup with a hash error.
3. Gemini's last metadata chunk has `finish_reason="MAX_TOKENS"`, which LangChain normalizes to `normalized_finish_reason="length"`. Only `app/coach/llm/llm_response.py` reads it (`read_reply`).
4. No. `PROVIDER_ERRORS` holds only provider exception types, so a `KeyError` propagates as a real bug instead of being disguised as an outage (`test_programming_errors_are_not_provider_errors`). The `llm_call` event still logs once, with outcome `error` at error level (it used to say `cancelled`, which hid the bug in the logs).
</details>

## 9. Go deeper / Still open

- Spec: `docs/features/slice-1a-talking-core/spec.md`. Plan: `plan.md`. Progress, spike findings and deviations: `task.md`.
- Next: slice 1b (tracing with masked content), slice 1c (seed evals), slice 2 (the safety gate before any model call).
- Still open:
  - step 9's real session and numbers (**pending**): median and worst TTFT, input tokens at turn 1 vs turn 20, next to your predictions (AC1, AC13)
  - whether to keep the emergency-line stopgap in `constraints_v1` (user decision)
  - B4 was not observed live: no real safety block was triggered, so block detection relies on the library's finish-reason mapping
  - open review findings: see the Review section in task.md (R2 tracing guard in the core, R4 declare `httpx2`, R5 the real session, R7 blocked text streamed before the block is seen, R10 to R13 cleanups and prompt wording)
  - type checking: `uv run pyright` (a dev dependency since the review) now checks `app` and `tests`; the editor's Pylance still shows more detail for files you have open
