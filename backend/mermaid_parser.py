# backend/mermaid_parser.py
import re
from typing import Dict, List, Optional, Tuple

NODE_ID_RE = re.compile(r'^([A-Za-z0-9_:\-]+)')

PIPE_EDGE_RE = re.compile(r'^\s*(.+?)\s*-->\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$')     # A -->|label| B
LABEL_EDGE_RE = re.compile(r'^\s*(.+?)\s*--\s*([^-\n]+?)\s*-->\s*(.+?)\s*$')      # A -- label --> B
PLAIN_EDGE_RE = re.compile(r'^\s*(.+?)\s*-->\s*(.+?)\s*$')                        # A --> B

def _parse_node_token(token: str) -> Optional[Tuple[str, str]]:
    """
    token examples:
      A[Start], B{Decision}, C((Circle)), D(Label)
    returns (id, label)
    """
    t = token.strip().strip(';').strip()
    m = NODE_ID_RE.match(t)
    if not m:
        return None

    node_id = m.group(1)
    rest = t[len(node_id):].strip()

    # ((Label))
    mm = re.search(r'\(\((.*?)\)\)', rest)
    if mm:
        return node_id, mm.group(1).strip()

    # [Label]
    mm = re.search(r'\[(.*?)\]', rest)
    if mm:
        return node_id, mm.group(1).strip()

    # {Label}
    mm = re.search(r'\{(.*?)\}', rest)
    if mm:
        return node_id, mm.group(1).strip()

    # (Label)
    mm = re.search(r'\((.*?)\)', rest)
    if mm:
        return node_id, mm.group(1).strip()

    # fallback
    return node_id, node_id

def parse_mermaid_flowchart_td(mermaid: str) -> Dict[str, List[Dict]]:
    """
    Minimal parser for Mermaid `flowchart TD` (and TB/LR/RL headers ignored).
    Returns coordinate-free graph:
      { nodes: [{id,label}], edges: [{source,destination,label?}] }
    """
    if not isinstance(mermaid, str) or not mermaid.strip():
        return {"nodes": [], "edges": []}

    lines: List[str] = []
    for raw in mermaid.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("%%"):
            continue
        # Ignore header lines like "flowchart TD" or "graph TD"
        if line.lower().startswith(("flowchart", "graph")):
            continue
        lines.append(line.rstrip(";").strip())

    nodes: Dict[str, str] = {}
    edges: List[Dict] = []

    def add_node(token: str):
        parsed = _parse_node_token(token)
        if not parsed:
            return
        nid, label = parsed
        if nid not in nodes or nodes[nid] == nid:
            nodes[nid] = label

    for line in lines:
        # A -->|label| B
        m = PIPE_EDGE_RE.match(line)
        if m:
            left, label, right = m.group(1), m.group(2), m.group(3)
            add_node(left); add_node(right)
            src = _parse_node_token(left)[0]
            dst = _parse_node_token(right)[0]
            edges.append({"source": src, "destination": dst, "label": label.strip()})
            continue

        # A -- label --> B
        m = LABEL_EDGE_RE.match(line)
        if m:
            left, label, right = m.group(1), m.group(2), m.group(3)
            add_node(left); add_node(right)
            src = _parse_node_token(left)[0]
            dst = _parse_node_token(right)[0]
            edges.append({"source": src, "destination": dst, "label": label.strip()})
            continue

        # A --> B
        m = PLAIN_EDGE_RE.match(line)
        if m:
            left, right = m.group(1), m.group(2)
            add_node(left); add_node(right)
            src = _parse_node_token(left)[0]
            dst = _parse_node_token(right)[0]
            edges.append({"source": src, "destination": dst})
            continue

        # stand-alone node declaration: A[Start]
        add_node(line)

    node_list = [{"id": nid, "label": label} for nid, label in nodes.items()]
    return {"nodes": node_list, "edges": edges}
