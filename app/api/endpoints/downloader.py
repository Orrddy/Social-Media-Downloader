from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel
from app.services.ytdlp_service import ytdlp_service
from app.services.ffmpeg_service import ffmpeg_service
from app.utils.validators import validate_url
from app.core.security import limiter
from app.core.config import settings
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

class DownloadRequest(BaseModel):
    url: str

@router.post("/download")
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_download_options(request: Request, body: DownloadRequest):
    """
    Returns metadata and download options for a given URL.
    """
    url = body.url
    if not validate_url(url):
        raise HTTPException(status_code=400, detail="Unsupported platform or invalid URL")
    
    try:
        data = await ytdlp_service.get_metadata(url)
        return data
    except Exception as e:
        logger.error(f"Download options error for {url}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stream")
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def stream_media(
    request: Request, 
    url: str = Query(..., description="The media URL to stream"),
    type: str = Query(..., description="Format type: video or audio"),
    quality: str = Query(None, description="Requested quality (e.g., 720p, mp3)")
):
    """
    Streams media content. Currently handles on-the-fly MP3 conversion for audio requests.
    """
    if not validate_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL")
    
    if type == "audio":
        try:
            return await ffmpeg_service.stream_audio_as_mp3(url)
        except Exception as e:
            logger.error(f"Streaming error for {url}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # For video, redirect directly to the signed source URL as requested
    # We use a 307 Temporary Redirect to ensure the browser handles the download
    from fastapi.responses import RedirectResponse
    try:
        data = await ytdlp_service.get_metadata(url)
        # Find the specific format requested or default to first video
        target_url = None
        for f in data.get("formats", []):
            if f["type"] == "video" and (not quality or f["quality"] == quality):
                target_url = f["url"]
                break
        
        if not target_url:
            # Fallback to any video format
            for f in data.get("formats", []):
                if f["type"] == "video":
                    target_url = f["url"]
                    break
        
        if target_url:
            return RedirectResponse(url=target_url)
        
        raise HTTPException(status_code=404, detail="Requested video format not found")
    except Exception as e:
        logger.error(f"Redirect error for {url}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resolve direct download link: {str(e)}")
