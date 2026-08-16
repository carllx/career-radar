"""
Focused Seam Tests for Issue #23:
Known-source incremental change detection & 0-Token monitoring.
Respects CONTEXT.md, ADR-0002, Spec #20, Issue #21, #22, and #23.
"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List
import pytest

from career_radar.acquisition import (
    AcquisitionResult,
    SourceAcquisitionExecutor,
    execute_production_acquisition,
)
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


class FakeHttpTransport:
    """Controlled fake HTTP transport returning deterministic canned responses and logging requests."""

    def __init__(self, responses: Dict[str, Dict[str, Any]]):
        self.responses = responses
        self.requests_log: List[Dict[str, Any]] = []

    def get(self, url: str, headers: Any = None, timeout: int = 15, verify: bool = True):
        self.requests_log.append({
            "url": url,
            "headers": dict(headers or {}),
            "timeout": timeout,
            "verify": verify,
        })
        if url in self.responses:
            resp_data = self.responses[url]
            return FakeResponse(
                status_code=resp_data.get("status_code", 200),
                text=resp_data.get("text", ""),
                headers=resp_data.get("headers", {"Content-Type": "text/html; charset=utf-8"}),
                url=url,
                content=resp_data.get("content"),
            )
        return FakeResponse(status_code=404, text="Not Found", headers={}, url=url)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        text: str,
        headers: Dict[str, str],
        url: str,
        content: Any = None,
    ):
        self.status_code = status_code
        self.text = text
        self.headers = headers
        self.url = url
        if content is not None:
            self.content = content
        else:
            self.content = text.encode("utf-8")


def test_etag_conditional_request_304_unchanged_zero_agent_evidence(tmp_path: Path):
    """
    1. Proves ETag conditional request produces If-None-Match header,
       HTTP 304 response records successful MonitoringFact,
       produces 0 Agent evidence packets, and does not fetch detail.
    """
    listing_url = "https://hr.example.edu.cn/jobs"
    transport = FakeHttpTransport({
        listing_url: {
            "status_code": 304,
            "headers": {"ETag": '"abc123etag"', "Content-Type": "text/html"},
            "text": "",
        }
    })

    source = SourceRecord(
        source_id="src_etag_test",
        name="测试高校招聘网",
        base_url=listing_url,
        domain="hr.example.edu.cn",
        metadata={
            "is_listing": True,
            "committed_etag": '"abc123etag"',
            "detail_url_pattern": r"/jobs/\d+",
        },
    )

    out = execute_production_acquisition(
        sources=[source],
        data_dir=tmp_path / ".data",
        transport=transport,
    )

    # 1. Assert If-None-Match header was sent
    assert len(transport.requests_log) == 1
    assert transport.requests_log[0]["headers"].get("If-None-Match") == '"abc123etag"'

    # 2. Assert zero Agent evidence packets
    assert out["agent_evidence_packets"] == []

    # 3. Assert AcquisitionResult facts
    acq_results = out["acquisition_results"]
    assert len(acq_results) == 1
    assert acq_results[0].http_status == 304
    assert acq_results[0].technical_status == "success"
    assert acq_results[0].body_length == 0
    assert acq_results[0].etag == '"abc123etag"'

    # 4. Assert MonitoringFact
    mon_facts = out["monitoring_facts"]
    assert len(mon_facts) == 1
    assert mon_facts[0].technical_status == "success"
    assert mon_facts[0].metadata.get("http_status") == 304
    assert mon_facts[0].metadata.get("unchanged") is True


def test_last_modified_conditional_request_304_behavior(tmp_path: Path):
    """
    2. Proves Last-Modified produces If-Modified-Since header and handles 304 truthfully.
    """
    url = "https://hr.example.edu.cn/announcement/1"
    last_mod_str = "Sun, 16 Aug 2026 08:00:00 GMT"
    transport = FakeHttpTransport({
        url: {
            "status_code": 304,
            "headers": {"Last-Modified": last_mod_str, "Content-Type": "text/html"},
            "text": "",
        }
    })

    source = SourceRecord(
        source_id="src_lastmod_test",
        name="测试直达招聘公告",
        base_url=url,
        domain="hr.example.edu.cn",
        metadata={
            "is_listing": False,
            "committed_last_modified": last_mod_str,
        },
    )

    out = execute_production_acquisition(
        sources=[source],
        data_dir=tmp_path / ".data",
        transport=transport,
    )

    assert len(transport.requests_log) == 1
    assert transport.requests_log[0]["headers"].get("If-Modified-Since") == last_mod_str
    assert out["agent_evidence_packets"] == []
    assert len(out["acquisition_results"]) == 1
    assert out["acquisition_results"][0].http_status == 304
    assert out["monitoring_facts"][0].technical_status == "success"


def test_200_listing_with_identical_fingerprint_skips_detail_and_attachments(tmp_path: Path):
    """
    3. Proves that when HTTP 200 listing is returned with an identical deterministic fingerprint:
       - detail request is NOT fetched;
       - attachments are NOT fetched;
       - agent_evidence_packets is [];
       - successful MonitoringFact is recorded.
    """
    listing_url = "https://hr.example.edu.cn/recruit/list"
    detail_url = "https://hr.example.edu.cn/recruit/detail/101"
    listing_html = f"""<html><body>
    <div class="list">
      <a href="{detail_url}">2026年专任教师招聘启事</a>
      <a href="https://hr.example.edu.cn/news/1">无关新闻通知</a>
    </div>
    </body></html>"""

    transport = FakeHttpTransport({
        listing_url: {"status_code": 200, "text": listing_html},
        detail_url: {"status_code": 200, "text": "<html><body><h1>招聘详情</h1></body></html>"},
    })

    # Pre-compute canonical fingerprint for the matching URL
    # mechanically selected detail_url matching pattern
    expected_fingerprint = hashlib.sha256(
        json.dumps([detail_url], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    source = SourceRecord(
        source_id="src_listing_fp_test",
        name="广东某学院招聘网",
        base_url=listing_url,
        domain="hr.example.edu.cn",
        metadata={
            "is_listing": True,
            "detail_url_pattern": r"/recruit/detail/\d+",
            "committed_listing_fingerprint": expected_fingerprint,
        },
    )

    out = execute_production_acquisition(
        sources=[source],
        data_dir=tmp_path / ".data",
        transport=transport,
    )

    # Proves only listing was requested (1 request total, NO detail request)
    assert len(transport.requests_log) == 1
    assert transport.requests_log[0]["url"] == listing_url
    assert out["agent_evidence_packets"] == []
    assert len(out["acquisition_results"]) == 1
    assert out["acquisition_results"][0].metadata.get("unchanged") is True
    assert out["monitoring_facts"][0].technical_status == "success"
    assert out["monitoring_facts"][0].metadata.get("unchanged") is True


def test_changed_listing_fingerprint_triggers_detail_and_attachment_acquisition(tmp_path: Path):
    """
    4. Proves that when a new announcement URL appears / fingerprint changes:
       - detail acquisition is triggered;
       - attachment acquisition is triggered;
       - agent evidence packet is emitted;
       - newly observed fingerprint is present in metadata.
    """
    listing_url = "https://hr.example.edu.cn/list"
    detail_url = "https://hr.example.edu.cn/post/202"
    att_url = "https://hr.example.edu.cn/files/table.xlsx"

    listing_html = f"""<html><body>
      <a href="{detail_url}">2026年新教师招聘公告</a>
    </body></html>"""
    detail_html = f"""<html><body>
      <h1>2026年新教师招聘公告</h1>
      <a href="{att_url}">岗位明细表.xlsx</a>
    </body></html>"""

    # minimal dummy xlsx header bytes
    xlsx_bytes = b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"\x00" * 40

    transport = FakeHttpTransport({
        listing_url: {"status_code": 200, "text": listing_html},
        detail_url: {"status_code": 200, "text": detail_html},
        att_url: {"status_code": 200, "content": xlsx_bytes, "headers": {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}},
    })

    source = SourceRecord(
        source_id="src_changed_test",
        name="某大学人事处",
        base_url=listing_url,
        domain="hr.example.edu.cn",
        metadata={
            "is_listing": True,
            "detail_url_pattern": r"/post/\d+",
            "committed_listing_fingerprint": "old_outdated_fingerprint_hash",
        },
    )

    out = execute_production_acquisition(
        sources=[source],
        data_dir=tmp_path / ".data",
        transport=transport,
    )

    # 3 requests: listing, detail, attachment
    assert len(transport.requests_log) == 3
    assert transport.requests_log[0]["url"] == listing_url
    assert transport.requests_log[1]["url"] == detail_url
    assert transport.requests_log[2]["url"] == att_url

    # Agent evidence packet emitted
    assert len(out["agent_evidence_packets"]) == 1
    packet = out["agent_evidence_packets"][0]
    assert packet["source_id"] == "src_changed_test"
    assert packet["url"] == detail_url
    assert len(packet["attachments"]) == 1


def test_unprocessed_change_downstream_failure_does_not_advance_baseline(tmp_path: Path):
    """
    5. Critical Invariant (Delta 1):
       When listing fingerprint changes, but downstream detail request returns 500:
       - committed baseline MUST NOT advance;
       - subsequent run still treats the listing as changed and attempts acquisition.
    """
    listing_url = "https://hr.example.edu.cn/jobs"
    detail_url = "https://hr.example.edu.cn/jobs/303"

    listing_html = f"""<html><body>
      <a href="{detail_url}">2026年最新招聘启事</a>
    </body></html>"""

    transport = FakeHttpTransport({
        listing_url: {"status_code": 200, "text": listing_html},
        detail_url: {"status_code": 500, "text": "Internal Server Error"},
    })

    registry = SourceRegistry(
        seed_path=tmp_path / "seed.json",
        data_dir=tmp_path / ".data",
    )

    old_baseline_fp = "old_baseline_fingerprint"
    source = SourceRecord(
        source_id="src_fail_test",
        name="测试高校",
        base_url=listing_url,
        domain="hr.example.edu.cn",
        metadata={
            "is_listing": True,
            "detail_url_pattern": r"/jobs/\d+",
            "committed_listing_fingerprint": old_baseline_fp,
        },
    )
    registry.local_sources[source.source_id] = source
    registry.save_local_state()

    # First run: detail fails (500)
    out1 = execute_production_acquisition(
        sources=[registry.get_source("src_fail_test")],
        data_dir=tmp_path / ".data",
        transport=transport,
    )

    # Assert downstream failed
    assert len(out1["agent_evidence_packets"]) == 0
    detail_res = [r for r in out1["acquisition_results"] if r.requested_url == detail_url][0]
    assert detail_res.technical_status == "failed"
    assert detail_res.http_status == 500

    # Record monitoring fact
    for f in out1["monitoring_facts"]:
        registry.record_monitoring_fact(f)

    # If downstream failed, we do NOT call commit_mechanical_baseline with the new fingerprint!
    # Check registry state: committed_listing_fingerprint remains old_baseline_fp
    saved_src = registry.get_source("src_fail_test")
    assert saved_src.metadata.get("committed_listing_fingerprint") == old_baseline_fp

    # Second run: transport detail is now fixed (200)
    transport.responses[detail_url] = {
        "status_code": 200,
        "text": "<html><body><h1>招聘成功详情</h1></body></html>",
    }
    out2 = execute_production_acquisition(
        sources=[registry.get_source("src_fail_test")],
        data_dir=tmp_path / ".data",
        transport=transport,
    )

    # Second run still classifies as changed and successfully fetches detail!
    assert len(out2["agent_evidence_packets"]) == 1
    assert out2["agent_evidence_packets"][0]["url"] == detail_url


def test_unchanged_monitoring_preserves_historical_persisted_opportunities(tmp_path: Path):
    """
    6. Proves that when an unchanged monitoring run occurs:
       - existing persisted Opportunities in .data/opportunities.jsonl remain intact;
       - DigestReporter continues to report persisted opportunity state without corruption.
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

    # Report generated without error
    report_file = reports_dir / "2026-08-16.md"
    assert report_file.exists()
    report_content = report_file.read_text(encoding="utf-8")
    assert "Career Radar 每日求职情报简报 (2026-08-16)" in report_content


def test_sources_seed_json_remains_unmodified_during_incremental_monitoring(tmp_path: Path):
    """
    7. Proves public seed configuration config/sources.seed.json is strictly read-only,
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
