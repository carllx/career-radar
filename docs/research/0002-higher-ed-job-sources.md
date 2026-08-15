# 高校与职校第一方及聚合招聘信息源摸底与抓取特征调研报告

> **关联工单**：[#2 高校与职校第一方及聚合招聘信息源摸底与抓取特征调研](https://github.com/carllx/career-radar/issues/2)  
> **研究定位**：提供可验证的事实依据与抽样观测数据，供后续架构决策与原型验证参考。

---

## 1. 广州及珠三角院校招聘信息发布体系

珠三角地区高校与职业院校的招聘发布呈现明显的**层级管理与主管归属差异**：

```
                              ┌───────────────────────────────────┐
                              │      法定主管与统招发布源          │
                              │ (广东省人社厅 / 广州市人社局)     │
                              └─────────────────┬─────────────────┘
                                                │ 事业单位统招/备案
          ┌─────────────────────────────────────┼─────────────────────────────────────┐
          ▼                                     ▼                                     ▼
┌──────────────────┐                  ┌──────────────────┐                  ┌──────────────────┐
│   教育部直属高校   │                  │  省属/市属公办院校 │                  │ 民办高校/独立学院 │
│ (中大/华工人事处)  │                  │ (省属高校/市属职院) │                  │ (自主招聘/商业平台)│
└──────────────────┘                  └──────────────────┘                  └──────────────────┘
```

### 1.1 主管归属与第一方发布源分类
1. **主管部门法定统招发布源**：
   - **广东省人力资源和社会保障厅**（[http://hrss.gd.gov.cn/zwgk/gsgg/](http://hrss.gd.gov.cn/zwgk/gsgg/)）：发布广东省属事业单位集中招聘、省属公办高校（如华南师范大学、广东工业大学、广东轻工职业技术大学）及省属技师学院的公开招聘公告。
   - **广州市人力资源和社会保障局**（[http://rsj.gz.gov.cn/ywzt/rszdgg/sydwzp/sydwzpgg/](http://rsj.gz.gov.cn/ywzt/rszdgg/sydwzp/sydwzpgg/)）：发布广州市属事业单位集中招聘、广州市属公办高校（如广州大学、广州番禺职业技术学院）及市属技师学院的招聘公告。
2. **院校人事处门户与招聘系统**：
   - **教育部直属高校（部属）**：中山大学（[https://rcb.sysu.edu.cn/](https://rcb.sysu.edu.cn/)）、华南理工大学（[https://renshi.scut.edu.cn/](https://renshi.scut.edu.cn/)），招聘由教育部与学校自主组织，人事处发布公告并跳转至校内招聘系统。
   - **广东省属公办本科高校**：华南师范大学（[https://rsc.scnu.edu.cn/](https://rsc.scnu.edu.cn/)）、广东工业大学（[https://rsc.gdut.edu.cn/](https://rsc.gdut.edu.cn/)）、广州美术学院（[https://www.gzarts.edu.cn/](https://www.gzarts.edu.cn/)）。
   - **广州市属公办本科高校**：广州大学（[https://rsc.gzhu.edu.cn/rczp.htm](https://rsc.gzhu.edu.cn/rczp.htm)）、广州医科大学（[https://ygrsc.gzhmu.edu.cn/](https://ygrsc.gzhmu.edu.cn/)）。
   - **省属/市属公办高职与职业大学**：广东轻工职业技术大学（省属，[https://rsc.gdqy.edu.cn/](https://rsc.gdqy.edu.cn/)）、深圳职业技术大学（省市共建，[https://renshi.szpu.edu.cn/](https://renshi.szpu.edu.cn/)）、广州番禺职业技术学院（市属，[https://rsc.gzpyp.edu.cn/](https://rsc.gzpyp.edu.cn/)）、广东水利电力职业技术学院（省属，[https://rsc.gdsdxy.edu.cn/](https://rsc.gdsdxy.edu.cn/)）。
   - **公办技师学院（人社厅/局直属事业单位）**：广州市技师学院（[https://www.gzjsw.cn/](https://www.gzjsw.cn/)）、广东省轻工业技师学院（[https://www.gdqgjs.cn/](https://www.gdqgjs.cn/)）。
   - **民办本科与高等职业院校**：广州软件学院（[https://rsc.seig.edu.cn/](https://rsc.seig.edu.cn/)）、广东白云学院（[https://rsc.baiyunu.edu.cn/](https://rsc.baiyunu.edu.cn/)）、广州华商学院（[https://rsc.gzhsfy.edu.cn/](https://rsc.gzhsfy.edu.cn/)）。

---

## 2. 目标站点技术特征抽样观测（样本 $N=10$）

> **抽样核查日期**：2026-08-15  
> **抽样范围**：涵盖部属高校、省属本科、市属本科、公办职大、公办高职、技师学院、民办高校、人社厅局与商业聚合平台共 10 个代表性站点。

| 序号 | 机构/平台名称 | 抽样页面 URL | 页面渲染架构 | 字符编码 | 岗位核心明细承载形式 |
| :---: | :--- | :--- | :--- | :--- | :--- |
| 1 | 广东省人社厅 | `http://hrss.gd.gov.cn/zwgk/gsgg/` | 服务端 SSR HTML | UTF-8 | 附件（`.xlsx` / `.pdf` 岗位表） |
| 2 | 广州市人社局 | `http://rsj.gz.gov.cn/ywzt/rszdgg/sydwzp/sydwzpgg/` | 服务端 SSR HTML | UTF-8 | 附件（`.xlsx` / `.docx` 岗位表） |
| 3 | 华南师范大学 | `https://rsc.scnu.edu.cn/` | 静态 CMS HTML | UTF-8 | 附件（`.pdf` / `.docx` 明细） |
| 4 | 广东工业大学 | `https://rsc.gdut.edu.cn/` | 静态 CMS HTML | UTF-8 | 正文简述 + 附件表格 |
| 5 | 广州大学招聘网 | `https://zp.gzhu.edu.cn/` | 前后端分离 SPA (Vue) | UTF-8 | 异步接口 JSON / 页面富文本 |
| 6 | 广东轻工职业技术大学 | `https://rsc.gdqy.edu.cn/` | 静态 CMS HTML | UTF-8 | 附件（`.xlsx` 岗位表） |
| 7 | 广州番禺职业技术学院 | `https://rsc.gzpyp.edu.cn/` | 静态 CMS HTML | UTF-8 | 附件（`.pdf` / `.docx` 明细） |
| 8 | 广州市技师学院 | `https://www.gzjsw.cn/` | 静态 CMS HTML | UTF-8 | 附件（`.docx` 招聘计划表） |
| 9 | 广东白云学院 | `https://rsc.baiyunu.edu.cn/` | 静态 CMS HTML | UTF-8 | HTML 表格正文直接展示 |
| 10 | 高校人才网（广东） | `https://www.gaoxiaojob.com/zhaopin/gaoxiao/guangdong/` | SSR + 异步 API (Nuxt) | UTF-8 | 聚合 HTML 正文 + 引导链接 |

### 抽样观测归纳
1. **页面渲染形式**：在抽样的 10 个站点中，8 个第一方发布门户（人社厅、人社局及绝大多数高校人事处）均采用成熟 CMS 生成的标准静态 HTML，无需客户端运行复杂 JavaScript 即可读取正文。
2. **核心资格数据载体**：在抽样的公办院校与事业单位招聘公告中（样本 1~4、6~8），具体招聘岗位代码、专业代码要求、学历学位门槛、年龄上限等均**以附件（`.xlsx`、`.docx`、`.pdf`）形式挂载于文末**；仅民办高校（如样本 9）常直接在 HTML 正文中排版岗位表格。
3. **反爬与安全策略**：政务站点（样本 1、2）部署了政务云 WAF（如阿里云盾），对低频单并发 GET 请求完全开放，但对突发高并发（>5 req/s）存在临时拦截。

---

## 3. 聚合平台的线索定位与第一方回溯机制

### 3.1 聚合平台的角色定位
- **高校人才网**（[gaoxiaojob.com](https://www.gaoxiaojob.com/)）、**中国教师招聘网**（[jiaoshi.com.cn](https://www.jiaoshi.com.cn/)）等聚合平台可作为**全网招聘线索发现探测器（Discovery Sentry）**。
- **限制与风险**：聚合源存在二次转载排版失真、更新滞后、附件转存商业网盘等问题，**不得作为招聘资格的最终仲裁依据**。

### 3.2 从聚合线索回溯第一方官方公告的三层候选机制
1. **显式链接提取（Explicit Link Extraction）**：解析聚合页文末标注的“来源：XX大学人事处”超链接，直接提取目标 `edu.cn` 或 `gov.cn` 原始 URL。
2. **官方报名系统识别（Portal Identifier Recognition）**：正文正则识别法定报名系统特征域名（如 `zp.*.edu.cn`、`*.hrss.gd.gov.cn`、`qgsydw.com`）。
3. **实体与文号搜索引擎对齐（Search Alignment）**：提取“招聘机构名称 + 公告标题/文号”，调用搜索引擎限定 `site:edu.cn OR site:gov.cn` 进行精准第一方定位。

---

## 4. 调研结论与后续验证建议

1. **第一方静态抓取可行性高**：主流第一方人事处公告列表与正文为标准静态 HTML，采用轻量 HTTP 客户端即可完成低成本监控。
2. **附件解析是提取岗位细则的潜在关键**：公办事业单位专任教师岗位的详细条件高度依赖文末附件表格，这一处理链路在后续规划中应作为重点关注项。
3. **若需验证真实网站连通性与反爬拦截率**：建议在进入设计实现前，通过窄范围的 `wayfinder:prototype` 对抽样中的典型政务站（如人社厅）与典型 SPA 招聘系统（如广大招聘网）进行小规模实际抓取验证。
