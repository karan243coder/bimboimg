# syntax=docker/dockerfile:1
###############################################################################
# AI Image Studio Bot — Koyeb free tier (512 MB / 0.1 vCPU) ke liye optimized
#
# Multi-stage build: wheels alag layer me, final image slim.
# Final size ~480 MB (onnxruntime + opencv bhaari hain, unavoidable).
###############################################################################

# ---------- stage 1: build wheels ----------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --wheel-dir=/wheels -r requirements.txt


# ---------- stage 2: runtime ----------
FROM python:3.11-slim

# Thread pinning — 0.1 vCPU par multi-thread ULTA slow karta hai
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    ORT_DISABLE_ALL_OPTIONAL_DEPS=1 \
    MALLOC_ARENA_MAX=2 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# tesseract = OCR · libgl/glib = opencv · tini = proper signal handling
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr \
      tesseract-ocr-eng \
      libgl1 \
      libglib2.0-0 \
      tini \
      curl \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man

WORKDIR /app

# wheels se install — koi compiler final image me nahi
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels \
 && find /usr/local/lib/python3.11 -type d -name '__pycache__' -prune -exec rm -rf {} + \
 && find /usr/local/lib/python3.11 -type d -name 'tests' -prune -exec rm -rf {} + \
 && find /usr/local/lib/python3.11 -name '*.pyc' -delete

# app code sabse aakhir me — cache friendly
COPY app ./app
COPY webapp ./webapp

# Model build-time par download + dynamic-axes patch.
# Isse pehle request instant hai aur runtime par patching ka RAM spike nahi.
RUN python -c "\
import os,urllib.request,onnx;\
os.makedirs('/opt/models',exist_ok=True);\
p='/opt/models/rmbg_q.onnx';\
urllib.request.urlretrieve('https://huggingface.co/briaai/RMBG-1.4/resolve/main/onnx/model_quantized.onnx',p);\
m=onnx.load(p);\
[[ (d.ClearField('dim_value'), setattr(d,'dim_param',n)) for d,n in zip(t.type.tensor_type.shape.dim[2:4],('H','W'))] for t in list(m.graph.input)+list(m.graph.output)];\
onnx.save(m,'/opt/models/rmbg_dyn.onnx');\
os.remove(p);\
print('model patched:',os.path.getsize('/opt/models/rmbg_dyn.onnx')//1048576,'MB')"

# non-root user (security)
RUN useradd -m -u 10001 botuser \
 && mkdir -p /tmp/cache \
 && chown -R botuser:botuser /app /tmp/cache /opt/models
USER botuser

ENV DB_PATH=/tmp/bot.db \
    CACHE_DIR=/tmp/cache \
    MODEL_DIR=/opt/models \
    PORT=8000

EXPOSE 8000

# start-period lamba: pehla boot par model download hota hai
HEALTHCHECK --interval=30s --timeout=8s --start-period=120s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# tini = zombie reaping + SIGTERM sahi tarah pass hota hai
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app.main"]
