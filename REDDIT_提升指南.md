# Reddit 抓取率提升 — 手把手操作指南（2026年更新版）

---

## ⚠️ 重要更新：Reddit 开发者政策已收紧

你遇到的「开发者平台提示需要看规则」是正常现象，**不是你操作错误**。

2025 年底起，Reddit 推出了「Responsible Builder Policy（负责任建设者政策）」，
大幅收紧了自助式 API App 创建：

- 旧的 `reddit.com/prefs/apps` 一键创建 script App 的流程已被「半冻结」
- 很多开发者反馈：填完表单、过了验证码，点击「Create App」后**没有反应**，
  或者卡在条款页面无法继续
- 真正的 API 数据访问，现在需要走 Reddit 的人工审批表单，
  **个人/小型项目的通过率很低**，主要倾向批准与 Reddit 商业目标一致的工具（如版主工具）

**结论：你不需要、也不一定能成功获得 Reddit OAuth API。**
本指南已据此更新——**不依赖 OAuth 也能让 Reddit 板块正常出数据**。

---

## 现在的策略：以 RSS / old.reddit 为主，OAuth 为可选加分项

脚本已重新调整抓取顺序：

**如果你没有配置 OAuth（大多数人的情况）：**
```
RSS（.rss后缀） → old.reddit HTML → Public JSON → Jina兜底
```

**如果你恰好申请成功了 OAuth（少数幸运情况）：**
```
OAuth → RSS → old.reddit → Public JSON → Jina兜底
```

也就是说：**不配置 OAuth 是正常状态，面板照常工作**。
折叠区「Reddit 抓取诊断」中如果显示「未配置」，这不是报错，只是说明用的是免密钥方式。

---

## 第一步（最推荐）：什么都不用做，直接测试效果

1. 进入仓库 → Actions → Daily VPN Dashboard Update
2. 点「Run workflow」→ 参数保持默认 → 运行
3. 等待 3~5 分钟，打开 GitHub Pages 地址
4. 查看「reddit讨论」板块是否有内容
5. 滚动到底部「🔍 Reddit 抓取诊断」，查看每个 subreddit 实际成功方式

**多数情况下，RSS 或 old.reddit 方式就能稳定取到数据，无需任何额外配置。**

---

## 第二步：如果 RSS/old.reddit 也抓不到，按以下顺序排查

### 排查 A：检查 GitHub Actions 的网络环境

GitHub Actions 使用的是云端服务器 IP（非你本机 IP），Reddit 对数据中心 IP 段
有时会有临时性限流。判断方法：

1. 看 Actions 日志中具体的报错（429 = 限流，403 = 拒绝）
2. 如果是 429，等几小时后重新 Run workflow 通常会恢复
3. 如果持续 403，可能是该 IP 段被长期标记，参考下方「第三步」

---

### 排查 B：检查 User-Agent 格式

打开 `scripts/update_dashboard.py`，默认 User-Agent 已经设置为浏览器 UA，
对 RSS/HTML 抓取通常足够。如果你已经在 GitHub Secrets 设置过
`REDDIT_USER_AGENT`，确认格式类似：

```
vpn-dashboard/1.0 by /u/你的用户名
```

不要留空、不要用纯 `python-requests` 之类的默认值。

---

### 排查 C：某个 subreddit 改名/限制了访问

有些 subreddit 设为仅登录可见、或仅限成员访问，这种情况下任何匿名方式
（包括 RSS）都无法抓取。这不是脚本问题，进折叠区「Reddit 抓取诊断」
看是否标注了该 subreddit 单独失败而其他 subreddit 正常即可确认。

---

## 第三步（仍想尝试 OAuth，可选）：如何应对「需要看规则」的卡点

如果你仍想试一试 OAuth（小概率成功，但不影响主流程），以下是 2026 年的
实际操作要点：

1. 打开 https://www.reddit.com/prefs/apps
2. 滚动到底部，点「create another app...」
3. **如果页面卡在条款/规则提示页**：
   - 仔细找页面上是否有「I accept the Developer Terms」或类似复选框
   - 部分用户反馈复选框默认隐藏或需要滚动到底部才出现
   - 如果勾选后点击「Create app」仍无响应（按钮像没反应一样），
     这通常意味着 Reddit 已经在后台静默禁用了你账号的自助创建权限，
     **这是 Reddit 端的限制，不是你操作有误**
4. 如果你有**几个月/几年前**就创建过的旧 App（client_id/secret），
   **那些旧凭据大概率仍然有效**（Reddit 对存量 App 采取了「祖父条款」豁免），
   可以直接拿来用，填入 GitHub Secrets
5. 如果你确实需要正式 API 权限（比如要做更大规模的商业项目），
   需要走 Reddit 官方的开发者申请表单，并等待人工审核，
   通过率取决于你的用例是否对 Reddit 自身有利（如版主工具），
   纯舆情监控类项目通过率较低，**不建议把它作为本项目的必要依赖**

---

## 第四步：手工补充（始终有效的兜底方案）

无论 OAuth 是否申请成功，对于抓不到的内容，可以用
`config/manual_inputs.csv` 手工补充：

```csv
source_name,url,category,title,summary,published_time,notes
r/VPN手工,https://reddit.com/r/VPN/comments/xxx,reddit讨论,用户反映NordVPN英国节点断线,多名UK用户反映北伦敦节点不稳定,2026-06-29T14:00:00+08:00,手工记录
```

`published_time` 填当前时间，格式：`2026-06-29T14:00:00+08:00`

适用场景：Discord 群聊内容、TikTok 评论、App Store 截图、
或某条特别重要但自动化没抓到的 Reddit 帖子。

---

## 诊断速查表

打开面板底部「🔍 Reddit 抓取诊断」，对照下表：

| 显示内容 | 含义 | 需要操作吗 |
|---------|------|-----------|
| `成功方式: RSS` | 正常，RSS 兜底成功 | 不需要 |
| `成功方式: old.reddit` | 正常，HTML兜底成功 | 不需要 |
| `成功方式: OAuth` | 最优状态（少见） | 不需要 |
| `成功方式: PublicJSON` | 正常 | 不需要 |
| `未配置（...属正常情况）` | 没配OAuth，但不影响其他方式 | 不需要 |
| `所有方式均失败` | 该来源临时不可用 | 等待自动重试，或手工补充 |

---

## 一句话总结

**2026 年的现实是：Reddit 个人开发者很难再像过去一样轻松拿到 OAuth API Key。
好消息是——本项目已经把 RSS / old.reddit 等免密钥方式设为主路径，
大多数情况下你什么都不用做，面板照常出数据。OAuth 只是锦上添花，不是必需品。**

---

# 社交媒体板块抓不到信息？— Nitter（Twitter抓取代理）结构性失效说明

如果你发现「社交媒体」板块始终是空的，**这不是脚本的 bug**，是外部依赖本身坏了。

## 问题根源

「社交媒体」板块目前依赖 `nitter.net`——一个第三方搭建的 Twitter/X 抓取代理，
原理是绕过 X 官方 API 直接抓取公开页面。但：

1. **2023-2024年起**：X 官方封锁了 Nitter 用来匿名抓取的"访客账号"机制，
   导致几乎所有公开 Nitter 实例不稳定甚至直接关闭
2. **2026年现状更严峻**：即便部分 Nitter 实例显示"在线"，**RSS 功能本身在大多数
   存活实例上也已被关闭**——也就是说，换一个 Nitter 地址也救不了，因为问题不是
   "这个网站挂了"，而是"这个功能这条路本身被堵死了"

本项目已经在脚本里加了**多实例轮询兜底**（`NITTER_INSTANCES` 列表，依次尝试
nitter.net、xcancel.com、nitter.poast.org 等6个实例），但根据目前的外部环境，
**这个板块大概率仍然会持续抓不到内容，这是合理预期，不代表配置出错**。

## 推荐替代方案：用 YouTube 官方 RSS 监控品牌动态

YouTube 提供官方、免费、无需 API Key 的 RSS 订阅功能，**100% 稳定可靠**，
不依赖任何第三方代理，是 Twitter 监控失效后最现实的替代品。

### 如何获取一个 YouTube 频道的 RSS 链接（无需写代码）

1. 打开该品牌的 YouTube 频道主页（例如 NordVPN 官方频道）
2. 在浏览器地址栏，网页源代码中找频道 ID：
   - 右键页面 → 「查看页面源代码」（或按 Ctrl+U）
   - 按 Ctrl+F 搜索 `channelId`
   - 会看到类似 `"channelId":"UCxxxxxxxxxxxxxxxxxxxxxx"` 的内容，
     复制这串 `UC` 开头的字符（这就是频道ID）
3. 拼出 RSS 地址，格式固定为：
   ```
   https://www.youtube.com/feeds/videos.xml?channel_id=UCxxxxxxxxxxxxxxxxxxxxxx
   ```
4. 打开 `config/sources.csv`，把这个地址填到对应品牌的 YouTube 行里
   （已经预留了 NordVPN/ExpressVPN/Surfshark 三行模板，把
   `填入频道ID` 替换成你找到的真实 ID）
5. 把那一行的 `enabled` 从 `false` 改成 `true`
6. Commit + Push，下次运行时这个来源就会生效

### 为什么 YouTube 比 Twitter 监控更可靠

- 官方原生支持，不需要任何第三方代理或抓取技巧
- 不需要 API Key、不需要登录、不会被限流
- 唯一的代价是：只能看到视频发布动态，看不到纯文字推文
  （但官方 VPN 品牌的重大公告通常也会同步发视频，覆盖率不算差）

## 如果你仍然想保留 Twitter/X 监控

- 可以手动用 `config/manual_inputs.csv` 补充重要推文（复制标题/链接/时间）
- 如果业务需要更系统化的 Twitter 监控，唯一稳定方案是申请 X 官方 Developer API
  （需付费，最低档约 $100/月起，超出本项目"零成本/低成本"的设计目标，
  不建议作为首选）
