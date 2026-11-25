import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from oracle import levels
from oracle.notify import format_message
from oracle.prices import evaluate

SIGNAL = datetime(2026, 11, 19, 13, 31, tzinfo=timezone.utc)


def hourly(price=4000.0, rng=10.0, n=30):
    return [(price + rng / 2, price - rng / 2, price) for _ in range(n)]


def minutes(entry, moves):
    start = int(SIGNAL.timestamp())
    return [(start - 60, entry)] + [(start + 60 * (i + 1), entry + m) for i, m in enumerate(moves)]


class PlanTests(unittest.TestCase):
    def test_stop_is_1_5_atr_target_twice_and_euro_amounts(self):
        with patch.dict(os.environ, {"ACCOUNT_SIZE": "200", "RISK_PCT": "2"}):
            plan = levels.plan({"Gold": "LONG", "Copper": "NEUTRALE"}, fetch=lambda s: hourly(), fx=1.0)
        self.assertEqual(list(plan), ["Gold"])
        gold = plan["Gold"]
        self.assertAlmostEqual(gold["stop_dist"], 15.0)
        self.assertAlmostEqual(gold["target_dist"], 30.0)
        self.assertAlmostEqual(gold["risk_eur"], 4.0)
        self.assertAlmostEqual(gold["gain_eur"], 8.0)
        self.assertAlmostEqual(gold["units"], 4 / 15, places=3)
        self.assertAlmostEqual(gold["margin_eur"], gold["notional_eur"] / 20, places=2)

    def test_grains_have_distances_without_euro(self):
        plan = levels.plan({"Wheat": "SHORT"}, fetch=lambda s: hourly(540, 4), fx=1.1)
        self.assertNotIn("risk_eur", plan["Wheat"])
        text = "\n".join(levels.lines("Wheat", "SHORT", plan["Wheat"]))
        self.assertIn("6,0 centesimi sopra", text)

    def test_price_errors_leave_the_asset_out(self):
        def boom(symbol):
            raise ValueError
        self.assertEqual(levels.plan({"Gold": "LONG"}, fetch=boom, fx=1.0), {})


class MessageTests(unittest.TestCase):
    def test_message_shows_distances_euro_and_time_exit(self):
        event = {"event": "Unemployment Insurance Weekly Claims", "date_utc": "2026-11-19T13:30:00+00:00"}
        analysis = SimpleNamespace(directions={"Gold": "SHORT", "Copper": "LONG"}, reason="test")
        plan = levels.plan({"Gold": "SHORT"}, fetch=lambda s: hourly(), fx=1.0)
        text = format_message(event, analysis, "x", levels=plan)
        self.assertIn("🛑 Stop loss: 15,00 $ sopra il tuo prezzo di entrata", text)
        self.assertIn("🎯 Take profit: 30,00 $ sotto il tuo prezzo di entrata", text)
        self.assertIn("perdi circa 4,00 €", text)
        self.assertIn("dopo 60 minuti", text)
        self.assertIn("🥈 COPPER — LONG\n⏱️", text)   # no levels for Copper: no level lines

    def test_message_without_levels_is_unchanged(self):
        event = {"event": "Unemployment Insurance Weekly Claims", "date_utc": "2026-11-19T13:30:00+00:00"}
        analysis = SimpleNamespace(directions={"Gold": "LONG"}, reason="test")
        self.assertNotIn("Stop loss", format_message(event, analysis, "x"))


class OutcomeTests(unittest.TestCase):
    level = {"stop_dist": 10.0, "target_dist": 20.0, "risk_eur": 4.0}

    def test_take_profit_first(self):
        row = levels.outcome("LONG", self.level, minutes(100, [5, 12, 21, -15]), SIGNAL)
        self.assertEqual((row["exit"], row["r"], row["eur"]), ("TP", 2.0, 8.0))

    def test_stop_first_for_short(self):
        row = levels.outcome("SHORT", self.level, minutes(100, [3, 11, -25]), SIGNAL)
        self.assertEqual((row["exit"], row["r"], row["eur"]), ("SL", -1.0, -4.0))

    def test_neither_closes_at_60_minutes(self):
        row = levels.outcome("LONG", self.level, minutes(100, [2] * 59 + [5]), SIGNAL)
        self.assertEqual((row["exit"], row["r"]), ("60 MIN", 0.5))

    def test_evaluate_adds_tp_sl(self):
        bars = minutes(100, [1] * 30 + [25] * 31)
        with patch("oracle.prices.minute_bars", return_value=bars):
            result = evaluate({"Gold": "LONG"}, SIGNAL, {"Gold": self.level})
        self.assertEqual(result["Gold"]["tp_sl"]["exit"], "TP")


if __name__ == "__main__":
    unittest.main()
