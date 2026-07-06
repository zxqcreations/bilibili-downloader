"""
Danmaku (弹幕) Download and Processing

Downloads danmaku in XML format from Bilibili's legacy API
and optionally converts to ASS subtitle format.
"""

import os
import xml.etree.ElementTree as ET


async def download_danmaku(
    client, cid: int, output_path: str, cookie: str = ""
) -> str:
    """Download danmaku XML and save to file.

    Args:
        client: httpx.AsyncClient
        cid: Content ID of the video part
        output_path: Path to save the XML file
        cookie: Optional cookie for authenticated requests

    Returns:
        Path to the saved XML file
    """
    from .api_client import fetch_danmaku_xml

    xml_content = await fetch_danmaku_xml(client, cid, cookie)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_content)

    return output_path


def parse_danmaku_stats(xml_path: str) -> dict:
    """Parse danmaku XML and return statistics.

    Returns dict with: total_count, by_type (scroll/top/bottom), sample_texts
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    total = 0
    by_type = {"scroll": 0, "top": 0, "bottom": 0}
    samples = []

    for d in root.findall("d"):
        total += 1
        # Danmaku format: time,mode,size,color,timestamp,pool,author,db_id
        attrs = d.get("p", "").split(",")
        if len(attrs) >= 2:
            mode = int(attrs[1])
            if mode <= 3:
                by_type["scroll"] += 1
            elif mode == 4:
                by_type["bottom"] += 1
            elif mode == 5:
                by_type["top"] += 1

        if len(samples) < 10 and d.text:
            samples.append(d.text)

    return {
        "total_count": total,
        "by_type": by_type,
        "sample_texts": samples,
    }


def xml_to_ass(xml_path: str, ass_path: str, video_width: int = 1920,
               video_height: int = 1080) -> str:
    """Convert danmaku XML to ASS subtitle format (basic conversion).

    This is a simplified converter for basic danmaku rendering.
    For full-featured conversion, consider using external tools like danmaku2ass.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    font_size = int(video_height / 36)  # Scale font to video height

    ass_header = f"""[Script Info]
Title: Bilibili Danmaku
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: R, Microsoft YaHei, {font_size}, &H00FFFFFF, &H00000000, &H00000000, &H00000000, 0, 0, 0, 0, 100, 100, 0, 0, 1, 1, 0, 2, 10, 10, 10, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    ass_lines = [ass_header]

    for d in root.findall("d"):
        attrs = d.get("p", "").split(",")
        if len(attrs) < 1 or not d.text:
            continue

        try:
            time_ms = float(attrs[0]) * 1000  # Convert to milliseconds
        except ValueError:
            continue

        start_time = _ms_to_ass_time(time_ms)
        # Each danmaku stays on screen for ~5 seconds
        end_time = _ms_to_ass_time(time_ms + 5000)

        # Escape ASS special characters
        text = d.text.replace("{", "\\{").replace("}", "\\}")

        ass_lines.append(
            f"Dialogue: 0,{start_time},{end_time},R,,0,0,0,,{text}"
        )

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ass_lines))

    return ass_path


def _ms_to_ass_time(ms: float) -> str:
    """Convert milliseconds to ASS time format (H:MM:SS.cc)."""
    hours = int(ms // 3600000)
    minutes = int((ms % 3600000) // 60000)
    seconds = int((ms % 60000) // 1000)
    centiseconds = int((ms % 1000) // 10)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"
