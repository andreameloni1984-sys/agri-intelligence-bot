import unittest
from datetime import datetime, timezone, timedelta
from oracle.analysis import build_signal, score_news, classify_market_state, rank_news_opportunities, build_news_led_signal, build_pre_news_scenario
from oracle.config import UNIVERSE
from oracle.models import NewsItem, Quote

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.gold = next(x for x in UNIVERSE if x.name == "Gold")
        self.now = datetime.now(timezone.utc)

    def item(self, title):
        return NewsItem(title, "https://example.test/" + str(abs(hash(title))), self.now, "test")

    def test_no_quote_never_emits_signal(self):
        signal, status = build_signal(self.gold, None, [])
        self.assertIsNone(signal)
        self.assertEqual(status, "NO_QUOTE")

    def test_stale_quote_blocks_signal(self):
        old = Quote("GC=F", 2010, 2000, 10, self.now - timedelta(hours=3),
                    "test", 2005, 1990, 60, 2008, 1980)
        signal, status = build_signal(self.gold, old, [])
        self.assertIsNone(signal)
        self.assertTrue(status.startswith("STALE_QUOTE_"))

    def test_generic_headline_does_not_create_direction(self):
        score, matched = score_news(self.gold, [self.item("Gold market update: sanctions announced")])
        self.assertEqual(score, 0)
        self.assertEqual(matched, [])

    def test_technical_long_does_not_require_news(self):
        quote = Quote("GC=F", 2010, 2005, 10, self.now, "test", 2005, 1990, 60, 2008, 1980)
        signal, status = build_signal(self.gold, quote, [])
        self.assertEqual(status, "SIGNAL")
        self.assertEqual(signal.direction, "LONG")
        self.assertEqual(signal.news_score, 0)
        self.assertLess(signal.stop_loss, signal.reference_price)
        self.assertGreater(signal.target_1, signal.reference_price)
        self.assertGreater(signal.target_2, signal.target_1)

    def test_technical_short_does_not_require_news(self):
        quote = Quote("GC=F", 1990, 1995, 10, self.now, "test", 2000, 2010, 40, 2015, 1992)
        signal, status = build_signal(self.gold, quote, [])
        self.assertEqual(status, "SIGNAL")
        self.assertEqual(signal.direction, "SHORT")
        self.assertGreater(signal.stop_loss, signal.reference_price)
        self.assertLess(signal.target_1, signal.reference_price)
        self.assertLess(signal.target_2, signal.target_1)

    def test_opposing_news_reduces_confidence_but_does_not_block_setup(self):
        quote = Quote("GC=F", 2010, 2005, 10, self.now, "test", 2005, 1990, 60, 2008, 1980)
        news = [self.item("Gold real yields rise and dollar strengthens")]
        signal, status = build_signal(self.gold, quote, news)
        self.assertIsNotNone(signal)
        self.assertEqual(status, "SIGNAL")
        self.assertEqual(signal.direction, "LONG")
        self.assertIn("contradicts", signal.rationale)

    def test_incomplete_technical_data_does_not_emit_signal(self):
        quote = Quote("GC=F", 2010, 2005, 10, self.now)
        signal, status = build_signal(self.gold, quote, [])
        self.assertIsNone(signal)
        self.assertEqual(status, "TECHNICAL_SETUP_NOT_CONFIRMED")

    def test_invalid_atr_blocks_signal(self):
        quote = Quote("GC=F", 2010, 2005, 0, self.now, "test", 2005, 1990, 60, 2008, 1980)
        signal, status = build_signal(self.gold, quote, [])
        self.assertIsNone(signal)
        self.assertEqual(status, "INVALID_MARKET_DATA")

    def test_asset_specific_catalysts_are_mapped(self):
        copper = next(x for x in UNIVERSE if x.name == "Copper")
        soybeans = next(x for x in UNIVERSE if x.name == "Soybeans")
        wti = next(x for x in UNIVERSE if x.name == "WTI")
        score, matched = score_news(copper, [self.item("China announces stimulus for manufacturing")])
        self.assertEqual(score, 2)
        self.assertEqual(len(matched), 1)
        score, _ = score_news(soybeans, [self.item("China import demand for soybeans rises")])
        self.assertEqual(score, 2)
        score, _ = score_news(wti, [self.item("Oil supply disruption threatens exports")])
        self.assertEqual(score, 2)

    def test_geopolitical_deescalation_maps_indirectly_to_oil_and_gold(self):
        wti = next(x for x in UNIVERSE if x.name == "WTI")
        score, matched = score_news(wti, [self.item("Iran peace deal reached; sanctions lifted")])
        self.assertEqual(score, -2)
        self.assertEqual(len(matched), 1)
        score, matched = score_news(self.gold, [self.item("Middle East ceasefire agreement reached")])
        self.assertEqual(score, -2)
        self.assertEqual(len(matched), 1)

    def test_negative_supply_and_harvest_catalysts_are_mapped(self):
        wheat = next(x for x in UNIVERSE if x.name == "Wheat")
        score, matched = score_news(wheat, [self.item("Bumper wheat crop expected this season")])
        self.assertEqual(score, -2)
        self.assertEqual(len(matched), 1)

    def test_explicitly_negated_catalyst_is_ignored(self):
        wti = next(x for x in UNIVERSE if x.name == "WTI")
        score, matched = score_news(wti, [self.item("OPEC says no production cut is planned")])
        self.assertEqual(score, 0)
        self.assertEqual(matched, [])

    def test_strong_rsi_does_not_cancel_bullish_trend(self):
        quote = Quote("GC=F", 2010, 2005, 10, self.now, "test", 2005, 1990, 82, 2008, 1980)
        signal, status = build_signal(self.gold, quote, [])
        self.assertEqual(status, "SIGNAL")
        self.assertEqual(signal.direction, "LONG")
        self.assertIn("strong bullish momentum", signal.rationale)

    def test_two_point_direction_is_reported_as_early_setup(self):
        quote = Quote("GC=F", 2010, 2015, 10, self.now, "test", 2010, 1990, 50, 2020, 1980)
        signal, status = build_signal(self.gold, quote, [])
        self.assertEqual(status, "EARLY_SETUP")
        self.assertEqual(signal.setup_type, "EARLY_SETUP")
        self.assertLessEqual(signal.confidence, 59)

    def test_bearish_primary_trend_with_bullish_rebound_is_distinguished(self):
        quote = Quote("CL=F", 91.14, 90.80, 1.2, self.now, "test", 90.5, 95.0, 59.9)
        trend, swing, interpretation = classify_market_state(quote)
        self.assertEqual(trend, "RIBASSISTA")
        self.assertEqual(swing, "RIALZISTA")
        self.assertEqual(interpretation, "rimbalzo rialzista contro trend")

    def test_bullish_primary_trend_with_bearish_pullback_is_distinguished(self):
        quote = Quote("GC=F", 4100, 4110, 10, self.now, "test", 4110, 4050, 42)
        trend, swing, interpretation = classify_market_state(quote)
        self.assertEqual(trend, "RIALZISTA")
        self.assertEqual(swing, "RIBASSISTA")
        self.assertEqual(interpretation, "correzione ribassista contro trend")


    def test_pre_news_scenario_uses_existing_catalyst_without_market_prediction(self):
        soy = next(x for x in UNIVERSE if x.name == "Soybeans")
        event = [{"phase": "IN ARRIVO", "minutes_to_event": 20,
                  "event": "USDA WASDE supply and demand report"}]
        scenario = build_pre_news_scenario(
            soy, [self.item("China resumes soybean purchases")], event
        )
        self.assertEqual(scenario["direction"], "LONG")
        self.assertEqual(scenario["score"], 2)
        self.assertEqual(scenario["confidence"], "bassa")

    def test_pre_news_scenario_is_neutral_without_evidence(self):
        soy = next(x for x in UNIVERSE if x.name == "Soybeans")
        event = [{"phase": "IN ARRIVO", "minutes_to_event": 10,
                  "event": "USDA WASDE supply and demand report"}]
        scenario = build_pre_news_scenario(soy, [], event)
        self.assertEqual(scenario["direction"], "NEUTRALE")
        self.assertEqual(scenario["score"], 0)

    def test_pre_news_scenario_does_not_run_outside_pre_release_window(self):
        soy = next(x for x in UNIVERSE if x.name == "Soybeans")
        event = [{"phase": "IN ARRIVO", "minutes_to_event": 45,
                  "event": "USDA WASDE supply and demand report"}]
        self.assertIsNone(build_pre_news_scenario(soy, [], event))

    def test_news_led_engine_does_not_select_without_asset_catalyst(self):
        ranked = rank_news_opportunities(UNIVERSE, [self.item("Global markets mixed in quiet session")])
        self.assertEqual(ranked, [])

    def test_news_led_engine_selects_commodity_from_specific_catalyst(self):
        ranked = rank_news_opportunities(UNIVERSE, [self.item("Drought damages wheat crop and threatens harvest")])
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["instrument"].name, "Wheat")
        self.assertEqual(ranked[0]["direction"], "LONG")

    def test_news_rank_excludes_catalysts_older_than_48_hours(self):
        wheat = next(x for x in UNIVERSE if x.name == "Wheat")
        stale = NewsItem("Drought damages wheat crop", "https://example.test/stale",
                         self.now - timedelta(hours=60), "Reuters")
        ranked = rank_news_opportunities(UNIVERSE, [stale])
        self.assertEqual(ranked, [])

    def test_news_rank_prefers_fresh_evidence_over_old_archive(self):
        wheat = next(x for x in UNIVERSE if x.name == "Wheat")
        fresh = NewsItem("Drought damages wheat crop", "https://example.test/fresh",
                         self.now, "Reuters")
        stale = NewsItem("Drought damages wheat crop", "https://example.test/old",
                         self.now - timedelta(hours=30), "unknown")
        fresh_rank = rank_news_opportunities([wheat], [fresh])
        stale_rank = rank_news_opportunities([wheat], [stale])
        self.assertGreater(fresh_rank[0]["rank_score"], stale_rank[0]["rank_score"])

    def test_macro_dollar_weakness_transmits_to_multiple_metals(self):
        copper = next(x for x in UNIVERSE if x.name == "Copper")
        headline = [self.item("US dollar weakens as DXY falls")]
        gold_score, _ = score_news(self.gold, headline)
        copper_score, _ = score_news(copper, headline)
        self.assertEqual(gold_score, 2)
        self.assertEqual(copper_score, 2)

    def test_geopolitical_deescalation_transmits_to_oil_and_gold(self):
        wti = next(x for x in UNIVERSE if x.name == "WTI")
        headline = [self.item("Iran diplomatic breakthrough raises ceasefire hopes")]
        gold_score, _ = score_news(self.gold, headline)
        oil_score, _ = score_news(wti, headline)
        self.assertEqual(gold_score, -2)
        self.assertEqual(oil_score, -2)

    def test_black_sea_shipping_risk_transmits_to_wheat(self):
        wheat = next(x for x in UNIVERSE if x.name == "Wheat")
        score, matched = score_news(wheat, [self.item("Black Sea shipping disrupted after port attacks")])
        self.assertEqual(score, 2)
        self.assertEqual(len(matched), 1)

    def test_china_stimulus_transmits_to_copper_without_copper_in_headline(self):
        copper = next(x for x in UNIVERSE if x.name == "Copper")
        score, matched = score_news(copper, [self.item("China announces new infrastructure spending package")])
        self.assertEqual(score, 2)
        self.assertEqual(len(matched), 1)

    def test_agricultural_macro_drivers_cover_wheat_corn_and_soybeans(self):
        wheat = next(x for x in UNIVERSE if x.name == "Wheat")
        corn = next(x for x in UNIVERSE if x.name == "Corn")
        soy = next(x for x in UNIVERSE if x.name == "Soybeans")

        wheat_score, wheat_news = score_news(
            wheat, [self.item("Black Sea shipping disrupted after port attacks")]
        )
        corn_score, corn_news = score_news(
            corn, [self.item("Ethanol margins improve as crude oil rises")]
        )
        soy_score, soy_news = score_news(
            soy, [self.item("China resumes soybean purchases")]
        )

        self.assertEqual(wheat_score, 2)
        self.assertEqual(corn_score, 2)
        self.assertEqual(soy_score, 2)
        self.assertEqual((len(wheat_news), len(corn_news), len(soy_news)), (1, 1, 1))

    def test_agricultural_macro_bearish_drivers_cover_all_three_crops(self):
        wheat = next(x for x in UNIVERSE if x.name == "Wheat")
        corn = next(x for x in UNIVERSE if x.name == "Corn")
        soy = next(x for x in UNIVERSE if x.name == "Soybeans")

        wheat_score, _ = score_news(
            wheat, [self.item("Black Sea shipping resumes and export corridor reopens")]
        )
        corn_score, _ = score_news(
            corn, [self.item("Ethanol margins weaken as crude oil falls")]
        )
        soy_score, _ = score_news(
            soy, [self.item("China cancels soybean purchases")]
        )

        self.assertEqual(wheat_score, -2)
        self.assertEqual(corn_score, -2)
        self.assertEqual(soy_score, -2)

    def test_macro_dollar_move_transmits_to_agricultural_complex(self):
        headline = [self.item("US dollar weakens as DXY falls")]
        scores = {
            name: score_news(next(x for x in UNIVERSE if x.name == name), headline)[0]
            for name in ("Wheat", "Corn", "Soybeans")
        }
        self.assertEqual(scores, {"Wheat": 2, "Corn": 2, "Soybeans": 2})

    def test_news_led_signal_requires_technical_confirmation(self):
        wheat = next(x for x in UNIVERSE if x.name == "Wheat")
        news = [self.item("Drought damages wheat crop and threatens harvest")]
        score, matched = score_news(wheat, news)
        quote = Quote("ZW=F", 590, 589, 4, self.now, "test", 588, 580, 58, 592, 575)
        signal, status = build_news_led_signal(wheat, quote, score, matched)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "LONG")
        self.assertEqual(status, "SIGNAL")
        self.assertTrue(signal.news_urls)

    def test_news_led_signal_waits_when_technicals_conflict(self):
        wheat = next(x for x in UNIVERSE if x.name == "Wheat")
        news = [self.item("Drought damages wheat crop and threatens harvest")]
        score, matched = score_news(wheat, news)
        quote = Quote("ZW=F", 580, 590, 4, self.now, "test", 585, 595, 40, 600, 575)
        signal, status = build_news_led_signal(wheat, quote, score, matched)
        self.assertIsNone(signal)
        self.assertIn("WAIT_TECHNICAL_CONFLICT", status)

    def test_news_led_signal_does_not_emit_from_technical_only_setup(self):
        quote = Quote("GC=F", 2010, 2005, 10, self.now, "test", 2005, 1990, 60, 2008, 1980)
        signal, status = build_news_led_signal(self.gold, quote, 0, [])
        self.assertIsNone(signal)
        self.assertEqual(status, "NEWS_NOT_SELECTED")

if __name__ == "__main__":
    unittest.main()
