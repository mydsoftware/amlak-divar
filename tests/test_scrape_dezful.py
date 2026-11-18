import unittest
from datetime import date

import scrape_dezful as scraper


class ScraperTests(unittest.TestCase):
    def test_token_from_action_payload(self):
        row = {"data": {"action": {"payload": {"token": "abc123"}}}}
        self.assertEqual(scraper.extract_token(row), "abc123")

    def test_token_from_direct_field(self):
        self.assertEqual(scraper.extract_token({"data": {"token": "xyz"}}), "xyz")

    def test_duplicate_rows_removed(self):
        payload = {"list_widgets": [
            {"widget_type": "POST_ROW", "data": {"action": {"payload": {"token": "a"}}}},
            {"widget_type": "POST_ROW", "data": {"token": "a"}},
            {"widget_type": "POST_ROW", "data": {"token": "b"}},
        ]}
        self.assertEqual([x["token"] for x in scraper.extract_search_rows(payload)], ["a", "b"])

    def test_pagination_cursor_preserved(self):
        cursor = {"last_post_date": "2026-11-01T10:00:00Z", "pelle_max_score": 12,
                  "filters_hash": "hash", "cumulative_widgets_count": 24}
        body = scraper.search_body("apartment-sell", "23", None, cursor, 2)
        self.assertEqual(body["pagination_data"]["last_post_date"], cursor["last_post_date"])
        self.assertEqual(body["pagination_data"]["pelle_max_score"], 12)
        self.assertEqual(body["pagination_data"]["page"], 2)

    def test_money_million_and_billion(self):
        self.assertEqual(scraper.parse_money("۲.۵ میلیارد تومان"), 2_500_000_000)
        self.assertEqual(scraper.parse_money("۸۵۰ میلیون تومان"), 850_000_000)
        self.assertEqual(scraper.parse_money("۲۵۰٬۰۰۰٬۰۰۰ تومان"), 250_000_000)

    def test_exact_jalali_publish_date(self):
        parsed = scraper.parse_jalali_datetime("انتشار آگهی: ۲۵ آبان ۱۴۰۵، ۱۴:۳۰")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.utcoffset().total_seconds(), 12600)

    def test_jalali_input(self):
        self.assertEqual(scraper.jalali_input("1405/08/01"), date(2026, 10, 23))


    def test_legacy_checkpoint_migration(self):
        state = {"categories": {"apartment-sell": {
            "cursor": "2026-11-01T10:00:00Z",
            "next_cursor": "2026-10-31T10:00:00Z",
            "pending": ["legacy-token"],
        }}}
        migrated = scraper.category_state(state, "apartment-sell")
        self.assertEqual(migrated["cursor"]["last_post_date"], "2026-11-01T10:00:00Z")
        self.assertEqual(migrated["next_cursor"]["last_post_date"], "2026-10-31T10:00:00Z")
        self.assertEqual(migrated["pending"][0]["token"], "legacy-token")

    def test_district_names_are_not_sent_as_free_text_query(self):
        body = scraper.search_body("apartment-sell", "23", ["بهاران"], None, 1)
        self.assertNotIn("query", body["search_data"])

    def test_detail_section_parser(self):
        payload = {"webengage": {"price": 3_000_000_000}, "sections": [
            {"section_name": "TITLE", "widgets": [
                {"widget_type": "LEGEND_TITLE_ROW", "data": {"title": "آپارتمان ۱۲۰ متری"}},
                {"widget_type": "EXPANDABLE_SECTION", "data": {"title": "دقایقی پیش در دزفول، بهاران",
                 "widget_list": [{"data": {"text": "انتشار آگهی: ۲۵ آبان ۱۴۰۵، ۱۴:۳۰"}}]}}
            ]},
            {"section_name": "LIST_DATA", "widgets": [
                {"widget_type": "UNEXPANDABLE_ROW", "data": {"title": "متراژ", "value": "۱۲۰"}},
                {"widget_type": "UNEXPANDABLE_ROW", "data": {"title": "سال ساخت", "value": "۱۴۰۲"}}
            ]}
        ]}
        result = scraper.extract_detail_fields(payload)
        self.assertEqual(result["title"], "آپارتمان ۱۲۰ متری")
        self.assertEqual(result["attributes"]["متراژ"], "۱۲۰")
        self.assertIsNotNone(result["posted_at"])
        self.assertEqual(result["price"], 3_000_000_000)


if __name__ == "__main__":
    unittest.main()
