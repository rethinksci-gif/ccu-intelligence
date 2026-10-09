# Evaluation goal

Evaluate whether the supplied item helps a CCU technology, project, procurement, investment or policy team make a better decision within the next 3–24 months.

# Relevance gate

Set `ccu_relevant` to true only when the supplied text substantively addresses CO2 being converted, utilized or mineralized: CO2 captured from point sources, air or biogenic sources, or supplied as a feedstock, and turned into a fuel, chemical, polymer, material or mineral carbonate. Integrated capture-and-conversion counts. Capture, transport or storage without a utilization step is false; enhanced oil recovery is false; carbon credits, nature-based removal, emissions inventories, CO2 as a refrigerant or in food and beverages without a conversion step are false. A passing mention is not substantive. For mixed-topic texts, judge only the CCU portion; do not invent a CCU angle to justify inclusion.

E-fuels count even when the text does not spell out the CO2 feedstock: e-methanol, e-SAF/e-kerosene, power-to-liquid (PtL), e-methane and other RFNBO fuels made from hydrogen and carbon. So do: offtakes, supply agreements, plants and engineering milestones for these fuels; Fischer–Tropsch, methanol-synthesis or reverse water-gas shift technology that is offered for power-to-liquid or e-SAF; and policy or market developments that change their demand or economics (RED RFNBO targets, ReFuelEU Aviation synthetic-fuel sub-mandate, FuelEU Maritime, SAF credits and mandates). Hydrogen, e-ammonia or biofuel news is relevant only when the text links it to CO2-derived fuels, for example green-hydrogen targets that set RFNBO demand, or biofuels compared with e-methanol or e-SAF as competing compliance options; otherwise it is false. Fischer–Tropsch or SAF technology for biomass or waste feedstock only, with no power-to-liquid or CO2 route stated, is false.

# Scoring rubric (decision value, 0–10)

- **9–10 — Strategic signal.** Adopted or binding policy that changes CCU or e-fuel economics; FID, major financing or a binding offtake for a commercial-scale CO2-to-product plant; commissioning or operation at demonstration scale or larger with reported data; a major cancellation, insolvency or delay; or a quantified, independently supported result that materially changes the cost, energy or scale outlook of a route.
- **7–8 — Actionable.** Credible new evidence with a clear implication for a route choice, partner, project pipeline, offtake, price, compliance plan or experiment: a FEED or basic-engineering award for a named commercial-scale plant with a stated capacity; a long-term offtake or supply agreement with named counterparties (8 with stated volumes or duration); pilot results with performance data; financing of a pilot or demo; a credible proposal, draft or reported plan to change a policy that sets e-fuel demand or economics (for example RFNBO targets or SAF mandates); a TEA or LCA with explicit assumptions and baseline; long-duration stability data at industrially relevant conditions; a technology scale-up that is offered for power-to-liquid with a stated size.
- **5–6 — Useful context.** Relevant and concrete but incremental, early-stage, narrow, or missing a decision-critical detail: a quantified laboratory result, an MoU with named partners and a stated scale, a policy consultation, market commentary on e-fuel policy uncertainty without a concrete change, a regional funding programme, a review with a genuinely useful quantitative synthesis.
- **3–4 — Weak signal.** Mostly promotional, derivative, vague, unquantified, or disconnected from a practical decision: MoUs without scale, generic reviews, market-size reports, opinion without new evidence.
- **0–2 — Noise.** Off-topic, unsupported, duplicate or greenwashing material.

Score the development, not the outlet. A news report of a company milestone scores like the milestone (the report is secondary evidence, which the editor sees separately); it is not marked down to 6 for being a news report. Use the whole range: commercial and policy events that meet the 7–8 descriptions should score 7–8, while most single laboratory results stay at 5–6.

# Calibration examples (hypothetical)

- "Engineering firm A wins FEED for Company B's 100,000 t/yr e-methanol plant using 150 MW electrolysis and biogenic CO2" (trade-press report, full text) → **7**, `commercialization`. Named commercial-scale plant, stated capacity, a concrete step toward FID; no cost data.
- "Airline C signs a 10-year binding offtake for 30,000 t/yr of e-SAF from Company D's planned plant" (company release) → **8**, `commercialization`. Named counterparties, volume and duration; FID still pending. Without volumes or duration it would be 7.
- "Report: the European Commission may drop binding RFNBO targets in the next Renewable Energy Directive" (news report of a draft) → **7**, `economics_climate_policy`. A credible proposed change to the main demand driver for EU e-fuels; adoption would be 9, a consultation without a proposal 5–6.
- "Catalyst reaches 80% Faradaic efficiency to C2+ at 800 mA/cm² in a flow cell" (abstract only, no durability) → **5–6**, `conversion`. Quantified but narrow laboratory result.

# Evaluation guidance

Reward source quality, quantified evidence (Faradaic efficiency, current density, stability hours, single-pass conversion, selectivity, energy per tonne, cost per tonne, tCO2 per year, TRL, plant capacity), an explicit comparison baseline, readiness level, scale, economics and regulatory certainty. Distinguish laboratory results from pilots, pilots from commercial plants, announced capacity from operating output, modelled from measured results, targets from audited results, and proposed rules from adopted law. Do not reward novelty by itself.

Laboratory research can score 5–6 when it reports a specific, quantified result that could guide an experiment or route assessment; it reaches 7 only with unusually strong, decision-relevant evidence (for example long stability at industrial current density, or an integrated system with energy and cost data). A review without new quantitative synthesis scores at most 5. A market-size or forecast report scores at most 3.

The `input_basis` field states what text you received. With `headline` you saw only a title and perhaps a feed snippet: do not infer technical results, scale or commercial readiness, and score at most 6. With `abstract`, results not stated in the abstract are unknown. News reports are secondary: judge the underlying development, but do not treat the report as verification.

Score concrete, relevant incremental developments at 5–6 even when early-stage. Do not give a passing score to fill a quota; off-topic material, vague promotion and unsupported headlines stay below 5.

Set `evidence_type` to `compilation` for collections of several unrelated studies or announcements (poster or abstract compilations, research highlights, virtual issues, news digests); a compilation is never original research.

List in `projects` the named plants or projects the item is about (for example "Project ENDOR", "NorthStarH2") and in `organizations` the companies, developers, buyers and agencies that are parties to the development, using their usual short names (for example "Arcadia eFuels", "Uniper", "Plug Power"). Leave out organizations only mentioned in passing. Use empty lists when none are named.

Assign exactly one `category` from the list below based on the central subject, ignoring the source type. Use three to five specific `tags` (the product, route or catalyst family, geography, company or regulation when known). Write `summary` as one neutral sentence of what the item reports, attributed to its source type.
