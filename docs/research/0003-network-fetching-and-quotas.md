# 网络获取与监控技术选型与配额边界调研报告

> **关联工单**：[#3 网络获取与监控技术选型与配额边界调研](https://github.com/carllx/career-radar/issues/3)  
> **研究定位**：梳理原生 HTTP、RSS、专用搜索/爬取 API 与无头浏览器在招聘场景下的技术边界与配额事实，供后续方案决策参考。

---

## 1. 原生 HTTP 请求（Python / Node.js）

### 1.1 性能与基础解析特征
- **常用客户端**：Python（`httpx`, `aiohttp`, `requests`）、Node.js（原生 `fetch`, `undici`, `axios`）。
- **响应速度与资源消耗**：国内直连高校（`.edu.cn`）与政务人社（`.gov.cn`）服务器响应一般在 **50ms ~ 300ms**，单请求内存消耗在数 KB 级别。
- **DOM 解析配合**：针对服务端渲染（SSR）的静态 HTML，配合 `cheerio`、`BeautifulSoup4` 或 `lxml` 可在 1~5ms 内完成 DOM 选择器提取。

### 1.2 关键网络与协议边界
1. **海外 IP 访问限制 (Geo-blocking)**：部分政务网及高校人事系统存在针对海外云服务商机房 IP 的访问控制策略，调度节点位于国内网络环境或使用国内合规出口时连通性更佳。
2. **老旧 TLS 证书兼容**：部分地级市政务系统中间证书不完整，原生请求可能触发证书链验证错误，需支持可配置的 CA Bundle 注入或特定域名的受控 TLS 验证配置。
3. **字符编码自适应**：部分老旧发布系统未在 HTTP Header 中显式声明 Charset，需优先读取 `<meta charset="...">` 并结合 `charset-normalizer` 或 `chardet` 自动检测 GBK/GB2312/UTF-8。
4. **WAF 动态 Challenge**：遭遇政务云 WAF（如阿里云盾 `acw_sc__v2`）动态 Cookie/JS 校验时，纯 HTTP 客户端会收到 421/403/521 状态码，无法单独完成动态运算。

---

## 2. RSS / Feed 技术

- **公共路由覆盖现状**：[RSSHub 官方路由文档](https://docs.rsshub.app/zh/routes/government) 显示，高校人事处与各地人社局的公共可用路由覆盖极少，无法直接作为长尾监控的主干。
- **自建与维护成本**：自建 Feed 需针对各院校频繁改版的 DOM 编写选择器；动态路由拉起 Chromium 容器常驻内存达 1GB+。
- **公共实例限流**：公共实例集中请求易触发目标政务站点的 IP 访问频次控制。

---

## 3. 专用搜索与爬取 API（功能与官方配额核验）

### 3.1 Brave Search API
- **官方定位**：基于独立索引的全球 Web 搜索 API。
- **官方免费配额**：每月提供 **$5 免费 Credit**。Web Search API 定价为 **$5 / 1,000 次请求**，即每月免费额度可用于 **最多 1,000 次搜索请求**。
- **速率限制**：50 requests/sec (QPS)。
- **时效过滤功能**：支持 `freshness` 参数进行时间窗口筛选（如 `pd` 过去 24 小时、`pw` 过去 7 天），支持 `country=CN` 与 `search_lang=zh` 定向。
- **官方文档与定价**：[Brave Search API Documentation](https://api-dashboard.search.brave.com/documentation/pricing)

### 3.2 Tavily API
- **官方定位**：面向 LLM Agent 的实时搜索与内容抽取 API。
- **官方免费配额**：**1,000 API Credits / 月**（每月 1 日重置，无需绑定信用卡）。
- **扣费规则**：基础搜索（`search_depth="basic"`）消耗 **1 Credit**；深度搜索（`search_depth="advanced"`）消耗 **2 Credits**。
- **速率限制**：免费计划为 **100 RPM**（每分钟请求数）。
- **特性**：支持 `include_raw_content=true` 直接获取清洗后的正文，支持 `include_domains` 与 `time_range` 过滤。
- **官方文档与定价**：[Tavily API Pricing & Docs](https://docs.tavily.com/docs/tavily-api/pricing)

### 3.3 Firecrawl API
- **官方定位**：将网页转化为 Clean Markdown 与结构化数据的爬取服务，支持开源自建。
- **官方免费配额**：**1,000 Free Credits / 月**，并发请求上限 **2 并发**。
- **扣费规则**：`/v1/scrape` 单页抓取消耗 **1 Credit / 页**；`/v1/search` 消耗 **2 Credits / 10 个结果**。
- **动态页面与反爬支持**：支持 JavaScript 渲染、代理轮换及针对部分 anti-bot 场景的处理。对 Career Radar 目标网站的实际可用性与成功率需要通过 Prototype 验证。
- **官方文档与定价**：[Firecrawl API Pricing](https://www.firecrawl.dev/pricing) ｜ [Firecrawl Docs](https://docs.firecrawl.dev)

---

## 4. Headless Browser（Playwright / Puppeteer）与运行环境

### 4.1 开销与适用场景
- **资源开销**：单 Chromium 实例常驻内存 **150MB ~ 400MB**，冷启动耗时约 1.5~3s，页面网络与 JS 解析约 2~5s。
- **适用场景**：必须由客户端执行 JavaScript 渲染的 SPA 招聘单页应用、动态滑块验证、复杂交互表单。

### 4.2 运行环境边界
- **本地开发机 / 本地 CLI**：计算与内存资源充裕，非常适合作为攻坚或疑难站点的验证与调试工具。
- **GitHub Actions (Public Repository)**：
  > [!NOTE]
  > 本项目为 **公开开源仓库（Public Repository）**。根据 [GitHub Actions 计费官方文档](https://docs.github.com/en/billing/managing-billing-for-github-actions/about-billing-for-github-actions)，标准 GitHub-hosted runners 在 public 仓库中执行是**免费且无每月分钟数限制**的。但在 workflow 中每次全新安装与拉起 Playwright/Chromium 仍存在构建与冷启动时间开销。
- **低配 VPS (1 vCPU, 1GB RAM)**：若并发运行多实例极易触发 OOM，需严格限制并发与资源加载。

---

## 5. agent-reach 能力定位

- **定位**：IDE 交互式探索、全网背景研究与多渠道即时检索工具。
- **运行依赖**：依赖本地开发机、本地浏览器 Cookie 登录态及 OpenCLI 运行时。
- **架构约定**：不预设为 Career Radar 产品的生产运行时依赖；生产环境应调用标准 API 或原生 HTTP 客户端。

---

## 6. 技术候选矩阵总览

| 技术方案 | 适用场景 | 官方免费配额 / 计费规则 | 主要优势 | 潜在边界与注意事项 |
| :--- | :--- | :--- | :--- | :--- |
| **原生 HTTP** (`httpx`/`undici`) | 静态第一方监控、正文抓取 | **完全免费、无配额限制** | 极低延迟与内存开销、高吞吐 | 不执行 JS；需处理海外 IP 访问控制与 GBK 编码 |
| **Brave Search API** | 全网新增线索发现 | **$5/月免费**（约 1,000 次搜索） | 独立索引、50 QPS、支持 24h 时效过滤 | 需绑卡（可设 Hard Cap = $0） |
| **Tavily API** | 全网线索发现与正文清洗 | **1,000 Credits/月**（免绑卡） | LLM 提取优化、支持域名白名单过滤 | 深度搜索扣 2 credits；并发限制 100 RPM |
| **Firecrawl API** | 疑难/SPA 页面正文抓取 | **1,000 Credits/月**（可开源自建） | 自动转 Markdown，支持 JS 渲染 | 免费版 2 并发；目标站点成功率需实测验证 |
| **Playwright** | 本地疑难攻坚与动态交互 | **完全免费**（消耗宿主机算力） | 具备完整浏览器控制力，适合复杂交互 | 资源占用大（150~400MB/实例） |
