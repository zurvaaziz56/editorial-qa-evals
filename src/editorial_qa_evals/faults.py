"""Seeded, explicit faults applied after clean fictional body generation."""

import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from editorial_qa_evals.models import Entry
from editorial_qa_evals.parser import LABEL, parse_items, quote_state


@dataclass(frozen=True)
class Recipe:
    name: str
    checks: tuple[str, ...]
    intended_verdict: Literal["READY", "REVISE", "MAJOR"]
    rubric_checks: tuple[str, ...]


RECIPES = {
    recipe.name: recipe
    for recipe in (
        Recipe("count_plus", ("C11",), "MAJOR", ("C11",)),
        Recipe("count_minus", ("C11",), "MAJOR", ("C11", "C4")),
        Recipe("noun_drift", (), "MAJOR", ("J1", "C13")),
        Recipe("orphan_closers", ("C12",), "MAJOR", ("C12",)),
        Recipe("intro_lines", ("C12",), "REVISE", ("C12",)),
        Recipe("mini_labels", ("C2",), "REVISE", ("C2",)),
        Recipe("cost_placeholder", ("C3",), "REVISE", ("C3",)),
        Recipe("em_dash", ("C8",), "REVISE", ("C8",)),
        Recipe("region_swap", ("C9",), "REVISE", ("C9",)),
        Recipe("generic_credential", (), "REVISE", ("C10",)),
        Recipe("dropped_tip", (), "MAJOR", ("C4", "C13")),
        Recipe("bundled_q5", (), "REVISE", ("C7",)),
        Recipe("mixed_quotes", ("C6",), "REVISE", ("C6",)),
        Recipe("filler", ("J4",), "REVISE", ("J4",)),
        Recipe("clinical_colloquialism", (), "REVISE", ("J5",)),
    )
}

NOUN = re.compile(
    r"\b(?:mistakes|red flags|signs|tips|habits|wastes? of money)\b", re.IGNORECASE
)
COST = re.compile(r"\b(?:cost|penalty|savings)\b", re.IGNORECASE)


def _qa_body(questions: list[str], answers: list[str]) -> str:
    return "\n\n".join(
        f"Q{number}: {question}\nA{number}: {answer}"
        for number, (question, answer) in enumerate(
            zip(questions, answers, strict=True), 1
        )
    )


def _with_qa(entry: Entry, questions: list[str], answers: list[str]) -> Entry:
    return entry.model_copy(
        update={
            "questions": questions,
            "answers": answers,
            "body": _qa_body(questions, answers),
        }
    )


def _list_parts(entry: Entry) -> tuple[str, list[str]]:
    items = parse_items(entry.body)
    if not items:
        raise ValueError("A numbered body is required for this recipe")
    return entry.body[: items[0].start].strip(), [item.text.strip() for item in items]


def _with_items(entry: Entry, preamble: str, items: list[str]) -> Entry:
    numbered = [
        re.sub(
            r"^([ \t]*(?:\*\*)?)\d+([.)])",
            lambda match, number=number: f"{match.group(1)}{number}{match.group(2)}",
            text,
            count=1,
        )
        for number, text in enumerate(items, 1)
    ]
    body = "\n\n".join(([preamble] if preamble else []) + numbered)
    return entry.model_copy(update={"body": body})


def _unwrap(answer: str) -> tuple[str, str, str]:
    text = answer.strip()
    if quote_state(text) == "quoted":
        return text[1:-1], text[0], text[-1]
    return text, "", ""


def _edit_prose(entry: Entry, transform: Callable[[str], str]) -> Entry:
    """Modify content while keeping section labels and Q&A wrapping intact."""
    if entry.piece_type == "qa":
        answers = list(entry.answers)
        text, opening, closing = _unwrap(answers[0])
        answers[0] = opening + transform(text) + closing
        return _with_qa(entry, list(entry.questions), answers)
    preamble, parts = _list_parts(entry)
    first = parts[0]
    labels = list(LABEL.finditer(first))
    if labels:
        marker = labels[0]
        stop = labels[1].start() if len(labels) > 1 else len(first)
        content = first[marker.end() : stop]
        edited = (
            " " + transform(content.strip()) + ("\n" if content.endswith("\n") else "")
        )
        parts[0] = first[: marker.end()] + edited + first[stop:]
    else:
        title, _, content = first.partition("\n")
        parts[0] = title + "\n" + transform(content.strip())
    return _with_items(entry, preamble, parts)


def available_recipes(entry: Entry) -> list[str]:
    """Return shape-compatible recipes without inferring semantic quality."""
    qa = entry.piece_type == "qa"
    items = parse_items(entry.body)
    count = len(entry.questions) if qa else len(items)
    paired = bool(entry.questions) and len(entry.questions) == len(entry.answers)
    if (qa and not paired) or (not qa and not items):
        return []
    names = ["count_plus", "em_dash", "region_swap", "filler"]
    if count > 1:
        names.extend(["count_minus", "dropped_tip"])
    if NOUN.search(entry.task_name):
        names.append("noun_drift")
    credential = entry.brief.expert.credential
    if (
        entry.task_name.lower().startswith(credential.lower())
        and credential.lower() != "expert"
    ):
        names.append("generic_credential")
    if entry.brief.voice_tier == "clinical" or re.search(
        r"\b(?:clinical|medical)\b", credential, re.IGNORECASE
    ):
        names.append("clinical_colloquialism")
    if entry.piece_type == "simple_pitch_list":
        names.extend(["orphan_closers", "intro_lines", "mini_labels"])
        if any(COST.search(label) for label in entry.approved_labels):
            if any(
                COST.search(section.label)
                for item in items
                for section in item.sections
            ):
                names.append("cost_placeholder")
    elif entry.piece_type == "cpr":
        names.append("mini_labels")
    if qa:
        if count >= 5 and len(entry.brief.tips) >= 5:
            names.append("bundled_q5")
        if count >= 2:
            names.append("mixed_quotes")
    return sorted(names)


def apply_fault(entry: Entry, name: str, rng: random.Random) -> Entry:
    """Return a modified copy; never attach hidden labels to the public entry."""
    if name not in RECIPES:
        raise ValueError(f"Unknown fault recipe: {name}")
    if name not in available_recipes(entry):
        raise ValueError(f"Fault recipe {name} does not apply to this entry")
    changed = entry.model_copy(deep=True)
    if name in {"count_plus", "count_minus", "dropped_tip"}:
        if changed.piece_type == "qa":
            questions, answers = list(changed.questions), list(changed.answers)
            if name == "count_plus":
                questions.append(questions[-1])
                answers.append(answers[-1])
            elif name == "count_minus":
                questions.pop()
                answers.pop()
            else:
                questions[-1], answers[-1] = questions[0], answers[0]
            return _with_qa(changed, questions, answers)
        preamble, parts = _list_parts(changed)
        if name == "count_plus":
            parts.append(parts[-1])
        elif name == "count_minus":
            parts.pop()
        else:
            parts[-1] = parts[0]
        return _with_items(changed, preamble, parts)
    if name == "noun_drift":
        match = NOUN.search(changed.task_name)
        assert match is not None
        replacement = "mistakes" if match.group().casefold() == "tips" else "tips"
        return changed.model_copy(
            update={"task_name": NOUN.sub(replacement, changed.task_name, count=1)}
        )
    if name == "generic_credential":
        return changed.model_copy(
            update={
                "task_name": "Expert"
                + changed.task_name[len(changed.brief.expert.credential) :]
            }
        )
    if name in {"orphan_closers", "intro_lines", "mini_labels", "cost_placeholder"}:
        preamble, parts = _list_parts(changed)
        if name == "orphan_closers":
            parts = [
                part + "\n\nA quiet moment brings the piece together." for part in parts
            ]
        elif name == "intro_lines":
            parts[0] = parts[0].replace(
                "\n", "\nA framing sentence introduces this item.\n", 1
            )
        elif name == "mini_labels":
            changed = _edit_prose(changed, lambda text: "Example: " + text)
            return changed
        else:
            for index, part in enumerate(parts):
                markers = list(LABEL.finditer(part))
                for position, marker in enumerate(markers):
                    if COST.search(marker.group("label")):
                        stop = (
                            markers[position + 1].start()
                            if position + 1 < len(markers)
                            else len(part)
                        )
                        parts[index] = (
                            part[: marker.end()] + " Not provided.\n" + part[stop:]
                        )
                        return _with_items(changed, preamble, parts)
        return _with_items(changed, preamble, parts)
    if name == "bundled_q5":
        questions = list(changed.questions)
        questions[4] = (
            f"What about {changed.brief.tips[3].rstrip('.?')} "
            f"and {changed.brief.tips[4].rstrip('.?')}?"
        )
        return _with_qa(changed, questions, list(changed.answers))
    if name == "mixed_quotes":
        answers = list(changed.answers)
        index = rng.randrange(len(answers))
        text, opening, _ = _unwrap(answers[index])
        answers[index] = text if opening else f'"{text}"'
        return _with_qa(changed, list(changed.questions), answers)
    if name == "em_dash":
        return _edit_prose(changed, lambda text: "A pause—then rest. " + text)
    if name == "region_swap":
        token = "color" if changed.region == "UK" else "colour"
        return _edit_prose(changed, lambda text: f"A {token} detail matters. " + text)
    if name == "filler":
        return _edit_prose(changed, lambda text: "It's worth noting that " + text)
    if name == "clinical_colloquialism":
        return _edit_prose(
            changed, lambda text: "The readings look scary in go-mode. " + text
        )
    raise AssertionError(f"Unimplemented recipe: {name}")
