# CONTEXT.md — 领域模型与统一语言词汇表 (Glossary)

本文件是 `career-radar` 项目的统一语言（Ubiquitous Language）定义。涉及本项目领域概念时，应优先使用本词汇表中的 canonical terms，避免同一概念出现多个冲突名称。

---

## 核心概念

### Opportunity（职业机会）
外部发布的一个具体工作职位、教学岗位或项目合作机会的实体抽象。

### Scope（范围）
基于用户偏好设定的情报检索边界（`IN_SCOPE` / `OUT_OF_SCOPE`）。`OUT_OF_SCOPE` 仅表示 Career Radar 不主动跟进与汇报该机会，与候选人是否具备资格无关。

### Preference（用户偏好）
用于指导情报路由、排序与行动倾向的非资格属性。涵盖赛道优先级（`Track Priority`）、地域层级（`Location Priority`）、现实保障（`Benefit Preferences`：社保医保、稳定性、时间自主权）、雇佣形态（`Engagement Preferences`）与弹性薪酬考量（`Compensation Preferences`）。偏好考量绝不作为法定资格准入的阻断项。

### Track Priority（赛道优先级）
业务关注赛道的战略分组与呈现层级（如 `1`、`2`、`3`、`4`），独立于法定资格准入（Eligibility）。

### Location Priority（地域优先级）
工作地点匹配层级（`P1 广州`、`P2 广佛莞周边`、`P3 大湾区其他`），用于呈现排序与关注度标记。

### Availability Constraint（排期约束）
候选人已知的时间排期与外聘/项目承诺约束。在排课或日程细节不明确（`UNKNOWN`）前，严禁主观推断为时间冲突。

### Unresolved Candidate Fact（待确认事实）
候选人背景中处于存疑或待核实状态的事实（如标记为 `NEEDS_USER_CONFIRMATION`），系统将其视为未决事项，不作为确凿事实推演。

---

## 证据与匹配模型

### Requirement Evidence（招聘要求证据）
来自招聘方第一方官方公告、岗位附件表格或法定发布系统的文本片段与具体条件凭证。

### Candidate Evidence（候选人背景证据）
来自用户私有画像配置（`Candidate Profile`）的真实事实与多层能力凭证。

### Proven Capability（已证明核心能力）
具备充分实践成果、历史岗位经历或真实项目/教学凭证支持的既有能力。

### Adjacent Capability（邻近迁移技能）
具备底层技术或方法论相近性、可在具体场景中迁移应用但需结合上下文研判的拓展技能。

### Learning Target（学习探索目标）
候选人当前正在探索、学习或构建的技能方向。在语义评定中，**学习目标严禁自动视为能力契合的 `PASS` 证据**。

### Evidence State（证据状态）
Agent 对某个适用维度进行语义推演后的证据状态评价，包含五个 canonical states：
- `PASS`：已有充分证据确认满足；
- `REVIEW`：已有证据，但存在放宽条款、歧义或需进一步判断；
- `FAIL`：已有权威证据确认不满足硬门槛且无适用放宽；
- `UNKNOWN`：信息重要但当前证据不足；
- `N/A`：该维度对当前岗位不适用。

具体判断与聚合规则参见 [`docs/adr/0001-agent-driven-discrete-matching-protocol.md`](docs/adr/0001-agent-driven-discrete-matching-protocol.md)。

### Eligibility（资格合规性）
候选人与岗位法定准入条件的符合程度，严格限定在以下 6 个标准维度：
1. `Age`（年龄上限与基准日）
2. `Education`（学历与学位层次）
3. `Formal Qualification`（法定学科专业代码与从业资质）
4. `Capability Fit`（实际能力与课程契合度）
5. `Teaching Experience`（任教经历与年限）
6. `Industry Experience`（行业与工程实战经历）

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
用户的全景私密背景与多轨职业偏好配置（含出生日期/年龄、三层能力分级、标准赛道配置、现实偏好与排期约束）。本地存放在被 `.gitignore` 保护的 `profile.local.yaml`，公开仓库仅保留通用脱敏模板 `config/profile.example.yaml`。

### Daily Digest Report（每日机会简报）
Agent 运行完成后生成的结构化 Markdown 报告（保存在 `reports/YYYY-MM-DD.md`），高信噪比呈现高价值新增机会、重点岗位动态变更、存疑待确认项及渠道网络变动。

### Local Data Cache（本地数据持久化）
本地被忽略的 `.data/` 目录，存放 Opportunity 历史库（`opportunities.jsonl`）、渠道元数据（`sources.json`）及原始公告抓取缓存。
