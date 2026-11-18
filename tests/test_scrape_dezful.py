import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import load_workbook

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


    def test_seller_type_supports_real_estate_and_personal(self):
        self.assertEqual(scraper.normalize_seller_type("business"), "املاک")
        self.assertEqual(scraper.normalize_seller_type("agency"), "املاک")
        self.assertEqual(scraper.normalize_seller_type("personal"), "شخصی")
        self.assertEqual(scraper.normalize_seller_type("individual"), "شخصی")
        self.assertEqual(scraper.normalize_seller_type("unknown"), "نامشخص")

    def test_build_year_is_extracted(self):
        row = {"token": "year-test", "title": "آپارتمان"}
        detail = {
            "attributes": {"متراژ": "۱۲۰ متر", "سال ساخت": "۱۴۰۲", "اتاق": "۲"},
            "price": 2_000_000_000, "business_type": "personal",
            "posted_at": None, "title": "آپارتمان ۱۲۰ متری",
            "description": "", "district": "بهاران",
        }
        result = scraper.make_listing(row, detail, "آپارتمان")
        self.assertEqual(result["سال_ساخت"], 1402)
        self.assertEqual(result["نوع_آگهی_دهنده"], "شخصی")


    def test_map_coordinates_are_saved_in_listing(self):
        row = {"token": "map-test", "title": "آپارتمان",
               "latitude": 32.38, "longitude": 48.40,
               "approximate_location": False}
        detail = {
            "attributes": {}, "price": None, "business_type": "personal",
            "posted_at": None, "title": "آپارتمان",
            "description": "", "district": "بهاران",
        }
        result = scraper.make_listing(row, detail, "آپارتمان")
        self.assertEqual(result["عرض_جغرافیایی"], 32.38)
        self.assertEqual(result["طول_جغرافیایی"], 48.40)
        self.assertEqual(result["موقعیت_تقریبی"], "خیر")

    def test_non_map_listing_has_no_approximate_location_flag(self):
        row = {"token": "regular-test", "title": "آپارتمان"}
        detail = {
            "attributes": {}, "price": None, "business_type": "personal",
            "posted_at": None, "title": "آپارتمان",
            "description": "", "district": "بهاران",
        }
        result = scraper.make_listing(row, detail, "آپارتمان")
        self.assertEqual(result["موقعیت_تقریبی"], "")

    def test_map_picker_opens_divar_and_parses_pasted_link(self):
        url = "https://divar.ir/s/dezful/buy-apartment?map_bbox=51.30%2C32.35%2C51.45%2C32.55"
        with patch.object(scraper.webbrowser, "open_new_tab", return_value=True) as opener, \\
             patch("builtins.input", return_value=url):
            bbox = scraper.ask_map_bbox()
        opener.assert_called_once_with(scraper.DIVAR_MAP_PICKER_URL)
        self.assertEqual(bbox["minLongitude"], 51.30)
        self.assertEqual(bbox["maxLatitude"], 32.55)

    def test_blank_dates_disable_date_filter(self):
        with patch("builtins.input", side_effect=["", ""]):
            self.assertEqual(scraper.ask_dates(), (None, None))

    def test_excel_links_are_hyperlinks_and_newest_rows_first(self):
        with TemporaryDirectory() as temp_dir:
            old_output = scraper.OUTPUT_DIR
            old_excel = scraper.EXCEL_FILE
            scraper.OUTPUT_DIR = Path(temp_dir)
            scraper.EXCEL_FILE = Path(temp_dir) / "export.xlsx"
            try:
                conn = scraper.sqlite3.connect(":memory:")
                conn.row_factory = scraper.sqlite3.Row
                conn.execute("CREATE TABLE listings (id INTEGER PRIMARY KEY, token TEXT, payload TEXT, saved_at TEXT)")
                for row_id, token in [(1, "old-token"), (2, "new-token")]:
                    row = {"عنوان": token, "لینک": f"https://divar.ir/v/{token}", "توکن": token}
                    conn.execute(
                        "INSERT INTO listings(id,token,payload,saved_at) VALUES(?,?,?,?)",
                        (row_id, token, scraper.json.dumps(row, ensure_ascii=False), "now"),
                    )
                conn.commit()
                scraper.export_excel(conn)
                book = load_workbook(scraper.EXCEL_FILE)
                sheet = book["همه آگهی‌ها"]
                self.assertEqual(sheet.cell(2, 1).value, 2)
                link_cell = sheet.cell(2, scraper.COLUMNS.index("لینک") + 1)
                self.assertEqual(link_cell.value, "مشاهده آگهی")
                self.assertEqual(link_cell.hyperlink.target, "https://divar.ir/v/new-token")
                conn.close()
            finally:
                scraper.OUTPUT_DIR = old_output
                scraper.EXCEL_FILE = old_excel

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
