"""
Corrected ffmpeg_service.py with fixes applied:
- Robust process cleanup preventing zombies
- Better timeout handling with force kill fallback
- Code deduplication via shared generator factory
"""
import asyncio
import logging
import subprocess
from typing import Optional, Callable
from fastapi.responses import StreamingResponse
from app.utils.helpers import sanitize_filename, build_content_disposition

logger = logging.getLogger(__name__)

# Timeouts (in seconds)
_FFMPEG_START_TIMEOUT = 30  # Max time to get first chunk
_FFMPEG_SHUTDOWN_TIMEOUT = 5  # Graceful shutdown wait
_FFMPEG_TOTAL_TIMEOUT = 600  # Max total runtime


class FfmpegService:
    @staticmethod
    async def _create_ffmpeg_process(command: list) -> asyncio.subprocess.Process:
        """
        Spawn FFmpeg process with proper pipe configuration.
        stderr → DEVNULL prevents deadlock (stderr buffer fills → FFmpeg blocks).
        """
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            return process
        except FileNotFoundError:
            logger.error("FFmpeg not found in system PATH")
            raise RuntimeError("FFmpeg is not installed on this system")
        except Exception as e:
            logger.error(f"Failed to spawn FFmpeg process: {e}", exc_info=True)
            raise

    @staticmethod
    async def _stream_from_process(
        process: asyncio.subprocess.Process,
        operation_name: str,
        chunk_size: int = 65536
    ):
        """
        Generic process streaming generator with robust cleanup.
        
        ✅ FIXED: Proper zombie process prevention
        ✅ Graceful termination with forced kill fallback
        ✅ Timeout on first byte to detect stalled processes early
        """
        first_chunk_received = False
        
        try:
            # Read first chunk with timeout (detects stalled processes)
            try:
                first_chunk = await asyncio.wait_for(
                    process.stdout.read(chunk_size),
                    timeout=_FFMPEG_START_TIMEOUT
                )
                if not first_chunk:
                    logger.warning(f"{operation_name}: FFmpeg produced no output")
                    return
                
                yield first_chunk
                first_chunk_received = True
            except asyncio.TimeoutError:
                logger.error(f"{operation_name}: FFmpeg timed out waiting for first byte after {_FFMPEG_START_TIMEOUT}s")
                raise
            
            # Stream remaining chunks
            while True:
                chunk = await process.stdout.read(chunk_size)
                if not chunk:
                    break
                yield chunk
                
        except asyncio.TimeoutError:
            logger.error(f"{operation_name}: Stream timed out")
        except asyncio.CancelledError:
            logger.debug(f"{operation_name}: Client disconnected")
        except Exception as e:
            logger.error(f"{operation_name}: Streaming error: {e}", exc_info=True)
        finally:
            # Robust process cleanup with multiple fallback strategies
            await FfmpegService._cleanup_process(process, operation_name)

    @staticmethod
    async def _cleanup_process(process: asyncio.subprocess.Process, operation_name: str):
        """
        Robust FFmpeg process cleanup with graceful degradation.
        
        ✅ FIXED: Multiple cleanup strategies:
        1. Try graceful termination
        2. Force kill if termination fails
        3. Log warnings without preventing cleanup
        """
        if process.returncode is not None:
            # Process already exited
            return
        
        try:
            # Step 1: Graceful termination
            logger.debug(f"{operation_name}: Terminating FFmpeg process (PID: {process.pid})")
            process.terminate()
            
            try:
                # Wait for graceful shutdown
                await asyncio.wait_for(process.wait(), timeout=_FFMPEG_SHUTDOWN_TIMEOUT)
                logger.debug(f"{operation_name}: FFmpeg terminated cleanly")
                return
            except asyncio.TimeoutError:
                logger.warning(f"{operation_name}: Graceful termination timed out after {_FFMPEG_SHUTDOWN_TIMEOUT}s, force killing")
        
            # Step 2: Force kill if graceful shutdown fails
            process.kill()
            
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
                logger.warning(f"{operation_name}: FFmpeg force killed")
            except asyncio.TimeoutError:
                logger.error(f"{operation_name}: Force kill did not complete (process may be zombie)")
        
        except ProcessLookupError:
            # Process already gone
            logger.debug(f"{operation_name}: Process already terminated")
        except Exception as e:
            logger.error(f"{operation_name}: Unexpected error during cleanup: {e}", exc_info=False)
            # Don't raise - we're in finally block and must complete cleanup

    async def stream_audio_as_mp3(self, url: str) -> StreamingResponse:
        """
        Extracts best audio stream and converts to MP3 via FFmpeg.
        
        ✅ FIXED: Uses shared streaming generator
        ✅ Proper process cleanup
        """
        from app.services.ytdlp_service import ytdlp_service
        
        try:
            stream_url, title = await ytdlp_service.get_best_audio_info(url)
            if not stream_url:
                raise RuntimeError("Could not get audio stream URL")
        except Exception as e:
            logger.error(f"Failed to get audio stream URL: {e}", exc_info=True)
            raise RuntimeError("Failed to get audio stream.") from e

        # FFmpeg command for MP3 conversion
        command = [
            'ffmpeg',
            '-i', stream_url,
            '-vn',  # No video
            '-ar', '44100',  # Sample rate
            '-ac', '2',  # 2 channels
            '-b:a', '192k',  # Bitrate
            '-f', 'mp3',
            'pipe:1'
        ]

        process = await self._create_ffmpeg_process(command)
        
        async def generate():
            async for chunk in self._stream_from_process(process, "audio_mp3"):
                yield chunk

        safe_title = sanitize_filename(title, fallback="audio")
        filename = f"{safe_title}.mp3"

        return StreamingResponse(
            generate(),
            media_type="audio/mpeg",
            headers={"Content-Disposition": build_content_disposition(filename)}
        )

    async def stream_video_ffmpeg(self, stream_url: str, filename: str) -> StreamingResponse:
        """
        Streams M3U8 or DASH manifest through FFmpeg as fragmented MP4.
        
        ✅ FIXED: Uses shared streaming generator
        ✅ Proper process cleanup
        """
        # FFmpeg command for manifest remuxing
        command = [
            'ffmpeg',
            '-i', stream_url,
            '-c', 'copy',  # Copy without re-encoding
            '-f', 'mp4',
            '-movflags', 'frag_keyframe+empty_moov',  # Fragmented MP4 for streaming
            'pipe:1'
        ]

        process = await self._create_ffmpeg_process(command)
        
        async def generate():
            async for chunk in self._stream_from_process(process, "video_ffmpeg"):
                yield chunk

        return StreamingResponse(
            generate(),
            media_type="video/mp4",
            headers={"Content-Disposition": build_content_disposition(filename)}
        )

    async def validate_ffmpeg(self) -> bool:
        """Health check: verify FFmpeg is available"""
        try:
            proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-version',
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            returncode = await asyncio.wait_for(proc.wait(), timeout=5.0)
            return returncode == 0
        except Exception:
            return False


# Global service instance
ffmpeg_service = FfmpegService()
