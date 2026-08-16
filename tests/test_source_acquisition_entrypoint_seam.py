"""
Production Acquisition Entrypoint Seam Tests for Issue #21.
Tests verify external behavior of execute_production_acquisition and SourceAcquisitionExecutor:
1. Primary test exercises execute_production_acquisition directly:
   SourceRecord + Fake HTTP transport -> AcquisitionResult + derived MonitoringFact
   + persisted raw HTML evidence + compact Agent-facing evidence packet (reusing HTMLAnnouncementParser).
2. Structural prevention: production entrypoint does not accept caller-supplied MonitoringFact/SourceObservation,
   and every derived MonitoringFact maintains traceable lineage to its AcquisitionResult.
3. Failed technical acquisitions (404/500/timeout) produce truthful failure facts in AcquisitionResult
   and MonitoringFact, but are strictly excluded from normal Agent content evidence packets.
4. Regression test: Parser failure after successful HTTP 200 preserves real network facts, retains raw evidence,
   records parsing failure facts, and excludes from Agent content evidence.
"""

from datetime import datetime
from pathlib import Path
import pytest
from typing import Any, Dict
from unittest.mock import patch

from career_radar.acquisition import (
    AcquisitionResult,
    SourceAcquisitionExecutor,
    execute_production_acquisition,
)
from career_radar.parser import HTMLAnnouncementParser
from career_radar.sources import MonitoringFact, SourceRecord


class FakeHttpTransport:
    """Controlled fake HTTP transport returning deterministic canned responses."""

    def __init__(self, responses: Dict[str, Dict[str, Any]]):
        self.responses = responses
        self.requests_log = []

    def get(self, url: str, headers: Any = None, timeout: int = 15, verify: bool = True):
        self.requests_log.append({
            "url": url,
            "headers": headers,
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

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code} Error")


SAMPLE_HTML_WITH_TABLE = """<!DOCTYPE html>
<html>
<head><title>广东某学院2026年高层次与专任教师招聘启事</title></head>
<body>
  <h1>广东某学院2026年高层次与专任教师招聘启事</h1>
  <p>为满足教学科研需要，现面向社会公开招聘专任教师。</p>
  <table border="1">
    <thead>
      <tr><th>岗位名称</th><th>招聘人数</th><th>专业要求</th><th>学历学位</th></tr>
    </thead>
    <tbody>
      <tr><td>计算机专任教师</td><td>2</td><td>0812 计算机科学与技术</td><td>硕士研究生及以上</td></tr>
      <tr><td>数字媒体艺术专任教师</td><td>1</td><td>1305 设计学 / 数字媒体</td><td>硕士研究生及以上</td></tr>
    </tbody>
  </table>
</body>
</html>
"""


def test_production_acquisition_entrypoint_static_html_table_or_body(tmp_path: Path):
    """
    Finding 1 & 2: Primary successful test exercises execute_production_acquisition directly:
    SourceRecord -> controlled HTTP acquisition -> AcquisitionResult -> derived MonitoringFact
    -> persisted raw evidence -> compact Agent-facing packet (via HTMLAnnouncementParser).
    """
    target_url = "https://www.sample-college.edu.cn/rsc/zp2026.html"
    transport = FakeHttpTransport(
        responses={
            target_url: {
                "status_code": 200,
                "text": SAMPLE_HTML_WITH_TABLE,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
            }
        }
    )

    source = SourceRecord(
        source_id="sample_college_hr",
        name="广东某学院人事处",
        base_url=target_url,
        domain="sample-college.edu.cn",
        source_type="first_party_institution",
        track=["higher_education_teaching"],
        region="guangzhou",
        metadata={"archetype": "static_html_table_or_body"},
    )

    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Primary entrypoint call
    output = execute_production_acquisition(
        sources=[source],
        data_dir=data_dir,
        transport=transport,
    )

    # 1. Verify transport invocation
    assert len(transport.requests_log) == 1
    assert transport.requests_log[0]["url"] == target_url

    # 2. Verify AcquisitionResult
    assert len(output["acquisition_results"]) == 1
    acq_res = output["acquisition_results"][0]
    assert isinstance(acq_res, AcquisitionResult)
    assert acq_res.source_id == "sample_college_hr"
    assert acq_res.requested_url == target_url
    assert acq_res.final_url == target_url
    assert acq_res.technical_status == "success"
    assert acq_res.http_status == 200
    assert "text/html" in acq_res.content_type
    assert acq_res.body_length == len(SAMPLE_HTML_WITH_TABLE.encode("utf-8"))
    assert len(acq_res.response_hash) == 64
    assert acq_res.acquisition_method == "native_http_get"
    assert acq_res.attempt_id.startswith("acq_")

    # 3. Verify derived MonitoringFact & Lineage
    assert len(output["monitoring_facts"]) == 1
    fact = output["monitoring_facts"][0]
    assert isinstance(fact, MonitoringFact)
    assert fact.source_id == "sample_college_hr"
    assert fact.technical_status == "success"
    assert fact.checked_url == target_url
    assert fact.checked_at == acq_res.timestamp
    assert fact.metadata["attempt_id"] == acq_res.attempt_id
    assert fact.metadata["response_hash"] == acq_res.response_hash

    # 4. Verify raw evidence persistence
    session_res = output["session_results"][0]
    assert session_res.raw_evidence_path is not None
    evidence_file = Path(session_res.raw_evidence_path)
    assert evidence_file.exists()
    assert evidence_file.read_text(encoding="utf-8") == SAMPLE_HTML_WITH_TABLE

    # 5. Verify compact Agent-facing evidence packet (reusing HTMLAnnouncementParser output)
    assert len(output["agent_evidence_packets"]) == 1
    packet = output["agent_evidence_packets"][0]
    assert packet["source_id"] == "sample_college_hr"
    assert packet["title"] == "广东某学院2026年高层次与专任教师招聘启事"
    assert packet["response_hash"] == acq_res.response_hash
    assert packet["is_excerpt"] is False
    assert len(packet["extracted_tables"]) == 1
    assert len(packet["extracted_tables"][0]["rows"]) == 2
    assert "计算机专任教师" in str(packet["extracted_tables"][0]["rows"])


def test_production_acquisition_structural_rejection_of_caller_injected_facts(tmp_path: Path):
    """
    Finding 4: Structural prevention:
    The production acquisition entrypoint does not accept caller-supplied MonitoringFact/SourceObservation
    as parameters. Passing unsupported arguments is rejected by Python argument binding, and all output
    MonitoringFact objects must have traceable lineage to AcquisitionResult.
    """
    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)

    fake_fact = MonitoringFact(
        source_id="fake_source",
        technical_status="success",
        checked_url="https://fake.edu.cn",
        checked_at=datetime.now().isoformat(),
        metadata={"announcements_found_count": 99},
    )

    # Calling production entrypoint with unsupported manual injection arguments is rejected
    with pytest.raises(TypeError):
        execute_production_acquisition(
            sources=[],
            data_dir=data_dir,
            manual_facts=[fake_fact],  # type: ignore
        )

    # Valid execution guarantees 1-to-1 lineage between MonitoringFact and AcquisitionResult
    target_url = "https://www.valid.edu.cn/zp"
    transport = FakeHttpTransport(
        responses={
            target_url: {
                "status_code": 200,
                "text": "<html><head><title>招聘</title></head><body>正文</body></html>",
            }
        }
    )
    source = SourceRecord(
        source_id="valid_src",
        name="有效渠道",
        base_url=target_url,
        domain="valid.edu.cn",
    )
    output = execute_production_acquisition(sources=[source], data_dir=data_dir, transport=transport)
    assert len(output["acquisition_results"]) == len(output["monitoring_facts"]) == 1
    acq = output["acquisition_results"][0]
    m_fact = output["monitoring_facts"][0]
    assert m_fact.metadata["attempt_id"] == acq.attempt_id
    assert m_fact.metadata["response_hash"] == acq.response_hash


def test_failed_technical_acquisition_excluded_from_agent_content_evidence(tmp_path: Path):
    """
    Finding 3: Technical failure reporting (404/500/timeout):
    - AcquisitionResult records technical_status="failed" and error_facts;
    - MonitoringFact derives technical_status="failed";
    - Raw error response is saved for audit;
    - BUT failed acquisition is STRICTLY EXCLUDED from agent_evidence_packets.
    """
    broken_url = "https://www.broken-link.edu.cn/not-found"
    valid_url = "https://www.ok-school.edu.cn/jobs"

    transport = FakeHttpTransport(
        responses={
            broken_url: {
                "status_code": 404,
                "text": "<html><head><title>404 Not Found</title></head><body>页面不存在</body></html>",
                "headers": {"Content-Type": "text/html"},
            },
            valid_url: {
                "status_code": 200,
                "text": "<html><head><title>正常招聘</title></head><body>招聘专任教师1名</body></html>",
                "headers": {"Content-Type": "text/html"},
            },
        }
    )

    broken_source = SourceRecord(
        source_id="broken_source",
        name="失效渠道",
        base_url=broken_url,
        domain="broken-link.edu.cn",
    )
    valid_source = SourceRecord(
        source_id="valid_source",
        name="正常渠道",
        base_url=valid_url,
        domain="ok-school.edu.cn",
    )

    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)

    output = execute_production_acquisition(
        sources=[broken_source, valid_source],
        data_dir=data_dir,
        transport=transport,
    )

    # 1. Verify two AcquisitionResults
    assert len(output["acquisition_results"]) == 2
    failed_acq = output["acquisition_results"][0]
    success_acq = output["acquisition_results"][1]

    assert failed_acq.technical_status == "failed"
    assert failed_acq.http_status == 404
    assert failed_acq.error_facts["http_status"] == 404

    assert success_acq.technical_status == "success"
    assert success_acq.http_status == 200

    # 2. Verify two MonitoringFacts
    assert len(output["monitoring_facts"]) == 2
    failed_fact = output["monitoring_facts"][0]
    success_fact = output["monitoring_facts"][1]

    assert failed_fact.technical_status == "failed"
    assert success_fact.technical_status == "success"

    # 3. Verify Agent content evidence packets: ONLY the successful source is included!
    assert len(output["agent_evidence_packets"]) == 1
    assert output["agent_evidence_packets"][0]["source_id"] == "valid_source"
    assert output["agent_evidence_packets"][0]["title"] == "正常招聘"


def test_parser_failure_preserves_http_200_network_facts_and_excludes_agent_packet(tmp_path: Path):
    """
    Browser Finding 1: Parser failure after successful HTTP 200:
    - preserves actual HTTP status 200;
    - preserves body length and response hash;
    - retains raw HTML response file on disk;
    - records parser failure facts in AcquisitionResult & MonitoringFact;
    - strictly excludes from normal Agent content evidence (agent_evidence_packets).
    """
    target_url = "https://www.example.edu.cn/zp.html"
    raw_html = "<html><body><h1>招聘启事</h1><p>内容</p></body></html>"
    transport = FakeHttpTransport(
        responses={
            target_url: {
                "status_code": 200,
                "text": raw_html,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
            }
        }
    )

    source = SourceRecord(
        source_id="crash_parse_source",
        name="解析异常渠道",
        base_url=target_url,
        domain="example.edu.cn",
    )

    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Patch HTMLAnnouncementParser.parse to raise an unexpected parsing exception
    with patch.object(
        HTMLAnnouncementParser, "parse", side_effect=RuntimeError("Malformed DOM parsing crash")
    ):
        output = execute_production_acquisition(
            sources=[source],
            data_dir=data_dir,
            transport=transport,
        )

    # 1. Verify AcquisitionResult preserves true HTTP 200 network observation facts
    assert len(output["acquisition_results"]) == 1
    acq_res = output["acquisition_results"][0]
    assert acq_res.http_status == 200
    assert acq_res.body_length == len(raw_html.encode("utf-8"))
    assert len(acq_res.response_hash) == 64
    assert acq_res.technical_status == "failed"
    assert acq_res.error_facts is not None
    assert acq_res.error_facts["parse_error"] == "Malformed DOM parsing crash"
    assert acq_res.error_facts["stage"] == "evidence_parsing"

    # 2. Verify raw evidence was retained on disk
    session_res = output["session_results"][0]
    assert session_res.raw_evidence_path is not None
    evidence_file = Path(session_res.raw_evidence_path)
    assert evidence_file.exists()
    assert evidence_file.read_text(encoding="utf-8") == raw_html

    # 3. Verify derived MonitoringFact preserves HTTP 200 facts and records parse error
    assert len(output["monitoring_facts"]) == 1
    fact = output["monitoring_facts"][0]
    assert fact.technical_status == "failed"
    assert fact.metadata["http_status"] == 200
    assert fact.metadata["response_hash"] == acq_res.response_hash
    assert fact.metadata["parse_error"] == "Malformed DOM parsing crash"

    # 4. Verify that NO false normal Agent content evidence packet was emitted
    assert len(output["agent_evidence_packets"]) == 0
    assert session_res.agent_evidence_packet is None
