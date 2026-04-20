import urllib.parse
import httpx
import yt_dlp
import asyncio
import copy
import logging

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.ytdlp_service import ytdlp_service
from app.services.ffmpeg_service import ffmpeg_service
from app.utils.validators import validate_url
from app.core.security import limiter
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


class DownloadRequest(BaseModel):
    url: str


@router.post("/download")
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_download_options(request: Request, body: DownloadRequest):
    """
    Extracts metadata and available download formats for a given URL.
    CDN URLs are NOT returned — format IDs are used instead and resolved
    server-side at download time via the /stream endpoint.
    """
    url = body.url.strip()
    if not validate_url(url):
        raise HTTPException(status_code=400, detail="Unsupported platform or invalid URL")

    try:
        data = await ytdlp_service.get_metadata(url)
        return data
    except Exception as e:
        logger.error(f"Metadata extraction error for {url}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream")
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def stream_media(
    request: Request,
    url: str = Query(..., description="The original social media URL to download"),
    type: str = Query(..., description="Format type: 'video' or 'audio'"),
    quality: str = Query(None, description="Quality label, e.g. '1080p Full HD', '720p HD'")
):
    """
    Streams media content. For audio, converts to MP3 via FFmpeg.
    For video, re-extracts the CDN URL server-side and proxies the bytes,
    which forces a 'Save As' dialog and avoids IP-locked CDN link issues.
    """
    if not validate_url(url):
        raise HTTPException(status_code=400, detail="Invalid or unsupported URL")

    if type == "audio":
        try:
            return await ffmpeg_service.stream_audio_as_mp3(url)
        except Exception as e:
            logger.error(f"Audio streaming error for {url}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # --- Video: re-fetch metadata to get a fresh, server-side CDN URL ---
    try:
        data = await ytdlp_service.get_metadata(url)

        # Match the requested quality label
        target_format = None
        for f in data.get("formats", []):
            if f["type"] == "video" and (not quality or f["quality"] == quality):
                target_format = f
                break

        # Fallback to any available video format
        if not target_format:
            for f in data.get("formats", []):
                if f["type"] == "video":
                    target_format = f
                    break

        if not target_format:
            raise HTTPException(status_code=404, detail="Requested video format not found")

        # Get the live CDN URL server-side using the format_id securely
        format_id = target_format.get("id")
        try:
            cdn_url = await ytdlp_service.get_stream_url(url, format_id)
        except Exception as e:
            logger.error(f"CDN URL resolution failed for {url}: {e}")
            cdn_url = None

        if not cdn_url:
            raise HTTPException(status_code=502, detail="Could not resolve a direct download URL")

        # Build safe ASCII + UTF-8 RFC 5987 filename
        raw_title = data.get('title', 'download')
        safe_title = "".join(
            c for c in raw_title if c.isalnum() or c in (' ', '-', '_')
        ).strip()[:50] or "download"

        ext = target_format.get('ext', 'mp4')
        filename = f"{safe_title}.{ext}"
        encoded_filename = urllib.parse.quote(filename)

        # Route through FFmpeg if it's a playlist/manifest (used heavily by Twitter/Insta)
        is_manifest = ".m3u8" in cdn_url.lower() or ".mpd" in cdn_url.lower()
        if is_manifest:
            return await ffmpeg_service.stream_video_ffmpeg(cdn_url, filename)

        import http.cookiejar
        
        # critically important: yt-dlp attaches CDN-specific authorization headers (including Cookies) 
        # to the specific format object. We MUST forward these or we will get a 403 Forbidden.
        base_opts = ytdlp_service._build_opts(url)
        http_headers = target_format.get("http_headers")
        if not http_headers:
            http_headers = base_opts.get("http_headers", {})
            
        # Also parse the Netscape cookies file into httpx to ensure CDN session validation passes
        httpx_cookies = httpx.Cookies()
        cookie_file = base_opts.get('cookiefile')
        if cookie_file and os.path.exists(cookie_file):
            try:
                cj = http.cookiejar.MozillaCookieJar(cookie_file)
                cj.load(ignore_discard=True, ignore_expires=True)
                for cookie in cj:
                    httpx_cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
            except Exception as e:
                logger.error(f"Failed to load httpx cookies: {e}")

        # Initialize the client first to grab headers BEFORE response stream setup
        client = httpx.AsyncClient(timeout=60.0, follow_redirects=True, cookies=httpx_cookies)
        
        req = client.build_request("GET", cdn_url, headers=http_headers)
        r = await client.send(req, stream=True)

        if r.status_code != 200:
            await r.aclose()
            await client.aclose()
            raise HTTPException(status_code=502, detail=f"Upstream CDN responded with {r.status_code}")

        headers = {
            "Content-Disposition": (
                f'attachment; filename="{filename.encode("ascii", "ignore").decode()}"; '
                f"filename*=UTF-8''{encoded_filename}"
            )
        }
        
        # Inject content length for progress browser mapping
        if "Content-Length" in r.headers:
            headers["Content-Length"] = r.headers["Content-Length"]

        async def generate_video_stream():
            try:
                # 64KB generator chunks to prevent heavy active RAM buffering
                async for chunk in r.aiter_bytes(chunk_size=65536):
                    yield chunk
            except asyncio.CancelledError:
                pass # The client killed the download
            finally:
                await r.aclose()
                await client.aclose()

        return StreamingResponse(
            generate_video_stream(),
            media_type=r.headers.get("Content-Type", "application/octet-stream"),
            headers=headers
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Video proxy error for {url}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate download: {str(e)}")
