# ✅ 只照做清单 — VPN 日报部署

按顺序打勾，每一步完成才继续下一步。

---

## 准备工作

- [ ] 我有 GitHub 账号（没有就去 github.com 注册，免费）
- [ ] 我已安装 GitHub Desktop（没有就去 desktop.github.com 下载）
- [ ] 我已下载项目 ZIP 文件并解压到桌面

---

## 第一阶段：创建仓库

- [ ] 1. 打开 github.com，登录
- [ ] 2. 点右上角「+」→「New repository」
- [ ] 3. Repository name 填：`vpn-dashboard`
- [ ] 4. 选择 **Public**
- [ ] 5. **不勾选** "Add a README file"
- [ ] 6. 点「Create repository」

---

## 第二阶段：上传文件

- [ ] 7. 打开 GitHub Desktop → File → Clone Repository
- [ ] 8. 选「vpn-dashboard」仓库，选本地保存位置，点 Clone
- [ ] 9. 打开解压后的项目文件夹
- [ ] 10. 把以下内容**复制**到本地仓库根目录（不是复制整个文件夹，是复制里面的内容）：
  - `.github` 文件夹
  - `scripts` 文件夹
  - `config` 文件夹
  - `docs` 文件夹
  - `requirements.txt`
  - `README_无代码部署.md`
  - `CHECKLIST_只照做.md`

- [ ] 11. 检查结构：打开仓库根目录，应该能看到 `.github`、`scripts`、`docs` 等文件夹在**第一层**
  - ✅ 正确：`vpn-dashboard/.github/workflows/daily-update.yml`
  - ❌ 错误：`vpn-dashboard/vpn_dashboard/.github/workflows/daily-update.yml`

- [ ] 12. 打开 GitHub Desktop，左侧 Changes 应该有很多文件变化
- [ ] 13. 底部 Summary 填：`初始部署`
- [ ] 14. 点「Commit to main」
- [ ] 15. 点右上角「Push origin」（等待上传完成）

---

## 第三阶段：开启 GitHub Pages

- [ ] 16. 浏览器打开你的仓库页面（github.com/你的用户名/vpn-dashboard）
- [ ] 17. 点「Settings」（顶部导航栏）
- [ ] 18. 左侧菜单点「Pages」
- [ ] 19. 在「Build and deployment」→「Source」下选「**GitHub Actions**」
- [ ] 20. 确认页面显示「GitHub Actions」已选中

---

## 第四阶段：手动运行

- [ ] 21. 点仓库顶部「Actions」标签
- [ ] 22. 左侧找「Daily VPN Dashboard Update」并点击
- [ ] 23. 点右侧「Run workflow」按钮
- [ ] 24. 参数保持默认：skip_network = false，lookback_hours = 48
- [ ] 25. 点绿色「Run workflow」
- [ ] 26. 等待 2~5 分钟
- [ ] 27. 看到绿色 ✅ 表示成功

---

## 第五阶段：验收

- [ ] 28. 打开 `https://你的用户名.github.io/vpn-dashboard/`
- [ ] 29. 页面正常加载，显示「VPN 行业情报日报」标题
- [ ] 30. 顶部显示「更新时间」为今天
- [ ] 31. 页面有 5 个分类板块

---

## 可选：配置 Reddit API（提升抓取质量）

- [ ] A. 去 reddit.com/prefs/apps 创建「script」类型 App
- [ ] B. 记录 client_id 和 secret
- [ ] C. GitHub 仓库 → Settings → Secrets → Actions → New secret
- [ ] D. 添加 `REDDIT_CLIENT_ID`、`REDDIT_CLIENT_SECRET`、`REDDIT_USER_AGENT`
- [ ] E. 再次 Run workflow 验证

---

完成！之后每天 08:00 SGT 自动更新，无需任何操作。
