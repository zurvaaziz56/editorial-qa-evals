"""Structural parsing only; detached paragraphs are orphan candidates, not judgments."""

import re
from dataclasses import dataclass
from itertools import zip_longest
from typing import Literal

from editorial_qa_evals.models import Entry

ITEM = re.compile(r"^[ \t]*(?:\*\*)?(\d+)[.)][ \t]+(.+)$", re.MULTILINE)
LABEL = re.compile(r"\*\*(?P<label>[^*\n:]+?)(?::\*\*|\*\*[ \t]*:)")
QUESTION = re.compile(
    r"^[ \t]*(?:Q(?:uestion)?[ \t]*(?P<qnumber>\d*)[.:)][ \t]*(?P<qtext>.+)|"
    r"(?P<number>\d+)[.)][ \t]+(?P<text>.+\?))[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)
ANSWER = re.compile(
    r"^[ \t]*A(?:nswer)?[ \t]*(?P<number>\d*)[.:)][ \t]*", re.MULTILINE | re.IGNORECASE
)
QUOTE_PAIRS = {'"': '"', "'": "'", "“": "”", "‘": "’"}


@dataclass(frozen=True)
class Section:
    label: str
    text: str


@dataclass(frozen=True)
class Item:
    number: int
    title: str
    text: str
    start: int
    end: int
    sections: tuple[Section, ...]
    intro: tuple[str, ...]
    orphans: tuple[str, ...]


@dataclass(frozen=True)
class QAPair:
    number: int
    question: str | None
    answer: str | None
    quotation: Literal["quoted", "unquoted", "partial"]


@dataclass(frozen=True)
class ParsedBody:
    items: tuple[Item, ...]
    preamble: str
    qa_pairs: tuple[QAPair, ...]


def quote_state(answer: str) -> Literal["quoted", "unquoted", "partial"]:
    """Recognize straight/curly single or double wrapping, including broken pairs."""
    text = answer.strip()
    if len(text) >= 2 and text[0] in QUOTE_PAIRS:
        return "quoted" if text[-1] == QUOTE_PAIRS[text[0]] else "partial"
    if text and (text[0] in QUOTE_PAIRS or text[-1] in QUOTE_PAIRS.values()):
        return "partial"
    return "unquoted"


def _lines(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in text.splitlines() if line.strip())


def parse_items(body: str) -> tuple[Item, ...]:
    matches = list(ITEM.finditer(body))
    items = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content = body[match.end() : end]
        labels = list(LABEL.finditer(content))
        intro = _lines(content[: labels[0].start()] if labels else content)
        sections = []
        orphans: tuple[str, ...] = ()
        for position, label in enumerate(labels):
            stop = labels[position + 1].start() if position + 1 < len(labels) else None
            text = content[label.end() : stop].strip()
            if position == len(labels) - 1:
                # Wrapped lines belong to the section. A detached paragraph after
                # the final section is structurally ambiguous: expose it for C12.
                paragraphs = re.split(r"\r?\n[ \t]*\r?\n", text, maxsplit=1)
                text = paragraphs[0]
                if len(paragraphs) == 2:
                    orphans = _lines(paragraphs[1])
            sections.append(Section(label.group("label"), text))
        items.append(
            Item(
                int(match.group(1)),
                match.group(2).strip().removesuffix("**").removeprefix("**"),
                body[match.start() : end],
                match.start(),
                end,
                tuple(sections),
                intro,
                orphans,
            )
        )
    return tuple(items)


def question_number(match: re.Match[str], ordinal: int) -> int:
    return int(match.group("qnumber") or match.group("number") or ordinal)


def _answer_segments(text: str) -> list[tuple[int | None, str]]:
    markers = list(ANSWER.finditer(text))
    if not markers:
        return [(None, text.strip())] if text.strip() else []
    segments = []
    if text[: markers[0].start()].strip():
        segments.append((None, text[: markers[0].start()].strip()))
    for index, marker in enumerate(markers):
        stop = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        number = int(marker.group("number")) if marker.group("number") else None
        segments.append((number, text[marker.end() : stop].strip()))
    return segments


def parse_qa(
    body: str, questions: list[str] | None = None, answers: list[str] | None = None
) -> tuple[QAPair, ...]:
    """Prefer structured fields; retain missing/extra answers and explicit Q numbers."""
    if questions or answers:
        return tuple(
            QAPair(number, question, answer, quote_state(answer or ""))
            for number, (question, answer) in enumerate(
                zip_longest(questions or [], answers or []), 1
            )
        )
    matches = list(QUESTION.finditer(body))
    pairs = []
    preamble = body[: matches[0].start()] if matches else body
    if ANSWER.search(preamble):
        for number, answer in _answer_segments(preamble):
            pairs.append(QAPair(number or 1, None, answer or None, quote_state(answer)))
    for index, match in enumerate(matches):
        number = question_number(match, index + 1)
        question = match.group("qtext") or match.group("text")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        segments = _answer_segments(body[match.end() : end])
        answer = None
        if segments and segments[0][0] in (None, number):
            answer = segments.pop(0)[1] or None
        pairs.append(QAPair(number, question, answer, quote_state(answer or "")))
        for extra_number, extra_answer in segments:
            pairs.append(
                QAPair(
                    extra_number or number,
                    None,
                    extra_answer or None,
                    quote_state(extra_answer),
                )
            )
    return tuple(pairs)


def parse_body(entry: Entry) -> ParsedBody:
    items = parse_items(entry.body)
    preamble = entry.body[: items[0].start].strip() if items else entry.body.strip()
    pairs = (
        parse_qa(entry.body, entry.questions, entry.answers)
        if entry.piece_type == "qa"
        else ()
    )
    return ParsedBody(items, preamble, pairs)
