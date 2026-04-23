import shutil
import yt_dlp
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Dependency health check — verifies FFmpeg is on PATH and yt-dlp is loaded.
    Returns 'degraded' (not 'healthy') if critical dependencies are missing,
    allowing Render's health checks to detect a broken container state.
    """
    ffmpeg_ok = shutil.which("ffmpeg") is not None

    try:
        ytdlp_version = yt_dlp.version.__version__
        ytdlp_ok = True
    except Exception:
        ytdlp_version = "unknown"
        ytdlp_ok = False

    all_ok = ffmpeg_ok and ytdlp_ok

    return {
        "status": "healthy" if all_ok else "degraded",
        "ffmpeg": ffmpeg_ok,
        "yt_dlp": ytdlp_ok,
        "yt_dlp_version": ytdlp_version,
    }
