"""
Bilibili Video Downloader - FastAPI Application

Provides a web interface for downloading Bilibili videos.
Backend: FastAPI with SSE for real-time progress.
Frontend: Single-page HTML/JS served from /static.
"""

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from downloader.api_client import (
    extract_bvid,
    fetch_video_info,
    QUALITY_MAP,
    HD_QUALITIES,
    PREMIUM_QUALITIES,
)
from downloader.downloader import download_bilibili_video, get_task, get_all_tasks

# ── App Setup ────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
COOKIE_FILE = BASE_DIR / "cookie.txt"


def _load_cookie() -> str:
    """Load saved cookie from file."""
    try:
        if COOKIE_FILE.exists():
            return COOKIE_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def _save_cookie(cookie: str) -> None:
    """Save cookie to file. Empty string deletes the file."""
    cookie = cookie.strip()
    if cookie:
        COOKIE_FILE.write_text(cookie, encoding="utf-8")
    elif COOKIE_FILE.exists():
        COOKIE_FILE.unlink()

app = FastAPI(
    title="Bilibili Video Downloader",
    description="Download Bilibili videos with danmaku",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── SSE Event Queues ─────────────────────────────────────────────────────────

# Per-task asyncio queues for SSE progress events
_sse_queues: dict[str, asyncio.Queue] = {}


def _get_or_create_queue(task_id: str) -> asyncio.Queue:
    if task_id not in _sse_queues:
        _sse_queues[task_id] = asyncio.Queue()
    return _sse_queues[task_id]


async def _push_event(task_id: str, event: str, data: dict):
    """Push an SSE event to all listeners for a task."""
    q = _get_or_create_queue(task_id)
    await q.put({"event": event, "data": data})


# ── API Endpoints ────────────────────────────────────────────────────────────


@app.post("/api/parse")
async def parse_url(request: Request):
    """Parse a Bilibili URL and return video metadata."""
    body = await request.json()
    url = body.get("url", "").strip()
    cookie = body.get("cookie", "").strip()

    # Auto-persist cookie (empty = delete saved)
    _save_cookie(cookie)

    bvid = extract_bvid(url)
    if not bvid:
        raise HTTPException(400, "无法识别的 Bilibili 链接，请检查 URL")

    import httpx

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            info = await fetch_video_info(client, bvid, cookie)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"请求 Bilibili API 失败: {e}")
    except ValueError as e:
        raise HTTPException(404, str(e))

    # Build quality options based on whether cookie is provided
    has_cookie = bool(cookie)
    all_qualities = sorted(QUALITY_MAP.keys(), reverse=True)

    qualities = []
    for q in all_qualities:
        label = QUALITY_MAP[q]
        if q in PREMIUM_QUALITIES:
            available = False  # VIP required
            requires_login = True
            requires_vip = True
        elif q in HD_QUALITIES:
            available = has_cookie
            requires_login = True
            requires_vip = False
        else:
            available = True
            requires_login = False
            requires_vip = False

        qualities.append({
            "qn": q,
            "label": label,
            "available": available,
            "requires_login": requires_login,
            "requires_vip": requires_vip,
        })

    return {
        "bvid": info["bvid"],
        "title": info["title"],
        "cover": info["cover"],
        "duration": info["duration"],
        "owner_name": info["owner_name"],
        "pages": info["pages"],
        "qualities": qualities,
        "stat": info["stat"],
    }


@app.post("/api/download")
async def start_download(request: Request):
    """Start a download task and return a task ID."""
    body = await request.json()
    bvid = body.get("bvid", "").strip()
    cid = body.get("cid")
    title = body.get("title", "").strip()
    cookie = body.get("cookie", "").strip()
    quality = body.get("quality", 16)
    part_title = body.get("part_title", "").strip()

    # Auto-persist cookie (empty = delete saved)
    _save_cookie(cookie)

    if not bvid or not cid:
        raise HTTPException(400, "缺少 bvid 或 cid 参数")

    task_id = str(uuid.uuid4())[:8]
    full_title = f"{title} - {part_title}" if part_title else title

    # Initialize SSE queue
    _get_or_create_queue(task_id)

    # Launch download in background
    async def _run():
        try:
            result = await download_bilibili_video(
                bvid=bvid,
                cid=int(cid),
                title=full_title,
                cookie=cookie,
                quality=int(quality),
                task_id=task_id,
            )
            await _push_event(task_id, "complete", {
                "output_file": result["output_file"],
                "danmaku_file": result["danmaku_file"],
                "danmaku_count": result["danmaku_count"],
            })
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"DOWNLOAD ERROR: {e!r}", flush=True)
            print(tb, flush=True)
            error_msg = str(e) if str(e) else repr(e)
            await _push_event(task_id, "error", {"message": error_msg})

    asyncio.create_task(_run())

    # Start progress broadcaster
    async def _broadcast_progress():
        """Poll task progress and push SSE events."""
        last_progress = -1
        last_stage = ""
        while True:
            task = get_task(task_id)
            if task is None:
                await asyncio.sleep(0.5)
                continue

            if task.stage != last_stage or abs(task.progress - last_progress) > 0.5:
                await _push_event(task_id, "progress", {
                    "stage": task.stage,
                    "progress": round(task.progress, 1),
                    "stage_text": _stage_text(task.stage),
                })
                last_stage = task.stage
                last_progress = task.progress

            if task.stage in ("complete", "error"):
                break

            await asyncio.sleep(0.3)

    asyncio.create_task(_broadcast_progress())

    return {
        "task_id": task_id,
        "status": "started",
    }


@app.get("/api/progress/{task_id}")
async def progress_sse(task_id: str):
    """Server-Sent Events endpoint for download progress."""
    q = _get_or_create_queue(task_id)

    async def event_generator():
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
                event_type = msg["event"]
                data = json.dumps(msg["data"], ensure_ascii=False)
                yield f"event: {event_type}\ndata: {data}\n\n"

                if event_type in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                yield f"event: ping\ndata: {{}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/downloads")
async def list_downloads():
    """List all completed download files."""
    downloads_dir = BASE_DIR / "downloads"
    files = []
    if downloads_dir.exists():
        for f in downloads_dir.iterdir():
            if f.is_file():
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "path": str(f.relative_to(BASE_DIR)),
                })
    return {"files": sorted(files, key=lambda x: x["name"])}


@app.get("/api/tasks")
async def list_tasks():
    """List all download tasks."""
    tasks = get_all_tasks()
    return {
        "tasks": [
            {
                "task_id": t.task_id,
                "title": t.title,
                "stage": t.stage,
                "progress": round(t.progress, 1),
                "error": t.error,
                "output_file": t.output_file,
                "danmaku_file": t.danmaku_file,
                "danmaku_count": t.danmaku_count,
            }
            for t in tasks
        ]
    }


def _stage_text(stage: str) -> str:
    """Convert stage code to Chinese display text."""
    stages = {
        "initializing": "初始化中...",
        "fetching_streams": "获取视频流信息...",
        "downloading_video": "下载视频流...",
        "downloading_audio": "下载音频流...",
        "downloading_danmaku": "下载弹幕...",
        "merging": "合并音视频...",
        "cleaning_up": "清理临时文件...",
        "complete": "完成!",
        "error": "出错",
    }
    return stages.get(stage, stage)


# ── Cookie Management ────────────────────────────────────────────────────────


@app.get("/api/cookie")
async def get_cookie():
    """Return the saved cookie (if any)."""
    return {"cookie": _load_cookie()}


@app.post("/api/cookie")
async def save_cookie(request: Request):
    """Save or clear the cookie."""
    body = await request.json()
    cookie = body.get("cookie", "").strip()
    _save_cookie(cookie)
    return {"cookie": cookie, "saved": True}


# ── Static Files & Frontend ──────────────────────────────────────────────────


@app.get("/")
async def index():
    """Serve the frontend page."""
    return FileResponse(BASE_DIR / "static" / "index.html")


# Mount static files for CSS/JS
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ── Startup ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
