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
    """Reduce title to key tokens for deduplication."""
    title = re.sub(r'[^\w\s]', '', title.lower())
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

    methods = [
        ("OAuth",     lambda: fetch_reddit_oauth(subreddit, source_name, category)),
        ("PublicJSON", lambda: fetch_reddit_json(subreddit, source_name, category)),
        ("RSS",        lambda: fetch_reddit_rss(subreddit, source_name, category)),
        ("old.reddit", lambda: fetch_old_reddit(subreddit, source_name, category)),
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
        diagnosis.append("未配置 REDDIT_CLIENT_ID/SECRET（OAuth不可用）")
    diagnosis.append("可能被限流或GitHub Actions IP被封")
    diagnosis.append("User-Agent可能不合规")
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
# MAIN PIPELINE
# ─────────────────────────────────────────────

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
        # Sort by latest_dt desc
        groups.sort(key=lambda g: g["latest_dt"] or datetime.min.replace(tzinfo=UTC), reverse=True)
        cat_groups[cat] = groups

    # Failed sources
    failed_sources = [fr for fr in fetch_results if not fr.success]
    success_sources = [fr for fr in fetch_results if fr.success]

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
        "category_counts": {cat: len(cat_groups[cat]) for cat in CATEGORY_ORDER},
    }

    return {
        "stats": stats,
        "cat_groups": cat_groups,
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

    return f"""<div class="info-card" style="border-left-color:{color}">
  <div class="card-header">
    <h3 class="card-title">{group['title']}</h3>
    <div class="card-meta">
      <span class="time-badge">{age}</span>
      {'<span class="multi-source-badge">📎 ' + str(src_count) + ' 个来源</span>' if src_count > 1 else ''}
    </div>
  </div>
  {f'<p class="card-summary">{group["summary"]}</p>' if group["summary"] else ''}
  <div class="card-time">🕐 {time_range}</div>
  <details class="sources-details">
    <summary>📋 查看来源（{src_count} 条）</summary>
    <div class="sources-list">{sources_html}</div>
  </details>
</div>"""

def render_html(data):
    stats     = data["stats"]
    cat_groups = data["cat_groups"]
    failed    = data["failed_sources"]
    no_time   = data["no_time_articles"]
    too_old   = data["too_old_articles"]

    # Category overview chips
    overview_html = ""
    for cat in CATEGORY_ORDER:
        count = stats["category_counts"].get(cat, 0)
        color = CATEGORY_COLORS.get(cat, "#374151")
        icon  = CATEGORY_ICONS.get(cat, "•")
        overview_html += f'<div class="overview-chip" style="border-color:{color}"><span class="chip-icon">{icon}</span><span class="chip-label">{cat}</span><span class="chip-count" style="background:{color}">{count}</span></div>\n'

    # Main sections
    sections_html = ""
    for cat in CATEGORY_ORDER:
        groups = cat_groups.get(cat, [])
        color  = CATEGORY_COLORS.get(cat, "#374151")
        icon   = CATEGORY_ICONS.get(cat, "•")
        count  = len(groups)

        if groups:
            cards_html = "\n".join(render_group_card(g, cat) for g in groups)
        else:
            cards_html = '<div class="empty-section">暂无本时效窗口内的有效信息</div>'

        sections_html += f"""<section class="category-section" id="cat-{slug(cat)}">
  <div class="category-header" style="border-left-color:{color}">
    <span class="cat-icon">{icon}</span>
    <h2 class="cat-title">{cat}</h2>
    <span class="cat-count" style="background:{color}">{count} 条</span>
  </div>
  <div class="cards-container">{cards_html}</div>
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
    <p><b>OAuth配置状态：</b>{'已配置 ✅' if REDDIT_CLIENT_ID else '未配置（将使用兜底方式）'}</p>
    {diag_items}
    <p class="note">提升 Reddit 抓取成功率：在 GitHub → Settings → Secrets 中配置 REDDIT_CLIENT_ID、REDDIT_CLIENT_SECRET、REDDIT_USER_AGENT</p>
  </div>
</details>"""

    run_time   = stats["run_time_sgt"]
    total_win  = stats["in_window"]
    window_str = f"最近 {stats['lookback_hours']}h（+{stats['grace_hours']}h 时区宽限）"

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

/* Overview chips */
.overview {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 24px; }}
.overview-chip {{
  display: flex; align-items: center; gap: 8px;
  background: var(--surface); border: 1.5px solid; border-radius: 999px;
  padding: 6px 14px; cursor: pointer; transition: background .15s;
}}
.overview-chip:hover {{ background: var(--surface2); }}
.chip-icon {{ font-size: 1rem; }}
.chip-label {{ font-size: 0.82rem; color: var(--text2); }}
.chip-count {{ font-size: 0.75rem; font-weight: 700; color: #fff;
              border-radius: 999px; padding: 1px 7px; }}

/* Category sections */
.category-section {{ margin-bottom: 32px; }}
.category-header {{
  display: flex; align-items: center; gap: 10px;
  border-left: 4px solid; padding-left: 12px; margin-bottom: 14px;
}}
.cat-icon {{ font-size: 1.2rem; }}
.cat-title {{ font-size: 1.05rem; font-weight: 700; flex: 1; }}
.cat-count {{ font-size: 0.75rem; font-weight: 700; color: #fff;
             border-radius: 999px; padding: 2px 10px; }}
.cards-container {{ display: flex; flex-direction: column; gap: 12px; }}
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

def save_outputs(data):
    for d in DIRS.values():
        d.mkdir(parents=True, exist_ok=True)

    # HTML
    html = render_html(data)
    html_path = DIRS["docs"] / "index.html"
    html_path.write_text(html, encoding="utf-8")
    log.info(f"HTML written: {html_path}")

    # JSON
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

    # Archive
    date_str = data["stats"]["run_time_sgt"][:10]
    archive_html = DIRS["archive"] / f"{date_str}.html"
    archive_html.write_text(html, encoding="utf-8")
    archive_json = DIRS["archive"] / f"{date_str}.json"
    archive_json.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"Archive written: {archive_html}")

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
