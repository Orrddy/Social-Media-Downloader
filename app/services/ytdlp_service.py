import yt_dlp
import asyncio
import copy
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


class YtdlpService:
    def __init__(self):
        import os
        self._base_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'best',
            'extract_flat': False,
            'nocheckcertificate': True,
            'no_color': True,
            'geo_bypass': True,
            # YouTube-specific bypass attempts
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

        # Inject cookies file at runtime if present (do not commit cookies.txt to git)
        cookie_path = os.path.join(os.getcwd(), "cookies.txt")
        if os.path.exists(cookie_path):
            self._base_opts['cookiefile'] = cookie_path

    def _build_opts(self, url: str) -> Dict[str, Any]:
        """
        Return a deep-copied options dict with per-platform Referer headers.
        Deep copy is essential — mutating http_headers on a shallow copy would
        permanently corrupt the shared _base_opts dict.
        """
        opts = copy.deepcopy(self._base_opts)
        if "tiktok" in url:
            opts['http_headers']['Referer'] = 'https://www.tiktok.com/'
        elif "instagram" in url:
            opts['http_headers']['Referer'] = 'https://www.instagram.com/'
        return opts

    async def get_metadata(self, url: str) -> Dict[str, Any]:
        # Use get_running_loop() — get_event_loop() is deprecated in Python 3.10+
        loop = asyncio.get_running_loop()
        opts = self._build_opts(url)
        try:
            info = await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False)
            )
            if not info:
                raise ValueError("Could not find any media at this URL.")
            return self._process_info(info)
        except Exception as e:
            logger.error(f"Error extracting metadata for {url}: {e}")
            raise Exception(f"Failed to extract metadata: {str(e)}")

    def _process_info(self, info: Dict[str, Any]) -> Dict[str, Any]:
        formats: List[Dict[str, Any]] = []
        raw_formats: List[Dict[str, Any]] = info.get('formats', [])

        # Sort by resolution descending so we keep the highest quality per label
        raw_formats.sort(key=lambda f: f.get('height') or 0, reverse=True)

        seen_qualities: set = set()

        for f in raw_formats:
            # Only include formats with BOTH video and audio (direct single-file download)
            # Skip HLS/M3U8 manifest streams — they cannot be proxied as a single byte range
            protocol = f.get('protocol', '')
            has_video = f.get('vcodec', 'none') != 'none'
            has_audio = f.get('acodec', 'none') != 'none'
            is_manifest = 'm3u8' in protocol or 'hls' in protocol

            if not (has_video and has_audio and not is_manifest):
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

            # One format per quality tier to keep the UI clean
            if quality_label not in seen_qualities:
                formats.append({
                    "id": f.get("format_id"),
                    # NOTE: 'url' is intentionally omitted from the public response.
                    # CDN URLs are signed and IP-locked to the server; they must be
                    # fetched server-side at download time via the /stream endpoint.
                    "ext": ext,
                    "quality": quality_label,
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                    "type": "video",
                    "height": height
                })
                seen_qualities.add(quality_label)

        # Best audio-only stream (converted to MP3 via FFmpeg on the /stream endpoint)
        best_audio = None
        for f in raw_formats:
            if f.get('vcodec') == 'none' and f.get('acodec') != 'none' and f.get('url'):
                if not best_audio or (f.get('abr') or 0) > (best_audio.get('abr') or 0):
                    best_audio = f

        if best_audio:
            formats.append({
                "id": best_audio.get("format_id"),
                # 'url' omitted — see note above
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


ytdlp_service = YtdlpService()
