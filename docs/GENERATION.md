# Synthetic generation and fault reconciliation

This covers Task 3, representative briefs and Fix 3c reliability recovery. Generation produces
fictional entries and recipe metadata;
it does not produce human labels, judge predictions, agreement metrics or a
labeling UI. Existing tests use mocked completions and temporary outputs. No
live dataset or API call is needed for cloud validation.

## Run from the repository web UI

1. After merge, configure repository Actions secrets `JUDGE_BASE_URL`,
   `JUDGE_MODEL` and `JUDGE_API_KEY`. Keep the key in secrets, never a file.
   The base URL is the chat API root, normally including `/v1`; do not append
   `/chat/completions` yourself or put credentials in its query string.
2. Open Actions → Generate synthetic entries → Run workflow. Select `main`,
   `n=80`, `seed=7`, `max_rpm=20`, `max_tokens=2048`. The workflow only runs on `main`.
`n` must be at least 20
   because the smoke subset always contains 20 distinct entries.
3. Check validation totals in the job output. Required deterministic injections
   must all be detected; a missed target fails generation before publication.
4. Read the job summary's domain, credential, headline-template and count
   distributions and top-25 content words. The report reads only public entries;
   it exposes no fault assignments and blocks publication when a cap fails.
5. Review the public JSONL after success. Read ten sample bodies for realism,
   accidental real entities and any unsupported factual claims. Do not inspect
   the faults branch or raw clean responses during blind human labeling.

If secrets are missing, generation fails before requesting a model. The total
budget is eight actual API requests per entry, including transport retries,
format fallback, token escalation and brief resamples. Validation gets up to
five attempts on the original brief before recovery reorders tips/re-hooks it;
all recovery shares the remaining budget. IDs, region, piece type and intended
class stay stable. No failed draft is accepted as clean. Ordinary exhausted
runs still fail if more than 10% of entries are missing.

`deadline_minutes` defaults to 75 (the workflow permits at most 75), leaving
15 minutes before the job timeout for output, artifact upload and publication.
The deadline covers throttling and backoff; a wait beyond it stops immediately.
In-flight requests use at most the remaining time as their HTTP timeout. At the
deadline the generator writes validated survivors and missing IDs, even if more
than 10% are missing. These provisional deadline datasets may miss diversity
caps; the summary records each violation and missing smoke stratum explicitly.
A zero-entry run retains its checkpoint but never replaces the public dataset.
Invalid configuration, I/O failures and broken fault-detection invariants still
fail and cannot publish corrupt data.

Each completed entry and matching hidden fault row is atomically checkpointed
immediately in provenance `checkpoint.json`. This artifact is hidden generation
metadata, never labeling input or a tracked file. To continue, enter the previous
workflow run ID in `resume_run`, retaining the same n, seed, base token budget,
rate, model and code version. The workflow downloads that run's provenance via
its existing repository token and passes `--resume <checkpoint.json>`. Prompt,
rule, source, Python and config hashes must match; a mismatched checkpoint is
rejected. Completed entries are reused without requests; request counts for
incomplete entries remain capped at eight across resume. Fault mutations use
per-ID seeds, so resuming does not shift later entries' recipe assignments.
Use the newest run ID for successive resumes. Expired artifacts and runs from
before Fix 3c without a checkpoint cannot resume.

Accepted partial runs contain only validated survivors. They report requested
and actual sizes, failed IDs, type/region counts and missing smoke strata. The
smoke list covers available strata with up to 20 distinct survivors; it can be
shorter if fewer than 20 survived. These losses are reported rather than
replacing failed bodies with invalid placeholders. Invalid configuration, I/O
errors or a broken fault-detection invariant still fail rather than publishing
corrupt data. Failed attempts retain their provenance artifact when available. The
workflow uses its existing repository token to publish;
branch protection can prevent the push and must be handled in repository settings.

## Planning and clean-body generation

Sampling is local and seeded. Largest-remainder quotas use weights 45:20:15 for
simple pitch lists, Q&A and CPR. At 80 entries the exact counts are 45, 20 and 15;
regions split 40/40. Odd totals put the extra entry in UK. Clean count is 25%,
rounded to the nearest integer. Each piece type reserves clean, revise and major
examples, so the smoke subset can cover all nine type/intended-class cells.
The final smoke ID order is shuffled and carries no class labels.

Briefs come from `rules/brief_catalog.yaml`, not a hard-coded household scenario.
Its twelve domains cover personal finance, mortgages/property, travel, home/garden,
sleep/health, dental, pets, careers, parenting, cybersecurity/scams, motoring and
food/nutrition. Each has three specific credentials, a voice tier per credential,
three hooks and twelve concrete candidates per noun category. The six categories
are mistakes, red flags, signs, tips, wastes of money and habits. Eight headline
templates retain the specific credential; generic credentials occur only through
the C10 recipe. Experts remain unnamed synthetic composites, never real people.

Each entry independently draws 3, 5 or 7 tips with weights .25/.5/.25; these are
sampling probabilities, not exact per-batch quotas. The schema supports seven
tips and remains compatible with earlier entries. Headlines and response schemas
use the actual count. Public optional brief fields `domain`, `noun_category`,
`headline_template` and `voice_tier` describe the brief, not its injected faults.
Approved labels come only from `rules/labels.yaml`. Nonmedical red flags use
"What to check next"; clinical red flags use "When to seek professional advice".

The seeded planner balances domains, credentials within domains and templates,
consuming every selected tip from its pool once. Outside deadline partials, survivors must
satisfy domain <=15%, credential <=10%, template <=25%, and no exact brief tip
reuse across entries (case-insensitive). These are hard limits, not rounded
shares; invalid survivors are not published. Deadline partials report cap violations for
completion through resume. With 864 candidates, the catalog is
finite: an infeasible request fails before API calls and asks for fewer entries
or more unique candidates. It never silently reuses a tip to fill a quota.
Recovery retains domain, credential, template, category, count and ownership of
its tips; it changes the tip order and hook, preserving all diversity guarantees.

Clinical voice is restricted to sleep/health, dental and pet-health topics.
The body prompt receives the explicit voice tier and requires proportionate
clinical statements; routine inconvenience must not be medicalised. Accessible
precise and lifestyle credentials use their corresponding registers. These
semantic requirements still need human review; deterministic validation cannot
establish medical accuracy or writing quality.

The prompt is versioned in `prompts/synthetic/generate_body.md` (v2.1). The model
returns structured titles, questions, prose and CPR statistic self-checks.
Numbering, labels, attribution, standfirst and source metadata are rendered
locally. Each prose paragraph contains two or three sentences. No draft text
may contain the words "fictional", "invented" or "simulation"; fictionality is
recorded here and in provenance, with made-up organisations and statistics in
the drafts. No actual surveys, sourced evidence or agreement results are claimed.

For each CPR item the model proposes a short, non-numeric survey-behaviour claim,
a relevance decision and a rationale connecting it to that item's tip AND prose.
The prompt requires a per-entry review of every claim, rejecting same-topic but
unrelated statistics, medical efficacy claims and vague "used this approach"
wording. A failed relevance decision drops that statistic; a missing CPR
self-check or malformed accepted claim triggers validation feedback. Retained
raw responses contain the rationale; human reviewers must still judge whether
accepted claims really support the prose. `validation.json` reports rendered
and dropped statistics on accepted clean entries, before deliberate faults.

The renderer supplies a stable seeded percentage, sample size (600–2000),
matching UK/US region, year 2026, the domain's made-up survey organisation, tier 3
and a `https://source.invalid/survey/...` URL. The year is a fixed fixture version,
not the current clock, so exact replay is stable. Refresh it when fixtures age
beyond the rubric's three-year window. Numbers, URLs, source names and dates
cannot be supplied through prose paragraphs or accepted survey claims. Never
use these synthetic figures as real research citations.

All ten existing deterministic checks must pass or be inapplicable on a clean
body. Before this validation, only clean model drafts receive deterministic
normalization: U+2010/U+2011 become ASCII hyphens when between word characters,
titles become sentence-case with canonical names from `rules/proper_nouns.yaml`,
and trailing title punctuation is removed. Each edit records its field path,
operation, before and after in attempt provenance. Paragraph counts, content,
question format and all final deterministic checks remain enforced. Nothing is
normalized after fault injection, so deliberate C8/J2 faults remain observable.

Before any API call, brief validation checks the headline count and noun
category, verb polarity, natural domain phrase and tip membership in the curated
category pool. “Warns of” goes with mistakes, red flags, signs or wastes of money;
“shares”/“reveals” goes with tips or beneficial habits. Bad-habit headlines cannot
reuse the beneficial habit pool. Domain wording uses phrases such as “for dog
owners” and “when booking a holiday”. This validates the local brief contract;
it does not claim semantic validation of model prose.

Each entry starts with strict JSON-schema output and the actual item/paragraph
counts. Any HTTP 400 changes that entry to `json_object`; if that shape fails,
raise the token budget once by 2048 (cap 8000), then stop on another 400.
Truncated (`finish_reason=length`) responses use the same recovery sequence.
A 400 request shape is never resent. Transient errors allow at most two
identical requests, and all requests share the eight-request entry cap. Both
formats retain the same local validation; no invalid body becomes acceptable.
Clear non-400 capability rejections still negotiate JSON mode.

`max_tokens` / `--max-tokens` is now the base budget, default 2048. Each brief
adds 500 tokens per item and CPR adds 200 per planned statistic, capped at 8000.
For seven-item CPR the initial budget is 6948. Model IDs containing `gpt-oss`
receive the standard `reasoning_effort="low"` request parameter. Other models
receive no reasoning parameter. Account input/token quotas still apply.

`--max-rpm` remains the initial maximum rate, default 20. Every 429 reduces the
rate by multiplying the minimum request interval by 1.5 for the remaining run.
Numeric and HTTP-date Retry-After values set a cooldown honored even when the
client returns to validation/recovery. Waits crossing the deadline stop cleanly.
Transport and server errors have bounded backoff; TLS verification stays enabled.

Every failed HTTP request gets an `api_failed` attempt record with HTTP status,
provider error code and a redacted provider error body of at most 2048 UTF-8
bytes. Parent validation attempts retain these diagnostics too, including errors
recovered by format fallback. Credentials, bearer tokens and URLs are redacted;
request headers are never persisted. The job summary groups failures by HTTP
status and provider code, separately from validation-check counts and missing IDs.
No semantic judge from a later task is implemented or invoked.

## Fault recipes

| Recipe | Applicability | Intended checks | Deterministic targets |
|---|---|---|---|
| `count_plus` / `count_minus` | All types | C11; count-minus also C4 | C11 |
| `noun_drift` | Headline with a recognized noun category | J1, C13 | None |
| `orphan_closers` | Simple pitch list, across items | C12 | C12 |
| `intro_lines` | Simple pitch list, one item | C12 | C12 |
| `mini_labels` | Simple pitch list or CPR | C2 | C2 |
| `cost_placeholder` | Simple pitch list with a cost-type section | C3 | C3 |
| `em_dash` | All types | C8 | C8 |
| `region_swap` | All types, a minor foreign lexical token | C9 | C9 |
| `generic_credential` | Specific credential at headline start | C10 | None |
| `dropped_tip` | At least two items/pairs | C4, C13 | None |
| `bundled_q5` | Q&A with five tips/questions | C7 | None |
| `mixed_quotes` | Q&A with at least two answers | C6 | C6 |
| `filler` | All types | J4 | J4 |
| `clinical_colloquialism` | Clinical/medical credential | J5 | None |

Approximately 25% receive no faults. Others receive one to three compatible
recipes, with duplicate or canceling structural operations excluded. Count plus,
count minus and dropped tip are mutually exclusive. Dropping a tip or removing an item
is incompatible with bundled Q5, so its
overloaded question cannot disappear in a later mutation. Dropped tip replaces a body
item with another item's content,
keeping the count but leaving a distinct brief tip uncovered. Q&A recipes keep
body text and question/answer arrays synchronized; Q1 is retained.

Count breaches, noun drift, missing tips and across-item orphan closers target
`MAJOR`; other listed recipes target `REVISE`. These are intended strata, not
human labels or a routing/verdict implementation. Human decisions may differ,
especially for mechanical-only changes and semantic faults.

Each accepted combination is checked again. Every expected deterministic target
must be a failed check on the final entry. Detection tallies count detected and
missed targets by check; an undetected target includes its confusion details in
the failure message. These tallies assess injected mechanical faults, not judge
agreement. Semantic recipes cannot be verified by the deterministic layer.

## Outputs, provenance and replay

The workflow invokes the thin `scripts/generate_synthetic.py` wrapper with
`--n`, `--seed`, `--out` and `--run-dir` in a temporary directory. The output
folder contains:

- `synthetic.jsonl`: public entries, without `injected_faults` or `human` fields.
- `smoke_ids.txt`: 20 IDs covering all type/intended-class combinations.
- `faults.jsonl`: per-ID recipe names, intended check IDs, intended verdict and
  a fingerprint of the matching public entry. This file is ignored in the main
  checkout and published only to the independent faults history.

Generation provenance contains `config.json`, `prompt_hashes.json`,
`source_hashes.json`, `validation.json`, `raw/` API responses, per-attempt
`attempts/` records (normalizations, exact validation feedback and brief schema),
and `resamples/` records (old/new briefs and reasons). The workflow
uploads it as an artifact; it is never staged to `main`. Default CLI provenance
uses `runs/generation-<timestamp>/`, whose raw folder is ignored. There are no
fake predictions or agreement metrics for this generation-only operation.

Seeded briefs and recipes are reproducible. A hosted model can still change
outputs at temperature zero. Exact regeneration therefore uses the retained
responses with `--replay-run` pointing to the extracted provenance directory;
pass the original `--n`, `--seed`, `--max-rpm` and a new `--out`/`--run-dir`. Replay makes
no model calls and requires matching model metadata, Python version, prompt,
rule (including the catalog), source-code and lockfile hashes. Older prompt-v1
artifacts require the original code and rules; v2 intentionally does not replay
those inputs as if they were generated under the new catalog. Public/sidecar paths cannot overlap
provenance paths. Preserve artifacts before their repository retention expires.

## Publication and reconciliation

The publisher uses temporary Git indexes to construct two commits. `main`
changes only the golden dataset and smoke file. `faults` contains only the
sidecar and has no shared ancestry with `main`; subsequent generations preserve
its independent history. One atomic, non-forced push updates both refs or
neither. Existing human-labeled or reconciled datasets are not replaced. The
worktree is never switched to the fault branch.

After all human labeling is complete, `scripts/reconcile_faults.py` accepts the
fault file as a positional path, `--entries` for the labeled JSONL and a required
new `--out` file. This is an offline operation suitable for Codex cloud once the
files are available; it does not need network access. It validates complete
C1–C13/J1–J7 human blocks, unique matching ID sets, known check IDs and entry
fingerprints, then copies only `injected_faults` into the new file. It refuses
to overwrite either source, an existing destination or an already reconciled
entry. Recipe names and intended verdicts remain separate. Obtaining fault
metadata is intentionally deferred until labeling is complete; do not expose it
to the future browser labeling page.

## Offline diversity report

`uv run python scripts/diversity_report.py data/golden/synthetic.jsonl` prints
Markdown distributions and a deterministic top-25 content-word frequency list.
The CLI reads no hidden sidecars or raw responses and returns nonzero for invalid
JSONL, empty data, missing planning metadata, exceeded caps or duplicate brief
tips. Legacy datasets lacking planning metadata must be regenerated to pass this
report. The Actions generation job prints the same report to its log and job
summary before atomic publication; no local terminal or API calls are needed.
The count distribution uses brief counts, so deliberate count faults do not
misrepresent planning. Word frequencies include final public prose (including
injected faults) while excluding stop words, URLs and survey attribution names.

Prompt v2.1 has no judge/agreement baseline to refresh: no evaluated run or
`data/baseline.json` exists yet. This changes synthetic generation only. Preserve
the current trial data until a new manual workflow is deliberately run, and
review sample bodies again before creating a final human labeling set.
