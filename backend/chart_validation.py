"""Validation for chart payloads. Pure (no Flask, no database) so it can be unit tested.

A chart is a table plus a few display settings. The server does not interpret the data; it only
makes sure what is stored is a bounded, well-formed table and a whitelisted config, because the
public page will load and render whatever is saved here.
"""
import json
import math

MAX_ROWS = 5000
MAX_COLUMNS = 100
MAX_TEXT = 500          # one cell, column name, label or title
MAX_TITLE = 255
MAX_BYTES = 2_000_000   # serialized dataset
MAX_SPEC_BYTES = 200_000
MAX_SPEC_DEPTH = 40
MAX_SPEC_NODES = 20_000

PRESETS = {"line", "bar", "histogram", "scatter_spatial", "scatter_temporal", "boxplot", "pie"}
CATEGORY_ORDERS = {"data", "alpha", "value-asc", "value-desc"}
COLUMN_FIELDS = ("timeColumn", "valueColumn", "categoryColumn")
TEXT_FIELDS = ("title", "xLabel", "yLabel")


# A Vega-Lite specification has at least one of these at its top level.
SPEC_VIEW_KEYS = {"mark", "layer", "hconcat", "vconcat", "concat", "facet", "repeat", "spec"}


class ChartValidationError(ValueError):
    pass


def _text(value, what, limit=MAX_TEXT):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ChartValidationError(f"{what} must be text")
    value = value.strip()
    if len(value) > limit:
        raise ChartValidationError(f"{what} is longer than {limit} characters")
    return value or None


def _cell(value):
    if value is None or isinstance(value, str):
        return _text(value, "a cell")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    raise ChartValidationError("cells must be text, numbers or empty")


def clean_dataset(raw):
    """Returns {"columns": [str], "rows": [dict], "name": str|None}."""
    if not isinstance(raw, dict):
        raise ChartValidationError("dataset must be an object with columns and rows")

    cols_in = raw.get("columns")
    rows_in = raw.get("rows")
    if not isinstance(cols_in, list) or not cols_in:
        raise ChartValidationError("dataset.columns must be a non-empty list")
    if not isinstance(rows_in, list) or not rows_in:
        raise ChartValidationError("dataset.rows must be a non-empty list")
    if len(cols_in) > MAX_COLUMNS:
        raise ChartValidationError(f"a chart can have at most {MAX_COLUMNS} columns")
    if len(rows_in) > MAX_ROWS:
        raise ChartValidationError(f"a chart can have at most {MAX_ROWS} rows")

    columns = []
    for c in cols_in:
        name = _text(c, "a column name")
        if not name:
            raise ChartValidationError("column names cannot be empty")
        if name in columns:
            raise ChartValidationError(f"duplicate column name: {name}")
        columns.append(name)

    rows = []
    for r in rows_in:
        if not isinstance(r, dict):
            raise ChartValidationError("each row must be an object")
        rows.append({c: _cell(r.get(c)) for c in columns})

    cleaned = {"columns": columns, "rows": rows, "name": _text(raw.get("name"), "dataset.name", MAX_TITLE)}
    if len(json.dumps(cleaned, ensure_ascii=False)) > MAX_BYTES:
        raise ChartValidationError("the data is too large to save")
    return cleaned


def clean_config(raw, columns):
    """Keeps only known settings. A column the data does not have is dropped, not kept dangling."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ChartValidationError("config must be an object")

    out = {}
    preset = raw.get("preset")
    if preset is not None:
        if preset not in PRESETS:
            raise ChartValidationError(f"unknown chart type: {preset}")
        out["preset"] = preset

    for key in COLUMN_FIELDS:
        v = _text(raw.get(key), key)
        out[key] = v if v in columns else None

    for key in TEXT_FIELDS:
        out[key] = _text(raw.get(key), key, MAX_TITLE if key == "title" else MAX_TEXT)

    order = raw.get("categoryOrder")
    if order is not None:
        if order not in CATEGORY_ORDERS:
            raise ChartValidationError(f"unknown category order: {order}")
        out["categoryOrder"] = order
    return out


def clean_spec(raw):
    """An optional Vega-Lite specification, stored so a shared link describes the chart the way its
    author did. This is deliberately a narrow door: the JSON is kept as-is (never executed here),
    but only if it is a bounded Vega-Lite object that cannot ask a viewer's browser to fetch
    anything. Returns the spec, or None when there is none.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ChartValidationError("spec must be a JSON object")

    # Walk iteratively: a hostile, deeply nested document must not be able to blow the stack here.
    stack = [(raw, 1)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if depth > MAX_SPEC_DEPTH:
            raise ChartValidationError(f"spec is nested more than {MAX_SPEC_DEPTH} levels deep")
        if nodes > MAX_SPEC_NODES:
            raise ChartValidationError("spec is too complex to save")
        if isinstance(node, dict):
            if "url" in node:
                # data.url, lookup sources and image marks all load from a web address.
                raise ChartValidationError(
                    "spec cannot refer to web addresses ('url'); include the data or use the uploaded table"
                )
            stack.extend((v, depth + 1) for v in node.values())
        elif isinstance(node, list):
            stack.extend((v, depth + 1) for v in node)

    schema = raw.get("$schema")
    if isinstance(schema, str) and "vega-lite" not in schema.lower():
        raise ChartValidationError("only Vega-Lite specifications are supported")
    if not SPEC_VIEW_KEYS & raw.keys():
        raise ChartValidationError("spec is not a Vega-Lite specification (no mark or view)")

    if len(json.dumps(raw, ensure_ascii=False)) > MAX_SPEC_BYTES:
        raise ChartValidationError(f"spec is larger than {MAX_SPEC_BYTES // 1000} KB")
    return raw

