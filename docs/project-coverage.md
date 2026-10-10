# Project coverage — 10 October 2026

The tracker contains nine sourced project baselines across six countries. Six records were added in this expansion, with nine evidence records containing source URLs, page locators, retrieval timestamps, publication dates where available, and SHA-256 hashes of the retrieved HTML. These are attributed source checks, not plant audits or human-reviewed lifecycle findings.

| Added project | Country | Source and scope |
| --- | --- | --- |
| George Olah | Iceland | [CRI](https://carbonrecycling.com/projects/george-olah): historical commissioning and expanded methanol design capacity. Current operation is not established. |
| Shunli | China | [CRI](https://carbonrecycling.com/projects/shunli): Henan Shuncheng ownership, coke-derived feedstocks and methanol design capacity. Conflicting quarter/month commissioning references remain explicit. |
| Haru Oni | Chile | [HIF](https://hifglobal.com/locations/hif-haru-oni): reported operation using biogenic CO₂ and methanol-to-gasoline synthesis. DAC is not assumed operational. |
| AirPlant One | United States | [Twelve](https://www.twelve.co/airplant): reported operation; electrolysis, Fischer–Tropsch synthesis and upgrading are described in the linked technical article. |
| ERA ONE | Germany | [INERATEC](https://www.ineratec.de/en/era-one-e-fuels-made-germany): reported operation and an upper design target for synthetic fuels. |
| HEIM Berlin | Germany | [neustark](https://www.neustark.com/en/news/from-pilot-project-to-the-first-commercial-co2-storage-site-in-germany-a-case-study): a specific HEIM site producing carbonated recycled aggregate, with neustark as technology supplier. |

## Capacity and status interpretation

- All six additions leave measured annual output, achieved TRL, CAPEX, OPEX and independently reviewed climate claims unknown.
- Haru Oni's gasoline design volume and AirPlant One's approximate E-Jet design volume remain in their limitations text. The current structured capacity schema supports mass rates only; these volume figures are not converted using assumed densities or gallon conventions. Their empty structured capacity fields do not mean that the sources contain no capacity information.
- HEIM's reported storage threshold is a CO₂ metric, not product output. Neither that lower bound nor total demolition-waste recycling throughput is recorded as an exact carbonated-aggregate capacity.
- ERA ONE's design target is an upper limit for e-fuels, not a dedicated SAF capacity or measured output.
- Old commissioning statements remain historical baselines. A fresh source-check date does not establish current operation or create a new commissioning event. Exact startup dates are left empty where only a year, quarter, inauguration or first-product milestone is available.
- The three previously published project baselines and their evidence are preserved. No event history is manufactured for the additions.

The canonical records are in `data/curated/verified-projects.json`; the build validates their relationships and regenerates `public/data/intelligence.json`. The tracker, filters, detail routes and downloadable data all use that same export.
