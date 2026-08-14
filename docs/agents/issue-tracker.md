# Issue Tracker: GitHub

本项目的 Issues 与需求规范统一托管在 GitHub Issues。所有操作均通过 `gh` CLI 完成。

## 常用操作规范

- **创建 Issue**：`gh issue create --title "..." --body "..."`。多行内容建议使用 heredoc 语法。
- **读取 Issue**：`gh issue view <number> --comments`，配合 `jq` 过滤评论并获取标签信息。
- **列出 Issues**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，可附加 `--label` 与 `--state` 过滤。
- **添加评论**：`gh issue comment <number> --body "..."`
- **添加/移除标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭 Issue**：`gh issue close <number> --comment "..."`

仓库名称由 `git remote -v` 自动推导——在克隆仓库内执行 `gh` 命令时会自动识别。

## Pull Requests 状态分流

**PRs as a request surface: no.** _（若设为 `yes`，表示本项目将外部 PR 作为功能需求请求纳入 `/triage` 流程。）_

当设为 `yes` 时，PR 将通过与 Issue 相同的标签和状态机流转，采用对应的 `gh pr` 命令：

- **读取 PR**：`gh pr view <number> --comments`，使用 `gh pr diff <number>` 查看改动。
- **列出外部待 Triage PR**：`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`，仅保留 `authorAssociation` 为 `CONTRIBUTOR`、`FIRST_TIME_CONTRIBUTOR` 或 `NONE` 的条目（排除 `OWNER` / `MEMBER` / `COLLABORATOR`）。
- **评论 / 标签 / 关闭**：使用 `gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub 在 Issue 与 PR 之间共享编号空间（如 `#42` 可能为 Issue 或 PR）——使用 `gh pr view 42` 判定，若非 PR 则回退至 `gh issue view 42`。

## 当技能指示“发布到 Issue Tracker（publish to the issue tracker）”

创建一个 GitHub Issue。

## 当技能指示“获取关联工单（fetch the relevant ticket）”

运行 `gh issue view <number> --comments`。

## Wayfinder 导航操作

供 `/wayfinder` 技能使用。**Map（全景地图）** 是一个单独的 Issue，而 **Child Tickets（子工单）** 是其子任务。

- **Map（全景地图）**：带有 `wayfinder:map` 标签的单个 Issue，包含 Notes / Decisions-so-far / Fog 等章节。创建方式：`gh issue create --label wayfinder:map`。
- **Child Ticket（子工单）**：作为 Map 的子 Issue 关联（在支持的环境下通过 `gh api` 子任务接口关联；若未启用子任务，则在 Map 正文的任务列表中记录并在子工单正文顶部标注 `Part of #<map>`）。标签使用 `wayfinder:<type>`（即 `research` / `prototype` / `grilling` / `task` 之一）。一旦被认领，该工单将分配给负责的开发者/Agent。
- **Blocking（阻塞依赖）**：使用 GitHub **原生 Issue 依赖关系**作为标准可视化表现。添加依赖关系：`gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`，其中 `<blocker-db-id>` 是阻塞方工单的数字 **Database ID**（通过 `gh api repos/<owner>/<repo>/issues/<n> --jq .id` 获取，_不是_ `#number` 或 `node_id`）。GitHub 汇总报告 `issue_dependencies_summary.blocked_by`（仅计算未解决的阻塞项）。在原生依赖不可用的情况下，降级为在子工单正文顶部注明 `Blocked by: #<n>, #<n>`。当所有阻塞工单关闭时，该工单即解除阻塞。
- **Frontier Query（前沿探索查询）**：查询 Map 下所有未解决的子工单（`gh issue list --state open` 并限定在 Map 的子工单/任务列表范围内），排除存在未解除阻塞项（`issue_dependencies_summary.blocked_by > 0` 或 `Blocked by` 中存在打开的 Issue）或已被认领的工单；按 Map 排序第一项优先。
- **Claim（认领）**：`gh issue edit <n> --add-assignee @me` — 每个会话开始工作时的第一次写入。
- **Resolve（解决）**：`gh issue comment <n> --body "<answer>"`，随后 `gh issue close <n>`，最后在 Map 的 Decisions-so-far 章节追加上下文索引（摘要 + 链接）。
