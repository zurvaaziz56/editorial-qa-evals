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

Task 2 provides a body/Q&A parser and ten offline deterministic checks with a
CLI table. The entry model and generated schema remain available. Judge,
routing, metrics and reporting modules remain empty. The browser labeling page
is a static placeholder; no dataset, predictions, baseline or agreement results exist.

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
Future runtime operations needing network or secrets must have manually
triggered workflow jobs. No such operations are implemented in this scaffold.
The empty variables in `.env.example` document future judge configuration;
never put credentials into tracked files.

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

## Browser labeling

In repository Settings → Pages, select **GitHub Actions** as the source once.
After merging to `main`, the Pages workflow deploys `labeling/`; it can also
be triggered from Actions. The deployed page clearly identifies itself as a
placeholder. Labeling, progress persistence and export arrive in a later task.
Read [the labeling guide](docs/LABELING_GUIDE.md) for the review protocol.

## Limitations

The deterministic layer uses documented lexical and structural heuristics; it
does not assess editorial meaning. The judge and agreement evaluation remain
unimplemented. Future results must account for synthetic
data, a single primary reviewer, judge drift, prompt sensitivity and English-only
coverage. Regulatory review is outside scope.

## Licenses

Code: [MIT](LICENSE). Dataset: [CC BY 4.0](data/LICENSE).
