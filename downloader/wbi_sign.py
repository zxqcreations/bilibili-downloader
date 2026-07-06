"""
Bilibili WBI Signature Module

Bilibili requires WBI signing (w_rid + wts) for the playurl API since ~2023.
The signing key is derived from image URLs in the nav API response.
"""

import hashlib
import time
from functools import lru_cache

import httpx

NAV_API = "https://api.bilibili.com/x/web-interface/nav"

# Fixed shuffle pattern for mixing img_key and sub_key
# Indices taken from the first 16 chars of img_key (even then odd positions)
# followed by the same pattern from sub_key
SHUFFLE = [0, 2, 4, 6, 8, 10, 12, 14, 1, 3, 5, 7, 9, 11, 13, 15]


def _extract_key_from_url(url: str) -> str:
    """Extract the key from a WBI image URL (filename without extension)."""
    # URL format: https://i0.hdslb.com/bfs/wbi/xxx.png
    filename = url.rsplit("/", 1)[-1]
    key = filename.rsplit(".", 1)[0]
    return key


def mix_key(img_key: str, sub_key: str) -> str:
    """Mix img_key and sub_key using Bilibili's fixed shuffle pattern.

    The pattern takes even-indexed chars first, then odd-indexed chars,
    from both keys, concatenated together.
    """
    result = []
    for i in SHUFFLE:
        result.append(img_key[i])
    for i in SHUFFLE:
        result.append(sub_key[i])
    return "".join(result)


async def get_mixin_key(client: httpx.AsyncClient) -> str:
    """Fetch WBI keys from nav API and return the mixed key.

    The nav API returns wbi_img with img_url and sub_url.
    We extract the filename stem from each URL and mix them.
    """
    resp = await client.get(NAV_API)
    resp.raise_for_status()
    data = resp.json()

    wbi_img = data["data"]["wbi_img"]
    img_key = _extract_key_from_url(wbi_img["img_url"])
    sub_key = _extract_key_from_url(wbi_img["sub_url"])

    return mix_key(img_key, sub_key)


def sign_params(params: dict, mixin_key: str) -> dict:
    """Sign request parameters with WBI signature.

    Returns a new dict with w_rid and wts added.
    """
    params = params.copy()
    params["wts"] = int(time.time())

    # Sort by key alphabetically
    sorted_keys = sorted(params.keys())
    query = "&".join(f"{k}={params[k]}" for k in sorted_keys)

    # MD5(query + mixin_key)
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()

    params["w_rid"] = w_rid
    return params
