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

## 关于 Reddit 抓取（重要说明）

**面板默认不依赖 Reddit OAuth API，无需任何配置即可抓取 Reddit 内容。**

脚本会自动用 RSS / old.reddit 等免密钥方式抓取，这是 2026 年最稳定的方式
（Reddit 已大幅收紧自助 API 申请，详见 `REDDIT_提升指南.md`）。

如果你想尝试额外配置 OAuth（非必须，少数情况能进一步提升稳定性），
完整说明和最新注意事项见项目根目录的 `REDDIT_提升指南.md`。

---

## 添加手工信息来源

如果有些来源（Discord、TikTok、App Store截图等）无法自动抓取，
可以手动添加到 `config/manual_inputs.csv`，格式见文件内的示例行。

编辑后 Commit + Push，下次运行时会包含这些内容。
