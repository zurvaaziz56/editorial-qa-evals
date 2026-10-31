"""Validated local brief data and diversity-preserving seeded sampling."""

import random
import re
from collections import Counter
from pathlib import Path
from string import Formatter
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from editorial_qa_evals.generation_errors import GenerationError
from editorial_qa_evals.models import Entry

ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = ("mistakes", "red flags", "signs", "tips", "wastes of money", "habits")
BANNED = re.compile(r"\b(?:fictional|invented|simulation)\b", re.IGNORECASE)
CLINICAL_CREDENTIAL = re.compile(
    r"dentist|dental|prosthodontist|veterinar|sleep scientist|physician|"
    r"clinical|medical|therapist",
    re.IGNORECASE,
)
CLINICAL_DOMAINS = {"sleep_health", "dental", "pets"}
VOICE_TONES = {
    "clinical": "Clinical and precise",
    "accessible_precise": "Accessible and precise",
    "lifestyle": "Warm and practical",
}


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credential(CatalogModel):
    name: str = Field(min_length=1)
    voice_tier: Literal["clinical", "accessible_precise", "lifestyle"]


class Domain(CatalogModel):
    name: str
    subject: str
    clinical_topics: bool
    stat_organisation: str
    credentials: list[Credential] = Field(min_length=3)
    hooks: list[str] = Field(min_length=3)
    tips: dict[str, list[str]]


class Catalog(CatalogModel):
    version: Literal[1]
    count_values: list[int]
    count_weights: list[float]
    headline_templates: dict[str, str]
    domains: dict[str, Domain]


def load_catalog(path: Path = ROOT / "rules/brief_catalog.yaml") -> Catalog:
    """Reject malformed or unsafe catalogs before requesting any model output."""
    try:
        catalog = Catalog.model_validate(yaml.safe_load(path.read_text()))
    except (ValidationError, yaml.YAMLError) as error:
        raise GenerationError("Invalid brief catalog structure") from error
    if catalog.count_values != [3, 5, 7] or catalog.count_weights != [0.25, 0.5, 0.25]:
        raise GenerationError("Catalog counts must be 3/5/7 with weights .25/.5/.25")
    if len(catalog.domains) < 12 or len(catalog.headline_templates) < 6:
        raise GenerationError("Catalog needs at least twelve domains and six templates")
    credentials: set[str] = set()
    tips: set[str] = set()
    for key, domain in catalog.domains.items():
        if domain.clinical_topics != (key in CLINICAL_DOMAINS):
            raise GenerationError(
                "Clinical topics must be sleep/health, dental or pets"
            )
        if set(domain.tips) != set(CATEGORIES):
            raise GenerationError("Every domain must cover all six noun categories")
        for credential in domain.credentials:
            name = credential.name.casefold()
            if name == "expert" or name in credentials:
                raise GenerationError("Catalog credentials must be specific and unique")
            credentials.add(name)
            if (
                credential.voice_tier == "clinical" or CLINICAL_CREDENTIAL.search(name)
            ) and not domain.clinical_topics:
                raise GenerationError("Clinical credential outside a clinical topic")
        for candidates in domain.tips.values():
            if len(candidates) < 8:
                raise GenerationError("Each noun category needs at least eight tips")
            for tip in candidates:
                if not tip.strip() or tip.casefold() in tips:
                    raise GenerationError(
                        "Catalog tips must be nonempty and globally unique"
                    )
                tips.add(tip.casefold())
        strings = [
            domain.subject,
            domain.stat_organisation,
            *[c.name for c in domain.credentials],
            *domain.hooks,
            *[t for ts in domain.tips.values() for t in ts],
        ]
        if any(BANNED.search(text) for text in strings):
            raise GenerationError("Banned meta-language in catalog content")
    allowed = {
        "credential",
        "credential_lower",
        "count",
        "category",
        "subject",
        "article",
        "article_cap",
    }
    for template in catalog.headline_templates.values():
        try:
            fields = {field for _, field, _, _ in Formatter().parse(template) if field}
            rendered = template.format(
                credential="Dentist",
                credential_lower="dentist",
                count=5,
                category="habits",
                subject="oral care",
                article="a",
                article_cap="A",
            )
        except (KeyError, ValueError) as error:
            raise GenerationError("Invalid headline template") from error
        if (
            not fields <= allowed
            or not {"count", "category"} <= fields
            or not fields & {"credential", "credential_lower"}
            or BANNED.search(rendered)
        ):
            raise GenerationError(
                "Headline templates need count, category and credential"
            )
    return catalog


def draw_count(catalog: Catalog, rng: random.Random) -> int:
    return rng.choices(catalog.count_values, weights=catalog.count_weights, k=1)[0]


def headline(
    catalog: Catalog,
    template: str,
    domain: Domain,
    credential: Credential,
    count: int,
    category: str,
) -> str:
    return catalog.headline_templates[template].format(
        credential=credential.name,
        credential_lower=credential.name.lower(),
        count=count,
        category=category,
        subject=domain.subject,
        article="an" if credential.name[0].lower() in "aeiou" else "a",
        article_cap="An" if credential.name[0].lower() in "aeiou" else "A",
    )


def sample_briefs(
    n: int, rng: random.Random, catalog: Catalog
) -> list[dict[str, object]]:
    """Balance domains, credentials and templates; consume each catalog tip once.

    A finite catalog cannot satisfy arbitrary n with unique tips. Reject capacity
    exhaustion before API calls instead of weakening the uniqueness guarantee.
    """
    keys = list(catalog.domains)
    templates = list(catalog.headline_templates)
    rng.shuffle(keys)
    rng.shuffle(templates)
    credential_counts: Counter[str] = Counter()
    available = {
        (key, category): list(domain.tips[category])
        for key, domain in catalog.domains.items()
        for category in CATEGORIES
    }
    for pool in available.values():
        rng.shuffle(pool)
    result = []
    for index in range(n):
        key = keys[index % len(keys)]
        domain = catalog.domains[key]
        count = draw_count(catalog, rng)
        categories = [c for c in CATEGORIES if len(available[key, c]) >= count]
        if not categories:
            raise GenerationError(
                "Brief catalog capacity exhausted: "
                "reduce n or add unique tip candidates"
            )
        category = rng.choice(categories)
        pool = available[key, category]
        tips = pool[:count]
        del pool[:count]
        least = min(credential_counts[c.name] for c in domain.credentials)
        credential = rng.choice(
            [c for c in domain.credentials if credential_counts[c.name] == least]
        )
        credential_counts[credential.name] += 1
        template = templates[index % len(templates)]
        result.append(
            {
                "domain": key,
                "noun_category": category,
                "headline_template": template,
                "voice_tier": credential.voice_tier,
                "tips": tips,
                "hook": rng.choice(domain.hooks),
                "tone": VOICE_TONES[credential.voice_tier],
                "expert": {"credential": credential.name, "specialism": domain.subject},
                "task_name": headline(
                    catalog, template, domain, credential, count, category
                ),
            }
        )
    return result


def check_diversity(entries: list[Entry]) -> list[str]:
    """Check actual survivors, never the requested size or a rounded percentage."""
    n = len(entries)
    issues = []
    for name, cap, values in (
        ("domain", 0.15, [e.brief.domain for e in entries]),
        ("credential", 0.10, [e.brief.expert.credential for e in entries]),
        ("headline_template", 0.25, [e.brief.headline_template for e in entries]),
    ):
        counts = Counter(values)
        if None in counts or any(count > n * cap + 1e-9 for count in counts.values()):
            issues.append(f"{name} exceeds {cap:.0%} or has missing metadata")
    tips = [tip.casefold() for e in entries for tip in e.brief.tips]
    if len(tips) != len(set(tips)):
        issues.append("Exact brief tip reused across entries")
    return issues
