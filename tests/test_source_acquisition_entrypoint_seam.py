"""
Production Acquisition Entrypoint Seam Tests for Issue #21.
Tests verify external behavior of SourceAcquisitionExecutor and Production Entrypoint:
1. static_html_table_or_body archetype performs real controlled transport acquisition,
   produces auditable AcquisitionResult, derives MonitoringFact, persists raw HTML evidence,
   and surfaces compact Agent-facing evidence packet.
2. Structural prevention: manually constructed MonitoringFact without AcquisitionResult
   cannot count as proof of production acquisition.
3. Truthful technical failure reporting when transport fails.
"""

from datetime import datetime
import json
from pathlib import Path
import pytest
from typing import Any, Dict

from career_radar.acquisition import (
    AcquisitionResult,
    SourceAcquisitionExecutor,
    execute_production_acquisition,
)
from career_radar.sources import MonitoringFact, SourceRecord, SourceRegistry


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
            )
        return FakeResponse(status_code=404, text="Not Found", headers={}, url=url)


class FakeResponse:
    def __init__(self, status_code: int, text: str, headers: Dict[str, str], url: str):
        self.status_code = status_code
        self.text = text
        self.headers = headers
        self.url = url
        self.content = text.encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code} Error")


SAMPLE_HTML_WITH_TABLE = """<!DOCTYPE html>
<html>
<head><title>广东某学院2026年高层次与专任教师招聘启事</title></head>
<body>
  <h1>招聘公告</h1>
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


def test_production_acquisition_static_html_table_or_body_end_to_end(tmp_path: Path):
    """
    Vertical slice for static_html_table_or_body:
    SourceRecord -> controlled HTTP acquisition -> AcquisitionResult -> derived MonitoringFact
    -> persisted raw evidence -> compact Agent-facing packet.
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

    executor = SourceAcquisitionExecutor(
        data_dir=data_dir,
        transport=transport,
    )

    # Execute acquisition through the executor
    session_result = executor.acquire_source(source)

    # 1. Verify AcquisitionResult audit contract
    acq_res = session_result.acquisition_result
    assert isinstance(acq_res, AcquisitionResult)
    assert acq_res.source_id == "sample_college_hr"
    assert acq_res.requested_url == target_url
    assert acq_res.final_url == target_url
    assert acq_res.technical_status == "success"
    assert acq_res.http_status == 200
    assert "text/html" in acq_res.content_type
    assert acq_res.body_length == len(SAMPLE_HTML_WITH_TABLE.encode("utf-8"))
    assert len(acq_res.response_hash) == 64  # SHA256 hex digest
    assert acq_res.acquisition_method == "native_http_get"
    assert acq_res.attempt_id.startswith("acq_")

    # 2. Verify derived MonitoringFact
    fact = session_result.monitoring_fact
    assert isinstance(fact, MonitoringFact)
    assert fact.source_id == "sample_college_hr"
    assert fact.technical_status == "success"
    assert fact.checked_url == target_url
    assert fact.checked_at == acq_res.timestamp
    assert fact.metadata["attempt_id"] == acq_res.attempt_id
    assert fact.metadata["response_hash"] == acq_res.response_hash

    # 3. Verify raw evidence persistence
    assert session_result.raw_evidence_path is not None
    evidence_file = Path(session_result.raw_evidence_path)
    assert evidence_file.exists()
    assert evidence_file.read_text(encoding="utf-8") == SAMPLE_HTML_WITH_TABLE

    # 4. Verify compact Agent-facing evidence packet
    packet = session_result.agent_evidence_packet
    assert packet is not None
    assert packet["source_id"] == "sample_college_hr"
    assert packet["title"] == "广东某学院2026年高层次与专任教师招聘启事"
    assert packet["response_hash"] == acq_res.response_hash
    assert len(packet["extracted_tables"]) == 1
    assert len(packet["extracted_tables"][0]["rows"]) == 2
    assert "计算机专任教师" in str(packet["extracted_tables"][0]["rows"])

    # Verify transport was actually invoked exactly once
    assert len(transport.requests_log) == 1
    assert transport.requests_log[0]["url"] == target_url


def test_production_acquisition_structural_prevention_of_fake_monitoring_facts(tmp_path: Path):
    """
    Structural verification:
    The production acquisition entrypoint requires real AcquisitionResult records.
    Passing arbitrary manually constructed MonitoringFact objects without corresponding
    AcquisitionResult execution is rejected by the production entrypoint verification.
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

    # Attempting to validate or run production acquisition using manual MonitoringFact alone
    # without genuine AcquisitionResult execution fails validation.
    with pytest.raises(ValueError, match="Production acquisition proof requires valid AcquisitionResult"):
        execute_production_acquisition(
            sources=[],
            manual_facts_override=[fake_fact],
            data_dir=data_dir,
            require_genuine_acquisition=True,
        )


def test_production_acquisition_truthful_failure_recording(tmp_path: Path):
    """
    When transport encounters 404 or connection error, AcquisitionResult and
    derived MonitoringFact truthfully record the failure facts.
    """
    target_url = "https://www.broken-link.edu.cn/not-found"
    transport = FakeHttpTransport(
        responses={
            target_url: {
                "status_code": 404,
                "text": "<html><body>404 Not Found</body></html>",
                "headers": {"Content-Type": "text/html"},
            }
        }
    )

    source = SourceRecord(
        source_id="broken_source",
        name="失效渠道",
        base_url=target_url,
        domain="broken-link.edu.cn",
        metadata={"archetype": "static_html_table_or_body"},
    )

    executor = SourceAcquisitionExecutor(
        data_dir=tmp_path / ".data",
        transport=transport,
    )

    session_result = executor.acquire_source(source)
    acq_res = session_result.acquisition_result
    fact = session_result.monitoring_fact

    assert acq_res.technical_status == "failed"
    assert acq_res.http_status == 404
    assert fact.technical_status == "failed"
    assert fact.metadata["http_status"] == 404
