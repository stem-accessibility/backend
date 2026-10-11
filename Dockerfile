FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libgl1 / libglib2.0-0 are needed by OpenCV
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch keeps the image far smaller than the default CUDA wheels.
RUN pip install torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Scale-to-zero defaults (Cloud Run): run each job inside the request that created it
# instead of in a background thread. Override both for an always-on host.
ENV RUN_JOBS_INLINE=1 \
    RUN_WORKER_IN_PROCESS=0

# One gunicorn process, several request threads.
CMD ["sh", "-c", "exec gunicorn backend.wsgi:app --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 8 --timeout 600"]
