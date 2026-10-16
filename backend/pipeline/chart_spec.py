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


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _value_columns(dataset, cat, val):
    """The chosen value column first, then every other column that holds numbers."""
    others = [
        c for c in dataset["columns"]
        if c not in (cat, val) and any(_is_number(r.get(c)) for r in dataset["rows"])
    ]
    return [val] + others


def _unused_name(base, taken):
    name = base
    while name in taken:
        name += "_"
    return name


def build_spec(dataset, config):
    """A Vega-Lite spec, or None when the preset has no template.

    A bar or line chart of a table with several numeric columns shows every one of them (grouped
    bars or one line each), so a second series is not silently dropped. A pie shows the first value
    column only, since a pie cannot hold several series."""
    preset = config.get("preset")
    cat, val = config.get("categoryColumn"), config.get("valueColumn")
    if preset not in TEMPLATED or not cat or not val:
        return None
    series = _value_columns(dataset, cat, val) if preset in ("bar", "line") else [val]
    if len(series) > 1:
        return _build_multi_series_spec(dataset, config, cat, series)
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
        sort_x = None
        spec["mark"] = {"type": "line", "point": True} if preset == "line" else {"type": "bar"}
        spec["encoding"] = {
            "x": {"field": cat, "type": "ordinal", "title": x_title, "sort": sort_x},
            "y": {"field": val, "type": "quantitative", "title": y_title},
        }
        spec["encoding"]["x"] = {k: v for k, v in spec["encoding"]["x"].items() if v is not None}
    return spec


def _build_multi_series_spec(dataset, config, cat, series):
    """Grouped bars or several lines: the value columns are folded into one (series, value) pair of
    fields, so the legend names the columns and nothing is dropped."""
    preset = config.get("preset")
    taken = set(dataset["columns"])
    series_field = _unused_name("Series", taken)
    value_field = _unused_name("Value", taken | {series_field})
    values = [{c: r.get(c) for c in [cat, *series]} for r in dataset["rows"]]
    spec = {
        "$schema": SCHEMA,
        "data": {"values": values},
        "transform": [{"fold": list(series), "as": [series_field, value_field]}],
    }
    if config.get("title"):
        spec["title"] = config["title"]
    x_title = config.get("xLabel") or cat
    # The default y label is the first series' name, which would mislabel the others.
    y_label = config.get("yLabel")
    y_title = y_label if y_label and y_label != series[0] else "Value"
    encoding = {
        "x": {"field": cat, "type": "ordinal", "title": x_title},
        "y": {"field": value_field, "type": "quantitative", "title": y_title},
        "color": {"field": series_field, "type": "nominal", "title": "Series"},
    }
    if preset == "line":
        spec["mark"] = {"type": "line", "point": True}
    else:
        spec["mark"] = {"type": "bar"}
        encoding["xOffset"] = {"field": series_field}
    spec["encoding"] = encoding
    return spec
