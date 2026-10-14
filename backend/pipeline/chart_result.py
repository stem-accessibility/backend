"""Turn a ChartExtraction into what the Charts page loads: a validated table, settings and, for
bar, line and pie, a Vega-Lite spec. Shared by the job worker (signed-in users) and the guest
route, so both go through the same validators."""
from backend.chart_validation import ChartValidationError, clean_config, clean_dataset, clean_spec
from backend.pipeline.chart_extract import ChartExtraction
from backend.pipeline.chart_spec import build_config, build_spec


def build_chart_result(x: ChartExtraction):
    """Returns the result dict. Raises ChartValidationError when the table itself is unusable."""
    warnings = list(x.warnings)
    rows = [{c: (r[i] if i < len(r) else None) for i, c in enumerate(x.columns)} for r in x.rows]
    dataset = clean_dataset({"columns": x.columns, "rows": rows})

    config = clean_config(
        build_config(x.columns, x.chart_type, x.title, x.x_label, x.y_label), dataset["columns"]
    )
    spec = None
    try:
        spec = clean_spec(build_spec(dataset, config))
    except ChartValidationError as e:
        warnings.append(f"A chart specification could not be built: {e}")
    if x.chart_type is None:
        warnings.append("The chart type could not be worked out; choose it before using the chart.")

    return {
        "dataset": dataset,
        "config": config,
        "spec": spec,
        "extractor": x.extractor,                  # "unichart" or "llm"
        "sent_to_ai_model": x.extractor == "llm",  # lets the page say where the image went
        "values_are_estimated": x.values_are_estimated,
        "warnings": warnings,
    }
