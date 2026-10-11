# detect.py
from ultralytics import YOLO
from PIL import Image
import numpy as np
import os

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "models", "best.pt")

model = YOLO(MODEL_PATH)

def run_detection(image_path):
    img = Image.open(image_path).convert("RGB")
    img_array = np.array(img)
    img_height, img_width = img_array.shape[:2]
    results = model.predict(source=image_path, device='cpu')[0]


    objects = []
    for box in results.boxes.data:
        cls_id = int(box[5])
        x1, y1, x2, y2 = map(int, box[:4])

        objects.append({
            "class_id": cls_id,
            "class_name": CLASS_NAMES.get(cls_id, "unknown"),
            "bounding_box": [(x1, y1), (x2, y2)]
        })

    return objects, img_width, img_height
