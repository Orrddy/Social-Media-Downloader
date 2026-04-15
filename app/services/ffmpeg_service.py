import subprocess
import yt_dlp
import asyncio
from fastapi.responses import StreamingResponse
import logging
import os

logger = logging.getLogger(__name__)

class FfmpegService:
    async def stream_audio_as_mp3(self, url: str):
        """
        Extracts the audio stream URL using yt-dlp and pipes it through FFmpeg to output MP3.
        """
        loop = asyncio.get_event_loop()
        
        # 1. Get the direct audio stream URL
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
            logger.error(f"Error getting stream URL: {e}")
            raise Exception(f"Failed to get audio stream: {str(e)}")

        # 2. Prepare FFmpeg command for piped production
        # -i: input stream
        # -vn: no video
        # -ab: bitrate
        # -f mp3: output format
        # pipe:1: output to stdout
        command = [
            'ffmpeg',
            '-i', stream_url,
            '-vn',
            '-ar', '44100',
            '-ac', '2',
            '-b:a', '192k',
            '-f', 'mp3',
            'pipe:1'
        ]

        # 3. Create the process
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        async def generate():
            try:
                while True:
                    chunk = await process.stdout.read(65536) # 64KB chunks
                    if not chunk:
                        break
                    yield chunk
            except Exception as e:
                logger.error(f"Streaming error: {e}")
            finally:
                if process.returncode is None:
                    try:
                        process.kill()
                    except:
                        pass

        filename = f"{title}.mp3".replace("/", "_")
        return StreamingResponse(
            generate(),
            media_type="audio/mpeg",
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )

ffmpeg_service = FfmpegService()
