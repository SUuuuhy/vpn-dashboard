# VPN 行业情报日报 — 无代码部署说明

## 这是什么？

这是一个每日自动更新的「VPN 行业情报面板」，部署在 GitHub Pages 上。
每天早上 8:00（新加坡时间）自动运行，抓取竞品官网、Reddit、政策网站、第三方媒体等来源，
生成一个网页日报，按照 5 个分类展示最近 48 小时内的有效信息。

**你不需要写任何代码。**

---

## 部署前准备

你需要的东西：

1. 一个 GitHub 账号（免费）：https://github.com
2. GitHub Desktop（免费桌面客户端）：https://desktop.github.com
3. 这个项目的 ZIP 文件（已下载）

---

## 第一步：创建 GitHub 仓库

1. 打开 https://github.com，登录你的账号
2. 点击右上角「+」→「New repository」
3. 填写：
   - Repository name：`vpn-dashboard`（可以改成其他名字）
   - 选择 **Public**（GitHub Pages 免费版需要 Public）
   - 不要勾选 "Add a README file"
4. 点「Create repository」

---

## 第二步：把项目文件上传到仓库

### 方法 A：用 GitHub Desktop（推荐）

1. 打开 GitHub Desktop
2. 点「File」→「Clone Repository」→ 选你刚创建的 `vpn-dashboard`
3. 选一个本地保存位置（例如桌面），点「Clone」
4. 解压下载到的 ZIP 文件
5. **将 ZIP 里的以下文件夹和文件，直接复制到你的本地仓库根目录**：

```
vpn-dashboard/（你的本地仓库根目录）
├── .github/
│   └── workflows/
│       └── daily-update.yml
├── scripts/
│   └── update_dashboard.py
├── config/
│   ├── sources.csv
│   └── manual_inputs.csv
├── docs/
│   ├── index.html
│   ├── data/
│   │   └── latest.json
│   └── archive/（空文件夹）
├── requirements.txt
├── README_无代码部署.md
└── CHECKLIST_只照做.md
```

⚠️ **注意：不要把整个解压后的文件夹拖进去，要把文件夹里的内容复制进去。**

错误结构（不对）：
```
vpn-dashboard/vpn_dashboard/.github/...
```
正确结构：
```
vpn-dashboard/.github/...
```

6. 回到 GitHub Desktop，你会看到左侧「Changes」列表显示了很多新文件
7. 在底部填写 Summary（例如：`初始部署`）
8. 点「Commit to main」
9. 点右上角「Push origin」

---

### 方法 B：直接在 GitHub 网页上传

1. 进入你的仓库页面
2. 点「Add file」→「Upload files」
3. 把 ZIP 里的文件一批一批拖进去（注意保持文件夹层级）
4. 每批上传后点「Commit changes」

---

## 第三步：开启 GitHub Pages

1. 进入仓库页面
2. 点顶部「Settings」
3. 左侧菜单找「Pages」
4. 在「Build and deployment」下面：
   - Source：选「**GitHub Actions**」
5. 会显示「GitHub Actions」已选中
6. 保存（通常不需要额外点保存，切换即生效）

---

## 第四步：手动运行第一次

1. 进入仓库页面，点顶部「Actions」
2. 左侧找「Daily VPN Dashboard Update」
3. 点右侧「Run workflow」下拉按钮
4. 参数设置：
   - skip_network：`false`（正常抓取）
   - lookback_hours：`48`（抓取过去48小时）
5. 点绿色「Run workflow」按钮
6. 等 2~5 分钟，看到绿色 ✅ 表示成功

---

## 第五步：查看你的日报

运行成功后，访问你的 GitHub Pages 地址：

```
https://你的用户名.github.io/vpn-dashboard/
```

例如：`https://john.github.io/vpn-dashboard/`

---

## 自动更新

设置好后，每天 08:00（新加坡时间）会自动运行，无需任何操作。

---

## 竞品监控矩阵 + 今日简报 + 风险标签（数据运营核心功能）

这是面板最重要的三个模块，专门解决"看不出竞品动态、看不出风险信号、
不方便给团队看"这三个问题：

### 📋 今日简报
面板最顶部，3-5句话讲清楚今天整体风险等级和最值得关注的事情，
右上角有「复制」按钮，点一下直接复制纯文本，可以直接粘贴发到团队群里，
不用让同事自己点进每个分类去读。

### 🎯 竞品监控矩阵
横跨全部5个分类，按竞品品牌（NordVPN、ExpressVPN、Surfshark等）汇总：
今天被提及几次、有几条负面信号、有几条正面信号、对我方意味着什么、
最具代表性的一条事件是什么。**我方品牌永远排在表格第一行**（带⭐我方标识），
其余竞品按"负面信号数"排序——因为竞品的负面信号数越多，对我方的潜在机会
通常也越大，这个排序逻辑和"我方风险"是两套不同的判断标准，互不混淆。

### 🔴🟡🟢 风险/利好标签（已区分"我方"与"竞品"）

每条信息卡片会自动打标签，**关键是：标签会区分这件事是关于我方品牌还是竞品**：

- 🔴 我方风险 / 🟢 我方利好 / 🟡 我方动态——只有涉及你自己品牌的负面信号才会标红
- 🎯 竞品负面·潜在机会——竞品出问题（比如NordVPN被投诉），对我方通常是机会，不是风险
- ⚠️ 竞品正面·值得关注——竞品有好消息（比如上线新功能），提示你留意但不是警报
- 📰 行业信息——不涉及具体品牌的内容（比如政策新闻）

**配置"我方品牌"**：打开 `config/own_brand.txt`，把你自己的品牌名称填进去
（必须与 `BRAND_REGISTRY` 中的名称完全一致），不需要写代码，在 GitHub 网页上
直接编辑这个文本文件即可。**如果不配置**，标签会退化为通用的"该品牌自身正/负面"
描述，不做"对我方而言"的判断（因为不知道谁是"我方"）。

判断逻辑默认是关键词规则（始终生效，不需要配置）；
如果配置了 `ANTHROPIC_API_KEY`，「今日简报」会改用 AI 生成更精准的解读，
并且 AI 也会被告知"我方"是谁，确保不会把竞品的坏消息错误地描述成我方的风险
（逐条卡片标签仍走规则判断，保证稳定可控）。

**如何扩充竞品品牌列表**：打开 `scripts/update_dashboard.py`，找到 `BRAND_REGISTRY`
字典，按现有格式添加新品牌名称和匹配关键词即可，改完 Commit + Push 生效。

---

## 历史数据查询（日期筛选）

面板顶部新增了一个「📅 历史数据查询」下拉框，可以随时切换查看任意一天的归档快照。

- 下拉框列出所有有历史归档的日期（连同当天条目数），选好后点「查看」即可跳转
- 在历史归档页面查看时，顶部会出现「↩ 返回今日最新」按钮，方便跳回最新数据
- 这个功能不需要任何配置，每次 Actions 运行后会自动维护历史索引
  （`docs/archive/manifest.json`），无需手动管理

**注意**：第一次部署当天还没有"昨天"的历史数据，下拉框里只会显示当天一条记录，
从第二天起会逐渐积累更多可查询的历史日期。

---

## 增长信号周报（深度分析，每周一次）

每日面板回答"今天发生了什么"，但如果你想知道"过去一段时间，用户/竞品反复
在讲什么、有没有持续出现的产品机会或自身问题"，需要看另一个独立页面：
`growth.html`（从每日面板顶部「📈 增长信号周报」按钮跳转）。

这是每周一自动跑一次的深度聚合分析，把过去30天的数据按关键词主题聚类，
分「自身体验问题」「产品功能缺口」「内容/营销角度」三个板块呈现。
完整说明见 `GROWTH_SIGNALS_说明.md`。

---

## 关于 Reddit 抓取（重要说明）

**面板默认不依赖 Reddit OAuth API，无需任何配置即可抓取 Reddit 内容。**

脚本会自动用 RSS / old.reddit 等免密钥方式抓取，这是 2026 年最稳定的方式
（Reddit 已大幅收紧自助 API 申请，详见 `REDDIT_提升指南.md`）。

如果你想尝试额外配置 OAuth（非必须，少数情况能进一步提升稳定性），
完整说明和最新注意事项见项目根目录的 `REDDIT_提升指南.md`。

---

## 可选：开启 AI 智能摘要（「今日要点」更聪明）

面板每个分类顶部都有「💡 今日要点」模块，默认用规则方式（高频词+重点条目）生成。
如果你想要更智能的语义摘要（真正读懂内容在说什么，而不只是罗列标题），
可以配置 Anthropic API Key：

1. 前往 https://console.anthropic.com 获取 API Key（需付费账户，用量很小，
   每天约 5 次调用，成本几乎可忽略）
2. GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret
3. Name 填：`ANTHROPIC_API_KEY`，Secret 填你的 key
4. 重新 Run workflow，「今日要点」会标注「🤖 AI摘要」而不是「📊 关键词/要点提取」

**不配置也完全可以正常使用**，规则方式已能覆盖大部分场景。

---

## 添加手工信息来源

如果有些来源（Discord、TikTok、App Store截图等）无法自动抓取，
可以手动添加到 `config/manual_inputs.csv`，格式见文件内的示例行。

编辑后 Commit + Push，下次运行时会包含这些内容。
