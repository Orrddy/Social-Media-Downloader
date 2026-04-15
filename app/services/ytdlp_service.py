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
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'no_color': True,
            'geo_bypass': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios'],
                    'skip': ['hls', 'dash']
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'en-US,en;q=0.9',
            }
        }

    async def get_metadata(self, url: str) -> Dict[str, Any]:
        loop = asyncio.get_event_loop()
        try:
            # We create a new instance per request to avoid state issues
            info = await loop.run_in_executor(
                None, 
                lambda: yt_dlp.YoutubeDL(self.ydl_opts).extract_info(url, download=False)
            )
            
            if not info:
                raise Exception("Could not find any media at this URL.")
                
            return self._process_info(info, url)
        except Exception as e:
            logger.error(f"Error extracting metadata for {url}: {e}")
            raise Exception(f"Failed to extract metadata: {str(e)}")

    def _process_info(self, info: Dict[str, Any], original_url: str) -> Dict[str, Any]:
        formats = []
        raw_formats = info.get("formats", [])

        # 1. Broad Filter for Video/Audio streams
        for f in raw_formats:
            if not f.get("url"):
                continue
            
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            height = f.get("height")
            ext = f.get("ext", "")
            
            # Identify Video Formats
            # We check for height OR vcodec. Some platforms (TikTok) don't label vcodec well.
            if (vcodec != "none" or height) and ext != "m3u8":
                res = height
                # Try to get a human-readable quality
                quality = f"{res}p" if res else f.get("format_note") or f.get("format_id", "Video")
                
                # TikTok specific mapping for "HD"
                if "tiktok" in original_url.lower() and not res:
                    if "hd" in quality.lower():
                        quality = "HD Video"
                    else:
                        quality = "Normal Video"

                formats.append({
                    "type": "video",
                    "quality": quality,
                    "url": f.get("url"),
                    "ext": ext,
                    "filesize": f.get("filesize") or f.get("filesize_approx")
                })

        # 2. Add Audio (MP3) Option via our internal proxy
        formats.append({
            "type": "audio",
            "quality": "mp3",
            "url": f"/api/stream?url={original_url}&type=audio"
        })

        # 3. Clean and Deduplicate
        processed_formats = self._deduplicate_formats(formats)

        return {
            "title": info.get("title", "Unknown Title"),
            "thumbnail": info.get("thumbnail") or (info.get("thumbnails", [{}])[-1].get("url") if info.get("thumbnails") else None),
            "duration": self._format_duration(info.get("duration")),
            "platform": info.get("extractor_key", "unknown").lower(),
            "formats": processed_formats
        }

    def _format_duration(self, seconds: Optional[int]) -> str:
        if seconds is None:
            return "00:00"
        mins, secs = divmod(int(seconds), 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def _deduplicate_formats(self, formats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        unique_formats = []
        
        # Sort by resolution (if numeric) to keep best
        def sort_key(x):
            if x["type"] == "audio": return -1
            try:
                return int(x["quality"].replace("p", ""))
            except:
                return 0

        sorted_formats = sorted(formats, key=sort_key, reverse=True)

        for f in sorted_formats:
            key = (f["type"], f["quality"])
            if key not in seen:
                unique_formats.append(f)
                seen.add(key)
        
        # Return in a nice display order (Audio last)
        return sorted(unique_formats, key=lambda x: x["type"], reverse=True)

ytdlp_service = YtdlpService()
