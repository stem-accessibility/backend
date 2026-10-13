"""Vega-Lite specification and chart settings from an extracted table.

Built from templates, not generated: the same table and settings always give the same spec, the
data is inline (chart_validation.clean_spec rejects `url`), and every spec passes clean_spec.
Only the presets with a template here get a spec; for the others the caller keeps the table and
the settings and leaves the spec empty.
"""
from backend.chart_validation import PRESETS

SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
TEMPLATED = {"bar", "line", "pie"}


def build_config(columns, preset, title=None, x_label=None, y_label=None):
    """The chart settings the Charts page works from (whitelisted by clean_config)."""
    cfg = {"preset": preset if preset in PRESETS else None}
    if len(columns) >= 2:
        cfg["categoryColumn"] = columns[0]
        cfg["valueColumn"] = columns[1]
        if preset == "line":
            cfg["timeColumn"] = columns[0]
    cfg["title"] = title
    cfg["xLabel"] = x_label or (columns[0] if columns else None)
    cfg["yLabel"] = y_label or (columns[1] if len(columns) > 1 else None)
    return cfg


def build_spec(dataset, config):
    """A Vega-Lite spec for the first value column, or None when the preset has no template."""
    preset = config.get("preset")
    cat, val = config.get("categoryColumn"), config.get("valueColumn")
    if preset not in TEMPLATED or not cat or not val:
        return None
    values = [{cat: r.get(cat), val: r.get(val)} for r in dataset["rows"]]
    spec = {"$schema": SCHEMA, "data": {"values": values}}
    if config.get("title"):
        spec["title"] = config["title"]
    x_title, y_title = config.get("xLabel") or cat, config.get("yLabel") or val
    if preset == "pie":
        spec["mark"] = {"type": "arc"}
        spec["encoding"] = {
            "theta": {"field": val, "type": "quantitative", "title": y_title},
            "color": {"field": cat, "type": "nominal", "title": x_title},
        }
    else:
        sort_x = None if preset == "line" else None
        spec["mark"] = {"type": "line", "point": True} if preset == "line" else {"type": "bar"}
        spec["encoding"] = {
            "x": {"field": cat, "type": "ordinal", "title": x_title, "sort": sort_x},
            "y": {"field": val, "type": "quantitative", "title": y_title},
        }
        spec["encoding"]["x"] = {k: v for k, v in spec["encoding"]["x"].items() if v is not None}
    return spec
