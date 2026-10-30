# AGENTS.md — editorial-qa-evals

You are working in a public portfolio repository. Read `docs/RUBRIC.md` and `docs/EVAL_SPEC.md`
before any task; they are the source of truth and override anything you infer from code.

## What this project is

An evaluation harness that measures how closely an LLM judge agrees with a human editorial
reviewer on a real QA workflow for AI-drafted expert quote pieces (PR bodies). The owner runs
this workflow professionally and labels the golden set herself. The repo is also a public case
study for **Encoded** (getencoded.co), a productized AI-workflow service for content and
editorial teams, so quality of documentation matters as much as code.

## Working mode (read this first)

The owner works only through **Codex cloud and the GitHub web UI** — no local terminal. Consequences:

- Anything that needs network access or secrets at runtime (synthetic generation, judge runs,
  report generation) must be runnable as a GitHub Actions `workflow_dispatch` job that reads
  repository secrets and commits or uploads its outputs. Local scripts are fine in addition, never instead.
- The labeling tool is a **static browser page served from GitHub Pages** (`labeling/`), not a
  terminal CLI. Vanilla HTML/JS, no build step, progress kept in `localStorage`, labels exported as JSON.
- Codex cloud has internet only during environment setup, so install everything in setup and
  never rely on network inside a task. If a step cannot run without network, implement it as a workflow and say so.
- Every command in the README must also be runnable in CI (`pip install uv && uv sync`).

## Hard rules

1. **Privacy.** Never write real names of clients, editors, writers, tools, boards or
   publications into any file. Use only the vocabulary in `docs/RUBRIC.md` (reviewer, client
   editor, writer, labels sheet, writer revision prompt). Never read from or copy out of
   `private/` into tracked files. If a task seems to require real data, stop and say so.
2. **Synthetic data must be fictional end-to-end**: experts, publications, brands, statistics,
   URLs. Seeded and regenerable.
3. **Deterministic before LLM.** If a check can be computed with code, it must be; LLM calls are
   only for reading-comprehension judgments. Every deterministic check has unit tests with one
   fixture per fault type.
4. **One eval framework max.** Plain pytest first; add DeepEval only if it removes code. Do not
   add promptfoo, LangChain, LlamaIndex or an agent framework.
5. **Provider-agnostic judge.** OpenAI-compatible client configured by env vars
   (`JUDGE_BASE_URL`, `JUDGE_MODEL`, `JUDGE_API_KEY`). No provider-specific SDK features.
   Never hard-code keys. Load `.env` locally; CI uses secrets.
6. **Reproducibility.** Every run writes `runs/<run_id>/` with config, prompt hashes, raw judge
   outputs, predictions and metrics. Metrics are never computed from anything but a run folder.
   Commit `config.json`, `prompt_hashes.json`, `predictions.jsonl` and `metrics.json`; `raw/` is
   gitignored and uploaded as a workflow artifact instead.
7. **Small PRs.** One task per branch/PR, with a short description of what changed and how to
   verify. Update `README.md` in the same PR when behaviour or results change.

## Stack and conventions

- Python 3.11+, `uv` for env and locking, `ruff` for lint/format, `pytest`, `pydantic` v2 models
  for the entry schema, `scikit-learn` for kappa, `numpy` for bootstrap, `typer` for CLIs.
- Package: `src/editorial_qa_evals/`. CLIs: `scripts/` (thin wrappers over package functions).
- Type hints everywhere; no bare `except`; no network calls in unit tests (mock the judge).
- Data files are JSONL; one entry per line; ids are stable (`syn-0001`, `anon-0001`).
- Prompts are markdown files with YAML front-matter (`name`, `version`, `checks`).

## Commands

```bash
uv sync                               # install
uv run pytest -q                      # unit tests (no network)
uv run ruff check . && uv run ruff format --check .
uv run python scripts/generate_synthetic.py --n 80 --seed 7 --out data/golden/synthetic.jsonl
uv run python scripts/label.py data/golden/synthetic.jsonl --labeler r1 --pass 1
uv run python scripts/run_judge.py --mode per_check --subset smoke
uv run python scripts/make_report.py runs/<run_id>
```

## Definition of done for any task

- Tests pass locally; lint clean.
- `docs/` updated if behaviour changed; README results table regenerated if metrics changed.
- No file in the diff contains a real person, company, tool or board name. Grep before you finish.
- A short "How to verify" section in the PR description.

## Review guidelines (for `@codex review`)

Flag: any LLM call for something a regex or parser could do; any metric computed outside a run
folder; any prompt change without a baseline update; any synthetic entry with a plausible real
brand or statistic; any English prose in generated README text that reads as marketing fluff.
