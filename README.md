# Editorial QA evaluations

A real editorial QA workflow reviews AI-drafted expert quote pieces against 13 mandatory
checks and 10 recurring writer failure patterns before they go to a PR agency client. This
repo turns that workflow into a measurable system: a golden set of labeled entries, a hybrid
checker (deterministic code for mechanical checks, an LLM judge for editorial judgment), and a
report that answers one question with statistics instead of vibes: **how closely does the
automated judge agree with the human reviewer, per check, with confidence intervals — and
is it safe to let it route pieces?** Regression gates in CI stop prompt or rubric changes
from silently degrading agreement.

## Status

Task 3 adds seeded fictional brief sampling, model-backed clean-body generation,
controlled fault recipes and a manual generation workflow. The parser, ten
deterministic checks, CLI and entry schema remain available. Judge, routing,
metrics and reporting modules remain empty; the browser labeling page is still
a placeholder. No live dataset or agreement results were generated in cloud.

## Results

Pending labeled entries and evaluated runs. No agreement claims yet.

## Architecture

Implemented: an entry JSON file is validated, parsed and checked against local
rule files. Results include pass/fail/na, severity and quoted evidence with item
numbers. The planned judge, run folders, metrics and reports are described in
[the specification](docs/EVAL_SPEC.md).

## Reproduce

The supported workflow uses Codex cloud and the repository web UI.
In cloud setup or CI, from the repository root:

```bash
pip install uv
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

The committed lockfile records dependency resolution. Python 3.11+ is required;
CI checks 3.11 and 3.12. Unit tests require no network or credentials after setup.
To refresh the generated schema after an intentional model change:

```bash
uv run python scripts/export_schema.py
```

The schema test checks that the committed artifact matches the model.
Runtime operations needing network or secrets run as manually triggered
workflow jobs. Generation is available now; the judge remains unimplemented.
The empty variables in `.env.example` document the shared generation/judge
configuration. Never put credentials into tracked files.

## Deterministic checks

From the repository root, inspect the fictional clean test entry:

```bash
uv run python -m editorial_qa_evals.cli check tests/fixtures/clean_entry.json
```

Replace the path with an entry JSON file following `data/schema/entry.schema.json`.
The table includes C1, C2, C3, C6, C8, C9, C11, C12, J2 and J4. The clean fixture
exits 0; any failed check exits 1; invalid input exits 2. No network, credentials
or model calls are needed. This command checks entries; labeling remains a
browser workflow.

See [deterministic conventions](docs/DETERMINISTIC.md) for applicability,
severity, supported formatting and heuristic limits. Unit tests include clean
entries for each piece type and individual fault bodies with expected evidence.

## Synthetic generation

After merging this task, add repository Actions secrets `JUDGE_BASE_URL`,
`JUDGE_MODEL` and `JUDGE_API_KEY`. The base URL is a chat API root, usually ending
in `/v1`, without credentials or query parameters. Run **Actions → Generate
synthetic entries → Run workflow** on `main`, with `n=80`, `seed=7` and
`max_rpm=20`.
Do not call the generation API from a Codex cloud task.

The job normalizes clean draft typography/title casing, then validates before
injecting zero to three faults. Final validation remains strict; injected faults
are never normalized. Exact validation feedback, five attempts per brief and up
to three brief resamples recover individual entries. A run fails only when more
than 10% remain ungenerated; accepted partial runs report missing IDs, final size
and smoke coverage. The default throttle is 20 requests per minute, including
capability fallback and bounded retries for rate limits/server errors. The default plan has 45 simple pitch lists, 20 Q&A and 15 CPR entries,
40 entries per region and 20 clean entries. Publication atomically updates
`data/golden/synthetic.jsonl` and `data/smoke_ids.txt` on `main`, plus the separate
orphan `faults` branch. Public entries contain no fault assignments or human
labels. For a complete run, 20 smoke IDs cover every piece type and intended verdict class;
these intended classes are recipe design targets, not human ground truth.

Open the public dataset and review ten entries for realism and accidental real
names, brands or statistics before labeling. Keep fault assignments and raw
generation provenance out of the labeling process. Model prose must use unnamed
fictional experts; CPR figures are locally constructed, explicitly fictional
simulations with reserved `.invalid` URLs.

See [generation and reconciliation](docs/GENERATION.md) for recipe applicability,
validation, exact offline replay, provenance and post-labeling reconciliation.
The workflow requires permission to push both branches. Existing human labels
are protected from regeneration; a protected branch or racing update makes the
atomic publication fail without partially updating the two branches.

## Browser labeling

In repository Settings → Pages, select **GitHub Actions** as the source once.
After merging to `main`, the Pages workflow deploys `labeling/`; it can also
be triggered from Actions. The deployed page clearly identifies itself as a
placeholder. Labeling, progress persistence and export arrive in a later task.
Read [the labeling guide](docs/LABELING_GUIDE.md) for the review protocol.

## Limitations

The deterministic layer uses documented lexical and structural heuristics; it
does not assess editorial meaning. The judge and agreement evaluation remain
unimplemented. Generation is tested with mocked responses; a live workflow run
and review of its output remain required. Seeded planning and mutations are
repeatable; hosted model responses can vary, so exact reproduction uses saved
raw responses. Future results must account for synthetic data, a single primary reviewer, judge drift, prompt sensitivity and English-only
coverage. Regulatory review is outside scope.

## Licenses

Code: [MIT](LICENSE). Dataset: [CC BY 4.0](data/LICENSE).
