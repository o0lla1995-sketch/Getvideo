# ═══════════════════════════════════════════════════════════════════════════
# GETVIDEO — Multi-Quality Video Extraction Server (v2)
# ═══════════════════════════════════════════════════════════════════════════
#
# Deployed on Coolify as: getvideo:main-okzr3huc0sxjmwk5ywcohdqp
# Repo: https://github.com/o0lla1995-sketch/Getvideo
#
# WHAT'S NEW IN v2:
#   - Extracts ALL available qualities, not just the highest:
#     * setVideoUrlHigh  → HD MP4 (when available, differs from Low)
#     * setVideoUrlLow   → SD MP4 (default for fast initial load)
#     * setVideoHLS      → HLS master manifest
#   - Parses the HLS master manifest to discover EVERY quality variant
#     (360p / 480p / 720p / 1080p ...) with bandwidth + resolution.
#   - Returns a `formats` array the site player uses for its quality
#     selector, plus `hlsQualities` (parsed from the manifest).
#   - Backward compatible: still returns `success` + `streamUrl` (the
#     LOW quality, so the site's old single-URL consumers keep working).
#
# API:
#   GET /extract-url?url=<embed or video page URL>
#
#   Response (success):
#   {
#     "success": true,
#     "streamUrl": "<low-or-default URL>",     # backward-compat single URL
#     "title": "...",
#     "high": "<HD MP4 URL or null>",
#     "low":  "<SD MP4 URL or null>",
#     "hls":  "<HLS master URL or null>",
#     "hlsQualities": [                         # parsed from HLS manifest
#       {"label": "360p", "resolution": "640x360", "height": 360,
#        "bandwidth": 475136, "url": "https://.../hls-360p-xxx.m3u8"},
#       ...
#     ],
#     "formats": [                              # everything, sorted LOW→HIGH
#       {"url": "...", "label": "SD (MP4)", "height": 360, "type": "mp4"},
#       {"url": "...", "label": "360p (HLS)", "height": 360, "type": "hls"},
#       {"url": "...", "label": "480p (HLS)", "height": 480, "type": "hls"},
#       {"url": "...", "label": "1080p (HLS)", "height": 1080, "type": "hls"},
#       {"url": "...", "label": "HLS (auto)", "height": 0, "type": "hls"}
#     ],
#     "qualitiesCount": 5
#   }
#
#   Response (failure):
#   {"success": false, "error": "..."}
#
# SUPPORTED SOURCE PAGES (any page containing the html5player patterns):
#   - https://www.xvideos.com/video.SLUG/title
#   - https://www.xvideos.com/embedframe/ID
#   - Most other sites that embed html5player.setVideoUrl* calls
# ═══════════════════════════════════════════════════════════════════════════

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urljoin
import requests
import re

app = FastAPI(title="Getvideo Multi-Quality Extractor", version="2.0")

# CORS: the site calls this API from the browser too (client-side
# extraction fallback), so allow everything.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.xvideos.com/',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}


# ─────────────────────────────────────────────────────────────────────────────
# Parse an HLS MASTER manifest and extract every quality variant.
#
# A master manifest looks like:
#   #EXTM3U
#   #EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=815104,RESOLUTION=854x480,NAME="480p"
#   hls-480p-7e217.m3u8
#   #EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=3375104,RESOLUTION=1922x1080,NAME="1080p"
#   hls-1080p-d1bfc.m3u8
#
# Each #EXT-X-STREAM-INF describes the variant on the NEXT non-comment line.
# Variant URLs are RELATIVE to the master URL → resolve with urljoin.
#
# Returns a list sorted by height ASCENDING (lowest quality first).
# ─────────────────────────────────────────────────────────────────────────────
def parse_hls_master(master_url: str) -> list:
    qualities = []
    try:
        res = requests.get(master_url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return qualities

        lines = res.text.strip().split('\n')
        current_info = {}
        for line in lines:
            line = line.strip()
            if line.startswith('#EXT-X-STREAM-INF:'):
                current_info = {}
                # Parse attributes: BANDWIDTH=815104,RESOLUTION=854x480,NAME="480p"
                attrs_part = line.split(':', 1)[1]
                for key, val in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', attrs_part):
                    current_info[key] = val.strip('"')
            elif line and not line.startswith('#') and current_info:
                # This is the variant playlist URL (relative → absolute)
                variant_url = urljoin(master_url, line)

                name = current_info.get('NAME', '')
                resolution = current_info.get('RESOLUTION', '')

                # Derive height from RESOLUTION (WxH) or NAME (e.g. "480p")
                height = 0
                if resolution and 'x' in resolution:
                    try:
                        height = int(resolution.split('x')[-1])
                    except ValueError:
                        pass
                if height == 0 and name:
                    m = re.match(r'(\d+)', name)
                    if m:
                        height = int(m.group(1))

                try:
                    bandwidth = int(current_info.get('BANDWIDTH', '0'))
                except ValueError:
                    bandwidth = 0

                qualities.append({
                    'label': name or resolution or 'Unknown',
                    'resolution': resolution,
                    'height': height,
                    'bandwidth': bandwidth,
                    'url': variant_url,
                })
                current_info = {}

        # Sort ascending (lowest first) — LOW quality first for fast load
        qualities.sort(key=lambda q: q['height'])
    except Exception:
        pass
    return qualities


# ─────────────────────────────────────────────────────────────────────────────
# Guess the quality label/height of an MP4 URL from its filename.
#   .../mp4_sd.mp4  → "SD", 360
#   .../mp4_hd.mp4  → "HD", 720
#   .../video_480p.mp4 → "480p", 480
# ─────────────────────────────────────────────────────────────────────────────
def guess_mp4_quality(url: str):
    low_url = url.lower()
    if 'mp4_sd' in low_url or '/sd/' in low_url:
        return 'SD', 360
    if 'mp4_hd' in low_url or '/hd/' in low_url:
        return 'HD', 720
    if '4k' in low_url:
        return '4K', 2160
    m = re.search(r'(\d{3,4})p', low_url)
    if m:
        h = int(m.group(1))
        return f'{h}p', h
    return 'MP4', 480


# ─────────────────────────────────────────────────────────────────────────────
# MAIN EXTRACTION ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/extract-url")
async def extract_url(url: str = Query(...)):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if response.status_code != 200:
            return {"success": False, "error": f"Source returned HTTP {response.status_code}"}
        html = response.text

        # ── Extract the three base URLs + title ──
        high = None
        low = None
        hls = None
        title = None

        m = re.search(r"setVideoUrlHigh\('(.*?)'\)", html)
        if m:
            high = m.group(1)
        m = re.search(r"setVideoUrlLow\('(.*?)'\)", html)
        if m:
            low = m.group(1)
        m = re.search(r"setVideoHLS\('(.*?)'\)", html)
        if m:
            hls = m.group(1)
        m = re.search(r"setVideoTitle\('(.*?)'\)", html)
        if m:
            title = m.group(1)

        # Fallback: generic patterns for OTHER sites (non-XVideos) that
        # embed a single video URL in JSON or a <video>/<source> tag.
        if not high and not low and not hls:
            generic_patterns = [
                r'["\'](?:videoUrl|streamUrl|playUrl|file)["\']\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
                r'["\'](?:videoUrl|streamUrl|playUrl|file)["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                r'<source[^>]+src=["\']([^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
                r'<video[^>]+src=["\']([^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
                r'https://[^"\'\s]+\.mp4[^"\'\s]*',
                r'https://[^"\'\s]+\.m3u8[^"\'\s]*',
            ]
            for p in generic_patterns:
                m = re.search(p, html)
                if m and m.group(1):
                    u = m.group(1).replace('\\u002F', '/').replace('\\/', '/').replace('&amp;', '&')
                    if u.lower().split('?')[0].endswith('.m3u8'):
                        hls = u
                    else:
                        high = u
                    break

        if not high and not low and not hls:
            return {"success": False, "error": "Extraction failed"}

        # ── Parse the HLS master manifest → ALL quality variants ──
        hls_qualities = parse_hls_master(hls) if hls else []

        # ── Build the unified `formats` list (LOW → HIGH) ──
        formats = []
        seen = set()

        # 1. MP4 Low (SD) — the fast-loading default
        if low and low not in seen:
            label, height = guess_mp4_quality(low)
            formats.append({'url': low, 'label': f'{label} (MP4)', 'height': height, 'type': 'mp4'})
            seen.add(low)

        # 2. MP4 High (only when it's a DIFFERENT URL from Low)
        if high and high not in seen:
            label, height = guess_mp4_quality(high)
            formats.append({'url': high, 'label': f'{label} (MP4)', 'height': height, 'type': 'mp4'})
            seen.add(high)

        # 3. Every HLS variant discovered from the master manifest
        for q in hls_qualities:
            if q['url'] not in seen:
                formats.append({
                    'url': q['url'],
                    'label': f"{q['label']} (HLS)",
                    'height': q['height'],
                    'type': 'hls',
                    'bandwidth': q.get('bandwidth', 0),
                })
                seen.add(q['url'])

        # 4. The HLS master itself (adaptive — hls.js auto-picks quality)
        if hls and hls not in seen:
            formats.append({'url': hls, 'label': 'Auto (HLS)', 'height': 0, 'type': 'hls'})
            seen.add(hls)

        # Sort ascending by height (height=0 "Auto" goes last)
        formats.sort(key=lambda f: f['height'] if f['height'] > 0 else 99999)

        # Default single URL for backward compatibility:
        # LOW MP4 → HIGH MP4 → lowest HLS variant → HLS master
        default = low or high
        if not default and hls_qualities:
            default = hls_qualities[0]['url']
        if not default:
            default = hls

        return {
            "success": True,
            "streamUrl": default,
            "title": title,
            "high": high,
            "low": low,
            "hls": hls,
            "hlsQualities": hls_qualities,
            "formats": formats,
            "qualitiesCount": len(formats),
        }

    except requests.Timeout:
        return {"success": False, "error": "Source page timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"ok": True, "service": "Getvideo Multi-Quality Extractor v2"}


@app.get("/ping")
async def ping():
    return "OK"
