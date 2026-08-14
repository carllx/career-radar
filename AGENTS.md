# AGENTS.md — Career Radar

本文件是 AI Agent（包括 Antigravity、Codex 及各类辅助 Agent）在本项目中工作的最高层指令与操作准则。

## 1. 项目概览

- **项目名称**：`career-radar`
- **代码仓库**：[carllx/career-radar](https://github.com/carllx/career-radar)
- **当前阶段**：项目启动与规划（Bootstrap / Planning）
- **项目范围**：单一 Context（Single-context）的自主职业雷达与求职情报追踪系统。

## 2. 核心安全与隐私红线

> [!CAUTION]
> 本项目为 **公开开源仓库（Public Repository）**。以下规则必须严格遵守，绝无例外：
> - **零凭据泄露（Zero Secrets）**：严禁提交任何 API Key、Token、私钥、证书或未脱敏的 `.env` 文件。所有敏感配置必须通过环境变量或被 `.gitignore` 忽略的本地配置文件注入。
> - **零个人隐私泄露（Zero PII）**：严禁提交个人真实姓名、完整简历、电话号码、私人邮箱、身份证件、家庭住址或私人申请文书。
> - **Git 提交身份匿名化（Noreply Email）**：本 public repository 的 Git commits 严禁使用真实私人邮箱，提交前必须配置并使用 GitHub noreply email（如 `4390475+carllx@users.noreply.github.com`）。Agent 在新环境或新电脑第一次提交前应检查 `git user.email` 确保不泄露真实私人邮箱。
> - **仅允许模板与示例**：如果需要配置或数据结构示例，仅允许提交经过脱敏的 `*.example.*` 模板。真实的个人数据存放在 `profile.local.*` 等本地忽略文件中。

## 3. 开发协作与行为规范

### 3.1 中文优先

- **交互语言**：Agent 与用户的所有交互、讨论与汇报默认使用中文。
- **文档与工单**：项目文档、Issue、PR 描述、研究总结、进度报告、Git Commit 提交信息默认使用中文。
- **专有名词**：源代码标识符（变量/函数/类名）、API 字段、CLI 命令、GitHub Canonical Labels、第三方产品和协议正式名称保持原文，不作强制翻译。

### 3.2 单文件大小限制

- **行数上限**：所有人工维护的源码、脚本和 Markdown 文档单文件不得超过 **500 行**。
- **拆分预警**：单文件行数接近 **450 行** 时，Agent 应主动评估模块职责并进行合理拆分。
- **防过度拆分**：严禁为了迎合行数限制而进行碎片化、破坏内聚性的无意义拆分。
- **豁免范围**：自动生成的代码、Lock 文件、第三方依赖库（Vendored code）、机器生成的数据不受此限制。

### 3.3 外部网络探索与调研规范

- **研究工具**：在 Wayfinder 决策、事实核验、技术调研或平台检索时，优先使用已安装的 `agent-reach` 能力。
- **第一方核实**：网络调研获取的信息，必须尽量回到官方文档或第一方权威来源进行交叉验证。
- **环境隔离**：`agent-reach` 目前是 IDE Agent 的探索与研究工具，**不得预设其为 `career-radar` 产品的运行时依赖**。
- **依赖决策**：产品实际运行时所需的抓取、搜索、数据管道技术（如是否采用 Firecrawl、Tavily、Brave、原生 HTTP、Headless Browser 等），必须在后续规划阶段通过 Wayfinder 明确讨论并决策。

### 3.4 Planning Gate（规划闸门）

- **严禁提前实现**：当前仍处于 Bootstrap / Planning 阶段。在完成 `Wayfinder → Spec → Tickets` 完整链路并获得确认前，不得编写任何 Career Radar 的具体产品业务代码（如爬虫、解析器、搜索器、调度器、CI/CD Actions 等）。
- **领域文档懒创建（Lazy Creation）**：遵循 Matt Pocock Domain Modeling 规范，`CONTEXT.md` 与 `docs/adr/` 不提前创建占位或虚构设计，仅在相关概念或架构决策经过推演确认后逐步生成。

## 4. Agent skills

### Issue tracker

使用 GitHub Issues（`carllx/career-radar`）。参见 [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md)。

### Triage labels

使用规范的 5 种默认 Triage 标签（`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`）。参见 [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md)。

### Domain docs

采用单一 Context 布局（`CONTEXT.md` + `docs/adr/`）。参见 [`docs/agents/domain.md`](docs/agents/domain.md)。
