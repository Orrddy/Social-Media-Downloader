import http.cookiejar
import urllib.parse
import httpx
import asyncio
import logging
import os

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.ytdlp_service import ytdlp_service
from app.services.ffmpeg_service import ffmpeg_service
from app.utils.validators import validate_url
from app.utils.helpers import sanitize_filename, build_content_disposition
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
        logger.error(f"Metadata extraction error for {url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to extract media information. Please try again.")


@router.get("/stream")
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def stream_media(
    request: Request,
    url: str = Query(..., description="Original social media URL"),
    type: str = Query(..., description="'video' or 'audio'"),
    format_id: str = Query(None, description="yt-dlp format_id (fast path — skips metadata re-fetch)"),
    quality: str = Query(None, description="Quality label fallback if format_id not provided"),
    ext: str = Query("mp4", description="File extension hint for Content-Disposition filename"),
):
    """
    Streams media content.
    - Audio: converted to MP3 via FFmpeg.
    - Video (fast path): format_id resolves directly to a live CDN URL — one yt-dlp call.
    - Video (fallback): quality label used when format_id absent — re-fetches metadata.
    The proxy pattern hides CDN URLs from the client and handles IP-locked signed links.
    """
    if not validate_url(url):
        raise HTTPException(status_code=400, detail="Invalid or unsupported URL")

    # ── Audio ──────────────────────────────────────────────────────────────────
    if type == "audio":
        try:
            return await ffmpeg_service.stream_audio_as_mp3(url)
        except Exception as e:
            logger.error(f"Audio streaming error for {url}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to stream audio.")

    # ── Video ──────────────────────────────────────────────────────────────────
    try:
        cdn_url: str | None = None
        http_headers: dict = {}
        resolved_title = "download"

        # Fast path: format_id supplied by the frontend (single yt-dlp call)
        if format_id:
            try:
                cdn_url, http_headers, resolved_ext = await ytdlp_service.get_stream_url(url, format_id)
                ext = resolved_ext or ext
            except Exception as e:
                logger.error(f"Fast-path CDN resolution failed for format '{format_id}': {e}", exc_info=True)
                cdn_url = None  # fall through to slow path

        # Slow path: quality label match — only used when format_id not provided
        if not cdn_url:
            data = await ytdlp_service.get_metadata(url)
            resolved_title = data.get("title", "download")

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

            ext = target_format.get("ext", ext)
            try:
                cdn_url, http_headers, _ = await ytdlp_service.get_stream_url(
                    url, target_format.get("id")
                )
            except Exception as e:
                logger.error(f"Slow-path CDN resolution failed: {e}", exc_info=True)

        if not cdn_url:
            raise HTTPException(status_code=502, detail="Could not resolve a direct download URL")

        # Build safe filename for Content-Disposition
        filename = f"{sanitize_filename(resolved_title)}.{ext}"

        # Route manifest streams (M3U8/DASH) through FFmpeg for remuxing
        is_manifest = ".m3u8" in cdn_url.lower() or ".mpd" in cdn_url.lower()
        if is_manifest:
            return await ffmpeg_service.stream_video_ffmpeg(cdn_url, filename)

        # ── Direct byte-range proxy ────────────────────────────────────────────
        # Use base opts headers as fallback when format-specific headers are absent
        if not http_headers:
            base_opts = ytdlp_service._build_opts(url)
            http_headers = base_opts.get("http_headers", {})

        # Load platform cookies into httpx for CDN session validation
        httpx_cookies = httpx.Cookies()
        base_opts = ytdlp_service._build_opts(url)
        cookie_file = base_opts.get('cookiefile')
        if cookie_file and os.path.exists(cookie_file):
            try:
                cj = http.cookiejar.MozillaCookieJar(cookie_file)
                cj.load(ignore_discard=True, ignore_expires=True)
                for cookie in cj:
                    httpx_cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
            except Exception as e:
                logger.error(f"Failed to load cookies: {e}", exc_info=True)

        # Open the httpx client; ensure it's closed on ALL code paths (error + success)
        client = httpx.AsyncClient(timeout=60.0, follow_redirects=True, cookies=httpx_cookies)
        try:
            req = client.build_request("GET", cdn_url, headers=http_headers)
            r = await client.send(req, stream=True)
        except Exception as e:
            await client.aclose()
            logger.error(f"CDN request failed for {url}: {e}", exc_info=True)
            raise HTTPException(status_code=502, detail="Upstream CDN request failed.")

        if r.status_code != 200:
            await r.aclose()
            await client.aclose()
            raise HTTPException(status_code=502, detail=f"Upstream CDN responded with {r.status_code}")

        response_headers = {"Content-Disposition": build_content_disposition(filename)}
        if "Content-Length" in r.headers:
            response_headers["Content-Length"] = r.headers["Content-Length"]

        async def generate_video_stream():
            try:
                async for chunk in r.aiter_bytes(chunk_size=65536):
                    yield chunk
            except asyncio.CancelledError:
                pass  # Client disconnected
            finally:
                # Always close — even if CancelledError interrupted the loop
                await r.aclose()
                await client.aclose()

        return StreamingResponse(
            generate_video_stream(),
            media_type=r.headers.get("Content-Type", "application/octet-stream"),
            headers=response_headers
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Video proxy error for {url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate download. Please try again.")
