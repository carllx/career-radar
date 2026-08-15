# 3. MVP-1 最小数据模型、实体关系与 Agent 驱动消歧协议

日期: 2026-08-15

## 状态

已通过 (Accepted)

## 上下文与问题陈述

在 Career Radar MVP-1 运行中，招聘信息通常具有以下特征：
1. **一公告多岗位**：一份高校公招公告或附件表格中可能包含数十个不同院系的专任教师岗位；
2. **多渠道多观测**：同一所高校的同一个职位往往同时出现在该校人事处官网、省人社厅报名系统以及高校人才网等多个聚合平台；
3. **动态增量变更**：同一岗位在发布后可能发生报名延期、专业条件放宽或附件修订等补充通知；
4. **机械规则局限**：基于字符串相似度或关键词哈希的机械去重极易误杀相似岗位（如“专任教师A岗”与“专任教师B岗”）或漏识别换标题的同质岗位。

为确保系统在 MVP-1 阶段能够安全、高精度地跟踪机会并保持证据溯源，需要确立最小数据模型架构与 Agent 实体消歧协议。

## 决策

我们决定确立 **三层实体关联模型（Announcement → SourceObservation → Opportunity）与 Agent 裁决实体消歧**：

### 1. 核心实体三层关系

1. **`Announcement`（招聘公告）**：
   - 记录抓取/检索到的原始公告维度（`announcement_id`, `source_id`, `url`, `title`, `published_at`, `raw_content`, `content_hash` 等）。
2. **`SourceObservation`（来源观测切片）**：
   - 从公告中提取的具体岗位观察片段（`observation_id`, `announcement_id`, `raw_job_title`, `organization`, `extracted_requirements`, `observed_at` 等）；
   - 承担 Requirement Evidence 的来源锚点，保证最终报告每一条资格判断均可追溯至具体的公告切片。
3. **`Opportunity`（具体岗位机会 - Canonical Entity）**：
   - 业务核心实体，聚合一个或多个跨平台/跨时间的 `SourceObservation`；
   - 记录规范化职位名称、用人单位、赛道、地点、生命周期状态（`active` / `updated` / `closed`）及最新的 Agent 离散多维匹配判定结果（`latest_evaluation`）。

### 2. 候选检索与 Agent 实体消歧协议

1. **确定性检索层（Helper Candidate Retrieval）**：
   - 仅负责基于机构名称、职位关键词、发布时间窗口等确定性特征从本地历史中检索 Top-N 可能相关的 Opportunity 候选集；
   - 严禁编码任何类似“相似度 > X% 自动判定为同岗位”的业务规则。
2. **Agent 语义实体消歧（Entity Resolution）**：
   - Agent 综合岗位职责、编制性质、院系机构、任职要求及全量证据上下文，对新观测与候选集输出四态决策：
     - `same`：确认同一岗位重复发布，直接将当前 Observation 追加至既有 Opportunity，不产生重复通知；
     - `update`：确认既有岗位的补充/变更（如延期、放宽），记录 Diff 并触发增量重评，在简报中标记为岗位更新；
     - `different`：确认为独立职位，新建全新 Opportunity；
     - `uncertain`：证据不足时遵循“不激进合并”原则，创建独立记录并保留双向软关联，等待后续证据演进。

### 3. 本地轻量持久化与零泄露契约

- 状态以结构化本地数据文件（如 JSON Lines 或轻量 SQLite）保存在本地被 `.gitignore` 忽略的数据目录；
- 严禁将任何包含真实个人信息（PII）或敏感路径的数据提交至公共仓库。

## 后果与权衡

### 积极影响
- **数据结构清晰可追溯**：一公告多岗位与多渠道同一岗位得到清晰建模，每个证据均有精确来源回溯；
- **杜绝机械误杀**：彻底避免传统爬虫用标题相似度去重导致的岗位误合并；
- **状态支持增量运行**：Agent 运行后持久化实体关系，后续运行无需从零比对。

### 潜在代价
- 实体消歧依赖 Agent 语义推理，当候选集较大时会消耗一定的模型上下文与推演资源（通过 Helper 进行合理的粗粒度候选初检索加以平衡）。
