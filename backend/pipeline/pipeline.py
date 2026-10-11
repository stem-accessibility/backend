
import json
import os
from backend.pipeline.ocr import google_ocr
from backend.pipeline.parse import assign_text_to_objects
from backend.pipeline.associate import associate_arrowheads, associate_edge_labels
from backend.pipeline.utils.general import create_json_structure
from backend.pipeline.detect import run_detection
from backend.pipeline.utils.edges import consolidate_edges_debug
from backend.pipeline.link_predictor import predict_links_from_gemini,predict_links_from_gemini_minimal2

import psutil

def print_memory(label=""):
    mem = psutil.Process().memory_info().rss / (1024 ** 2)  # in MB
    print(f"🧠 {label} - Memory usage: {mem:.2f} MB")


def process_image(image_path, base_name=None):
    print_memory("START")
    # Step 1: Run OCR
    ocr_texts = google_ocr(image_path)
    print_memory("After OCR")       
    # Step 2: Detect objects using YOLO
    yolo_objects, img_width, img_height = run_detection(image_path)
    print_memory("After YOLO")
   
    # 🔥 Consolidate edge segments into merged edges
    yolo_objects = consolidate_edges_debug(yolo_objects)
    print_memory("After Edge Consolidation")

    # Step 3: Assign OCR text to detected objects
    yolo_objects = assign_text_to_objects(yolo_objects, ocr_texts)

    # Step 4: Associate edge labels with edges
    yolo_objects = associate_edge_labels(yolo_objects)

    # Step 5: Associate arrowheads with edges
    yolo_objects = associate_arrowheads(yolo_objects)
    print_memory("After Text + Arrow Associations")

    node_counter = 1
    for obj in yolo_objects:
        if obj["class_name"] in ["rectangle", "circle", "diamond", "ellipse", "parallelogram", "hexagon", "cylinder"]:
            obj["id"] = f"node_{node_counter}"
            node_counter += 1
    # Step 6: Build minimal inputs for Gemini link prediction
    nodes = [
        {
            "id": obj["id"],
            "label": obj.get("label", ""),
            "coordinates": obj["bounding_box"]
        }
        for obj in yolo_objects
        if obj["class_name"] in ["rectangle", "circle", "diamond", "ellipse", "parallelogram", "hexagon", "cylinder"]
    ]
    # Assign consistent edge IDs to each edge object in-place
    edge_counter = 1
    for obj in yolo_objects:
        if obj["class_name"] in ["solid_edge", "dashed_edge"]:
            obj["id"] = f"edge_{edge_counter}"
            edge_counter += 1

    edges = [
        {
            "id": obj["id"],
            "coordinates": obj["bounding_box"],
            "arrowheads": [arrow["bounding_box"][0] for arrow in obj.get("arrowheads", [])]
        }
        for obj in yolo_objects
        if obj["class_name"] in ["solid_edge", "dashed_edge"]
    ]
    print_memory("Before Gemini Call")
    print(f"🧠 Sending {len(nodes)} nodes and {len(edges)} edges to Gemini...")
    predicted_links = predict_links_from_gemini_minimal2(nodes, edges, image_path)
    print_memory("After Gemini Call")
# Step 7: Generate final JSON structure (inject predicted links)
    final_json = create_json_structure(yolo_objects, predicted_links)
    print("✅ Flowchart JSON created")
    print_memory("END")
    # Step 6: Generate the preliminary JSON
   # json_data = create_json_structure(yolo_objects)

    # Step 7: Run link prediction
    #json_data = predict_links_from_gemini(json_data, image_path)

    return final_json


import os
from glob import glob

if __name__ == "__main__":

    TEST_MODE = True  # 👈 Toggle this to switch between single image vs batch mode

    image_dir = "data/images"
    json_dir = "data/json"
    pred_dir = "data/predictions"

    os.makedirs(json_dir, exist_ok=True)
    os.makedirs(pred_dir, exist_ok=True)

    if TEST_MODE:
        image_path = "flow.png"  # 🔁 Change this to any test image
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        json_path = f"test-{base_name}.json"

        print(f"\n🖼 Processing single image: {base_name}...")

        try:
            json_data = process_image(image_path, base_name=base_name)

            with open(json_path, "w") as json_file:
                json.dump(json_data, json_file, indent=4)

            print(f"✅ Done! Output saved to {json_path}")
        except Exception as e:
            print(f"❌ Failed on {image_path}: {e}")

    else:
        image_paths = glob(os.path.join(image_dir, "*.png")) + glob(os.path.join(image_dir, "*.jpg"))

        for image_path in image_paths:
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            json_path = os.path.join(json_dir, f"{base_name}.json")
        

            print(f"\n🖼 Processing {base_name}...")

            try:
                json_data = process_image(image_path, base_name=base_name)

                with open(json_path, "w") as json_file:
                    json.dump(json_data, json_file, indent=4)

                # Optionally draw YOLO predictions
                # draw_yolo_predictions(image_path, yolo_objects, save_path=output_img_path)

            except Exception as e:
                print(f"❌ Failed on {image_path}: {e}")
