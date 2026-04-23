import yt_dlp
import asyncio
import atexit
import copy
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Tuple

from cachetools import TTLCache

from app.utils.validators import get_platform

logger = logging.getLogger(__name__)

# Bounded executor — prevents unbounded thread spawning under concurrent load.
# Tune max_workers to (CPU cores * 2) for IO-bound yt-dlp extractions.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ytdlp")

# Metadata TTL cache — avoids redundant yt-dlp calls for repeat URLs within 60s.
# maxsize=256 keeps memory bounded; TTL matches CDN signed URL validity windows.
_metadata_cache: TTLCache = TTLCache(maxsize=256, ttl=60)


class YtdlpService:
    def __init__(self):
        self._base_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            # NOTE: nocheckcertificate is required — several platform CDNs serve
            # content through domains with cert chains that yt-dlp's bundled CA
            # store doesn't recognise. Removing this causes widespread 403s.
            'nocheckcertificate': True,
            'no_color': True,
            'geo_bypass': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['web', 'web_embedded', 'ios', 'mweb'],
                    'player_skip': ['hls', 'dash']
                }
            },
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/123.0.0.0 Safari/537.36'
                ),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.google.com/'
            }
        }

        # Cookie injection — env var wins over local file.
        env_cookies = os.environ.get("YTDLP_COOKIES")
        cookie_path = os.path.join(os.getcwd(), "cookies.txt")

        if env_cookies:
            fd, temp_cookie_path = tempfile.mkstemp(suffix=".txt", text=True)
            with os.fdopen(fd, 'w') as f:
                f.write(env_cookies)
            self._base_opts['cookiefile'] = temp_cookie_path
            # Ensure temp file is cleaned up when the process exits
            atexit.register(os.unlink, temp_cookie_path)
            logger.info("Loaded yt-dlp cookies from YTDLP_COOKIES environment variable.")
        elif os.path.exists(cookie_path):
            self._base_opts['cookiefile'] = cookie_path
            logger.info("Loaded yt-dlp cookies from local cookies.txt file.")

    def _build_opts(self, url: str) -> Dict[str, Any]:
        """
        Returns a deep-copied options dict with per-platform Referer headers.
        Uses the validated get_platform() util — not a fragile substring check.
        Deep copy is essential to avoid mutating shared _base_opts.
        """
        opts = copy.deepcopy(self._base_opts)
        platform_referers = {
            'tiktok': 'https://www.tiktok.com/',
            'instagram': 'https://www.instagram.com/',
            'twitter': 'https://twitter.com/',
            'facebook': 'https://www.facebook.com/',
        }
        platform = get_platform(url)
        if platform in platform_referers:
            opts['http_headers']['Referer'] = platform_referers[platform]
        return opts

    async def get_metadata(self, url: str) -> Dict[str, Any]:
        # Return cached result if available (avoids redundant platform API calls)
        if url in _metadata_cache:
            logger.debug(f"Cache hit for metadata: {url}")
            return _metadata_cache[url]

        loop = asyncio.get_running_loop()
        opts = self._build_opts(url)
        try:
            info = await loop.run_in_executor(
                _executor,
                lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False)
            )
            if not info:
                raise ValueError("Could not find any media at this URL.")
            result = self._process_info(info)
            _metadata_cache[url] = result
            return result
        except Exception as e:
            logger.error(f"Error extracting metadata for {url}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to extract metadata: {str(e)}") from e

    def _process_info(self, info: Dict[str, Any]) -> Dict[str, Any]:
        formats: List[Dict[str, Any]] = []
        raw_formats: List[Dict[str, Any]] = info.get('formats', [])

        # Sort by resolution descending so highest quality wins per label
        raw_formats.sort(key=lambda f: f.get('height') or 0, reverse=True)

        seen_qualities: set = set()

        for f in raw_formats:
            protocol = f.get('protocol', '')
            has_video = f.get('vcodec', 'none') != 'none'
            is_manifest = 'm3u8' in protocol or 'hls' in protocol

            if not has_video or is_manifest:
                continue
            if not f.get('url'):
                continue

            height = f.get('height') or 0
            ext = f.get('ext') or 'mp4'

            if height >= 2160:
                quality_label = "4K Ultra HD"
            elif height >= 1440:
                quality_label = "2K Quad HD"
            elif height >= 1080:
                quality_label = "1080p Full HD"
            elif height >= 720:
                quality_label = "720p HD"
            elif height >= 480:
                quality_label = "480p"
            else:
                quality_label = "Standard"

            if quality_label not in seen_qualities:
                formats.append({
                    "id": f.get("format_id"),
                    # NOTE: 'url' intentionally omitted — CDN URLs are IP-locked to
                    # the server and must be re-resolved server-side at stream time.
                    "ext": ext,
                    "quality": quality_label,
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                    "type": "video",
                    "height": height
                })
                seen_qualities.add(quality_label)

        # Best audio-only stream — prefer explicit audio-only (vcodec==none)
        # Falls back to 'bestaudio' selection if no audio-only track found
        best_audio = None
        for f in raw_formats:
            if f.get('vcodec') == 'none' and f.get('acodec') != 'none' and f.get('url'):
                if not best_audio or (f.get('abr') or 0) > (best_audio.get('abr') or 0):
                    best_audio = f

        if best_audio:
            formats.append({
                "id": best_audio.get("format_id"),
                "ext": "mp3",
                "quality": f"{int(best_audio.get('abr') or 128)}kbps Audio",
                "filesize": best_audio.get("filesize") or best_audio.get("filesize_approx"),
                "type": "audio"
            })

        return {
            "title": info.get("title", "Unknown Title"),
            "thumbnail": info.get("thumbnail"),
            "duration": self._format_duration(info.get("duration")),
            "platform": info.get("extractor_key", "unknown").lower(),
            "formats": formats
        }

    def _format_duration(self, seconds: Optional[int]) -> str:
        if seconds is None:
            return "00:00"
        mins, secs = divmod(int(seconds), 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    async def get_stream_url(self, url: str, format_id: str = None) -> Tuple[Optional[str], Dict, str]:
        """
        Resolves a live CDN URL for the given format_id.

        Returns:
            (cdn_url, http_headers, ext) — ext defaults to 'mp4' if unknown.

        Uses the bounded _executor to prevent thread exhaustion under load.
        """
        loop = asyncio.get_running_loop()
        opts = self._build_opts(url)
        opts['format'] = format_id if format_id else 'best'

        def _extract() -> Tuple[Optional[str], Dict, str]:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            # Prefer top-level url (set when format is resolved to a single stream)
            cdn_url = info.get('url')
            http_headers = info.get('http_headers', {})
            ext = info.get('ext', 'mp4')

            # Fall back to last format entry
            if not cdn_url and info.get('formats'):
                last_fmt = info['formats'][-1]
                cdn_url = last_fmt.get('url')
                http_headers = last_fmt.get('http_headers', http_headers)
                ext = last_fmt.get('ext', ext)

            return cdn_url, http_headers, (ext or 'mp4')

        return await loop.run_in_executor(_executor, _extract)

    async def get_best_audio_info(self, url: str) -> Tuple[Optional[str], str]:
        """
        Returns (stream_url, title) for the best available audio track.
        Uses 'bestaudio[ext=m4a]/bestaudio' to avoid pulling a full video stream.
        """
        loop = asyncio.get_running_loop()
        opts = self._build_opts(url)
        # Prefer m4a audio, then any audio-only, then best as last resort
        opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'

        def _extract() -> Tuple[Optional[str], str]:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'audio')

        return await loop.run_in_executor(_executor, _extract)


ytdlp_service = YtdlpService()
