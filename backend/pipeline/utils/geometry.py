# 🔹 Expand bounding boxes slightly
def expand_bbox(bbox, expand_ratio=.05):
    """Expands a bounding box slightly to improve text detection matching."""
    x_min, y_min = bbox[0]
    x_max, y_max = bbox[1]
    width = x_max - x_min
    height = y_max - y_min

    # Expand the box slightly
    x_min -= width * expand_ratio
    y_min -= height * expand_ratio
    x_max += width * expand_ratio
    y_max += height * expand_ratio

    return [(x_min, y_min), (x_max, y_max)]

# 🔹 Calculate the center of a bounding box
def get_bbox_center(bbox):
    x_min, y_min = bbox[0]
    x_max, y_max = bbox[1]
    return ((x_min + x_max) / 2, (y_min + y_max) / 2)

# 🔹 Check if a text box is fully inside a bounding box
def is_text_fully_inside_box(text_bbox, obj_bbox):
    x_min, y_min = obj_bbox[0]
    x_max, y_max = obj_bbox[1]

    # Ensure all four points of the text bbox are inside the object bbox
    for x, y in text_bbox:
        if not (x_min <= x <= x_max and y_min <= y <= y_max):
            return False  # If any point is outside, return False
    return True

# 🔹 Function to check if OCR text is inside a YOLO box
def is_text_inside_box(text_bbox, obj_bbox):
    x_min, y_min = obj_bbox[0]
    x_max, y_max = obj_bbox[1]
    
    for x, y in text_bbox:
        if x_min <= x <= x_max and y_min <= y <= y_max:
            return True
    return False

