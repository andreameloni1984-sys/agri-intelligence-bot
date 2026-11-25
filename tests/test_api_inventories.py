import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from oracle import api_inventories as api
from tests.fixtures import text


def item(title, published, publisher="Seeking Alpha"):
    return {"title": title, "publisher": publisher, "published": published}


class HeadlineTests(unittest.TestCase):
    def test_real_headlines(self):
        cases = {
            "U.S. crude stockpiles rose 5.3M barrels last week, API says (USO:NYSEARCA)": 5.3,
            "U.S. crude stockpiles fell 2M barrels last week, API says": -2.0,
            "Strait of Hormuz Risk Unresolved as API Inventory Surge of 5.3 Million Barrels Weighs": 5.3,
            "US oil inventories reportedly down 5.3M barrels": -5.3,
            "API crude oil inventories -4.2M vs -1.1M expected": -4.2,
        }
        for title, value in cases.items():
            self.assertEqual(api.parse_headline(title), value, title)

    def test_ignores_eia_and_numberless_headlines(self):
        for title in ("EIA Data Shows Builds in Crude, Gasoline and Distillates",
                      "US Crude Inventories Fall 2.03M Barrels as SPR Releases Continue",
                      "API Shows Sharp Build in US Crude Oil, Distillate Inventories",
                      "Crude oil inventories +4.657 million versus -1.109 million estimate"):
            self.assertIsNone(api.parse_headline(title), title)

    def test_direction_without_figure(self):
        cases = {
            "API Shows Sharp Build in US Crude Oil, Distillate Inventories": 1,
            "Oil prices rise after API reports surprise crude draw": -1,
            "US crude inventories fall, API says": -1,
        }
        for title, direction in cases.items():
            self.assertEqual(api.parse_direction(title), direction, title)
        for title in ("EIA Data Shows Builds in Crude, Gasoline and Distillates",
                      "Oil prices rise ahead of API data"):
            self.assertIsNone(api.parse_direction(title), title)

    def test_feed_parsing_splits_publisher(self):
        xml = ("<rss><channel><item><title>U.S. crude stockpiles rose 5.3M barrels last week, API says "
               "- Seeking Alpha</title><pubDate>Tue, 17 Nov 2026 23:11:00 GMT</pubDate></item></channel></rss>")
        [parsed] = api.parse_feed(xml)
        self.assertEqual(parsed["publisher"], "Seeking Alpha")
        self.assertEqual(parsed["published"], datetime(2026, 11, 17, 23, 11, tzinfo=timezone.utc))


class RunTests(unittest.TestCase):
    rows = json.loads(text("forexfactory_week_2026-11-16.json"))
    release = datetime(2026, 11, 17, 21, 30, tzinfo=timezone.utc)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch("oracle.storage.DB_PATH", os.path.join(self.tmp.name, "t.sqlite3"))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_release_and_forecast_from_forexfactory(self):
        self.assertEqual(api.release_time(self.rows, self.release), self.release)
        when, forecast, previous = api.eia_forecast(self.rows, self.release)
        self.assertEqual((when.hour, forecast, previous), (15, 0.4, 4.7))

    def test_fallback_release_is_tuesday_new_york(self):
        now = datetime(2026, 11, 24, 22, 0, tzinfo=timezone.utc)
        self.assertEqual(api.release_time([], now), datetime(2026, 11, 24, 21, 30, tzinfo=timezone.utc))

    def test_build_above_forecast_is_short_and_sent_once(self):
        items = [item("U.S. crude stockpiles fell 4M barrels last week, API says", self.release - timedelta(days=7)),
                 item("U.S. crude stockpiles rose 5.3M barrels last week, API says", self.release + timedelta(minutes=40))]
        sent = []
        now = self.release + timedelta(hours=1)
        message = api.run(now, self.rows, items, send=lambda m: sent.append(m) or "delivered")
        self.assertIn("WTI — ⬇️ SHORT", message)
        self.assertIn("+5.3 milioni", message)
        self.assertIn("+0.4 milioni", message)
        self.assertIn("STIMA", message)
        self.assertIsNone(api.run(now, self.rows, items, send=lambda m: sent.append(m) or "delivered"))
        self.assertEqual(len(sent), 1)

    def test_draw_below_forecast_is_long(self):
        items = [item("US oil inventories reportedly down 3M barrels", self.release + timedelta(minutes=20))]
        message = api.run(self.release + timedelta(minutes=30), self.rows, items, send=lambda m: "delivered")
        self.assertIn("WTI — ⬆️ LONG", message)

    def test_in_line_gives_no_direction(self):
        items = [item("U.S. crude stockpiles rose 1M barrels last week, API says", self.release + timedelta(minutes=20))]
        message = api.run(self.release + timedelta(minutes=30), self.rows, items, send=lambda m: "delivered")
        self.assertIn("nessuna direzione", message)
        self.assertNotIn("LONG", message)

    def test_nothing_outside_window_or_before_news(self):
        self.assertIsNone(api.run(self.release - timedelta(minutes=5), self.rows, [], send=self.fail))
        self.assertIsNone(api.run(self.release + timedelta(hours=5), self.rows, [], send=self.fail))
        self.assertIsNone(api.run(self.release + timedelta(minutes=10), self.rows, [], send=self.fail))

    def test_disagreeing_headlines_wait(self):
        items = [item("U.S. crude stockpiles rose 5.3M barrels last week, API says", self.release + timedelta(minutes=20)),
                 item("US oil inventories reportedly down 5.3M barrels", self.release + timedelta(minutes=25))]
        self.assertIsNone(api.run(self.release + timedelta(minutes=30), self.rows, items, send=self.fail))

    def test_figureless_headline_waits_then_sends_direction(self):
        items = [item("API Shows Draw in US Crude Oil Inventories", self.release + timedelta(minutes=10))]
        self.assertIsNone(api.run(self.release + timedelta(minutes=30), self.rows, items, send=self.fail))
        message = api.run(self.release + timedelta(minutes=50), self.rows, items, send=lambda m: "delivered")
        self.assertIn("in calo (il titolo non riporta la cifra)", message)
        self.assertIn("WTI — ⬆️ LONG", message)   # forecast +0.4: a draw goes against it

    def test_figureless_same_direction_as_forecast_gives_no_direction(self):
        items = [item("API Shows Sharp Build in US Crude Oil, Distillate Inventories",
                      self.release + timedelta(minutes=10))]
        message = api.run(self.release + timedelta(minutes=50), self.rows, items, send=lambda m: "delivered")
        self.assertIn("nessuna direzione", message)
        self.assertNotIn("SHORT", message)

    def test_figure_beats_figureless_headline(self):
        items = [item("API Shows Sharp Build in US Crude Oil Inventories", self.release + timedelta(minutes=5)),
                 item("U.S. crude stockpiles rose 5.3M barrels last week, API says", self.release + timedelta(minutes=40))]
        message = api.run(self.release + timedelta(minutes=50), self.rows, items, send=lambda m: "delivered")
        self.assertIn("+5.3 milioni", message)

    def test_failed_delivery_retries(self):
        items = [item("U.S. crude stockpiles rose 5.3M barrels last week, API says", self.release + timedelta(minutes=20))]
        now = self.release + timedelta(minutes=30)
        api.run(now, self.rows, items, send=lambda m: "retry")
        self.assertIsNotNone(api.run(now, self.rows, items, send=lambda m: "delivered"))


if __name__ == "__main__":
    unittest.main()
