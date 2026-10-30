# Deterministic checks and parser conventions

The rubric remains the source of truth. This layer performs structural and
lexical checks without model calls. It does not derive routing or verdicts.

## Entry points and output

`parse_body(entry)` exposes numbered items, labels, intro lines, detached trailing
paragraphs and Q&A pairs. `run_checks(entry, rules)` returns ten `CheckResult`
models. Each serializes to `check_id`, `result`, `severity` and `evidence`.
Evidence includes the literal `span`, `item_number`, `detail` and `location`.
Numbers match body numbering, or structured Q&A array positions starting at 1;
`null` denotes global/body-preamble, headline or brief evidence. The CLI quotes
spans explicitly. A passed or inapplicable check has null severity and no evidence.

Individual check functions take parsed input and rule data without I/O. The
runner loads repository YAML rules by default; callers can inject rule data.
Run from the repository checkout: rule files live in `rules/`, and the package
is installed in editable mode by the documented setup.

## Structural conventions

- Item titles occupy their own lines, prefixed by `1.` or `1)`. Bold title
  wrapping is supported. Item numbers and raw text offsets are retained.
- A subsection header is `**Label:** prose` or `**Label**: prose`. Label wording
  and capitalization are preserved for exact compliance checks.
- Nonempty lines between the title and first header are intro lines. Text
  preceding the first numbered item is a global intro candidate.
- Wrapped lines remain in a subsection. After the final header, the first
  blank-line-separated paragraph ends that subsection; later detached paragraphs
  are exposed as orphan candidates. A legitimate second paragraph can therefore
  be flagged. A closer without a separating blank line cannot be distinguished
  from continuation prose by structure alone. These cases need reviewer judgment.
- Q&A uses nonempty `questions`/`answers` arrays when supplied, paired by index.
  Otherwise, body parsing accepts `Q:`, `Q1:`, `Question 1:` and numbered question
  lines ending in `?`, followed by `A:`, `A1:`, `Answer 1:` or unprefixed answers.
  Explicit question numbers are preserved. Extra/missing answers and mismatched
  answer numbers remain visible as incomplete pairs. Straight and curly single
  and double wrapping quotes are recognized; broken wrapping is reported.

## Applicability and severity

| Check | Applies to | Failure severity / convention |
|---|---|---|
| C1 | Simple pitch list | `HARD_BLOCKER` for missing exact approved bold labels or absent numbered items. Approved labels must come from the labels sheet; this check does not invent them. |
| C2 | Simple pitch list and CPR | `FLAG` for one affected item, `STRUCTURAL` across two or more items. Checks bold text and short line/sentence-leading colon headers, plus seeded offenders. Titles and exact approved headers are exempt; CPR permits Top tip. |
| C3 | Any piece with a cost, penalty or savings label | `HARD_BLOCKER` for seeded placeholders anywhere in the piece. Matching is case-insensitive. |
| C6 | Q&A | `FORMAT` for mixed quoted/unquoted answers, broken wrapping, missing pairs or no recognizable Q&A. Restating Q1 is never a failure. |
| C8 | All | `MECHANICAL` for the rubric's three Unicode dash characters, spaced hyphens and non-Latin alphabetic runs. Accented Latin letters and combining marks are permitted. |
| C9 | All | `FORMAT` for one or two distinct foreign-region vocabulary families; `MAJOR` for three or more. Repeated occurrences of one family remain minor. |
| C11 | Any piece with a count promise | `MAJOR_MISMATCH` when the actual count differs from any recognized headline count or nonempty brief tip count. Count numbered items, or questions for Q&A; extra answers are handled by C6. |
| C12 | Simple pitch list | `FLAG` for intro/orphan candidates affecting at most one item, `MAJOR` across two or more items. Global text is reported but does not count as an extra item. |
| J2 | Numbered lists outside Q&A | `FORMAT` for non-sentence-case, long, sentence-like or imperative titles. Uses a case-sensitive proper-noun allowlist. Unnumbered CPR is `na`. |
| J4 | All | `FORMAT` for exact seeded filler phrases, ignoring case and enforcing word boundaries. |

C9's three-family threshold is an operational heuristic, not a numeric rule in
the rubric. Currency aliases (`GBP`/`£` and `$`/`USD`) share one family, and symbols
adjacent to digits are recognized. Institutions and common-word lexicons can be contextually
ambiguous. Inspect evidence before accepting a major-region judgment. No
semantic disambiguation or additional routing rule is implemented here.

C11 recognizes digits and number words one through twenty before common item
nouns, allowing up to three intervening words, and leading headline numerals for
other categories. Age/duration patterns followed by years, months or days, and
percent patterns, are excluded. Brief promises use the number of brief tips;
conflicting headline/brief promises are checked independently. An absent count
promise gives `na`. The prescribed correction remains merge/replace, never add.

J2 masks exact allowlisted proper nouns, then checks capitalization after the
first word, lowercase title starts, common sentence verbs, terminal sentence
punctuation, common imperatives and a 12-word limit. It is a lexical heuristic,
not proof of noun-phrase grammar. Edit `rules/proper_nouns.yaml` intentionally
when the approved vocabulary changes.

C8/C9/J4 scan the body plus structured Q&A text absent from the body. C3 uses the
same scope when applicable. Editorial comparisons against the brief, nuanced
voice judgments, inferred orphan meanings, regulatory judgments and noun-category
semantics remain outside this task. In particular, deterministic J4 only checks
its phrase list; it does not claim to detect every voice issue in the rubric.

## Validation

`tests/fixtures/deterministic.json` contains fictional clean entries for each
piece type, a clean cost-label entry, and separate fault bodies. Tests check the
exact failed-check set, severity and quoted evidence/item numbers, as well as
`na` behavior, boundaries, rule injection, Q&A pairing and CLI exit codes.
`tests/fixtures/clean_entry.json` is a standalone CLI smoke fixture, not a golden
or human-labeled dataset. All validation runs offline after dependency setup.
