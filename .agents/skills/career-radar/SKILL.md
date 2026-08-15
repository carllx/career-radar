---
name: career-radar
description: "Executes an end-to-end Autonomous Career Radar run. Orchestrates known-source monitoring, open source discovery, first-party announcement extraction, agent entity resolution, multi-dimensional qualification matching, atomic persistence, and daily digest generation."
---

# Career Radar — Autonomous Daily Radar Orchestration Skill

Use this skill when running Career Radar daily monitoring, exploring new recruitment channels, evaluating incoming job announcements, or triggered by an IDE schedule / manual command.

## Orchestration Workflow

An autonomous Career Radar run consists of 8 sequential steps:

### 1. Load Configurations and State
- Profile: Load private `profile.local.yaml` (fallback to `config/profile.example.yaml`).
- Public Source Registry: Load `config/sources.seed.json` (Read-only SSOT).
- Local Source State: Load `.data/sources.json` (runtime discoveries and lifecycle health).
- Opportunity History: Load `.data/opportunities.jsonl`.

### 2. Known-Source Monitoring
- Select a bounded monitoring set from active seed and local sources matching candidate tracks/regions.
- Check target endpoints (e.g. HRSS portals, university personnel bulletin boards).
- Record mechanical technical results (`success`, `blocked_by_captcha`, `failed`).

### 3. Source Discovery (Open Exploration)
- Use available environment capabilities (e.g. `agent-reach`, browser, search) to discover candidate recruitment channels not yet in seed.
- Verify basic channel authenticity (institution legitimacy, active job bulletin, direct URL).
- If validated, record as `discovered` in `.data/sources.json` via `SourceLifecycleDecision(action="discover")`. Never auto-mutate `config/sources.seed.json`.

### 4. Acquisition & Extraction
- Fetch target announcements and attachment tables (`.xlsx`, `.docx`, text-native `.pdf`) using `fetch_and_extract_first_party_announcement`.
- Slice tables into concrete `SourceObservation`s with verbatim cell contents and provenance.

### 5. Agent Entity Resolution
- Candidate retrieval: Helper retrieves prior and same-run working opportunities matching the recruiting institution.
- Agent semantic arbitration: Classify observation into one of four states:
  - `same`: merges observation history, no duplicate Opportunity.
  - `update`: updates opportunity info, records change diff, triggers re-evaluation.
  - `different`: creates new independent Opportunity.
  - `uncertain`: creates independent Opportunity with bidirectional soft links (`uncertain_links`).

### 6. Qualification Matching (6 Canonical Dimensions)
- Evaluate each `different`, `update`, and `uncertain` opportunity across 6 dimensions:
  1. `degree` (学历层次与全日制要求)
  2. `major` (学科专业代码与名称)
  3. `age` (年龄硬性上限与基准日)
  4. `location` (用人单位属地与通勤偏好)
  5. `track` (招聘赛道匹配度)
  6. `hard_exclusions` (定向生/失信/处分等一票否决)
- Assign discrete states (`PASS`, `FAIL`, `UNCERTAIN`, `INFO_MISSING`) and quote verbatim Requirement Evidence.

### 7. Atomic Persistence
- Persist opportunities to `.data/opportunities.jsonl` in a single-shot transaction.
- Persist runtime sources to `.data/sources.json`.

### 8. Delivery & In-Chat Summary
- Render `reports/YYYY-MM-DD.md` with 4 data-driven sections:
  - 🎯 **强烈推荐 / 新增高价值机会**
  - 🔄 **重点岗位动态变更** (with evidence URLs)
  - ⚠️ **需要人工确认** (with uncertain badges)
  - 🌐 **渠道网络变动** (newly discovered & degraded channels)
- Output concise summary to the user.
