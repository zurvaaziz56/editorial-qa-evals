"""Regenerate the checked-in entry schema from the model."""

import json
from pathlib import Path

from editorial_qa_evals.models import Entry


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "data/schema/entry.schema.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(Entry.model_json_schema(), indent=2) + "\n")


if __name__ == "__main__":
    main()
