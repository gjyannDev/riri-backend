# Learn: Slice 1, Text coach on LangChain (1a talking core, 1b tracing, 1c seed evals)

One learnings file for the whole of slice 1, as `docs/ai-engineering-learning-path-v2.md` asks. 1a's own notes stay in `docs/features/slice-1a-talking-core/learnings.md`; this file adds 1c and the concept 14 write-up from 1b, and holds the slice 1 number.

Status: the 1c code is built and tested with fakes, and the baseline run against the real model is done (2026-11-25, eval log row 1). Still **pending**: a repeat run, the prediction exercises 2-4, and the concept 14 section, which needs a real Langfuse trace (1b R1).

**The slice 1 number:** one_question 30/30, no_markdown 30/30, no_fake_empathy 30/30, 0 errors, on `gemini-3.5-flash-lite`, prompt `coach_default:role@v1,constraints@v1,task@v1,input@v1,output@v1,capabilities@v1`, hash `aa5966c524f5`, 2026-11-25 (`uv run python -m app.scripts.run_seed`, default 5 s pause). Results: `docs/features/slice-1c-seed-evals/results/2026-11-25-aa5966c524f5.md`.

## 1. Why it exists

After 1a and 1b the coach talks and is traced, but nobody had measured whether its replies follow the spoken-coach style: at most one question, no lists or markdown, no fake empathy ("I understand exactly"). Without a number, a prompt change can only be judged by feel. 1c gives a baseline that later prompt versions and models are compared against.

## 2. What it is

- `evals/seed_v1.jsonl`: 10 synthetic messages, one per type (angry, numb, rambling, one-word, resistant, anxious, ashamed, sad, skill request, vague). Written fresh, no crisis content because there is no safety gate until slice 2.
- `app/evals/seed_rules.py`: three pure rule checks, `reply -> bool`, and `RULES` naming them in report order.
- `app/evals/seed_messages.py`: loads and validates the seed file before any model call.
- `app/evals/seed_runner.py`: `run_seed()` runs each message 3 times in a fresh conversation, scores the reply, pauses between calls, records errors.
- `app/evals/seed_report.py`: the pass table, the committed results file, the local JSONL.
- `app/scripts/run_seed.py`: the hand-run door. `uv run python -m app.scripts.run_seed [--pause-seconds 5]`.

## 3. When to use it

- After any change to a prompt block (new registry version, new hash), and after a model change. The results file name holds the date and the prompt hash, so the old and new runs sit side by side.
- Not in CI and not from `pytest`: it calls the real model and costs a little. Tests use the fake model.
- Not for safety, scope or tone. The checks are literal; tone and scope need a judge (slice 6).

## 4. How it works

Decisions:
- Literal checks, not an LLM judge: the same reply always gets the same verdict, so the only variation between runs comes from the model. Three runs per message show that variation.
- An error (provider failure, block, empty reply) is neither a pass nor a fail. Pass rates use scored runs as the denominator and the table shows the error count beside it.
- No retry inside the script. A rate limit is recorded as an error; rerun with a larger `--pause-seconds`.
- Run info (model, prompt version, hash, session id) is read from the built `Coach`, not recomputed, so the table records what the run actually used.

One run, through the code:
1. `main()` parses `--pause-seconds` (`app/scripts/run_seed.py:38` rejects negative, NaN and infinite values), loads the seed file (`app/evals/seed_messages.py:25`) and builds the coach through `build_coach`.
2. `run_seed()` (`app/evals/seed_runner.py:32`) loops over 10 messages x 3 runs. Before every run except the first it sleeps (`seed_runner.py:50`).
3. `_run_once()` calls `coach.reset()` (`seed_runner.py:68`), so the model sees only the system prompt, the fixed greeting and this one message. A coach `ExternalServiceError` becomes an error run (`seed_runner.py:72`).
4. The reply goes through `one_question` (`app/evals/seed_rules.py:12`), `no_markdown` (`seed_rules.py:17`) and `no_fake_empathy` (`seed_rules.py:24`). A progress line and a `seed_run` log event carry ids and verdicts only. `on_result` (`seed_runner.py:63`) hands each result to the script straight away, so Ctrl-C still leaves partial results.
5. At the end `coach.close()` flushes tracing (`run_seed.py:99`), `render_report()` (`app/evals/seed_report.py:23`) builds the table, and `write_report()` (`seed_report.py:93`) writes both files. On Ctrl-C only the partial JSONL is written and the exit code is 130 (`run_seed.py:93`).

## 5. What can go wrong

| Risk | What happens | Test |
|---|---|---|
| History leaks between runs | Each run resets the coach | `test_each_message_runs_three_times_in_a_fresh_conversation` |
| A rate limit or block counts as a pass | It becomes an error run with the error code | `test_a_failed_blocked_or_empty_reply_is_an_error_run_and_the_loop_goes_on` |
| Calls too fast for the rate limit | One pause between every pair of runs, including after errors | `test_it_pauses_after_every_run_but_the_last_including_error_runs` |
| Reply or message text in logs | Logs and progress lines carry ids and verdicts only | `test_progress_lines_and_logs_carry_ids_and_verdicts_never_text` |
| A bad seed file wastes a run | It stops before the coach is built | `test_a_bad_seed_file_stops_before_the_coach_is_built` |
| A missing key leaks in the error | The message names the setting only | `test_a_failing_build_stops_before_any_call_and_shows_no_secret` |
| Ctrl-C loses traces or writes a half table | Coach closed, no results file, partial JSONL kept | `test_ctrl_c_closes_the_coach_writes_no_results_file_and_keeps_partial_runs` |
| A rerun silently replaces an old baseline | Only the same date and hash overwrite | `test_a_new_hash_or_date_keeps_the_old_files` |

What the rule checks cannot see (known gaps, written down instead of tuned away):
- Two questions joined into one sentence with one `?` ("what happened and how do you feel?") pass `one_question`.
- A question without a `?` ("tell me what happened") is not a question to the check; a rhetorical `?` is.
- `no_fake_empathy` checks one literal phrase. "I know exactly how you feel" passes.
- `no_markdown` allows a dash in the middle of a line ("I'm here - take your time") and an emoji or a long monologue. Length and pacing are not checked at all.

## 6. Try it yourself

Write each prediction down before you run.

1. Run `uv run python -m app.scripts.run_seed`. Predict: which rule fails most, and on which message types? Result (2026-11-25): none failed, 30/30 on every rule. No prediction was written down first, so this one can't be checked against a guess.
2. Run it again with nothing changed. Predict: the same failures, or different ones? Result: **pending** (this tells you which failures repeat and which are noise).
3. Run it with `--pause-seconds 0`. Predict: how many errors, and from which run on? Result: **pending**.
4. Open the local `logs/seed-<date>-<hash>.jsonl` and find the reply with the highest `ttft_ms`. Predict: is it the rambling message? Result: **pending**.

## 7. What surprised me

From building 1c:
- An empty or whitespace reply never reaches the runner as text: `Coach` already turns it into an `external` error (`app/coach/llm/llm_response.py:61`), so the runner needs no empty-reply check of its own.
- "Fresh conversation" still starts with the greeting. Every seed reply is the coach's answer to its own greeting plus the user's message, which matches the CLI.
- `?!?` had to be one question, not two, which a plain `\?+` count gets wrong. The spec's edge case caught it before the real run did.

From the real run (2026-11-25, `logs/seed-2026-11-25-aa5966c524f5.jsonl`):
- A perfect score on the first try: 30/30 on all three rules, no errors, no rate limits at the default 5 s pause. The prompt's style rules hold on single first replies.
- All 30 replies end with exactly one `?`; none has zero. The coach always closes on a question, even for the skill request (m09), where an answer could come before a question.
- No reply contains "exactly" or "understand" at all, so the fake-empathy check never had a near-miss to judge. It passed by never coming close, which is weaker evidence than catching and passing near-misses.
- 28 of 30 replies put a blank line between sentences. Not markdown, so `no_markdown` correctly passes them; for voice (slice 7) a paragraph break is just a pause, but it is formatting the model chose on its own.
- The one-question gap is real: about 14 of 30 replies end with a choice joined by "or" under one `?`, for example m04 run 1: "Would you like to tell me a bit more about what's making you feel so tired, or would you rather just take it easy?" The literal check passes them. That count comes from a rough regex (`, or ... ?` on the last line), not a hand read. Whether an "A or B?" choice breaks "one question per turn" is a decision for the rubric in slice 6, not for this check.
- Size: input tokens 1066-1139 per call (average 1089, almost all of it the system prompt and greeting), output 22-51 (average 37), replies 32 words on average, 46 at most. Time to first token median 860 ms, max 1447 ms.

### Eval log (AI features only)

| # | Run (date, session) | What changed | Versions | Pass | Errors | Task metrics | Tokens in / out | Failures → type | Decision |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-11-25, `run_seed`, 5 s pause | None (baseline) | model `gemini-3.5-flash-lite`, prompt hash `aa5966c524f5`, seed_v1 | one_question 30/30, no_markdown 30/30, no_fake_empathy 30/30 | 0 | ttft median 860 ms, max 1447 ms | 1089 / 37 average per call | none. Gap noted: about 14/30 end with an "A or B?" choice under one `?` (passes the literal check) | Keep the prompt. Rerun once unchanged to see if 30/30 holds; take the "or" choice question to the slice 6 rubric |

### Concept 14: what the framework does in one real turn (from 1b AC14)

**Pending 1b R1:** needs Langfuse keys in `.env` and one real traced turn. To record: every LLM call in one turn (expected: one model call), its tokens and latency, and the v1 code each piece replaced (prompt template, message assembly, streaming, usage metadata, the callback handler).

## 8. Check your understanding

1. Why is a blocked reply an error, not a fail?
2. Why does the script read the prompt hash from the coach instead of from the registry file?
3. A rule passes 30/30. Does that mean the coach never breaks the rule?
4. Why three runs per message?

<details>
<summary>Answers</summary>

1. A blocked reply has no text to judge; counting it as a fail would mix provider behavior into a style score, and counting it as a pass would hide it. The error count shows it separately.
2. The table must record what the run used. Reading it from the built coach removes the chance of a mismatch between what was loaded and what is reported.
3. No. It means no reply broke the literal check. The gaps in section 5 still pass, and 30 runs is a small sample.
4. The model is not deterministic. One run per message cannot tell a repeating failure from noise; three can show a pattern cheaply.

</details>

## 9. Go deeper / Still open

- A repeat run with nothing changed (eval log row 2) and the prediction exercises 2-4.
- 30/30 at baseline means these three checks can no longer show an improvement, only a regression. The next useful signal needs harder checks or a judge (slice 6), and harder seed messages.
- 1b R1: the real masked trace check, then the concept 14 section above.
- Later: Langfuse datasets, experiments and evaluators fit slice 6 (conversation evals with a judge). The rule functions here become evaluators unchanged.
- Prompt changes that the failures suggest are new registry versions with a new hash, not part of 1c.
