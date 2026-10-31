# Synthetic generation and fault reconciliation

This covers Task 3 and the Task 3b representative-brief update. Generation produces
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

If secrets are missing, generation fails before requesting a model. One bad
entry does not stop the batch: after five attempts on its original brief, it
gets up to three reordered/re-hooked briefs, each with five attempts. Its ID, region, piece type
and intended class remain stable. API and validation failures are logged; later
IDs still run after an entry exhausts recovery. The run fails when more than
10% of requested entries remain ungenerated (exactly 10% is accepted). On failure,
no new public dataset or fault sidecar is written and publication does not run.
Attempt provenance and a per-check failure summary are retained even on failure.
The summary counts failed attempts by check, independently of the count of
entries that ultimately failed. No failed body is accepted as a clean draft.

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
consuming every selected tip from its pool once. Actual public survivors must
satisfy domain <=15%, credential <=10%, template <=25%, and no exact brief tip
reuse across entries (case-insensitive). These are hard limits, not rounded
shares; invalid survivors are not published. With 864 candidates, the catalog is
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

The prompt is versioned in `prompts/synthetic/generate_body.md` (v2.0). The model
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

Each request includes a strict JSON schema with the exact required paragraph
array length when supported. A clear structured-output capability rejection
switches the client to plain JSON mode for subsequent requests. Invalid schemas,
authentication errors and ordinary missing-endpoint errors do not trigger a
silent downgrade. Both modes still use the same local validation.

On failed validation, the next prompt includes the exact failed check IDs and
evidence, or structural error location/expected/actual values. Feedback accumulates
for at most five attempts per brief before resampling. Transport errors, 429s
and server errors receive bounded backoff; TLS verification stays enabled.
`--max-rpm` (default 20) sets a minimum interval between all API requests,
including retries and schema fallback. The client uses standard chat messages
with the configured model and temperature zero, without provider SDKs.
`--max-tokens` (default 2048, also a workflow input) caps output tokens explicitly
so providers do not reserve a large model-default completion budget. This does
not cap input tokens or guarantee compliance with account token quotas. Numeric
`Retry-After` delays are honored in full, including waits longer than 60 seconds;
transient retries remain limited to three attempts.
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

Prompt v2 has no judge/agreement baseline to refresh: no evaluated run or
`data/baseline.json` exists yet. This changes synthetic generation only. Preserve
the current trial data until a new manual workflow is deliberately run, and
review sample bodies again before creating a final human labeling set.
