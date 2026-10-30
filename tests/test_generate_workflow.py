"""Manual generation workflow contract; no remote calls are made."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_workflow_is_manual_and_keeps_secrets_in_generation_step() -> None:
    doc = yaml.load(
        (ROOT / ".github/workflows/generate.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert set(doc["on"]) == {"workflow_dispatch"}
    inputs = doc["on"]["workflow_dispatch"]["inputs"]
    assert inputs["n"]["default"] == "80"
    assert inputs["seed"]["default"] == "7"
    job = doc["jobs"]["generate"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert "env" not in job
    generation = next(
        step for step in job["steps"] if step.get("name") == "Generate and validate"
    )
    assert set(generation["env"]) == {
        "N",
        "SEED",
        "JUDGE_BASE_URL",
        "JUDGE_MODEL",
        "JUDGE_API_KEY",
    }
    assert '--n "$N" --seed "$SEED"' in generation["run"]
    assert "synthetic-generation/synthetic.jsonl" in generation["run"]
    assert "--run-dir" in generation["run"]
    publisher = next(
        step for step in job["steps"] if step.get("name", "").startswith("Publish")
    )
    assert "env" not in publisher
    assert "publish_synthetic.sh" in publisher["run"]
    artifact = next(
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert artifact["with"]["path"].endswith("/provenance")
    assert doc["permissions"]["contents"] == "write"
