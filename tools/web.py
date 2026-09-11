"""栖语 联网工具箱：免费公开接口，失败自动降级，不拖垮主链路
- web_search: DuckDuckGo Lite 主 / Bing HTML 备
- fetch_page_meta: 通用网页元信息（og:title/description）
- video_info: B站/YouTube/抖音/通用 视频信息
- fetch_hotlist: 每日热门（B站热门视频 + DDG 综合热搜），本地缓存
"""
import asyncio
import json
import re
import time
import html as html_mod
import urllib.parse
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from pathutil import get_data_dir

_HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

HOT_CACHE = get_data_dir() / "hot_cache.json"
HOT_TTL = 6 * 3600  # 6 小时内不重复抓


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


async def _get(url: str, params: dict = None, headers: dict = None, timeout: float = 15) -> httpx.Response:
    h = dict(_HDRS)
    if headers:
        h.update(headers)
    async with httpx.AsyncClient(timeout=timeout, headers=h, follow_redirects=True) as client:
        return await client.get(url, params=params)


# ============ 搜索 ============

async def web_search(query: str, top_k: int = 5) -> list:
    """搜索网页，返回 [{title, url, snippet}]，全部失败返回 []。降级链：DDG → Bing → 百度。"""
    for fn in (_ddg_search, _bing_search, _baidu_search):
        try:
            out = await fn(query, top_k)
            if out:
                return out[:top_k]
        except Exception as e:
            logger.warning(f"[联网] 搜索降级: {type(e).__name__}: {e}")
    return []


async def _ddg_search(query: str, top_k: int) -> list:
    r = await _get("https://lite.duckduckgo.com/lite/", params={"q": query})
    r.raise_for_status()
    text = r.text
    results = []
    # DDG lite 结果：<a rel="nofollow" href="//duckduckgo.com/l/?uddg=...">标题</a> 后跟 snippet
    for m in re.finditer(r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.S):
        href = html_mod.unescape(m.group(1))
        title = _clean(m.group(2))
        if not title or title.startswith("!"):
            continue
        real = href
        if "uddg=" in href:
            real = urllib.parse.unquote(re.sub(r"^.*uddg=", "", href))
            real = re.sub(r"&rut=.*$", "", real)
        if real.startswith("//"):
            real = "https:" + real
        if not real.startswith("http"):
            continue
        # 找紧随其后的 snippet（到下一个 <a 为止）
        snippet = ""
        after = text[m.end():]
        nxt = re.search(r"<a ", after)
        if nxt:
            seg = after[:nxt.start()]
            snippet = _clean(re.sub(r"<[^>]+>", " ", seg))[:200]
        results.append({"title": title[:160], "url": real[:500], "snippet": snippet})
        if len(results) >= top_k:
            break
    return results


async def _bing_search(query: str, top_k: int) -> list:
    r = await _get("https://www.bing.com/search", params={"q": query, "setlang": "zh-hans", "mkt": "zh-CN"})
    r.raise_for_status()
    text = r.text
    results = []
    for block in re.findall(r'<li class="b_algo".*?</li>', text, re.S)[:top_k]:
        hm = re.search(r'<h2><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not hm:
            continue
        url = html_mod.unescape(hm.group(1))
        title = _clean(hm.group(2))
        pm = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        snippet = _clean(pm.group(1)) if pm else ""
        results.append({"title": title[:160], "url": url[:500], "snippet": snippet[:200]})
    return results


async def _baidu_search(query: str, top_k: int) -> list:
    """百度网页搜索兜底（国内可直连）。百度结果 URL 是跳转链接，标题可直接用。"""
    r = await _get("https://www.baidu.com/s", params={"wd": query, "rn": 20})
    r.raise_for_status()
    text = r.text
    results = []
    for m in re.finditer(r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.S):
        url = html_mod.unescape(m.group(1))
        title = _clean(m.group(2))
        if not title or not url.startswith("http"):
            continue
        snippet = ""
        tail = text[m.end():m.end() + 600]
        seg = _clean(re.sub(r"<[^>]+>", " ", tail))
        if seg:
            snippet = seg[:200]
        results.append({"title": title[:160], "url": url[:500], "snippet": snippet})
        if len(results) >= top_k:
            break
    return results


# ============ 图片搜索（免费源：Bing 图片主 / 百度图片备） ============

async def image_search(query: str, top_k: int = 3) -> list:
    """搜索图片，返回 [{title, url, image_url, source}]；全部失败返回 []。
    用户要看 xxx 长什么样时走这里：真的能找到图就把真实图片发过去。"""
    for fn in (_bing_image_search, _baidu_image_search):
        try:
            out = await fn(query, top_k)
            if out:
                return out[:top_k]
        except Exception as e:
            logger.warning(f"[图片] 搜索降级: {type(e).__name__}: {e}")
    return []


async def _bing_image_search(query: str, top_k: int) -> list:
    r = await _get("https://www.bing.com/images/search",
                   params={"q": query, "setlang": "zh-hans", "mkt": "zh-CN", "form": "HDRSC2"})
    r.raise_for_status()
    text = r.text
    out = []
    for m in re.finditer(r'\bm="(\{.*?\})"', text, re.S):
        try:
            d = json.loads(html_mod.unescape(m.group(1)))
        except Exception:
            continue
        murl = (d.get("murl") or d.get("turl") or "").strip()
        if not murl.startswith("http"):
            continue
        out.append({
            "title": _clean(d.get("t") or "")[:160],
            "url": (d.get("purl") or murl)[:500],
            "image_url": murl,
            "source": "bing",
        })
        if len(out) >= top_k:
            break
    return out


async def _baidu_image_search(query: str, top_k: int) -> list:
    r = await _get("https://image.baidu.com/search/acjson",
                   params={"tn": "resultjson_com", "ipn": "rj", "word": query,
                           "pn": 0, "rn": max(6, top_k * 2), "width": "", "height": "",
                           "face": 0, "istype": 2, "qc": "", "nc": 1, "fr": "", "simid": "",
                           "lm": -1, "ie": "utf-8", "oe": "utf-8", "cg": "", "z": "", "st": -1,
                           "cl": 2, "ct": "", "di": "", "pi": "", "tn": "resultjson_com"},
                   timeout=12)
    r.raise_for_status()
    data = r.json()
    out = []
    for it in (data.get("data") or []):
        if not isinstance(it, dict):
            continue
        img = (it.get("objURL") or it.get("thumbURL") or it.get("middleURL") or "").strip()
        if not img.startswith("http"):
            continue
        out.append({
            "title": _clean(it.get("fromPageTitle") or "")[:160],
            "url": (it.get("fromURLHost") or img)[:500],
            "image_url": img,
            "source": "baidu",
        })
        if len(out) >= top_k:
            break
    return out


# ============ 网页元信息 ============

async def fetch_page_meta(url: str) -> Optional[dict]:
    """抓网页 og 元信息（标题/描述），失败或非网页返回 None"""
    try:
        r = await _get(url, timeout=12)
        if r.status_code != 200:
            return None
        text = r.text
        title = ""
        desc = ""
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', text, re.I) or \
            re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', text, re.I)
        if m:
            title = _clean(m.group(1))
        if not title:
            m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
            title = _clean(m.group(1)) if m else ""
        m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', text, re.I) or \
            re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']', text, re.I)
        if m:
            desc = _clean(m.group(1))
        if not desc:
            m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', text, re.I)
            desc = _clean(m.group(1)) if m else ""
        if not title and not desc:
            return None
        return {"title": title[:200], "description": desc[:300], "url": url, "platform": "网页"}
    except Exception as e:
        logger.warning(f"[联网] 抓页失败 {url}: {type(e).__name__}")
        return None


# ============ 视频信息 ============

async def video_info(url: str) -> Optional[dict]:
    """解析视频链接信息（B站/YouTube/抖音/通用 og），失败返回 None（模型可自然说'我手机里没有xxx'）"""
    url = (url or "").strip()
    if not url.startswith("http"):
        return None
    if "bilibili.com" in url or "b23.tv" in url:
        info = await _bilibili_info(url)
        if info:
            return info
    if "youtube.com" in url or "youtu.be" in url:
        try:
            r = await _get("https://www.youtube.com/oembed", params={"url": url, "format": "json"})
            if r.status_code == 200:
                d = r.json()
                return {"platform": "youtube", "title": d.get("title", ""), "description": "", "author": d.get("author_name", ""), "url": url}
        except Exception:
            pass
    if "douyin.com" in url or "iesdouyin.com" in url:
        meta = await fetch_page_meta(url)
        if meta:
            meta["platform"] = "douyin"
            return meta
    # 通用
    meta = await fetch_page_meta(url)
    if meta:
        return meta
    return None


async def _bilibili_info(url: str) -> Optional[dict]:
    bvid = ""
    m = re.search(r"(BV[0-9A-Za-z]{10})", url)
    if m:
        bvid = m.group(1)
    elif "b23.tv" in url:
        try:
            r = await _get(url, timeout=10)
            url = str(r.url)
            m = re.search(r"(BV[0-9A-Za-z]{10})", url)
            if m:
                bvid = m.group(1)
        except Exception:
            pass
    if not bvid:
        return None
    try:
        r = await _get("https://api.bilibili.com/x/web-interface/view",
                       params={"bvid": bvid},
                       headers={"Referer": "https://www.bilibili.com/"})
        if r.status_code != 200:
            return None
        d = r.json().get("data") or {}
        if not d.get("title"):
            return None
        return {
            "platform": "bilibili",
            "title": d.get("title", ""),
            "description": (d.get("desc") or "")[:300],
            "author": (d.get("owner") or {}).get("name", ""),
            "url": f"https://www.bilibili.com/video/{bvid}",
        }
    except Exception as e:
        logger.warning(f"[联网] B站信息失败: {type(e).__name__}: {e}")
        return None


# ============ 每日热门 ============

async def fetch_hotlist(force: bool = False) -> list:
    """每日热门：B站热门视频 + DDG 综合热搜；本地缓存 6 小时"""
    if not force and HOT_CACHE.exists():
        try:
            data = json.loads(HOT_CACHE.read_text(encoding="utf-8"))
            if data.get("ts", 0) > time.time() - HOT_TTL and data.get("items"):
                return data["items"]
        except Exception:
            pass
    items = []
    try:
        r = await _get("https://api.bilibili.com/x/web-interface/popular",
                       params={"ps": 8, "pn": 1},
                       headers={"Referer": "https://www.bilibili.com/"})
        if r.status_code == 200:
            for v in (r.json().get("data") or {}).get("list", [])[:6]:
                bvid = v.get("bvid", "")
                title = _clean(v.get("title", ""))
                if title and bvid:
                    items.append({
                        "kind": "video",
                        "title": title[:120],
                        "url": f"https://www.bilibili.com/video/{bvid}",
                        "source": "B站热门",
                        "extra": f"UP主：{(v.get('owner') or {}).get('name', '')}",
                    })
    except Exception as e:
        logger.warning(f"[联网] B站热门抓取失败: {e}")
    try:
        for q in ("今日热搜 新闻", "今天 热门事件"):
            res = await web_search(q, top_k=3)
            for it in res:
                items.append({"kind": "news", "title": it["title"][:120], "url": it["url"], "source": "热搜", "extra": ""})
    except Exception as e:
        logger.warning(f"[联网] 热搜抓取失败: {e}")
    # 去重
    seen = set()
    uniq = []
    for it in items:
        key = it["title"][:30]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    if uniq:
        try:
            HOT_CACHE.write_text(json.dumps({"ts": time.time(), "items": uniq}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return uniq[:10]


# ============ 小红书 / 购物 ============

def is_shopish(url: str) -> bool:
    return any(k in url for k in ("xiaohongshu", "xhslink", "taobao", "tmall", "jd.com", "item.taobao", "detail.tmall"))


async def lookup_shop_url(url: str) -> Optional[dict]:
    """小红书/购物链接：尽力解析重定向与 og 元信息；登录墙内抓不到就返回 None，让模型像真人一样说'我手机里没有xxx'"""
    try:
        if "xhslink.com" in url or "xhslink.cn" in url:
            try:
                r = await _get(url, timeout=12)
                url = str(r.url)
            except Exception:
                pass
        meta = await fetch_page_meta(url)
        if meta:
            meta["platform"] = "小红书" if ("xiaohongshu" in url or "xhslink" in url) else "购物"
            return meta
        return None
    except Exception as e:
        logger.warning(f"[联网] 购物链接解析失败: {e}")
        return None
