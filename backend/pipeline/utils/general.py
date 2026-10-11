import re

def clean_ocr_text(text):
    # Remove spaces before punctuation
    text = re.sub(r'\s+([.,!?;:])', r'\1', text)

    # Remove space after '(' and before ')'
    text = re.sub(r'\(\s+', '(', text)
    text = re.sub(r'\s+\)', ')', text)
    
    return text

# 🔹 Function to create final JSON structure with optional Gemini links
def create_json_structure(yolo_objects, predicted_links=None):
    nodes = []
    edges = []

    # Step 1: Map predicted links by edge_id
    link_map = {}
    if predicted_links:
        link_map = {link["edge_id"]: (link["source"], link["destination"]) for link in predicted_links}

    
    for obj in yolo_objects:
        obj_id = obj.get("id")

        if obj["class_name"] in ["rectangle", "circle", "diamond", "ellipse", "parallelogram", "hexagon", "cylinder"]:
            
            nodes.append({
                "id": obj_id,
                "label": obj.get("label", ""),
                "shape": obj["class_name"],
                "coordinates": obj["bounding_box"]
            })

        elif obj["class_name"] in ["solid_edge", "dashed_edge"]:
        
            source, destination = link_map.get(obj_id, (None, None))

            edges.append({
                "id": obj_id,
                "source": source,
                "destination": destination,
                "label": obj.get("label", ""),
                "type": obj["class_name"],
                "arrowheads": [arrow["bounding_box"][0] for arrow in obj.get("arrowheads", [])],
                "coordinates": obj["bounding_box"]
            })

    return {"nodes": nodes, "edges": edges}


def create_structure(nodes, edges):
    """
    Normalize final pipeline output into one consistent schema.

    Expected node shape:
    {
        "id": str,
        "label": str,
        "shape": str,
        "coordinates": [...]
    }

    Expected edge shape:
    {
        "id": str,
        "source": str | None,
        "destination": str | None,
        "label": str,
        "type": str,           # "solid" or "dashed"
        "arrowheads": list,    # e.g. [], ["end"], ["start", "end"]
        "coordinates": [...] | None
    }
    """
    normalized_nodes = []
    normalized_edges = []

    for node in nodes:
        normalized_nodes.append({
            "id": node.get("id"),
            "label": node.get("label", ""),
            "shape": node.get("shape", ""),
            "coordinates": node.get("coordinates"),
        })

    for i, edge in enumerate(edges):
        edge_type = edge.get("type", "solid")

        # normalize accidental old values like "solid_edge" / "dashed_edge"
        if edge_type == "solid_edge":
            edge_type = "solid"
        elif edge_type == "dashed_edge":
            edge_type = "dashed"

        normalized_edges.append({
            "id": edge.get("id", f"edge_{i+1}"),
            "source": edge.get("source"),
            "destination": edge.get("destination"),
            "label": edge.get("label", ""),
            "type": edge_type,
            "arrowheads": edge.get("arrowheads", []),
            "coordinates": edge.get("coordinates"),
        })

    return {
        "nodes": normalized_nodes,
        "edges": normalized_edges,
    }