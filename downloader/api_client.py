"""
Bilibili API Client

Handles all HTTP interactions with Bilibili's APIs:
- Video metadata (view API)
- DASH stream URLs (wbi/playurl API)
- Danmaku data (legacy XML API)
"""

import re
from typing import Optional

import httpx

from .wbi_sign import get_mixin_key, sign_params

VIEW_API = "https://api.bilibili.com/x/web-interface/view"
PLAYURL_API = "https://api.bilibili.com/x/player/wbi/playurl"
DANMAKU_API = "https://api.bilibili.com/x/v1/dm/list.so"

# Common headers for all Bilibili API requests
BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}

# Quality code → label mapping
QUALITY_MAP = {
    6: "240P 极速",
    16: "360P 流畅",
    32: "480P 清晰",
    64: "720P 高清",
    74: "720P60 高帧率",
    80: "1080P 高清",
    112: "1080P+ 高码率",
    116: "1080P60 高帧率",
    120: "4K 超清",
    125: "HDR 真彩",
    126: "杜比视界",
    127: "8K 超高清",
}

# Qualities that require login cookie
PREMIUM_QUALITIES = {112, 116, 120, 125, 126, 127}
HD_QUALITIES = {64, 74, 80}


def extract_bvid(url: str) -> Optional[str]:
    """Extract BV ID from a Bilibili URL.

    Supports formats:
    - https://www.bilibili.com/video/BV1YgT26qETR
    - https://www.bilibili.com/video/BV1YgT26qETR/?p=1
    - https://b23.tv/BV1YgT26qETR
    - BV1YgT26qETR (raw BV ID)
    """
    # If it's already a raw BV ID
    if re.match(r"^BV[a-zA-Z0-9]{10}$", url.strip()):
        return url.strip()

    # Extract from URL
    match = re.search(r"(?:bilibili\.com/video/|b23\.tv/)(BV[a-zA-Z0-9]{10})", url)
    if match:
        return match.group(1)
    return None


def build_headers(cookie: str = "") -> dict:
    """Build request headers, optionally including cookie."""
    headers = BASE_HEADERS.copy()
    if cookie:
        headers["Cookie"] = cookie
    return headers


async def fetch_video_info(
    client: httpx.AsyncClient, bvid: str, cookie: str = ""
) -> dict:
    """Fetch video metadata from the view API.

    Returns a dict with: bvid, title, cover, duration, pages, owner_name, stat
    Each page has: cid, title, duration, page (page number)
    """
    resp = await client.get(
        VIEW_API,
        params={"bvid": bvid},
        headers=build_headers(cookie),
    )
    resp.raise_for_status()
    data = resp.json()

    if data["code"] != 0:
        raise ValueError(f"API error: {data.get('message', 'Unknown error')}")

    video = data["data"]

    pages = []
    for p in video.get("pages", []):
        pages.append({
            "cid": p["cid"],
            "title": p.get("part", ""),
            "duration": p.get("duration", 0),
            "page": p.get("page", 0),
        })

    if not pages:
        # Single-part video — cid is at top level
        pages.append({
            "cid": video["cid"],
            "title": video.get("title", ""),
            "duration": video.get("duration", 0),
            "page": 1,
        })

    return {
        "bvid": video.get("bvid", bvid),
        "aid": video.get("aid", 0),
        "title": video.get("title", ""),
        "cover": video.get("pic", ""),
        "duration": video.get("duration", 0),
        "owner_name": video.get("owner", {}).get("name", ""),
        "pages": pages,
        "stat": video.get("stat", {}),
    }


async def fetch_playurl(
    client: httpx.AsyncClient,
    bvid: str,
    cid: int,
    cookie: str = "",
    quality: int = 80,
) -> dict:
    """Fetch DASH stream URLs from the playurl API.

    Requires WBI signing. Returns the full dash object with video[] and audio[] arrays.

    Args:
        client: httpx AsyncClient
        bvid: Video BV ID
        cid: Content ID (part identifier)
        cookie: Optional SESSDATA cookie for HD qualities
        quality: Desired quality code (qn), default 80 (1080P)

    Returns dict with keys: video (list of streams), audio (list of streams),
    duration, quality_label
    """
    # Get WBI mixin key
    mixin_key = await get_mixin_key(client)

    # Build params
    params = {
        "bvid": bvid,
        "cid": cid,
        "fnval": 4048,  # Request all available DASH streams
        "fnver": 0,
        "qn": quality,
        "fourk": 1,
    }

    signed = sign_params(params, mixin_key)

    resp = await client.get(
        PLAYURL_API,
        params=signed,
        headers=build_headers(cookie),
    )
    resp.raise_for_status()
    data = resp.json()

    if data["code"] != 0:
        raise ValueError(f"PlayURL error: {data.get('message', 'Unknown error')}")

    dash = data["data"]["dash"]
    accepted_quality = data["data"].get("accept_quality", [])
    current_quality = data["data"].get("quality", quality)

    # Build available quality list
    available_qualities = []
    for q in accepted_quality:
        if q in QUALITY_MAP:
            available_qualities.append({
                "qn": q,
                "label": QUALITY_MAP[q],
            })

    return {
        "video": dash.get("video", []),
        "audio": dash.get("audio", []),
        "duration": dash.get("duration", 0),
        "current_quality": current_quality,
        "available_qualities": available_qualities,
    }


async def fetch_danmaku_xml(
    client: httpx.AsyncClient, cid: int, cookie: str = ""
) -> str:
    """Fetch danmaku (弹幕) in XML format.

    Uses the legacy XML API which returns all danmaku for a video.
    """
    resp = await client.get(
        DANMAKU_API,
        params={"oid": cid},
        headers=build_headers(cookie),
    )
    resp.raise_for_status()
    return resp.text
