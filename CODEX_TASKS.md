# Codex task sequence

Paste one task at a time. Every task prompt starts with the same preamble so Codex re-anchors
on the spec. Tasks 1–8 are independent enough to run as parallel cloud tasks once Task 1 is
merged, but review and merge them in order the first time through.

**Preamble (prepend to every task):**

```
Read AGENTS.md, docs/RUBRIC.md and docs/EVAL_SPEC.md in full before doing anything. Follow the
hard rules and the "Working mode" section in AGENTS.md: this repo is worked on only through
Codex cloud and the GitHub web UI, so anything needing network or secrets at runtime must also
run as a GitHub Actions workflow_dispatch job, and the labeling tool is a browser page, not a
CLI. Work only on the task below; do not start later tasks. When done, summarise what changed,
list the commands you ran, and write a "How to verify" section. Grep the diff for any real
person, company, tool or board name before you finish.
```

---

## Task 0 — Rubric completeness audit (SKIP in web-only mode)

This task needs the real, confidential skill folders on a local machine. In web-only mode the
owner handles rubric completeness outside Codex. Do not upload private material to the repo to
run it. Kept here for reference only.

```
TASK 0. The folder private/ contains the real, confidential source material for the workflow
described in docs/RUBRIC.md (skill definitions, reference files, a plan document and session
logs). Read it in full. Then audit docs/RUBRIC.md for completeness against it: list every check,
pattern, severity rule, format rule or precedent that exists in private/ but is missing or
weaker in docs/RUBRIC.md. Propose additions as a unified diff to docs/RUBRIC.md using ONLY the
sanitized vocabulary (reviewer, client editor, writer, labels sheet, writer revision prompt).
Do not copy example titles, expert names, brand names, figures or any sentence verbatim from
private/; paraphrase into fictional equivalents. Do not modify anything under private/. Do not
create or edit any other file. Output the diff and a short list of judgment calls you made.
```

Accept when: the diff adds nothing identifying; you agree with each addition; apply it yourself.

---

## Task 1 — Scaffold

```
TASK 1. Scaffold the repository exactly per docs/EVAL_SPEC.md §7 and AGENTS.md "Stack and
conventions". Create: pyproject.toml managed by uv (python>=3.11; deps: pydantic>=2, typer,
pyyaml, scikit-learn, numpy, httpx, python-dotenv, jsonschema; dev: pytest, ruff),
src/editorial_qa_evals/ with empty modules named in §7 and a pydantic Entry model matching §3.1,
data/schema/entry.schema.json generated from the pydantic model, rules/region_swaps.yaml,
rules/filler_phrases.yaml and rules/mini_label_offenders.yaml seeded from docs/RUBRIC.md,
docs/LABELING_GUIDE.md written for a human labeler from docs/RUBRIC.md (checklist order: body
first, checks second, verdict last; include the severity routing table), README.md skeleton with
the one-paragraph pitch from EVAL_SPEC §0 and placeholder sections for Results, Architecture,
Reproduce, Limitations, .github/workflows/ci.yml running ruff + pytest only (no judge yet),
LICENSE (MIT) and data/LICENSE (CC BY 4.0). Add .env.example with JUDGE_BASE_URL, JUDGE_MODEL,
JUDGE_API_KEY. Ensure .gitignore exists and contains: private/, .env, *.key, __pycache__/,
.venv/, .pytest_cache/, runs/*/raw/, START_HERE.md (create or fix it if the web upload dropped
it). Add .github/workflows/pages.yml that deploys the labeling/ folder (create it with a
placeholder index.html for now) to GitHub Pages via the official actions/deploy-pages flow.
Make `pip install uv && uv sync && uv run pytest -q` pass with one trivial schema test.
```

Accept when: CI green on the first push; README pitch reads cleanly; no provider SDKs added.
After merging: in GitHub → Settings → Pages set the source to "GitHub Actions" once.

---

## Task 2 — Parser and deterministic checks

```
TASK 2. Implement src/editorial_qa_evals/parser.py and deterministic.py per EVAL_SPEC §2.1.
Parser: split a body into numbered items; within each item identify the item title, labelled
sub-sections (bold label followed by a colon), unlabelled intro lines before the first label and
orphan lines after the last label; for Q&A bodies pair questions with answers and detect
quotation wrapping. Checks: C1, C2, C3, C6, C8, C9 (minor vs major), C11 (parse the promised
count from task_name, headline-style numerals and the brief's tip count), C12 (single-item vs
across-items severity), J2 sentence-case item titles with a proper-noun allowlist, J4 filler
phrase lexicon. Each check returns {check_id, result: pass|fail|na, severity, evidence:[...]}
with evidence quoting the offending span and item number. Write tests/ with one fixture body per
fault type plus a clean body per piece type; assert pass on clean, fail with correct evidence on
faulty, and `na` when a check does not apply to the piece type. No LLM calls anywhere in this
task. Add a `uv run python -m editorial_qa_evals.cli check <entry.json>` command that prints the
deterministic results as a table.
```

Accept when: every fault fixture fails exactly its intended check; coverage of deterministic.py ≥ 95%.

---

## Task 3 — Synthetic golden set

```
TASK 3. Implement scripts/generate_synthetic.py per EVAL_SPEC §3.2. Inputs: --n, --seed, --out,
JUDGE_* env vars for the generation model. Steps: (1) sample a fictional brief (fictional expert
credential + specialism, 5 tips, hook, tone, region, piece type, approved labels drawn from a
small label table you add to rules/labels.yaml with entries like mistakes→["Why it's a mistake",
"What to do instead"], red flags→["Why it's a red flag","When to see a doctor"], tips→["Why it
matters","How to do it"], waste of money→["Why it's not worth it","What to buy instead",
"Savings"]); (2) generate a clean, compliant body with prompts/synthetic/generate_body.md;
(3) apply 0–3 faults from a recipe list implemented in code (count +1/−1, noun drift, orphan
closers, intro framing lines, mini-labels, placeholders in cost sub-sections, em-dashes,
region swaps, generic credential in task_name, dropped brief tip, bundled Q5, mixed quotes,
filler phrases, clinical colloquialisms) so that ~25% of entries are clean; (4) write entries to
--out WITHOUT the injected_faults field and write the per-id faults to a separate file
faults.jsonl; (5) stratify ~45 simple pitch lists, ~20 Q&A, ~15 CPR, regions 50/50. Run the
deterministic checks from Task 2 on the output and assert that each injected deterministic
fault is detected; print the confusion for faults that are not. Because generation needs an LLM
API and Codex cloud has no runtime network, do NOT generate the dataset inside this task.
Instead add .github/workflows/generate.yml (workflow_dispatch; inputs n and seed; secrets
JUDGE_BASE_URL/JUDGE_MODEL/JUDGE_API_KEY) that runs the generator, commits
data/golden/synthetic.jsonl and data/smoke_ids.txt (20 ids covering every piece type and every
intended verdict class) to main, and pushes faults.jsonl to a separate orphan branch named
`faults` so the labeler never sees it on main. Also add scripts/reconcile_faults.py that reads
faults.jsonl from a path argument. Unit-test the fault recipes with the LLM mocked.
```

Accept when: the owner runs the generate workflow from the Actions tab and gets 80 entries on main plus faults on the `faults` branch; deterministic checks catch ≥ 95% of their injected faults; sample 10 bodies by eye for realism and for any accidental real brand or statistic.

---

## Task 4 — Browser labeling page (GitHub Pages)

```
TASK 4. Implement labeling/index.html per EVAL_SPEC §4 as a static, dependency-free page
(vanilla HTML/CSS/JS, no build step) deployed by the existing pages.yml. It fetches
data/golden/synthetic.jsonl (relative path, so it works on GitHub Pages and when opened via a
local static server), shows one entry at a time (task_name, brief, region, approved labels, then
the body), then walks the checklist from docs/LABELING_GUIDE.md: each applicable check as
pass/fail/na with an optional note, then routing (escalate/fix_direct/none), then verdict
(READY/REVISE/MAJOR), then free notes. Never fetch or display anything from the `faults` branch.
Fields: labeler id, pass number, optional subset (paste ids). Persist progress in localStorage;
show progress and seconds-per-entry; support resume, back, and keyboard shortcuts. Export a
labels-<labeler>-pass<N>.json download containing the human blocks keyed by id. Add
scripts/import_labels.py that merges such a file into data/golden/synthetic.jsonl, and
.github/workflows/import_labels.yml (workflow_dispatch; input: path of a file the owner uploaded
to data/labels/incoming/ via the GitHub web UI) that runs the import and commits. Use the
Encoded palette (highlighter yellow, red pen, approved green) and the fonts named in EVAL_SPEC §8,
loaded from Google Fonts with a system fallback. Add a tiny Playwright-free smoke test that the
page's JS module parses a fixture JSONL and validates an exported labels file against the schema.
```

Accept when: you can label 3 entries end to end in the browser in under 10 minutes, close the tab, reopen and resume, export, upload the file to data/labels/incoming/ on github.com, run the import workflow, and see the labels on main.

---

## Task 5 — Judge layer

```
TASK 5. Implement src/editorial_qa_evals/judge.py and scripts/run_judge.py per EVAL_SPEC §2.2.
Provider-agnostic OpenAI-compatible chat client via httpx (base URL, model, key from env; retry
with backoff on 429/5xx; respect a --max-rpm flag so free tiers are not exceeded). Two modes:
per_check (one prompt per judgment check: C4, C7, C10, C13, J1, J3, J5, J6, J7, plus severity
classification for ambiguous C2/C9/C12 evidence) and holistic (one prompt returning all checks,
routing and verdict). Prompts live in prompts/judge/ as markdown with YAML front-matter and are
rendered with the entry plus the rubric excerpt for that check. Enforce JSON output against a
schema; on validation failure, re-ask once with the validation error; otherwise record an error
row. Temperature 0 default; --repeats N for self-consistency. Every run writes
runs/<run_id>/{config.json, prompt_hashes.json, raw/*.json, predictions.jsonl}. Mock the client
in tests; test prompt rendering, schema validation, retry and run-folder layout. Add --subset
smoke|all and --judge-name for labeling runs across providers. Add
.github/workflows/judge.yml (workflow_dispatch; inputs: mode, subset, judge_name; secrets
JUDGE_BASE_URL/JUDGE_MODEL/JUDGE_API_KEY) that runs the judge, commits the run folder minus
raw/ to main, and uploads raw/ as a workflow artifact. Do not call any API inside this Codex task.
```

Accept when: the owner runs judge.yml from the Actions tab against a hosted free-tier model and gets a committed run folder with zero schema errors after retry; a second run with a different judge_name (e.g. a second free provider) works by changing only the secrets.

---

## Task 6 — Routing, metrics, report

```
TASK 6. Implement routing.py (rule-derived routing and verdict from the union of deterministic
and judge results, exactly per docs/RUBRIC.md §5–6), metrics.py and scripts/make_report.py per
EVAL_SPEC §5 and §8. Metrics: per-check accuracy, Cohen's kappa, precision/recall on fail,
support (exclude na); quadratic-weighted kappa and 3×3 confusion for verdict; precision/recall/
macro-F1 for routing with escalate reported separately; bootstrap 95% CIs (1000 resamples over
entries, fixed seed) for every kappa; judge self-consistency kappa across repeats; human
intra-rater and inter-rater kappas when pass-2 or r2 labels exist; cost (tokens × a price table
in rules/prices.yaml) and latency p50/p95. Compare rule-derived vs holistic routing and verdict
in the same table. make_report.py writes report/<run_id>/report.md and report.html (static,
Encoded palette per §8, no JS framework) and a README snippet
report/<run_id>/README_results.md. Extend judge.yml so make_report.py runs after the judge and
commits report/latest/. Unit-test metrics on tiny hand-computed examples, including a
perfect-agreement case (kappa 1.0), chance-level case (kappa ≈ 0), and an all-na check (skipped).
```

Accept when: the hand-computed kappa tests pass and report/latest/report.html renders on GitHub Pages after a judge workflow run.

---

## Task 7 — Regression gates

```
TASK 7. Implement the gates in EVAL_SPEC §6. Add data/baseline.json produced by a script
scripts/update_baseline.py from a named run on the smoke subset (stores prompt hashes, judge
name, per-check kappas, verdict weighted kappa, escalate recall and per-entry verdicts).
Extend .github/workflows/ci.yml: on PRs touching prompts/, rules/, src/ run ruff + pytest, then
run the judge on smoke with JUDGE_* from repository secrets and fail when weighted verdict
kappa drops > 0.05 vs baseline, escalate recall drops > 0.05, or any smoke entry flips between
READY and MAJOR; print a markdown summary to the job summary. Add nightly.yml running the full
golden set and uploading report/ as an artifact. Document in README how to refresh the baseline
intentionally (and that a prompt change without a baseline update fails CI by design).
```

Accept when: a deliberate prompt weakening in a test PR turns CI red with a readable summary.

---

## Task 8 — Write-up

```
TASK 8. Finish README.md: the §0 pitch; a Mermaid architecture diagram of EVAL_SPEC §2; a Results
section pasted from the latest report/<run_id>/README_results.md with the human-ceiling row;
a Reproduce section (commands from AGENTS.md); Limitations (synthetic data, single primary
rater, judge drift, prompt sensitivity, English-only); "What I'd do differently"; and a short
Dataset card for data/golden (fields, generation method, license, known biases). Add a
screenshot placeholder for the labeling page and the report. Keep the prose plain: no marketing adjectives,
no exclamation marks, numbers before interpretation. Then propose, as a separate list, three
concrete follow-ups (e.g. fine-tuning a small classifier on deterministic features, adding a
second rater, evaluating writer revision prompts against §7 of the rubric).
```

Accept when: a stranger can reproduce the smoke run from the README alone in under 15 minutes.
