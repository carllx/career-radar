"""
Historical Opportunity and Public Seed Invariant Tests for Issue #23.
Respects CONTEXT.md, ADR-0002, Spec #20, and AGENTS.md single-file line limits.
"""

import json
from pathlib import Path
from typing import Any, Dict, List
import pytest

from career_radar.models import (
    CandidateProfile,
    EvaluationResult,
    Opportunity,
    SourceObservation,
)
from career_radar.orchestrator import RadarOrchestrator
from career_radar.reporter import DigestReporter
from career_radar.sources import MonitoringFact, SourceRecord, SourceRegistry
from career_radar.store import OpportunityStore


def test_unchanged_monitoring_preserves_historical_persisted_opportunities(tmp_path: Path):
    """
    Proves that when an unchanged monitoring run occurs:
    - existing persisted Opportunities in .data/opportunities.jsonl remain intact;
    - DigestReporter continues to report persisted opportunity state without corruption;
    - persisted historical opportunity title appears in generated report.
    """
    data_dir = tmp_path / ".data"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    opp_store = OpportunityStore(data_dir=data_dir)
    obs = SourceObservation(
        observation_id="obs_001",
        announcement_id="ann_001",
        source_id="src_unchanged_daily",
        source_name="测试高校",
        announcement_title="2026年专任教师招聘",
        job_title="计算机专业专任教师",
        organization="广东岭南职业技术学院",
        location="广州",
        track="higher_education_teaching",
        official_url="https://hr.example.edu.cn/jobs/100",
        observed_at="2026-08-15T00:00:00",
        extracted_requirements={},
    )
    eval_res = EvaluationResult(
        final_recommendation="建议关注",
        dimension_evaluations={},
        evaluated_at="2026-08-15T00:00:00",
    )
    hist_opp = Opportunity(
        opportunity_id="opp_historical_001",
        canonical_job_title="计算机专业专任教师",
        organization="广东岭南职业技术学院",
        location="广州",
        track="higher_education_teaching",
        official_url="https://hr.example.edu.cn/jobs/100",
        lifecycle_status="active",
        observations=[obs],
        latest_evaluation=eval_res,
        created_at="2026-08-15T00:00:00",
        updated_at="2026-08-15T00:00:00",
        opportunity_intent="APPLY_NOW",
        intent_rationale="与候选人背景高度匹配",
    )
    opp_store.save_opportunities([hist_opp])

    # Setup seed source in tmp directory
    seed_file = tmp_path / "sources.seed.json"
    seed_file.write_text(json.dumps([
        {
            "source_id": "src_unchanged_daily",
            "name": "测试高校",
            "base_url": "https://hr.example.edu.cn/jobs",
            "domain": "hr.example.edu.cn",
        }
    ], ensure_ascii=False), encoding="utf-8")

    # Execute orchestrator run with ZERO incoming observations (simulating unchanged sources)
    orchestrator = RadarOrchestrator(
        profile_path="config/profile.example.yaml",
        seed_sources_path=seed_file,
        data_dir=data_dir,
        reports_dir=reports_dir,
    )

    fact = MonitoringFact(
        source_id="src_unchanged_daily",
        technical_status="success",
        checked_url="https://hr.example.edu.cn/jobs",
        metadata={"unchanged": True},
    )

    outcome = orchestrator.run(
        observations=[],
        monitoring_facts=[fact],
        run_date="2026-08-16",
    )

    # Opportunity is preserved in store
    reloaded_opps = opp_store.load_all_opportunities()
    assert len(reloaded_opps) == 1
    assert reloaded_opps[0].opportunity_id == "opp_historical_001"
    assert reloaded_opps[0].canonical_job_title == "计算机专业专任教师"

    # Report generated without error (truthfully reporting 0 new opportunities)
    report_file = reports_dir / "2026-08-16.md"
    assert report_file.exists()
    report_content = report_file.read_text(encoding="utf-8")
    assert "Career Radar 每日求职情报简报 (2026-08-16)" in report_content
    assert "本次巡检未发现新增高匹配度机会。" in report_content

    # Proves DigestReporter direct rendering of historical opportunities includes title
    reporter = DigestReporter(reports_dir)
    direct_report_path = reporter.generate_report(reloaded_opps, run_date="2026-08-16-full")
    assert direct_report_path.exists()
    direct_content = direct_report_path.read_text(encoding="utf-8")
    assert "计算机专业专任教师" in direct_content
    assert "广东岭南职业技术学院" in direct_content


def test_sources_seed_json_remains_unmodified_during_incremental_monitoring(tmp_path: Path):
    """
    Proves public seed configuration config/sources.seed.json is strictly read-only,
    while local runtime state in .data/sources.json updates.
    """
    seed_file = tmp_path / "sources.seed.json"
    seed_content = json.dumps([
        {
            "source_id": "seed_src_01",
            "name": "种子招聘源",
            "base_url": "https://hr.example.edu.cn/list",
            "domain": "hr.example.edu.cn",
        }
    ], ensure_ascii=False, indent=2)
    seed_file.write_text(seed_content, encoding="utf-8")

    registry = SourceRegistry(seed_path=seed_file, data_dir=tmp_path / ".data")
    registry.commit_mechanical_baseline(
        source_id="seed_src_01",
        listing_fingerprint="new_sha256_fp",
        etag='"etag_val"',
    )
    registry.save_local_state()

    # Seed file content remains identical
    assert seed_file.read_text(encoding="utf-8") == seed_content

    # Local state holds the committed metadata
    local_state_file = tmp_path / ".data" / "sources.json"
    assert local_state_file.exists()
    local_data = json.loads(local_state_file.read_text(encoding="utf-8"))
    assert len(local_data) == 1
    assert local_data[0]["metadata"]["committed_listing_fingerprint"] == "new_sha256_fp"
    assert local_data[0]["metadata"]["committed_etag"] == '"etag_val"'



