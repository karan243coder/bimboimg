"""Central config — sab tuning yahan se."""
import os


def _b(k: str, d: bool) -> bool:
    return os.getenv(k, str(d)).lower() in ("1", "true", "yes", "on")


def _i(k: str, d: int) -> int:
    try:
        return int(os.getenv(k, d))
    except ValueError:
        return d


# ---------- required ----------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

# ---------- deployment ----------
PORT = _i("PORT", 8000)
BASE_URL = os.getenv("KOYEB_PUBLIC_DOMAIN", "") or os.getenv("BASE_URL", "")
if BASE_URL and not BASE_URL.startswith("http"):
    BASE_URL = "https://" + BASE_URL
USE_WEBHOOK = _b("USE_WEBHOOK", bool(BASE_URL))
WEBHOOK_PATH = "/tg/" + (BOT_TOKEN.split(":")[-1][:16] if BOT_TOKEN else "hook")

# ---------- memory guards (512 MB tier) ----------
MAX_RAM_MB = _i("MAX_RAM_MB", 512)
RAM_SOFT_LIMIT = _i("RAM_SOFT_LIMIT", 400)   # is se upar -> defensive unload
MODEL_IDLE_UNLOAD_SEC = _i("MODEL_IDLE_UNLOAD_SEC", 90)   # idle par model free (aggressive)
MAX_SIDE = _i("MAX_SIDE", 1400)          # input image ka max side
AI_SIZE = _i("AI_SIZE", 640)             # model input. 640 = 416MB peak / 1.8s (512MB safe)
                                         # 512 = 372MB / 1.1s · 704 = 423MB / 2.1s
MAX_FILE_MB = _i("MAX_FILE_MB", 20)
JPEG_Q = _i("JPEG_Q", 92)

# ---------- concurrency ----------
MAX_CONCURRENT_JOBS = _i("MAX_CONCURRENT_JOBS", 1)   # 512MB = 1 se zyada mat karo
QUEUE_MAX = _i("QUEUE_MAX", 40)
JOB_TIMEOUT = _i("JOB_TIMEOUT", 180)

# ---------- rate limits ----------
FREE_DAILY = _i("FREE_DAILY", 40)
RATE_WINDOW = _i("RATE_WINDOW", 60)
RATE_MAX = _i("RATE_MAX", 12)

# ---------- features ----------
ENABLE_VIDEO = _b("ENABLE_VIDEO", False)   # free tier par bhaari
VIDEO_MAX_SEC = _i("VIDEO_MAX_SEC", 5)
VIDEO_FPS = _i("VIDEO_FPS", 6)
ENABLE_OCR = _b("ENABLE_OCR", True)
WEBAPP_URL = os.getenv("WEBAPP_URL", "")   # client-side heavy tools

# ---------- storage ----------
DB_PATH = os.getenv("DB_PATH", "/tmp/bot.db")
CACHE_DIR = os.getenv("CACHE_DIR", "/tmp/cache")
MODEL_DIR = os.getenv("MODEL_DIR", "/opt/models")

RMBG_URL = "https://huggingface.co/briaai/RMBG-1.4/resolve/main/onnx/model_quantized.onnx"
