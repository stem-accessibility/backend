import json
import os
import psutil

from backend.pipeline.ocr import google_ocr
from backend.pipeline.parse import assign_text_to_objects
from backend.pipeline.detect import run_detection
from backend.pipeline.link_predictor import infer_edges_from_nodes_and_image
from backend.pipeline.utils.general import create_structure


NODE_CLASSES = {
    "rectangle",
    "circle",
    "diamond",
    "ellipse",
    "parallelogram",
    "hexagon",
    "cylinder",
}


def print_memory(label=""):
    mem = psutil.Process().memory_info().rss / (1024 ** 2)
    print(f"🧠 {label} - Memory usage: {mem:.2f} MB")


def build_nodes_from_detection(yolo_objects, ocr_texts):
    node_objects = [obj for obj in yolo_objects if obj["class_name"] in NODE_CLASSES]
    node_objects = assign_text_to_objects(node_objects, ocr_texts)

    nodes = []
    for i, obj in enumerate(node_objects, start=1):
        node_id = f"node_{i}"
        obj["id"] = node_id

        nodes.append({
            "id": node_id,
            "label": obj.get("label", ""),
            "shape": obj["class_name"],
            "coordinates": obj["bounding_box"],
        })

    return nodes


def process_image(image_path, base_name=None):
    print_memory("START")

    # 1. OCR
    ocr_texts = google_ocr(image_path)
    print_memory("After OCR")

    # 2. YOLO detection
    yolo_objects, img_width, img_height = run_detection(image_path)
    print_memory("After YOLO")

    # 3. Nodes only
    nodes = build_nodes_from_detection(yolo_objects, ocr_texts)
    print_memory("After Node Extraction")

    # 4. Full VLM edge inference
    edges = infer_edges_from_nodes_and_image(image_path, nodes)
    print_memory("After Gemini Edge Inference")

    # 5. Final consistent schema
    final_json = create_structure(nodes, edges)

    print("✅ Flowchart JSON created")
    print_memory("END")
    return final_json