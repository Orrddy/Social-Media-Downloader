import yt_dlp
import asyncio
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)
class YtdlpService:
    def __init__(self):
        import os
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'best',
            'extract_flat': False,
            'nocheckcertificate': True,
            'no_color': True,
            'geo_bypass': True,
            # YouTube specific bypass attempts
            'extractor_args': {
                'youtube': {
                    'player_client': ['web', 'web_embedded', 'ios', 'mweb'],
                    'player_skip': ['hls', 'dash']
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.google.com/'
            }
        }
        
        # Fallback to cookies.txt if exists in the backend root
        cookie_path = os.path.join(os.getcwd(), "cookies.txt")
        if os.path.exists(cookie_path):
            self.ydl_opts['cookiefile'] = cookie_path

    async def get_metadata(self, url: str) -> Dict[str, Any]:
        loop = asyncio.get_event_loop()
        try:
            # We use a fresh YDL instance with specific referer for some platforms
            opts = self.ydl_opts.copy()
            if "tiktok" in url:
                opts['http_headers']['Referer'] = 'https://www.tiktok.com/'
            elif "instagram" in url:
                opts['http_headers']['Referer'] = 'https://www.instagram.com/'
            
            info = await loop.run_in_executor(
                None, 
                lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False)
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
        
        # YouTube specifically: look for highest quality single-file or best merged if available
        # However, for '1-click direct download', we MUST have a format with both audio and video
        
        raw_formats = info.get('formats', [])
        
        # 1. Try to find the absolute best video formats with integrated audio
        # We want to label 4K (2140p), 2K (1440p), HD (1080p), etc.
        
        seen_qualities = set()
        
        # Sort formats by resolution (height) descending
        raw_formats.sort(key=lambda x: x.get('height') or 0, reverse=True)
        
        for f in raw_formats:
            # We only want formats that have BOTH video and audio for direct downloading
            # acodec != 'none' means it has audio, vcodec != 'none' means it has video
            # CRITICAL: Filter out HLS/M3U8 playlists (manifests) as they are not playable via proxy
            protocol = f.get('protocol', '')
            if (f.get('vcodec') != 'none' and f.get('acodec') != 'none' and 
                'm3u8' not in protocol and 'hls' not in protocol):
                
                height = f.get('height') or 0
                ext = f.get('ext') or 'mp4'
                
                quality_label = f"Standard"
                if height >= 2160: quality_label = "4K Ultra HD"
                elif height >= 1440: quality_label = "2K Quad HD"
                elif height >= 1080: quality_label = "1080p Full HD"
                elif height >= 720: quality_label = "720p HD"
                elif height >= 480: quality_label = "480p"
                
                # We only need one format per quality label to keep UI clean
                if quality_label not in seen_qualities:
                    formats.append({
                        "id": f.get("format_id"),
                        "url": f.get("url"),
                        "ext": ext,
                        "quality": quality_label,
                        "filesize": f.get("filesize") or f.get("filesize_approx"),
                        "type": "video",
                        "height": height
                    })
                    seen_qualities.add(quality_label)
        
        # 2. Extract best audio if available
        best_audio = None
        for f in raw_formats:
            if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                if not best_audio or (f.get('abr') or 0) > (best_audio.get('abr') or 0):
                    best_audio = f
        
        if best_audio:
            formats.append({
                "id": best_audio.get("format_id"),
                "url": best_audio.get("url"),
                "ext": "mp3", # We convert to mp3 in the stream endpoint
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
