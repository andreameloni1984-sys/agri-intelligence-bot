import unittest

from oracle.analysis import UNKNOWN, interpret
from oracle.models import Context, Release


class EconomicAnalysisTests(unittest.TestCase):
    def test_oil_draw_against_forecast_is_long(self):
        release = Release({"crude_mb": -3.0}, "https://eia.gov")
        result = interpret("eia", release, Context(consensus={"crude_mb": 1.0}))
        self.assertEqual(result.directions, {"WTI": "LONG", "Brent": "LONG"})

    def test_oil_build_does_not_imply_surprise_without_consensus(self):
        release = Release({"crude_mb": 3.38}, "https://eia.gov", previous={"crude_mb": 4.657})
        result = interpret("eia", release, Context())
        self.assertEqual(set(result.directions.values()), {UNKNOWN})

    def test_products_can_conflict_with_crude(self):
        result = interpret(
            "eia", Release({"crude_mb": 3.0, "gasoline_mb": -5.0}, "https://eia.gov"),
            Context(consensus={"crude_mb": 0, "gasoline_mb": 0}),
        )
        self.assertEqual(set(result.directions.values()), {UNKNOWN})

    def test_rate_and_growth_channels_point_in_opposite_directions_for_jobs(self):
        result = interpret("nfp", Release({"payrolls": 172000}, "https://bls.gov"),
                           Context(consensus={"payrolls": 130000}))
        self.assertEqual(result.directions, {"Gold": "SHORT", "Copper": "LONG"})

    def test_payroll_revision_can_cancel_surprise(self):
        release = Release({"payrolls": 172000}, "https://bls.gov", {"payrolls": 180000}, {"payrolls": 130000})
        result = interpret("nfp", release, Context(consensus={"payrolls": 130000}))
        self.assertEqual(set(result.directions.values()), {UNKNOWN})

    def test_cpi_selects_metals_by_inflation_channel(self):
        release = Release({"headline_mom_pct": 0.5, "core_mom_pct": 0.2}, "https://bls.gov")
        result = interpret("cpi", release, Context(consensus={"headline_mom_pct": 0.3}))
        self.assertEqual(result.directions, {"Gold": "SHORT", "Copper": "SHORT"})
        result = interpret("cpi", release, Context(consensus={"core_mom_pct": 0.1}))
        self.assertEqual(result.directions, {"Gold": "SHORT", "Platinum": "SHORT"})

    def test_conflicting_inflation_remains_undetermined(self):
        release = Release({"headline_mom_pct": 0.5, "core_mom_pct": 0.2}, "https://bls.gov")
        result = interpret("cpi", release, Context(consensus={"headline_mom_pct": 0.3, "core_mom_pct": 0.4}))
        self.assertEqual(set(result.directions.values()), {UNKNOWN})

    def test_wasde_ranks_relative_revisions_in_historical_edition(self):
        release = Release({"Wheat": 743, "Corn": 1758, "Soybeans": 300}, "https://usda.gov",
                          {"Wheat": 740, "Corn": 1849, "Soybeans": 315},
                          periods=dict.fromkeys(("Wheat", "Corn", "Soybeans"), "2026/27"))
        result = interpret("wasde", release, Context())
        self.assertEqual(list(result.directions.items()), [("Corn", "LONG"), ("Soybeans", "LONG")])
        self.assertIn("stima USDA precedente", result.reason)

    def test_wasde_uses_baseline_from_same_marketing_year_only(self):
        release = Release({"Wheat": 500, "Soybeans": 300}, "https://usda.gov", periods={"Wheat": "2026/27"})
        result = interpret("wasde", release, Context(consensus={"Wheat": 600}, periods={"Wheat": "2025/26"}))
        self.assertEqual(result.directions["Wheat"], UNKNOWN)

    def test_preliminary_uses_attributed_scenario_not_actual(self):
        release = Release({"crude_mb": 3}, "https://eia.gov")
        context = Context(consensus={"crude_mb": 0})
        self.assertEqual(interpret("eia", release, context, True).directions["WTI"], UNKNOWN)
        context.scenario["crude_mb"] = -3
        self.assertEqual(interpret("eia", release, context, True).directions["WTI"], "LONG")
        self.assertEqual(interpret("eia", release, context).directions["WTI"], "SHORT")
