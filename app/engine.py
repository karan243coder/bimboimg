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
_dynamic = False
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


def _make_dynamic(src: str, dst: str) -> str:
    """RMBG ka graph 1024x1024 par HARD-CODED hai.

    1024 par inference ~600 MB peak leta hai -> 512 MB tier par OOM (exit 137).
    Graph ke H/W dims ko dynamic banane se chhoti input chalti hai:
        1024 -> 603 MB / 5.5 s
         640 -> 416 MB / 1.8 s   (IoU 0.94 vs 1024, aankh se farak nahi)
    Ye ek baar hota hai, patched file cache ho jaati hai.
    """
    if os.path.exists(dst) and os.path.getsize(dst) > 1_000_000:
        return dst
    try:
        import onnx
        m = onnx.load(src)
        for t in list(m.graph.input) + list(m.graph.output):
            dims = t.type.tensor_type.shape.dim
            for d, name in zip(dims[2:4], ("H", "W")):
                d.ClearField("dim_value")
                d.dim_param = name
        onnx.save(m, dst)
        log.info("patched model to dynamic H/W")
        return dst
    except Exception as e:
        log.warning("dynamic patch failed (%s) — 1024 fixed mode", e)
        return src


def get_session():
    """Lazy-load ONNX session. Thread-safe."""
    global _sess, _last_used, _dynamic
    with _sess_lock:
        if _sess is None:
            import onnxruntime as ort

            raw = _download(C.RMBG_URL, os.path.join(C.MODEL_DIR, "rmbg_q.onnx"))
            path = _make_dynamic(raw, os.path.join(C.MODEL_DIR, "rmbg_dyn.onnx"))
            _dynamic = path != raw

            so = ort.SessionOptions()
            # ORT_ENABLE_ALL kuch nodes fuse karke memory badha deta hai —
            # 512 MB par BASIC safer hai
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
            so.intra_op_num_threads = 1
            so.inter_op_num_threads = 1
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            so.enable_mem_pattern = False       # pre-allocation off
            so.enable_cpu_mem_arena = False     # arena free karo turant
            so.add_session_config_entry("session.use_env_allocators", "0")
            _sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
            log.info("onnx session ready (dynamic=%s, rss=%.0f MB)", _dynamic, ram_mb())
        _last_used = time.time()
        return _sess


def _trim():
    """glibc ko bolo free memory OS ko wapas de (RSS actually girta hai)."""
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def maybe_unload():
    """Idle par session free karo — RAM wapas OS ko."""
    global _sess
    with _sess_lock:
        if _sess is not None and time.time() - _last_used > C.MODEL_IDLE_UNLOAD_SEC:
            before = ram_mb()
            _sess = None
            _trim()
            log.info("model unloaded (idle): %.0f -> %.0f MB", before, ram_mb())


def force_unload():
    """Turant free karo — RAM watchdog ke liye."""
    global _sess
    with _sess_lock:
        before = ram_mb()
        _sess = None
        _trim()
        if before - ram_mb() > 5:
            log.info("force unload: %.0f -> %.0f MB", before, ram_mb())


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
    """RMBG-1.4 se alpha matte (0-255), original size me.

    Dynamic model ho to C.AI_SIZE par chalta hai (kam RAM, tez).
    Warna 1024 (jo 512 MB par risky hai — isliye patch zaroori).
    """
    sess = get_session()
    n = C.AI_SIZE if _dynamic else RMBG_INPUT
    n = max(256, (n // 32) * 32)              # model stride ke multiple

    small = im.convert("RGB").resize((n, n), Image.BILINEAR)
    x = np.asarray(small, dtype=np.float32)
    x /= 255.0
    x -= 0.5
    x = np.ascontiguousarray(np.transpose(x, (2, 0, 1))[None])
    del small

    out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
    del x
    m = out[0, 0] if out.ndim == 4 else out[0]
    mn, mx = float(m.min()), float(m.max())
    m = (m - mn) / (mx - mn + 1e-8)
    a = Image.fromarray((m * 255).astype(np.uint8), "L").resize(im.size, Image.BILINEAR)
    del out, m
    gc.collect()
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
    _trim()
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
