"""UniChart as a small HTTP service: chart image in, text data table out.

Runs separately from the Flask backend because UniChart needs transformers==4.28.1 and torch, which
the backend should not carry. The backend calls POST /extract (chart_extract.extract_with_unichart).

    POST /extract   multipart field "image"          -> {"table": "<text table>"}
    GET  /health                                      -> {"ok": true, "loaded": bool}

The model is loaded on first use, and one request is generated at a time. Set UNICHART_TOKEN and
send it as X-Service-Token; the service refuses to start without one unless
UNICHART_ALLOW_NO_TOKEN=1 (local use only). It keeps no images: each upload is read into memory and
dropped.
"""
import hmac
import io
import os
import threading
import time

from flask import Flask, jsonify, request
from PIL import Image

MODEL_NAME = os.environ.get("UNICHART_MODEL", "ahmed-masry/unichart-base-960")
TOKEN = os.environ.get("UNICHART_TOKEN", "")
MAX_BYTES = int(os.environ.get("UNICHART_MAX_BYTES", str(8 * 1024 * 1024)))
PROMPT = "<extract_data_table> <s_answer>"

if not TOKEN and os.environ.get("UNICHART_ALLOW_NO_TOKEN") != "1":
    raise RuntimeError("Set UNICHART_TOKEN (or UNICHART_ALLOW_NO_TOKEN=1 for local use)")

# A decompression bomb is a small file that expands to a huge image; refuse past this many pixels.
Image.MAX_IMAGE_PIXELS = 40_000_000

app = Flask(__name__)
_lock = threading.Lock()
_state = {"model": None, "processor": None}


def _load():
    if _state["model"] is None:
        import torch
        from transformers import DonutProcessor, VisionEncoderDecoderModel

        torch.set_num_threads(int(os.environ.get("UNICHART_THREADS", "4")))
        _state["processor"] = DonutProcessor.from_pretrained(MODEL_NAME)
        _state["model"] = VisionEncoderDecoderModel.from_pretrained(MODEL_NAME).eval()
    return _state["model"], _state["processor"]


def _authorised():
    if not TOKEN:
        return True
    return hmac.compare_digest(request.headers.get("X-Service-Token", ""), TOKEN)


def read_table(image: Image.Image) -> str:
    import torch

    model, proc = _load()
    ids = proc.tokenizer(PROMPT, add_special_tokens=False, return_tensors="pt").input_ids
    pixels = proc(image, return_tensors="pt").pixel_values
    with torch.inference_mode():
        out = model.generate(
            pixels,
            decoder_input_ids=ids,
            max_length=model.decoder.config.max_position_embeddings,
            early_stopping=True,
            pad_token_id=proc.tokenizer.pad_token_id,
            eos_token_id=proc.tokenizer.eos_token_id,
            use_cache=True,
            num_beams=4,
            bad_words_ids=[[proc.tokenizer.unk_token_id]],
            return_dict_in_generate=True,
        )
    seq = proc.tokenizer.batch_decode(out.sequences)[0]
    seq = seq.replace(proc.tokenizer.eos_token, "").replace(proc.tokenizer.pad_token, "")
    return seq.split("<s_answer>")[1].strip() if "<s_answer>" in seq else seq.strip()


@app.get("/health")
def health():
    return jsonify({"ok": True, "loaded": _state["model"] is not None}), 200


@app.post("/extract")
def extract():
    if not _authorised():
        return jsonify({"error": "unauthorised"}), 401
    file = request.files.get("image")
    if file is None:
        return jsonify({"error": "no image"}), 400
    data = file.read(MAX_BYTES + 1)
    if not data:
        return jsonify({"error": "empty image"}), 400
    if len(data) > MAX_BYTES:
        return jsonify({"error": "image too large"}), 413
    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return jsonify({"error": "not a readable image"}), 400
    started = time.time()
    with _lock:
        table = read_table(image)
    return jsonify({"table": table, "seconds": round(time.time() - started, 2)}), 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5060")))
