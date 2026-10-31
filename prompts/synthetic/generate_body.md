---
name: synthetic-clean-body
version: "2.0"
checks: [C1, C2, C3, C4, C5, C6, C7, C8, C9, C10, C11, C12, C13, J1, J2, J3, J4, J5, J6, J7]
---

Write realistic expert-quote PR draft material for a fictional synthetic dataset.
Return the requested JSON object without markdown fences. The expert is an
unnamed composite: use only the supplied credential and specialism. Do not
introduce people, organisations, publications, brands, products or tools by name.
Never copy real research or quotes. The supplied source organisation is made up;
its survey is synthetic and must never be presented as verified real research.
Do not write the words "fictional", "invented" or "simulation" in any returned
field. Those provenance details belong outside the draft, in the dataset guide.

Return exactly as many items as there are brief tips (three, five or seven), in
that tip order. Every item has title, paragraphs, question and statistic keys.
Follow the response schema's exact item and paragraph counts. Every paragraph
has two or three substantive sentences. Use concrete mechanisms and practical
examples relevant to the tip, not generic reassurance or repeated stock prose.
Do not add numbers, dates, currencies, URLs, statistics, markup, newlines or
quotation wrapping in titles, questions or paragraphs. Use short sentence-case
noun-phrase titles without terminal punctuation or imperatives. Every question
is one interrogative dedicated to its corresponding tip; retain Q1 even when it
restates the headline. All tips must be covered exactly once.

Deliver the noun category in brief.noun_category: mistakes are wrong actions;
red flags are warning signals; signs are observable indicators; tips are useful
approaches; wastes of money are unnecessary purchases; habits are repeated
behaviours. Follow the hook and headline's editorial promise.

Use voice_tier explicitly:
- clinical: precise, measured language without colloquialisms; explain uncertainty
  and avoid diagnosis, treatment promises or medical escalation for ordinary
  inconvenience. Recommend professional assessment only for proportionate,
  persistent or concerning symptoms. Stay within the supplied clinical topic.
- accessible_precise: plain explanations, specific mechanisms and practical
  actions without unexplained jargon or exaggerated risk.
- lifestyle: warm, concrete and conversational without filler or sales language.
Use regional spelling and vocabulary throughout. Never raise regulatory approval
or authorisation issues. Avoid em/en dashes, nonbreaking or spaced hyphens,
placeholders, generic expert headlines, framing intros, orphan closers and all
forbidden_phrases. Avoid "X, not Y" constructions and robotic "Confirm X" or
"Verify Y" instructions.

The renderer inserts labels verbatim. Paragraph order must match approved_labels.
Savings paragraphs give a concrete non-numeric saving such as reusing an item.
CPR has two paragraphs per item: explanation and practical top tip. Q&A has one
answer paragraph. The renderer adds CPR expert attribution and a standfirst.

For non-CPR items, statistic must be null. For each CPR item, propose one plausible
survey claim as statistic.claim, a short gerund phrase completing "respondents
reported ..." (for example "leaving engines idling while clearing the windscreen").
No numbers, sentence punctuation, source names, region, year or URLs belong in
that claim: the renderer supplies a percentage, sample size, matching region,
year, the made-up organisation and a reserved .invalid URL locally.
Before returning the entry, self-check EVERY proposed statistic against its
specific brief tip AND item explanation. statistic.rationale explains exactly
how that behaviour supports that item's claim; statistic.relevant is true only
when the connection is direct and the hypothetical survey is plausible. A
same-topic but unrelated statistic fails. Set relevant=false for failed checks;
the renderer drops them. Do not invent medical efficacy or treatment statistics,
or use vague "used this approach" claims. Never label entries, inject faults or
return fault assignments or human labels.
