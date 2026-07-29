"""AI engine — 512MB tier ke liye tuned.

Key ideas:
  • Model lazy load hota hai, idle par unload (RAM wapas)
  • Quantized ONNX (42MB) — full model 168MB hai, fit nahi hota
  • Ek hi session, ek hi job at a time (semaphore)
  • Sab kuch numpy me, koi extra copy nahi
"""
from __future__ import annotations

import gc
import io
import os
import time
import logging
import threading
import urllib.request

import numpy as np
from PIL import Image, ImageFilter

from . import config as C

log = logging.getLogger("engine")

_sess = None
_sess_lock = threading.Lock()
_last_used = 0.0


# --------------------------------------------------------------- model
def _download(url: str, path: str):
    if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    log.info("downloading model…")
    with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(tmp, path)
    log.info("model ready: %.1f MB", os.path.getsize(path) / 1e6)
    return path


def get_session():
    """Lazy-load ONNX session. Thread-safe."""
    global _sess, _last_used
    with _sess_lock:
        if _sess is None:
            import onnxruntime as ort

            path = _download(C.RMBG_URL, os.path.join(C.MODEL_DIR, "rmbg_q.onnx"))
            so = ort.SessionOptions()
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            so.intra_op_num_threads = 1          # 0.1 vCPU — 1 thread hi behtar
            so.inter_op_num_threads = 1
            so.enable_mem_pattern = False        # memory spike kam
            so.enable_cpu_mem_arena = False
            _sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
            log.info("onnx session ready")
        _last_used = time.time()
        return _sess


def maybe_unload():
    """Idle par session free karo — RAM wapas OS ko."""
    global _sess
    with _sess_lock:
        if _sess is not None and time.time() - _last_used > C.MODEL_IDLE_UNLOAD_SEC:
            _sess = None
            gc.collect()
            log.info("model unloaded (idle) — RAM freed")


def ram_mb() -> float:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return 0.0


# --------------------------------------------------------------- helpers
def load_image(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
    w, h = im.size
    if max(w, h) > C.MAX_SIDE:
        s = C.MAX_SIDE / max(w, h)
        im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
    return im


def to_bytes(im: Image.Image, fmt="PNG", q=None) -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG" and im.mode == "RGBA":
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        im = bg
    im.save(buf, fmt, quality=q or C.JPEG_Q, optimize=True)
    return buf.getvalue()


# --------------------------------------------------------------- core AI
# RMBG-1.4 ONNX graph FIXED 1024x1024 leta hai — variable size par InvalidArgument.
# Speed C.AI_SIZE se nahi, image ko pehle downscale karke aati hai (kam pixels =
# kam pre/post-process), model input hamesha 1024 rehta hai.
RMBG_INPUT = 1024


def _alpha(im: Image.Image) -> np.ndarray:
    """RMBG-1.4 se alpha matte (0-255) nikalo, original size me."""
    sess = get_session()
    n = RMBG_INPUT
    small = im.convert("RGB").resize((n, n), Image.BILINEAR)
    x = np.asarray(small, dtype=np.float32) / 255.0
    x = (x - 0.5)                                  # RMBG normalize
    x = np.transpose(x, (2, 0, 1))[None]           # NCHW
    inp = sess.get_inputs()[0].name
    out = sess.run(None, {inp: x})[0]
    m = out[0, 0] if out.ndim == 4 else out[0]
    mn, mx = float(m.min()), float(m.max())
    m = (m - mn) / (mx - mn + 1e-8)
    a = Image.fromarray((m * 255).astype(np.uint8), "L").resize(im.size, Image.BILINEAR)
    del x, out
    return np.asarray(a)


def remove_bg(data: bytes, bg=None, feather=1, edge_shrink=0) -> bytes:
    """Background hatao. bg=None -> transparent, ya (r,g,b).

    Speed trick: alpha chhoti copy par nikaalo (AI_SIZE), phir full-res par
    upscale karo. Model to 1024 par hi chalta hai, par pre/post-process
    ke pixels kam ho jaate hain — 512 par ~1.8x fast, quality lagbhag same.
    """
    im = load_image(data)
    work = im
    if C.AI_SIZE and max(im.size) > C.AI_SIZE:
        s = C.AI_SIZE / max(im.size)
        work = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))),
                         Image.BILINEAR)
    a = _alpha(work)
    if work is not im:
        a = np.asarray(Image.fromarray(a, "L").resize(im.size, Image.BILINEAR))
    am = Image.fromarray(a, "L")
    if edge_shrink:
        am = am.filter(ImageFilter.MinFilter(2 * edge_shrink + 1))
    if feather:
        am = am.filter(ImageFilter.GaussianBlur(feather))
    rgb = im.convert("RGB")
    if bg:
        base = Image.new("RGB", im.size, tuple(bg))
        base.paste(rgb, mask=am)
        out = base
        fmt = "JPEG"
    else:
        out = rgb.convert("RGBA")
        out.putalpha(am)
        fmt = "PNG"
    res = to_bytes(out, fmt)
    del im, a, am, rgb, out
    gc.collect()
    return res


def convert(data: bytes, fmt="PNG", quality=92, max_w=0) -> bytes:
    im = load_image(data)
    if max_w and im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    return to_bytes(im, fmt, quality)


def compress(data: bytes, target_kb=300) -> tuple[bytes, int]:
    """Binary-search quality taaki target size ke aas-paas aaye.
    Agar original pehle se chhota hai to usko hi wapas karo (no re-encode)."""
    if len(data) / 1024 <= target_kb * 0.9:
        return data, len(data) // 1024

    im = load_image(data).convert("RGB")
    lo, hi = 30, 95
    best = None
    while lo <= hi:
        q = (lo + hi) // 2
        cand = to_bytes(im, "JPEG", q)
        if len(cand) / 1024 > target_kb:
            hi = q - 1
        else:
            best = cand
            lo = q + 1
    if best is None:                       # target bahut chhota — floor par jao
        best = to_bytes(im, "JPEG", 30)
    # agar phir bhi original se bada, original hi behtar
    if len(best) >= len(data):
        return data, len(data) // 1024
    return best, len(best) // 1024


def upscale(data: bytes, factor=2) -> bytes:
    """Lanczos + unsharp — light, koi model nahi (RAM bachao)."""
    im = load_image(data)
    w, h = im.size
    if w * factor > 4000:
        factor = max(1, 4000 // w)
    big = im.resize((w * factor, h * factor), Image.LANCZOS)
    big = big.filter(ImageFilter.UnsharpMask(radius=2, percent=110, threshold=3))
    return to_bytes(big, "PNG")


# --------------------------------------------------------------- text removal
def remove_text(data: bytes, zone="both", zone_pct=0.22, min_conf=45) -> tuple[bytes, list]:
    """Edge-zone OCR + inpaint. Center bilkul safe."""
    import cv2

    im = load_image(data).convert("RGB")
    img = np.asarray(im)[:, :, ::-1].copy()          # RGB->BGR
    H, W = img.shape[:2]
    band = int(W * zone_pct)

    words = []
    mask = np.zeros((H, W), np.uint8)
    try:
        import pytesseract
        from pytesseract import Output
        # tessdata path debian version se badalta hai — auto-detect
        if not os.environ.get("_TESS_OK"):
            import glob
            for p in glob.glob("/usr/share/tesseract-ocr/*/tessdata"):
                os.environ["TESSDATA_PREFIX"] = p
                break
            os.environ["_TESS_OK"] = "1"

        d = pytesseract.image_to_data(im, output_type=Output.DICT)
        for i, txt in enumerate(d["text"]):
            t = (txt or "").strip()
            if not t or int(float(d["conf"][i])) < min_conf:
                continue
            alnum = sum(c.isalnum() for c in t)
            if alnum < 2 or alnum / len(t) < 0.5:
                continue
            x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
            cx = x + w / 2
            ok = (zone == "off"
                  or (zone in ("left", "both") and cx < band)
                  or (zone in ("right", "both") and cx > W - band))
            if not ok:
                continue
            pad = max(2, int(h * 0.2))
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
            roi = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
            _, t1 = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            _, t2 = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            stroke = t1 if cv2.countNonZero(t1) <= cv2.countNonZero(t2) else t2
            stroke = cv2.dilate(stroke, np.ones((3, 3), np.uint8))
            mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], stroke)
            words.append(t)
    except Exception as e:
        log.warning("ocr unavailable: %s", e)

    if mask.any():
        img = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)
    out = Image.fromarray(img[:, :, ::-1])
    return to_bytes(out, "PNG"), words
