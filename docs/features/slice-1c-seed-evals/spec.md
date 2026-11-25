# Feature: Slice 1c, Seed evals

Part of slice 1 (Text coach on LangChain) in `docs/ai-engineering-learning-path-v2.md` (row "1c. Seed evals", the "1c done when" list and the "Seed evals" bullet). Slices 1a (talking core) and 1b (tracing) are built. This spec covers 1c only.

## Problem

The coach talks and is traced, but nobody has measured how well its replies follow the spoken-coach style rules: at most one question, no lists or markdown, and no fake empathy such as "I understand exactly". Without a baseline, a later prompt change (a new block version, a new model) cannot be judged as better or worse. Replies are only checked by reading a conversation by eye.

The only user is the developer, who is learning AI engineering by building the coach. The project doubles as a learning path, so the number and the written failures matter as much as the script.

## Goal

A hand-run script sends 10 fixed synthetic messages to the real model, 3 runs each, scores every reply with 3 literal rule checks, and writes a pass table. The developer ends with:

- a pass count per rule out of the runs that produced a reply (30 when nothing errors), with model, date, prompt version and prompt hash
- the failing cases written down in words
- one `docs/features/slice-1/learnings.md` for the whole of slice 1

Measurable outcome (from "1c done when"): the pass count per rule over 30 runs is recorded, the failures are in words, and `learnings.md` exists.

## Project Conventions

Rule files consulted: `.claude/CLAUDE.md`, `.claude/rules/architecture.md`, `.claude/rules/ai-core.md`. Constraints they put on this feature:

- **Tests never reach real services (CLAUDE.md):** the rule checks are pure functions tested on fixed strings, and the script's orchestration is tested with a fake chat model. Only the developer's manual run uses the real model.
- **Privacy (ai-core, Privacy):** never log, trace or store user or coach text unless a spec says so explicitly. This spec says so, narrowly: the seed messages are synthetic, so their replies may be written to the results files described below (see FR9). No log line carries message or reply text.
- **Test data is synthetic (ai-core):** the 10 seed messages are written fresh from the brainstorm list (`docs/brainstorming.md`), never copied from a real person.
- **One core, every door (ai-core):** the script is a door. It builds the coach with `build_coach(settings)` so it uses the same prompt registry, model and tracing as the CLI. It adds no prompt text and no vendor code.
- **Prompts (ai-core):** the registry is locked. If an eval shows the prompt needs changing, that is a new block version through the registry command and a new hash, and it is not part of this slice. Each run records the hash it used.
- **Settings:** only through `app.core.config`, never `os.getenv`. No new settings group is expected.
- **Scripts (architecture):** one-off scripts live in `app/scripts/` and run as `uv run python -m app.scripts.<name>`.
- **Tests (architecture):** mirror the source tree, shared fakes in `tests/fakes/`.
- **Safety (ai-core):** there is no safety gate until slice 2, so the seed messages contain no crisis content.
- **Workflow:** spec first, then `/create-plan`, then `/implement`. The user commits manually.

## User Flow

1. The developer has a working `.env` (model key, and optionally Langfuse keys).
2. The developer runs `uv run python -m app.scripts.run_seed`.
3. The script loads and validates `evals/seed_v1.jsonl`, builds the coach once, and prints the model, the prompt version and hash.
4. For each of the 10 messages, 3 times: it starts a fresh conversation, sends the message, collects the full reply, scores it against the 3 rules, and prints one progress line with ids and verdicts only.
5. At the end it flushes tracing, prints the pass table, and writes the results files.
6. The developer reads the failing replies, writes the failures in words in `learnings.md`, and records the number.

## Requirements

### Functional

- **FR1 Seed file.** `evals/seed_v1.jsonl` holds 10 synthetic messages, one JSON object per line with an `id`, a `type` and the message `text`. The types cover angry, numb, rambling, one-word and resistant, plus five more (anxious, ashamed, sad, a practical skill request, a vague "I don't know"). No crisis content.
- **FR2 Rule checks.** Three pure functions, each taking a reply string and returning pass or fail:
  - **one question:** count groups of consecutive `?` characters; pass when the count is 0 or 1 (`??` counts as one).
  - **no lists or markdown:** fail when any line starts with `-`, `*`, `+`, or a number followed by `.` or `)` and a space, or a line starts with `#`, or the text contains a backtick, `**` or `__`. A number followed by a dot inside a sentence does not fail.
  - **no fake empathy:** fail when the reply contains "I understand exactly", case-insensitive. Only that phrase; near-misses pass.
- **FR3 Runs.** Each message runs 3 times, 30 runs in total. Each run is a fresh conversation (the coach is reset before it), so no history carries over between runs. A fresh conversation still starts with the coach's fixed greeting, as in the CLI, so every reply is measured as an answer to the greeting.
- **FR3a Pause between runs.** The script waits between model calls so a provider rate limit is not hit. The wait is a command-line option `--pause-seconds` (a number, default 5, `0` means no wait). The wait happens after every run except the last, and also after a run that ended in an error. The option is a script argument, not an app setting, because it only concerns this manual script. The existing model retry settings are unchanged.
- **FR4 Scoring.** A reply is scored against all 3 rules. A run that produced a non-empty reply is "scored"; a run that did not is an "error" and is neither pass nor fail.
- **FR5 Errors.** A model failure, a provider block, or an empty or whitespace-only reply makes that run an error. The script records it, keeps going, and shows the error count in the table.
- **FR6 Pass table.** Per rule: passes out of scored runs. Also: the error count, the model name, the date, the prompt version and the prompt hash.
- **FR7 Failure rows.** The committed results file has one row per failing (run, rule): message id, run number, rule, and the reply text. Passing runs get no row.
- **FR8 Result files.**
  - Committed: `docs/features/slice-1c-seed-evals/results/<date>-<hash>.md` (pass table and failure rows).
  - Local, gitignored: `logs/seed-<date>-<hash>.jsonl`, one line per run with the reply, the 3 verdicts, tokens and time to first token, and the Langfuse session id when tracing is on.
  - A rerun with the same date and hash overwrites both files. A different date or hash keeps the old files, so runs stay comparable.
- **FR9 Text in the results files.** The reply text of synthetic seed messages is allowed in the two result files above and in `learnings.md` quotes. Nowhere else: not in log events, not in tracing outside the existing FR14 capture rules of slice 1b.
- **FR10 Seed validation.** The script validates the seed file before any model call (valid JSON per line, required fields, unique ids, exactly 10 rows) and stops with a message naming the line.
- **FR11 Config failure.** If `build_coach` fails (missing key, broken registry, bad tracing config), the script stops before any model call with the existing error message and prints no secret values.
- **FR12 Tracing flush.** When tracing is on, the script calls `coach.close()` at the end, also after an interruption, so the last traces are sent.
- **FR13 Learnings.** `docs/features/slice-1/learnings.md` is written at the end: the number, the failures in words, what each rule check cannot see, and the concept 14 write-up from 1b (see Blockers).

### Non-Functional

- **Run cost and time:** 30 sequential single-turn calls to the real model with a pause between them (default 5 s, so about 3 to 4 minutes of waiting plus call time) and a negligible cost on the current model. No parallelism needed.
- **Determinism of scoring:** the same reply string always gives the same verdicts. The only variation between runs comes from the model.
- **No tuning:** a rule check is never changed to make a run pass. If a check is changed for a real reason (it was wrong), the old results are rerun and the change is written in `learnings.md`.
- **Privacy of logs:** structured log events from the script carry ids, counts and verdicts only.

## UX Requirements

- Terminal only. One progress line per run, such as `m03 run 2: one_question=pass no_markdown=fail no_fake_empathy=pass`, no reply text.
- Errors name the message id, run number and the error class, not the text.
- The final table is printed in the terminal and equals the committed file's table.

## Constraints

- Python 3.14, `uv`, the existing tooling. Windows (PowerShell 5.1 and Git Bash both in use).
- No new dependency.
- Single turn only, no history from earlier turns.
- The developer runs the real eval by hand; it is never run by `pytest` or in CI.

## Blockers

- **The real run needs the developer:** a model key in `.env`, and the run itself. Implementation can finish with fakes, but the slice is not done until the real numbers exist.
- **Concept 14 write-up (1b AC14):** the `learnings.md` section on every LLM call in one real turn needs the real Langfuse trace check (1b R1). That needs Langfuse keys in `.env`, which were missing when 1b was built. If the keys are still missing at the end, that section is marked pending and tracked in the 1b `task.md`.
- Not blockers, but untouched here: 1a R5 (the real 20-turn session) and 1a R12 (prompt wording).

## Edge Cases

Format: condition -> expected outcome.

- **EC1:** the model call raises an error for a run -> that run is an error, the script continues, the error count shows in the table.
- **EC2:** the provider blocks a message (safety block) -> same as EC1; the run is an error, not a pass.
- **EC3:** the reply is empty or whitespace only -> the run is an error, not scored.
- **EC4:** `build_coach` fails, for example a missing key -> the script stops before any call and names the missing setting without its value.
- **EC5:** the seed file has a bad JSON line, a missing field, a duplicate id, or not 10 rows -> the script stops before any call and names the line or the problem.
- **EC6:** a reply has `??` or `?!?` -> the consecutive `?` group counts as one question.
- **EC7:** a reply has two questions with only one `?` (for example "what happened and how do you feel?") -> passes the one-question rule. Known gap of the literal check, to be noted in `learnings.md`.
- **EC8:** a reply has "in step 1. then" mid-sentence, or "5-4-3-2-1" inside a sentence -> does not fail the markdown rule. A line that starts with `1. ` or `- ` does.
- **EC9:** a reply says "I UNDERSTAND EXACTLY" -> fails. "I understand how hard that is" or "I know exactly how you feel" -> passes, because only the literal phrase is checked.
- **EC10:** a rerun on the same date with the same prompt hash -> both result files are overwritten.
- **EC11:** a rerun with a different prompt hash or a different date -> the old result files stay and new ones are written.
- **EC12:** the developer presses Ctrl-C mid-run -> the script stops, calls `coach.close()`, writes no committed results file, exits non-zero, and leaves the partial local JSONL. (Default chosen here; tell me if you want partial results kept.)
- **EC13:** tracing is off or keys are absent -> the script runs normally and the JSONL has no session id.
- **EC14:** errors occurred in some runs -> pass rates use scored runs as the denominator, and the table shows both the denominator and the error count, so "27/28 with 2 errors" is visible.
- **EC16:** `--pause-seconds` is negative or not a number -> the script stops before any call with a usage message.
- **EC17:** a rate-limit error still happens despite the pause -> it is an error run as in EC1 (no extra retry loop in the script); the developer can rerun with a larger `--pause-seconds`.
- **EC18:** Ctrl-C during a pause -> handled as EC12.
- **EC15:** every rule passes on all runs -> the table and file are still written, and the failures section says there were none.

## Acceptance Criteria

- [ ] **AC1:** `evals/seed_v1.jsonl` has 10 lines, each valid JSON with `id`, `type` and `text`, ids unique, and the types include angry, numb, rambling, one-word and resistant. A test loads the file and checks this. (EC5 covered by validator tests.)
- [ ] **AC2:** the three rule checks are pure functions, each with unit tests on fixed strings covering pass and fail cases, including EC6, EC7, EC8 and EC9.
- [ ] **AC3:** with a fake chat model, the script runs 10 messages x 3 runs = 30 calls, and each call's model input is the system prompt, the coach's fixed greeting (which `Coach` puts first in every fresh history) and that one message, with no earlier run's text. (FR3)
- [ ] **AC4:** with a fake model scripted to produce known replies, the pass table shows the expected per-rule counts, the model name, the date, and the prompt version and hash.
- [ ] **AC5:** with scripted failing replies, the committed results file has exactly one row per failing (run, rule) with message id, run number, rule and reply, and no row for passing runs.
- [ ] **AC6:** with scripted errors (a raised provider error, a blocked reply, an empty reply), those runs are counted as errors, the script finishes, and the table's denominator and error count match (EC1, EC2, EC3, EC14).
- [ ] **AC7:** result file names follow `<date>-<hash>`; a same-name rerun overwrites and a different hash keeps the old file (EC10, EC11), checked with a temp directory.
- [ ] **AC8:** the local JSONL has one line per run with the reply, three verdicts, and the session id only when tracing is on; `logs/` is gitignored (already is) (EC13).
- [ ] **AC9:** no log event emitted by the script contains the message text or reply text; a test captures the log output of a fake run and asserts this.
- [ ] **AC10:** a failing `build_coach` or a bad seed file stops the script before any model call and the message contains no secret value (EC4, EC5).
- [ ] **AC11:** Ctrl-C mid-run calls `coach.close()`, writes no committed results file, and exits non-zero (EC12), checked with a fake that raises `KeyboardInterrupt`.
- [ ] **AC11a:** with a fake clock/sleep, the script waits `--pause-seconds` between runs: 29 waits for 30 runs, including after error runs, none after the last, and none when the value is `0`. Tests never really sleep. A negative or non-numeric value stops the script before any call (FR3a, EC16).
- [ ] **AC12:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check` on the touched files, and `uv run pyright` all pass, and no test reaches a real service.
- [ ] **AC13:** the developer has run the script once against the real model; the committed results file holds the real pass count per rule, model, date and prompt hash.
- [ ] **AC14:** `docs/features/slice-1/learnings.md` exists and contains: the number (pass count per rule), each failing case in words, what each rule check cannot see (including EC7), and the concept 14 section (or an explicit "pending 1b R1" note).

## Out of Scope

- LLM-as-judge scoring, the 20-30 message set from the brainstorm: later slices; 1c is a literal, cheap baseline.
- Crisis, out-of-scope and safety messages: slice 2 owns the gate and its own evals.
- Multi-turn conversations and greeting handling: 1c measures first replies only.
- Changing the prompt to fix failures: that is a new registry version and its own change; 1c only records the baseline.
- CI runs, pass thresholds and automatic gating: the run is manual and the number is a record, not a gate.
- A new settings group, a dashboard, or storing results in the database: the committed markdown and local JSONL are enough.
