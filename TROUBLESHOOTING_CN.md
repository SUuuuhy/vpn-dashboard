# 排错说明 — VPN 日报面板

遇到问题时，先找到对应的错误，按照步骤操作。

---

## 错误 1：Process completed with exit code 1

**什么意思**：脚本运行失败

**怎么查原因**：
1. 进入仓库 → 点「Actions」
2. 点那次失败的运行（红色 ✗）
3. 点「build-and-deploy」
4. 展开每个步骤，找到标红的那个步骤
5. 查看具体报错信息

**常见子原因**：

### a. requirements.txt not found
- **原因**：`requirements.txt` 没有上传到仓库根目录
- **修复**：在 GitHub Desktop 检查本地仓库根目录是否有 `requirements.txt`
  - 如果没有，从 ZIP 重新复制
  - Commit + Push

### b. ModuleNotFoundError: No module named 'feedparser'
- **原因**：同上，requirements.txt 缺失或安装失败
- **修复**：同上

### c. FileNotFoundError: config/sources.csv
- **原因**：`config` 文件夹没有上传
- **修复**：检查仓库是否有 `config/sources.csv`，没有则重新复制 Commit Push

### d. 文件夹层级错误（nested folder）
- **症状**：Actions 找不到文件，但你明明上传了
- **原因**：解压后把整个文件夹拖进去，变成了 `vpn-dashboard/vpn_dashboard/...`
- **修复**：
  1. 进仓库页面，检查是否有多余的一层文件夹
  2. 如有，删除那个多余的文件夹，把里面的内容移出来
  3. 或者：在 GitHub 网页，用「Delete file」删掉错误的，重新上传正确的层级

---

## 错误 2：Get Pages site failed / Configure Pages failed

**什么意思**：GitHub Pages 没有正确配置

**修复步骤**：
1. 进入仓库 → Settings → Pages
2. 确认「Source」选的是「**GitHub Actions**」（不是 Deploy from branch）
3. 如果之前选的是「Deploy from branch」，改成「GitHub Actions」
4. 等 1 分钟后重新 Run workflow

---

## 错误 3：Upload Pages artifact failed

**什么意思**：`docs/index.html` 没有生成

**修复步骤**：
1. 查看 Actions 日志中「Generate dashboard」步骤的输出
2. 如果有 Python 错误，根据错误信息定位问题
3. 如果 `docs/index.html` 不存在，检查 `scripts/update_dashboard.py` 是否上传
4. 可以先用 skip_network=true 测试是否能生成空面板：
   - Actions → Run workflow → skip_network = true

---

## 错误 4：Deploy Pages failed

**什么意思**：Pages 部署失败，通常是权限问题

**修复步骤**：
1. Settings → Pages → Source → 确认是「GitHub Actions」
2. Settings → Actions → General → Workflow permissions → 选「Read and write permissions」
3. 重新 Run workflow

---

## 错误 5：GitHub Pages 地址打开是 404

**修复步骤**：
1. 确认 Actions 最近一次运行是绿色 ✅
2. 确认 Settings → Pages 有显示你的 Pages 地址
3. 等 2~3 分钟，Pages 部署有延迟
4. 确认地址正确：`https://你的用户名.github.io/仓库名/`
5. 如仓库名不是 `vpn-dashboard`，地址也要对应修改

---

## 错误 5.5：社交媒体板块始终为空

**原因**：社交媒体板块依赖 Nitter（Twitter抓取代理），这是 2026 年的结构性问题，
不是配置错误。X/Twitter 已封锁 Nitter 的访客账号机制，多数存活实例的 RSS 功能
也已被关闭。脚本已加了多实例轮询兜底，但大概率仍会持续失败。

**推荐解决方式**：改用 YouTube 官方 RSS 监控品牌动态（100%稳定，无需API Key）。
详细操作步骤见 `REDDIT_提升指南.md` 文末「社交媒体板块抓不到信息」章节。

---

## 错误 6：Reddit 板块为空

**什么意思**：Reddit 所有抓取方式都失败

**原因分析**（面板底部折叠区有诊断信息）：
- 未配置 OAuth → 参考 README 配置 REDDIT_CLIENT_ID 等
- GitHub Actions 的 IP 被 Reddit 临时限流 → 等几小时后重试
- User-Agent 不合规 → 确认 REDDIT_USER_AGENT 格式正确
- 社区暂时不可访问 → 等待恢复

**不影响其他 4 个分类**，Reddit 为空时其他信息仍正常展示。

---

## 错误 7：面板没有显示今天的信息，只有旧信息

**原因**：时效窗口设置问题

**修复**：
- Run workflow 时，lookback_hours 改为 `72`（扩大窗口到3天）
- 或者检查来源网站是否有新内容

---

## 常见问题

### Q：每次 Push 后需要手动 Run workflow 吗？
A：不需要。只有第一次或需要立刻更新时才手动运行。之后每天 08:00 SGT 自动运行。

### Q：可以改成每天运行两次吗？
A：可以，修改 `.github/workflows/daily-update.yml` 里的 cron 表达式。
例如每天 00:00 和 12:00 UTC：
```yaml
  schedule:
    - cron: '0 0 * * *'
    - cron: '0 12 * * *'
```
修改后 Commit + Push 即生效。

### Q：如何添加新的信息来源？
A：编辑 `config/sources.csv`，参照现有格式添加一行，Commit + Push。

### Q：如何临时关闭某个来源？
A：编辑 `config/sources.csv`，把对应行的 `enabled` 改为 `false`，Commit + Push。

### Q：如何手动添加无法自动抓取的信息？
A：编辑 `config/manual_inputs.csv`，参照格式添加，Commit + Push，下次运行会包含。

---

## 联系方式

如有无法自行解决的问题，把以下信息提供给技术支持：
1. Actions 失败运行的截图（包含步骤展开的日志）
2. 仓库文件结构截图（根目录展开的样子）
3. Settings → Pages 页面截图
