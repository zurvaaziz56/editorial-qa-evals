# Synthetic generation and fault reconciliation

This is Task 3 only. Generation produces fictional entries and recipe metadata;
it does not produce human labels, judge predictions, agreement metrics or a
labeling UI. Existing tests use mocked completions and temporary outputs. No
live dataset or API call is needed for cloud validation.

## Run from the repository web UI

1. After merge, configure repository Actions secrets `JUDGE_BASE_URL`,
   `JUDGE_MODEL` and `JUDGE_API_KEY`. Keep the key in secrets, never a file.
   The base URL is the chat API root, normally including `/v1`; do not append
   `/chat/completions` yourself or put credentials in its query string.
2. Open Actions → Generate synthetic entries → Run workflow. Select `main`,
   `n=80`, `seed=7`, `max_rpm=20`. The workflow only runs on `main`. `n` must be at least 20
   because the smoke subset always contains 20 distinct entries.
3. Check validation totals in the job output. Required deterministic injections
   must all be detected; a missed target fails generation before publication.
4. Review the public JSONL after success. Read ten sample bodies for realism,
   accidental real entities and any unsupported factual claims. Do not inspect
   the faults branch or raw clean responses during blind human labeling.

If secrets are missing, generation fails before requesting a model. One bad
entry does not stop the batch: after five attempts on its original brief, it
gets up to three new briefs, each with five attempts. Its ID, region, piece type
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
corrupt data. Failed attempts retain their provenance artifact when available. The workflow uses its existing repository token to publish;
branch protection can prevent the push and must be handled in repository settings.

## Planning and clean-body generation

Sampling is local and seeded. Largest-remainder quotas use weights 45:20:15 for
simple pitch lists, Q&A and CPR. At 80 entries the exact counts are 45, 20 and 15;
regions split 40/40. Odd totals put the extra entry in UK. Clean count is 25%,
rounded to the nearest integer. Each piece type reserves clean, revise and major
examples, so the smoke subset can cover all nine type/intended-class cells.
The final smoke ID order is shuffled and carries no class labels.

Each entry has five sampled, fictional brief tips, a role credential, a
specialism, a hook and a tone. Experts are unnamed fictional composites.
Approved labels come from `rules/labels.yaml`, only for simple pitch lists.
The prompt is versioned in `prompts/synthetic/generate_body.md`. The model
returns structured titles, questions and prose paragraphs; numbering, labels,
CPR attribution, standfirst, fictional statistics and source URLs are rendered
locally. Each prose paragraph must contain two or three sentences.

Model text cannot introduce digits, URLs, price symbols, markup or newlines.
The prompt prohibits real identities, brands, research and factual claims.
These constraints reduce risk but do not prove semantic quality; human review
remains required. CPR statistics explicitly describe invented-room simulations,
use reserved `source.invalid` URLs, and have a fictional tier/region/year marker.
They are synthetic fixtures, not real research citations. Topic and credential
variety is deliberately small in this first generator.

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
count minus and dropped tip are mutually exclusive. Dropping a tip or removing an item is incompatible with bundled Q5, so its
overloaded question cannot disappear in a later mutation. Dropped tip replaces a body item with another item's content,
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
rule, source-code and lockfile hashes. Public/sidecar paths cannot overlap
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
