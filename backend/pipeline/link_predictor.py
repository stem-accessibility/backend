# link_prediction.py

from dotenv import load_dotenv
load_dotenv()

import re
import json

from backend import llm

def clean_gemini_response(response_text):
    # Extract JSON from markdown code block
    match = re.search(r"```json\s*(\[.*?\])\s*```", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Fallback: try to match just any JSON list
    match = re.search(r"(\[\s*{.*?}\s*\])", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    return response_text.strip()  # last resort

def extract_json(raw_text):
    # Match content inside ```json ... ```
    match = re.search(r"```(?:json)?\n(.*?)\n```", raw_text, re.DOTALL)
    if not match:
        raise ValueError("No valid JSON block found")
    
    json_str = match.group(1)
    return json.loads(json_str)

base_prompt = """
You are given a flowchart image and two lists:

1. Nodes: each has an `id`, a `label`, and `coordinates` (bounding box)
2. Edges: each has an `id`, a `coordinates` list (line segment), and optional `arrowheads`

Each edge is missing its `source` and `destination` node IDs.

Your task:
- Use spatial layout and arrowhead direction to infer `source` and `destination` for each edge
- You may use node `labels` to help disambiguate, but prioritize geometry and layout

Output ONLY a JSON array of edge mappings.
Return format:

```json
[
  {"edge_id": "edge_1", "source": "node_3", "destination": "node_4"},
  {"edge_id": "edge_2", "source": "node_1", "destination": "node_2"}
]
```

Do not explain anything.
Do not return any text outside the JSON code block.

"""

base_prompt2 = """

You are given a flowchart image and a list of detected nodes.

Each node has:
- id
- label
- shape
- coordinates (bounding box)

Your task:
Infer the directed connections between nodes.

Important rules:

1) Only use the nodes provided.
2) Do NOT invent new nodes or edges.
3) Edges must connect existing node IDs only.
4) Use spatial layout and visual flow direction:
   - Prefer top-to-bottom flow
   - If horizontal, use left-to-right
5) Use node labels and diagram structure to resolve ambiguity.
6) Do NOT attempt to detect or reason about individual line segments.

Output ONLY a JSON array of edges in this exact format:

[
  {"edge_id": "edge_1", "source": "node_3", "destination": "node_4"},
  {"edge_id": "edge_2", "source": "node_1", "destination": "node_2"}
]

Edge IDs must be deterministic:
- Sort edges by source node reading order, then destination node.
- Name them edge_1, edge_2, edge_3, ...

Do not include arrowheads, styles, or labels.
Do not explain anything.
Return only JSON.


"""

def predict_links_from_gemini(json_data: dict, image_path: str) -> dict:
    import json

    json_str = json.dumps(json_data, indent=4)

    try:
        response_text = llm.complete(
            base_prompt + json_str, model=llm.MODEL_EDGES, image_path=image_path
        )

        # 🔥 Clean response before parsing
        cleaned_text = clean_gemini_response(response_text)

        return json.loads(cleaned_text)

    except Exception as e:
        print(f"❌ Gemini link prediction failed for {image_path}: {e}")
        return json_data  # fallback

def predict_links_from_gemini_minimal(nodes: list, edges: list, image_path: str) -> list:

    try:
        # Compose minimal structure with labels
        trimmed = {
            "nodes": [
                {
                    "id": node["id"],
                    "coordinates": node["coordinates"],
                    "label": node.get("label", "")
                }
                for node in nodes
            ],
            "edges": [
                {
                    "id": edge["id"],
                    "coordinates": edge["coordinates"],
                    "arrowheads": edge.get("arrowheads", [])
                }
                for edge in edges
            ]
        }

        response_text = llm.complete(
            base_prompt + "\n\n" + json.dumps(trimmed, separators=(",", ":")),
            model=llm.MODEL_EDGES,
            image_path=image_path,
        )

        print("📤 Raw Gemini response:\n")
        print(response_text)
        

        # 🔥 Clean response before parsing
        cleaned_text = extract_json(response_text)
        print("🧼 Cleaned response:\n")
        print(cleaned_text)

        return cleaned_text

    except Exception as e:
        print(f"❌ Gemini link prediction failed for {image_path}: {e}")
        return []  # fallback

def predict_links_from_gemini_minimal2(nodes: list, edges: list, image_path: str) -> list:

    try:
        # Compose minimal structure with labels
        trimmed = {
            "nodes": [
                {
                    "id": node["id"],
                    "coordinates": node["coordinates"],
                    "label": node.get("label", "")
                }
                for node in nodes
            ]
        }

        response_text = llm.complete(
            base_prompt + "\n\n" + json.dumps(trimmed, separators=(",", ":")),
            model=llm.MODEL_EDGES,
            image_path=image_path,
        )

        print("📤 Raw Gemini response:\n")
        print(response_text)
        

        # 🔥 Clean response before parsing
        cleaned_text = extract_json(response_text)
        print("🧼 Cleaned response:\n")
        print(cleaned_text)

        return cleaned_text

    except Exception as e:
        print(f"❌ Gemini link prediction failed for {image_path}: {e}")
        return []  # fallback

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




def call_gemini_edges(image_path: str, nodes: list[dict]) -> tuple[str | None, str | None]:
    try:
        text = llm.complete(
            build_edge_prompt(nodes),
            model=llm.MODEL_EDGES,
            image_path=str(image_path),
        )
        return text, None
    except Exception as e:
        return None, str(e)[:500]


def parse_gemini_edge_response(raw: str | None) -> tuple[dict | None, str | None]:
    if raw is None:
        return None, "No response from Gemini"

    text = raw.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()

    try:
        parsed = json.loads(text)

        if isinstance(parsed, list):
            parsed = {"edges": parsed}

        if not isinstance(parsed, dict):
            return None, "Gemini returned non-dict JSON"

        return parsed, None

    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"


def infer_edges_from_nodes_and_image(image_path: str, nodes: list[dict]) -> list[dict]:
    raw, call_err = call_gemini_edges(image_path, nodes)
    parsed, parse_err = parse_gemini_edge_response(raw)

    if parsed is None:
        raise RuntimeError(f"VLM edge inference failed: {call_err or parse_err}")

    return parsed.get("edges", [])