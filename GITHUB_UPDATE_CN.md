# GitHub 更新操作说明

本文档说明如何在已部署的项目中更新文件，以及如何手动触发运行。

---

## 情况 A：更新信息源列表（config/sources.csv）

### 用 GitHub 网页编辑（最简单）

1. 打开你的仓库页面
2. 点击 `config` 文件夹 → 点 `sources.csv`
3. 点右上角铅笔图标「Edit this file」
4. 直接在网页上编辑内容（按 CSV 格式添加或修改行）
5. 滚动到底部，填写「Commit changes」描述（例如：添加新来源）
6. 点「Commit changes」

更改立即生效，下次 Actions 运行时会使用新的来源列表。

---

## 情况 B：更新脚本文件（scripts/update_dashboard.py）

1. 从提供方获取新版本的 `update_dashboard.py`
2. 打开 GitHub Desktop，确保本地仓库是最新的（点「Fetch origin」）
3. 用新文件替换本地 `scripts/update_dashboard.py`
4. GitHub Desktop 会显示文件变化
5. 填写 Summary（例如：更新抓取脚本）
6. 点「Commit to main」→「Push origin」

---

## 情况 C：手动触发立即更新

1. 进入仓库页面 → 点「Actions」
2. 左侧点「Daily VPN Dashboard Update」
3. 点右上角「Run workflow」
4. 参数说明：
   - `skip_network`：
     - `false` = 正常抓取（推荐）
     - `true` = 跳过网络，只用 manual_inputs.csv 生成面板（测试用）
   - `lookback_hours`：
     - `48` = 抓取过去 48 小时（默认）
     - `72` = 如果内容较少，可扩大到 72 小时
5. 点「Run workflow」

---

## 情况 D：查看历史运行记录

1. 仓库 → Actions → Daily VPN Dashboard Update
2. 可以看到每次运行的时间、状态（✅/❌）
3. 点某次运行 → 展开步骤 → 查看日志

---

## 情况 E：查看历史日报

历史日报归档在：`docs/archive/` 文件夹下，按日期命名。

也可以直接访问：
```
https://你的用户名.github.io/vpn-dashboard/archive/2026-06-28.html
```

---

## 情况 F：完整重新部署（出现严重问题时）

1. 下载最新的项目 ZIP
2. 解压到本地
3. 把所有文件复制到本地仓库（覆盖）
4. GitHub Desktop：Commit + Push
5. Actions 重新 Run workflow

---

## 文件说明速查

| 文件 | 作用 | 多久改一次 |
|------|------|-----------|
| `config/sources.csv` | 信息源列表，可增删改 | 随时 |
| `config/manual_inputs.csv` | 手工添加信息 | 随时 |
| `scripts/update_dashboard.py` | 抓取和生成逻辑 | 升级时 |
| `.github/workflows/daily-update.yml` | 自动运行计划 | 一般不改 |
| `requirements.txt` | Python 依赖 | 升级时 |
| `docs/` | 生成的网页（自动生成，不要手改） | 自动 |
