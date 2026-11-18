import json
import sqlite3
import unittest
from unittest.mock import Mock

import osm_neighborhoods


class OSMNeighborhoodTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("""
            CREATE TABLE osm_geocode_cache (
                lat REAL NOT NULL, lon REAL NOT NULL, payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(lat, lon)
            )
        """)

    def tearDown(self):
        self.conn.close()

    def test_normalize_nominatim_address(self):
        result = osm_neighborhoods.normalize_address({
            "display_name": "خیابان نمونه، دزفول",
            "osm_type": "way", "osm_id": 123,
            "address": {"neighbourhood": "مصلا", "road": "بهاران ۵",
                        "city_district": "مرکز شهر"}
        })
        self.assertEqual(result["neighborhood"], "مصلا")
        self.assertEqual(result["road"], "بهاران ۵")
        self.assertEqual(result["district"], "مرکز شهر")

    def test_reverse_lookup_caches_coordinate(self):
        response = Mock()
        response.json.return_value = {
            "address": {"suburb": "بهاران", "road": "خیابان نمونه"},
            "display_name": "خیابان نمونه، دزفول"
        }
        response.raise_for_status.return_value = None
        session = Mock()
        session.get.return_value = response

        first = osm_neighborhoods.reverse_lookup(32.38123, 48.40123, self.conn, session)
        second = osm_neighborhoods.reverse_lookup(32.38124, 48.40124, self.conn, session)

        self.assertEqual(first["neighborhood"], "بهاران")
        self.assertEqual(second["road"], "خیابان نمونه")
        session.get.assert_called_once()
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM osm_geocode_cache"
        ).fetchone()[0], 1)

    def test_invalid_coordinates_do_not_call_api(self):
        session = Mock()
        self.assertEqual(osm_neighborhoods.reverse_lookup(None, 48.4, self.conn, session), {})
        session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
