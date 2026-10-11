from scipy.spatial import distance
from backend.pipeline.utils.geometry import expand_bbox, is_text_fully_inside_box
from backend.pipeline.utils.general import clean_ocr_text

# 🔹 Class labels
CLASS_NAMES = {
    0: "rectangle",
    1: "solid_edge",
    2: "circle",
    3: "edge_label",
    4: "diamond",
    5: "ellipse",
    6: "parallelogram",
    7: "hexagon",
    8: "cylinder",
    9: "arrowhead",
    10: "dashed_edge"
}

# 🔹 Function to parse YOLO annotations
def parse_yolo_annotation(yolo_txt_path, img_width, img_height):
    objects = []
    with open(yolo_txt_path, "r") as f:
        for line in f:
            data = line.strip().split()
            class_id = int(data[0])
            x_center, y_center, w, h = map(float, data[1:])

            # Convert YOLO format (normalized) to absolute pixel coordinates
            x_min = int((x_center - w / 2) * img_width)
            y_min = int((y_center - h / 2) * img_height)
            x_max = int((x_center + w / 2) * img_width)
            y_max = int((y_center + h / 2) * img_height)

            objects.append({
                "class_id": class_id,
                "class_name": CLASS_NAMES[class_id],
                "bounding_box": [(x_min, y_min), (x_max, y_max)]
            })

    return objects

# 🔹 Function to associate arrowheads with edges
def associate_arrowheads(yolo_objects):
    edges = [obj for obj in yolo_objects if obj["class_name"] in ["solid_edge", "dashed_edge"]]
    arrowheads = [obj for obj in yolo_objects if obj["class_name"] == "arrowhead"]

    for arrow in arrowheads:
        closest_edge = min(edges, key=lambda edge: distance.euclidean(arrow["bounding_box"][0], edge["bounding_box"][0]), default=None)
        if closest_edge:
            if "arrowheads" not in closest_edge:
                closest_edge["arrowheads"] = []
            closest_edge["arrowheads"].append(arrow)

    return yolo_objects



# 🔹 Associate text with objects (fixes the edge label issue)
def assign_text_to_objects(yolo_objects, ocr_texts):
    node_classes = {"rectangle", "diamond", "circle", "ellipse", "parallelogram", "hexagon", "cylinder"}
    edge_classes = {"solid_edge", "dashed_edge"}
    edge_label_class = "edge_label"

    # Initialize text storage
    for obj in yolo_objects:
        obj["text"] = []

    # Process each detected text
    for text in ocr_texts:
        assigned = False

        # Check if the text belongs to an edge label first
        for obj in yolo_objects:
            if obj["class_name"] == edge_label_class:
                expanded_bbox = expand_bbox(obj["bounding_box"], expand_ratio=0.2)  # Expand edge labels more
                if is_text_fully_inside_box(text["bounding_box"], expanded_bbox):
                    obj["text"].append(text["text"])
                    assigned = True
                    break  # Only one match per text

        # If not assigned to an edge label, check if it belongs to a node
        if not assigned:
            for obj in yolo_objects:
                if obj["class_name"] in node_classes:
                    expanded_bbox = expand_bbox(obj["bounding_box"], expand_ratio=0.1)
                    if is_text_fully_inside_box(text["bounding_box"], expanded_bbox):
                        obj["text"].append(text["text"])
                        assigned = True
                        break  # Only one match per text

    # Merge text into a single label for each object
    for obj in yolo_objects:
        obj["label"] = clean_ocr_text(" ".join(obj["text"])) if obj["text"] else None

    return yolo_objects

