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


def test_multi_url_matching_process_restart_and_incremental_diff(tmp_path: Path):
    """
    Proves multi-match listing with process restarts:
    RUN 1: Listing with [A] -> A acquired, committed baseline = [A].
    RUN 2 (Restart): Listing with [A, B] -> ONLY B acquired (not A again).
    RUN 3 (Restart): Listing with [A, B] unchanged -> 0 HTTP detail requests, 0 agent evidence.
    """
    from career_radar.acquisition import execute_production_acquisition

    class Transport:
        def __init__(self):
            self.responses = {}
            self.requested_urls = []

        def get(self, url: str, headers: Any = None, timeout: int = 15, verify: bool = True):
            self.requested_urls.append(url)
            if url in self.responses:
                d = self.responses[url]
                from career_radar.acquisition_models import AcquisitionResult
                class Resp:
                    def __init__(self, status, text, headers):
                        self.status_code = status
                        self.text = text
                        self.headers = headers
                        self.url = url
                        self.content = text.encode("utf-8")
                return Resp(d.get("status_code", 200), d.get("text", ""), d.get("headers", {}))
            class Resp404:
                status_code = 404
                text = "Not Found"
                headers = {}
                url = url
                content = b""
            return Resp404()

    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    seed_file = tmp_path / "sources.seed.json"
    seed_file.write_text(json.dumps([
        {
            "source_id": "src_multi_match",
            "name": "高校招聘多条目源",
            "base_url": "https://hr.example.edu.cn/jobs",
            "domain": "hr.example.edu.cn",
            "metadata": {
                "is_listing": True,
                "detail_url_pattern": r"/jobs/\d+",
            }
        }
    ]), encoding="utf-8")

    # RUN 1: Listing contains only announcement A (/jobs/101)
    t1 = Transport()
    t1.responses = {
        "https://hr.example.edu.cn/jobs": {
            "status_code": 200,
            "text": '<html><body><a href="/jobs/101">计算机教师招聘</a></body></html>',
        },
        "https://hr.example.edu.cn/jobs/101": {
            "status_code": 200,
            "text": '<html><head><title>计算机教师招聘</title></head><body><h1>岗位要求</h1><p>硕士及以上学历</p></body></html>',
        },
    }
    r1 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t1)
    assert len(r1["agent_evidence_packets"]) == 1
    assert r1["agent_evidence_packets"][0]["url"] == "https://hr.example.edu.cn/jobs/101"
    assert "https://hr.example.edu.cn/jobs/101" in t1.requested_urls

    # Verify baseline in local state
    reg1 = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    s1 = reg1.get_source("src_multi_match")
    assert s1.metadata["committed_listing_urls"] == ["https://hr.example.edu.cn/jobs/101"]

    # RUN 2 (Fresh process restart): Listing now contains [A (/jobs/101), B (/jobs/102)]
    t2 = Transport()
    t2.responses = {
        "https://hr.example.edu.cn/jobs": {
            "status_code": 200,
            "text": '<html><body><a href="/jobs/101">计算机教师招聘</a><a href="/jobs/102">数学教师招聘</a></body></html>',
        },
        "https://hr.example.edu.cn/jobs/102": {
            "status_code": 200,
            "text": '<html><head><title>数学教师招聘</title></head><body><h1>岗位要求</h1><p>数学专业</p></body></html>',
        },
    }
    r2 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t2)
    # MUST only fetch B, not A!
    assert "https://hr.example.edu.cn/jobs/101" not in t2.requested_urls
    assert "https://hr.example.edu.cn/jobs/102" in t2.requested_urls
    assert len(r2["agent_evidence_packets"]) == 1
    assert r2["agent_evidence_packets"][0]["url"] == "https://hr.example.edu.cn/jobs/102"

    # RUN 3 (Fresh process restart): Listing still [A, B] -> Unchanged
    t3 = Transport()
    t3.responses = {
        "https://hr.example.edu.cn/jobs": {
            "status_code": 200,
            "text": '<html><body><a href="/jobs/101">计算机教师招聘</a><a href="/jobs/102">数学教师招聘</a></body></html>',
        }
    }
    r3 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t3)
    assert len(r3["agent_evidence_packets"]) == 0
    assert len(t3.requested_urls) == 1  # Only listing request, 0 detail requests


def test_multi_url_partial_failure_does_not_advance_baseline_and_retries(tmp_path: Path):
    """
    Proves partial failure invariant:
    Listing has [A, B, C]. A succeeds, B succeeds, C fails HTTP 500.
    Full baseline MUST NOT be committed.
    Next run retries and succeeds when C recovers.
    """
    from career_radar.acquisition import execute_production_acquisition

    class Transport:
        def __init__(self):
            self.responses = {}
            self.requested_urls = []

        def get(self, url: str, headers: Any = None, timeout: int = 15, verify: bool = True):
            self.requested_urls.append(url)
            d = self.responses.get(url, {"status_code": 404, "text": "Not Found", "headers": {}})
            class Resp:
                def __init__(self, status, text, headers):
                    self.status_code = status
                    self.text = text
                    self.headers = headers
                    self.url = url
                    self.content = text.encode("utf-8")
            return Resp(d.get("status_code", 200), d.get("text", ""), d.get("headers", {}))

    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    seed_file = tmp_path / "sources.seed.json"
    seed_file.write_text(json.dumps([
        {
            "source_id": "src_partial_fail",
            "name": "部分失败源",
            "base_url": "https://hr.example.edu.cn/jobs",
            "domain": "hr.example.edu.cn",
            "metadata": {
                "is_listing": True,
                "detail_url_pattern": r"/jobs/\d+",
            }
        }
    ]), encoding="utf-8")

    # RUN 1: A (/jobs/101) is already committed
    reg = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    reg.commit_mechanical_baseline(
        source_id="src_partial_fail",
        listing_urls=["https://hr.example.edu.cn/jobs/101"],
        listing_fingerprint="fp_only_101",
    )
    reg.save_local_state()

    # RUN 2: Listing now contains [101, 102, 103]. 102 succeeds (200), 103 fails (500).
    t2 = Transport()
    t2.responses = {
        "https://hr.example.edu.cn/jobs": {
            "status_code": 200,
            "text": '<html><body><a href="/jobs/101">岗位1</a><a href="/jobs/102">岗位2</a><a href="/jobs/103">岗位3</a></body></html>',
        },
        "https://hr.example.edu.cn/jobs/102": {
            "status_code": 200,
            "text": '<html><head><title>岗位2</title></head><body><h1>岗位2要求</h1></body></html>',
        },
        "https://hr.example.edu.cn/jobs/103": {
            "status_code": 500,
            "text": 'Server Error',
        },
    }
    r2 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t2)
    # Session monitoring fact is failed
    assert r2["session_results"][0].monitoring_fact.technical_status == "failed"

    # Baseline MUST NOT advance to the full [101, 102, 103]
    reg2 = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    s2 = reg2.get_source("src_partial_fail")
    assert s2.metadata.get("committed_listing_urls") == ["https://hr.example.edu.cn/jobs/101"]

    # RUN 3: C recovers (200)
    t3 = Transport()
    t3.responses = {
        "https://hr.example.edu.cn/jobs": {
            "status_code": 200,
            "text": '<html><body><a href="/jobs/101">岗位1</a><a href="/jobs/102">岗位2</a><a href="/jobs/103">岗位3</a></body></html>',
        },
        "https://hr.example.edu.cn/jobs/102": {
            "status_code": 200,
            "text": '<html><head><title>岗位2</title></head><body><h1>岗位2要求</h1></body></html>',
        },
        "https://hr.example.edu.cn/jobs/103": {
            "status_code": 200,
            "text": '<html><head><title>岗位3</title></head><body><h1>岗位3要求</h1></body></html>',
        },
    }
    r3 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t3)
    assert r3["session_results"][0].monitoring_fact.technical_status == "success"

    # Now full baseline is committed
    reg3 = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    s3 = reg3.get_source("src_partial_fail")
    assert s3.metadata.get("committed_listing_urls") == [
        "https://hr.example.edu.cn/jobs/101",
        "https://hr.example.edu.cn/jobs/102",
        "https://hr.example.edu.cn/jobs/103",
    ]


def test_removal_only_listing_change_commits_baseline_without_fake_agent_evidence(tmp_path: Path):
    """
    Proves removal-only change:
    Prior committed URLs = [A, B].
    Current listing contains only [A].
    No new URLs to acquire -> 0 HTTP detail requests, 0 fake Agent evidence packets.
    New baseline [A] is committed safely.
    """
    from career_radar.acquisition import execute_production_acquisition

    class Transport:
        def __init__(self):
            self.responses = {}
            self.requested_urls = []

        def get(self, url: str, headers: Any = None, timeout: int = 15, verify: bool = True):
            self.requested_urls.append(url)
            d = self.responses.get(url, {"status_code": 404, "text": "Not Found", "headers": {}})
            class Resp:
                def __init__(self, status, text, headers):
                    self.status_code = status
                    self.text = text
                    self.headers = headers
                    self.url = url
                    self.content = text.encode("utf-8")
            return Resp(d.get("status_code", 200), d.get("text", ""), d.get("headers", {}))

    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    seed_file = tmp_path / "sources.seed.json"
    seed_file.write_text(json.dumps([
        {
            "source_id": "src_removal",
            "name": "删除条目源",
            "base_url": "https://hr.example.edu.cn/jobs",
            "domain": "hr.example.edu.cn",
            "metadata": {
                "is_listing": True,
                "detail_url_pattern": r"/jobs/\d+",
            }
        }
    ]), encoding="utf-8")

    # Prior state has [A, B] committed
    reg = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    reg.commit_mechanical_baseline(
        source_id="src_removal",
        listing_urls=["https://hr.example.edu.cn/jobs/101", "https://hr.example.edu.cn/jobs/102"],
        listing_fingerprint="fp_101_102",
    )
    reg.save_local_state()

    # Current listing only has [A (/jobs/101)]
    t = Transport()
    t.responses = {
        "https://hr.example.edu.cn/jobs": {
            "status_code": 200,
            "text": '<html><body><a href="/jobs/101">岗位1</a></body></html>',
        }
    }
    r = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t)
    assert len(r["agent_evidence_packets"]) == 0
    assert len(t.requested_urls) == 1  # Only listing requested

    # Baseline advances to [A]
    reg2 = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    s2 = reg2.get_source("src_removal")
    assert s2.metadata.get("committed_listing_urls") == ["https://hr.example.edu.cn/jobs/101"]


