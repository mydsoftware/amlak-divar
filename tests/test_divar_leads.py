# -*- coding: utf-8 -*-
import unittest

from divar_leads import BusinessProfile, analyze_listing, detect_intent, normalize_fa


class DivarLeadTests(unittest.TestCase):
    def test_persian_normalization(self):
        self.assertEqual(normalize_fa("كیف  ي"), "کیف ی")

    def test_detects_buyer_intent(self):
        intent, hits = detect_intent("خریدار آپارتمان در دزفول هستم")
        self.assertEqual(intent, "BUY")
        self.assertTrue(hits)

    def test_detects_seller_intent(self):
        intent, _ = detect_intent("فروش فوری آپارتمان")
        self.assertEqual(intent, "SELL")

    def test_unknown_intent_does_not_get_high_score(self):
        profile = BusinessProfile(
            name="املاک دزفول",
            positive_keywords=["آپارتمان"],
            target_categories=["آپارتمان"],
            target_districts=["پیام‌آوران"],
        )
        result = analyze_listing({"title": "", "description": ""}, profile)
        self.assertEqual(result.intent, "UNKNOWN")
        self.assertEqual(result.score, 0)
        self.assertEqual(result.confidence, "LOW")
        self.assertTrue(result.requires_human_review)

    def test_profile_scoring_is_explainable(self):
        profile = BusinessProfile(
            name="املاک دزفول",
            positive_keywords=["آپارتمان"],
            target_categories=["آپارتمان"],
            target_districts=["پیام آوران"],
            min_price=1_000_000_000,
            max_price=5_000_000_000,
        )
        result = analyze_listing({
            "title": "فروش آپارتمان",
            "description": "فروش فوری",
            "category": "آپارتمان",
            "district": "پیام آوران",
            "price": 2_500_000_000,
        }, profile)
        self.assertEqual(result.intent, "SELL")
        self.assertEqual(result.score, 100)
        self.assertEqual(result.confidence, "HIGH")
        self.assertIn("price:within_range", result.matched_signals)

    def test_negative_keyword_reduces_score(self):
        profile = BusinessProfile(
            name="املاک",
            positive_keywords=["آپارتمان"],
            negative_keywords=["استخدام"],
        )
        result = analyze_listing({
            "title": "فروش آپارتمان",
            "description": "استخدام مشاور املاک",
        }, profile)
        self.assertIn("negative:استخدام", result.excluded_signals)
        self.assertLess(result.score, 45)


if __name__ == "__main__":
    unittest.main()
