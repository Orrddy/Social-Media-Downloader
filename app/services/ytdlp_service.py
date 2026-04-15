import yt_dlp
import asyncio
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

class YtdlpService:
    def __init__(self):
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'best',
            'extract_flat': False,
        }

    async def get_metadata(self, url: str) -> Dict[str, Any]:
        """
        Extracts metadata from the given URL using yt-dlp.
        Runs the blocking extract_info in a separate thread.
        """
        loop = asyncio.get_event_loop()
        try:
            # download=False only extracts information
            info = await loop.run_in_executor(
                None, 
                lambda: yt_dlp.YoutubeDL(self.ydl_opts).extract_info(url, download=False)
            )
            return self._process_info(info, url)
        except Exception as e:
            logger.error(f"Error extracting metadata for {url}: {e}")
            raise Exception(f"Failed to extract metadata: {str(e)}")

    def _process_info(self, info: Dict[str, Any], original_url: str) -> Dict[str, Any]:
        """
        Filters and structures the raw yt-dlp info into the requested format.
        """
        formats = []
        raw_formats = info.get("formats", [])

        # 1. Filter Video Formats (Common quality levels)
        # We look for formats with both video and audio, or just high-quality video
        for f in raw_formats:
            # Skip formats without a URL or with DRM
            if not f.get("url"):
                continue
            
            ext = f.get("ext", "")
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            
            # Simple heuristic for "video" type
            if vcodec != "none":
                res = f.get("height")
                quality = f"{res}p" if res else f.get("format_note", "Video")
                formats.append({
                    "type": "video",
                    "quality": quality,
                    "url": f.get("url")
                })

        # 2. Add Audio (MP3) Option
        # For audio, we'll provide a local API proxy link so we can convert on-the-fly
        # because yt-dlp gives raw audio streams (m4a, webm).
        # The proxy will use /api/stream?url=...&type=audio
        formats.append({
            "type": "audio",
            "quality": "mp3",
            "url": f"/api/stream?url={original_url}&type=audio"
        })

        return {
            "title": info.get("title", "Unknown Title"),
            "thumbnail": info.get("thumbnail") or (info.get("thumbnails", [{}])[0].get("url") if info.get("thumbnails") else None),
            "duration": self._format_duration(info.get("duration")),
            "formats": self._deduplicate_formats(formats)
        }

    def _format_duration(self, seconds: Optional[int]) -> str:
        if seconds is None:
            return "00:00"
        mins, secs = divmod(seconds, 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def _deduplicate_formats(self, formats: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Keeps only the best version of each quality level.
        """
        seen = set()
        unique_formats = []
        for f in formats:
            key = (f["type"], f["quality"])
            if key not in seen:
                unique_formats.append(f)
                seen.add(key)
        return unique_formats

ytdlp_service = YtdlpService()
