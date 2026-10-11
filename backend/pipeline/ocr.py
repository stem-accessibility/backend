import io
import os
import json
from dotenv import load_dotenv
from google.cloud import vision
from google.oauth2 import service_account

load_dotenv()

# Load JSON credentials from env var
json_creds = os.environ.get("GOOGLE_CREDENTIALS")

if json_creds:
    print("✅ Found GOOGLE_CREDENTIALS in environment. Parsing credentials...")
    try:
        cred_dict = json.loads(json_creds)
        credentials = service_account.Credentials.from_service_account_info(cred_dict)
        client = vision.ImageAnnotatorClient(credentials=credentials)
    except Exception as e:
        print("❌ Failed to parse GOOGLE_CREDENTIALS:", e)
        print("Falling back to application default credentials...")
        client = vision.ImageAnnotatorClient()
else:
    print("⚠️ GOOGLE_CREDENTIALS not found. Falling back to ADC (may fail)...")
    client = vision.ImageAnnotatorClient()


def google_ocr(image_path):
    with open(image_path, "rb") as image_file:
        content = image_file.read()
    
    image = vision.Image(content=content)
    response = client.text_detection(image=image)

    texts = response.text_annotations
    if not texts:
        print("No text found")
        return []

    results = []
    for text in texts[1:]:  # Skip first element
        bbox = [(v.x, v.y) for v in text.bounding_poly.vertices]
        results.append({"text": text.description, "bounding_box": bbox})
    
    return results
