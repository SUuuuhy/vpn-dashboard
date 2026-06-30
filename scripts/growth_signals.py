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
OUTPUT_HTML = Path("docs/growth.html")
OUTPUT_JSON = Path("docs/data/growth.json")

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

                topics = match_feature_topics(text)
                if not topics:
                    continue

                item = {
                    "date": date_str, "title": title, "category": cat,
                    "brands": brands, "url": url, "source_count": src_count,
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
        items_html += f"""<div class="eg-item">
  <span class="eg-date">{it['date']}</span>
  <span class="eg-brand">{brand_str}</span>
  <span class="eg-cat">{it['category']}</span>
  <span class="eg-title">{it['title'][:70]}</span>
  <span class="eg-link">{link}</span>
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


def render_html(buckets_final, own_brand, days, latest_date):
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

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>增长信号周报</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {{
  --bg: #F5F7FC; --surface: #FFFFFF; --surface2: #EEF1F9; --border: #E3E7F2;
  --text: #0B1220; --text2: #4B5568; --text3: #94A0B8;
  --accent: #2F5DFF; --accent2: #7C3AED;
  --shadow-sm: 0 1px 2px rgba(15,23,42,0.05); --shadow-md: 0 4px 16px rgba(15,23,42,0.07);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Manrope', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.6; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 24px 16px; }}

.page-header {{
  background: linear-gradient(135deg, #2F5DFF 0%, #7C3AED 100%);
  border-radius: 20px; padding: 26px; margin-bottom: 22px; box-shadow: var(--shadow-md);
}}
.page-title {{ font-size: 1.5rem; font-weight: 800; color: #fff; margin-bottom: 6px; }}
.page-subtitle {{ color: rgba(255,255,255,0.85); font-size: 0.85rem; margin-bottom: 4px; }}
.page-meta {{ color: rgba(255,255,255,0.7); font-size: 0.78rem; }}
.back-link {{
  display: inline-block; margin-top: 14px; background: rgba(255,255,255,0.18);
  color: #fff; border: 1px solid rgba(255,255,255,0.35); border-radius: 999px;
  padding: 6px 16px; font-size: 0.8rem; font-weight: 600;
}}
.back-link:hover {{ background: rgba(255,255,255,0.28); text-decoration: none; }}

.method-note {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  padding: 14px 18px; margin-bottom: 22px; font-size: 0.8rem; color: var(--text3);
  line-height: 1.7; box-shadow: var(--shadow-sm);
}}

.bucket-section {{ margin-bottom: 32px; }}
.bucket-header {{
  display: flex; align-items: center; gap: 10px;
  border-left: 4px solid; padding-left: 12px; margin-bottom: 8px;
}}
.bucket-icon {{ font-size: 1.3rem; }}
.bucket-title {{ font-size: 1.15rem; font-weight: 800; flex: 1; color: var(--text); }}
.bucket-count {{ font-size: 0.75rem; font-weight: 700; color: #fff;
                 border-radius: 999px; padding: 2px 12px; }}
.bucket-desc {{ font-size: 0.8rem; color: var(--text3); margin: 0 0 16px 4px; line-height: 1.6; }}

.topics-grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 16px; align-items: start;
}}
.empty-bucket {{ color: var(--text3); font-size: 0.85rem; padding: 20px;
                 background: var(--surface); border: 1px solid var(--border);
                 border-radius: 14px; grid-column: 1 / -1; }}

.topic-card {{
  background: var(--surface); border: 1px solid var(--border); border-left: 3px solid;
  border-radius: 14px; padding: 16px 18px; box-shadow: var(--shadow-sm);
}}
.topic-header {{ display: flex; justify-content: space-between; align-items: flex-start;
                 gap: 8px; margin-bottom: 8px; }}
.topic-name {{ font-size: 1rem; font-weight: 700; color: var(--text); }}
.strength-badge {{ font-size: 0.68rem; font-weight: 700; border-radius: 6px;
                   padding: 3px 9px; white-space: nowrap; }}
.strength-persistent {{ background: #FEF2F2; color: #DC2626; }}
.strength-emerging {{ background: #FFFBEB; color: #D97706; }}
.topic-meta {{ font-size: 0.78rem; color: var(--text3); margin-bottom: 10px; }}

.topic-details summary {{ font-size: 0.8rem; color: var(--text3); cursor: pointer;
                          list-style: none; padding: 4px 0; }}
.topic-details summary::-webkit-details-marker {{ display:none; }}
.topic-details[open] summary {{ color: var(--text2); }}
.eg-list {{ margin-top: 8px; display: flex; flex-direction: column; gap: 6px;
            max-height: 320px; overflow-y: auto; padding-right: 4px; }}
.eg-item {{ background: var(--bg); border-radius: 8px; padding: 8px 10px;
            font-size: 0.76rem; display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline; }}
.eg-date {{ color: var(--text3); white-space: nowrap; font-weight: 600; }}
.eg-brand {{ color: var(--accent); font-weight: 600; }}
.eg-cat {{ color: var(--text3); background: var(--surface2); border-radius: 4px; padding: 0 6px; }}
.eg-title {{ color: var(--text2); flex: 1; min-width: 100px; }}
.eg-link {{ word-break: break-all; }}

@media (max-width: 600px) {{
  .topics-grid {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<div class="container">

<div class="page-header">
  <div class="page-title">📈 增长信号周报</div>
  <div class="page-subtitle">Growth Signals — 跨{WINDOW_DAYS}天聚合，关键词主题聚类</div>
  <div class="page-meta">分析窗口：{window_desc} ｜ {own_brand_note}</div>
  <a href="index.html" class="back-link">↩ 返回每日面板</a>
</div>

<div class="method-note">
💡 <strong>这是什么：</strong>每周运行一次，把过去最多{WINDOW_DAYS}天的归档数据按关键词主题做聚类，
找出"反复出现"的话题/抱怨/需求。<strong>不做机会打分，不给运营建议</strong>——只是把聚类后的原始信号
按出现天数排序列出来，你自己判断要不要跟进。🔥持续信号 = 在{PERSISTENT_THRESHOLD}个或以上不同日期出现过；
💡观察中 = 出现次数还不够多，可能是噪音也可能是刚冒头的新趋势，仅供参考。
</div>

{sections_html}

</div>
</body>
</html>
"""


def main():
    own_brand = ud.read_own_brand()
    days = load_archives_within_window(WINDOW_DAYS)
    print(f"Loaded {len(days)} archived day(s) within {WINDOW_DAYS}-day window "
          f"(own_brand={own_brand or '未配置'})")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not days:
        print("No archive data available yet — writing placeholder growth report.")
        buckets_final = {"self": [], "feature_gap": [], "content": []}
        html = render_html(buckets_final, own_brand, [], None)
        OUTPUT_HTML.write_text(html, encoding="utf-8")
        OUTPUT_JSON.write_text(json.dumps({
            "generated_at": ud.now_sgt().isoformat(),
            "window_days": WINDOW_DAYS,
            "own_brand": own_brand,
            "days_analyzed": 0,
            "buckets": buckets_final,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    latest_date = days[-1][0]
    buckets_raw = build_buckets(days, own_brand)
    buckets_final = {key: finalize_bucket(buckets_raw[key]) for key in buckets_raw}

    for key, entries in buckets_final.items():
        print(f"  [{key}] {len(entries)} topic(s) found")

    html = render_html(buckets_final, own_brand, days, latest_date)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"HTML written: {OUTPUT_HTML}")

    OUTPUT_JSON.write_text(json.dumps({
        "generated_at": ud.now_sgt().isoformat(),
        "window_days": WINDOW_DAYS,
        "own_brand": own_brand,
        "days_analyzed": len(days),
        "date_range": [days[0][0], days[-1][0]],
        "buckets": buckets_final,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON written: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
