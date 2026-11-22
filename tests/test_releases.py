import io
import unittest
from datetime import date

from pypdf import PdfReader

from oracle.releases import parse_bls, parse_claims, parse_eia_table, parse_fomc, parse_pce, parse_wasde
from tests.fixtures import raw, text


class HistoricalReleaseTests(unittest.TestCase):
    def test_june_2026_cpi_reads_mom_and_rejects_stale_publication(self):
        html = """<PRE>8:30 a.m. (ET) Wednesday, June 10, 2026
        The Consumer Price Index for All Urban Consumers (CPI-U) increased 0.5 percent on a seasonally adjusted basis in May,
        after rising 0.6 percent in April. Over the last 12 months, the all items index increased 4.2 percent.
        The index for all items less food and energy rose 0.2 percent in May.</PRE>"""
        url = "https://www.bls.gov/news.release/archives/cpi_06102026.htm"
        release = parse_bls(html, "cpi", url, date(2026, 6, 10))
        self.assertEqual(release.actual, {"headline_mom_pct": 0.5, "core_mom_pct": 0.2})
        self.assertEqual(release.previous, {"headline_mom_pct": 0.6})
        self.assertIsNone(parse_bls(html, "cpi", url, date(2026, 7, 10)))

    def test_dol_november_19_2026_keeps_original_and_revised_claims(self):
        text = """8:30 A.M. (Eastern) Thursday, November 19, 2026
        The advance figure for seasonally adjusted initial claims was 203,000, an increase of 1,000
        from the previous week's revised level. The previous week's level was revised up by 2,000
        from 200,000 to 202,000. The 4-week moving average was 197,750."""
        release = parse_claims(text, date(2026, 11, 19))
        self.assertEqual(release.actual, {"claims": 203000})
        self.assertEqual(release.previous, {"claims": 200000})
        self.assertEqual(release.revised, {"claims": 202000})

    def test_eia_november_18_2026_uses_commercial_stocks_and_exact_period(self):
        text = """STUB_1,11/13/26,11/6/26,Difference
Crude Oil,694.158,693.952,0.206
Commercial (Excluding SPR),417.797,414.417,3.380
Total Motor Gasoline,215.949,210.757,5.193
Distillate Fuel Oil,104.901,103.330,1.571"""
        self.assertEqual(parse_eia_table(text, date(2026, 11, 13)),
                         {"crude_mb": 3.38, "gasoline_mb": 5.193, "distillates_mb": 1.571})
        self.assertEqual(parse_eia_table(text, date(2026, 11, 20)), {})

    def test_fomc_rate_with_fractions_and_range(self):
        html = "The Committee decided to maintain the target range for the federal funds rate at 3-3/4 to 4 percent."
        release = parse_fomc(html, "https://federalreserve.gov")
        self.assertEqual(release.actual, {"upper_pct": 4, "lower_pct": 3.75})
        self.assertEqual(release.previous, {"upper_pct": 4})

    def test_pce_october_29_2026_reads_monthly_table(self):
        html = """EMBARGOED UNTIL RELEASE AT 8:30 a.m. EDT, Thursday, October 29, 2026
        Personal Income and Related Measures [Percent change from preceding month]
        August September PCE price index 0.3 0.5 PCE price index excluding food and energy 0.3 0.3"""
        release = parse_pce(html, date(2026, 10, 29), "https://bea.gov")
        self.assertEqual(release.actual, {"headline_mom_pct": 0.5, "core_mom_pct": 0.3})

    def test_wasde_uses_prior_projection_for_same_marketing_year(self):
        xml = """<Report><Report Report_Month="November 2026"
            sub_report_title="U.S. Wheat Supply and Use 1/">
            <attribute1 attribute1="Ending Stocks">
              <year market_year1="2026/27 Proj."><months><month forecast_month1="Oct">
                <Cell cell_value1="740"/></month></months></year>
              <year market_year1="2026/27 Proj."><months><month forecast_month1="Nov">
                <Cell cell_value1="743"/></month></months></year>
            </attribute1></Report></Report>"""
        release = parse_wasde(xml, date(2026, 11, 10), "https://usda.gov")
        self.assertEqual(release.actual, {"Wheat": 743})
        self.assertEqual(release.previous, {"Wheat": 740})
        self.assertIsNone(parse_wasde(xml, date(2026, 12, 10), "https://usda.gov"))


class OfficialReleaseFixtureTests(unittest.TestCase):
    """Real releases downloaded from the agencies on 2026-11-21."""

    def test_cpi_october_2026(self):
        release = parse_bls(text("bls_cpi_2026-11-10.txt"), "cpi", "u", date(2026, 11, 10))
        self.assertEqual(release.actual, {"headline_mom_pct": 0.4, "core_mom_pct": 0.3})
        self.assertEqual(release.previous, {"headline_mom_pct": 0.6})

    def test_ppi_october_2026(self):
        release = parse_bls(text("bls_ppi_2026-11-13.txt"), "ppi", "u", date(2026, 11, 13))
        self.assertEqual(release.actual["headline_mom_pct"], 0.3)

    def test_employment_october_2026_with_revisions_and_unemployment(self):
        release = parse_bls(text("bls_empsit_2026-11-06.txt"), "nfp", "u", date(2026, 11, 6))
        self.assertEqual(release.actual["payrolls"], 165000)
        self.assertIn("unemployment_pct", release.actual)
        self.assertEqual(release.revised["payrolls"], 60000)

    def test_claims_november_19_2026_from_official_pdf(self):
        page = PdfReader(io.BytesIO(raw("dol_claims_2026-11-19.pdf"))).pages[0].extract_text()
        release = parse_claims(page, date(2026, 11, 19))
        self.assertEqual((release.actual, release.previous, release.revised),
                         ({"claims": 203000}, {"claims": 200000}, {"claims": 202000}))
        self.assertIsNone(parse_claims(page, date(2026, 11, 25)))

    def test_eia_fomc_pce_wasde(self):
        self.assertEqual(parse_eia_table(text("eia_table4_2026-11-18.csv"), date(2026, 11, 13)),
                         {"crude_mb": 3.38, "gasoline_mb": 5.193, "distillates_mb": 1.571})
        self.assertEqual(parse_fomc(text("fomc_2026-10-28.txt"), "u").actual, {"upper_pct": 4.0, "lower_pct": 3.75})
        self.assertEqual(parse_pce(text("bea_pce_2026-10-29.txt"), date(2026, 10, 29), "u").actual,
                         {"headline_mom_pct": 0.5, "core_mom_pct": 0.3})
        wasde = parse_wasde(raw("wasde_2026-11.xml"), date(2026, 11, 10), "u")
        self.assertEqual(wasde.actual, {"Wheat": 743, "Corn": 1758, "Soybeans": 300})
        self.assertEqual(wasde.previous, {"Wheat": 740, "Corn": 1849, "Soybeans": 315})
