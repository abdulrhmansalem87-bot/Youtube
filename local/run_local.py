"""Local render engine (second engine). Runs the SAME pipeline as GitHub Actions on the owner's PC.

    python local/run_local.py            # preflight, then render-only run (long video + Shorts), never uploads
    python local/run_local.py --check    # preflight only

Safety: uploads are forced off and privacy stays private. Output goes to output/ and a timing log to
output/local_render_log.json (minutes per run; feeds the cadence math in HANDOVER.md).
Keys come from a local .env file next to this script's parent folder (never commit it).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOW_MEMORY_THREADS = "2"  # 8 GB machine: cap x264 threads; the renderer already encodes one scene at a time


def _ram_gb() -> float | None:
    try:
        if os.name == "nt":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                            ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]

            status = Status()
            status.l = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.avail / 2**30
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 2**20
    except Exception:
        return None
    return None


def preflight() -> list[str]:
    """Return a list of problems (empty means ready)."""
    sys.path.insert(0, str(ROOT))
    problems = []
    if sys.version_info < (3, 10):
        problems.append(f"Python {sys.version.split()[0]} is too old; install Python 3.11 or newer.")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            problems.append(f"{tool} not found on PATH (Windows: winget install Gyan.FFmpeg, then reopen the terminal).")
    try:
        from PIL import features

        if not features.check("raqm"):
            problems.append("Pillow has no RAQM Arabic shaping on this machine; run in WSL2 Ubuntu or Docker instead "
                            "(rendering refuses to run rather than produce broken Arabic).")
    except ImportError:
        problems.append("Pillow missing: run  pip install -r requirements.txt")
    try:
        from newsflow import rendering

        rendering._font_path(False)
        rendering._font_path(True)
    except Exception as exc:  # noqa: BLE001 - report any import or font problem plainly
        problems.append(f"Arabic font check failed: {exc}")
    if not any(os.getenv(k) or _env_has(k) for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY")):
        problems.append("PEXELS_API_KEY or PIXABAY_API_KEY missing (put one in .env; --render-only needs a B-roll key).")
    ram = _ram_gb()
    if ram is not None and ram < 2.5:
        problems.append(f"Only {ram:.1f} GB RAM free; close browsers and other apps before rendering.")
    return problems


def _env_has(key: str) -> bool:
    env = ROOT / ".env"
    return env.is_file() and any(line.strip().startswith(key + "=") and len(line.split("=", 1)[1].strip()) > 0
                                 for line in env.read_text(encoding="utf-8").splitlines())


def run() -> int:
    problems = preflight()
    for problem in problems:
        print("[LOCAL_PREFLIGHT_FAIL]", problem)
    if problems:
        return 2
    print("[LOCAL_PREFLIGHT_OK]")
    if "--check" in sys.argv:
        return 0
    env = dict(os.environ)
    env.setdefault("NEWSFLOW_FFMPEG_THREADS", LOW_MEMORY_THREADS)
    env["YOUTUBE_UPLOAD_ENABLED"] = "false"
    env["YOUTUBE_PRIVACY_STATUS"] = "private"
    env["NEWSFLOW_PRIVATE_STAGING"] = "false"
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.time()
    code = subprocess.call([sys.executable, "-m", "newsflow", "--render-only"], cwd=ROOT, env=env)
    minutes = round((time.time() - started) / 60, 2)
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    log = out / "local_render_log.json"
    history = json.loads(log.read_text(encoding="utf-8")) if log.is_file() else []
    history.append({"finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "exit_code": code,
                    "minutes": minutes, "ffmpeg_threads": env["NEWSFLOW_FFMPEG_THREADS"]})
    log.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[LOCAL_RENDER_DONE] exit={code} minutes={minutes}")
    return code


if __name__ == "__main__":
    sys.exit(run())
