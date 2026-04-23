import asyncio
import logging
import urllib.parse
from fastapi.responses import StreamingResponse

from app.utils.helpers import sanitize_filename, build_content_disposition

logger = logging.getLogger(__name__)

# Maximum seconds to wait for FFmpeg to start producing output before aborting.
_FFMPEG_START_TIMEOUT = 30
# Maximum total seconds an FFmpeg process may run (prevents infinite hang on stalled CDN).
_FFMPEG_TOTAL_TIMEOUT = 600


class FfmpegService:
    async def stream_audio_as_mp3(self, url: str) -> StreamingResponse:
        """
        Extracts the best audio stream URL via yt-dlp and pipes it through
        FFmpeg to produce an MP3 stream returned as a StreamingResponse.
        """
        from app.services.ytdlp_service import ytdlp_service
        try:
            stream_url, title = await ytdlp_service.get_best_audio_info(url)
        except Exception as e:
            logger.error(f"Failed to get audio stream URL for {url}: {e}", exc_info=True)
            raise RuntimeError("Failed to get audio stream.") from e

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

        # stderr → DEVNULL prevents OS pipe-buffer deadlock:
        # when stderr fills its ~64 KB buffer and is never drained, FFmpeg blocks
        # waiting for the parent — deadlocking stdout. Discarding stderr avoids this.
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )

        async def generate():
            start_ok = False
            try:
                # First-byte timeout — kills stalled FFmpeg processes early
                first_chunk = await asyncio.wait_for(
                    process.stdout.read(65536),
                    timeout=_FFMPEG_START_TIMEOUT
                )
                if not first_chunk:
                    return
                yield first_chunk
                start_ok = True

                while True:
                    chunk = await process.stdout.read(65536)
                    if not chunk:
                        break
                    yield chunk
            except asyncio.TimeoutError:
                logger.error("FFmpeg audio process timed out waiting for first byte.")
            except asyncio.CancelledError:
                pass  # Client disconnected
            except Exception as e:
                logger.error(f"Audio streaming error: {e}", exc_info=True)
            finally:
                if process.returncode is None:
                    try:
                        process.kill()
                        # shield prevents a second CancelledError from leaving a zombie
                        await asyncio.shield(process.wait())
                    except ProcessLookupError:
                        pass
                    except Exception as kill_err:
                        logger.warning(f"Could not kill FFmpeg audio process: {kill_err}")

        safe_title = sanitize_filename(title, fallback="audio")
        filename = f"{safe_title}.mp3"

        return StreamingResponse(
            generate(),
            media_type="audio/mpeg",
            headers={"Content-Disposition": build_content_disposition(filename)}
        )

    async def stream_video_ffmpeg(self, stream_url: str, filename: str) -> StreamingResponse:
        """
        Pipes an M3U8 or DASH manifest stream through FFmpeg and exports as
        fragmented MP4. Required for Instagram/Twitter manifest-only videos.
        """
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
                first_chunk = await asyncio.wait_for(
                    process.stdout.read(65536),
                    timeout=_FFMPEG_START_TIMEOUT
                )
                if not first_chunk:
                    return
                yield first_chunk

                while True:
                    chunk = await process.stdout.read(65536)
                    if not chunk:
                        break
                    yield chunk
            except asyncio.TimeoutError:
                logger.error("FFmpeg video process timed out waiting for first byte.")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"FFmpeg MP4 streaming error: {e}", exc_info=True)
            finally:
                if process.returncode is None:
                    try:
                        process.kill()
                        await asyncio.shield(process.wait())
                    except ProcessLookupError:
                        pass
                    except Exception as kill_err:
                        logger.warning(f"Could not kill FFmpeg video process: {kill_err}")

        return StreamingResponse(
            generate(),
            media_type="video/mp4",
            headers={"Content-Disposition": build_content_disposition(filename)}
        )


ffmpeg_service = FfmpegService()
