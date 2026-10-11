# descriptions/deterministic_longdesc.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional
from collections import defaultdict, deque

Json = Dict[str, Any]


# -------------------------
# Data model
# -------------------------
@dataclass
class Node:
  id: str
  label: str
  x: float
  y: float
  shape: str = "rectangle"


@dataclass
class Edge:
  source: str
  destination: str
  label: str


# -------------------------
# Normalization helpers
# -------------------------
def _node_xy(n: Json) -> Tuple[float, float]:
  """
  Your nodes have coordinates like: [[x1,y1],[x2,y2]].
  We use the top-left corner for ordering.
  """
  coords = n.get("coordinates") or []
  if (
    isinstance(coords, list)
    and len(coords) > 0
    and isinstance(coords[0], (list, tuple))
    and len(coords[0]) >= 2
  ):
    x, y = coords[0][0], coords[0][1]
    try:
      return float(x), float(y)
    except Exception:
      return 0.0, 0.0
  return 0.0, 0.0


def normalize_flow_json(diagram_json: Json) -> Tuple[Dict[str, Node], List[Edge]]:
  nodes: Dict[str, Node] = {}
  for n in (diagram_json.get("nodes") or []):
    nid = str(n.get("id", "")).strip()
    if not nid:
      continue
    label = str(n.get("label") or "").strip()
    x, y = _node_xy(n)
    shape = str(n.get("shape") or "rectangle")
    nodes[nid] = Node(id=nid, label=label, x=x, y=y, shape=shape)

  edges: List[Edge] = []
  for e in (diagram_json.get("edges") or []):
    s = str(e.get("source", "")).strip()
    d = str(e.get("destination", "")).strip()
    if not s or not d:
      continue
    label = str(e.get("label") or "").strip()
    edges.append(Edge(source=s, destination=d, label=label))

  return nodes, edges


# -------------------------
# Graph helpers
# -------------------------
def build_graph(nodes: Dict[str, Node], edges: List[Edge]):
  out_adj: Dict[str, List[Edge]] = defaultdict(list)
  indeg: Dict[str, int] = {nid: 0 for nid in nodes.keys()}

  for e in edges:
    if e.source in nodes and e.destination in nodes:
      out_adj[e.source].append(e)
      indeg[e.destination] = indeg.get(e.destination, 0) + 1
      indeg.setdefault(e.source, 0)

  return out_adj, indeg


def _degrees(nodes: Dict[str, Node], out_adj: Dict[str, List[Edge]]):
  indeg = {nid: 0 for nid in nodes}
  outdeg = {nid: len(out_adj.get(nid, [])) for nid in nodes}
  for s, edges in out_adj.items():
    for e in edges:
      if e.destination in indeg:
        indeg[e.destination] += 1
  return indeg, outdeg


def has_cycle(nodes: Dict[str, Node], edges: List[Edge]) -> bool:
  out_adj, indeg = build_graph(nodes, edges)
  q = deque([nid for nid, d in indeg.items() if d == 0])
  seen = 0
  while q:
    u = q.popleft()
    seen += 1
    for e in out_adj.get(u, []):
      v = e.destination
      indeg[v] -= 1
      if indeg[v] == 0:
        q.append(v)
  return seen != len(indeg)


def _is_linear(nodes: Dict[str, Node], out_adj: Dict[str, List[Edge]]) -> bool:
  indeg, outdeg = _degrees(nodes, out_adj)
  roots = [n for n, d in indeg.items() if d == 0]
  sinks = [n for n, d in outdeg.items() if d == 0]

  # linear chain: one start, one end, every node has <=1 in and <=1 out
  if len(roots) != 1 or len(sinks) != 1:
    return False
  for nid in nodes:
    if indeg[nid] > 1 or outdeg[nid] > 1:
      return False
  return True


def _is_tree(nodes: Dict[str, Node], out_adj: Dict[str, List[Edge]]) -> bool:
  indeg, _outdeg = _degrees(nodes, out_adj)
  roots = [n for n, d in indeg.items() if d == 0]
  if len(roots) != 1:
    return False
  # tree-ish: no merges (indeg <= 1 for all nodes)
  return all(d <= 1 for d in indeg.values())


def classify_diagram(diagram_json: Json) -> str:
  """
  Deterministic classifier:
    - linear
    - hierarchy (tree)
    - process (DAG; branching + merges allowed; cycles-with-exit treated as process)
    - cycle (pure loop with no sinks)
  """
  nodes, edges = normalize_flow_json(diagram_json)
  if not nodes:
    return "unknown"

  out_adj, _ = build_graph(nodes, edges)
  indeg, outdeg = _degrees(nodes, out_adj)
  sinks = [n for n, d in outdeg.items() if d == 0]

  if edges and has_cycle(nodes, edges):
    # If there is any sink, treat as process-with-loop rather than pure cycle.
    return "process" if len(sinks) > 0 else "cycle"

  if _is_linear(nodes, out_adj):
    return "linear"

  if _is_tree(nodes, out_adj):
    return "hierarchy"

  return "process"


# -------------------------
# Rendering helpers
# -------------------------
def _sort_children(nodes: Dict[str, Node], child_ids: List[str]) -> List[str]:
  def key(nid: str):
    n = nodes.get(nid)
    if not n:
      return (0.0, 0.0, "")
    return (n.y, n.x, (n.label or "").lower())
  return sorted(child_ids, key=key)


def _render_hierarchy(nodes: Dict[str, Node], out_adj: Dict[str, List[Edge]], roots: List[str]) -> str:
  visited_path: set[Tuple[str, str]] = set()

  def render_node(nid: str, indent: int) -> List[str]:
    n = nodes[nid]
    lines = [("  " * indent) + f"- {n.label or nid}"]
    children = [e.destination for e in out_adj.get(nid, []) if e.destination in nodes]
    children = _sort_children(nodes, children)

    for cid in children:
      edge_key = (nid, cid)
      if edge_key in visited_path:
        continue
      visited_path.add(edge_key)
      lines.extend(render_node(cid, indent + 1))
    return lines

  roots_sorted = _sort_children(nodes, roots)
  out_lines: List[str] = ["## Structure (Hierarchy)", ""]
  for r in roots_sorted:
    out_lines.extend(render_node(r, 0))
  return "\n".join(out_lines).strip() + "\n"


def _render_process_from_start(
  nodes: Dict[str, Node],
  out_adj: Dict[str, List[Edge]],
  start_id: str,
  *,
  base_indent: int = 0,
  max_steps: int = 200,
  skip_first_node: bool = False,
) -> List[str]:
  """
  Renders a nested bullet outline starting from start_id.

  Notes:
  - Requires Node to have: label, shape, x, y
    (shape can be "diamond" for decision nodes)
  - Correctly nests single-successor chains (indent+1).
  - Uses "(already described above)" for revisits to prevent duplication.
  """
  lines: List[str] = []
  visited_nodes: set[str] = set()

  def node_text(nid: str) -> str:
    n = nodes[nid]
    base = (n.label or nid).strip()
    if getattr(n, "shape", None) == "diamond":
      return f"{base} **(Decision)**"
    return base

  def sort_edges(edges: List[Edge]) -> List[Edge]:
    return sorted(
      edges,
      key=lambda e: (
        nodes[e.destination].y if e.destination in nodes else 0.0,
        nodes[e.destination].x if e.destination in nodes else 0.0,
        (nodes[e.destination].label or "").lower() if e.destination in nodes else "",
        (e.label or "").lower(),
      ),
    )

  def edge_prefix(e: Edge) -> Optional[str]:
    lbl = (e.label or "").strip()
    return lbl if lbl else None

  def walk(nid: str, indent: int, step_counter: List[int], incoming_label: Optional[str] = None):
    if step_counter[0] >= max_steps:
      lines.append(("  " * indent) + "- (Stopped: too many steps)")
      return

    if nid in visited_nodes:
      prefix = f"**{incoming_label}** → " if incoming_label else ""
      lines.append(("  " * indent) + f"- {prefix}{node_text(nid)} (already described above)")
      return

    visited_nodes.add(nid)
    step_counter[0] += 1

    outgoing = [e for e in out_adj.get(nid, []) if e.destination in nodes]
    outgoing = sort_edges(outgoing)

    prefix = f"**{incoming_label}** → " if incoming_label else ""
    lines.append(("  " * indent) + f"- {prefix}{node_text(nid)}")

    if not outgoing:
      return

    if len(outgoing) == 1:
      e = outgoing[0]
      # ✅ critical: indent + 1 so successor is nested under this step
      walk(e.destination, indent + 1, step_counter, incoming_label=edge_prefix(e))
      return

    # branching: each branch is a child bullet of this node
    for e in outgoing:
      walk(e.destination, indent + 1, step_counter, incoming_label=edge_prefix(e))

  if skip_first_node:
    outgoing = [e for e in out_adj.get(start_id, []) if e.destination in nodes]
    outgoing = sort_edges(outgoing)
    for e in outgoing:
      walk(e.destination, base_indent, [0], incoming_label=edge_prefix(e))
    return lines

  walk(start_id, base_indent, [0], incoming_label=None)
  return lines

def _render_cycle(nodes: Dict[str, Node], out_adj: Dict[str, List[Edge]]) -> str:
  """
  Cycle renderer: follows a deterministic "spine" (first outgoing edge),
  and annotates loop-backs and exits at the step where they occur.
  """
  def sort_edges(edges: List[Edge]) -> List[Edge]:
    return sorted(edges, key=lambda e: (nodes[e.destination].y, nodes[e.destination].x, (e.label or "").lower()))

  # deterministic start: top-most / left-most
  start = sorted(nodes.keys(), key=lambda nid: (nodes[nid].y, nodes[nid].x, (nodes[nid].label or "").lower()))[0]

  spine: List[str] = []
  index: Dict[str, int] = {}
  current = start

  # build spine by following first outgoing edge each time
  for _ in range(400):
    if current in index:
      break
    index[current] = len(spine)
    spine.append(current)

    outs = [e for e in out_adj.get(current, []) if e.destination in nodes]
    if not outs:
      break
    outs = sort_edges(outs)
    current = outs[0].destination

  lines: List[str] = ["## Structure (Cycle)", ""]

  for nid in spine:
    lines.append(f"- {nodes[nid].label or nid}")

    outs = [e for e in out_adj.get(nid, []) if e.destination in nodes]
    outs = sort_edges(outs)

    if not outs:
      continue

    primary = outs[0]
    if primary.destination in index:
      lines.append(f"  - loops back to: {nodes[primary.destination].label or primary.destination}")

    for e in outs[1:]:
      if e.destination in index:
        lines.append(f"  - loops back to: {nodes[e.destination].label or e.destination}")
      else:
        lines.append(f"  - exits to: {nodes[e.destination].label or e.destination}")

  return "\n".join(lines).strip() + "\n"


def _render_network(nodes: Dict[str, Node], out_adj: Dict[str, List[Edge]]) -> str:
  ordered_sources = sorted(
    nodes.keys(),
    key=lambda nid: (nodes[nid].y, nodes[nid].x, (nodes[nid].label or "").lower()),
  )
  lines: List[str] = ["## Relationships", ""]

  for s in ordered_sources:
    edges = [e for e in out_adj.get(s, []) if e.destination in nodes]
    if not edges:
      continue
    s_label = nodes[s].label or s

    edges = sorted(
      edges,
      key=lambda e: (
        nodes[e.destination].y,
        nodes[e.destination].x,
        (nodes[e.destination].label or "").lower(),
        (e.label or "").lower(),
      ),
    )

    for e in edges:
      d_label = nodes[e.destination].label or e.destination
      if e.label:
        lines.append(f"- {s_label} → {d_label} (label: {e.label})")
      else:
        lines.append(f"- {s_label} → {d_label}")

  return "\n".join(lines).strip() + "\n"


# -------------------------
# Public entrypoint
# -------------------------
def build_deterministic_outline(diagram_json: Json) -> Dict[str, str]:
  nodes, edges = normalize_flow_json(diagram_json)
  if not nodes:
    return {"diagram_type": "unknown", "outline_markdown": "## Structure\n\n(No nodes.)\n"}

  dtype = classify_diagram(diagram_json)

  out_adj, indeg = build_graph(nodes, edges)
  roots = [nid for nid, d in indeg.items() if d == 0]
  roots_sorted = _sort_children(nodes, roots) if roots else []

  if dtype == "hierarchy":
    md = _render_hierarchy(nodes, out_adj, roots_sorted or _sort_children(nodes, list(nodes.keys()))[:1])

  elif dtype == "linear":
    start = roots_sorted[0] if roots_sorted else _sort_children(nodes, list(nodes.keys()))[0]
    lines = ["## Structure (Linear)", ""]
    lines.extend(_render_process_from_start(nodes, out_adj, start, base_indent=0))
    md = "\n".join(lines).strip() + "\n"

  elif dtype == "process":
    lines = ["## Structure (Process)", ""]
    if len(roots_sorted) >= 2:
      for i, r in enumerate(roots_sorted, start=1):
        lines.append(f"{i}. Starting point: {nodes[r].label or r}")
        lines.extend(_render_process_from_start(
          nodes, out_adj, r,
          base_indent=1,
          skip_first_node=True,  # prevents repeating the start node bullet
        ))
        lines.append("")
    else:
      start = roots_sorted[0] if roots_sorted else _sort_children(nodes, list(nodes.keys()))[0]
      lines.extend(_render_process_from_start(nodes, out_adj, start, base_indent=0))
    md = "\n".join(lines).strip() + "\n"

  elif dtype == "cycle":
    md = _render_cycle(nodes, out_adj)

  else:
    md = _render_network(nodes, out_adj)

  return {"diagram_type": dtype, "outline_markdown": md}