"""Try to obtain a Pillow wheel for the running Python from several mirrors."""
import json
import os
import re
import sys
import urllib.request

MIRRORS = [
    "https://pypi.tuna.tsinghua.edu.cn/simple/pillow/",
    "https://mirrors.aliyun.com/pypi/simple/pillow/",
    "https://mirrors.cloud.tencent.com/pypi/simple/pillow/",
    "https://pypi.org/simple/pillow/",
]

TAG = "cp314-cp314-win_amd64.whl"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pillow.whl")


def pick(html, base):
    hrefs = re.findall(r'href="([^"]+)"', html)
    matches = [h for h in hrefs if TAG in h]
    if not matches:
        return None
    href = matches[-1]
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http"):
        return href
    if href.startswith("../"):
        return base.rsplit("/simple/", 1)[0] + "/" + href.replace("../", "", 1)
    return base.rsplit("/", 1)[0] + "/" + href


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(OUT, "wb") as fh:
        total = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            fh.write(chunk)
            total += len(chunk)
    return total


for base in MIRRORS:
    try:
        with urllib.request.urlopen(base, timeout=30) as resp:
            html = resp.read().decode("utf-8", "ignore")
        url = pick(html, base)
        print("index", base, "->", url or "no cp314 wheel")
        if not url:
            continue
        size = download(url)
        print("downloaded", url, size)
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print("fail", base, type(exc).__name__, str(exc)[:160])
sys.exit(1)
