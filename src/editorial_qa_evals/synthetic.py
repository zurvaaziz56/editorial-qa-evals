"""Seeded synthetic generation; external calls occur only in the CLI job."""

import hashlib
import json
import math
import platform
import random
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import typer
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from editorial_qa_evals.brief_catalog import (
    BANNED,
    check_diversity,
    load_catalog,
    sample_briefs,
)
from editorial_qa_evals.deterministic import Rules, load_rules, run_checks
from editorial_qa_evals.draft_normalization import normalize_clean_draft
from editorial_qa_evals.faults import RECIPES, apply_fault, available_recipes
from editorial_qa_evals.fingerprints import entry_sha256
from editorial_qa_evals.generation_client import GenerationClient
from editorial_qa_evals.generation_errors import GenerationError
from editorial_qa_evals.models import Entry

ROOT = Path(__file__).resolve().parents[2]
VERDICTS = ("READY", "REVISE", "MAJOR")
PIECE_TYPES = ("simple_pitch_list", "qa", "cpr")


class StatDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str = Field(min_length=1)
    relevant: bool
    rationale: str = Field(min_length=1)


class DraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    paragraphs: list[str] = Field(min_length=1, max_length=3)
    question: str = Field(min_length=1)
    statistic: StatDraft | None = None


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[DraftItem] = Field(min_length=3, max_length=7)


class Completion(Protocol):
    def __call__(self, system: str, user: str, seed: int) -> dict[str, Any]: ...


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
    catalog = load_catalog()
    briefs = sample_briefs(n, rng, catalog)
    plans = []
    for index, kind in enumerate(types):
        sampled = dict(briefs[index])
        task = sampled.pop("task_name")
        angle = str(sampled["noun_category"])
        label_key = (
            "clinical red flags"
            if angle == "red flags" and sampled["voice_tier"] == "clinical"
            else angle
        )
        entry = Entry(
            id=f"syn-{index + 1:04d}",
            source="synthetic",
            piece_type=kind,
            region=regions[index],
            task_name=task,
            brief=sampled,
            approved_labels=labels[label_key] if kind == "simple_pitch_list" else [],
            body="",
        )
        plans.append(
            PlannedEntry(entry, assigned.get(index, rng.choice(("REVISE", "MAJOR"))))
        )
    issues = check_diversity([p.entry for p in plans])
    if issues:
        raise GenerationError("Invalid brief plan: " + "; ".join(issues))
    return plans


def _paragraph_count(entry: Entry) -> int:
    return (
        len(entry.approved_labels)
        if entry.piece_type == "simple_pitch_list"
        else (1 if entry.piece_type == "qa" else 2)
    )


@lru_cache(maxsize=12)
def _stat_organisation(domain: str) -> str:
    return load_catalog().domains[domain].stat_organisation


def statistic_context(entry: Entry) -> dict[str, Any] | None:
    """Only locally chosen metadata may appear in a generated source attribution."""
    if entry.piece_type != "cpr":
        return None
    return {
        "organisation": _stat_organisation(entry.brief.domain),
        "region": entry.region,
        "year": 2026,
        "synthetic_source": True,
        "instruction": (
            "For every item propose a survey claim and assess its direct relevance "
            "to that item's prose and brief tip. Set relevant=false if it adds no "
            "support; that statistic will be omitted. Never invent real research."
        ),
    }


def render_statistic(entry: Entry, item: DraftItem, index: int) -> str:
    """Drop a failed semantic self-check; construct figures and attribution locally."""
    statistic = item.statistic
    if statistic is None:
        raise DraftValidationError(
            [
                {
                    "check_id": "STAT_REQUIRED",
                    "item_number": index,
                    "detail": "Each CPR item needs a statistic relevance self-check",
                }
            ]
        )
    if not statistic.relevant:
        return ""
    claim = statistic.claim
    if (
        claim != claim.strip()
        or BANNED.search(claim)
        or re.search(r"[\r\n*<>\d%£$.!?]|https?://|www\.", claim)
        or len(claim.split()) > 40
    ):
        raise DraftValidationError(
            [
                {
                    "check_id": "STAT_CONTENT",
                    "item_number": index,
                    "detail": (
                        "Statistic claim must be plain non-numeric prose "
                        "without meta-language"
                    ),
                    "evidence": claim,
                }
            ]
        )
    # The tip, not its item position, determines the synthetic figures. Resampling
    # reorders tips without changing their statistic seed. No clock or network.
    tip = entry.brief.tips[index - 1]
    rng = random.Random(f"{entry.id}:{tip}:stat-v1")
    percentage = rng.randint(18, 68)
    sample = rng.choice((600, 800, 1200, 1600, 2000))
    context = statistic_context(entry)
    assert context is not None
    return (
        f"In a 2026 survey by {context['organisation']}, {percentage}% of "
        f"{sample} {entry.region} respondents reported {claim} "
        f"(tier 3, {entry.region}, 2026; "
        f"https://source.invalid/survey/{entry.id}/{index})."
    )


def render_draft(entry: Entry, draft: Draft) -> Entry:
    """Render labels/numbering locally; the model generates only prose and questions."""
    if len(draft.items) != len(entry.brief.tips):
        raise DraftValidationError(
            [
                {
                    "check_id": "ITEM_COUNT",
                    "expected": len(entry.brief.tips),
                    "actual": len(draft.items),
                    "detail": "Draft count must equal brief tip count",
                }
            ]
        )
    questions, answers, blocks = [], [], []
    for index, item in enumerate(draft.items, 1):
        if len(item.paragraphs) != _paragraph_count(entry):
            raise DraftValidationError(
                [
                    {
                        "check_id": "PARAGRAPH_COUNT",
                        "item_number": index,
                        "location": f"items.{index - 1}.paragraphs",
                        "expected": _paragraph_count(entry),
                        "actual": len(item.paragraphs),
                        "evidence": item.paragraphs,
                        "detail": "Draft has an incorrect paragraph count",
                    }
                ]
            )
        for text in [item.title, item.question, *item.paragraphs]:
            if BANNED.search(text):
                raise DraftValidationError(
                    [
                        {
                            "check_id": "BANNED_WORD",
                            "item_number": index,
                            "evidence": text,
                            "detail": (
                                "Draft text must omit fictional, "
                                "invented and simulation"
                            ),
                        }
                    ]
                )
            if (
                not text.strip()
                or text != text.strip()
                or re.search(r"[\r\n*<>\d%£$]|https?://|www\.", text)
            ):
                raise DraftValidationError(
                    [
                        {
                            "check_id": "CONTENT",
                            "item_number": index,
                            "evidence": text,
                            "detail": (
                                "Draft contains empty text, markup, newlines, "
                                "figures or URLs"
                            ),
                        }
                    ]
                )
        if not item.question.endswith("?") or item.question.count("?") != 1:
            raise DraftValidationError(
                [
                    {
                        "check_id": "QUESTION_FORMAT",
                        "item_number": index,
                        "evidence": item.question,
                        "detail": "Each draft question must be one question",
                    }
                ]
            )
        for paragraph in item.paragraphs:
            if len(re.findall(r"[.!?](?:\s|$)", paragraph)) not in (2, 3):
                raise DraftValidationError(
                    [
                        {
                            "check_id": "J3",
                            "item_number": index,
                            "evidence": paragraph,
                            "detail": (
                                "Draft paragraphs must contain two or three sentences"
                            ),
                        }
                    ]
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
            statistic = render_statistic(entry, item, index)
            blocks.append(
                f"{index}. {item.title}\n{item.paragraphs[0]}\n"
                + (statistic + "\n" if statistic else "")
                + f"Top tip: {item.paragraphs[1]}"
            )
    body = "\n\n".join(blocks)
    if entry.piece_type == "cpr":
        quote = draft.items[0].paragraphs[0].split(". ", 1)[0].rstrip(".") + "."
        body = (
            f"The {entry.brief.expert.credential.lower()} "
            f"{'specialises' if entry.region == 'UK' else 'specializes'} in "
            f"{entry.brief.expert.specialism}.\n\n“{quote}”\n\n" + body
        )
    return entry.model_copy(
        update={"body": body, "questions": questions, "answers": answers}
    )


class DraftValidationError(GenerationError):
    def __init__(self, issues: list[dict[str, Any]]) -> None:
        self.issues = issues
        super().__init__(issues[0]["detail"])


class BatchGenerationError(GenerationError):
    def __init__(self, summary: dict[str, Any]) -> None:
        self.summary = summary
        super().__init__(
            f"Could not generate {summary['failed_entries']} of "
            f"{summary['requested_entries']} entries: more than 10% failed"
        )


def draft_schema(paragraph_count: int, item_count: int = 5) -> dict[str, Any]:
    schema = Draft.model_json_schema()
    schema["properties"]["items"]["minItems"] = item_count
    schema["properties"]["items"]["maxItems"] = item_count
    # Strict output APIs require every declared key, with null for absent statistics.
    schema["$defs"]["DraftItem"]["required"].append("statistic")
    schema["$defs"]["DraftItem"]["properties"]["statistic"].pop("default", None)
    paragraphs = schema["$defs"]["DraftItem"]["properties"]["paragraphs"]
    paragraphs["minItems"] = paragraphs["maxItems"] = paragraph_count
    return schema


def prepare_clean_draft(
    entry: Entry,
    raw: dict[str, Any],
    rules: Rules,
) -> tuple[Entry | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize only model drafts, then run the unchanged final-output validators."""
    changes: list[dict[str, Any]] = []
    try:
        content = raw["choices"][0]["message"]["content"]
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError("Expected a draft object")
    except (KeyError, IndexError, TypeError, ValueError):
        return (
            None,
            changes,
            [
                {
                    "check_id": "SCHEMA",
                    "location": "response",
                    "detail": (
                        "Expected a JSON draft object in choices[0].message.content"
                    ),
                }
            ],
        )
    normalized, changes = normalize_clean_draft(value, rules["proper_nouns"])
    try:
        draft = Draft.model_validate(normalized)
    except ValidationError as error:
        return (
            None,
            changes,
            [
                {
                    "check_id": "SCHEMA",
                    "location": list(issue["loc"]),
                    "detail": issue["msg"],
                    "evidence": issue.get("input"),
                }
                for issue in error.errors(include_url=False)
            ],
        )
    try:
        clean = render_draft(entry, draft)
    except DraftValidationError as error:
        return None, changes, error.issues
    failures = [
        result.model_dump()
        for result in run_checks(clean, rules)
        if result.result == "fail"
    ]
    return (None if failures else clean), changes, failures


def resample_entry(entry: Entry, seed: int, resample: int) -> Entry:
    """Keep catalog assignments and tip ownership; vary order and hook for recovery.

    Replacing tips from another entry's reserved pool would break uniqueness.
    Reordering this entry's tips is a new prompt without consuming another pool.
    """
    rng = random.Random(f"{seed}:{entry.id}:resample:{resample}")
    tips = list(entry.brief.tips)
    rng.shuffle(tips)
    if tips == entry.brief.tips:
        tips = tips[1:] + tips[:1]
    domain = load_catalog().domains[entry.brief.domain]
    hooks = [hook for hook in domain.hooks if hook != entry.brief.hook]
    return entry.model_copy(
        update={
            "brief": entry.brief.model_copy(
                update={
                    "tips": tips,
                    "hook": rng.choice(hooks),
                }
            )
        }
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
    entries: list[Entry],
    intended: dict[str, str],
    seed: int,
    *,
    allow_partial: bool = False,
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
                if allow_partial:
                    continue
                raise GenerationError(
                    f"Missing intended smoke stratum: {kind}/{verdict}"
                )
            chosen.append(candidate)
    remaining = [entry.id for entry in entries if entry.id not in chosen]
    random.Random(seed).shuffle(remaining)
    result = chosen + remaining[: min(20, len(entries)) - len(chosen)]
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
    max_rpm: float = 20,
) -> dict[str, Any]:
    if not math.isfinite(max_rpm) or max_rpm <= 0:
        raise GenerationError("max-rpm must be a finite positive number")
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
                "brief_catalog.py",
                "faults.py",
                "parser.py",
                "deterministic.py",
                "models.py",
                "fingerprints.py",
                "draft_normalization.py",
                "generation_client.py",
                "generation_errors.py",
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
        "generator_version": 3,
        "max_rpm": max_rpm,
        "max_tokens": (
            json.loads((replay_run / "config.json").read_text())["max_tokens"]
            if replay_run
            else getattr(completion, "max_tokens", None)
        ),
        "max_attempts": 5,
        "max_resamples": 3,
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
    failure_counts: Counter[str] = Counter()
    normalization_counts: Counter[str] = Counter()
    failed_ids: list[str] = []
    attempt_count = resample_count = 0
    statistics: Counter[str] = Counter()
    for plan in plans:
        entry = plan.entry
        clean = None
        last_failures: list[dict[str, Any]] = []
        for resample in range(4):  # Original brief plus at most three replacements.
            if resample:
                previous = entry
                entry = resample_entry(previous, seed, resample)
                resample_count += 1
                _json(
                    run_dir / "resamples" / f"{entry.id}-{resample}.json",
                    {
                        "id": entry.id,
                        "resample": resample,
                        "previous_brief": previous.model_dump(
                            exclude={"human", "injected_faults", "body"}
                        ),
                        "new_brief": entry.model_dump(
                            exclude={"human", "injected_faults", "body"}
                        ),
                        "reason": last_failures,
                    },
                )
            payload = {
                **entry.model_dump(exclude={"human", "injected_faults", "body"}),
                "paragraphs_per_item": _paragraph_count(entry),
                "forbidden_phrases": rules["phrases"],
                "voice_tier": entry.brief.voice_tier,
                "statistic_context": statistic_context(entry),
                "response_schema": draft_schema(
                    _paragraph_count(entry), len(entry.brief.tips)
                ),
            }
            history = []
            for attempt in range(1, 6):
                attempt_count += 1
                filename = f"{entry.id}-resample-{resample}-attempt-{attempt}.json"
                raw_path = Path("raw") / filename
                attempt_path = Path("attempts") / filename
                feedback = (
                    (
                        "\nValidation feedback from previous attempts:\n"
                        + json.dumps(history, ensure_ascii=False)
                    )
                    if history
                    else ""
                )
                user = json.dumps(payload, ensure_ascii=False) + feedback
                changes: list[dict[str, Any]] = []
                try:
                    if replay_run:
                        recorded = json.loads((replay_run / attempt_path).read_text())
                        if recorded["status"] == "api_failed":
                            raise GenerationError(recorded["failures"][0]["detail"])
                        raw = json.loads((replay_run / raw_path).read_text())
                    else:
                        raw = completion(prompt, user, seed)
                    _json(run_dir / raw_path, raw)
                    clean, changes, last_failures = prepare_clean_draft(
                        entry, raw, rules
                    )
                    status = "passed" if clean is not None else "validation_failed"
                except GenerationError as error:
                    clean = None
                    last_failures = [{"check_id": "API", "detail": str(error)}]
                    status = "api_failed"
                normalization_counts.update(change["operation"] for change in changes)
                failure_counts.update(
                    {failure["check_id"] for failure in last_failures}
                )
                _json(
                    run_dir / attempt_path,
                    {
                        "id": entry.id,
                        "resample": resample,
                        "attempt": attempt,
                        "status": status,
                        "normalizations": changes,
                        "failures": last_failures,
                        "brief": payload,
                        "raw_path": str(raw_path) if status != "api_failed" else None,
                    },
                )
                if clean is not None:
                    break
                history.append({"attempt": attempt, "failures": last_failures})
            if clean is not None:
                break
        if clean is None:
            failed_ids.append(entry.id)
            continue
        if clean.piece_type == "cpr":
            rendered = clean.body.count("https://source.invalid/survey/")
            statistics.update(
                {"rendered": rendered, "dropped": len(clean.brief.tips) - rendered}
            )
        # No normalization or repair is permitted beyond this boundary.
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
    intended = {row["id"]: row["intended_verdict"] for row in fault_rows}
    smoke = select_smoke(entries, intended, seed, allow_partial=bool(failed_ids))
    public = "".join(
        entry.model_dump_json(exclude={"injected_faults", "human"}) + "\n"
        for entry in entries
    )
    faults = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in fault_rows)
    summary = {
        "requested_entries": n,
        "entries": len(entries),
        "failed_entries": len(failed_ids),
        "failed_ids": failed_ids,
        "attempts": attempt_count,
        "resamples": resample_count,
        "failure_summary": dict(sorted(failure_counts.items())),
        "normalization_counts": dict(sorted(normalization_counts.items())),
        "cpr_statistics": dict(statistics),
        "smoke_entries": len(smoke),
        "missing_smoke_strata": [
            f"{kind}/{verdict}"
            for kind in PIECE_TYPES
            for verdict in VERDICTS
            if not any(
                e.piece_type == kind and intended[e.id] == verdict for e in entries
            )
        ],
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
    if len(failed_ids) * 10 > n:
        raise BatchGenerationError(summary)
    diversity_issues = check_diversity(entries)
    if diversity_issues:
        raise GenerationError(
            "Survivor diversity failed: " + "; ".join(diversity_issues)
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(public, encoding="utf-8")
    (out.parent / "faults.jsonl").write_text(faults, encoding="utf-8")
    (out.parent / "smoke_ids.txt").write_text("\n".join(smoke) + "\n")
    return summary


app = typer.Typer(add_completion=False)


@app.command()
def main(
    n: int = typer.Option(80, min=20),
    seed: int = 7,
    out: Path = Path("data/golden/synthetic.jsonl"),
    run_dir: Path | None = None,
    replay_run: Path | None = None,
    max_rpm: float = typer.Option(20, min=0.001),
    max_tokens: int = typer.Option(2048, min=1),
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
                os.environ["JUDGE_BASE_URL"],
                model_name,
                os.environ["JUDGE_API_KEY"],
                max_rpm=max_rpm,
                max_tokens=max_tokens,
            )
        summary = generate_dataset(
            n, seed, out, run_dir, completion, model_name, replay_run, max_rpm
        )
    except BatchGenerationError as error:
        typer.echo(json.dumps(error.summary, indent=2), err=True)
        typer.echo(f"Generation failed: {error}", err=True)
        raise typer.Exit(1) from None
    except (OSError, ValueError) as error:
        # Do not print request headers, endpoint credentials or raw model content.
        typer.echo(f"Generation failed: {error}", err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(summary, indent=2))


if __name__ == "__main__":
    app()
