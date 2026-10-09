# Evaluation goal

Evaluate whether the supplied item helps a CCU technology, project, procurement, investment or policy team make a better decision within the next 3–24 months.

# Relevance gate

Set `ccu_relevant` to true only when the supplied text substantively addresses CO2 being converted, utilized or mineralized: CO2 captured from point sources, air or biogenic sources, or supplied as a feedstock, and turned into a fuel, chemical, polymer, material or mineral carbonate. Integrated capture-and-conversion counts. Capture, transport or storage without a utilization step is false; enhanced oil recovery is false; carbon credits, nature-based removal, emissions inventories, CO2 as a refrigerant or in food and beverages without a conversion step are false. Hydrogen, ammonia or biofuel news is false unless CO2 is a stated feedstock. A passing mention is not substantive. For mixed-topic texts, judge only the CCU portion; do not invent a CCU angle to justify inclusion.

# Scoring rubric (decision value, 0–10)

- **9–10 — Strategic signal.** Adopted or binding policy that changes CCU economics; FID, major financing or a binding offtake for a commercial-scale CO2-to-product plant; commissioning or operation at demonstration scale or larger with reported data; a major cancellation, insolvency or delay; or a quantified, independently supported result that materially changes the cost, energy or scale outlook of a route.
- **7–8 — Actionable.** Credible new evidence with a clear implication for a route choice, partner, project pipeline, offtake, price, compliance plan or experiment: pilot results with performance data, financing of a pilot or demo, a TEA or LCA with explicit assumptions and baseline, long-duration stability data at industrially relevant conditions, a named offtake or supply agreement with volumes.
- **5–6 — Useful context.** Relevant and concrete but incremental, early-stage, narrow, or missing a decision-critical detail: a quantified laboratory result, an MoU with named partners and a stated scale, a policy consultation or draft, a regional funding programme, a review with a genuinely useful quantitative synthesis.
- **3–4 — Weak signal.** Mostly promotional, derivative, vague, unquantified, or disconnected from a practical decision: MoUs without scale, generic reviews, market-size reports, opinion without new evidence.
- **0–2 — Noise.** Off-topic, unsupported, duplicate or greenwashing material.

# Evaluation guidance

Reward source quality, quantified evidence (Faradaic efficiency, current density, stability hours, single-pass conversion, selectivity, energy per tonne, cost per tonne, tCO2 per year, TRL, plant capacity), an explicit comparison baseline, readiness level, scale, economics and regulatory certainty. Distinguish laboratory results from pilots, pilots from commercial plants, announced capacity from operating output, modelled from measured results, targets from audited results, and proposed rules from adopted law. Do not reward novelty by itself.

Laboratory research can score 5–6 when it reports a specific, quantified result that could guide an experiment or route assessment; it reaches 7 only with unusually strong, decision-relevant evidence (for example long stability at industrial current density, or an integrated system with energy and cost data). A review without new quantitative synthesis scores at most 5. A market-size or forecast report scores at most 3.

The `input_basis` field states what text you received. With `headline` you saw only a title and perhaps a feed snippet: do not infer technical results, scale or commercial readiness, and score at most 6. With `abstract`, results not stated in the abstract are unknown. News reports are secondary: judge the underlying development, but do not treat the report as verification.

Score concrete, relevant incremental developments at 5–6 even when early-stage. Do not give a passing score to fill a quota; off-topic material, vague promotion and unsupported headlines stay below 5.

Assign exactly one `category` from the list below based on the central subject, ignoring the source type. Use three to five specific `tags` (the product, route or catalyst family, geography, company or regulation when known). Write `summary` as one neutral sentence of what the item reports, attributed to its source type.
