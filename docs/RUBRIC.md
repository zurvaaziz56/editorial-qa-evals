# Editorial QA Rubric (sanitized, public-safe)

This is the source of truth for what the harness evaluates. It is a de-identified
version of a real editorial QA pipeline used to review journalist-facing expert
quote pieces ("PR bodies") before they are submitted to a PR agency client.

Terminology used throughout this repo (never use real names in this repo):

| Term in this repo | Meaning |
|---|---|
| **reviewer** | The human editor who runs QA and owns the final verdict (the labeler of the golden set) |
| **client editor** | The PR agency editor who accepts or sends back pieces |
| **writer** | The upstream drafting step (an AI writing assistant) that produces questions, answers and bodies |
| **labels sheet** | The per-task sheet that fixes the approved sub-heading labels for a piece |
| **writer revision prompt** | A ≤2000-character instruction sent back to the writer to fix a piece |

## 1. The unit of evaluation

One **entry** at body stage:

- `task_name` — the headline / editorial promise (e.g. "Psychotherapist reveals 5 signs …")
- `brief` — up to 7 tips, a hook, a tone, and the expert's credential + specialism
- `region` — `UK` or `US`
- `piece_type` — `simple_pitch_list` | `cpr` (curated press release) | `qa`
- `approved_labels` — the sub-heading labels fixed on the labels sheet (e.g. `["Why it's a mistake", "What to do instead"]`), may be empty for CPR/Q&A
- `body` — the full body text under review
- optional `questions` / `answers` for Q&A pieces

## 2. Piece types (gate many checks)

- **Simple pitch list**: numbered items; every item carries the approved labels inline as bolded sub-section headers; no stats in body; no "Top tip" lines (unless "Top Tip" is itself an approved third label).
- **CPR (curated press release)**: expert attribution paragraph + standfirst quote + "Top tip" lines + embedded stats with source URLs; approved labels NOT required.
- **Q&A**: question/answer pairs are the structure; no sub-heading labels required.

## 3. Mandatory checks (13)

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

## 4. Writer patterns (10 recurring failure modes)

| ID | Pattern | Typical frequency | Detected by |
|---|---|---|---|
| P1 | Meta-question Q1 restates the headline | ~100% of Q&A | awareness only (C5) |
| P2 | Overloaded Q5 bundling 2–3 tips with "and" | 60–70% | C7 |
| P3 | Missing brief tip (usually the most distinctive one) | 50–60% | C4 / C13 |
| P4 | "Not provided" placeholders after a restructure | round 2+ of cost pieces | C3 |
| P5 | Unauthorised mini-labels inside sub-sections | ~30%, esp. after "needs more detail" | C2 |
| P6 | Ghost answer to a dropped Q1 | deprecated (Q1 never dropped); check answer count = question count instead | C6-adjacent |
| P7 | Generic headline credential | 30–40% | C10 |
| P8 | Mixed quotation formatting in Q&A | rare | C6 |
| P9 | Em/en-dashes, spaced hyphens, paste artefacts | common | C8 |
| P10 | Intro lines before first label / orphan closers after last label | high in recent batches | C12 |

## 5. Severity routing (the business-critical decision)

Every entry gets a **routing** label:

- `escalate` — a writer revision prompt is required (content/structure problems): C1, C3, C4, C7, C11, C12-across-items, C13, P5-across-items, P10-across-items, major region mismatch.
- `fix_direct` — the reviewer fixes it by hand, no writer round: C2 single item, C6, C8, C9 minor, C10, single-item C12/P10.
- `none` — nothing to fix.

Cost asymmetry: a missed `escalate` (false negative) means a flawed piece reaches the client editor; a spurious `escalate` (false positive) wastes a writer round. Report recall and precision for `escalate` separately.

## 6. Verdict (3-class, ordinal)

- `READY` — all applicable checks pass; only mechanical polish at most.
- `REVISE` — one or more checks fail but the piece is structurally sound; fixes are specific and actionable.
- `MAJOR` — piece type is wrong, angle fundamentally off, count contract breached, or multiple hard blockers.

Order for weighted kappa: READY < REVISE < MAJOR.

## 7. Writer revision prompt constraints (if the harness evaluates generated prompts)

- ≤ 2000 characters, exact count reported
- refers to "the labels on the labels sheet", never lists label text inline
- includes exactly one example item in the correct format
- itemised fixes applied to all items, written as direct instruction, not as a QA report
- re-states all previously locked fixes on round 2+
- one prompt per entry, never combined across entries
