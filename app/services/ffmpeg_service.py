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
        try:
            from app.services.ytdlp_service import ytdlp_service
            stream_url, title = await ytdlp_service.get_best_audio_info(url)
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
            except asyncio.CancelledError:
                pass  # Request cut off
            except Exception as e:
                logger.error(f"Audio streaming error: {e}")
            finally:
                if process.returncode is None:
                    try:
                        process.kill()
                        await process.wait()  # <--- REQUIRED to reap the zombie UNIX process
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

    async def stream_video_ffmpeg(self, stream_url: str, filename: str) -> StreamingResponse:
        """
        Pipes an M3U8 or DASH stream through FFmpeg and exports directly as an MP4 byte stream.
        This provides compatibility for Instagram/Twitter videos that exclusively use manifests.
        """
        # FFmpeg command: stream input, copy codecs, fragment it to allow piped MP4 streaming
        command = [
            'ffmpeg',
            '-i', stream_url,
            '-c', 'copy',
            '-f', 'mp4',
            '-movflags', 'frag_keyframe+empty_moov',
            'pipe:1'
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )

        async def generate():
            try:
                while True:
                    chunk = await process.stdout.read(65536)
                    if not chunk:
                        break
                    yield chunk
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"FFmpeg MP4 streaming error: {e}")
            finally:
                if process.returncode is None:
                    try:
                        process.kill()
                        await process.wait()
                    except ProcessLookupError:
                        pass
                    except Exception as kill_err:
                        logger.warning(f"Could not kill FFmpeg process: {kill_err}")

        encoded_filename = urllib.parse.quote(filename)
        return StreamingResponse(
            generate(),
            media_type="video/mp4",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename.encode("ascii", "ignore").decode()}"; '
                    f"filename*=UTF-8''{encoded_filename}"
                )
            }
        )


ffmpeg_service = FfmpegService()
