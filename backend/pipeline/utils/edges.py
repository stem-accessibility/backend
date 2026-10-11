
import numpy as np
from collections import deque
import os

# --- Use the Intersection-based connectability check ---
def are_boxes_connectable(b1, b2, threshold):
    (x1a, y1a), (x2a, y2a) = b1
    (x1b, y1b), (x2b, y2b) = b2

    # Expand boxes by the threshold
    x1a_exp, y1a_exp = x1a - threshold, y1a - threshold
    x2a_exp, y2a_exp = x2a + threshold, y2a + threshold
    x1b_exp, y1b_exp = x1b - threshold, y1b - threshold
    x2b_exp, y2b_exp = x2b + threshold, y2b + threshold

    # Check for intersection of expanded boxes
    # Intersection occurs if:
    # X dimensions overlap: Left_A < Right_B AND Left_B < Right_A
    x_intersects = (x1a_exp < x2b_exp) and (x1b_exp < x2a_exp)
    # Y dimensions overlap: Top_A < Bottom_B AND Top_B < Bottom_A
    y_intersects = (y1a_exp < y2b_exp) and (y1b_exp < y2a_exp)

    return x_intersects and y_intersects
# --- End connectability check ---

def are_boxes_connectable_min_overlap(b1, b2, min_overlap=5):
    """
    Checks if two boxes are connectable based on having more than a minimum
    overlap along one dimension while being aligned (overlapping by >= 1px)
    on the other.

    Args:
        b1: Bounding box tuple ((x1, y1), (x2, y2)).
        b2: Bounding box tuple ((x1, y1), (x2, y2)).
        min_overlap: The minimum number of pixels boxes must overlap
                     along their primary connection axis (exclusive, > min_overlap).

    Returns:
        True if the boxes meet the overlap criteria, False otherwise.
    """
    (x1a, y1a), (x2a, y2a) = b1
    (x1b, y1b), (x2b, y2b) = b2

    # Calculate the intersection rectangle (common area)
    # Find the coordinates of the intersection rectangle
    x_overlap_start = max(x1a, x1b)
    y_overlap_start = max(y1a, y1b)
    x_overlap_end = min(x2a, x2b)
    y_overlap_end = min(y2a, y2b)

    # Calculate the width and height of the intersection
    # If end < start, there is no overlap in that dimension, so width/height is 0
    x_overlap_width = max(0, x_overlap_end - x_overlap_start)
    y_overlap_height = max(0, y_overlap_end - y_overlap_start)

    # --- Define connection criteria ---

    # Criterion 1: Connect vertically?
    # - Vertical overlap must be significant (> min_overlap)
    # - Horizontal overlap must be at least 1 pixel (ensures alignment)
    connect_vertically = (y_overlap_height > min_overlap) and (x_overlap_width >= 1)

    # Criterion 2: Connect horizontally?
    # - Horizontal overlap must be significant (> min_overlap)
    # - Vertical overlap must be at least 1 pixel (ensures alignment)
    connect_horizontally = (x_overlap_width > min_overlap) and (y_overlap_height >= 1)

    # Return True if either criterion is met
    return connect_vertically or connect_horizontally

# Helper to check if inner box is contained within outer box
def is_contained(inner, outer):
    (x1i, y1i), (x2i, y2i) = inner
    (x1o, y1o), (x2o, y2o) = outer
    # Add a small tolerance to containment check? Optional.
    # tol = 1
    # return (x1o - tol) <= x1i and (y1o - tol) <= y1i and \
    #        x2i <= (x2o + tol) and y2i <= (y2o + tol)
    return x1o <= x1i and y1o <= y1i and x2i <= x2o and y2i <= y2o

def consolidate_edges_debug(yolo_objects, min_overlap=15):

    # Step 1: Filter edges and remove contained ones
    edge_objs = [obj for obj in yolo_objects if obj["class_name"] in ["solid_edge", "dashed_edge"]]
    #print(f"\n🔍 Starting with {len(edge_objs)} edge candidates...")

    edge_indices = list(range(len(edge_objs)))
    removed_indices = set()

    # Iterate through pairs to find contained boxes
    for i in edge_indices:
        if i in removed_indices:
            continue
        bbox_i = edge_objs[i]["bounding_box"]
        for j in edge_indices:
            if i == j or j in removed_indices:
                continue
            bbox_j = edge_objs[j]["bounding_box"]

            # Check containment both ways
            if is_contained(bbox_i, bbox_j):
                # print(f"ℹ️ Edge {i} {bbox_i} is contained within edge {j} {bbox_j}")
                removed_indices.add(i)
                break # Box i is contained, no need to check it against others
            elif is_contained(bbox_j, bbox_i):
                # print(f"ℹ️ Edge {j} {bbox_j} is contained within edge {i} {bbox_i}")
                removed_indices.add(j)
                # Continue checking i against other boxes, as j might be contained in others too

    # Create the filtered list
    filtered_edge_objs = [edge_objs[i] for i in edge_indices if i not in removed_indices]
    #print(f"✅ {len(filtered_edge_objs)} edges after containment filter (Removed indices: {sorted(list(removed_indices))})")
    edge_objs = filtered_edge_objs # Use the filtered list from now on


    
    # Step 2: Group connected edges using BFS
    used = set()
    consolidated = []
    obj_indices = list(range(len(edge_objs))) # Indices refer to the filtered list

    for i in obj_indices:
        if i in used:
            continue

        current_group_indices = []
        queue = deque([i])
        processed_in_this_group = set([i]) # Track nodes added to queue/processed in this specific BFS

        while queue:
            idx = queue.popleft()

            if idx in used: # Should not happen if processed_in_this_group works, but safe check
                continue

            # Add to the final group and mark globally used
            current_group_indices.append(idx)
            used.add(idx)

            box_idx = edge_objs[idx]["bounding_box"]
            class_idx = edge_objs[idx]["class_name"]

            # Find neighbors of idx
            for j in obj_indices:
                # Skip if same node, already used globally, or already queued/processed in this group
                if j == idx or j in used or j in processed_in_this_group:
                    continue

                box_j = edge_objs[j]["bounding_box"]
                class_j = edge_objs[j]["class_name"]

                # Check for connectability: same class and geometrically connectable
                if class_j == class_idx and are_boxes_connectable_min_overlap(box_idx, box_j, min_overlap):
                    # Add to queue and mark as processed for this group search
                    queue.append(j)
                    processed_in_this_group.add(j)


        # Process the found group (if any nodes were added)
        if current_group_indices:
            group_objects = [edge_objs[idx] for idx in current_group_indices]

            # Merge group bounding boxes
            xs = [pt[0] for e in group_objects for pt in e["bounding_box"]]
            ys = [pt[1] for e in group_objects for pt in e["bounding_box"]]
            merged_bbox = [(min(xs), min(ys)), (max(xs), max(ys))]

            consolidated.append({
                "class_name": group_objects[0]["class_name"], # Assume all in group have same class
                "bounding_box": merged_bbox,
                "label": next((e.get("label") for e in group_objects if e.get("label")), None),
                "arrowheads": sum([e.get("arrowheads", []) for e in group_objects], [])
            })
            #print(f"✅ Group {len(consolidated)} has {len(group_objects)} boxes (Indices: {current_group_indices}) → {merged_bbox}")

            


    #print(f"\n🎯 Final: {len(consolidated)} consolidated edges")

    


    # Final output: Combine consolidated edges with non-edge objects
    others = [obj for obj in yolo_objects if obj["class_name"] not in ["solid_edge", "dashed_edge"]]
    return others + consolidated


