---
name: synthetic-clean-body
version: "1.0"
checks: [C1, C2, C3, C4, C5, C6, C7, C8, C9, C10, C11, C12, C13, J1, J2, J3, J4, J5, J6, J7]
---

Write fictional editorial material for a synthetic QA evaluation, using only the
provided brief. Return the requested JSON object, without markdown fences.
The expert is an unnamed fictional composite; use only the supplied credential
and specialism. Do not introduce names of people, organizations, publications,
brands, tools or boards. Do not quote or reproduce real source material.
Do not introduce URLs, research, dates, statistics, numerical claims or prices.
The renderer supplies explicitly fictional simulation figures and reserved
.invalid source URLs for CPR pieces, separately from your prose.

Return exactly five items, in the brief's tip order, each covering only its
corresponding tip. Each item has `title`, `paragraphs` and `question` fields.
`paragraphs` contains exactly the requested number of strings per item.
Each string is one paragraph of two or three substantive sentences. Never put
newlines, headings, mini-labels, markdown, quotations or numbered lists inside
paragraphs. Titles are short sentence-case noun phrases, without terminal
punctuation or imperative verbs. Item titles and content must deliver the
headline's noun category: mistakes are wrong actions, red flags are observable
warning signals, tips are useful habits, waste of money identifies unneeded
purchases. `question` is a single question dedicated to the corresponding tip;
Q1 may restate the headline and must never be dropped for that reason.

Match the requested region's spelling and vocabulary. Use the brief's tone.
Clinical/medical credentials require precise prose without colloquialisms;
psychotherapist prose is accessible and precise. Never raise regulatory
approval or authorization issues. Keep every tip covered and retain the count.
Do not include em/en dashes, nonbreaking hyphens, spaced hyphens or paste artefacts.
Do not include placeholders, generic expert headlines, orphan closers, framing
intros, statistics for pitch lists, unnecessary quotation wrapping or filler.
In particular omit all phrases in `forbidden_phrases`; avoid contrastive
"X, not Y" phrasing and robotic "Confirm X" / "Verify Y" instructions.

The caller renders approved labels verbatim. In label-based pieces, paragraph
order must match the provided labels. A Savings paragraph must give a concrete
non-numeric fictional saving (reuse what is already available), without a
placeholder. CPR paragraph one supplies the item prose and paragraph two a
practical top tip. Q&A uses one paragraph as the answer. Do not judge or label
any entry, invent faults or include fault metadata in the response.
