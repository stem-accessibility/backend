"""Chart permalinks: validation, ownership, sharing and the public link.

Runs against a throwaway SQLite file with dev auth; never touches a real database.
    .venv/bin/python -m unittest tests.test_charts -v
"""
import os
import tempfile
import unittest

_tmp = tempfile.mkdtemp()
os.environ["AUTH_MODE"] = "dev"
os.environ["AUTO_CREATE_TABLES"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.sqlite"
os.environ.pop("K_SERVICE", None)

from backend.app_factory import create_app  # noqa: E402
from backend.chart_validation import (  # noqa: E402
    MAX_ROWS,
    ChartValidationError,
    clean_config,
    clean_dataset,
    clean_spec,
)
from backend.db import db  # noqa: E402
from backend.models import Chart  # noqa: E402
from backend.study.event_types import EVENT_TYPES  # noqa: E402

DATASET = {
    "name": "months.csv",
    "columns": ["month", "temp_c"],
    "rows": [{"month": "Jan", "temp_c": 3}, {"month": "Feb", "temp_c": 5}, {"month": "Mar", "temp_c": None}],
}
CONFIG = {"preset": "bar", "valueColumn": "temp_c", "categoryColumn": "month", "title": "Average temperature"}


class ValidationTests(unittest.TestCase):
    def test_keeps_a_good_table_and_fills_gaps(self):
        d = clean_dataset({"columns": ["a", "b"], "rows": [{"a": 1}, {"a": "x", "b": 2.5, "junk": 9}]})
        self.assertEqual(d["rows"], [{"a": 1, "b": None}, {"a": "x", "b": 2.5}])

    def test_rejects_bad_shapes(self):
        bad = [
            None,
            {},
            {"columns": [], "rows": [{}]},
            {"columns": ["a"], "rows": []},
            {"columns": ["a", "a"], "rows": [{"a": 1}]},
            {"columns": ["a", " "], "rows": [{"a": 1}]},
            {"columns": ["a"], "rows": ["not a row"]},
            {"columns": ["a"], "rows": [{"a": {"nested": 1}}]},
            {"columns": ["a"], "rows": [{"a": "x" * 501}]},
        ]
        for b in bad:
            with self.subTest(b=str(b)[:40]), self.assertRaises(ChartValidationError):
                clean_dataset(b)

    def test_row_cap(self):
        rows = [{"a": i} for i in range(MAX_ROWS + 1)]
        with self.assertRaises(ChartValidationError):
            clean_dataset({"columns": ["a"], "rows": rows})

    def test_config_is_whitelisted_and_columns_must_exist(self):
        c = clean_config(
            {"preset": "line", "valueColumn": "v", "timeColumn": "gone", "evil": "x", "xLabel": "  Time  "},
            ["t", "v"],
        )
        self.assertEqual(c["valueColumn"], "v")
        self.assertIsNone(c["timeColumn"])
        self.assertEqual(c["xLabel"], "Time")
        self.assertNotIn("evil", c)

    def test_config_rejects_unknown_choices(self):
        with self.assertRaises(ChartValidationError):
            clean_config({"preset": "radar"}, [])
        with self.assertRaises(ChartValidationError):
            clean_config({"categoryOrder": "random"}, [])


SPEC = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    "title": "Temperature",
    "mark": "bar",
    "encoding": {"x": {"field": "month", "type": "ordinal"}, "y": {"field": "temp_c", "type": "quantitative"}},
}


class SpecValidationTests(unittest.TestCase):
    def test_none_means_no_spec(self):
        self.assertIsNone(clean_spec(None))

    def test_keeps_a_plain_vega_lite_spec_unchanged(self):
        self.assertEqual(clean_spec(SPEC), SPEC)

    def test_rejects_anything_that_loads_from_a_web_address(self):
        cases = {
            "data url": {**SPEC, "data": {"url": "https://example.com/x.csv"}},
            "layer url": {"layer": [{"data": {"url": "https://example.com/y.json"}, "mark": "line"}]},
            "lookup url": {**SPEC, "transform": [{"lookup": "a", "from": {"data": {"url": "https://e.com/z"}}}]},
            "image mark": {"mark": {"type": "image"}, "encoding": {"url": {"field": "u"}}},
        }
        for name, spec in cases.items():
            with self.subTest(name), self.assertRaises(ChartValidationError):
                clean_spec(spec)

    def test_rejects_other_schemas_and_non_specs(self):
        for bad in (
            ["not", "an", "object"],
            {"foo": 1},
            {"$schema": "https://vega.github.io/schema/vega/v5.json", "mark": "bar"},
        ):
            with self.subTest(str(bad)[:30]), self.assertRaises(ChartValidationError):
                clean_spec(bad)

    def test_bounds_depth_size_and_complexity(self):
        deep = {"mark": "bar"}
        cur = deep
        for _ in range(60):
            cur["n"] = {}
            cur = cur["n"]
        with self.assertRaises(ChartValidationError):
            clean_spec(deep)
        with self.assertRaises(ChartValidationError):
            clean_spec({"mark": "bar", "big": "x" * 250_000})
        with self.assertRaises(ChartValidationError):
            clean_spec({"mark": "bar", "many": [[0] for _ in range(21_000)]})


class ChartRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.c = cls.app.test_client()
        assert cls.app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")  # never a real database

    def make(self, **extra):
        r = self.c.post("/charts", json={"dataset": DATASET, "config": CONFIG, **extra})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()

    def test_create_is_shared_by_link_by_default(self):
        d = self.make()
        self.assertEqual(d["sharing"], "link")
        self.assertTrue(d["is_published"])
        self.assertEqual(d["public_url"], f"/charts/{d['public_slug']}")
        self.assertEqual(d["title"], "Average temperature")  # falls back to the chart title
        self.assertEqual(d["dataset"]["rows"][2]["temp_c"], None)

    def test_public_link_serves_the_chart_without_owner_details(self):
        d = self.make()
        r = self.c.get(f"/c/{d['public_slug']}")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["dataset"]["columns"], ["month", "temp_c"])
        self.assertEqual(body["config"]["categoryColumn"], "month")
        for private in ("chart_id", "owner_id", "sharing", "is_published"):
            self.assertNotIn(private, body)

    def test_private_chart_has_no_public_link(self):
        d = self.make(sharing="private")
        self.assertFalse(d["is_published"])
        self.assertIsNone(d["public_slug"])
        self.assertEqual(self.c.get("/c/anything").status_code, 404)

    def test_unpublishing_keeps_the_slug_so_resharing_restores_the_link(self):
        d = self.make()
        slug = d["public_slug"]
        off = self.c.put(f"/charts/{d['chart_id']}/sharing", json={"sharing": "private"}).get_json()
        self.assertEqual(off["sharing"], "private")
        self.assertEqual(self.c.get(f"/c/{slug}").status_code, 404)
        on = self.c.put(f"/charts/{d['chart_id']}/sharing", json={"sharing": "link"}).get_json()
        self.assertEqual(on["public_slug"], slug)
        self.assertEqual(self.c.get(f"/c/{slug}").status_code, 200)

    def test_public_is_accepted_and_reported(self):
        d = self.make(sharing="public")
        self.assertEqual(d["sharing"], "public")
        self.assertTrue(d["is_published"])
        self.assertEqual(self.c.get(f"/c/{d['public_slug']}").status_code, 200)

    def test_sharing_can_move_between_all_three_states(self):
        d = self.make(sharing="private")
        cid = d["chart_id"]
        for state in ("public", "link", "private", "public"):
            r = self.c.put(f"/charts/{cid}/sharing", json={"sharing": state})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            self.assertEqual(r.get_json()["sharing"], state)
        slug = self.c.get(f"/charts/{cid}").get_json()["public_slug"]
        self.assertEqual(self.c.get(f"/c/{slug}").status_code, 200)

    def test_unknown_sharing_value_is_a_400(self):
        r = self.c.post("/charts", json={"dataset": DATASET, "config": CONFIG, "sharing": "everyone"})
        self.assertEqual(r.status_code, 400)
        d = self.make()
        r = self.c.put(f"/charts/{d['chart_id']}/sharing", json={"sharing": "everyone"})
        self.assertEqual(r.status_code, 400)

    def test_public_charts_do_not_appear_in_the_stem_image_listing(self):
        # There is no chart listing yet; /repo must keep returning STEM images only.
        d = self.make(sharing="public")
        ids = {x["flowchart_id"] for x in self.c.get("/repo").get_json()}
        self.assertNotIn(d["chart_id"], ids)

    def test_update_revalidates_settings_against_new_columns(self):
        d = self.make()
        new = {"columns": ["when", "n"], "rows": [{"when": 1, "n": 2}]}
        r = self.c.put(f"/charts/{d['chart_id']}", json={"dataset": new, "title": "Renamed"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        body = r.get_json()
        self.assertEqual(body["title"], "Renamed")
        self.assertIsNone(body["config"]["valueColumn"])      # temp_c no longer exists
        self.assertEqual(body["config"]["preset"], "bar")      # unrelated settings survive

    def test_delete_removes_it_and_kills_the_link(self):
        d = self.make()
        self.assertEqual(self.c.delete(f"/charts/{d['chart_id']}").status_code, 200)
        self.assertEqual(self.c.get(f"/charts/{d['chart_id']}").status_code, 404)
        self.assertEqual(self.c.get(f"/c/{d['public_slug']}").status_code, 404)
        self.assertNotIn(d["chart_id"], {x["chart_id"] for x in self.c.get("/charts").get_json()})

    def test_someone_elses_chart_is_not_found(self):
        d = self.make()
        with self.app.app_context():
            row = Chart.query.filter_by(chart_id=d["chart_id"]).first()
            row.owner_id = "someone-else"
            db.session.commit()
        self.assertEqual(self.c.get(f"/charts/{d['chart_id']}").status_code, 404)
        self.assertEqual(self.c.put(f"/charts/{d['chart_id']}", json={"title": "x"}).status_code, 404)
        self.assertEqual(self.c.delete(f"/charts/{d['chart_id']}").status_code, 404)
        # ...but the shared link still works for anyone.
        self.assertEqual(self.c.get(f"/c/{d['public_slug']}").status_code, 200)

    def test_bad_input_is_a_400_with_a_message(self):
        r = self.c.post("/charts", json={"dataset": {"columns": ["a"], "rows": []}})
        self.assertEqual(r.status_code, 400)
        self.assertIn("rows", r.get_json()["error"])

    def test_list_omits_data(self):
        self.make()
        rows = self.c.get("/charts").get_json()
        self.assertTrue(rows)
        self.assertNotIn("dataset", rows[0])


    def test_spec_is_saved_and_travels_with_the_public_link(self):
        d = self.make(spec=SPEC)
        self.assertEqual(d["spec"], SPEC)
        pub = self.c.get(f"/c/{d['public_slug']}").get_json()
        self.assertEqual(pub["spec"], SPEC)

    def test_charts_without_a_spec_report_none(self):
        d = self.make()
        self.assertIsNone(d["spec"])
        self.assertIsNone(self.c.get(f"/c/{d['public_slug']}").get_json()["spec"])

    def test_bad_spec_is_a_400_and_nothing_is_saved(self):
        before = len(self.c.get("/charts").get_json())
        r = self.c.post("/charts", json={
            "dataset": DATASET, "config": CONFIG,
            "spec": {**SPEC, "data": {"url": "https://example.com/x.csv"}},
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("web address", r.get_json()["error"])
        self.assertEqual(len(self.c.get("/charts").get_json()), before)

    def test_update_can_replace_and_remove_the_spec(self):
        d = self.make(spec=SPEC)
        cid = d["chart_id"]
        other = {**SPEC, "mark": "line"}
        self.assertEqual(self.c.put(f"/charts/{cid}", json={"spec": other}).get_json()["spec"], other)
        self.assertEqual(self.c.put(f"/charts/{cid}", json={"title": "x"}).get_json()["spec"], other)  # untouched
        self.assertIsNone(self.c.put(f"/charts/{cid}", json={"spec": None}).get_json()["spec"])


class EventTypeTests(unittest.TestCase):
    def test_create_chart_event_is_registered(self):
        # The frontend logs this when someone picks Chart on /create; unknown types are a 400.
        self.assertEqual(EVENT_TYPES.get("Create_Chart"), "creation")


if __name__ == "__main__":
    unittest.main()
