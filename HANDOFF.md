# Handoff: project state as of 2026-11-14

Read this first, then `AGENTS.md`, `docs/RUBRIC.md`, `docs/EVAL_SPEC.md` and `CODEX_TASKS.md`.
Delete or update this file when the state below changes.

## What this repo is

An evaluation harness that measures how closely an LLM judge agrees with a human editorial
reviewer on a QA workflow for AI-drafted expert quote pieces. Target output: a results table of
Cohen's kappa per check with bootstrap confidence intervals, plus CI regression gates.

## Done (merged on main)

| Task | Content | PRs |
|---|---|---|
| 1 | Scaffold, CI (ruff + pytest on 3.11/3.12), GitHub Pages deploy | #1 |
| 2 | Body parser and ten deterministic checks, 100% covered | #2 |
| 3 | Seeded synthetic generator, 15 fault recipes, hidden `faults` branch | #3, #4, #5 |
| 3b | Domain catalog for representative briefs (`rules/brief_catalog.yaml`) | #6 |
| 3c | Non-retryable 400 handling, token budget, checkpoint and resume, headline coherence | #8 |

Task 2 was independently probed with realistic bodies (bold numbered titles, labels on their own
line, an approved third label). All eight probes behaved correctly. Known limits are in
`docs/DETERMINISTIC.md`: a label-wording drift fails both C1 and C2, and an orphan closer with no
blank line before it cannot be caught structurally (left to the judge).

## Current blocker: the golden set does not exist yet

`data/golden/synthetic.jsonl` on main still holds 20 entries from the first generator version.
They are rejected: every headline is "... in a fictional household", two credentials only, count
always 5, templated CPR statistics. Do not label them. They get overwritten by the next
successful generate run.

Latest trial, run 43683421416 (n=20, seed=11, max_rpm=10, model openai/gpt-oss-120b on Groq):

- 17 of 20 entries generated; the run failed because 3 failures exceed the 10% threshold.
- HTTP 400s are almost gone (1 exhausted recovery, on syn-0013). Fix 3c worked.
- Remaining failures are draft validation, by count of failed attempts:
  J3 paragraph length 18 (model writes one long sentence where two or three are required),
  QUESTION_FORMAT 7 (question without a question mark or capital), C9 5, C8 4, CONTENT 2.
- Entries that never passed: syn-0012 (J3 on all 8 attempts), syn-0019 (QUESTION_FORMAT on all
  8), syn-0013 (API 400).
- Injected deterministic faults were all detected (C2, C6, C8, C9, C11, C12, J4: 0 missed).

Content review of the 17 entries that passed in that run (from the run's checkpoint artifact):

- Fixed: 12 domains, 17 distinct credentials, counts of 3, 5 and 7, zero occurrences of
  "fictional", "invented", "simulation" or "household". CPR statistics now support their item
  (named made-up organisation, sample size, region, `.invalid` URL).
- Still wrong, fix before n=80:
  1. Headlines are concatenated fragments and read unnaturally: "5 wastes of money for a better
     sleep routine", "warns of 5 signs when applying for a job", "3 signs for everyday dental
     care", "3 mistakes to consider when storing food". Signs and red flags need an object
     ("5 signs your CV is being filtered out"). Prefer curated full headline patterns per
     domain and noun category, or one LLM call that writes the headline and is validated.
  2. Credential and domain mismatches: an occupational therapist on sleep routines, a baggage
     specialist on booking holidays. Tighten the catalog pairing.
  3. The C9 region fault inserts a filler sentence ("A colour detail matters.") instead of
     swapping words already in the body. It is a giveaway to both the labeler and the judge.
     Region faults must substitute existing terms (color/colour, vacation/holiday, $/GBP).
     Review the other injected-sentence recipes for the same problem.

Suggested next fix ("3d", after the items above), smallest change first:
1. Normalise before validating clean drafts: capitalise the question and append "?" when the
   text is a single interrogative; this removes QUESTION_FORMAT failures without an API call.
2. For J3, put the sentence-count rule and one worked example at the top of
   `prompts/synthetic/generate_body.md`, and make the feedback retry quote the offending
   paragraph with "split this into two or three sentences".
3. Allow the publish step to commit a partial set when the deadline or failure threshold is hit
   and report missing ids, so 17 good entries are not thrown away.
4. Then run n=20 again; read ten entries; if at least 19 pass and headlines read naturally,
   run n=80, seed=7.
Fallback if the model keeps failing J3: change the `JUDGE_MODEL` secret to another
OpenAI-compatible model; no code change is needed.

## Not started

- Task 4: browser labeling page (`labeling/index.html` is a placeholder).
- Task 5: LLM judge layer and `judge.yml` workflow.
- Task 6: routing, kappa metrics with bootstrap CIs, report.
- Task 7: regression gates against `data/baseline.json`.
- Task 8: README results, limitations, dataset card.
- Human labeling: 80 entries by the reviewer, then 20 re-labelled a week later. Not automatable.

Paste-ready prompts for Tasks 4 to 8 are in `CODEX_TASKS.md` (prepend the preamble).

## How this repo is operated

- No local terminal is assumed. Runtime steps are `workflow_dispatch` jobs in the Actions tab:
  `Generate synthetic entries` (inputs n >= 20, seed, max_rpm, max_tokens, deadline_minutes,
  resume_run).
- Repository secrets `JUDGE_BASE_URL`, `JUDGE_MODEL`, `JUDGE_API_KEY` are set (Groq free tier).
- Pages source is GitHub Actions; the site is https://zurvaaziz56.github.io/editorial-qa-evals/
- The `faults` branch is the answer key. The reviewer must not read it before labeling is done.
- Privacy rule: no real client, editor, tool or publication names anywhere. Use only the
  vocabulary in `docs/RUBRIC.md`.

## If time is short

A defensible smaller version: 40 entries, one judge, per-check kappa with CIs, README with
limitations. That still demonstrates the method; the second judge and the regression gates can
follow.
