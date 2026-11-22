"""RTSP snapshot capture using ffmpeg.

Captures still frames from RTSP camera streams via ffmpeg stdout.
"""

from __future__ import annotations

import asyncio
import shutil

from shared.logging import get_logger

logger = get_logger("rtsp_snapshot")

FFMPEG_TIMEOUT = 15.0  # seconds — 1080p HEVC cameras need >8s to emit a keyframe


async def capture_rtsp_frame_to_bytes(
    rtsp_url: str,
    timeout: float = FFMPEG_TIMEOUT,
) -> bytes | None:
    """Capture a single JPEG frame from RTSP and return as bytes via image2pipe.

    Args:
        rtsp_url: RTSP URL (e.g. rtsp://192.168.1.201/stream)
        timeout: Maximum time to wait for capture

    Returns:
        JPEG image bytes, or None if capture failed
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        logger.error("ffmpeg_not_found", rtsp_url=rtsp_url)
        return None

    cmd = [
        ffmpeg_path,
        "-y",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-vframes", "1",
        "-q:v", "2",
        "-f", "image2pipe", "-",
    ]

    logger.info("rtsp_capture_start", rtsp_url=rtsp_url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("rtsp_capture_timeout", rtsp_url=rtsp_url, timeout=timeout)
            return None

        if proc.returncode != 0 or not stdout:
            if proc.returncode != 0:
                stderr_text = stderr.decode("utf-8", errors="ignore")[:500]
                logger.error(
                    "rtsp_capture_failed",
                    rtsp_url=rtsp_url,
                    returncode=proc.returncode,
                    stderr=stderr_text,
                )
            return None

        logger.info(
            "rtsp_capture_success",
            rtsp_url=rtsp_url,
            size=len(stdout),
        )
        return stdout

    except Exception as e:
        logger.error("rtsp_capture_exception", rtsp_url=rtsp_url, error=str(e))
        return None
