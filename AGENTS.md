# AGENTS.md — Career Radar

Guidelines and operational configuration for AI agents working in this repository.

## Project Overview

- **Name**: `career-radar`
- **Repository**: [carllx/career-radar](https://github.com/carllx/career-radar)
- **Phase**: Bootstrap / Planning
- **Scope**: Single-context repository for autonomous job tracking and career radar intelligence.

## Security & Privacy Guardrails

> [!CAUTION]
> This is a **PUBLIC** repository. The following rules are strictly enforced:
> - **Zero Secrets**: Never commit API keys, tokens, or private credentials. All secret values must be read from environment variables or ignored `.env` files.
> - **Zero Personally Identifiable Information (PII)**: Never commit real resumes, CVs, phone numbers, personal email addresses, national IDs, or private application documents.
> - **Profile Templates Only**: Use `profile.example.json` or `.env.example` as schemas/templates. Real personal data belongs in `profile.local.*` which is git-ignored.

## Agent skills

### Issue tracker

GitHub Issues on `carllx/career-radar`. See [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).

### Triage labels

Default canonical triage roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).

### Domain docs

Single-context repository layout (`CONTEXT.md` + `docs/adr/`). See [`docs/agents/domain.md`](docs/agents/domain.md).

## Development Conventions

- Do not implement product code until the planning/spec phase is approved.
- Use ADRs in `docs/adr/` for significant architecture and design decisions.
- Maintain ubiquitous domain vocabulary in `CONTEXT.md`.
