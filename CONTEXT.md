# CONTEXT.md — 领域模型与统一语言词汇表 (Glossary)

本文件是 `career-radar` 项目的统一语言（Ubiquitous Language）定义。所有工单、代码标识符、Prompt 与文档必须严格使用本词汇表中的术语。

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
Agent 对某个适用维度进行语义推演后的证据完备度与合规度评价，仅允许取五态之一：
- `PASS`：已有充分证据确认满足；
- `REVIEW`：已有证据，但存在放宽条款、歧义或需要人工进一步判断；
- `FAIL`：已有权威证据确认不满足硬性门槛且无适用放宽；
- `UNKNOWN`：信息重要但当前证据不足（触发 Agent 进一步自主查证，查证未果保留 UNKNOWN）；
- `N/A`：该维度对当前岗位类型不适用。

### Eligibility（资格合规性）
候选人与岗位硬性法定准入条件的符合程度（涵盖 `Age`、`Education`、`Formal Qualification` 等）。

### Formal Qualification（正式专业资格）
依据招聘公告指定的正式专业目录、专业代码或学科分类标准所界定的法定专业准入门槛。

### Capability Fit（能力与课程契合度）
候选人实际掌握的专业能力、技术栈与教学经验，与岗位所要求的课程讲授能力或岗位职责的实际契合程度。

### Hard Blocker（硬性门槛阻断）
在具备充分第一方证据的前提下，某一硬性维度求值为 `FAIL` 时的全局熔断状态，导致该岗位直接判定为 `明显不符合`。

### Final Recommendation（最终推荐结论）
Agent 综合各维度证据状态输出的最终三态决策：
- `建议关注`：无 `FAIL`、无 `REVIEW`，核心维度 `PASS`；
- `需要人工确认`：无 `FAIL`，但存在 `REVIEW` 或补查后仍保留 `UNKNOWN`；
- `明显不符合`：命中至少一项权威第一方确认的 `Hard Blocker`。
