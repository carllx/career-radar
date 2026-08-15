# 网络获取与监控技术选型与配额边界调研报告

> **关联工单**：[#3 网络获取与监控技术选型与配额边界调研](https://github.com/carllx/career-radar/issues/3)  
> **研究目标**：调研原生 HTTP、RSS、专用搜索/爬取 API 与 Headless Browser 在招聘监控场景下的适用边界与免费配额。

---

## 1. 原生 HTTP 请求（Python / Node.js）

### 1.1 性能与静态 HTML 提取
- **客户端生态**：Python（`httpx`, `aiohttp`, `requests`）、Node.js（原生 `fetch`, `undici`, `axios`）。
- **响应速度**：国内网络直连高校（`.edu.cn`）与政务人社（`.gov.cn`）服务器响应一般在 **50ms ~ 300ms**，单请求仅数 KB 内存。
- **DOM 提取能力**：国内 80% 以上的高校人事处和地市人社局采用传统 CMS（如 TRS、SiteFactory、动易、博达等），公告列表与正文均为服务端渲染（SSR）。配合 `cheerio`、`BeautifulSoup4` 或 `lxml` 可在毫秒级完成解析。

### 1.2 关键挑战与防御机制
1. **海外 IP 阻断 (Geo-blocking)**：绝大部分 `.gov.cn` 与部分高校配置了区域防火墙策略，直接阻断海外云厂商机房 IP。调度节点建议位于国内或配合合规出口。
2. **TLS/SSL 证书链老旧**：部分政务与高校老旧站点缺少中间证书，原生请求易报证书验证失败，需支持配置 CA Bundle 或针对只读公开公告的可控 TLS 降级。
3. **字符编码混乱（GB2312 / GBK / GB18030）**：老旧系统 Header 未规范声明 Charset 时易出现乱码，需通过 `<meta>` 标签解析与 `charset-normalizer`/`chardet` 自动推断。
4. **WAF 动态 Challenge**：政务云（如阿里云盾 `acw_sc__v2`、加速乐、安恒等）的动态 JS 重定向会导致纯 HTTP 客户端返回 421/403/521，需要降级方案支撑。

---

## 2. RSS / Feed 技术

- **RSSHub 现有路由覆盖**：高校人事处与各地人社局的公共路由覆盖率极低，无法直接满足垂直长尾监控需求。详见 [RSSHub Routes](https://docs.rsshub.app/zh/routes/government)。
- **维护成本**：高校改版会导致硬编码 CSS 选择器频繁失效；部分动态路由需要依赖 Chromium，自建 Docker 实例内存占用达 1GB+。
- **公共实例限制**：公共实例容易被目标站点列入 IP 黑名单，生产环境不宜直接依赖公共 RSS 聚合。

---

## 3. 专用搜索与爬取 API（功能与免费配额）

### 3.1 Tavily API
- **官方定位**：面向 LLM Agent 的实时搜索与内容抽取 API。
- **免费配额**：**1,000 API Credits / 月**（每月 1 日重置，无需绑定信用卡）。
- **速率限制**：免费版 100 RPM（每分钟请求数）。
- **核心功能**：支持中文关键词、`search_depth`（basic 消耗 1 额度，advanced 消耗 2 额度）、`include_raw_content=true` 返回清洗正文、支持 `include_domains` 与 `time_range`（如 `"day"`, `"week"`）时效过滤。
- **官方文档**：[Tavily Docs](https://docs.tavily.com) | [Tavily Pricing](https://tavily.com)

### 3.2 Firecrawl API
- **官方定位**：将任意网站/网页转换为高质量 Markdown 与结构化 JSON 的 LLM 爬虫。
- **免费配额**：**1,000 Free Credits / 月**，并发上限 2 并发。支持完全开源自建（Self-hosted）。
- **扣费规则**：`/v1/scrape` 单页抓取 1 Credit/页，`/v1/search` 2 Credits/10 结果。
- **反爬与渲染**：内置 Headless 浏览器与代理轮换，自动等待 JS 渲染并绕过复杂反爬，输出清洗后的 Markdown。
- **官方文档**：[Firecrawl Docs](https://docs.firecrawl.dev) | [Firecrawl Pricing](https://www.firecrawl.dev/pricing)

### 3.3 Brave Search API
- **官方定位**：基于独立索引的全球网页搜索 API。
- **免费配额**：**每月赠送 $5 免费额度**（等效于 **1,000 次免费搜索**）。需绑卡核验，可在控制台设置 **Hard Cap = $0** 防超额扣费。
- **速率限制**：50 QPS。
- **时效与长尾**：支持 `freshness` 参数（如 `pd` 过去 24 小时、`pw` 过去 7 天），支持 `country=CN` 与 `search_lang=zh`。
- **官方文档**：[Brave Search API Docs](https://api-dashboard.search.brave.com/documentation/pricing)

---

## 4. Headless Browser（Playwright / Puppeteer）

- **开销**：单 Chromium 实例常驻内存 **150MB ~ 400MB**，冷启动 1.5~3s，页面完整渲染 2~5s，耗时比原生 HTTP 高 10~20 倍。
- **适用场景**：必须执行客户端 JS 渲染的 SPA 招聘单页应用、动态滑动验证码、复杂政务 WAF 动态 JS Challenge。
- **运行环境考量**：本地开发环境/CLI 运行极佳；低配 VPS（1GB 内存）易 OOM；GitHub Actions 需注意每月 2,000 分钟配额消耗。

---

## 5. agent-reach 能力定位

- **定位**：IDE 交互式探索、全网背景研究与多渠道即时检索工具。
- **环境要求**：依赖本地开发机、本地浏览器 Cookie 登录态及 OpenCLI 运行时。
- **架构约束**：严禁将其预设为 Career Radar 产品的生产运行时依赖；生产数据采集应依赖标准 API 或原生 HTTP 客户端。

---

## 6. 技术矩阵与分层建议

| 技术方案 | 适用生命周期阶段 | 官方免费配额 | 核心优势 | 局限与边界 |
| :--- | :--- | :--- | :--- | :--- |
| **原生 HTTP** (`httpx`/`undici`) | 固定源轮询、80% 正文抓取 | **完全免费、无上限** | 毫秒级极速、内存占用极低 | 不支持执行 JS、需处理 GBK/证书 |
| **Brave Search API** | 全网时效线索发现 | **$5/月（~1,000 次）** | 50 QPS、独立索引、支持时效过滤 | 需绑卡（可设硬顶） |
| **Tavily API** | 全网线索发现与正文清洗 | **1,000 Credits/月** | 原生 LLM 优化、无需绑卡 | 并发 100 RPM |
| **Firecrawl API** | 疑难/SPA 页面正文抓取 | **1,000 Credits/月** | 自动绕过 WAF/SPA、转高质量 Markdown | 免费版 2 并发 |
| **Playwright** | 本地攻坚与复杂交互 | **完全免费（消耗算力）** | 完整浏览器控制力、支持复杂验证 | 资源占用高、并发易 OOM |

### 建议分层流水线
1. **发现层**：Brave / Tavily API（每月共约 2,000 次免费额度）用于全网增量线索探测；
2. **抓取层**：优先使用 原生 HTTP 请求抓取 80%+ 静态第一方公告；遇 SPA 或 WAF 动态拦截时，自动降级至 Firecrawl API 或本地 Playwright；
3. **提取层**：结合 Cheerio/BS4 结构化提取与轻量 LLM 语义解析。
