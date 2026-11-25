# Implementation Plan: Slice 1c, Seed evals

## Overview
Add a hand-run script that sends 10 fixed synthetic messages to the real coach 3 times each, scores every reply with 3 literal rule checks, and writes a pass table, failure rows and `learnings.md`, so the coach has a measured baseline.

## Architecture & Design
A new `app/evals/` package holds three small modules: the pure rule checks, the run loop (fresh conversation per run, pause, error handling) and the report writer (table, committed results file, local JSONL). `app/scripts/run_seed.py` is a thin argparse wrapper in the style of `app/scripts/prompts.py`: it builds the coach with `build_coach(settings)`, runs, flushes tracing and prints the table. `Coach` gets four read-only properties so a run records what the coach actually used (session id, model name, prompt version, prompt hash) instead of recomputing them.

## Approaches Considered
Spec.md settled the behavior. The layout was the open design choice, decided with the user.

| Approach | Trade-offs | Chosen? |
|----------|-----------|---------|
| A. `app/evals/` package + thin script | Pure checks and the loop are importable and testable; one line added to the architecture layout; nothing in `app/coach` imports it | **Yes**: matches "scripts are thin", keeps the engine free of eval code (architecture.md, Helpers and Imports) |
| B. Everything in `app/scripts/run_seed.py` | Fewest files, no layout change, but about 250 lines mixing three jobs and a script file holding pure logic | No: hard to test at the seams |
| C. `app/coach/evals/` | Eval code next to the engine, but `app/coach` would hold code that imports `coach_factory` above it | No: muddies "engine imports nothing above it" |

Run info: read from the built `Coach` (new properties) rather than recomputed from settings and the registry, because the point is to record what the run used.

## Spec Requirements -> Implementation
- FR1, FR10 (seed file, validation) -> Step 3
- FR2 (rule checks) -> Step 2
- FR3, FR3a, FR4, FR5 (runs, pause, scoring, errors) -> Step 4
- FR6, FR7, FR8, FR9 (table, failure rows, files, text allowance) -> Step 5
- FR11, FR12 (config failure, flush) and the CLI options -> Step 6
- FR13 (learnings) -> Step 8
- Session id and run info access -> Step 1
- Layout and docs updates -> Step 7

## Implementation Steps
Checkpoint interval: none

Gate commands after every step (see Testing Strategy). All paths are relative to the repo root.

1. **Coach read-only run info.** Add `session_id`, `model_name`, `prompt_version`, `prompt_hash` properties to `Coach`; tests that they match the construction values, that `session_id` changes on `reset()`, and that none of them carries text. Files: `app/coach/conversation/coach.py`, `tests/coach/conversation/test_coach.py`. Verify: `uv run pytest tests/coach/conversation/test_coach.py` + gates. Test: first. Seam: the `Coach` public properties.
2. **Rule checks.** Create the package and three pure functions (one question, no lists or markdown, no fake empathy), each taking a reply string and returning a bool, plus a constant naming the three rules in order. Thin vertical slices, one behavior each: no question and one question pass; two questions fail; `??` counts once (EC6); one `?` over two questions passes (EC7); line-start bullets and numbers fail, mid-sentence "1." and "5-4-3-2-1" pass (EC8); bold, heading and backtick fail; the phrase fails case-insensitively and near-misses pass (EC9). Files: `app/evals/__init__.py`, `app/evals/seed_rules.py`, `tests/evals/__init__.py`, `tests/evals/test_seed_rules.py`. Verify: `uv run pytest tests/evals/test_seed_rules.py` + gates. Test: first. Seam 1 (user-confirmed): the three rule functions.
3. **Seed file and loader.** Write `evals/seed_v1.jsonl`: 10 fresh synthetic messages with `id`, `type`, `text` (angry, numb, rambling, one-word, resistant, anxious, ashamed, sad, skill request, vague), no crisis content, none copied from anyone. Add a loader in `seed_messages.py` that validates JSON per line, required fields, unique ids and exactly 10 rows, and raises an error naming the line. Tests load the real file and malformed temp files. Files: `evals/seed_v1.jsonl`, `app/evals/seed_messages.py`, `tests/evals/test_seed_messages.py`. Verify: `uv run pytest tests/evals/test_seed_messages.py` + gates. Test: after. (The loader is a fourth public interface the user did not confirm as a seam, so it is tested after, not first.)
4. **Run loop.** One run function taking the coach, the messages, runs per message (3), `pause_seconds`, an injected `sleep`, a `write` callable for progress lines and a flag for tracing on. For each run: `reset()`, collect the full reply, score all 3 rules, record verdicts, tokens and time to first token from the coach's last stats, and the session id only when tracing is on. A provider error, a block, or an empty or whitespace reply is an error run (no retry). Wait after every run except the last, including error runs, none when `0`. Progress lines carry ids and verdicts only. Logs carry ids, counts and verdicts only. Ctrl-C propagates. Tests with `SpyChatModel`: 30 calls and each model input is system prompt + greeting + one message (AC3); counts match scripted replies (AC4 input); raised provider error, refused reply and empty reply become errors and the loop finishes (EC1-3, EC14, EC17); 29 sleeps for 30 runs, none at `0`, including after errors (AC11a); `capture_logs` shows no message or reply text (AC9); `KeyboardInterrupt` during a sleep propagates (EC18). Files: `app/evals/seed_runner.py`, `tests/evals/test_seed_runner.py`. Verify: `uv run pytest tests/evals/test_seed_runner.py` + gates. Test: first. Seam 2 (user-confirmed): the run function.
5. **Report writer.** Takes the results, the run info (model name, prompt version, prompt hash), a date and output directories. Builds the pass table (per rule: passes over scored runs, error count, model, date, version, hash), one failure row per failing (run, rule) with message id, run number, rule and reply, and "no failures" when there are none. Writes the committed results file `<date>-<hash>.md` and the local `seed-<date>-<hash>.jsonl` (all runs, reply included, session id only when present). Same date and hash overwrites; a different one keeps the old files. Tests in a tmp dir with fixed results, plus a check that the table text equals what is printed. Files: `app/evals/seed_report.py`, `tests/evals/test_seed_report.py`. Verify: `uv run pytest tests/evals/test_seed_report.py` + gates. Test: first. Seam 3 (user-confirmed): the report writer.
6. **Script wrapper.** `app/scripts/run_seed.py`: `--pause-seconds` (default 5, negative or non-numeric stops with a usage message), logging to a file under `logs/` so the terminal stays clean, `build_coach(settings)` with `CoachConfigError` and `PromptRegistryError` caught and printed without secret values, seed validation before any call, run, then print and write results. `coach.close()` in a `finally`. Ctrl-C: no committed file, non-zero exit. Tests drive `main(argv)` with the fake model patched in: bad pause value, failing build, bad seed file all stop before any model call (AC10, EC4, EC5, EC16); an interrupt closes the coach, writes no committed file, exits non-zero (AC11, EC12). Files: `app/scripts/run_seed.py`, `tests/scripts/test_run_seed_command.py`. Verify: `uv run pytest tests/scripts/test_run_seed_command.py` + gates. Test: after (wiring around the seams, plus real behavior of the `build_coach` failure path).
7. **Docs and layout.** Add `app/evals/` to the layout and the import rules in `.claude/rules/architecture.md` (evals may import `app/coach`, `app/core`, `app/shared`; nothing imports evals), a pointer in `.claude/rules/ai-core.md` Privacy for the narrow eval text allowance, and a `run_seed` row in the Commands table of `.claude/CLAUDE.md`. Run `graphify update .`. Files: `.claude/rules/architecture.md`, `.claude/rules/ai-core.md`, `.claude/CLAUDE.md`. Verify: full gate commands, `uv run python -m app.scripts.prompts check`. Test: skip (docs only; the full suite and gates must still pass).
8. **Real run and learnings (manual, by the user).** The user runs `uv run python -m app.scripts.run_seed` with real keys. The committed results file gets the real numbers (AC13). Then write `docs/features/slice-1/learnings.md`: the pass count per rule, each failing case in words, what each rule cannot see (EC7 and others), and the concept 14 section or an explicit "pending 1b R1" note (AC14). Files: `docs/features/slice-1c-seed-evals/results/<date>-<hash>.md` (generated), `docs/features/slice-1/learnings.md`. Verify: the results file exists with 3 rules, a date and a hash, and the full gate commands still pass. Test: skip (manual run; behavior checked by hand against the real model).

## Affected Files & Patterns
- `app/coach/conversation/coach.py`: four read-only properties next to the existing `history` property. Reuse the `llm_call` fields as the source of truth.
- `app/evals/` (new): `seed_rules.py`, `seed_messages.py`, `seed_runner.py`, `seed_report.py`. Files are prefixed by topic as in `.claude/rules/architecture.md`.
- `app/scripts/run_seed.py` (new): follows `app/scripts/prompts.py` (argparse, `main(argv)`, returns an int exit code).
- `evals/seed_v1.jsonl` (new, repo root), `docs/features/slice-1/learnings.md` (new), `docs/features/slice-1c-seed-evals/results/` (generated).
- Tests mirror the source tree under `tests/evals/`; reuse `tests/fakes/spy_chat_model.py` (scripted replies, exceptions, `REFUSED`), no new fake expected.
- Patterns to follow: `tests/coach/conversation/test_coach.py` (`_coach`, `_say`, `capture_logs`), `tests/scripts/test_prompts_command.py` (driving `main(argv)`), `app/entrypoints/cli.py` (logging to a file, catching `CoachConfigError`, `coach.close()` in `finally`).
- Risks: the Coach properties are the only engine change; `logs/` is already gitignored; Windows console encoding for the printed table (keep ASCII).

## Testing Strategy
- Framework and command: `pytest` via `uv run pytest <path>`. Under Git Bash use `env -u API_V1_PREFIX uv run pytest` (the env var is mangled); PowerShell needs no workaround.
- Gate commands: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check <touched files>` (format named files only, never `ruff format .`), `uv run pyright`, `uv run python -m app.scripts.prompts check`.
- Coverage map:

| Spec ID | Step | Test mode | Notes |
|---------|------|-----------|-------|
| AC1 | 3 | after | loads the real file |
| AC2 | 2 | first | EC6-EC9 as slices |
| AC3 | 4 | first | system + greeting + message |
| AC4 | 4, 5 | first | counts in 4, table text in 5 |
| AC5 | 5 | first | |
| AC6 | 4 | first | |
| AC7 | 5 | first | tmp dir |
| AC8 | 4, 5 | first | session id only when tracing on; `logs/` already ignored |
| AC9 | 4 | first | `capture_logs` |
| AC10 | 6 | after | |
| AC11 | 6 | after | |
| AC11a | 4 | first | fake sleep |
| AC12 | every step | gates | |
| AC13 | 8 | skip | manual real run |
| AC14 | 8 | skip | manual write-up |
| EC1, EC2, EC3 | 4 | first | provider error, refused reply, empty reply |
| EC4 | 6 | after | |
| EC5 | 3, 6 | after | |
| EC6, EC7, EC8, EC9 | 2 | first | |
| EC10, EC11 | 5 | first | |
| EC12 | 6 | after | |
| EC13 | 4, 5 | first | |
| EC14 | 4, 5 | first | |
| EC15 | 5 | first | "no failures" text |
| EC16 | 6 | after | |
| EC17 | 4 | first | rate limit is an error run, no retry |
| EC18 | 4 | first | interrupt during a pause |

- Must verify, not assume: how the real Gemini model reports a blocked or empty reply in a real run (the fake mirrors the 1a spike); that 5 s between calls stays under the real rate limit; that `Coach` really returns the full reply text for a streamed answer (it does in the CLI, confirm in the first real run).
- Open questions: none; every EC has an outcome.
- Known baseline failures: none (329 tests passed at the 1b handoff).

## Blockers & Resolutions
- Real run needs keys and the developer -> Step 8 is manual; implementation ends at step 7 with fakes.
- Concept 14 write-up needs the 1b R1 Langfuse trace check -> `learnings.md` gets the section or a "pending 1b R1" note.
- Coach private fields -> read-only properties instead of reaching into `_prompt`, `_info`, `_session_id`.
- No place for evals in the architecture layout -> Step 7 adds it, as the architecture rules require saying so.

## Trade-offs & Rationale
- Properties on `Coach` over recomputing run info: the table must show what the coach used. Cost: four trivial accessors.
- `--pause-seconds` as a script option, not a setting: it only concerns this manual script (spec FR3a).
- No retry loop in the script: a rate-limit error is an error run and the developer reruns with a larger pause (spec EC17). Keeps the baseline honest and the script small.
- The pause is injected as a `sleep` callable so tests never wait.
- One sequential loop, no parallelism: 30 calls, and parallel calls would hit the rate limit.

## Project Rules Applied
- `.claude/CLAUDE.md` -> tests never reach real services; the script is the one manual real-model path.
- `.claude/rules/architecture.md` -> thin script, topic-prefixed files, helpers private until a second user appears, tests mirror the tree, layout updated in step 7.
- `.claude/rules/ai-core.md` -> no prompt text in code, privacy of conversation text (narrow allowance for synthetic replies in result files only), registry locked, hash recorded per run.

## Skills Consulted
| Skill | Contribution |
|-------|-------------|
| lean-ctx | read `cli.py`, `coach_factory.py`, `coach.py`, `spy_chat_model.py`, the scripts and tests layout |
| graphify | one query in /feature mapped Coach, build_coach and the CLI door |
| grilling | layout, test seams and session-id access put to the user (answers above) |
| ponytail | no retry loop, no new setting, no new fake, no new dependency |

## Ready to Implement
- All spec requirements mapped to steps
- Every step has a Test tag; every AC and EC mapped, none uncovered
- Gate commands listed
- Every step names exact files and a verification command
- Approaches Considered filled; checkpoint interval none
- Affected files identified
- Blockers resolved or assigned (step 8 manual)
- One deviation from spec.md, already applied there: a fresh conversation still begins with the fixed greeting, so AC3 and FR3 were reworded
- Extension beyond what the user approved: `Coach` gets `model_name`, `prompt_version` and `prompt_hash` properties as well as `session_id`

## Deviations found during implementation
- D1 (EC12 partial JSONL): writing the JSONL only at the end could not leave partial runs on Ctrl-C. `run_seed` got an `on_result` callback (step 4) and the report writer was split into `report_paths` and `write_runs` (step 5) so the script writes the partial JSONL on interrupt.
- D2 (step 5): the results file also lists error runs (message, run, error code) under "Errors", so EC14's error count can be traced to cases.
- D3 (step 6): the script imports `app.entrypoints.cli` first, reusing its settings guard (a bad `.env` value prints one line without the value) and `configure_cli_logging`, instead of copying them.
