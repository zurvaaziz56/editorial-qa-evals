"""Seeded synthetic generation; external calls occur only in the CLI job."""

import hashlib
import json
import math
import platform
import random
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
import typer
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from editorial_qa_evals.deterministic import Rules, load_rules, run_checks
from editorial_qa_evals.faults import RECIPES, apply_fault, available_recipes
from editorial_qa_evals.fingerprints import entry_sha256
from editorial_qa_evals.models import Entry

ROOT = Path(__file__).resolve().parents[2]
VERDICTS = ("READY", "REVISE", "MAJOR")
PIECE_TYPES = ("simple_pitch_list", "qa", "cpr")
# Fictional scenarios without expert identities or external facts.
TOPICS = {
    "mistakes": [
        "Late pauses",
        "Crowded routines",
        "Rushed transitions",
        "Missed breaks",
        "Uneven rhythms",
    ],
    "red flags": [
        "Restless evenings",
        "Repeated interruptions",
        "Unsettled mornings",
        "Narrow recovery",
        "Persistent overload",
    ],
    "tips": [
        "Quiet pauses",
        "Steady routines",
        "Gentle transitions",
        "Shared planning",
        "Restful evenings",
    ],
    "waste of money": [
        "Duplicate cushions",
        "Unused organizers",
        "Spare baskets",
        "Novelty timers",
        "Extra trays",
    ],
}


class GenerationError(ValueError):
    """A generation invariant failed; no dataset should be published."""


class DraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    paragraphs: list[str] = Field(min_length=1, max_length=3)
    question: str = Field(min_length=1)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[DraftItem] = Field(min_length=5, max_length=5)


class Completion(Protocol):
    def __call__(self, system: str, user: str, seed: int) -> dict[str, Any]: ...


class GenerationClient:
    """Small provider-neutral chat client; no judge implementation is introduced."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        url = urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise GenerationError(
                "JUDGE_BASE_URL needs an HTTP(S) API root without credentials/query"
            )
        if not model.strip() or not api_key.strip():
            raise GenerationError("JUDGE_MODEL and JUDGE_API_KEY must be configured")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._transport = transport
        self._sleep = sleep

    def __call__(self, system: str, user: str, seed: int) -> dict[str, Any]:
        # Sampling and fault selection use seed locally. A provider-specific seed
        # parameter is deliberately avoided; exact replay uses retained responses.
        with httpx.Client(transport=self._transport, timeout=90.0) as client:
            for attempt in range(3):
                try:
                    response = client.post(
                        self.base_url + "/chat/completions",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json={
                            "model": self.model,
                            "temperature": 0,
                            "response_format": {"type": "json_object"},
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": user},
                            ],
                        },
                    )
                except httpx.TransportError:
                    if attempt == 2:
                        raise GenerationError(
                            "Generation transport failed after three attempts"
                        ) from None
                    self._sleep(2**attempt)
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        self._sleep(2**attempt)
                        continue
                if response.is_error:
                    raise GenerationError(
                        f"Generation API returned HTTP {response.status_code}"
                    )
                try:
                    return response.json()
                except ValueError:
                    raise GenerationError(
                        "Generation API returned non-JSON content"
                    ) from None
        raise GenerationError("Generation request did not complete")


@dataclass(frozen=True)
class PlannedEntry:
    entry: Entry
    intended_verdict: str


def plan_entries(n: int, seed: int) -> list[PlannedEntry]:
    """Largest-remainder type quotas; exact region balance and 25% clean to rounding."""
    if n < 20:
        raise GenerationError("n must be at least 20 to create a 20-entry smoke subset")
    rng = random.Random(seed)
    quotas = [n * weight / 80 for weight in (45, 20, 15)]
    counts = [math.floor(value) for value in quotas]
    for index in sorted(range(3), key=lambda i: (-(quotas[i] - counts[i]), i))[
        : n - sum(counts)
    ]:
        counts[index] += 1
    types = [
        kind
        for kind, count in zip(PIECE_TYPES, counts, strict=True)
        for _ in range(count)
    ]
    rng.shuffle(types)
    clean_count = max(3, round(n / 4))
    clean_indices = set()
    reserved = set()
    assigned = {}
    for kind in PIECE_TYPES:
        indices = [i for i, value in enumerate(types) if value == kind]
        rng.shuffle(indices)
        clean_indices.add(indices[0])
        reserved.update(indices[1:3])
        assigned[indices[1]], assigned[indices[2]] = "REVISE", "MAJOR"
    eligible = [i for i in range(n) if i not in clean_indices | reserved]
    clean_indices.update(rng.sample(eligible, clean_count - 3))
    assigned.update({i: "READY" for i in clean_indices})
    regions = ["UK"] * ((n + 1) // 2) + ["US"] * (n // 2)
    rng.shuffle(regions)
    labels = yaml.safe_load((ROOT / "rules/labels.yaml").read_text())["labels"]
    plans = []
    for index, kind in enumerate(types):
        # Guarantee cost-label cases in each seed without forcing every piece to cost.
        angle = (
            "waste of money"
            if kind == "simple_pitch_list" and index == types.index(kind)
            else rng.choice(list(TOPICS))
        )
        tips = rng.sample(TOPICS[angle], 5)
        clinical = index % 3 == 0
        credential = (
            "Clinical wellbeing practitioner" if clinical else "Psychotherapist"
        )
        headline_angle = "wastes of money" if angle == "waste of money" else angle
        task = f"{credential} reveals 5 {headline_angle} in a fictional household"
        entry = Entry(
            id=f"syn-{index + 1:04d}",
            source="synthetic",
            piece_type=kind,
            region=regions[index],
            task_name=task,
            brief={
                "tips": tips,
                "hook": "Everyday choices in an invented household",
                "tone": "Clinical and precise"
                if clinical
                else "Accessible and precise",
                "expert": {
                    "credential": credential,
                    "specialism": "Fictional household routines",
                },
            },
            approved_labels=labels[angle] if kind == "simple_pitch_list" else [],
            body="",
        )
        plans.append(
            PlannedEntry(entry, assigned.get(index, rng.choice(("REVISE", "MAJOR"))))
        )
    return plans


def _paragraph_count(entry: Entry) -> int:
    return (
        len(entry.approved_labels)
        if entry.piece_type == "simple_pitch_list"
        else (1 if entry.piece_type == "qa" else 2)
    )


def render_draft(entry: Entry, draft: Draft) -> Entry:
    """Render labels/numbering locally; the model generates only prose and questions."""
    questions, answers, blocks = [], [], []
    for index, item in enumerate(draft.items, 1):
        if len(item.paragraphs) != _paragraph_count(entry):
            raise GenerationError("Draft has an incorrect paragraph count")
        for text in [item.title, item.question, *item.paragraphs]:
            if (
                not text.strip()
                or text != text.strip()
                or re.search(r"[\r\n*<>\d%£$]|https?://|www\.", text)
            ):
                raise GenerationError(
                    "Draft contains empty text, markup, newlines, figures or URLs"
                )
        if not item.question.endswith("?") or item.question.count("?") != 1:
            raise GenerationError("Each draft question must be one question")
        for paragraph in item.paragraphs:
            if len(re.findall(r"[.!?](?:\s|$)", paragraph)) not in (2, 3):
                raise GenerationError(
                    "Draft paragraphs must contain two or three sentences"
                )
        if entry.piece_type == "qa":
            questions.append(item.question)
            answers.append(item.paragraphs[0])
            blocks.append(f"Q{index}: {item.question}\nA{index}: {item.paragraphs[0]}")
        elif entry.piece_type == "simple_pitch_list":
            sections = "\n".join(
                f"**{label}:** {text}"
                for label, text in zip(
                    entry.approved_labels, item.paragraphs, strict=True
                )
            )
            blocks.append(f"{index}. {item.title}\n{sections}")
        else:
            # Every statistic is locally authored and explicitly fictional, with a
            # reserved nonresolving URL; it can never be mistaken for live sourcing.
            statistic = (
                f"In a fictional simulation, {index + 6} of 19 invented rooms "
                f"used this approach (fictional source, tier 3, {entry.region}, 2026; "
                f"https://source.invalid/simulation/{entry.id}/{index})."
            )
            blocks.append(
                f"{index}. {item.title}\n{item.paragraphs[0]}\n{statistic}\n"
                f"Top tip: {item.paragraphs[1]}"
            )
    body = "\n\n".join(blocks)
    if entry.piece_type == "cpr":
        body = (
            f"The fictional {entry.brief.expert.credential.lower()} "
            "works with invented household routines.\n\n"
            "“Familiar routines can make room for a quiet pause.”\n\n" + body
        )
    return entry.model_copy(
        update={"body": body, "questions": questions, "answers": answers}
    )


def _failure_ids(entry: Entry, rules: Rules) -> set[str]:
    return {
        result.check_id
        for result in run_checks(entry, rules)
        if result.result == "fail"
    }


def verify_faults(
    entry: Entry, names: list[str], rules: Rules
) -> dict[str, dict[str, int]]:
    failures = _failure_ids(entry, rules)
    expected = {check for name in names for check in RECIPES[name].checks}
    confusion = {
        check: {
            "detected": int(check in failures),
            "missed": int(check not in failures),
        }
        for check in sorted(expected)
    }
    missing = expected - failures
    if missing:
        raise GenerationError(
            f"Undetected deterministic fault for {entry.id}: "
            f"{','.join(sorted(missing))}; "
            f"confusion={json.dumps(confusion, sort_keys=True)}"
        )
    return confusion


def inject_faults(
    entry: Entry, verdict: str, rng: random.Random, rules: Rules
) -> tuple[Entry, list[str]]:
    if verdict == "READY":
        return entry, []
    names: list[str] = []
    mutated = entry
    target = rng.randint(1, 3)
    for position in range(target):
        choices = [name for name in available_recipes(mutated) if name not in names]
        rng.shuffle(choices)
        for name in choices:
            recipe = RECIPES[name]
            rank = VERDICTS.index(recipe.intended_verdict)
            if rank > VERDICTS.index(verdict) or (
                position == 0 and recipe.intended_verdict != verdict
            ):
                continue
            if name in {"count_plus", "count_minus", "dropped_tip"} and set(names) & {
                "count_plus",
                "count_minus",
                "dropped_tip",
            }:
                continue
            if "bundled_q5" in {name, *names} and set([name, *names]) & {
                "dropped_tip",
                "count_minus",
            }:
                continue
            candidate = apply_fault(mutated, name, rng)
            try:
                verify_faults(candidate, [*names, name], rules)
            except GenerationError:
                continue  # Reject interactions that cancel a prior deterministic fault.
            if candidate.model_dump() == mutated.model_dump():
                continue
            mutated, names = candidate, [*names, name]
            break
        else:
            break
    if not names:
        raise GenerationError(f"No compatible {verdict} recipe for {entry.id}")
    return mutated, names


def select_smoke(
    entries: list[Entry], intended: dict[str, str], seed: int
) -> list[str]:
    chosen = []
    for kind in PIECE_TYPES:
        for verdict in VERDICTS:
            candidate = next(
                (
                    entry.id
                    for entry in entries
                    if entry.piece_type == kind and intended[entry.id] == verdict
                ),
                None,
            )
            if candidate is None:
                raise GenerationError(
                    f"Missing intended smoke stratum: {kind}/{verdict}"
                )
            chosen.append(candidate)
    remaining = [entry.id for entry in entries if entry.id not in chosen]
    random.Random(seed).shuffle(remaining)
    result = chosen + remaining[: 20 - len(chosen)]
    random.Random(seed).shuffle(result)
    return result


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def generate_dataset(
    n: int,
    seed: int,
    out: Path,
    run_dir: Path,
    completion: Completion,
    model_name: str = "mock",
    replay_run: Path | None = None,
) -> dict[str, Any]:
    outputs = [out, out.parent / "faults.jsonl", out.parent / "smoke_ids.txt"]
    if out.name in {"faults.jsonl", "smoke_ids.txt"}:
        raise GenerationError("Public output uses a reserved sidecar filename")
    for output in outputs:
        if (
            output.resolve().is_relative_to(run_dir.resolve())
            or run_dir.resolve().is_relative_to(output.resolve())
            or (replay_run and output.resolve().is_relative_to(replay_run.resolve()))
        ):
            raise GenerationError("Public/sidecar outputs must not overlap provenance")
    plans = plan_entries(n, seed)
    rules = load_rules()
    prompt_path = ROOT / "prompts/synthetic/generate_body.md"
    prompt = prompt_path.read_text()
    hashes = {
        str(path.relative_to(ROOT)): _hash(path.read_bytes())
        for path in [prompt_path, *sorted((ROOT / "rules").glob("*.yaml"))]
    }
    source_files = [
        ROOT / "uv.lock",
        *[
            ROOT / "src/editorial_qa_evals" / filename
            for filename in (
                "synthetic.py",
                "faults.py",
                "parser.py",
                "deterministic.py",
                "models.py",
                "fingerprints.py",
            )
        ],
    ]
    sources = {
        str(path.relative_to(ROOT)): _hash(path.read_bytes()) for path in source_files
    }
    config = {
        "n": n,
        "seed": seed,
        "model": model_name,
        "generator_version": 1,
        "python_version": platform.python_version(),
    }
    if replay_run:
        if (
            json.loads((replay_run / "config.json").read_text()) != config
            or json.loads((replay_run / "prompt_hashes.json").read_text()) != hashes
            or json.loads((replay_run / "source_hashes.json").read_text()) != sources
        ):
            raise GenerationError(
                "Replay configuration or prompt/rule/source hashes differ"
            )
    if run_dir.exists() and any(run_dir.iterdir()):
        raise GenerationError(
            "run-dir must be new or empty to protect prior provenance"
        )
    _json(run_dir / "config.json", config)
    _json(run_dir / "prompt_hashes.json", hashes)
    _json(run_dir / "source_hashes.json", sources)
    entries, fault_rows = [], []
    totals: dict[str, Counter[str]] = {}
    rng = random.Random(seed)
    for plan in plans:
        entry = plan.entry
        payload = {
            **entry.model_dump(exclude={"human", "injected_faults", "body"}),
            "paragraphs_per_item": _paragraph_count(entry),
            "forbidden_phrases": rules["phrases"],
            "response_schema": Draft.model_json_schema(),
        }
        errors = ""
        for attempt in range(3):
            raw_path = Path("raw") / f"{entry.id}-attempt-{attempt + 1}.json"
            user = json.dumps(payload, ensure_ascii=False) + errors
            raw = (
                json.loads((replay_run / raw_path).read_text())
                if replay_run
                else completion(prompt, user, seed)
            )
            _json(run_dir / raw_path, raw)
            try:
                content = raw["choices"][0]["message"]["content"]
                clean = render_draft(entry, Draft.model_validate_json(content))
                failures = _failure_ids(clean, rules)
                if failures:
                    raise GenerationError(
                        "Clean draft failed checks: " + ",".join(sorted(failures))
                    )
            except (
                KeyError,
                IndexError,
                TypeError,
                ValidationError,
                GenerationError,
            ) as error:
                # ValidationError can contain provider text; feed safe feedback only.
                # Raw responses remain in ignored raw/ for diagnosis and replay.
                errors = (
                    "\nPrevious response failed validation. "
                    "Follow all format constraints."
                )
                if isinstance(error, GenerationError):
                    errors += " " + str(error)
                if attempt == 2:
                    raise GenerationError(
                        f"Clean draft for {entry.id} failed validation "
                        "after three attempts"
                    ) from None
                continue
            break
        mutated, names = inject_faults(clean, plan.intended_verdict, rng, rules)
        confusion = verify_faults(mutated, names, rules)
        for check, counts in confusion.items():
            totals.setdefault(check, Counter()).update(counts)
        entries.append(mutated)
        fault_rows.append(
            {
                "id": entry.id,
                "entry_sha256": entry_sha256(mutated),
                "recipes": names,
                "injected_faults": sorted(
                    {check for name in names for check in RECIPES[name].rubric_checks}
                ),
                "intended_verdict": plan.intended_verdict,
            }
        )
    smoke = select_smoke(
        entries, {row["id"]: row["intended_verdict"] for row in fault_rows}, seed
    )
    public = "".join(
        entry.model_dump_json(exclude={"injected_faults", "human"}) + "\n"
        for entry in entries
    )
    faults = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in fault_rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(public, encoding="utf-8")
    (out.parent / "faults.jsonl").write_text(faults, encoding="utf-8")
    (out.parent / "smoke_ids.txt").write_text("\n".join(smoke) + "\n")
    summary = {
        "entries": len(entries),
        "types": dict(Counter(entry.piece_type for entry in entries)),
        "regions": dict(Counter(entry.region for entry in entries)),
        "clean": sum(not row["recipes"] for row in fault_rows),
        "deterministic_confusion": {
            key: dict(value) for key, value in sorted(totals.items())
        },
        "public_sha256": _hash(public.encode()),
        "faults_sha256": _hash(faults.encode()),
    }
    _json(run_dir / "validation.json", summary)
    return summary


app = typer.Typer(add_completion=False)


@app.command()
def main(
    n: int = typer.Option(80, min=20),
    seed: int = 7,
    out: Path = Path("data/golden/synthetic.jsonl"),
    run_dir: Path | None = None,
    replay_run: Path | None = None,
) -> None:
    """Generate fictional entries. Run live generation only in the manual workflow."""
    import os

    load_dotenv()
    run_dir = run_dir or Path("runs") / (
        "generation-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    try:
        if replay_run:
            model_name = json.loads((replay_run / "config.json").read_text())["model"]

            def offline(system: str, user: str, seed: int) -> dict[str, Any]:
                raise GenerationError("Replay must not call a model")

            completion: Completion = offline
        else:
            names = ("JUDGE_BASE_URL", "JUDGE_MODEL", "JUDGE_API_KEY")
            if any(not os.environ.get(name, "").strip() for name in names):
                raise GenerationError(
                    "Configure JUDGE_BASE_URL, JUDGE_MODEL and JUDGE_API_KEY "
                    "as repository secrets"
                )
            model_name = os.environ["JUDGE_MODEL"]
            completion = GenerationClient(
                os.environ["JUDGE_BASE_URL"], model_name, os.environ["JUDGE_API_KEY"]
            )
        summary = generate_dataset(
            n, seed, out, run_dir, completion, model_name, replay_run
        )
    except (OSError, ValueError) as error:
        # Do not print request headers, endpoint credentials or raw model content.
        typer.echo(f"Generation failed: {error}", err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(summary, indent=2))


if __name__ == "__main__":
    app()
