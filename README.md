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

Task 1 scaffold only. The entry model and generated schema are available;
checker, judge, metrics, reporting and CLI modules are empty. The labeling page
is a static placeholder. No dataset, predictions, baseline or measured results exist.

## Results

Pending labeled entries and evaluated runs. No agreement claims yet.

## Architecture

Planned: entries feed deterministic checks and an editorial judge; predictions
are saved in a run folder, from which metrics and reports are computed.
See [the specification](docs/EVAL_SPEC.md) for the planned layout.

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

## Browser labeling

In repository Settings → Pages, select **GitHub Actions** as the source once.
After merging to `main`, the Pages workflow deploys `labeling/`; it can also
be triggered from Actions. The deployed page clearly identifies itself as a
placeholder. Labeling, progress persistence and export arrive in a later task.
Read [the labeling guide](docs/LABELING_GUIDE.md) for the review protocol.

## Limitations

The harness is not implemented yet. Future results must account for synthetic
data, a single primary reviewer, judge drift, prompt sensitivity and English-only
coverage. Regulatory review is outside scope.

## Licenses

Code: [MIT](LICENSE). Dataset: [CC BY 4.0](data/LICENSE).
