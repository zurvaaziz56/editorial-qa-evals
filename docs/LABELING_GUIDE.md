# Human labeling guide

The [rubric](RUBRIC.md) is the source of truth. This guide concerns editorial QA;
regulatory authorisation is outside scope. Use only fictional or fully rewritten,
untraceable entries. Never upload private source material.

## 1. Read the body first

Read the full body before scoring. Then compare it with the task name, brief,
region, piece type and approved labels on the labels sheet. Do not consult
injected faults, model predictions or the separate faults branch.

Identify the structure: a simple pitch list has numbered items with exact inline
bold approved labels, no statistics and no unapproved Top tip lines. CPR has
expert attribution, a standfirst quote, Top tip lines and sourced statistics;
approved labels are not required. Q&A uses paired questions and answers;
approved labels are not required. Keep Q1 unchanged, including when it restates
the headline, and check that questions and answers have matching counts.

## 2. Score the checks

For each applicable C1–C13 and J1–J7 check, choose `pass` or `fail`. Use `na`
when the check does not apply to this piece. Record short evidence identifying
the offending span and item or question number. Do not infer missing content.
C5 is awareness only; a headline-restating Q1 must not cause a failure or escalation.

Severity vocabulary: `HARD_BLOCKER`, `STRUCTURAL`, `HARD_GAP`, `FORMAT`, `MECHANICAL`, `MAJOR_MISMATCH`, `AWARENESS_ONLY`.

| ID | Check | Applies to | Pass condition | Severity | Routing |
|---|---|---|---|---|---|
| C1 | **Label compliance** | simple pitch list | Every numbered item has every approved label present inline as a bolded sub-section header, wording and capitalisation exactly as the labels sheet | HARD_BLOCKER | escalate |
| C2 | **Mini-label scan** | pitch list, CPR | No bolded or colon-suffixed text inside sub-sections other than approved labels (offenders: "Script to use:", "Price check line:", "A practical habit:", "Boundary line:", "Tip:", "Habit:", "Example:", "Line:", "Key takeaway:", "What to say:", "Top tip:" on non-CPR) | STRUCTURAL (across items) / FLAG (single item) | escalate / fix_direct |
| C3 | **Placeholder scan on cost labels** | any piece whose labels include a cost-type label ("Estimated cost", "Potential penalty", "Savings") | No "Not provided", "TBD", "To be confirmed", "N/A", "Varies", "Check with …", "[figure to be added]" | HARD_BLOCKER | escalate |
| C4 | **One-to-one brief mapping** | all | Every brief tip has a dedicated body item (and/or question for Q&A); no tip has zero coverage | HARD_GAP | escalate |
| C5 | **Meta-question Q1** | Q&A | Awareness only. Q1 is always kept unchanged even if it restates the headline | AWARENESS_ONLY | none |
| C6 | **Quote consistency** | Q&A | All answers consistently quoted or consistently unquoted | FORMAT | fix_direct |
| C7 | **Overloaded question** | Q&A | No question bundles 2+ distinct brief tips (usually joined by "and") | STRUCTURAL | escalate |
| C8 | **Dash / artefact scan** | all | Zero em-dashes (U+2014), en-dashes (U+2013), non-breaking hyphens (U+2011), spaced hyphens " - ", stray non-Latin paste artefacts | MECHANICAL | fix_direct |
| C9 | **Regionalisation** | all | Spelling, currency, institutions and terms match `region` (colour/color, GBP/$, HMRC/IRS, NHS/Medicare, pension/401(k), Mum/Mom, garden/yard, holiday/vacation, flat/apartment …) | FORMAT (minor) / MAJOR (wrong region entirely) | fix_direct / escalate |
| C10 | **Expert credential in headline** | all | Headline leads with the most specific credential available ("Psychotherapist reveals", not "Expert reveals") | FORMAT | fix_direct (reviewer updates brief) |
| C11 | **Count contract** | any piece with a count in task name / headline / brief | Body item count equals the promised count exactly (a 6-item body for "5 mistakes" fails). Fix is always merge/replace, never add | MAJOR_MISMATCH | escalate |
| C12 | **Orphan lines** | simple pitch list | Every line belongs to the item title or a labelled sub-section; no trailing closers/aphorisms after the last label and no intro framing line before the first label | MAJOR (across multiple items) / FLAG (single item) | escalate / fix_direct |
| C13 | **Angle alignment** | all | Body delivers the title's editorial promise (angle, register, count, noun category) and every brief tip; no drift between Q&A stage and body stage | MAJOR_MISMATCH | escalate |

Additional judgment checks carried over from the body-alignment skill (score these too):

| ID | Check | Pass condition |
|---|---|---|
| J1 | **Noun category** | Items are actually the noun the title promises: mistakes = things done wrong; red flags = warning signals; signs = observable indicators; questions = literal interrogatives |
| J2 | **Sub-heading form** | List-piece item titles are short noun phrases in sentence case (first word + proper nouns only), never full sentences or instructions |
| J3 | **Sub-section depth** | Each labelled sub-section is 2–3 sentences of flowing prose with real content; flag 1-sentence or >5-sentence blocks and template filler |
| J4 | **Voice / AI filler** | None of: "it's worth noting that", "this is particularly important", "in today's world", "at the end of the day", "it goes without saying", "In this piece, I will explore", "There are many factors to consider", "Ultimately, the key is to remember", "In conclusion"; no "X, not Y" tic; no robotic task-list imperatives ("Confirm X", "Verify Y") |
| J5 | **Voice tier** | Clinical/medical expert = zero colloquialisms (flag "go-mode", "scary", "chasing scary numbers" → "falsely high"); psychotherapist / sound healer = accessible but precise; lifestyle = warmer register acceptable. Tone must match the brief's stated tone |
| J6 | **Stats hygiene** | Simple pitch: no stats in body. CPR: every stat has a source URL, credibility tier (1 authoritative/peer-reviewed, 2 industry, 3 brand-PR), region match, age < 3 years, and genuine subject-matter relevance to a specific answer |
| J7 | **Regulatory scope** | Reviewer never flags regulatory authorisation (FCA/SEC etc.) — this is editorial QA only. A judge that raises regulatory issues is wrong |


## 3. Assign routing and record notes

Use the most consequential applicable route: an escalation issue takes priority
over a direct fix. Distinguish a single affected item from repeated structural
problems. A missed escalation lets a flawed piece reach the client editor; an
unnecessary escalation wastes a writer round.

| Route | Severity / triggering issues | Action |
|---|---|---|
| `escalate` | C1/C3 hard blockers; C4 hard gap; C7 structural; C11/C13 major mismatch; C2/P5 across items; C12/P10 across items; C9 major region mismatch | A writer revision prompt is required. |
| `fix_direct` | C2 single item; C6 format; C8 mechanical; C9 minor; C10 headline credential; C12/P10 single item | The reviewer fixes the issue without a writer round. |
| `none` | No issue requiring correction; C5 awareness alone | No corrective action. |

For C11, the correction is merge/replace, never adding an item. For C10, the
reviewer updates the brief. Do not invent routing thresholds for ambiguous cases;
record the evidence and judgment in notes using the rubric's severity terms.

If a writer revision prompt is evaluated, it must be at most 2000 characters
with the exact count reported, refer to “the labels on the labels sheet” without
listing their text, include exactly one correctly formatted example item, give
itemised direct instructions across all items, retain previously locked fixes
on round 2+, and cover only one entry.

## 4. Choose the verdict last

- `READY`: all applicable checks pass; only mechanical polish at most.
- `REVISE`: checks fail but the piece is structurally sound and fixes are specific.
- `MAJOR`: wrong piece type, fundamentally wrong angle, count breach, or multiple hard blockers.

The ordinal order is READY < REVISE < MAJOR. Record notes supporting the decision.

## Labeling sessions and export

The browser page is currently a placeholder. When implemented, it will show the
body before the checklist, retain progress in browser storage and export labels
as JSON. There is no labeling CLI in this scaffold.

Use labeler `r1` or `r2` and a pass number starting at 1. Label every entry on pass 1;
allow about 3–4 minutes per entry. Re-label a random 20-entry subset at least seven
days later for pass 2. An optional second reviewer labels the same subset.
Record the timestamp, check results, judgment results, routing, notes and final
verdict. Future exports are named `labels-<labeler>-pass<N>.json`, uploaded through
the repository web UI to `data/labels/incoming/`, then merged by the future import
workflow. Do not inspect faults until human labeling is complete and reconciliation
is explicitly performed. No generation or import workflow is included in Task 1.
