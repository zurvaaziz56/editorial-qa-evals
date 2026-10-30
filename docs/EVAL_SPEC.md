# Eval Harness Spec — Editorial QA Judge Agreement

## 0. One-paragraph pitch (use in README)

A real editorial QA workflow reviews AI-drafted expert quote pieces against 13 mandatory
checks and 10 recurring writer failure patterns before they go to a PR agency client. This
repo turns that workflow into a measurable system: a golden set of labeled entries, a hybrid
checker (deterministic code for mechanical checks, an LLM judge for editorial judgment), and a
report that answers one question with statistics instead of vibes: **how closely does the
automated judge agree with the human reviewer, per check, with confidence intervals — and
is it safe to let it route pieces?** Regression gates in CI stop prompt or rubric changes
from silently degrading agreement.

## 1. Goals / non-goals

Goals
1. Golden set of 60–100 labeled entries (target 80), stratified by piece type and verdict.
2. Hybrid checker: deterministic checks + LLM judge, both producing the same structured output.
3. Agreement report: Cohen's kappa per check (binary), weighted kappa for the ordinal verdict,
   precision/recall for `escalate` routing, bootstrap 95% CIs, confusion matrices.
4. Regression gates in GitHub Actions on a fixed smoke subset; nightly full run.
5. README with a results table and an honest "what moved the needle / what didn't" section.

Non-goals
- Rewriting pieces. The harness judges; it does not fix.
- Regulatory review of any kind (explicitly out of scope in the source workflow).
- Reproducing the client's confidential process documents. See §9.

## 2. Architecture

```
data/golden/*.jsonl           ─┐
                                ├─▶ checker ──▶ runs/<run_id>/predictions.jsonl ──▶ metrics ──▶ report/
prompts/judge/*.md            ─┘        │
                                        ├── deterministic/   (pure Python, unit-tested, no LLM)
                                        └── judge/           (LLM, structured JSON output, provider-agnostic)
```

### 2.1 Deterministic layer (no LLM, 100% unit-tested)

Implement as pure functions over the parsed body. Each returns `{check_id, result: pass|fail|na, evidence: [...]}`.

- Body parser: split into numbered items; within items, detect item title, labelled sub-sections
  (bold label + colon), and unlabelled lines before the first label / after the last label.
- C1 label compliance (exact string match against `approved_labels`, per item)
- C2 mini-label regex (bold or colon-suffixed lead-ins inside sub-sections not in `approved_labels`)
- C3 placeholder scan (only when a cost-type label is present)
- C6 quote consistency (Q&A)
- C8 dash / artefact scan (U+2014, U+2013, U+2011, ` - `, non-Latin runs)
- C9 regionalisation lexicon pass (swap table in `rules/region_swaps.yaml`; report mismatches, severity minor vs major by count/type)
- C11 count contract (parse count from task_name/headline/brief; count numbered items)
- C12 orphan lines (structural parse; report per item; severity across-items vs single)
- J2 sentence-case item titles (lexical heuristic with proper-noun allowlist)
- J4 filler-phrase lexicon (exact phrases only; the judgment part of voice goes to the LLM)

Anything that needs reading comprehension goes to the judge.

### 2.2 Judge layer (LLM)

- Provider-agnostic client: OpenAI-compatible base URL + model name from env
  (`JUDGE_BASE_URL`, `JUDGE_MODEL`, `JUDGE_API_KEY`). Must work with at least two providers
  out of the box (e.g. a free-tier hosted model and a local Ollama model) so the agreement
  numbers can be compared across judges.
- Two judge modes, both emitting the same schema:
  - `per_check`: one call per judgment check (C4, C7, C10, C13, J1, J3, J5, J6, J7, plus
    severity classification for C2/C9/C12 when deterministic evidence is ambiguous).
  - `holistic`: one call that returns all checks + routing + verdict.
- Structured output enforced with a JSON schema; retries with validation errors fed back; temperature 0 by default; `n_repeats` option for self-consistency.
- Judge prompts live in `prompts/judge/` as versioned markdown; every run records prompt hashes.

### 2.3 Verdict and routing derivation

Two ways to produce `routing` and `verdict`, both compared to human labels:
1. **Rule-derived**: apply the severity routing table in `docs/RUBRIC.md §5–6` to the union of deterministic + judge check results.
2. **Holistic**: the judge's own routing/verdict.

Hypothesis to test and report: rule-derived routing beats holistic routing on `escalate` recall.

## 3. Data

### 3.1 Schema (`data/schema/entry.schema.json`)

```json
{
  "id": "syn-0001",
  "source": "synthetic | anonymized",
  "piece_type": "simple_pitch_list | cpr | qa",
  "region": "UK | US",
  "task_name": "string",
  "brief": {"tips": ["..."], "hook": "...", "tone": "...", "expert": {"credential": "...", "specialism": "..."}},
  "approved_labels": ["..."],
  "questions": ["..."], "answers": ["..."],
  "body": "string",
  "injected_faults": ["C11", "C12", "P5"],
  "human": {
    "checks": {"C1": "pass|fail|na", "...": "..."},
    "judgment": {"J1": "pass|fail|na", "...": "..."},
    "routing": "escalate | fix_direct | none",
    "verdict": "READY | REVISE | MAJOR",
    "notes": "string",
    "labeled_at": "ISO-8601", "labeler": "r1 | r2", "pass_number": 1
  }
}
```

`injected_faults` is hidden from the labeler during labeling: the generator writes it to a separate `faults.jsonl` that lives on an orphan branch named `faults`, never on `main`, until labeling is complete and the reconciliation step copies it in.

### 3.2 Synthetic generation (`scripts/generate_synthetic.py`)

- Fictional experts, publications, brands and figures only. Seeded for reproducibility.
- Generate a clean body from a fictional brief, then apply a controlled fault recipe
  drawn from the rubric: count breach (+1/−1 item), noun drift (mistakes→tips), orphan closers,
  intro framing lines, mini-labels, placeholders in cost sub-sections, em-dashes, region swaps,
  generic credential, dropped brief tip, bundled Q5, mixed quotes, filler phrases, clinical
  colloquialisms. Recipes combine 0–3 faults; ~25% of entries are clean.
- Stratify: ~45 simple pitch lists, ~20 Q&A, ~15 CPR; regions ~50/50.
- Keep the generation prompt and the recipe list in the repo; the dataset must be regenerable.

### 3.3 Private calibration set (never committed)

Real entries from past batches may live only in `private/` for the reviewer's own calibration.
If any real-derived example is ever added to `data/golden/`, it must be rewritten end-to-end
(new topic, new expert, new figures) so that no sentence is traceable to a client piece, and
`source` must be `anonymized`.

## 4. Labeling protocol (the human part — the reviewer does this, not Codex)

1. Labeling page (`labeling/index.html`, static, served from GitHub Pages) shows one entry at a time: body first, rubric checklist second, never anything from the `faults` branch. Progress lives in `localStorage`; the page exports `labels-<labeler>-pass<N>.json`, which the reviewer uploads to `data/labels/incoming/` on github.com and merges with the `import_labels` workflow.
2. Label all entries once (pass 1). Budget ~3–4 minutes each → two 2-hour sessions for 80 entries.
3. Re-label a random 20-entry subset ≥ 7 days later (pass 2) → intra-rater kappa.
4. Optional: a second rater labels the same 20 → inter-rater kappa = the human ceiling the judge is compared against.
5. Also compute agreement between human labels and `injected_faults` for deterministic checks → surfaces labeling slips before they contaminate the judge comparison.

## 5. Metrics (`src/.../metrics.py`)

- Per check (binary pass/fail, `na` excluded): accuracy, Cohen's kappa, precision/recall on `fail`, support.
- Verdict: quadratic-weighted Cohen's kappa on READY<REVISE<MAJOR plus a 3×3 confusion matrix.
- Routing: precision and recall for `escalate` (the business-critical class), plus macro-F1.
- Uncertainty: bootstrap 95% CIs (≥1000 resamples over entries) for every kappa.
- Judge self-consistency: kappa between repeat runs of the same judge at temperature 0 (n=3) on the smoke subset.
- Cost and latency: tokens, USD at list price, p50/p95 latency per entry, per judge.
- Human ceiling: inter/intra-rater kappas from §4 reported in the same table.

Interpretation bands reported alongside numbers (Landis & Koch): <0.20 slight, 0.21–0.40 fair,
0.41–0.60 moderate, 0.61–0.80 substantial, >0.80 almost perfect. Numbers first; bands are context.

## 6. Regression gates

- `smoke` subset: 20 fixed ids spanning all piece types and verdicts, committed as `data/smoke_ids.txt`.
- `baseline.json`: committed snapshot of metrics on the smoke subset for the current prompt hashes.
- GitHub Actions on PRs touching `prompts/`, `rules/`, `src/`: run deterministic unit tests (always), then the judge on `smoke` (needs `JUDGE_API_KEY` secret). Fail if:
  - any deterministic unit test fails
  - weighted kappa on verdict drops > 0.05 vs baseline
  - `escalate` recall drops below baseline − 0.05
  - any smoke entry's verdict flips from READY to MAJOR or vice versa vs baseline
- Nightly workflow: full golden set, publish `report/latest/` as a workflow artifact.
- Implement with pytest; use DeepEval (Apache-2.0) for the judge-metric assertions if it reduces code, otherwise plain pytest. Do not introduce a second eval framework.

## 7. Repo layout

```
AGENTS.md
README.md                      results table, architecture diagram, how to reproduce, limitations
docs/RUBRIC.md                 sanitized rubric (source of truth)
docs/EVAL_SPEC.md              this file
docs/LABELING_GUIDE.md         how the reviewer labels (written by Codex from RUBRIC.md)
data/schema/entry.schema.json
data/golden/*.jsonl            synthetic + anonymized entries with human labels
data/smoke_ids.txt
data/baseline.json
rules/region_swaps.yaml        UK/US swap table
rules/filler_phrases.yaml
rules/mini_label_offenders.yaml
prompts/judge/per_check/*.md
prompts/judge/holistic.md
prompts/synthetic/generate_body.md
src/editorial_qa_evals/        parser.py, deterministic.py, judge.py, routing.py, metrics.py, report.py, cli.py
scripts/generate_synthetic.py, import_labels.py, reconcile_faults.py, run_judge.py, make_report.py, update_baseline.py
labeling/index.html            static browser labeling page (GitHub Pages)
data/labels/incoming/          exported label files uploaded via the GitHub web UI
tests/                         unit tests for parser + every deterministic check (fixtures per fault)
runs/<run_id>/                 committed minus raw/ (raw/ goes to workflow artifacts)
report/latest/                 generated HTML + markdown, committed by the judge workflow
.github/workflows/             ci.yml, nightly.yml, pages.yml, generate.yml, judge.yml, import_labels.yml
```

Operating model: the owner has no local terminal. Every runtime step (generate, judge, report,
import labels, refresh baseline) is a `workflow_dispatch` job run from the Actions tab; Codex
cloud writes the code and tests but never calls an external API inside a task.

## 8. Report and README

- `make_report.py` writes `report/latest/report.md` and `report.html`. Styling may use the
  Encoded editorial palette: highlighter yellow (flags), red pen (fails), approved green (passes);
  fonts Bricolage Grotesque / Instrument Sans / IBM Plex Mono. Keep it static, no framework.
- README results table columns: check, n, human-vs-judge kappa [95% CI], human-vs-human kappa (if available), fail-recall, judge, cost per 100 entries.
- README must include a limitations section: synthetic data caveat, single primary rater, judge model drift, prompt sensitivity.

## 9. Privacy and licensing

- Never commit `private/`. Never write real names of people, companies, tools or boards into any file in this repo. The sanitized vocabulary in `docs/RUBRIC.md` is mandatory.
- Synthetic entries must use fictional experts, publications, brands, statistics and URLs.
- License: MIT for code; CC BY 4.0 for the dataset.

## 10. Definition of done

- [ ] 80 labeled entries, `injected_faults` reconciled with human labels, labeling guide published
- [ ] deterministic checks: 100% unit-test coverage per fault fixture
- [ ] two judges run (hosted + local), per-check kappas with CIs in README
- [ ] rule-derived vs holistic routing compared; `escalate` precision/recall reported
- [ ] CI gates green on main, baseline committed, nightly artifact publishing
- [ ] README: pitch, architecture diagram, results table, limitations, "what I'd do differently"
