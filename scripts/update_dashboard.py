#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPN Industry Daily Intelligence Dashboard
Fetches, deduplicates, categorizes and renders a daily HTML panel.
"""

import os, sys, csv, json, re, time, hashlib, traceback, argparse, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, urljoin
from collections import defaultdict

import requests
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
import pytz

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
SGT = pytz.timezone("Asia/Singapore")
UTC = pytz.utc

DEFAULT_LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "48"))
TIMEZONE_GRACE_HOURS   = int(os.environ.get("TIMEZONE_GRACE_HOURS", "12"))
SKIP_NETWORK           = os.environ.get("SKIP_NETWORK", "false").lower() == "true"

REDDIT_CLIENT_ID     = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT    = os.environ.get("REDDIT_USER_AGENT", "vpn-dashboard-bot/1.0 (by /u/vpndashbot)")

# Optional: enables AI-synthesized "今日要点" summaries per category.
# Without this key, a rule-based keyword/top-story fallback is used instead —
# the dashboard works either way, this just makes the synthesis smarter.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

REQUEST_TIMEOUT = 15
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

# Known RSS feed URLs for sites that block root URL scraping
KNOWN_RSS_URLS = {
    "nordvpn.com":           "https://nordvpn.com/blog/feed/",
    "expressvpn.com":        "https://www.expressvpn.com/blog/feed/",
    "surfshark.com":         "https://surfshark.com/blog/feed/",
    "protonvpn.com":         "https://protonvpn.com/blog/feed/",
    "mullvad.net":           "https://mullvad.net/blog/feed/atom",
    "windscribe.com":        "https://blog.windscribe.com/feed",
    "privateinternetaccess.com": "https://www.privateinternetaccess.com/blog/feed/",
    "cyberghostvpn.com":     "https://www.cyberghostvpn.com/privacyhub/feed/",
    "ipvanish.com":          "https://www.ipvanish.com/blog/feed/",
    "techradar.com":         "https://www.techradar.com/feeds/tag/vpn",
    "tomsguide.com":         "https://www.tomsguide.com/feeds/all",
    "comparitech.com":       "https://www.comparitech.com/blog/vpn-privacy/feed/",
    "restoreprivacy.com":    "https://restoreprivacy.com/feed/",
    "bleepingcomputer.com":  "https://www.bleepingcomputer.com/feed/",
    "theverge.com":          "https://www.theverge.com/rss/index.xml",
    "wired.com":             "https://www.wired.com/feed/category/security/latest/rss",
    "gov.uk":                "https://www.gov.uk/search/news-and-communications.atom?keywords=VPN",
    "ofcom.org.uk":          "https://www.ofcom.org.uk/about-ofcom/rss/news.xml",
    "ftc.gov":               "https://www.ftc.gov/feeds/press-release.xml",
    "cisa.gov":              "https://www.cisa.gov/cybersecurity-advisories/all.xml",
    "digital-strategy.ec.europa.eu": "https://digital-strategy.ec.europa.eu/en/rss.xml",
}

CATEGORY_ORDER = ["竞品动态", "社交媒体", "reddit讨论", "政策风险", "第三方网站"]

DIRS = {
    "docs":    Path("docs"),
    "data":    Path("docs/data"),
    "archive": Path("docs/archive"),
    "config":  Path("config"),
    "scripts": Path("scripts"),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("vpn_dashboard")

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def now_sgt():
    return datetime.now(SGT)

def to_sgt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(SGT)

def parse_time_safe(raw):
    """Parse a time string into a timezone-aware datetime (SGT). Returns None on failure."""
    if not raw:
        return None
    try:
        dt = dateparser.parse(str(raw), fuzzy=True)
        return to_sgt(dt)
    except Exception:
        return None

def is_within_window(dt, lookback_hours, grace_hours=TIMEZONE_GRACE_HOURS):
    if dt is None:
        return False
    cutoff = now_sgt() - timedelta(hours=lookback_hours + grace_hours)
    return dt >= cutoff

def age_label(dt):
    if dt is None:
        return "时间不明"
    diff = now_sgt() - dt
    h = diff.total_seconds() / 3600
    if h < 1:
        return f"{int(diff.total_seconds()/60)} 分钟前"
    if h < 24:
        return f"{int(h)} 小时前"
    return f"{int(h/24)} 天前"

def safe_get(url, timeout=REQUEST_TIMEOUT, headers=None, retries=2):
    h = {**REQUEST_HEADERS, **(headers or {})}
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=h, timeout=timeout, allow_redirects=True)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2)

def slug(text):
    return hashlib.md5(text.encode()).hexdigest()[:8]

def clean_text(t):
    if not t:
        return ""
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:500]

def title_fingerprint(title):
    """Reduce title to key tokens for deduplication.
    Handles both space-separated (English) and CJK (Chinese) text —
    CJK text has no whitespace between words, so word-splitting alone
    would make every Chinese title a single unmatched token."""
    title = title.lower()
    has_cjk = bool(re.search(r'[\u4e00-\u9fff]', title))
    if has_cjk:
        # character bigrams over CJK + alnum runs
        cleaned = re.sub(r'[^\u4e00-\u9fff\w]', '', title)
        bigrams = {cleaned[i:i+2] for i in range(len(cleaned) - 1)}
        return frozenset(list(bigrams)[:20])
    else:
        title = re.sub(r'[^\w\s]', '', title)
        words = [w for w in title.split() if len(w) > 3]
        return frozenset(words[:10])

# ─────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────

class Article:
    def __init__(self, title, url, summary, published_dt, source_name,
                 category, source_type="", raw_time=""):
        self.title        = clean_text(title) or "(无标题)"
        self.url          = url or ""
        self.summary      = clean_text(summary)
        self.published_dt = published_dt          # timezone-aware or None
        self.source_name  = source_name
        self.category     = category
        self.source_type  = source_type
        self.raw_time     = raw_time
        self.id           = slug(f"{url}{title}")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "published_sgt": self.published_dt.strftime("%Y-%m-%d %H:%M SGT") if self.published_dt else None,
            "published_iso": self.published_dt.isoformat() if self.published_dt else None,
            "source_name": self.source_name,
            "category": self.category,
            "source_type": self.source_type,
        }

class FetchResult:
    def __init__(self, source_name, category, url):
        self.source_name = source_name
        self.category    = category
        self.url         = url
        self.articles    : list[Article] = []
        self.success     = False
        self.method      = ""
        self.error       = ""
        self.note        = ""

# ─────────────────────────────────────────────
# FEED / RSS FETCHER
# ─────────────────────────────────────────────

def fetch_rss(source_name, url, category):
    result = FetchResult(source_name, category, url)
    try:
        feed = feedparser.parse(url, request_headers=REQUEST_HEADERS)
        if feed.bozo and not feed.entries:
            raise ValueError(f"feedparser bozo: {feed.bozo_exception}")
        for entry in feed.entries[:30]:
            title   = entry.get("title", "")
            link    = entry.get("link", "")
            summary = BeautifulSoup(entry.get("summary", entry.get("content", [{"value":""}])[0].get("value","")), "lxml").get_text()
            raw_t   = entry.get("published", entry.get("updated", ""))
            pub_dt  = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                import calendar
                ts = calendar.timegm(entry.published_parsed)
                pub_dt = datetime.fromtimestamp(ts, tz=UTC)
                pub_dt = to_sgt(pub_dt)
            else:
                pub_dt = parse_time_safe(raw_t)

            result.articles.append(Article(
                title=title, url=link, summary=summary[:400],
                published_dt=pub_dt, source_name=source_name,
                category=category, source_type="RSS/Feed", raw_time=raw_t
            ))
        result.success = True
        result.method  = "RSS"
    except Exception as e:
        result.error = str(e)
    return result

# ─────────────────────────────────────────────
# BLOG HTML FETCHER (generic)
# ─────────────────────────────────────────────

def fetch_html_blog(source_name, url, category):
    result = FetchResult(source_name, category, url)
    try:
        r   = safe_get(url)
        soup = BeautifulSoup(r.text, "lxml")
        articles = []

        # Try common article selectors
        selectors = [
            "article", ".post", ".blog-post", ".entry",
            ".news-item", ".article-card", ".post-card",
            "h2 a", "h3 a",
        ]
        candidates = []
        for sel in selectors:
            found = soup.select(sel)
            if found:
                candidates = found
                break

        if not candidates:
            # fallback: all <a> with substantial text near a date
            candidates = soup.find_all("a", href=True)

        seen_urls = set()
        for c in candidates[:25]:
            # Extract title
            title_tag = c.find(["h1","h2","h3","h4"]) or c
            if title_tag.name == "a":
                title = title_tag.get_text()
                link  = title_tag["href"]
            else:
                a = c.find("a", href=True)
                title = title_tag.get_text()
                link  = a["href"] if a else ""

            title = clean_text(title)
            if not title or len(title) < 5:
                continue

            # Resolve relative URL
            if link and not link.startswith("http"):
                link = urljoin(url, link)

            if link in seen_urls:
                continue
            seen_urls.add(link)

            # Extract date
            date_text = ""
            for dt_sel in ["time", ".date", ".published", ".post-date", "meta[property='article:published_time']"]:
                dt_el = c.find(dt_sel) if hasattr(c, 'find') else None
                if dt_el:
                    date_text = dt_el.get("datetime", "") or dt_el.get_text()
                    break

            pub_dt = parse_time_safe(date_text)

            # Summary
            summary = ""
            p = c.find("p")
            if p:
                summary = p.get_text()[:300]

            articles.append(Article(
                title=title, url=link, summary=summary,
                published_dt=pub_dt, source_name=source_name,
                category=category, source_type="官网HTML", raw_time=date_text
            ))

        result.articles = articles
        result.success  = True
        result.method   = "HTML"
    except Exception as e:
        result.error = str(e)
    return result

# ─────────────────────────────────────────────
# REDDIT FETCHER (multi-level fallback)
# ─────────────────────────────────────────────

def get_reddit_token():
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        return None
    try:
        r = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
            headers={"User-Agent": REDDIT_USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("access_token")
    except Exception as e:
        log.warning(f"Reddit OAuth failed: {e}")
        return None

_reddit_token = None
_reddit_token_fetched = False

def reddit_oauth_token():
    global _reddit_token, _reddit_token_fetched
    if not _reddit_token_fetched:
        _reddit_token = get_reddit_token()
        _reddit_token_fetched = True
    return _reddit_token

def parse_reddit_listing(data, source_name, category):
    articles = []
    children = data.get("data", {}).get("children", [])
    for child in children:
        p = child.get("data", {})
        title     = p.get("title", "")
        link      = "https://www.reddit.com" + p.get("permalink", "")
        selftext  = p.get("selftext", "")[:300]
        score     = p.get("score", 0)
        created   = p.get("created_utc")
        pub_dt    = None
        if created:
            pub_dt = datetime.fromtimestamp(created, tz=UTC)
            pub_dt = to_sgt(pub_dt)
        articles.append(Article(
            title=title, url=link,
            summary=f"[Score: {score}] {selftext}",
            published_dt=pub_dt, source_name=source_name,
            category=category, source_type="Reddit",
            raw_time=str(created)
        ))
    return articles

def fetch_reddit_oauth(subreddit, source_name, category):
    token = reddit_oauth_token()
    if not token:
        return None, "No OAuth token"
    try:
        url = f"https://oauth.reddit.com/r/{subreddit}/new.json?limit=25"
        r = requests.get(url, headers={
            "Authorization": f"bearer {token}",
            "User-Agent": REDDIT_USER_AGENT,
        }, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return parse_reddit_listing(r.json(), source_name, category), "OAuth"
    except Exception as e:
        return None, str(e)

def fetch_reddit_json(subreddit, source_name, category):
    try:
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=25"
        r = requests.get(url, headers={
            "User-Agent": REDDIT_USER_AGENT,
        }, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return parse_reddit_listing(r.json(), source_name, category), "PublicJSON"
    except Exception as e:
        return None, str(e)

def fetch_reddit_rss(subreddit, source_name, category):
    url = f"https://www.reddit.com/r/{subreddit}/new/.rss"
    result = fetch_rss(source_name, url, category)
    if result.success and result.articles:
        return result.articles, "RSS"
    return None, result.error

def fetch_old_reddit(subreddit, source_name, category):
    try:
        url  = f"https://old.reddit.com/r/{subreddit}/new/"
        r    = safe_get(url, headers={"User-Agent": REDDIT_USER_AGENT})
        soup = BeautifulSoup(r.text, "lxml")
        articles = []
        for thing in soup.select("div.thing")[:25]:
            title_el = thing.select_one("a.title")
            if not title_el:
                continue
            title = title_el.get_text()
            href  = title_el.get("href", "")
            if href.startswith("/r/"):
                href = "https://www.reddit.com" + href
            time_el = thing.select_one("time")
            raw_t   = time_el.get("datetime","") if time_el else ""
            pub_dt  = parse_time_safe(raw_t)
            score_el = thing.select_one("div.score.unvoted")
            score    = score_el.get_text("").strip() if score_el else ""
            articles.append(Article(
                title=title, url=href,
                summary=f"[old.reddit] {score}",
                published_dt=pub_dt, source_name=source_name,
                category=category, source_type="old.reddit",
                raw_time=raw_t
            ))
        if articles:
            return articles, "old.reddit"
        return None, "No articles found"
    except Exception as e:
        return None, str(e)

def fetch_jina_reddit(subreddit, source_name, category):
    try:
        url  = f"https://r.jina.ai/https://www.reddit.com/r/{subreddit}/new/"
        r    = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        lines = r.text.split('\n')
        articles = []
        for line in lines:
            if re.search(r'https://www\.reddit\.com/r/\w+/comments/', line):
                m = re.search(r'\[([^\]]+)\]\((https://www\.reddit\.com/r/\w+/comments/[^\)]+)\)', line)
                if m:
                    articles.append(Article(
                        title=m.group(1), url=m.group(2),
                        summary="[via Jina Reader]",
                        published_dt=None, source_name=source_name,
                        category=category, source_type="Jina/Reddit",
                        raw_time=""
                    ))
        if articles:
            return articles, "Jina"
        return None, "No articles found"
    except Exception as e:
        return None, str(e)

def fetch_reddit(source_name, subreddit_url, category):
    result = FetchResult(source_name, category, subreddit_url)

    # Parse subreddit name
    m = re.search(r'/r/([^/]+)', subreddit_url)
    if not m:
        result.error = "Cannot parse subreddit name"
        return result
    subreddit = m.group(1)

    # NOTE (2026): Reddit's "Responsible Builder Policy" rollout has largely
    # gated self-serve script-app creation and tightened unauthenticated JSON
    # access. RSS (.rss suffix) remains the most reliable no-auth path, so it
    # is tried first. OAuth is only attempted first if credentials are present
    # (i.e. the user successfully obtained them), since it's the most complete
    # data source when available.
    if REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET:
        methods = [
            ("OAuth",      lambda: fetch_reddit_oauth(subreddit, source_name, category)),
            ("RSS",        lambda: fetch_reddit_rss(subreddit, source_name, category)),
            ("old.reddit", lambda: fetch_old_reddit(subreddit, source_name, category)),
            ("PublicJSON", lambda: fetch_reddit_json(subreddit, source_name, category)),
            ("Jina",       lambda: fetch_jina_reddit(subreddit, source_name, category)),
        ]
    else:
        methods = [
            ("RSS",        lambda: fetch_reddit_rss(subreddit, source_name, category)),
            ("old.reddit", lambda: fetch_old_reddit(subreddit, source_name, category)),
            ("PublicJSON", lambda: fetch_reddit_json(subreddit, source_name, category)),
            ("Jina",       lambda: fetch_jina_reddit(subreddit, source_name, category)),
        ]

    errors = []
    for method_name, fn in methods:
        try:
            articles, info = fn()
            if articles:
                result.articles = articles
                result.success  = True
                result.method   = method_name
                result.note     = f"成功方式: {method_name}"
                log.info(f"Reddit {subreddit}: {method_name} → {len(articles)} items")
                return result
            else:
                errors.append(f"{method_name}: {info}")
        except Exception as e:
            errors.append(f"{method_name}: {e}")
        time.sleep(1)

    result.error = " | ".join(errors)
    result.note  = "所有方式均失败"
    diagnosis = []
    if not REDDIT_CLIENT_ID:
        diagnosis.append("未配置OAuth（2026年起Reddit已大幅限制自助创建App，未配置属正常情况，不影响RSS等兜底方式）")
    diagnosis.append("可能被限流或GitHub Actions IP被封")
    diagnosis.append("该 subreddit 可能临时不可访问或改名")
    result.note += "\n诊断建议: " + "; ".join(diagnosis)
    return result

# ─────────────────────────────────────────────
# GENERIC FETCHER ROUTER
# ─────────────────────────────────────────────

def detect_rss_url(url):
    """Try to find RSS feed for a given URL. Checks known URLs first."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")

    # Check known RSS URLs first
    for key, rss in KNOWN_RSS_URLS.items():
        if key in domain:
            return rss

    # Then try common patterns
    candidates = [
        url.rstrip('/') + "/feed",
        url.rstrip('/') + "/feed.xml",
        url.rstrip('/') + "/rss",
        url.rstrip('/') + "/rss.xml",
        url.rstrip('/') + "/atom.xml",
        url.rstrip('/') + "/feed/atom",
    ]
    for candidate in candidates:
        try:
            feed = feedparser.parse(candidate, request_headers=REQUEST_HEADERS)
            if feed.entries:
                return candidate
        except:
            pass
    return None

def fetch_source(row):
    source_name = row.get("source_name", "Unknown")
    url         = row.get("url", "").strip()
    category    = row.get("category", "第三方网站")

    if not url:
        r = FetchResult(source_name, category, url)
        r.error = "URL为空"
        return r

    # Reddit
    if "reddit.com/r/" in url:
        return fetch_reddit(source_name, url, category)

    # Nitter RSS (Twitter)
    if "nitter.net" in url:
        return fetch_rss(source_name, url, category)

    # Known RSS/Atom feeds (direct URL)
    rss_hints = ["/feed", "/rss", ".rss", ".xml", "/atom", "feeds.feedburner"]
    if any(h in url for h in rss_hints):
        result = fetch_rss(source_name, url, category)
        if result.success and result.articles:
            return result

    # Try known RSS map first (fast, no extra HTTP round-trip)
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    for key, rss_url in KNOWN_RSS_URLS.items():
        if key in domain:
            result = fetch_rss(source_name, rss_url, category)
            if result.success and result.articles:
                return result
            break  # tried the known URL, fall through to HTML

    # Try RSS autodiscovery
    rss_url = detect_rss_url(url)
    if rss_url:
        result = fetch_rss(source_name, rss_url, category)
        if result.success and result.articles:
            return result

    # Fallback: HTML scraping
    result = fetch_html_blog(source_name, url, category)
    return result

# ─────────────────────────────────────────────
# MANUAL INPUTS
# ─────────────────────────────────────────────

def load_manual_inputs(path):
    articles = []
    if not path.exists():
        return articles
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row.get("title", "").strip()
            if not title or title.startswith("示例"):
                continue
            url       = row.get("url", "").strip()
            category  = row.get("category", "第三方网站").strip()
            summary   = row.get("summary", "").strip()
            pub_raw   = row.get("published_time", "").strip()
            pub_dt    = parse_time_safe(pub_raw)
            source    = row.get("source_name", "手工补充").strip()
            articles.append(Article(
                title=title, url=url, summary=summary,
                published_dt=pub_dt, source_name=source,
                category=category, source_type="手工补充", raw_time=pub_raw
            ))
    return articles

# ─────────────────────────────────────────────
# DEDUPLICATION & MERGING
# ─────────────────────────────────────────────

def jaccard(a: frozenset, b: frozenset):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def deduplicate_and_merge(articles: list[Article]):
    """
    Group articles that appear to be about the same event.
    Returns list of merged groups: [{title, summary, sources:[Article], earliest_dt, latest_dt}]
    """
    groups = []

    for art in articles:
        fp = title_fingerprint(art.title)
        merged = False
        for g in groups:
            if jaccard(g["fp"], fp) >= 0.45:
                g["sources"].append(art)
                g["fp"] = g["fp"] | fp
                if art.published_dt:
                    if g["earliest_dt"] is None or art.published_dt < g["earliest_dt"]:
                        g["earliest_dt"] = art.published_dt
                    if g["latest_dt"] is None or art.published_dt > g["latest_dt"]:
                        g["latest_dt"] = art.published_dt
                merged = True
                break
        if not merged:
            groups.append({
                "fp":         fp,
                "title":      art.title,
                "summary":    art.summary,
                "sources":    [art],
                "earliest_dt": art.published_dt,
                "latest_dt":   art.published_dt,
                "category":    art.category,
            })

    return groups

# ─────────────────────────────────────────────
# IMPORTANCE SCORING
# ─────────────────────────────────────────────

def importance_score(group):
    """
    Data-ops style prioritization:信号被多个独立来源印证 比 单源信息更重要，
    同时新鲜度也加分。score 用于组内排序，让真正值得看的内容排在最前面。
    """
    src_count = len(group["sources"])
    latest    = group["latest_dt"]
    recency_bonus = 0.0
    if latest:
        hours_ago = (now_sgt() - latest).total_seconds() / 3600
        recency_bonus = max(0.0, 24 - hours_ago) / 24 * 3  # up to +3 for very fresh
    return src_count * 4 + recency_bonus

# ─────────────────────────────────────────────
# KEYWORD EXTRACTION (rule-based fallback)
# ─────────────────────────────────────────────

STOPWORDS = set("""
the a an and or but if then else for of to in on at by with from as is are was were
be been being this that these those it its they them their there here what which who
whom how why when where not no nor so than too very can will would should could may
might must shall do does did have has had you your we our i my he she his her vpn
about into over under again further once more most other some such only own same
""".split())

def extract_keywords(groups, top_n=8):
    counter = defaultdict(int)
    for g in groups:
        text = (g["title"] + " " + (g["summary"] or "")).lower()
        words = re.findall(r"[a-z][a-z\-]{2,}", text)
        for w in words:
            if w not in STOPWORDS and len(w) > 3:
                counter[w] += 1
    ranked = sorted(counter.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in ranked[:top_n] if _ >= 2] or [w for w, _ in ranked[:top_n]]

# ─────────────────────────────────────────────
# CATEGORY HIGHLIGHTS — AI synthesis with rule-based fallback
# ─────────────────────────────────────────────

def generate_ai_highlights(cat, groups):
    """Call Anthropic API to synthesize what's actually being discussed.
    Returns list[str] (bullets) or None on any failure (caller falls back)."""
    if not ANTHROPIC_API_KEY or not groups:
        return None
    try:
        top = sorted(groups, key=importance_score, reverse=True)[:15]
        payload_items = [
            {
                "title": g["title"][:120],
                "summary": (g["summary"] or "")[:200],
                "source_count": len(g["sources"]),
            }
            for g in top
        ]
        prompt = (
            f"以下是「{cat}」类别下，过去时效窗口内抓取到的 VPN 行业信息条目（JSON数组，"
            f"source_count 表示有多少独立来源报道了同一件事，数值越高说明信号越强）：\n\n"
            f"{json.dumps(payload_items, ensure_ascii=False)}\n\n"
            "请用中文写出 3-5 条「今日要点」，每条不超过35字，帮助阅读者快速抓住"
            "本类别用户/媒体/官方在讨论什么、有什么共性趋势或异常信号。"
            "只做客观信息归纳，不要给出运营建议、增长建议或下一步行动。"
            "直接输出要点列表，每行一条，不要编号前缀、不要多余说明文字。"
        )
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        bullets = [ln.strip("•-* 　").strip() for ln in text.strip().split("\n") if ln.strip()]
        return bullets[:5] if bullets else None
    except Exception as e:
        log.warning(f"AI highlight generation failed for {cat}: {e}")
        return None

def generate_rule_based_highlights(cat, groups):
    """No-AI fallback: surface the top stories by importance + frequent keywords."""
    if not groups:
        return ["本时效窗口内暂无该类别有效信息"]
    top = sorted(groups, key=importance_score, reverse=True)[:3]
    bullets = []
    for g in top:
        src_n = len(g["sources"])
        tag = f"（{src_n}个来源印证）" if src_n > 1 else ""
        bullets.append(f"{g['title'][:50]}{tag}")
    keywords = extract_keywords(groups)
    if keywords:
        bullets.append("高频关键词：" + "、".join(keywords[:6]))
    return bullets

def generate_category_highlights(cat, groups):
    ai_result = generate_ai_highlights(cat, groups)
    if ai_result:
        return ai_result, "AI"
    return generate_rule_based_highlights(cat, groups), "规则"



def run_pipeline(lookback_hours=DEFAULT_LOOKBACK_HOURS, skip_network=SKIP_NETWORK):
    run_start = now_sgt()
    log.info(f"=== Dashboard run started at {run_start.strftime('%Y-%m-%d %H:%M SGT')} ===")
    log.info(f"Lookback: {lookback_hours}h | Grace: {TIMEZONE_GRACE_HOURS}h | skip_network={skip_network}")

    # Load sources
    sources_path = DIRS["config"] / "sources.csv"
    sources = []
    if sources_path.exists():
        with open(sources_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("enabled", "true").lower() == "true":
                    sources.append(row)
    log.info(f"Loaded {len(sources)} enabled sources")

    fetch_results : list[FetchResult] = []

    if not skip_network:
        for row in sources:
            sname = row.get("source_name","?")
            log.info(f"Fetching: {sname}")
            try:
                result = fetch_source(row)
                fetch_results.append(result)
            except Exception as e:
                log.error(f"  FATAL error fetching {sname}: {e}")
                r = FetchResult(sname, row.get("category",""), row.get("url",""))
                r.error = str(e)
                fetch_results.append(r)
            time.sleep(0.5)
    else:
        log.warning("SKIP_NETWORK=true — skipping all network fetches")

    # Load manual inputs
    manual = load_manual_inputs(DIRS["config"] / "manual_inputs.csv")
    log.info(f"Manual inputs: {len(manual)} items")

    # Collect all articles
    all_articles : list[Article] = []
    for fr in fetch_results:
        all_articles.extend(fr.articles)
    all_articles.extend(manual)

    log.info(f"Total raw articles: {len(all_articles)}")

    # Partition: in-window vs filtered
    in_window   = [a for a in all_articles if is_within_window(a.published_dt, lookback_hours)]
    no_time     = [a for a in all_articles if a.published_dt is None]
    too_old     = [a for a in all_articles if a.published_dt is not None and not is_within_window(a.published_dt, lookback_hours)]

    log.info(f"In window: {len(in_window)} | No time: {len(no_time)} | Too old: {len(too_old)}")

    # Group by category and deduplicate
    cat_groups = defaultdict(list)
    for cat in CATEGORY_ORDER:
        cat_articles = [a for a in in_window if a.category == cat]
        groups = deduplicate_and_merge(cat_articles)
        # Sort by importance: multi-source-confirmed + fresher items surface first
        groups.sort(key=importance_score, reverse=True)
        cat_groups[cat] = groups

    # Generate per-category highlight summaries ("今日要点")
    cat_highlights = {}
    cat_highlight_method = {}
    for cat in CATEGORY_ORDER:
        bullets, method = generate_category_highlights(cat, cat_groups[cat])
        cat_highlights[cat] = bullets
        cat_highlight_method[cat] = method

    # Failed sources
    failed_sources = [fr for fr in fetch_results if not fr.success]
    success_sources = [fr for fr in fetch_results if fr.success]

    category_counts = {cat: len(cat_groups[cat]) for cat in CATEGORY_ORDER}

    # Day-over-day delta vs yesterday's archive (data-ops style trend indicator)
    category_deltas = {cat: None for cat in CATEGORY_ORDER}
    try:
        yesterday = (run_start - timedelta(days=1)).strftime("%Y-%m-%d")
        prev_path = DIRS["archive"] / f"{yesterday}.json"
        if prev_path.exists():
            prev_data = json.loads(prev_path.read_text(encoding="utf-8"))
            prev_counts = prev_data.get("stats", {}).get("category_counts", {})
            for cat in CATEGORY_ORDER:
                if cat in prev_counts:
                    category_deltas[cat] = category_counts[cat] - prev_counts[cat]
    except Exception as e:
        log.warning(f"Could not compute day-over-day delta: {e}")

    # Stats
    stats = {
        "run_time_sgt": run_start.strftime("%Y-%m-%d %H:%M SGT"),
        "run_time_iso": run_start.isoformat(),
        "timezone": "Asia/Singapore (SGT, UTC+8)",
        "lookback_hours": lookback_hours,
        "grace_hours": TIMEZONE_GRACE_HOURS,
        "total_sources": len(sources),
        "fetch_success": len(success_sources),
        "fetch_failed": len(failed_sources),
        "total_raw": len(all_articles),
        "in_window": len(in_window),
        "no_time": len(no_time),
        "too_old": len(too_old),
        "category_counts": category_counts,
        "category_deltas": category_deltas,
    }

    return {
        "stats": stats,
        "cat_groups": cat_groups,
        "cat_highlights": cat_highlights,
        "cat_highlight_method": cat_highlight_method,
        "failed_sources": failed_sources,
        "no_time_articles": no_time,
        "too_old_articles": too_old,
        "fetch_results": fetch_results,
    }

# ─────────────────────────────────────────────
# HTML GENERATOR
# ─────────────────────────────────────────────

CATEGORY_ICONS = {
    "竞品动态": "🏢",
    "社交媒体": "📣",
    "reddit讨论": "💬",
    "政策风险": "⚖️",
    "第三方网站": "🌐",
}

CATEGORY_COLORS = {
    "竞品动态": "#2563eb",
    "社交媒体": "#7c3aed",
    "reddit讨论": "#ea580c",
    "政策风险": "#dc2626",
    "第三方网站": "#059669",
}

CATEGORY_DESC = {
    "竞品动态": (
        "来源：竞品官网、官方博客、新闻室、产品更新页等官方渠道。"
        "监控竞品产品发布、促销活动、功能上线、安全公告及官方声明。"
        "仅限官方发布内容，媒体转载请见「第三方网站」板块。"
    ),
    "社交媒体": (
        "来源：竞品官方 X/Twitter 等社交账号（经 Nitter RSS 抓取）。"
        "记录竞品的实时发文、营销话术、与用户互动内容。"
        "仅包含经验证的官方账号，用户讨论帖请见「reddit讨论」板块。"
    ),
    "reddit讨论": (
        "来源：r/VPN、r/vpnreviews、r/nordvpn、r/ProtonVPN、r/UniUK 等多个社区。"
        "重点关注：真实用户的购买决策、竞品抱怨、节点故障、流媒体解锁、"
        "价格/退款、隐私信任、英国学生场景等高价值舆情信号。"
    ),
    "政策风险": (
        "来源：GOV.UK、Ofcom、ICO（英国信息专员）、欧盟数字战略、CISA、FTC 等官方机构。"
        "监控可能影响 VPN 行业的立法动态、监管公告、执法行动、数据保护法规更新。"
        "媒体对政策的解读/报道放入「第三方网站」，本板块仅收录官方一手文件。"
    ),
    "第三方网站": (
        "来源：TechRadar、Tom's Guide、Comparitech、VPNCompare（英国）、top10vpn、"
        "BleepingComputer、Trustpilot、AirVPN论坛、Privacyguides 等。"
        "涵盖媒体评测、SEO 排行、用户投诉、安全漏洞报道、行业报告。"
        "Affiliate 属性较强的来源（vpnMentor 等）已排除，以保证信息客观性。"
    ),
}

def fmt_dt(dt):
    if dt is None:
        return "时间不明"
    return dt.strftime("%Y-%m-%d %H:%M SGT")

def render_source_tag(art: Article):
    link_html = f'<a href="{art.url}" target="_blank" rel="noopener">{art.url[:60]}{"…" if len(art.url)>60 else ""}</a>' if art.url else "无链接"
    time_str  = fmt_dt(art.published_dt)
    age_str   = age_label(art.published_dt)
    return f"""<div class="source-item">
  <span class="source-name">{art.source_name}</span>
  <span class="source-type">{art.source_type}</span>
  <span class="source-title">《{art.title[:80]}》</span>
  <span class="source-time">{time_str}（{age_str}）</span>
  <span class="source-link">{link_html}</span>
</div>"""

def render_group_card(group, cat):
    color = CATEGORY_COLORS.get(cat, "#374151")
    sources_html = "\n".join(render_source_tag(a) for a in group["sources"])
    src_count = len(group["sources"])
    earliest = fmt_dt(group["earliest_dt"])
    latest   = fmt_dt(group["latest_dt"])
    age      = age_label(group["latest_dt"])

    time_range = earliest if earliest == latest else f"{earliest} → {latest}"

    if src_count >= 3:
        signal_badge = '<span class="signal-badge signal-strong">🔥 多源印证</span>'
    elif src_count == 2:
        signal_badge = '<span class="signal-badge signal-medium">📎 2个来源</span>'
    else:
        signal_badge = ''

    return f"""<div class="info-card" style="border-left-color:{color}">
  <div class="card-header">
    <h3 class="card-title">{group['title']}</h3>
    <div class="card-meta">
      <span class="time-badge">{age}</span>
      {signal_badge}
    </div>
  </div>
  {f'<p class="card-summary">{group["summary"]}</p>' if group["summary"] else ''}
  <div class="card-time">🕐 {time_range}</div>
  <details class="sources-details">
    <summary>📋 查看来源（{src_count} 条）</summary>
    <div class="sources-list">{sources_html}</div>
  </details>
</div>"""

def render_history_nav(mode="index", current_date=""):
    """
    Date-filter widget. 'mode'='index' lives on docs/index.html (links into
    archive/), 'mode'='archive' lives on docs/archive/{date}.html (links back
    to ../index.html and sideways to other archive/{date}.html files).
    Reads docs/archive/manifest.json client-side — no server needed, works
    on static GitHub Pages.
    """
    if mode == "archive":
        manifest_path = "manifest.json"
        nav_prefix    = ""
        back_link     = '<a href="../index.html" class="history-btn history-btn-secondary">↩ 返回今日最新</a>'
    else:
        manifest_path = "archive/manifest.json"
        nav_prefix    = "archive/"
        back_link     = ""

    return f"""<div class="history-nav">
  <span class="history-label">📅 历史数据查询</span>
  <select id="historyDateSelect" class="history-select">
    <option value="">加载中…</option>
  </select>
  <button id="historyGoBtn" class="history-btn" type="button">查看</button>
  {back_link}
</div>
<script>
(function() {{
  var manifestUrl = "{manifest_path}";
  var navPrefix   = "{nav_prefix}";
  var currentDate = "{current_date}";
  var sel = document.getElementById('historyDateSelect');
  var btn = document.getElementById('historyGoBtn');

  fetch(manifestUrl).then(function(r) {{
    if (!r.ok) throw new Error('no manifest');
    return r.json();
  }}).then(function(data) {{
    sel.innerHTML = '';
    if (!data || !data.length) {{
      sel.innerHTML = '<option value="">暂无历史归档</option>';
      return;
    }}
    data.forEach(function(item) {{
      var opt = document.createElement('option');
      opt.value = item.date;
      var label = item.date + '（共' + item.total + '条）';
      if (item.date === currentDate) label += ' · 当前';
      opt.textContent = label;
      sel.appendChild(opt);
    }});
    if (currentDate) {{
      sel.value = currentDate;
    }}
  }}).catch(function(e) {{
    sel.innerHTML = '<option value="">暂无历史归档（首次运行后将自动生成）</option>';
  }});

  btn.addEventListener('click', function() {{
    var d = sel.value;
    if (!d) return;
    window.location.href = navPrefix + d + '.html';
  }});
}})();
</script>"""

def render_html(data, mode="index", current_date=""):
    stats     = data["stats"]
    cat_groups = data["cat_groups"]
    cat_highlights = data["cat_highlights"]
    cat_highlight_method = data["cat_highlight_method"]
    failed    = data["failed_sources"]
    no_time   = data["no_time_articles"]
    too_old   = data["too_old_articles"]
    deltas    = stats.get("category_deltas", {})

    # Category overview chips (with day-over-day delta)
    overview_html = ""
    for cat in CATEGORY_ORDER:
        count = stats["category_counts"].get(cat, 0)
        color = CATEGORY_COLORS.get(cat, "#374151")
        icon  = CATEGORY_ICONS.get(cat, "•")
        delta = deltas.get(cat)
        if delta is None:
            delta_html = ""
        elif delta > 0:
            delta_html = f'<span class="chip-delta delta-up">▲{delta}</span>'
        elif delta < 0:
            delta_html = f'<span class="chip-delta delta-down">▼{abs(delta)}</span>'
        else:
            delta_html = '<span class="chip-delta delta-flat">—</span>'
        overview_html += f'<a href="#cat-{slug(cat)}" class="overview-chip" style="border-color:{color}"><span class="chip-icon">{icon}</span><span class="chip-label">{cat}</span><span class="chip-count" style="background:{color}">{count}</span>{delta_html}</a>\n'

    # Main sections
    sections_html = ""
    for cat in CATEGORY_ORDER:
        groups = cat_groups.get(cat, [])
        color  = CATEGORY_COLORS.get(cat, "#374151")
        icon   = CATEGORY_ICONS.get(cat, "•")
        count  = len(groups)
        desc   = CATEGORY_DESC.get(cat, "")
        highlights = cat_highlights.get(cat, [])
        h_method   = cat_highlight_method.get(cat, "规则")

        if groups:
            cards_html = "\n".join(render_group_card(g, cat) for g in groups)
        else:
            cards_html = '<div class="empty-section">暂无本时效窗口内的有效信息</div>'

        desc_html = f'<p class="cat-desc">{desc}</p>' if desc else ""

        # "今日要点" synthesis box
        highlight_items = "".join(f'<li>{h}</li>' for h in highlights)
        method_tag = "🤖 AI摘要" if h_method == "AI" else "📊 关键词/要点提取"
        highlight_html = f"""<div class="highlight-box" style="border-color:{color}">
    <div class="highlight-header">
      <span class="highlight-title">💡 今日要点</span>
      <span class="highlight-method">{method_tag}</span>
    </div>
    <ul class="highlight-list">{highlight_items}</ul>
  </div>""" if highlights else ""

        # Scrollable container only kicks in visually past ~4 cards (CSS max-height handles it)
        scroll_class = "cards-container scrollable" if count > 4 else "cards-container"

        sections_html += f"""<section class="category-section" id="cat-{slug(cat)}">
  <div class="category-header" style="border-left-color:{color}">
    <span class="cat-icon">{icon}</span>
    <h2 class="cat-title">{cat}</h2>
    <span class="cat-count" style="background:{color}">{count} 条</span>
  </div>
  {desc_html}
  {highlight_html}
  <div class="{scroll_class}">{cards_html}</div>
</section>
"""

    # Failed sources section
    failed_html = ""
    if failed:
        items = ""
        for fr in failed:
            items += f"<div class='fail-item'><strong>{fr.source_name}</strong> ({fr.category})<br><code>{fr.url}</code><br><span class='error-text'>{fr.error[:200]}</span></div>\n"
        failed_html = f"""<details class="collapsed-section">
  <summary>⚠️ 抓取失败来源（{len(failed)} 个）</summary>
  <div class="collapsed-content">{items}</div>
</details>"""

    # No-time articles
    notime_html = ""
    if no_time:
        items = ""
        for a in no_time[:50]:
            link = f'<a href="{a.url}" target="_blank">{a.url[:60]}</a>' if a.url else "无链接"
            items += f"<div class='filtered-item'><strong>{a.title[:80]}</strong><br>{a.source_name} · {link}</div>\n"
        notime_html = f"""<details class="collapsed-section">
  <summary>🕐 无法确认发布时间（{len(no_time)} 条，不进入主面板）</summary>
  <div class="collapsed-content">{items}</div>
</details>"""

    # Too-old articles
    old_html = ""
    if too_old:
        items = ""
        for a in sorted(too_old, key=lambda x: x.published_dt or datetime.min.replace(tzinfo=UTC), reverse=True)[:50]:
            link = f'<a href="{a.url}" target="_blank">{a.url[:60]}</a>' if a.url else "无链接"
            items += f"<div class='filtered-item'><strong>{a.title[:80]}</strong><br>{a.source_name} · {fmt_dt(a.published_dt)} · {link}</div>\n"
        old_html = f"""<details class="collapsed-section">
  <summary>🗓️ 时效窗口外的旧信息（{len(too_old)} 条，已过滤）</summary>
  <div class="collapsed-content">{items}</div>
</details>"""

    # Reddit diagnosis
    reddit_results = [fr for fr in data.get("fetch_results", []) if fr.category == "reddit讨论"]
    reddit_diag = ""
    if reddit_results:
        diag_items = ""
        for fr in reddit_results:
            status = "✅" if fr.success else "❌"
            diag_items += f"<div><b>{status} {fr.source_name}</b> — 方式：{fr.method or '—'} — 数量：{len(fr.articles)} — {fr.note or fr.error or ''}</div>"
        reddit_diag = f"""<details class="collapsed-section">
  <summary>🔍 Reddit 抓取诊断</summary>
  <div class="collapsed-content">
    <p><b>OAuth配置状态：</b>{'已配置 ✅（优先使用OAuth，更稳定）' if REDDIT_CLIENT_ID else '未配置 — 当前使用 RSS/old.reddit/JSON 等无需密钥的兜底方式（2026年起Reddit已大幅收紧自助API申请，未配置是常态，不代表故障）'}</p>
    {diag_items}
    <p class="note">提升建议：若多个 subreddit 同时失败，优先检查 RSS（.rss）和 old.reddit 兜底是否被限流，而非纠结 OAuth；2026 年起 Reddit 自助创建 API App 门槛大幅提高，详见 REDDIT_提升指南.md</p>
  </div>
</details>"""

    run_time   = stats["run_time_sgt"]
    total_win  = stats["in_window"]
    window_str = f"最近 {stats['lookback_hours']}h（+{stats['grace_hours']}h 时区宽限）"
    history_nav_html = render_history_nav(mode=mode, current_date=current_date)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VPN 行业情报日报</title>
<style>
:root {{
  --bg: #0f172a;
  --surface: #1e293b;
  --surface2: #273549;
  --border: #334155;
  --text: #e2e8f0;
  --text2: #94a3b8;
  --text3: #64748b;
  --accent: #38bdf8;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.6; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.container {{ max-width: 960px; margin: 0 auto; padding: 24px 16px; }}

/* Header */
.panel-header {{
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 20px;
}}
.panel-title {{ font-size: 1.5rem; font-weight: 700; color: #fff; margin-bottom: 4px; }}
.panel-subtitle {{ color: var(--text2); font-size: 0.85rem; margin-bottom: 16px; }}
.meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }}
.meta-item {{ background: var(--surface2); border-radius: 8px; padding: 10px 14px; }}
.meta-label {{ font-size: 0.7rem; color: var(--text3); text-transform: uppercase; letter-spacing: .05em; }}
.meta-value {{ font-size: 0.9rem; font-weight: 600; color: var(--text); margin-top: 2px; }}

/* History date-filter nav */
.history-nav {{
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 10px 14px; margin-bottom: 20px;
}}
.history-label {{ font-size: 0.82rem; color: var(--text2); font-weight: 600; white-space: nowrap; }}
.history-select {{
  background: var(--bg); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 6px 10px; font-size: 0.82rem; flex: 1; min-width: 160px;
  max-width: 320px;
}}
.history-btn {{
  background: var(--accent); color: #0f172a; border: none; border-radius: 6px;
  padding: 6px 14px; font-size: 0.82rem; font-weight: 700; cursor: pointer;
  text-decoration: none; display: inline-flex; align-items: center;
}}
.history-btn:hover {{ opacity: 0.85; }}
.history-btn-secondary {{ background: var(--surface2); color: var(--text2); }}

/* Overview chips */
.overview {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 24px; }}
.overview-chip {{
  display: flex; align-items: center; gap: 8px;
  background: var(--surface); border: 1.5px solid; border-radius: 999px;
  padding: 6px 14px; cursor: pointer; transition: background .15s;
  text-decoration: none; color: inherit;
}}
.overview-chip:hover {{ background: var(--surface2); }}
.chip-icon {{ font-size: 1rem; }}
.chip-label {{ font-size: 0.82rem; color: var(--text2); }}
.chip-count {{ font-size: 0.75rem; font-weight: 700; color: #fff;
              border-radius: 999px; padding: 1px 7px; }}
.chip-delta {{ font-size: 0.7rem; font-weight: 700; border-radius: 4px; padding: 1px 5px; }}
.delta-up {{ background: #14532d; color: #4ade80; }}
.delta-down {{ background: #450a0a; color: #f87171; }}
.delta-flat {{ background: var(--surface2); color: var(--text3); }}

/* Category sections */
.category-section {{ margin-bottom: 32px; scroll-margin-top: 16px; }}
.category-header {{
  display: flex; align-items: center; gap: 10px;
  border-left: 4px solid; padding-left: 12px; margin-bottom: 14px;
}}
.cat-icon {{ font-size: 1.2rem; }}
.cat-title {{ font-size: 1.05rem; font-weight: 700; flex: 1; }}
.cat-count {{ font-size: 0.75rem; font-weight: 700; color: #fff;
             border-radius: 999px; padding: 2px 10px; }}
.cat-desc {{ font-size: 0.78rem; color: var(--text3); line-height: 1.6;
             padding: 6px 0 10px 26px; border-left: 1px solid var(--border);
             margin: 0 0 10px 4px; }}

/* Highlight box — "今日要点" synthesis */
.highlight-box {{
  background: linear-gradient(135deg, var(--surface) 0%, var(--surface2) 100%);
  border: 1px solid var(--border); border-left: 3px solid;
  border-radius: 10px; padding: 12px 16px; margin-bottom: 14px;
}}
.highlight-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
.highlight-title {{ font-size: 0.85rem; font-weight: 700; color: var(--text); }}
.highlight-method {{ font-size: 0.68rem; color: var(--text3); background: var(--bg);
                     border-radius: 4px; padding: 2px 6px; }}
.highlight-list {{ list-style: none; display: flex; flex-direction: column; gap: 6px; }}
.highlight-list li {{
  font-size: 0.83rem; color: var(--text2); line-height: 1.5; padding-left: 14px;
  position: relative;
}}
.highlight-list li::before {{ content: "▸"; position: absolute; left: 0; color: var(--accent); }}

.cards-container {{ display: flex; flex-direction: column; gap: 12px; }}

/* Scrollable card containers — keeps the page from becoming an endless list */
.cards-container.scrollable {{
  max-height: 560px; overflow-y: auto; padding-right: 6px;
  scrollbar-width: thin; scrollbar-color: var(--border) transparent;
  position: relative;
}}
.cards-container.scrollable::-webkit-scrollbar {{ width: 6px; }}
.cards-container.scrollable::-webkit-scrollbar-thumb {{
  background: var(--border); border-radius: 3px;
}}
.cards-container.scrollable::-webkit-scrollbar-track {{ background: transparent; }}
.empty-section {{ color: var(--text3); font-size: 0.85rem;
                  padding: 16px; background: var(--surface); border-radius: 8px; }}

/* Info cards */
.info-card {{
  background: var(--surface); border-radius: 10px;
  border-left: 3px solid; padding: 16px;
  transition: background .15s;
}}
.info-card:hover {{ background: var(--surface2); }}
.card-header {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; margin-bottom: 8px; }}
.card-title {{ font-size: 0.95rem; font-weight: 600; color: var(--text); flex: 1; }}
.card-meta {{ display: flex; gap: 6px; flex-shrink: 0; align-items: center; flex-wrap: wrap; }}
.time-badge {{
  font-size: 0.72rem; background: var(--surface2); color: var(--text2);
  border-radius: 4px; padding: 2px 7px;
}}
.multi-source-badge {{
  font-size: 0.72rem; background: #1e3a5f; color: #7dd3fc;
  border-radius: 4px; padding: 2px 7px;
}}
.signal-badge {{ font-size: 0.72rem; border-radius: 4px; padding: 2px 7px; font-weight: 600; }}
.signal-strong {{ background: #451a03; color: #fb923c; }}
.signal-medium {{ background: #1e3a5f; color: #7dd3fc; }}
.card-summary {{ font-size: 0.83rem; color: var(--text2); margin-bottom: 8px; }}
.card-time {{ font-size: 0.75rem; color: var(--text3); margin-bottom: 8px; }}

/* Sources details */
.sources-details summary {{
  font-size: 0.8rem; color: var(--text3); cursor: pointer;
  padding: 4px 0; list-style: none;
}}
.sources-details summary::-webkit-details-marker {{ display:none; }}
.sources-details[open] summary {{ color: var(--text2); }}
.sources-list {{ margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }}
.source-item {{
  background: var(--bg); border-radius: 6px; padding: 8px 10px;
  font-size: 0.78rem; display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline;
}}
.source-name {{ font-weight: 600; color: var(--accent); }}
.source-type {{ color: var(--text3); background: var(--surface2); border-radius: 3px; padding: 0 5px; }}
.source-title {{ color: var(--text2); flex: 1; min-width: 100px; }}
.source-time {{ color: var(--text3); white-space: nowrap; }}
.source-link {{ word-break: break-all; }}

/* Collapsed sections */
.collapsed-section {{
  background: var(--surface); border-radius: 8px;
  border: 1px solid var(--border); margin-bottom: 10px;
}}
.collapsed-section > summary {{
  padding: 12px 16px; cursor: pointer; font-size: 0.85rem;
  color: var(--text2); list-style: none; user-select: none;
}}
.collapsed-section > summary::-webkit-details-marker {{ display:none; }}
.collapsed-section[open] > summary {{ color: var(--text); border-bottom: 1px solid var(--border); }}
.collapsed-content {{ padding: 12px 16px; }}
.fail-item {{ padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 0.82rem; }}
.fail-item:last-child {{ border-bottom: none; }}
.error-text {{ color: #f87171; font-size: 0.78rem; }}
.filtered-item {{ padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 0.8rem; color: var(--text2); }}
.filtered-item:last-child {{ border-bottom: none; }}
.note {{ font-size: 0.78rem; color: var(--text3); margin-top: 8px; }}

/* Collapsed zone header */
.collapsed-zone {{ margin-top: 32px; }}
.collapsed-zone-title {{ font-size: 0.8rem; color: var(--text3);
  text-transform: uppercase; letter-spacing: .08em; margin-bottom: 8px; }}

@media (max-width: 600px) {{
  .meta-grid {{ grid-template-columns: 1fr 1fr; }}
  .card-header {{ flex-direction: column; }}
}}
</style>
</head>
<body>
<div class="container">

<!-- HEADER -->
<div class="panel-header">
  <div class="panel-title">📡 VPN 行业情报日报</div>
  <div class="panel-subtitle">Daily VPN Industry Intelligence Panel</div>
  <div class="meta-grid">
    <div class="meta-item"><div class="meta-label">更新时间</div><div class="meta-value">{run_time}</div></div>
    <div class="meta-item"><div class="meta-label">时区</div><div class="meta-value">SGT (UTC+8)</div></div>
    <div class="meta-item"><div class="meta-label">时效窗口</div><div class="meta-value">{window_str}</div></div>
    <div class="meta-item"><div class="meta-label">抓取来源</div><div class="meta-value">{stats['total_sources']} 个（成功 {stats['fetch_success']}）</div></div>
    <div class="meta-item"><div class="meta-label">原始抓取</div><div class="meta-value">{stats['total_raw']} 条</div></div>
    <div class="meta-item"><div class="meta-label">进入面板</div><div class="meta-value">{total_win} 条</div></div>
    <div class="meta-item"><div class="meta-label">已过滤</div><div class="meta-value">时效外 {stats['too_old']} + 时间不明 {stats['no_time']}</div></div>
  </div>
</div>

<!-- HISTORY NAV -->
{history_nav_html}

<!-- OVERVIEW -->
<div class="overview">
{overview_html}
</div>

<!-- MAIN SECTIONS -->
{sections_html}

<!-- COLLAPSED ZONE -->
<div class="collapsed-zone">
<div class="collapsed-zone-title">▼ 折叠区（非主要信息）</div>
{failed_html}
{notime_html}
{old_html}
{reddit_diag}
</div>

</div><!-- /container -->
</body>
</html>
"""
    return html

# ─────────────────────────────────────────────
# SAVE OUTPUTS
# ─────────────────────────────────────────────

def build_archive_manifest():
    """Scan docs/archive/*.json (skip manifest.json itself) and build a
    lightweight index the client-side date-filter widget can fetch."""
    items = []
    for jf in DIRS["archive"].glob("*.json"):
        if jf.name == "manifest.json":
            continue
        date_str = jf.stem  # filename like 2026-06-30.json -> 2026-06-30
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            continue
        try:
            payload = json.loads(jf.read_text(encoding="utf-8"))
            total = payload.get("stats", {}).get("in_window", 0)
        except Exception:
            total = 0
        items.append({"date": date_str, "total": total})

    items.sort(key=lambda x: x["date"], reverse=True)
    manifest_path = DIRS["archive"] / "manifest.json"
    manifest_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"Archive manifest written: {manifest_path} ({len(items)} dates)")
    return items

def save_outputs(data):
    for d in DIRS.values():
        d.mkdir(parents=True, exist_ok=True)

    date_str = data["stats"]["run_time_sgt"][:10]

    # docs/index.html — the "live" page, links forward into archive/
    index_html = render_html(data, mode="index", current_date=date_str)
    index_path = DIRS["docs"] / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    log.info(f"HTML written: {index_path}")

    # JSON (latest snapshot)
    stats = data["stats"]
    json_data = {
        "stats": stats,
        "categories": {
            cat: [
                {
                    "title": g["title"],
                    "summary": g["summary"],
                    "source_count": len(g["sources"]),
                    "earliest_dt": g["earliest_dt"].isoformat() if g["earliest_dt"] else None,
                    "latest_dt":   g["latest_dt"].isoformat() if g["latest_dt"] else None,
                    "sources": [s.to_dict() for s in g["sources"]],
                }
                for g in groups
            ]
            for cat, groups in data["cat_groups"].items()
        }
    }
    json_path = DIRS["data"] / "latest.json"
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"JSON written: {json_path}")

    # Archive — a standalone snapshot page for THIS date, with nav adjusted
    # for its location (docs/archive/{date}.html), so it can link back to
    # ../index.html and sideways to other dates via the same manifest.
    archive_html_content = render_html(data, mode="archive", current_date=date_str)
    archive_html = DIRS["archive"] / f"{date_str}.html"
    archive_html.write_text(archive_html_content, encoding="utf-8")
    archive_json = DIRS["archive"] / f"{date_str}.json"
    archive_json.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"Archive written: {archive_html}")

    # Rebuild the manifest so the date-filter dropdown picks up today's entry
    build_archive_manifest()

# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="VPN Dashboard Generator")
    ap.add_argument("--lookback-hours", type=int, default=DEFAULT_LOOKBACK_HOURS)
    ap.add_argument("--skip-network", action="store_true", default=SKIP_NETWORK)
    args = ap.parse_args()

    data = run_pipeline(
        lookback_hours=args.lookback_hours,
        skip_network=args.skip_network,
    )
    save_outputs(data)

    s = data["stats"]
    log.info(f"=== Done. In-window: {s['in_window']} items across {len(CATEGORY_ORDER)} categories ===")

if __name__ == "__main__":
    main()
