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
    
    # For video, proxy the bytes to ensure '1-click' download and bypass hotlinking
    import httpx
    from fastapi.responses import StreamingResponse
    try:
        data = await ytdlp_service.get_metadata(url)
        target_format = None
        for f in data.get("formats", []):
            if f["type"] == "video" and (not quality or f["quality"] == quality):
                target_format = f
                break
        
        if not target_format:
            for f in data.get("formats", []):
                if f["type"] == "video":
                    target_format = f
                    break
        
        if not target_format:
            raise HTTPException(status_code=404, detail="Requested video format not found")

        # We proxy the request to force a download attachment behavior
        async def generate_video_stream():
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                async with client.stream("GET", target_format["url"], headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
                }) as r:
                    async for chunk in r.aiter_bytes():
                        yield chunk

        filename = f"{data['title'][:50]}.{target_format.get('ext', 'mp4')}"
        # Ensure filename is URL-safeish if needed, or let browser handle
        return StreamingResponse(
            generate_video_stream(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename=\"{filename}\""
            }
        )

    except Exception as e:
        logger.error(f"Proxy error for {url}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate download: {str(e)}")
