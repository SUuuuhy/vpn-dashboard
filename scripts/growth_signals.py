#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增长信号周报 (Growth Signals Weekly Report)

聚合过去 N 天（默认30天）的归档数据，按关键词主题聚类，分三个维度呈现：
  🧩 产品功能缺口 — 竞品被吐槽的痛点（可能是我们的机会）
  📢 内容/营销角度 — 反复被讨论的话题（不限品牌，内容选题参考）
  🔧 自身体验问题 — 我方品牌（own_brand.txt 配置）被吐槽的痛点

设计原则（用户确认过的边界）：
  - 每周跑一次，不需要每天重算
  - 聚类用关键词主题归类（不依赖AI，规则透明可控）
  - 不打分、不给"机会大小"排序建议，只做聚类后的原始清单，
    按出现天数从高到低排序，由人自己判断
  - 证据强度分两档：🔥持续信号（≥3个不同日期出现）/ 💡观察中（少于3天，含今日初现）
  - 历史不足30天也直接跑，用现有的全部归档数据，不等满30天
"""
import sys
import os
import json
import re
from pathlib import Path
from datetime import timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
import update_dashboard as ud  # reuse: contains_keyword, read_own_brand, now_sgt, CATEGORY_ORDER

ARCHIVE_DIR = Path("docs/archive")
DATA_DIR    = Path("docs/data")
OUTPUT_FRAGMENT = Path("docs/data/growth_fragment.html")
OUTPUT_JSON     = Path("docs/data/growth.json")

WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "30"))
PERSISTENT_THRESHOLD = 3  # distinct days within window to count as "持续信号"

# ─────────────────────────────────────────────
# FEATURE/TOPIC TAXONOMY
# Broader than the sentiment-oriented RISK/POSITIVE maps in update_dashboard.py —
# this captures WHAT users are talking about, regardless of polarity, so the
# same taxonomy serves all three buckets (功能缺口/内容角度/自身体验).
# ─────────────────────────────────────────────
FEATURE_TOPIC_MAP = {
    "netflix": "流媒体解锁", "disney": "流媒体解锁", "disney+": "流媒体解锁",
    "hulu": "流媒体解锁", "streaming": "流媒体解锁", "stream": "流媒体解锁",
    "bbc iplayer": "流媒体解锁", "iplayer": "流媒体解锁", "unblock": "流媒体解锁",
    "gaming": "游戏场景优化", "game": "游戏场景优化", "games": "游戏场景优化",
    "latency": "游戏场景优化", "ping": "游戏场景优化",
    "split tunneling": "分应用分流", "split tunnel": "分应用分流",
    "kill switch": "断网保护(Kill Switch)",
    "double vpn": "多重跳转加密", "multi hop": "多重跳转加密", "multihop": "多重跳转加密",
    "static ip": "静态IP",
    "ad block": "广告拦截", "adblock": "广告拦截", "ads": "广告拦截",
    "torrent": "P2P/种子下载支持", "torrenting": "P2P/种子下载支持", "p2p": "P2P/种子下载支持",
    "router": "路由器支持",
    "speed": "连接速度", "slow": "连接速度", "fast": "连接速度", "bandwidth": "连接速度",
    "price": "价格/订阅模式", "expensive": "价格/订阅模式", "pricing": "价格/订阅模式",
    "subscription": "价格/订阅模式", "cheap": "价格/订阅模式", "renewal": "价格/订阅模式",
    "free": "免费版限制", "data cap": "免费版限制", "data limit": "免费版限制",
    "customer service": "客服响应", "support": "客服响应", "live chat": "客服响应",
    "interface": "应用体验/界面", "crash": "应用体验/界面", "ui": "应用体验/界面",
    "ux": "应用体验/界面",
    "server": "服务器覆盖/节点", "location": "服务器覆盖/节点", "country": "服务器覆盖/节点",
    "no-log": "隐私/无日志政策", "no logs": "隐私/无日志政策", "logging": "隐私/无日志政策",
    "obfuscation": "防审查/混淆能力", "censorship": "防审查/混淆能力",
    "firewall": "防审查/混淆能力", "china": "防审查/混淆能力", "great firewall": "防审查/混淆能力",
    "refund": "退款/订阅纠纷", "cancel": "退款/订阅纠纷", "cancellation": "退款/订阅纠纷",
    "mobile": "移动端体验", "ios": "移动端体验", "android": "移动端体验",
    "windows": "桌面端体验", "macos": "桌面端体验", "mac": "桌面端体验",
}


def match_feature_topics(text):
    """Returns ALL matched topics (not just first match) since a single
    post can touch multiple feature themes at once."""
    text_l = text.lower()
    found = set()
    for kw, topic in FEATURE_TOPIC_MAP.items():
        if ud.contains_keyword(text_l, kw):
            found.add(topic)
    return found


def load_archives_within_window(window_days):
    """Scan docs/archive/*.json (skip manifest.json). If fewer than
    window_days of history exist, just use whatever is available — this is
    the agreed bootstrap behavior, no special-casing needed."""
    today = ud.now_sgt().date()
    cutoff = today - timedelta(days=window_days)
    days = []
    for jf in sorted(ARCHIVE_DIR.glob("*.json")):
        if jf.name == "manifest.json":
            continue
        date_str = jf.stem
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            continue
        try:
            from datetime import datetime
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            continue
        try:
            payload = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  Skipping unreadable archive {jf.name}: {e}")
            continue
        days.append((date_str, payload))
    days.sort(key=lambda x: x[0])
    return days


def build_buckets(days, own_brand):
    """bucket -> topic -> {dates:set(), items:[...]}"""
    buckets = {
        "self":        defaultdict(lambda: {"dates": set(), "items": []}),
        "feature_gap": defaultdict(lambda: {"dates": set(), "items": []}),
        "content":     defaultdict(lambda: {"dates": set(), "items": []}),
    }

    for date_str, payload in days:
        categories = payload.get("categories", {})
        for cat, groups in categories.items():
            for g in groups:
                title   = g.get("title", "")
                summary = g.get("summary", "")
                text    = f"{title} {summary}"
                brands  = g.get("brands", [])
                sentiment = (g.get("signal") or {}).get("sentiment", "neutral")
                src_count = g.get("source_count", 1)
                sources   = g.get("sources", [])
                url       = sources[0].get("url", "") if sources else ""
                summary_zh_ai = sources[0].get("summary_zh") if sources else None

                topics = match_feature_topics(text)
                if not topics:
                    continue

                item = {
                    "date": date_str, "title": title, "summary": summary, "category": cat,
                    "brands": brands, "url": url, "source_count": src_count,
                    "summary_zh": summary_zh_ai,
                }

                is_own        = bool(own_brand) and own_brand in brands
                is_competitor = bool(brands) and not is_own

                for topic in topics:
                    # 内容/营销角度：不分品牌不分情绪，话题反复出现就记录
                    buckets["content"][topic]["dates"].add(date_str)
                    buckets["content"][topic]["items"].append(item)

                    if is_own and sentiment == "risk":
                        buckets["self"][topic]["dates"].add(date_str)
                        buckets["self"][topic]["items"].append(item)
                    elif is_competitor and sentiment == "risk":
                        buckets["feature_gap"][topic]["dates"].add(date_str)
                        buckets["feature_gap"][topic]["items"].append(item)

    return buckets


def finalize_bucket(bucket):
    """Convert raw accumulator into a sorted list of result dicts."""
    result = []
    for topic, data in bucket.items():
        dates_sorted = sorted(data["dates"])
        n_dates = len(dates_sorted)
        strength = "persistent" if n_dates >= PERSISTENT_THRESHOLD else "emerging"
        # de-dup items by (date,title) to avoid the same merged-group being
        # listed twice if it matched the same topic via title AND summary
        seen = set()
        dedup_items = []
        for it in data["items"]:
            key = (it["date"], it["title"])
            if key in seen:
                continue
            seen.add(key)
            dedup_items.append(it)
        result.append({
            "topic": topic,
            "dates": dates_sorted,
            "n_dates": n_dates,
            "n_items": len(dedup_items),
            "strength": strength,
            "items": dedup_items[:20],  # cap per-topic detail list
        })
    result.sort(key=lambda x: (x["n_dates"], x["n_items"]), reverse=True)
    return result


# ─────────────────────────────────────────────
# HTML RENDERING — visually consistent with the main dashboard's
# light X-VPN-style theme, but as a simpler standalone page.
# ─────────────────────────────────────────────

BUCKET_META = {
    "feature_gap": {"icon": "🧩", "title": "产品功能缺口", "color": "#2F5DFF",
                     "desc": "竞品用户反复吐槽的痛点（不含我方）。竞品的弱点，"
                             "可能是我们的产品/功能机会——具体要不要做，你自己判断。"},
    "content":     {"icon": "📢", "title": "内容/营销角度", "color": "#7C3AED",
                     "desc": "不限定品牌、不限定情绪，单纯看哪些话题被反复讨论。"
                             "用作内容选题、广告投放关键词的参考池。"},
    "self":        {"icon": "🔧", "title": "自身体验问题", "color": "#DC2626",
                     "desc": "我方品牌被反复吐槽的痛点（基于 config/own_brand.txt 配置的品牌）。"
                             "这些是真实存在的产品体验缺口。"},
}


def render_topic_card(entry, color):
    badge = (f'<span class="strength-badge strength-persistent">🔥 持续信号 · {entry["n_dates"]}天</span>'
             if entry["strength"] == "persistent" else
             f'<span class="strength-badge strength-emerging">💡 观察中 · {entry["n_dates"]}天</span>')

    items_html = ""
    for it in entry["items"]:
        brand_str = "、".join(it["brands"]) if it["brands"] else "—"
        link = (f'<a href="{it["url"]}" target="_blank" rel="noopener">{it["url"][:55]}'
                f'{"…" if len(it["url"]) > 55 else ""}</a>') if it["url"] else "无链接"
        if it.get("summary_zh"):
            gist_zh = it["summary_zh"]
            gist_badge = '<span class="gist-method-badge" title="AI生成的中文摘要">🤖</span>'
        else:
            gist_zh = ud.describe_text_zh(it["title"], it.get("summary", ""), it["brands"])
            gist_badge = ""
        items_html += f"""<div class="eg-item">
  <div class="eg-item-main">
    <span class="eg-date">{it['date']}</span>
    <span class="eg-brand">{brand_str}</span>
    <span class="eg-cat">{it['category']}</span>
    <span class="eg-gist">{gist_zh}{gist_badge}</span>
  </div>
  <div class="eg-item-detail">
    <span class="eg-title-original">原标题：{it['title'][:80]}</span>
    <span class="eg-link">{link}</span>
  </div>
</div>"""

    return f"""<div class="topic-card" style="border-left-color:{color}">
  <div class="topic-header">
    <h3 class="topic-name">{entry['topic']}</h3>
    {badge}
  </div>
  <div class="topic-meta">共 {entry['n_items']} 条相关信息，分布在 {entry['n_dates']} 个不同日期</div>
  <details class="topic-details">
    <summary>📋 查看原始记录（{len(entry['items'])} 条）</summary>
    <div class="eg-list">{items_html}</div>
  </details>
</div>"""


def render_bucket_section(bucket_key, entries):
    meta = BUCKET_META[bucket_key]
    if entries:
        cards_html = "\n".join(render_topic_card(e, meta["color"]) for e in entries)
    else:
        cards_html = '<div class="empty-bucket">本窗口内暂无匹配该维度的信号</div>'

    return f"""<section class="bucket-section">
  <div class="bucket-header" style="border-left-color:{meta['color']}">
    <span class="bucket-icon">{meta['icon']}</span>
    <h2 class="bucket-title">{meta['title']}</h2>
    <span class="bucket-count" style="background:{meta['color']}">{len(entries)} 个主题</span>
  </div>
  <p class="bucket-desc">{meta['desc']}</p>
  <div class="topics-grid">{cards_html}</div>
</section>"""


def render_growth_fragment(buckets_final, own_brand, days, latest_date):
    """
    Renders ONLY the inner content for the growth tab — no <html>/<head>/
    <style> wrapper. This gets embedded into the shared docs/index.html
    (which already carries all the necessary CSS classes), so the growth
    report lives as a tab inside the single combined page rather than a
    separate HTML document.
    """
    window_desc = (
        f"过去 {len(days)} 天（{days[0][0]} 至 {days[-1][0]}）"
        if days else "暂无归档数据"
    )
    own_brand_note = (
        f"我方品牌：{own_brand}" if own_brand
        else "未配置我方品牌（config/own_brand.txt）— 「自身体验问题」板块将持续为空"
    )

    sections_html = "".join(
        render_bucket_section(key, buckets_final.get(key, []))
        for key in ["self", "feature_gap", "content"]
    )

    return f"""<div class="method-note">
📈 <strong>增长信号周报</strong> — 跨{WINDOW_DAYS}天聚合，关键词主题聚类，每周一自动更新一次。<br>
分析窗口：{window_desc} ｜ {own_brand_note}<br>
💡 <strong>这是什么：</strong>把过去最多{WINDOW_DAYS}天的归档数据按关键词主题做聚类，
找出"反复出现"的话题/抱怨/需求。<strong>不做机会打分，不给运营建议</strong>——只是把聚类后的原始信号
按出现天数排序列出来，你自己判断要不要跟进。🔥持续信号 = 在{PERSISTENT_THRESHOLD}个或以上不同日期出现过；
💡观察中 = 出现次数还不够多，可能是噪音也可能是刚冒头的新趋势，仅供参考。
</div>

{sections_html}"""


def splice_into_index_html(fragment_html):
    """
    Inject the freshly rendered growth fragment into the already-generated
    docs/index.html (produced moments earlier in the same workflow run by
    update_dashboard.py), by replacing the content between the
    GROWTH_TAB_CONTENT marker comments. This makes the merged single-page
    site reflect the new growth report immediately, rather than waiting
    for tomorrow's daily run to pick up docs/data/growth_fragment.html.

    If docs/index.html doesn't exist yet (shouldn't normally happen — the
    weekly workflow runs update_dashboard.py first), this is a no-op;
    the fragment file alone will still be picked up on the next daily run.
    """
    index_path = Path("docs/index.html")
    if not index_path.exists():
        print("docs/index.html not found — skipping splice; "
              "next daily run will pick up the saved fragment instead.")
        return False

    html = index_path.read_text(encoding="utf-8")
    start_marker = "<!-- GROWTH_TAB_CONTENT_START -->"
    end_marker   = "<!-- GROWTH_TAB_CONTENT_END -->"

    start_idx = html.find(start_marker)
    end_idx   = html.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        print("Growth tab markers not found in docs/index.html — skipping splice "
              "(this index.html may have been generated by an older version of "
              "update_dashboard.py without tab support).")
        return False

    new_html = (
        html[: start_idx + len(start_marker)]
        + "\n" + fragment_html + "\n"
        + html[end_idx:]
    )
    index_path.write_text(new_html, encoding="utf-8")
    print("Spliced fresh growth content into docs/index.html ✅")
    return True


def main():
    own_brand = ud.read_own_brand()
    days = load_archives_within_window(WINDOW_DAYS)
    print(f"Loaded {len(days)} archived day(s) within {WINDOW_DAYS}-day window "
          f"(own_brand={own_brand or '未配置'})")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not days:
        print("No archive data available yet — writing placeholder growth fragment.")
        buckets_final = {"self": [], "feature_gap": [], "content": []}
        fragment = render_growth_fragment(buckets_final, own_brand, [], None)
    else:
        latest_date = days[-1][0]
        buckets_raw = build_buckets(days, own_brand)
        buckets_final = {key: finalize_bucket(buckets_raw[key]) for key in buckets_raw}
        for key, entries in buckets_final.items():
            print(f"  [{key}] {len(entries)} topic(s) found")
        fragment = render_growth_fragment(buckets_final, own_brand, days, latest_date)

    OUTPUT_FRAGMENT.write_text(fragment, encoding="utf-8")
    print(f"Fragment written: {OUTPUT_FRAGMENT}")

    OUTPUT_JSON.write_text(json.dumps({
        "generated_at": ud.now_sgt().isoformat(),
        "window_days": WINDOW_DAYS,
        "own_brand": own_brand,
        "days_analyzed": len(days),
        "date_range": [days[0][0], days[-1][0]] if days else None,
        "buckets": buckets_final,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON written: {OUTPUT_JSON}")

    # Immediately merge into the single combined page, rather than waiting
    # for tomorrow's daily run to pick up the saved fragment.
    splice_into_index_html(fragment)


if __name__ == "__main__":
    main()
