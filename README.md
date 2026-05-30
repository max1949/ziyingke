# BK-GTA 静态官网

一个 100% 纯静态网站，定位为：**AI 行为仿真 + 云电脑基础设施 + 仿真数据分析**。默认英文，支持中英文切换。中文品牌名：**自营客**。正式域名：`ziyingke.com`。

## 目录结构

```
bk-gta-site/
├── index.html        # 首页（定位 / 技术 / 数据价值 / 产品 / 10-Dan / Research / Pricing / FAQ）
├── platform-notice.html # 平台声明
├── platform-faq.html # 平台 FAQ / 合规与业务边界
├── contact.html      # 联系与支持
├── terms.html        # 用户协议
├── privacy.html      # 隐私政策
├── 404.html          # 静态 404 页面
├── robots.txt        # SEO 爬虫配置
├── sitemap.xml       # SEO 站点地图（上线后替换域名）
├── CNAME             # GitHub Pages 自定义域名：ziyingke.com
├── _headers          # Cloudflare / Netlify 安全响应头
├── .nojekyll         # GitHub Pages 兼容
├── assets/
│   ├── css/style.css # 样式
│   └── js/main.js    # 导航与 FAQ 交互
└── README.md
```

## 本地预览

直接双击 `index.html` 即可在浏览器打开。或用本地服务器：

```bash
# 任选其一
python -m http.server 8080        # 然后访问 http://localhost:8080
npx serve .
```

## 部署到永久免费空间（任选一种）

### 方案 A：GitHub Pages（推荐，免费、永久）
1. 在 GitHub 新建一个仓库，例如 `bk-gta-site`。
2. 把 `bk-gta-site` 文件夹内所有文件推上去：
   ```bash
   cd bk-gta-site
   git init
   git add .
   git commit -m "init BK-GTA site"
   git branch -M main
   git remote add origin https://github.com/<你的用户名>/bk-gta-site.git
   git push -u origin main
   ```
3. 仓库 → Settings → Pages → Source 选 `main` 分支、`/ (root)` 目录 → Save。
4. 等待 1～2 分钟，访问 `https://<你的用户名>.github.io/bk-gta-site/`。

### 方案 B：Cloudflare Pages（免费、速度快、可绑定自定义域名）
1. 登录 Cloudflare → Workers & Pages → Create → Pages。
2. 连接 GitHub 仓库，或直接「Upload assets」把本文件夹拖上去。
3. 构建命令留空，输出目录填 `/` 或留空（这是纯静态站，无需构建）。
4. 部署后得到 `*.pages.dev` 域名。

### 方案 C：Netlify（免费、拖拽即部署）
1. 登录 https://app.netlify.com → 「Add new site」→「Deploy manually」。
2. 直接把 `bk-gta-site` 文件夹拖进去即可。
3. 得到 `*.netlify.app` 域名，可在 Site settings 改名或绑定域名。

> 以上三家对静态站点均提供长期免费额度，无需服务器。

## 上线前必须替换

- `robots.txt`、`sitemap.xml` 和 `CNAME` 已设置为 `ziyingke.com`。
- 如需在线表单，建议使用 Tally、Formspree、Getform 或 Netlify Forms，保持网站无后端。

## 自定义建议

- 首页文案集中在 `index.html`。
- 颜色与排版在 `assets/css/style.css` 顶部 `:root` 变量里调整。
- 替换品牌名 / Logo：改 `.brand-mark` 文本与 `.brand-text`。
- 技术社区链接已指向 `https://bkgta.com`，并在新页面打开。

## 合规提示
本站文案刻意强调「仿真、研究、基础设施、无金融执行」。请勿在对外宣传中加入「赚钱 / 收益 / 招聘 / 兼职 / 带单 / 保本 / 信号 / 跟单」等表述，以免与产品定位冲突并带来合规风险。
