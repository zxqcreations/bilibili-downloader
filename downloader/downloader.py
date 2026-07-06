"""
Download Pipeline

Orchestrates the full download process:
1. Fetch stream URLs via API
2. Download video + audio M4S files with progress tracking
3. Download danmaku XML
4. Merge video + audio with FFMPEG
5. Clean up temp files
"""

import asyncio
import os
import subprocess
import uuid
from pathlib import Path
from typing import Callable, Optional

import httpx

from .api_client import fetch_playurl, build_headers
from .danmaku import download_danmaku

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
TEMP_DIR = BASE_DIR / "temp"
FFMPEG_PATH = r"D:\ENV\ffmpeg-7.1-full_build\bin\ffmpeg.exe"

# Ensure directories exist
DOWNLOADS_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

# Track active download tasks for progress reporting
_active_tasks: dict = {}


class DownloadTask:
    """Represents an active or completed download task."""

    def __init__(self, task_id: str, title: str, bvid: str, cid: int):
        self.task_id = task_id
        self.title = title
        self.bvid = bvid
        self.cid = cid
        self.progress = 0.0  # 0-100
        self.stage = "initializing"
        self.error = None
        self.output_file = None
        self.danmaku_file = None
        self.danmaku_count = 0

    def update(self, stage: str, progress: float = None):
        """Update task status. Called from download coroutine."""
        if progress is not None:
            self.progress = min(progress, 100.0)
        self.stage = stage

    def set_error(self, error: str):
        self.error = error
        self.stage = "error"

    def set_complete(self, output_file: str, danmaku_file: str, danmaku_count: int):
        self.output_file = output_file
        self.danmaku_file = danmaku_file
        self.danmaku_count = danmaku_count
        self.progress = 100.0
        self.stage = "complete"


async def download_file(
    client: httpx.AsyncClient,
    url: str,
    output_path: str,
    callback: Callable = None,
) -> str:
    """Download a file with progress reporting.

    Downloads in chunks and calls the optional callback with (downloaded, total)
    for progress tracking.
    """
    headers = build_headers()

    async with client.stream("GET", url, headers=headers, follow_redirects=True) as resp:
        resp.raise_for_status()
        total_size = int(resp.headers.get("content-length", 0))

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        downloaded = 0
        with open(output_path, "wb") as f:
            async for chunk in resp.aiter_bytes(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if callback and total_size > 0:
                    await callback(downloaded, total_size)

    return output_path


async def download_bilibili_video(
    bvid: str,
    cid: int,
    title: str = "",
    cookie: str = "",
    quality: int = 80,
    task_id: str = None,
) -> dict:
    """Full download pipeline for a single Bilibili video part.

    Args:
        bvid: Video BV ID
        cid: Content ID of the part
        title: Video title (for filename)
        cookie: Optional SESSDATA cookie
        quality: Desired quality code (qn)
        task_id: Optional task ID for progress tracking (auto-generated if not provided)

    Returns:
        dict with: task_id, output_file, danmaku_file, danmaku_count
    """
    if task_id is None:
        task_id = str(uuid.uuid4())[:8]

    # Create or retrieve task
    if task_id not in _active_tasks:
        _active_tasks[task_id] = DownloadTask(task_id, title, bvid, cid)
    task = _active_tasks[task_id]

    safe_title = _sanitize_filename(title or f"{bvid}_c{cid}")
    video_m4s = str(TEMP_DIR / f"{task_id}_video.m4s")
    audio_m4s = str(TEMP_DIR / f"{task_id}_audio.m4s")
    output_mp4 = str(DOWNLOADS_DIR / f"{safe_title}.mp4")
    output_xml = str(DOWNLOADS_DIR / f"{safe_title}.xml")

    task.update("fetching_streams", 0)

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(300.0),
            headers=build_headers(cookie),
        ) as client:
            # Step 1: Get stream URLs
            task.update("fetching_streams", 5)
            playurl_data = await fetch_playurl(client, bvid, cid, cookie, quality)

            if not playurl_data["video"] or not playurl_data["audio"]:
                raise ValueError("No video or audio streams available")

            # Select best video and audio streams
            video_stream = _select_best_stream(playurl_data["video"], "video")
            audio_stream = _select_best_stream(playurl_data["audio"], "audio")

            video_url = video_stream["base_url"]
            audio_url = audio_stream["base_url"]
            total_duration = playurl_data.get("duration", 0)

            # Step 2: Download video M4S
            task.update("downloading_video", 10)

            async def video_progress(downloaded, total):
                pct = 10 + (downloaded / total) * 40  # 10% → 50%
                task.update("downloading_video", pct)

            await download_file(client, video_url, video_m4s, video_progress)

            # Step 3: Download audio M4S
            task.update("downloading_audio", 50)

            async def audio_progress(downloaded, total):
                pct = 50 + (downloaded / total) * 30  # 50% → 80%
                task.update("downloading_audio", pct)

            await download_file(client, audio_url, audio_m4s, audio_progress)

            # Step 4: Download danmaku
            task.update("downloading_danmaku", 80)
            xml_path = await download_danmaku(client, cid, output_xml, cookie)

            # Count danmaku
            from .danmaku import parse_danmaku_stats
            try:
                stats = parse_danmaku_stats(xml_path)
                danmaku_count = stats["total_count"]
            except Exception:
                danmaku_count = 0

            task.update("downloading_danmaku", 85)

        # Step 5: Merge with FFMPEG (outside httpx context since it uses subprocess)
        task.update("merging", 90)
        await _merge_with_ffmpeg(video_m4s, audio_m4s, output_mp4)

        # Step 6: Cleanup
        task.update("cleaning_up", 95)
        _cleanup_temp(video_m4s, audio_m4s)

        # Done
        task.set_complete(output_mp4, output_xml, danmaku_count)

        return {
            "task_id": task_id,
            "output_file": output_mp4,
            "danmaku_file": output_xml,
            "danmaku_count": danmaku_count,
        }

    except Exception as e:
        task.set_error(str(e))
        _cleanup_temp(video_m4s, audio_m4s)
        raise


def get_task(task_id: str) -> Optional[DownloadTask]:
    """Get a download task by ID."""
    return _active_tasks.get(task_id)


def get_all_tasks() -> list:
    """Get all download tasks."""
    return list(_active_tasks.values())


def _select_best_stream(streams: list, stream_type: str) -> dict:
    """Select the highest quality stream from available options.

    For video: picks by id (higher id = higher quality within same codec)
    For audio: picks by id (higher id = higher quality/bitrate)

    Prefers: id=120 (4K/AVC) > id=116 (1080P60) > id=80 (1080P) > etc.
    """
    if not streams:
        raise ValueError(f"No {stream_type} streams available")

    # Sort by id descending (higher id = higher quality)
    sorted_streams = sorted(streams, key=lambda s: s.get("id", 0), reverse=True)
    best = sorted_streams[0]

    # Build base_url from baseUrl or base_url
    if "base_url" in best:
        base_url = best["base_url"]
    elif "baseUrl" in best:
        base_url = best["baseUrl"]
    else:
        # Construct from host + base_url parts
        base_url = best.get("base_url", best.get("baseUrl", ""))

    # Some streams use backup_url for CDN fallback
    backup_urls = best.get("backup_url", best.get("backupUrl", []))
    if isinstance(backup_urls, str):
        backup_urls = [backup_urls]

    return {
        "id": best.get("id", 0),
        "base_url": base_url,
        "backup_urls": backup_urls,
        "codecs": best.get("codecs", ""),
        "bandwidth": best.get("bandwidth", 0),
        "width": best.get("width", 0),
        "height": best.get("height", 0),
        "frame_rate": best.get("frameRate", best.get("frame_rate", "")),
    }


async def _merge_with_ffmpeg(video_path: str, audio_path: str, output_path: str) -> None:
    """Merge video and audio M4S files into MP4 using FFMPEG.

    Uses stream copy (no re-encode) for lossless merging.
    On Windows, asyncio.create_subprocess_exec is not supported with
    ProactorEventLoop, so we run FFMPEG in a thread pool via asyncio.to_thread.
    """
    import subprocess

    if not os.path.exists(FFMPEG_PATH):
        ffmpeg_cmd = "ffmpeg"
    else:
        ffmpeg_cmd = FFMPEG_PATH

    cmd = [
        ffmpeg_cmd,
        "-i", video_path,
        "-i", audio_path,
        "-c", "copy",          # Stream copy, no re-encode
        "-map", "0:v:0",       # Take video from first input
        "-map", "1:a:0",       # Take audio from second input
        "-y",                  # Overwrite output if exists
        output_path,
    ]

    def _run():
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"FFMPEG merge failed (exit {result.returncode}): {result.stderr[-500:]}"
            )
        return result

    await asyncio.to_thread(_run)


def _cleanup_temp(*paths: str) -> None:
    """Remove temporary files."""
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def _sanitize_filename(filename: str) -> str:
    """Remove or replace characters that are invalid in Windows filenames."""
    invalid_chars = r'<>:"/\|?*'
    for ch in invalid_chars:
        filename = filename.replace(ch, "_")
    # Also trim whitespace and limit length
    filename = filename.strip()
    if len(filename) > 120:
        filename = filename[:120]
    return filename
