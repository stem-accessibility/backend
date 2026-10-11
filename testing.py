"""
test_od_nodes_vlm_edges.py

Pipeline variant: OD-detected nodes + VLM-only edge inference.
Skips all edge detection, consolidation, arrowhead association, and OCR edge label assignment.
Passes only OD nodes + image to the VLM and asks it to infer all edges.

This isolates the question: how much does OD node quality (vs GT nodes) affect VLM edge inference?

Usage:
    python test_od_nodes_vlm_edges.py --images test-images --output test-json-od-nodes-vlm-edges
"""

import os
import json
import csv
import time
import argparse
from pathlib import Path
from glob import glob

from backend.pipeline.detect import run_detection
from backend.pipeline.ocr import google_ocr
from backend.pipeline.parse import assign_text_to_objects
from google import genai
from google.genai import types

# -------- CONFIG --------
MODEL_NAME    = "gemini-2.5-flash"
MAX_RETRIES   = 3
RETRY_DELAY   = 5.0
SLEEP_BETWEEN = 1.0
OVERWRITE     = False
# ------------------------

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
NODE_CLASSES = {"rectangle", "circle", "diamond", "ellipse", "parallelogram", "hexagon", "cylinder"}


def build_edge_prompt(nodes: list) -> str:
    return f"""You are a flowchart edge extractor. You are given a flowchart image and the already-extracted list of nodes with their ids, labels, and bounding box coordinates. Your job is to identify all edges (connections) between those nodes.

Return ONLY valid JSON. No explanation, no markdown code fences, no preamble. Your entire response must be parseable by JSON.parse().

Here are the nodes already extracted from this diagram:
{json.dumps(nodes, ensure_ascii=False, indent=2)}

Use these exact node ids when specifying edge sources and destinations. Do not invent new node ids.

Return a JSON object with this exact schema:

{{
  "edges": [
    {{
      "id": "edge__<type>__<source_id>__<destination_id>__ah_<arrowheads>__i_<index>",
      "source": "<node id from the list above>",
      "destination": "<node id from the list above>",
      "label": "<edge label text, or empty string if none>",
      "type": "<solid or dashed>",
      "arrowheads": ["<see arrowhead options below>"]
    }}
  ]
}}

EDGE RULES:
- id: construct as "edge__<type>__<source_id>__<destination_id>__ah_<arrowheads>__i_<index>" where:
    - type is "solid" or "dashed"
    - arrowheads is a hyphen-joined list of arrowhead positions present, e.g. "end" or "start-end"
    - index is the 0-based position of this edge in the edges array
  Example: "edge__solid__node_1__node_2__ah_end__i_0"
- source: the node id where the edge originates
- destination: the node id where the edge terminates
- label: exact text on the edge (e.g. "Yes", "No", a condition). Use empty string if none.
- type: "solid" if the edge line is solid, "dashed" if the edge line is dashed or dotted
- arrowheads: a list of which ends of the edge have arrowheads. Use "end" if only the destination end
  has an arrowhead (most common), "start" if only the source end, ["start","end"] if both.
  Use [] if no arrowheads are present.

GENERAL RULES:
- Use the node coordinates to help locate each node in the image and trace connections between them
- Include every directed edge visible in the diagram, following the direction of the arrow
- Only use node ids from the provided node list — do not create new ids
- Do not infer or hallucinate any edges not visually present in the image
- If two nodes are visually connected by a line with no arrowhead, still include the edge with arrowheads set to []
- Do not include a "nodes" key in your response — return only the "edges" array"""


def call_gemini_edges(client, img_path: Path, nodes_json: dict) -> tuple[str | None, str | None]:
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",  ".webp": "image/webp",
        ".bmp": "image/bmp",  ".tiff": "image/tiff",
    }
    mime = mime_map.get(img_path.suffix.lower(), "image/png")
    with open(img_path, "rb") as f:
        image_bytes = f.read()
 
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
                types.Part.from_text(text=build_edge_prompt(nodes_json)),
            ],
        )
    ]
    generate_content_config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            thinking_budget=-1,
        ),
    )
 
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            full_text = ""
            for chunk in client.models.generate_content_stream(
                model=MODEL_NAME,
                contents=contents,
                config=generate_content_config,
            ):
                if chunk.text:
                    full_text += chunk.text
            return full_text, None
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
            else:
                return None, str(e)[:500]
 

def parse_response(raw: str | None) -> tuple[dict | None, str | None]:
    if raw is None:
        return None, "No response"
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    try:
        parsed = json.loads(text)
        # handle bare list vs {"edges": [...]}
        if isinstance(parsed, list):
            return {"edges": parsed}, None
        return parsed, None
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"


def process_image(img_path: Path, client) -> dict:
    """
    Stripped pipeline:
      1. YOLO detection (nodes only — we ignore detected edges entirely)
      2. OCR
      3. Assign OCR text to nodes
      4. Pass nodes + image to VLM → get edges
      5. Return merged {nodes, edges}
    """
    # Step 1: Detect with YOLO
    yolo_objects, img_width, img_height = run_detection(str(img_path))

    # Step 2: OCR
    ocr_texts = google_ocr(str(img_path))

    # Step 3: Assign OCR text to node objects only
    node_objects = [obj for obj in yolo_objects if obj["class_name"] in NODE_CLASSES]
    node_objects = assign_text_to_objects(node_objects, ocr_texts)

    # Step 4: Build node list with sequential ids
    nodes = []
    for i, obj in enumerate(node_objects, start=1):
        obj["id"] = f"node_{i}"
        nodes.append({
            "id": obj["id"],
            "label": obj.get("label", ""),
            "shape": obj["class_name"],
            "coordinates": obj["bounding_box"],
        })

    # Step 5: Call VLM for edges
    raw, call_err = call_gemini_edges(client, img_path, nodes)
    parsed, parse_err = parse_response(raw)

    err = call_err or parse_err
    if parsed is None:
        raise RuntimeError(f"VLM edge inference failed: {err}")

    edges = parsed.get("edges", [])

    return {"nodes": nodes, "edges": edges}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=str, default="test-images")
    parser.add_argument("--output", type=str, default="od-nodes-vlm-edges-flash")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable not set.")
    client = genai.Client(api_key=api_key)

    image_dir = Path(args.images)
    out_dir   = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_csv   = out_dir / "_timings.csv"

    images = sorted([p for p in image_dir.iterdir()
                     if p.is_file() and p.suffix.lower() in IMG_EXTS])
    print(f"Found {len(images)} images in {image_dir}\n")

    log_exists = log_csv.exists()
    with open(log_csv, "a", newline="", encoding="utf-8") as cf:
        writer = csv.DictWriter(cf, fieldnames=[
            "id", "image_name", "status", "model",
            "latency_s", "node_count", "edge_count", "error"
        ])
        if not log_exists:
            writer.writeheader()

        total_t0 = time.time()
        ok = fail = skipped = 0
        latencies = []

        for img_path in images:
            img_id   = img_path.stem
            out_path = out_dir / f"{img_id}.json"

            if out_path.exists() and not OVERWRITE:
                skipped += 1
                continue

            t0 = time.time()
            try:
                result = process_image(img_path, client)
                elapsed = time.time() - t0

                node_count = len(result.get("nodes", []))
                edge_count = len(result.get("edges", []))

                out_obj = {
                    "_meta": {
                        "id": img_id,
                        "image_name": img_path.name,
                        "model": MODEL_NAME,
                        "pipeline": "od_nodes_vlm_edges",
                        "latency_s": round(elapsed, 4),
                        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    },
                    "mermaid_json": result,
                }

                with open(out_path, "w", encoding="utf-8") as jf:
                    json.dump(out_obj, jf, ensure_ascii=False, indent=2)

                ok += 1
                latencies.append(elapsed)
                print(f"✅ {img_id} ({elapsed:.2f}s) — {node_count} nodes, {edge_count} edges")
                writer.writerow({
                    "id": img_id, "image_name": img_path.name,
                    "status": "ok", "model": MODEL_NAME,
                    "latency_s": round(elapsed, 4),
                    "node_count": node_count, "edge_count": edge_count, "error": ""
                })

            except Exception as e:
                elapsed = time.time() - t0
                fail += 1
                err = str(e)[:500]
                print(f"❌ {img_id} ({elapsed:.2f}s) {err}")
                writer.writerow({
                    "id": img_id, "image_name": img_path.name,
                    "status": "fail", "model": MODEL_NAME,
                    "latency_s": round(elapsed, 4),
                    "node_count": "", "edge_count": "", "error": err
                })

            if SLEEP_BETWEEN > 0:
                time.sleep(SLEEP_BETWEEN)

        total_elapsed = time.time() - total_t0

    def pct(x, d): return 0.0 if d == 0 else 100.0 * x / d
    n_attempted = ok + fail
    if latencies:
        lat_sorted = sorted(latencies)
        p50 = lat_sorted[len(lat_sorted) // 2]
        p90 = lat_sorted[int(0.9 * (len(lat_sorted) - 1))]
        p95 = lat_sorted[int(0.95 * (len(lat_sorted) - 1))]
        mx, mn = max(lat_sorted), min(lat_sorted)
    else:
        p50 = p90 = p95 = mx = mn = None

    print("\n=== Batch Summary ===")
    print(f"Pipeline     : OD nodes → VLM edges")
    print(f"Output dir   : {out_dir}")
    print(f"Model        : {MODEL_NAME}")
    print(f"Attempted    : {n_attempted} | OK: {ok} | FAIL: {fail} | Skipped: {skipped}")
    print(f"Success rate : {pct(ok, n_attempted):.1f}%")
    print(f"Wall time    : {total_elapsed:.2f}s ({total_elapsed/60:.2f} min)")
    if p50 is not None:
        print(f"Latency (s)  : min={mn:.2f} p50={p50:.2f} p90={p90:.2f} p95={p95:.2f} max={mx:.2f}")


if __name__ == "__main__":
    main()