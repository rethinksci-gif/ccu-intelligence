"""Illustrative partial variable cost, NOT a minimum selling price or LCA."""

from .models import RealityAssumptions

CO2_T_PER_T_METHANOL = 44.01 / 32.04
H2_T_PER_T_METHANOL = (3 * 2.016) / 32.04


def methanol(a: RealityAssumptions) -> dict:
    co2 = CO2_T_PER_T_METHANOL / a.co2_utilization
    h2 = H2_T_PER_T_METHANOL / a.h2_utilization
    parts = {
        "co2": co2 * a.co2_usd_per_t,
        "hydrogen": h2 * 1000 * a.h2_usd_per_kg,
        "process_electricity": a.process_mwh_per_t * a.electricity_usd_per_mwh,
    }
    total = sum(parts.values())
    return {
        "functional_unit": "1 tonne methanol",
        "boundary": "Purchased feedstocks and process electricity only",
        "theoretical_co2_t": CO2_T_PER_T_METHANOL,
        "theoretical_h2_t": H2_T_PER_T_METHANOL,
        "scenario_co2_t": co2,
        "scenario_h2_t": h2,
        "components_usd_per_t": parts,
        "partial_cost_usd_per_t": total,
        "gap_to_assumed_benchmark": total - a.fossil_benchmark_usd_per_t,
        "assumptions": a.model_dump(),
        "source_confidence": "Exact stoichiometry; illustrative scenario prices",
        "limitations": "Excludes CAPEX, fixed OPEX, heat, water, separation not in selected electricity, logistics, taxes and margins. Purchased H2 includes its production cost; do not add electrolysis electricity again. No lifecycle GHG result or commercial viability conclusion.",
    }
