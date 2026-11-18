import unittest

import osm_city_index


class OSMCityIndexTests(unittest.TestCase):
    def test_parse_named_roads_and_neighborhood_areas(self):
        result = osm_city_index.parse_overpass({"elements": [
            {"type": "way", "id": 1, "tags": {"highway": "residential", "name": "بهاران ۵"},
             "geometry": [{"lat": 32.38, "lon": 48.40}, {"lat": 32.381, "lon": 48.40}]},
            {"type": "way", "id": 2, "tags": {"place": "neighbourhood", "name:fa": "مصلا"},
             "geometry": [{"lat": 32.37, "lon": 48.39}, {"lat": 32.37, "lon": 48.41},
                          {"lat": 32.39, "lon": 48.41}, {"lat": 32.39, "lon": 48.39},
                          {"lat": 32.37, "lon": 48.39}]}
        ]})
        self.assertEqual(len(result["roads"]), 1)
        self.assertEqual(result["roads"][0]["name"], "بهاران ۵")
        self.assertEqual(result["areas"][0]["name"], "مصلا")
        residential_only = osm_city_index.parse_overpass({"elements": [{
            "type": "way", "id": 3, "tags": {"landuse": "residential", "name": "دزفول"},
            "geometry": [{"lat": 32.3, "lon": 48.3}, {"lat": 32.3, "lon": 48.5},
                         {"lat": 32.48, "lon": 48.5}, {"lat": 32.48, "lon": 48.3},
                         {"lat": 32.3, "lon": 48.3}]
        }]})
        self.assertEqual(residential_only["areas"], [])

    def test_relation_area_outer_members_are_stitched(self):
        result = osm_city_index.parse_overpass({"elements": [{
            "type": "relation", "id": 10,
            "tags": {"place": "neighbourhood", "name": "محله نمونه"},
            "members": [
                {"type": "way", "role": "outer", "geometry": [
                    {"lat": 32.37, "lon": 48.39}, {"lat": 32.37, "lon": 48.41}]},
                {"type": "way", "role": "outer", "geometry": [
                    {"lat": 32.37, "lon": 48.41}, {"lat": 32.39, "lon": 48.41}]},
                {"type": "way", "role": "outer", "geometry": [
                    {"lat": 32.39, "lon": 48.41}, {"lat": 32.39, "lon": 48.39}]},
                {"type": "way", "role": "outer", "geometry": [
                    {"lat": 32.39, "lon": 48.39}, {"lat": 32.37, "lon": 48.39}]}
            ]
        }]})
        self.assertEqual(len(result["areas"]), 1)
        self.assertEqual(len(result["areas"][0]["geometry"]), 5)

    def test_named_area_polygon_classifies_point(self):
        index = {"roads": [], "areas": [{"name": "مصلا", "geometry": [
            [32.37, 48.39], [32.37, 48.41], [32.39, 48.41],
            [32.39, 48.39], [32.37, 48.39]
        ]}]}
        result = osm_city_index.classify_point(32.38, 48.40, index)
        self.assertEqual(result["neighborhood"], "مصلا")
        self.assertGreaterEqual(result["confidence"], 0.9)

    def test_nearest_street_is_classified_without_inventing_neighborhood(self):
        index = {"areas": [], "roads": [{"name": "خیابان بهاران ۵", "highway": "residential",
            "geometry": [[32.38, 48.39], [32.38, 48.41]]}]}
        result = osm_city_index.classify_point(32.3801, 48.40, index)
        self.assertEqual(result["street"], "خیابان بهاران ۵")
        self.assertEqual(result["neighborhood"], "")
        self.assertGreater(result["confidence"], 0)

    def test_neighborhood_polygon_does_not_hide_street_and_city_name_is_ignored(self):
        index = {'areas': [
            {'name': 'دزفول', 'geometry': [[32.30, 48.30], [32.30, 48.50], [32.48, 48.50], [32.48, 48.30], [32.30, 48.30]]},
            {'name': 'بهاران', 'geometry': [[32.379, 48.39], [32.379, 48.41], [32.381, 48.41], [32.381, 48.39], [32.379, 48.39]]}
        ], 'roads': [{'name': 'خیابان بهاران', 'highway': 'residential', 'geometry': [[32.38, 48.39], [32.38, 48.41]]}]}
        result = osm_city_index.classify_point(32.3801, 48.40, index)
        self.assertEqual(result['neighborhood'], 'بهاران')
        self.assertEqual(result['street'], 'خیابان بهاران')

    def test_between_streets_requires_parallel_roads_on_opposite_sides(self):
        index = {"areas": [], "roads": [
            {"name": "بهاران ۵", "highway": "residential",
             "geometry": [[32.381, 48.39], [32.381, 48.41]]},
            {"name": "بهاران ۶", "highway": "residential",
             "geometry": [[32.379, 48.39], [32.379, 48.41]]}
        ]}
        result = osm_city_index.classify_point(32.38, 48.40, index)
        self.assertIn("بین", result["subarea"])
        self.assertIn("بهاران ۵", result["subarea"])
        self.assertIn("بهاران ۶", result["subarea"])
        self.assertLessEqual(result["confidence"], 0.72)

    def test_approximate_coordinates_reduce_confidence(self):
        index = {"areas": [], "roads": [{"name": "خیابان نمونه", "highway": "residential",
            "geometry": [[32.38, 48.39], [32.38, 48.41]]}]}
        exact = osm_city_index.classify_point(32.3801, 48.40, index)
        approximate = osm_city_index.classify_point(32.3801, 48.40, index, approximate=True)
        self.assertLessEqual(approximate["confidence"], exact["confidence"])


if __name__ == "__main__":
    unittest.main()
