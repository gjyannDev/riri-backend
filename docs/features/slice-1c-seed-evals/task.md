# Implementation: Slice 1c, Seed evals

## Status
Real run done (AC13, 2026-11-25: 30/30 on every rule, 0 errors, hash `aa5966c524f5`). Remaining before ready for PR: the concept 14 section of `learnings.md` (needs 1b R1) and the user's OK on deviations D1-D3.
Health Check: all present. find-skills: no gap found; installed `tdd`, `test`, `python-testing-patterns` and `llm-evaluation` cover the plan, so nothing was installed.
Branch: `feat/slice-1a-talking-core` (user's choice, no new branch). The user commits manually.

## Completed Steps
- [x] 1. Coach read-only run info (`session_id`, `model_name`, `prompt_version`, `prompt_hash`)
- [x] 2. Rule checks (`app/evals/seed_rules.py`)
- [x] 3. Seed file and loader (`evals/seed_v1.jsonl`, `app/evals/seed_messages.py`)
- [x] 4. Run loop (`app/evals/seed_runner.py`)
- [x] 5. Report writer (`app/evals/seed_report.py`)
- [x] 6. Script wrapper (`app/scripts/run_seed.py`)
- [x] 7. Docs and layout (`.claude/rules/architecture.md`, `.claude/rules/ai-core.md`, `.claude/CLAUDE.md`, `graphify update .`)
- [ ] 8. Real run and learnings (manual, by the user)

## Current Step
### 8. Real run and learnings (user)
1. Run `uv run python -m app.scripts.run_seed` (PowerShell, or Git Bash with `env -u API_V1_PREFIX`). Optionally set `LANGFUSE_CAPTURE_TEXT=false` if tracing is on.
2. Check: 30 runs, few errors, model, date and hash filled. If many errors are rate limits, rerun with `--pause-seconds 10`.
3. Fill the pending parts of `docs/features/slice-1/learnings.md`: eval log row 1, the failures in words, sections 6 and 7.
4. When Langfuse keys exist: 1b R1 (masked trace by eye) and the concept 14 section.

## Changes Made
Suggested commits (the user runs them):

    git add app/coach/conversation/coach.py tests/coach/conversation/test_coach.py
    git commit -m "feat(coach): expose session id, model name and prompt version and hash as read-only properties"

    git add app/evals/__init__.py app/evals/seed_rules.py tests/evals/__init__.py tests/evals/test_seed_rules.py
    git commit -m "feat(evals): add the three literal seed rule checks"

    git add evals/seed_v1.jsonl app/evals/seed_messages.py tests/evals/test_seed_messages.py
    git commit -m "feat(evals): add 10 synthetic seed messages and a validating loader"

    git add app/evals/seed_runner.py app/evals/seed_report.py tests/evals/test_seed_runner.py tests/evals/test_seed_report.py
    git commit -m "feat(evals): run each seed message three times with a pause and write the pass table"

    git add app/scripts/run_seed.py tests/scripts/test_run_seed_command.py
    git commit -m "feat(scripts): add run_seed with --pause-seconds, partial results on Ctrl-C"

    git add .claude/rules/architecture.md .claude/rules/ai-core.md .claude/CLAUDE.md docs/features/slice-1c-seed-evals docs/features/slice-1/learnings.md
    git commit -m "docs(evals): slice 1c spec, plan, task, layout rules and slice 1 learnings"

The real-run results file is inside `docs/features/slice-1c-seed-evals`, so it goes in that last commit. `logs/` stays out (gitignored).

## Test Results
- Baseline: 329 passed (2026-11-25).
- After step 7: 397 passed (`env -u API_V1_PREFIX uv run pytest -q`), `uv run ruff check .` clean, `ruff format --check` on touched files clean, `uv run pyright` 0 errors, `prompts check` OK hash `aa5966c524f5`.
- Manual: `uv run python -m app.scripts.run_seed --help` shows the option; `--pause-seconds -2` exits 2 with a usage message. No real-model run yet.

## Tests Pending
- AC13: done 2026-11-25 by the user. Result file `docs/features/slice-1c-seed-evals/results/2026-11-25-aa5966c524f5.md`.
- AC14: number, failures (none) and rule gaps written in `docs/features/slice-1/learnings.md`. Concept 14 section still pending 1b R1.
- Optional: a repeat run with nothing changed (eval log row 2).

## Test Cases
| ID | Step | Case | Tag | Source | Status |
|----|------|------|-----|--------|--------|
| T1 | 1 | run info equals the construction values | spec | plan step 1 | pass |
| T2 | 1 | session id is the traced one and changes on reset | spec | AC8 | pass |
| T3 | 2 | one question: 0/1 pass, 2 fail, `??` and `?!?` count once, one `?` over two questions passes | spec | AC2, EC6, EC7 | pass |
| T4 | 2 | no markdown: line-start bullets, numbers, heading, `**`, `__`, backtick fail; mid-sentence numbers and dashes pass | spec | AC2, EC8 | pass |
| T5 | 2 | indented bullet fails | inferred | risk: model indents lists | pass |
| T6 | 2 | fake empathy: literal phrase fails any case; near-misses pass | spec | AC2, EC9 | pass |
| T7 | 2 | rules named in report order | spec | FR6 | pass |
| T8 | 3 | real seed file: 10 unique ids, the five named types | spec | AC1 | pass |
| T9 | 3 | bad JSON, non-object, missing or blank field, non-string id, duplicate ids, wrong count each named | spec | EC5 | pass |
| T10 | 3 | bad line error has no message text; missing file is a seed error; blank lines ignored | inferred | risk: text in errors, unreadable file | pass |
| T11 | 4 | 30 calls, each input system + greeting + one message | spec | AC3, FR3 | pass |
| T12 | 4 | verdicts and tokens per run | spec | AC4 | pass |
| T13 | 4 | rate limit, refused and whitespace replies are error runs; loop continues; no retry | spec | AC6, EC1, EC2, EC3, EC17 | pass |
| T14 | 4 | 29 pauses for 30 runs including after errors; none at 0 | spec | AC11a | pass |
| T15 | 4 | Ctrl-C during a pause propagates | spec | EC18 | pass |
| T16 | 4 | results handed over as they exist (partial on Ctrl-C) | code-derived | `on_result` branch (D1) | pass |
| T17 | 4 | session id only when asked | spec | AC8, EC13 | pass |
| T18 | 4 | progress lines and logs carry ids and verdicts, never text | spec | AC9 | pass |
| T19 | 5 | table: passes over scored runs, error count, model, date, version, hash | spec | AC4, EC14 | pass |
| T20 | 5 | one failure row per failing run and rule, errors listed, `|` and newlines escaped | spec | AC5 | pass |
| T21 | 5 | clean run says no failures, no errors | spec | EC15 | pass |
| T22 | 5 | date-hash names; same name overwrites; new hash or date keeps old | spec | AC7, EC10, EC11 | pass |
| T23 | 5 | JSONL: every run, reply, verdicts, tokens, session id only when set | spec | AC8, EC13 | pass |
| T24 | 6 | full fake run prints the table, writes both files, closes the coach | spec | FR6, FR8, FR12 | pass |
| T25 | 6 | `-1`, `abc`, `nan`, `inf` pause stop before build, exit 2 | spec | EC16 | pass |
| T26 | 6 | failing build stops, names the setting, no results dir | spec | AC10, EC4 | pass |
| T27 | 6 | bad seed stops before the build | spec | AC10, EC5 | pass |
| T28 | 6 | Ctrl-C: coach closed, no results file, partial JSONL, exit 130 | spec | AC11, EC12 | pass |

## Open Questions
- none

## Baseline Failures
- none

## Known Issues
- TDD slips: in step 4 slice A and step 5 slice B the test and the code were written together, so those two tests were never seen red. Both assert literal expected values from the spec, so they are not tautological, but they were not proven to fail first.
- `render_report` runs twice on a normal finish (once for the printed table, once inside `write_report`). Harmless for 30 rows.
- The script's reuse of `app.entrypoints.cli` couples one door to another (D3). If the CLI module grows, move the settings guard and logging helper into `app/core`.

## Deviations from Plan
- D1: `on_result` callback and `report_paths` / `write_runs` split, for EC12 partial JSONL -> plan.md updated ("Deviations found during implementation") -> needs the user's OK at review.
- D2: results file lists error runs -> plan.md updated -> needs the user's OK at review.
- D3: script reuses the CLI settings guard and logging helper -> plan.md updated -> needs the user's OK at review.

## Debug Log
- none

## Review

## Skills Consulted During Implementation
| Step | Skill | Why |
|------|-------|-----|
| 1-5 | tdd, test | red -> green at the confirmed seams |
| 3, 6 | test | after-mode tests and code-derived pass |
| all | ponytail (judgment) | no retry loop, no new fake, no new dependency, reuse CLI guard |
| all | lean-ctx, graphify | reads, search, shell; graph updated after step 7 |

## Links
- Spec: docs/features/slice-1c-seed-evals/spec.md
- Plan: docs/features/slice-1c-seed-evals/plan.md
- Learnings: docs/features/slice-1/learnings.md

---

## Validation Checklist (before PR)
- [ ] All plan.md steps complete (step 8 is the user's)
- [x] Full test suite + build green
- [x] Gate commands green on every step
- [x] No `/debug` invocations; no step left `blocked`
- [ ] Every spec.md acceptance criterion met (AC13, AC14 pending the real run)
- [x] Open Questions resolved or surfaced
- [x] No skipped, deleted, or loosened tests; no baseline failures
- [x] task.md fully updated
- [x] learnings.md written with pending measurements matching Tests Pending
- [x] Commits documented (suggested above, the user commits)
- [ ] No open blockers (the real run)
- [x] Code follows project .claude/rules
- [ ] No unresolved plan deviations (D1-D3 need the user's OK)
