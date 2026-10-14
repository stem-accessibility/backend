FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# Bake the model in so a cold start does not download ~800 MB. Pass --build-arg BAKE_MODEL=0 to skip.
ARG BAKE_MODEL=1
ENV HF_HOME=/models
RUN if [ "$BAKE_MODEL" = "1" ]; then \
      python -c "from transformers import DonutProcessor, VisionEncoderDecoderModel as M; \
n='ahmed-masry/unichart-base-960'; DonutProcessor.from_pretrained(n); M.from_pretrained(n)"; \
    fi

COPY app.py .
ENV PORT=8080
# One worker: the model is loaded once per process and generation is serialised inside it.
CMD exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 180 app:app
