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
    import urllib.parse
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
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                async with client.stream("GET", target_format["url"], headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                    'Referer': target_format.get('url', '')
                }) as r:
                    # Capture the original content type if available
                    content_type = r.headers.get("Content-Type", "application/octet-stream")
                    async for chunk in r.aiter_bytes():
                        yield chunk

        # Clean filename and encode for HTTP headers (avoids latin-1 errors with emojis)
        safe_title = "".join([c for c in data['title'] if c.isalnum() or c in (' ', '-', '_')]).strip()[:50]
        if not safe_title: safe_title = "download"
        
        filename = f"{safe_title}.{target_format.get('ext', 'mp4')}"
        encoded_filename = urllib.parse.quote(filename)
        
        return StreamingResponse(
            generate_video_stream(),
            media_type="application/octet-stream",
            headers={
                # filename* uses RFC 5987 to support non-ASCII (emojis) correctly
                "Content-Disposition": f"attachment; filename=\"{filename.encode('ascii', 'ignore').decode()}\"; filename*=UTF-8''{encoded_filename}"
            }
        )

    except Exception as e:
        logger.error(f"Proxy error for {url}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate download: {str(e)}")
