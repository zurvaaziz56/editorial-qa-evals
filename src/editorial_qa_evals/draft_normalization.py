"""Narrow, auditable repairs for clean model drafts before final validation."""

import copy
import re
import unicodedata
from typing import Any

WORD_HYPHEN = re.compile(r"(?<=[^\W_])[\u2010\u2011](?=[^\W_])")


def _sentence_case(title: str, proper_nouns: list[str]) -> str:
    result = title.lower()
    for index, character in enumerate(result):
        if character.isalpha():
            result = result[:index] + character.upper() + result[index + 1 :]
            break
    canonical = {}
    for name in proper_nouns:
        if name:
            canonical.setdefault(name.casefold(), name)
    names = sorted(canonical.values(), key=lambda name: (-len(name), name.casefold()))
    if names:
        # One substitution avoids shorter entries changing an already restored
        # multiword name. Word boundaries prevent restoring partial-word matches.
        pattern = re.compile(
            r"(?<!\w)(?:" + "|".join(re.escape(name) for name in names) + r")(?!\w)",
            re.IGNORECASE,
        )

        def restore(match: re.Match[str]) -> str:
            return next(
                name
                for name in names
                if re.fullmatch(re.escape(name), match.group(), re.IGNORECASE)
            )

        result = pattern.sub(restore, result)
    return result


def _strip_title_punctuation(title: str) -> str:
    while title and unicodedata.category(title[-1]).startswith("P"):
        title = title[:-1]
    return title


def normalize_clean_draft(
    value: dict[str, Any], proper_nouns: list[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a copy plus changes; never repair structure or edit injected entries.

    Only item titles, questions and prose paragraph strings are considered. An
    invalid shape is preserved so the schema validator can reject it. The caller
    must invoke this only before clean validation and before fault injection.
    """
    normalized = copy.deepcopy(value)
    changes: list[dict[str, Any]] = []

    def transform(text: str, path: str, title: bool = False) -> str:
        operations = [("word_hyphen", lambda source: WORD_HYPHEN.sub("-", source))]
        if title:
            operations.extend(
                [
                    ("title_punctuation", _strip_title_punctuation),
                    (
                        "sentence_case",
                        lambda source: _sentence_case(source, proper_nouns),
                    ),
                ]
            )
        for operation, action in operations:
            after = action(text)
            if after != text:
                changes.append(
                    {
                        "path": path,
                        "operation": operation,
                        "before": text,
                        "after": after,
                    }
                )
                text = after
        return text

    items = normalized.get("items")
    if not isinstance(items, list):
        return normalized, changes
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        for field in ("title", "question"):
            if isinstance(item.get(field), str):
                item[field] = transform(
                    item[field], f"items.{index}.{field}", title=field == "title"
                )
        paragraphs = item.get("paragraphs")
        if isinstance(paragraphs, list):
            item["paragraphs"] = [
                transform(text, f"items.{index}.paragraphs.{position}")
                if isinstance(text, str)
                else text
                for position, text in enumerate(paragraphs)
            ]
    return normalized, changes
