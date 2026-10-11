from scipy.spatial import distance
import numpy as np

# 🔹 Calculate the center of a bounding box
def get_bbox_center(bbox):
    x_min, y_min = bbox[0]
    x_max, y_max = bbox[1]
    return ((x_min + x_max) / 2, (y_min + y_max) / 2)
# 🔹 Find the closest edge for each edge label
def associate_edge_labels(yolo_objects):
    edges = [obj for obj in yolo_objects if obj["class_name"] in {"solid_edge", "dashed_edge"}]
    edge_labels = [obj for obj in yolo_objects if obj["class_name"] == "edge_label"]

    for edge_label in edge_labels:
        label_center = get_bbox_center(edge_label["bounding_box"])
        closest_edge = None
        min_distance = float("inf")

        for edge in edges:
            edge_center = get_bbox_center(edge["bounding_box"])
            distance = np.linalg.norm(np.array(label_center) - np.array(edge_center))  # Euclidean distance

            if distance < min_distance:
                min_distance = distance
                closest_edge = edge

        if closest_edge:
            closest_edge["label"] = edge_label["label"]

    return yolo_objects

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

