"""Canonical public-entry fingerprints bind hidden faults to their generation."""

import hashlib
import json

from editorial_qa_evals.models import Entry


def entry_sha256(entry: Entry) -> str:
    """Hash public content independently of human labels and reconciled faults."""
    canonical = json.dumps(
        entry.model_dump(mode="json", exclude={"human", "injected_faults"}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
