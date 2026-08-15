# CONTEXT.md — 领域模型与统一语言词汇表 (Glossary)

本文件是 `career-radar` 项目的统一语言（Ubiquitous Language）定义。涉及本项目领域概念时，应优先使用本词汇表中的 canonical terms，避免同一概念出现多个冲突名称。

---

## 核心概念

### Opportunity（职业机会）
外部发布的一个具体工作职位、教学岗位或项目合作机会的实体抽象。

### Scope（范围）
基于用户偏好设定的情报检索边界（`IN_SCOPE` / `OUT_OF_SCOPE`）。`OUT_OF_SCOPE` 仅表示 Career Radar 不主动跟进与汇报该机会，与候选人是否具备资格无关。

### Preference（用户偏好）
用于指导情报路由与呈现排名的非资格属性，包括 `Track Priority` 与 `Location Priority`。

### Track Priority（赛道优先级）
业务关注赛道划分，用于日报分组与通知提权（如 `P1 高校与职校教学`、`P2 游戏与数字创意产业`），不单独作为资格阻断项。

### Location Priority（地域优先级）
工作地点匹配层级（`P1 广州`、`P2 广佛莞周边`、`P3 大湾区其他`），用于呈现排序与关注度标记。

---

## 证据与匹配模型

### Requirement Evidence（招聘要求证据）
来自招聘方第一方官方公告、岗位附件表格或法定发布系统的文本片段与具体条件凭证。

### Candidate Evidence（候选人背景证据）
来自用户私有本地配置的真实资质事实凭证（如学历、工作年限、实战技能）。

### Evidence State（证据状态）
Agent 对某个适用维度进行语义推演后的证据状态评价，包含五个 canonical states：
- `PASS`：已有充分证据确认满足；
- `REVIEW`：已有证据，但存在放宽条款、歧义或需进一步判断；
- `FAIL`：已有权威证据确认不满足硬门槛且无适用放宽；
- `UNKNOWN`：信息重要但当前证据不足；
- `N/A`：该维度对当前岗位不适用。

具体判断与聚合规则参见 [`docs/adr/0001-agent-driven-discrete-matching-protocol.md`](docs/adr/0001-agent-driven-discrete-matching-protocol.md)。

### Eligibility（资格合规性）
候选人与岗位法定准入条件的符合程度（涵盖 `Age`、`Education`、`Formal Qualification` 等）。

### Formal Qualification（正式专业资格）
依据招聘公告指定的正式专业目录、专业代码或学科分类标准所界定的法定专业准入门槛。

### Capability Fit（能力与课程契合度）
候选人实际掌握的专业能力、技术栈与教学经验，与岗位所要求的课程讲授能力或岗位职责的实际契合程度。

### Hard Blocker（硬性门槛阻断）
在具备充分第一方证据的前提下，某一硬性维度求值为 `FAIL` 时的全局熔断状态，导致该岗位直接判定为 `明显不符合`。

### Final Recommendation（最终推荐结论）
Agent 综合各维度证据状态输出的最终三态决策，包含三个 canonical outcomes：
- `建议关注`
- `需要人工确认`
- `明显不符合`

具体聚合规则参见 [`docs/adr/0001-agent-driven-discrete-matching-protocol.md`](docs/adr/0001-agent-driven-discrete-matching-protocol.md)。

---

## 数据模型与实体消歧 (Data Model & Entity Resolution)

### Source（渠道源）
招聘信息的采集入口（如高校人事处官网、人社局考录系统、垂直人才网等），分为 `known_fixed`（静态已知源）与 `discovered`（动态探索发现源）。

### Announcement（招聘公告）
某一渠道在特定时间发布的一篇具体招聘文章、通知或推文，包含标题、原文文本、附件提取内容及抓取时间戳。

### Source Observation（来源观测）
从特定 `Announcement` 中切片提取出的关于某个具体岗位的原始观察记录与条款证据，是 `Announcement` 与 `Opportunity` 之间的多对一连接节点。

### Entity Resolution（实体消歧与去重）
由 Agent 基于语义、组织、岗位要求与全量上下文证据所执行的实体同一性判别过程。确定性辅助工具仅负责以高召回（High Recall）为目标检索可能相关的历史候选集（严禁将关键词或标题相似度作为硬排除门槛），最终判定由 Agent 输出四种 canonical outcomes：
- `same`：跨渠道重复发布，归并至同一 Opportunity；
- `update`：既有 Opportunity 的补充、延期或资格修订，记录变更并触发增量评估；
- `different`：确认为不同编制或不同业务方向的独立职位，创建新 Opportunity；
- `uncertain`：证据不足以断定，保留独立实体，避免激进误合并。

---

## 运行与交付 (Runtime & Delivery)

### Candidate Profile（候选人画像）
用户的私密背景信息（含学历、专业、地域赛道偏好与论文成果），本地存放在被 `.gitignore` 保护的 `profile.local.yaml`，仓库仅保留脱敏模板 `profile.example.yaml`。

### Daily Digest Report（每日机会简报）
Agent 运行完成后生成的结构化 Markdown 报告（保存在 `reports/YYYY-MM-DD.md`），高信噪比呈现高价值新增机会、重要岗位动态变更、存疑待确认项及渠道网络变动。

### Local Data Cache（本地数据持久化）
本地被忽略的 `.data/` 目录，存放 Opportunity 历史库（`opportunities.jsonl`）、渠道元数据（`sources.json`）及原始公告抓取缓存。

