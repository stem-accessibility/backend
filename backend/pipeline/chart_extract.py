"""Chart image -> table (and a suggested chart type).

Two interchangeable extractors sit behind `extract_chart`:

  unichart  a small local model run as a separate service (UNICHART_URL). No third party sees the
            image, no credits are spent.
  llm       a vision LLM through OpenRouter (llm.complete). Sends the image to a third party, so it
            only runs when the caller passes allow_llm=True.

UniChart is tried first. When its result looks incomplete (several series, a pie, nothing numeric)
and the person has agreed to the LLM, the LLM is used instead; if they have not, UniChart's result
is returned with a warning. Nothing here saves anything: the caller validates the result with
chart_validation before it is returned or stored.
"""
import json
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

MAX_ROWS = 5000
MAX_COLS = 100
MONTHS = {
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "january", "february", "march", "april", "june", "july", "august", "september", "october",
    "november", "december",
}
LLM_PROMPT = (
    "Extract the data behind this chart as a table. Reply with JSON only: "
    '{"chart_type": one of "bar", "line", "pie", "scatter", "histogram", "boxplot", "other", '
    '"title": string or null, "x_label": string or null, "y_label": string or null, '
    '"values_printed": true if the chart prints its values, else false, '
    '"columns": [first column is the category or x label, then one column per series], '
    '"rows": [[...], ...]}. Use numbers (no units or % signs) for values. '
    "If values are not printed, estimate them from the axis as precisely as you can."
)


class ConsentRequired(Exception):
    """The chosen extractor would send the image to a third party and the person has not agreed."""


class ExtractionError(Exception):
    pass


@dataclass
class ChartExtraction:
    columns: List[str]
    rows: List[list]
    extractor: str                       # "unichart" or "llm"
    chart_type: Optional[str] = None     # one of chart_validation.PRESETS, or None
    title: Optional[str] = None
    x_label: Optional[str] = None
    y_label: Optional[str] = None
    values_are_estimated: bool = True    # assume approximate unless the chart printed its values
    warnings: List[str] = field(default_factory=list)


# ---- parsing -------------------------------------------------------------------------------

def parse_number(value):
    """123, '1,200', '45%', '$3.5' -> float; anything without a number -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"-?\d[\d,]*\.?\d*|-?\.\d+", str(value))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_unichart_table(raw: str):
    """UniChart returns text: rows separated by newline, '&' or '<0x0A>', cells by '|'."""
    raw = (raw or "").replace("<0x0A>", "\n").replace("<0x0a>", "\n")
    lines = [l for l in re.split(r"\n|&", raw) if l.strip()]
    table = [[c.strip() for c in l.split("|")] for l in lines]
    if len(table) < 2:
        raise ExtractionError("the chart reader returned no table")
    return table[0], table[1:]


def _clean_columns(names, width):
    out, seen = [], set()
    for i in range(width):
        n = (str(names[i]).strip() if i < len(names) else "") or f"Column {i + 1}"
        base, k = n, 2
        while n in seen:
            n, k = f"{base} {k}", k + 1
        seen.add(n)
        out.append(n)
    return out


def _clean_label(value) -> str:
    """A category label as text. The reader prints whole-number axis labels as floats ("2004.0",
    "3.0"); the axis shows "2004" and "3", so drop a trailing ".0". Other labels are untouched."""
    text = str(value).strip()
    return re.sub(r"^(-?\d+)\.0+$", r"\1", text)


def _normalise(columns, rows):
    """Rectangular table, unique column names, numbers where a cell holds one (first column stays
    text, since it holds labels such as years)."""
    rows = [r for r in rows if isinstance(r, (list, tuple)) and any(str(c).strip() for c in r)]
    width = min(max([len(columns)] + [len(r) for r in rows] or [0]), MAX_COLS)
    cols = _clean_columns(list(columns), width)
    out = []
    for r in rows[:MAX_ROWS]:
        r = list(r) + [None] * (width - len(r))
        cells = [_clean_label(r[0]) if r[0] is not None else ""]
        for v in r[1:width]:
            n = parse_number(v)
            if n is not None:
                cells.append(n)
            else:
                text = "" if v is None else str(v).strip()
                cells.append(text or None)
        out.append(cells)
    return cols, out


def suggest_chart_type(columns, rows):
    """A cheap, no-LLM suggestion the person confirms: ordered categories (years, months) -> line,
    otherwise bar. Returns None when there is nothing to go on."""
    if not rows:
        return None
    labels = [str(r[0]).strip().lower() for r in rows]
    yearish = all(re.fullmatch(r"(19|20)\d\d(\.0)?", l) for l in labels)
    monthish = all(l.split()[0].rstrip(".") in MONTHS for l in labels if l)
    return "line" if (yearish or monthish) else "bar"


# ---- backends ------------------------------------------------------------------------------

def extract_with_unichart(image_path: str) -> ChartExtraction:
    url = os.environ.get("UNICHART_URL")
    if not url:
        raise ExtractionError("the built-in chart reader is not configured")
    import requests  # imported here so the module loads where requests is unavailable

    headers = {}
    if os.environ.get("UNICHART_TOKEN"):
        headers["X-Service-Token"] = os.environ["UNICHART_TOKEN"]
    with open(image_path, "rb") as f:
        try:
            resp = requests.post(url.rstrip("/") + "/extract", files={"image": f},
                                 headers=headers, timeout=120)
            resp.raise_for_status()
            raw = resp.json().get("table", "")
        except Exception as e:
            raise ExtractionError(f"the built-in chart reader failed: {str(e)[:200]}")
    header, body = parse_unichart_table(raw)
    columns, rows = _normalise(header, body)
    return ChartExtraction(
        columns=columns, rows=rows, extractor="unichart",
        chart_type=suggest_chart_type(columns, rows),
    )


def extract_with_llm(image_path: str) -> ChartExtraction:
    from backend import llm

    reply = llm.complete(LLM_PROMPT, model=llm.MODEL_EDGES, image_path=image_path, json_mode=True,
                         temperature=0, max_tokens=4000)
    try:
        d = json.loads(reply)
        header, body = d["columns"], d["rows"]
    except Exception:
        raise ExtractionError("the AI model did not return a table")
    columns, rows = _normalise(header, body)
    ctype = d.get("chart_type")
    return ChartExtraction(
        columns=columns, rows=rows, extractor="llm",
        chart_type=ctype if ctype in {"bar", "line", "pie", "scatter", "histogram", "boxplot"}
        else suggest_chart_type(columns, rows),
        title=d.get("title") or None, x_label=d.get("x_label") or None,
        y_label=d.get("y_label") or None,
        values_are_estimated=not bool(d.get("values_printed")),
    )


# ---- routing -------------------------------------------------------------------------------

def extraction_options():
    """What this deployment can do, so the page can show only real choices.
    local: the built-in reader (UniChart) is configured; no third party sees the image.
    llm:   the AI model (Gemini via OpenRouter) is configured; it needs the person's agreement."""
    return {
        "local": bool(os.environ.get("UNICHART_URL")),
        "llm": bool(
            os.environ.get("GEMINI_API_KEY") or os.environ.get("ACCESSFLOW_OPENROUTER_API_KEY")
        ),
    }


def looks_incomplete(x: ChartExtraction) -> Optional[str]:
    """Why a local result probably needs the LLM, or None. The evaluation found the local reader
    reliable on single-series charts and weak on several series and on pies."""
    if len(x.rows) < 2:
        return "only one row was read"
    if len(x.columns) > 2:
        return "the chart appears to have several series, or it may be a pie chart, which the built-in reader often misreads"
    numeric = sum(1 for r in x.rows for v in r[1:] if isinstance(v, (int, float)))
    if numeric == 0:
        return "no numbers were read"
    return None


def extract_chart(image_path: str, *, allow_llm: bool, mode: Optional[str] = None) -> ChartExtraction:
    """mode: "unichart" (default when UNICHART_URL is set) or "llm". allow_llm is the person's
    explicit choice; it is never assumed."""
    mode = mode or os.environ.get("CHART_EXTRACTOR") or ("unichart" if os.environ.get("UNICHART_URL") else "llm")

    if mode == "llm":
        if not allow_llm:
            raise ConsentRequired("sending this image to the AI model needs your agreement")
        return extract_with_llm(image_path)

    local = extract_with_unichart(image_path)
    why = looks_incomplete(local)
    if why is None:
        return local
    if allow_llm:
        try:
            return extract_with_llm(image_path)
        except (ExtractionError, RuntimeError) as e:
            local.warnings.append(f"The AI model could not read this chart ({e}); showing the built-in reader's result, which may be incomplete.")
            return local
    local.warnings.append(
        f"The built-in reader may be incomplete here: {why}. Check the table against the chart, "
        "or choose to use the AI model."
    )
    return local
