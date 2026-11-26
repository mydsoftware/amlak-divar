# -*- coding: utf-8 -*-
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import scrape_dezful


class DivarLeadIntegrationTests(unittest.TestCase):
    def test_listing_pipeline_adds_lead_analysis_columns(self):
        with TemporaryDirectory() as temp_dir:
            with patch.object(scrape_dezful, "DATA_DIR", Path(temp_dir)):
                result = scrape_dezful.make_listing(
                    {"token": "test-token", "title": "فروش فوری آپارتمان", "district": "پیام‌آوران"},
                    {
                        "attributes": {"متراژ": "۱۲۰"},
                        "price": 2_500_000_000,
                        "business_type": "personal",
                        "posted_at": None,
                        "title": "فروش فوری آپارتمان ۱۲۰ متری",
                        "description": "آپارتمان در محدوده پیام‌آوران",
                        "district": "پیام‌آوران",
                    },
                    "آپارتمان",
                )
        self.assertEqual(result["قصد_احتمالی"], "SELL")
        self.assertGreater(result["امتیاز_سرنخ"], 0)
        self.assertIn(result["اطمینان_تحلیل"], ("LOW", "MEDIUM", "HIGH"))
        self.assertEqual(result["نیازمند_بازبینی"], "بله")
        self.assertIn("keyword:", result["سیگنال‌های_مثبت"])


if __name__ == "__main__":
    unittest.main()
