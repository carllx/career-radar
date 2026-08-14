# CONTEXT.md — Career Radar Domain Model

This document serves as the ubiquitous language and domain definition for `career-radar`.

## Domain Overview

Career Radar is an agent-friendly intelligence system designed to track, filter, and score career opportunities (jobs, projects, open positions) based on user profile criteria, target companies, and search parameters.

## Core Glossary

- **Radar**: The periodic or on-demand scanning mechanism looking for career opportunities.
- **Opportunity / Job Posting**: A specific job opening, role, or contracting gig discovered across sources.
- **Source**: A channel where job listings or announcements appear (e.g. company career pages, job boards, platforms).
- **Candidate Profile / Profile**: User preference and skill definition (stored locally, sanitized of PII in public commits) containing skill tags, target roles, location constraints, and salary expectations.
- **Match Score / Fit Score**: Evaluated alignment between an Opportunity and a Candidate Profile.
- **Application Tracker**: Record of applied, interested, rejected, or interviewing opportunities.

## Architectural Boundaries

- **Local Privacy Layer**: User personal credentials and specific resume text remain local (`profile.local.json`, `.env`).
- **Data Pipeline**: Sources $\rightarrow$ Extraction & Normalization $\rightarrow$ Scoring & Ranking $\rightarrow$ Output / Notification.
