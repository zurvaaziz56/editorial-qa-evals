"""Offline distributions and content vocabulary for a public generated dataset."""

import json
import re
from collections import Counter
from pathlib import Path

import typer

from editorial_qa_evals.brief_catalog import check_diversity
from editorial_qa_evals.models import Entry

# Fixed stop list: reproducible and network-free. Source attribution and formatting
# tokens are excluded so the vocabulary list reflects draft content more closely.
STOP_WORDS = set(
    """
a an the and or but if so to of in on at by for from with without as is are was were
be been being this that these those it its they their them each every all any can
could may might will would should do does did not no only more most less than then
when where while which who how what why into about after before during through
between over under also such some your you our we has have had helps help using
use used make makes one two three first second uk us top tip survey respondents
reported tier according https source invalid com www q a
""".split()
)


def diversity_report(entries: list[Entry]) -> str:
    n = len(entries)
    lines = ["## Synthetic entry diversity", "", f"Entries: {n}", ""]
    for title, counts in (
        ("Domains", Counter(e.brief.domain or "missing" for e in entries)),
        ("Credentials", Counter(e.brief.expert.credential for e in entries)),
        (
            "Headline templates",
            Counter(e.brief.headline_template or "missing" for e in entries),
        ),
        ("Counts", Counter(str(len(e.brief.tips)) for e in entries)),
    ):
        lines.extend(
            [f"### {title}", "", "| Value | Entries | Share |", "| --- | ---: | ---: |"]
        )
        for value, count in sorted(counts.items()):
            lines.append(f"| {value} | {count} | {count / n:.1%} |")
        lines.append("")
    words: Counter[str] = Counter()
    for entry in entries:
        text = entry.task_name + " " + entry.body
        text = re.sub(r"https?://\S+", "", text)
        # Locally made-up source names should not dominate content-word counts.
        text = re.sub(r"In a \d+ survey by [^,]+,", "", text)
        words.update(
            word
            for word in re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
            if len(word) > 2 and word not in STOP_WORDS
        )
    lines.extend(
        ["### Top 25 content words", "", "| Word | Occurrences |", "| --- | ---: |"]
    )
    for word, count in sorted(words.items(), key=lambda pair: (-pair[1], pair[0]))[:25]:
        lines.append(f"| {word} | {count} |")
    issues = check_diversity(entries)
    lines.extend(
        ["", "Diversity checks: " + ("; ".join(issues) if issues else "PASS"), ""]
    )
    return "\n".join(lines)


app = typer.Typer(add_completion=False)


@app.command()
def main(entries: Path) -> None:
    """Print Markdown for the public JSONL; do not read hidden fault assignments."""
    try:
        rows = [
            Entry.model_validate(json.loads(line))
            for line in entries.read_text().splitlines()
            if line.strip()
        ]
    except (OSError, ValueError) as error:
        raise typer.BadParameter("Cannot read valid entry JSONL") from error
    if not rows:
        raise typer.BadParameter("Dataset must contain at least one entry")
    typer.echo(diversity_report(rows))
    if check_diversity(rows):
        raise typer.Exit(1)
