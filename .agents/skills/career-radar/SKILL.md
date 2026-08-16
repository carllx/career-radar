---
name: career-radar
description: "Executes an end-to-end Autonomous Career Radar run as the primary workflow orchestrator. Coordinates bounded known-source monitoring, open source discovery, first-party announcement fetching, candidate retrieval, 4-state entity resolution, 6-dimension qualification evaluation, atomic persistence, and daily digest generation."
---

# Career Radar — Autonomous Daily Radar Orchestration Skill

本 Skill 是 Career Radar 的**最高工作流编排器（Workflow Orchestrator）**。
当收到用户手动指令（如“运行 Career Radar 巡检”）或被 IDE Schedule 周期唤醒时，Agent 必须以此规范端到端自主执行巡检、探索、消歧、评定与交付。Python 模块仅作为底层确定性辅助层（Deterministic Helpers）。

---

## 1. 核心领域契约与协议规范

### 1.1 资格评定 6 大标准维度 (6 Canonical Eligibility Dimensions)
每次对岗位进行资格评估时，必须且仅能使用以下 6 个标准维度：
1. **`Age`**：年龄硬性上限与基准日要求；
2. **`Education`**：学历层次（博士/硕士/本科）与全日制学位要求；
3. **`Formal Qualification`**：学科专业代码/名称对口度及法定从业资质/资格证；
4. **`Capability Fit`**：专业方向匹配度、教学科研或工程成果门槛；
5. **`Teaching Experience`**：高校或职业院校任教年限与经历要求；
6. **`Industry Experience`**：企业一线研发、工程实践或专业技术经历要求。

> [!IMPORTANT]
> **偏好与资格边界**：候选人画像中的 `Track Priority`（赛道偏好）与 `Location Priority`（地域偏好）属于检索与圈定范围的 `Preference / Scope / Routing`，**绝不作为**上述 6 项资格准入维度的评估项。

### 1.2 证据状态与判定结论 (5 Evidence States & 3 Recommendations)
每个维度的 `state` 必须严格取自以下 5 种标准状态：
- **`PASS`**：充分满足要求；
- **`REVIEW`**：存在边缘模糊或需人工核实（如相近专业、跨学科等）；
- **`FAIL`**：明确不符合硬性门槛；
- **`UNKNOWN`**：公告未提供足够信息以供核验；
- **`N/A`**：公告对该维度无任何限制要求。

最终推荐结论（Final Recommendation）由多维聚合确定：
- **`建议关注`**：全部维度为 `PASS` 或 `N/A`；
- **`需要人工确认`**：存在 `REVIEW` 或 `UNKNOWN` 且无 `FAIL`；
- **`明显不符合`**：存在任意维度为 `FAIL`。

### 1.3 机会行动意图 (Opportunity Intent 3 Canonical States)
针对具体机会当前应采取的行动姿态，必须且仅能取自以下 3 种标准状态：
- **`APPLY_NOW`**：即刻行动（条件对口、偏好符合，建议立即推进申请）；
- **`CONDITIONAL`**：条件关注（存在特定排期、待遇、岗位编制或外部约束，触发条件后再行动）；
- **`WATCH_LEARN`**：情报观测（用于跟踪赛道标杆技能要求、薪酬风向或市场动态，非即刻投递目标）。

> [!IMPORTANT]
> **资格与意图解耦**：
> 1. `Track.default_intent` 仅为候选人画像中配置的**先验倾向**，绝不机械等同于具体机会的最终意图；
> 2. `Opportunity Intent` 由 Agent 语义层依据岗位具体条件与候选人偏好综合裁决；
> 3. 意图吸引力**绝不可篡改**资格评定结论（`Eligibility FAIL` 依然保持 `明显不符合`）。

### 1.4 市场情报观察 8 大标准事实 (8 Canonical Market Intelligence Facts)
针对 `opportunity_intent == "WATCH_LEARN"` 的情报观测机会，Agent 语义层必须从第一方公告与附件证据中提取且仅提取以下 8 项事实：
1. **`brief`**：项目/岗位核心简述与业务背景；
2. **`deliverables`**：明确交付物清单；
3. **`content_type`**：内容资产类别或岗位类型；
4. **`timeline_volume`**：周期排期、体量与交付节奏；
5. **`revision_quality_rules`**：修改轮次、验收标准与质量门槛；
6. **`requested_tools_workflow`**：要求掌握或使用的工具链、软件与工作流；
7. **`budget_compensation`**：预算区间、报酬标准或岗位薪酬；
8. **`use_case`**：成果应用场景或业务落地方向。

> [!IMPORTANT]
> **真实证据与 UNKNOWN 规范**：
> 1. 第一方证据未提及的事实，值必须为字面量 **`UNKNOWN`**（严禁凭空脑补或外推预算、工具链、交付节奏或修改规则）；
> 2. 市场需求中提及的技能并不等同于候选人已掌握该技能（`Learning Targets != Proven Capabilities`），市场情报**绝不反向篡改**候选人的 `Capability Fit` 资格结论。

### 1.5 概念解耦原则 (Semantic Independence)
- **Entity Resolution `uncertain`**：实体同一性存疑（跨渠道两篇公告是否属于同一用人单位同一岗位存疑，建立双向 soft link，不污染资格维度）；
- **Dimension `UNKNOWN` / `REVIEW`**：单项资格维度事实或证据的不确定性；
- **Final Recommendation `需要人工确认`**：多维综合研判后的资格准入分级；
- **Opportunity Intent `CONDITIONAL` / `WATCH_LEARN`**：针对该具体机会的行动与跟进策略；
- **Market Intelligence `UNKNOWN`**：第一方来源未记载某项市场事实（非负面证据，亦非资格不确定性）。
五者严格解耦，独立表达。

---

## 2. Agent 端到端编排工作流 (14-Step Workflow)

### 步骤 1：加载候选人画像与运行状态
- 读取 `profile.local.yaml`（若缺失则回退 `config/profile.example.yaml`）；
- 读取公共种子源 `config/sources.seed.json`（只读 SSOT）；
- 读取本地渠道状态 `.data/sources.json`（包含历史 `active` 与 `discovered` 渠道）；
- 读取既有岗位实体库 `.data/opportunities.jsonl`。

### 步骤 2：圈定巡检候选网络 (Bounded Monitoring Set)
- 从 `active` 和 `discovered` 渠道中，根据候选人 `track_names()`、目标地域及巡检价值圈定本轮巡检子集；
- 严禁无脑全量遍历，保持在有界巡检预算内。

### 步骤 3：执行已知源巡检并记录真实事实 (Known-source Monitoring)
- 实际访问选中的目标渠道（如人社厅公告栏、高校招聘专栏）；
- 由 Helper 记录**真实的** `MonitoringFact`（记录实际技术状态：`success`、`blocked_by_captcha`、`failed`、`content_type_mismatch` 及抓取 URL 与时间戳）；
- **严禁无实际访问伪造 `success`**。

### 步骤 4：开放动态渠道发现 (Open Source Discovery)
- Agent 主动使用环境已批准的能力（Web 搜索、`agent-reach`、第一方官网导航）探索公共种子库之外的潜在招聘渠道（高校/职校人才专栏、新 ATS 等）；
- 严禁平台硬编码黑名单与侵入式反爬；
- 若本轮未发现合格新渠道，如实记录 0 发现，不得伪造。

### 步骤 5：新渠道真实性核验与本地建档
- 对发现的候选渠道核验机构真实性、是否具备活跃第一方招聘专栏及直达 URL；
- 验证通过后由 Agent 签发 `SourceLifecycleDecision(action="discover")` 记录至本地 `.data/sources.json`（标记为 `discovered`，使未来 Run 能够可见该候选源）；
- **严禁自动篡改公共种子库 `config/sources.seed.json`**。

### 步骤 6：第一方公告与附件切片提取 (Acquisition & Extraction)
- 对发现的目标招聘公告，调用 `fetch_and_extract_first_party_announcement` 下载并解析附件表格（`.xlsx`、`.docx`、text-native `.pdf`）；
- 机械切片生成包含原始单元格内容与来源 Provenance 的 `SourceObservation` 列表。

### 步骤 7：高召回候选检索 (Candidate Retrieval)
- 由 Helper `CandidateRetriever` 基于用人单位检索同机构历史 Opportunity 以及同 Run 先前 staged 的实体。

### 步骤 8：Agent 实体消歧裁决 (Entity Resolution)
- Agent 作为唯一语义权威，依据岗位信息研判四态：
  - `same`：同一岗位多渠道观测，合并历史，继承既有意图与市场情报，不重复通知；
  - `update`：历史岗位发布补充公告或延期，记录 Diff 摘要并触发增量重评；
  - `different`：新建独立 Opportunity 实体；
  - `uncertain`：存疑不激进误合并，创建独立实体并建立双向 `uncertain_links`。

### 步骤 9：Agent 多维资格评定 (Eligibility Evaluation)
- 对 `different`、`update`、`uncertain` 岗位严格执行 6 大标准维度评估；
- 逐项给出 5 种标准状态之一，并在 `requirement_evidence` 中**必须引用公告/附件原文证据**（严禁编造伪原文）；
- 聚合输出资格推荐结论（`建议关注` / `需要人工确认` / `明显不符合`）。

### 步骤 10：Agent 机会行动意图裁决 (Opportunity Intent Decision)
- 对 `different`、`update`、`uncertain` 岗位进行独立的行动意图研判：
  - 读取赛道 `default_intent` 作为先验；
  - 结合岗位具体条件（用人单位性质、工作自主权、薪资待遇、排期冲突等）与候选人偏好（`benefit_preferences`, `engagement_preferences`, `compensation_preferences`, `availability_constraints`）；
  - 输出标准意图：`APPLY_NOW` / `CONDITIONAL` / `WATCH_LEARN` 与 `intent_rationale`。

### 步骤 11：Agent 市场情报语义提取 (Market Intelligence Extraction for WATCH_LEARN)
- 若岗位的最终行动意图裁决为 **`WATCH_LEARN`**：
  - Agent 依据第一方公告/附件证据提取 8 大标准市场事实（`brief`, `deliverables`, `content_type`, `timeline_volume`, `revision_quality_rules`, `requested_tools_workflow`, `budget_compensation`, `use_case`）；
  - 未提及事实输出字面量 `UNKNOWN`；
  - 生成 `MarketIntelligence` 事实快照。
- 若意图为 `APPLY_NOW` 或 `CONDITIONAL`，无需执行市场情报提取。

### 步骤 12：Single-Shot 独立文件原子写入 (Persistence)
- 调用 Helper 写入 `.data/opportunities.jsonl`（包含资格结论、行动意图及 WATCH_LEARN 市场情报快照，采用临时文件后重命名替换，保证单文件原子性与不损坏）；
- 调用 Helper 写入本地渠道状态至 `.data/sources.json`（同样采用临时文件重命名原子替换）；
- 校验失败则在写入前 Fail Fast。各状态文件独立维护，不依赖跨文件分布式事务。

### 步骤 13：数据驱动渲染每日简报 (Daily Digest)
- 生成 `reports/YYYY-MM-DD.md`，完整呈现核心板块：
  - 🎯 **资格建议关注 / 新增机会**（清晰展示资格结论与行动意图及理由）
  - 🔭 **WATCH_LEARN / 市场情报观察**（高信噪比呈现 8 项市场事实；缺失项清晰标明 `UNKNOWN`）
  - ⚠️ **需要人工确认**（标注 `【实体同一性待确认】` 与存疑维度）
  - 🔄 **重点岗位动态变更**（直达本次变更的最新 SourceObservation URL）
  - 🌐 **渠道网络变动**（真实数据驱动呈现新发现渠道与降级渠道；若无变动则写“本轮无渠道网络状态变化。”）

### 步骤 14：输出 IDE 对话高信噪比摘要
- 在聊天窗口中为用户呈现巡检总结：实际监控源数量、新发现渠道、新增岗位数（资格建议关注数、待确认数）以及行动意图分布（即刻行动、条件关注、情报观测）。

