import unittest
from unittest.mock import Mock

import divar_map


class DivarMapTests(unittest.TestCase):
    def test_parse_bbox_from_coordinates(self):
        bbox = divar_map.parse_bbox("51.30,32.35,51.45,32.55")
        self.assertEqual(bbox["minLongitude"], 51.30)
        self.assertEqual(bbox["maxLatitude"], 32.55)

    def test_parse_bbox_from_divar_url(self):
        bbox = divar_map.parse_bbox(
            "https://divar.ir/s/ahvaz?map_bbox=51.30%2C32.35%2C51.45%2C32.55"
        )
        self.assertEqual(bbox["minLatitude"], 32.35)

    def test_invalid_bbox_rejected(self):
        with self.assertRaises(ValueError):
            divar_map.parse_bbox("51,32,50,33")

    def test_map_request_contains_viewport(self):
        bbox = {"minLongitude": 51.0, "minLatitude": 32.0,
                "maxLongitude": 52.0, "maxLatitude": 33.0}
        body = divar_map.request_body("apartment-sell", "23", bbox)
        self.assertEqual(body["city_ids"], ["23"])
        self.assertEqual(body["camera_info"]["bbox"], bbox)
        self.assertEqual(body["camera_info"]["zoom"], 15)

    def test_extract_map_cards_and_coordinates(self):
        payload = {"posts": [{
            "map_post_card": {"token": "abc", "title": "آپارتمان",
                              "price_fields": [{"title": "قیمت", "value": "۲ میلیارد"}]},
            "map_pin_feature": {"lat": 32.38, "lon": 48.40,
                                "approximate_location": False}
        }]}
        rows = divar_map.extract_rows(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["token"], "abc")
        self.assertEqual(rows[0]["latitude"], 32.38)
        self.assertEqual(rows[0]["longitude"], 48.40)
        self.assertFalse(rows[0]["approximate_location"])

    def test_duplicate_map_tokens_removed(self):
        card = {"map_post_card": {"token": "same"}, "map_pin_feature": {"lat": 1, "lon": 2}}
        self.assertEqual(len(divar_map.extract_rows({"posts": [card, card]})), 1)

    def test_dense_viewport_is_subdivided(self):
        session = Mock()
        session.post.side_effect = [
            Mock(status_code=200, json=lambda: {"count": 201, "posts": []},
                 raise_for_status=lambda: None),
            *[
                Mock(status_code=200, json=lambda: {"count": 1, "posts": [{
                    "map_post_card": {"token": f"t{i}", "title": "x"},
                    "map_pin_feature": {"lat": 32, "lon": 48}
                }]}, raise_for_status=lambda: None)
                for i in range(4)
            ]
        ]
        bbox = {"minLongitude": 51, "minLatitude": 32,
                "maxLongitude": 52, "maxLatitude": 33}
        rows = divar_map.search("apartment-sell", "23", bbox, session)
        self.assertEqual(len(rows), 4)
        self.assertEqual(session.post.call_count, 5)


if __name__ == "__main__":
    unittest.main()
