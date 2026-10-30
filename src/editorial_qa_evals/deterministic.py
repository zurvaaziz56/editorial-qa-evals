"""Pure editorial checks. See docs/DETERMINISTIC.md for heuristic boundaries."""

import re
import unicodedata
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

import yaml
from pydantic import BaseModel, Field

from editorial_qa_evals.models import Entry
from editorial_qa_evals.parser import (
    LABEL,
    QUESTION,
    ParsedBody,
    parse_body,
    question_number,
)

Severity = Literal[
    "HARD_BLOCKER",
    "STRUCTURAL",
    "FLAG",
    "FORMAT",
    "MECHANICAL",
    "MAJOR_MISMATCH",
    "MAJOR",
]


class Evidence(BaseModel):
    span: str
    item_number: int | None
    detail: str
    location: str = "body"


class CheckResult(BaseModel):
    check_id: str
    result: Literal["pass", "fail", "na"]
    severity: Severity | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class RegionSwap(TypedDict):
    uk: str
    us: str
    uk_aliases: NotRequired[list[str]]
    us_aliases: NotRequired[list[str]]


class Rules(TypedDict):
    swaps: list[RegionSwap]
    phrases: list[str]
    offenders: list[str]
    proper_nouns: list[str]


def load_rules(directory: Path | None = None) -> Rules:
    """Load repository rule data once at the application boundary, never in checks."""
    root = (
        directory
        if directory is not None
        else Path(__file__).resolve().parents[2] / "rules"
    )
    return {
        "swaps": yaml.safe_load((root / "region_swaps.yaml").read_text())["swaps"],
        "phrases": yaml.safe_load((root / "filler_phrases.yaml").read_text())[
            "phrases"
        ],
        "offenders": yaml.safe_load((root / "mini_label_offenders.yaml").read_text())[
            "offenders"
        ],
        "proper_nouns": yaml.safe_load((root / "proper_nouns.yaml").read_text())[
            "proper_nouns"
        ],
    }


def _result(
    check_id: str,
    evidence: list[Evidence],
    severity: Severity,
    applicable: bool = True,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        result=("fail" if evidence else "pass") if applicable else "na",
        severity=severity if evidence and applicable else None,
        evidence=evidence if applicable else [],
    )


def _evidence(
    span: str, number: int | None, detail: str, location: str = "body"
) -> Evidence:
    return Evidence(span=span, item_number=number, detail=detail, location=location)


def _texts(entry: Entry, parsed: ParsedBody) -> list[tuple[str, int | None, str]]:
    """Scan body once, plus structured Q&A text that is absent from the body."""
    chunks = []
    cursor = 0
    if entry.piece_type == "qa":
        markers = list(QUESTION.finditer(entry.body))
        regions = [
            (
                match.start(),
                markers[index + 1].start()
                if index + 1 < len(markers)
                else len(entry.body),
                question_number(match, index + 1),
            )
            for index, match in enumerate(markers)
        ]
    else:
        regions = [(item.start, item.end, item.number) for item in parsed.items]
    for start, end, number in regions:
        if start > cursor:
            chunks.append((entry.body[cursor:start], None, "body"))
        chunks.append((entry.body[start:end], number, "body"))
        cursor = end
    if cursor < len(entry.body):
        chunks.append((entry.body[cursor:], None, "body"))
    if entry.piece_type == "qa":
        for pair in parsed.qa_pairs:
            for name, text in (("question", pair.question), ("answer", pair.answer)):
                if text and text not in entry.body:
                    chunks.append((text, pair.number, name))
    return chunks


def check_c1(entry: Entry, parsed: ParsedBody) -> CheckResult:
    evidence = []
    if not parsed.items:
        evidence.append(_evidence(entry.body, None, "No numbered items found"))
    for item in parsed.items:
        labels = {section.label for section in item.sections}
        for expected in entry.approved_labels:
            if expected not in labels:
                evidence.append(
                    _evidence(
                        item.text,
                        item.number,
                        f"Missing exact bold label: {expected!r}",
                    )
                )
    return _result(
        "C1", evidence, "HARD_BLOCKER", entry.piece_type == "simple_pitch_list"
    )


def check_c2(entry: Entry, parsed: ParsedBody, offenders: list[str]) -> CheckResult:
    evidence = []
    # Bold text and short sentence/line-leading colon headers are candidates.
    candidate = re.compile(
        r"\*\*[^*\n]+\*\*:?"
        + r"|(?:^|(?<=[.!?:])\s+|(?<=\*\*)[ \t]+)([A-Za-z][A-Za-z '’/-]{0,59}):",
        re.MULTILINE,
    )
    known = (
        re.compile(
            r"(?<!\w)(?:" + "|".join(re.escape(x) for x in offenders) + r")",
            re.IGNORECASE,
        )
        if offenders
        else None
    )
    regions: list[tuple[str, int | None]] = []
    for item in parsed.items:
        # Skip the title line; bold titles are not mini-labels.
        regions.append(
            (item.text.split("\n", 1)[1] if "\n" in item.text else "", item.number)
        )
    if not parsed.items or parsed.preamble:
        regions.append((parsed.preamble, None))
    for text, number in regions:
        spans = [(match.start(), match.end()) for match in candidate.finditer(text)]
        if known:
            spans.extend((match.start(), match.end()) for match in known.finditer(text))
        accepted = [
            (m.start(), m.end(), m.group("label")) for m in LABEL.finditer(text)
        ]
        seen = set()
        for start, end in sorted(spans):
            token = text[start:end].strip()
            label = token.replace("**", "").rstrip(":").strip()
            enclosing = next(
                ((a, name) for a, b, name in accepted if a <= start and end <= b), None
            )
            enclosing_label = enclosing[1] if enclosing else None
            token_start = (
                enclosing[0]
                if enclosing
                else start + len(text[start:end]) - len(text[start:end].lstrip())
            )
            if (
                enclosing_label in entry.approved_labels
                or label in entry.approved_labels
            ):
                continue
            if entry.piece_type == "cpr" and label.casefold() == "top tip":
                continue
            if (token_start, label) in seen:
                continue
            seen.add((token_start, label))
            evidence.append(
                _evidence(token, number, "Unauthorised mini-label or bold text")
            )
    affected = {e.item_number for e in evidence if e.item_number is not None}
    return _result(
        "C2",
        evidence,
        "STRUCTURAL" if len(affected) > 1 else "FLAG",
        entry.piece_type in {"simple_pitch_list", "cpr"},
    )


def check_c3(entry: Entry, parsed: ParsedBody) -> CheckResult:
    applicable = any(
        re.search(r"\b(cost|penalty|savings)\b", label, re.IGNORECASE)
        for label in entry.approved_labels
    )
    pattern = re.compile(
        r"\b(?:Not provided|TBD|To be confirmed|N/A|Varies)\b"
        r"|\bCheck with\b[^\n]*|\[figure to be added\]",
        re.IGNORECASE,
    )
    evidence = [
        _evidence(m.group(), number, "Placeholder under a cost-type label", location)
        for text, number, location in _texts(entry, parsed)
        for m in pattern.finditer(text)
    ]
    return _result("C3", evidence, "HARD_BLOCKER", applicable)


def check_c6(entry: Entry, parsed: ParsedBody) -> CheckResult:
    evidence = []
    complete = [pair for pair in parsed.qa_pairs if pair.question and pair.answer]
    states = {pair.quotation for pair in complete}
    if not parsed.qa_pairs:
        evidence.append(_evidence(entry.body, None, "No question/answer pairs found"))
    for pair in parsed.qa_pairs:
        if not pair.question or not pair.answer:
            evidence.append(
                _evidence(
                    pair.answer or pair.question or "",
                    pair.number,
                    "Unpaired question or answer",
                )
            )
        elif pair.quotation == "partial" or len(states) > 1:
            evidence.append(
                _evidence(
                    pair.answer,
                    pair.number,
                    "Inconsistent or incomplete quotation wrapping",
                    "answer",
                )
            )
    return _result("C6", evidence, "FORMAT", entry.piece_type == "qa")


def check_c8(entry: Entry, parsed: ParsedBody) -> CheckResult:
    evidence = []
    for text, number, location in _texts(entry, parsed):
        for match in re.finditer("[\u2014\u2013\u2011]| - ", text):
            evidence.append(
                _evidence(match.group(), number, "Disallowed dash", location)
            )
        # Latin accents and combining marks are valid; reject other alphabetic scripts.
        for match in re.finditer(r"[^\W\d_]+", text):
            bad = "".join(
                char
                for char in match.group()
                if char.isalpha() and "LATIN" not in unicodedata.name(char, "")
            )
            if bad:
                evidence.append(
                    _evidence(
                        match.group(), number, "Non-Latin paste artefact", location
                    )
                )
    return _result("C8", evidence, "MECHANICAL")


def check_c9(entry: Entry, parsed: ParsedBody, swaps: list[RegionSwap]) -> CheckResult:
    target = "uk" if entry.region == "UK" else "us"
    other = "us" if target == "uk" else "uk"
    evidence = []
    families = set()
    for index, swap in enumerate(swaps):
        token = swap[other]
        aliases = (
            swap.get("uk_aliases", []) if other == "uk" else swap.get("us_aliases", [])
        )
        variants = [token, *aliases]
        pattern = "|".join(
            r"(?<!\w)"
            + re.escape(variant)
            + (r"(?!\w)" if variant not in {"$", "£"} else "")
            for variant in variants
        )
        for text, number, location in _texts(entry, parsed):
            for match in re.finditer(pattern, text, re.IGNORECASE):
                families.add(index)
                evidence.append(
                    _evidence(
                        match.group(),
                        number,
                        f"Expected {entry.region} variant {swap[target]!r}",
                        location,
                    )
                )
    # Operational heuristic only: three distinct foreign families indicate broad drift.
    return _result("C9", evidence, "MAJOR" if len(families) >= 3 else "FORMAT")


NUMBER_WORDS = dict(
    zip(
        "one two three four five six seven eight nine ten eleven twelve "
        "thirteen fourteen fifteen "
        "sixteen seventeen eighteen nineteen twenty".split(),
        range(1, 21),
        strict=True,
    )
)
COUNT_NOUN = (
    r"(?:signs?|tips?|mistakes?|red flags?|habits?|ways?|steps?|"
    r"reasons?|items?|questions?)"
)
COUNT = re.compile(
    r"\b(\d+|" + "|".join(NUMBER_WORDS) + r")\s+"
    r"(?:(?!years?\b|percent\b|days?\b|months?\b)[\w'-]+\s+){0,3}?"
    + COUNT_NOUN
    + r"\b",
    re.IGNORECASE,
)


def check_c11(entry: Entry, parsed: ParsedBody) -> CheckResult:
    promises: list[tuple[int, str, str]] = []
    for match in COUNT.finditer(entry.task_name):
        token = match.group(1).lower()
        promises.append(
            (
                int(token) if token.isdigit() else NUMBER_WORDS[token],
                match.group(),
                "task_name",
            )
        )
    # Leading numerals also cover headline categories not in the count-noun vocabulary.
    leading = re.match(
        r"^\s*(\d+)\s+(?!years?\b|percent\b|days?\b|months?\b)", entry.task_name, re.I
    )
    if leading and not promises:
        promises.append((int(leading.group(1)), leading.group().strip(), "task_name"))
    if entry.brief.tips:
        promises.append(
            (len(entry.brief.tips), " | ".join(entry.brief.tips), "brief.tips")
        )
    actual = (
        sum(pair.question is not None for pair in parsed.qa_pairs)
        if entry.piece_type == "qa"
        else len(parsed.items)
    )
    evidence = [
        _evidence(
            span,
            None,
            f"Promised {expected} items; found {actual}. Merge/replace, never add.",
            location,
        )
        for expected, span, location in promises
        if expected != actual
    ]
    return _result("C11", evidence, "MAJOR_MISMATCH", bool(promises))


def check_c12(entry: Entry, parsed: ParsedBody) -> CheckResult:
    evidence = []
    if parsed.preamble:
        evidence.append(
            _evidence(parsed.preamble, None, "Unlabelled text before the first item")
        )
    for item in parsed.items:
        for line in item.intro:
            evidence.append(
                _evidence(line, item.number, "Unlabelled intro before the first label")
            )
        for line in item.orphans:
            evidence.append(
                _evidence(line, item.number, "Detached text after the final label")
            )
    affected = {e.item_number for e in evidence if e.item_number is not None}
    return _result(
        "C12",
        evidence,
        "MAJOR" if len(affected) > 1 else "FLAG",
        entry.piece_type == "simple_pitch_list",
    )


def check_j2(entry: Entry, parsed: ParsedBody, proper_nouns: list[str]) -> CheckResult:
    evidence = []
    for item in parsed.items:
        title = item.title
        masked = title
        for noun in sorted(proper_nouns, key=len, reverse=True):
            masked = re.sub(
                r"(?<!\w)" + re.escape(noun) + r"(?!\w)", "propernoun", masked
            )
        words = re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", masked)
        bad_case = any(word != word.lower() for word in words[1:])
        imperative = bool(
            re.match(
                r"^(?:Confirm|Verify|Check|Keep|Avoid|Use|Make|Try|Stop|Choose|Remember|Ensure)\b",
                title,
                re.I,
            )
        )
        sentence = bool(
            re.search(r"[.!?]$|\b(?:is|are|was|were|will|should|must)\b", title, re.I)
        )
        if (
            not words
            or title[:1].islower()
            or bad_case
            or imperative
            or sentence
            or len(words) > 12
        ):
            evidence.append(
                _evidence(
                    title, item.number, "Expected a short sentence-case noun phrase"
                )
            )
    return _result(
        "J2",
        evidence,
        "FORMAT",
        entry.piece_type != "qa" and bool(parsed.items),
    )


def check_j4(entry: Entry, parsed: ParsedBody, phrases: list[str]) -> CheckResult:
    evidence = [
        _evidence(match.group(), number, "Exact filler phrase", location)
        for text, number, location in _texts(entry, parsed)
        for phrase in phrases
        for match in re.finditer(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.I)
    ]
    return _result("J4", evidence, "FORMAT")


def run_checks(entry: Entry, rules: Rules | None = None) -> list[CheckResult]:
    """Evaluate all ten checks; supply rule data to keep the execution entirely pure."""
    rules = load_rules() if rules is None else rules
    parsed = parse_body(entry)
    return [
        check_c1(entry, parsed),
        check_c2(entry, parsed, rules["offenders"]),
        check_c3(entry, parsed),
        check_c6(entry, parsed),
        check_c8(entry, parsed),
        check_c9(entry, parsed, rules["swaps"]),
        check_c11(entry, parsed),
        check_c12(entry, parsed),
        check_j2(entry, parsed, rules["proper_nouns"]),
        check_j4(entry, parsed, rules["phrases"]),
    ]
