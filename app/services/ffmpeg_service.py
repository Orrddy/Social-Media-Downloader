import subprocess
import yt_dlp
import asyncio
import urllib.parse
from fastapi.responses import StreamingResponse
import logging
import os

logger = logging.getLogger(__name__)


class FfmpegService:
    async def stream_audio_as_mp3(self, url: str) -> StreamingResponse:
        """
        Extracts the best audio stream URL via yt-dlp and pipes it through
        FFmpeg to produce an MP3 stream. Returned as a StreamingResponse.
        """
        # Use get_running_loop() — get_event_loop() is deprecated in Python 3.10+
        loop = asyncio.get_running_loop()

        def get_stream_url():
            ydl_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get('url'), info.get('title', 'audio')

        try:
            stream_url, title = await loop.run_in_executor(None, get_stream_url)
        except Exception as e:
            logger.error(f"Error getting stream URL for audio: {e}")
            raise Exception(f"Failed to get audio stream: {str(e)}")

        # FFmpeg command: read from stream URL, output MP3 to stdout
        command = [
            'ffmpeg',
            '-i', stream_url,
            '-vn',           # no video
            '-ar', '44100',  # sample rate
            '-ac', '2',      # stereo
            '-b:a', '192k',  # bitrate
            '-f', 'mp3',
            'pipe:1'         # stdout
        ]

        # stderr → DEVNULL to prevent OS pipe-buffer deadlock.
        # When stderr fills its buffer (~64 KB) and is never read, FFmpeg blocks
        # waiting for the parent to drain it — causing the streaming generator
        # to deadlock on stdout. Discarding stderr avoids this entirely.
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )

        async def generate():
            try:
                while True:
                    chunk = await process.stdout.read(65536)  # 64 KB chunks
                    if not chunk:
                        break
                    yield chunk
            except Exception as e:
                logger.error(f"Audio streaming error: {e}")
            finally:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass  # Process already exited — acceptable
                    except Exception as kill_err:
                        logger.warning(f"Could not kill FFmpeg process: {kill_err}")

        # Build a safe ASCII filename with UTF-8 fallback (RFC 5987)
        safe_title = "".join(
            c for c in title if c.isalnum() or c in (' ', '-', '_')
        ).strip()[:50] or "audio"
        filename = f"{safe_title}.mp3"
        encoded_filename = urllib.parse.quote(filename)

        return StreamingResponse(
            generate(),
            media_type="audio/mpeg",
            headers={
                # filename= is ASCII-safe; filename*= carries the full UTF-8 name (RFC 5987)
                "Content-Disposition": (
                    f'attachment; filename="{filename.encode("ascii", "ignore").decode()}"; '
                    f"filename*=UTF-8''{encoded_filename}"
                )
            }
        )


ffmpeg_service = FfmpegService()
