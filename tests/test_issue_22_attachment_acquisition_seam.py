"""
Production Acquisition Entrypoint Seam Tests for Issue #22 (static_html_attachment).
Tests verify external behavior of execute_production_acquisition and SourceAcquisitionExecutor:
1. Multi-hop acquisition flow: Listing HTML -> Detail HTML -> Discovered Attachment (XLSX, DOCX, text-PDF)
   -> Binary download & hashing -> Deterministic parsing -> Compact Agent evidence packet.
2. Raw attachment evidence persistence and hash verification.
3. Attachment HTTP failure / 404 preserves detail HTML facts and records failure audit.
4. Attachment corrupt / parse failure preserves raw downloaded bytes & HTTP facts, records parse error without crashing.
5. Legacy unsupported formats (.xls, .doc) report unsupported_legacy_format truthfully.
6. Zero fabricated observations / zero business rule filtering.
"""

from pathlib import Path
import docx
import openpyxl
from pypdf import PageObject, PdfWriter
import pytest
from typing import Any, Dict

from career_radar.acquisition import (
    AcquisitionResult,
    execute_production_acquisition,
)
from career_radar.sources import MonitoringFact, SourceRecord


class FakeHttpTransport:
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


@pytest.fixture
def sample_xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "岗位明细"
    ws.append(["序号", "招聘单位", "工作部门", "岗位名称", "学历学位要求", "专业及代码", "年龄要求", "能力要求"])
    ws.append([
        "1", "广东岭南工程学院", "智能制造学院", "机器人工程专任教师",
        "硕士研究生及以上", "0811 控制科学与工程 / 0802 机械工程", "35周岁以下", "具备ROS开发经验"
    ])
    ws.append([
        "2", "广东岭南工程学院", "计算机学院", "人工智能专任教师",
        "博士研究生", "0812 计算机科学与技术", "38周岁以下", "有大模型实训带教经历"
    ])
    from io import BytesIO
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


@pytest.fixture
def sample_docx_bytes() -> bytes:
    doc = docx.Document()
    doc.add_heading("2026年高层次人才招聘岗位表", level=1)
    table = doc.add_table(rows=1, cols=4)
    hdr = table.rows[0].cells
    hdr[0].text = "岗位名称"
    hdr[1].text = "学历要求"
    hdr[2].text = "专业方向"
    hdr[3].text = "招聘人数"

    row = table.add_row().cells
    row[0].text = "数字媒体艺术专任教师"
    row[1].text = "硕士及以上"
    row[2].text = "设计学 / 数字媒体"
    row[3].text = "2"

    from io import BytesIO
    bio = BytesIO()
    doc.save(bio)
    return bio.getvalue()


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    writer = PdfWriter()
    page = PageObject.create_blank_page(width=612, height=792)
    writer.add_page(page)
    from io import BytesIO
    bio = BytesIO()
    writer.write(bio)
    return bio.getvalue()


def test_multi_hop_listing_to_detail_to_xlsx_attachment(tmp_path: Path, sample_xlsx_bytes: bytes):
    """
    Issue #22 Acceptance Criteria 1, 2, 3:
    Exercises multi-hop acquisition flow:
    Detail HTML -> Discovered attachment -> XLSX binary retrieval -> Disk persistence -> Parsing -> Compact packet.
    """
    detail_url = "https://hrss.gd.gov.cn/zwgk/zp2026_01.html"
    att_url = "https://hrss.gd.gov.cn/attach/2026_post_table.xlsx"

    detail_html = f"""<!DOCTYPE html>
    <html>
    <head><title>广东岭南工程学院2026年公开招聘专任教师公告</title></head>
    <body>
      <h1>广东岭南工程学院2026年公开招聘专任教师公告</h1>
      <p>为满足教育教学需要，现面向社会招聘专任教师，具体岗位见附件：</p>
      <div class="attachment-box">
        <a href="{att_url}" title="岗位表.xlsx">附件：广东岭南工程学院2026年岗位需求明细表.xlsx</a>
      </div>
    </body>
    </html>"""

    transport = FakeHttpTransport(
        responses={
            detail_url: {
                "status_code": 200,
                "text": detail_html,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
            },
            att_url: {
                "status_code": 200,
                "content": sample_xlsx_bytes,
                "headers": {
                    "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "Content-Disposition": 'attachment; filename="2026_post_table.xlsx"',
                },
            },
        }
    )

    source = SourceRecord(
        source_id="gd_hrss_att",
        name="广东省人社厅附件招聘",
        base_url=detail_url,
        domain="hrss.gd.gov.cn",
        source_type="first_party_official",
        metadata={"archetype": "static_html_attachment"},
    )

    data_dir = tmp_path / ".data"
    output = execute_production_acquisition(sources=[source], data_dir=data_dir, transport=transport)

    # 1. Transport invoked for both detail page and attachment
    assert len(transport.requests_log) == 2
    assert transport.requests_log[0]["url"] == detail_url
    assert transport.requests_log[1]["url"] == att_url

    # 2. AcquisitionResult recorded accurately
    assert len(output["acquisition_results"]) == 1
    acq_res = output["acquisition_results"][0]
    assert acq_res.technical_status == "success"
    assert acq_res.metadata["attachments_found_count"] == 1
    assert acq_res.metadata["attachments_acquired_count"] == 1

    # 3. Auditable attachment evidence facts
    att_audits = acq_res.metadata["attachment_audits"]
    assert len(att_audits) == 1
    assert att_audits[0]["url"] == att_url
    assert att_audits[0]["status"] == "success"
    assert att_audits[0]["parse_status"] == "success"
    assert att_audits[0]["body_length"] == len(sample_xlsx_bytes)
    assert len(att_audits[0]["attachment_hash"]) == 64
    assert Path(att_audits[0]["local_evidence_path"]).exists()

    # 4. Agent evidence packet contains parsed attachment tabular rows
    assert len(output["agent_evidence_packets"]) == 1
    packet = output["agent_evidence_packets"][0]
    assert packet["title"] == "广东岭南工程学院2026年公开招聘专任教师公告"
    assert len(packet["attachments"]) == 1
    assert packet["attachments"][0]["status"] == "success"
    assert len(packet["attachment_tables"]) == 1
    rows = packet["attachment_tables"][0]["rows"]
    assert len(rows) == 2
    assert rows[0]["cells"]["岗位名称"] == "机器人工程专任教师"
    assert rows[1]["cells"]["岗位名称"] == "人工智能专任教师"


def test_docx_and_pdf_attachments_acquisition_and_parsing(
    tmp_path: Path, sample_docx_bytes: bytes, sample_pdf_bytes: bytes
):
    """
    Verifies multi-format attachment support: DOCX and text-native PDF in a single announcement.
    """
    detail_url = "https://rsc.sample.edu.cn/zp/announcement.html"
    docx_url = "https://rsc.sample.edu.cn/zp/docs/posts.docx"
    pdf_url = "https://rsc.sample.edu.cn/zp/docs/guidelines.pdf"

    detail_html = f"""<!DOCTYPE html>
    <html>
    <body>
      <h1>招聘公告</h1>
      <a href="{docx_url}">附件1：岗位表.docx</a>
      <a href="{pdf_url}">附件2：报考指南.pdf</a>
    </body>
    </html>"""

    transport = FakeHttpTransport(
        responses={
            detail_url: {"status_code": 200, "text": detail_html, "headers": {"Content-Type": "text/html"}},
            docx_url: {
                "status_code": 200,
                "content": sample_docx_bytes,
                "headers": {"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            },
            pdf_url: {
                "status_code": 200,
                "content": sample_pdf_bytes,
                "headers": {"Content-Type": "application/pdf"},
            },
        }
    )

    source = SourceRecord(
        source_id="multi_format_src",
        name="多格式渠道",
        base_url=detail_url,
        domain="rsc.sample.edu.cn",
    )

    data_dir = tmp_path / ".data"
    output = execute_production_acquisition(sources=[source], data_dir=data_dir, transport=transport)

    assert len(transport.requests_log) == 3
    packet = output["agent_evidence_packets"][0]
    assert len(packet["attachments"]) == 2
    assert len(packet["attachment_tables"]) == 1
    assert packet["attachment_tables"][0]["rows"][0]["cells"]["岗位名称"] == "数字媒体艺术专任教师"
    assert len(packet["attachment_pages"]) == 1


def test_attachment_http_404_preserves_html_facts_and_records_audit(tmp_path: Path):
    """
    Issue #22 Acceptance Criteria 4:
    Attachment 404 HTTP failure must preserve HTML acquisition facts, record truthful attachment failure,
    and not crash or fabricate fake data.
    """
    detail_url = "https://www.school.edu.cn/zp.html"
    missing_att_url = "https://www.school.edu.cn/attach/missing.xlsx"

    detail_html = f"""<html><body><h1>招聘</h1><a href="{missing_att_url}">岗位表.xlsx</a></body></html>"""

    transport = FakeHttpTransport(
        responses={
            detail_url: {"status_code": 200, "text": detail_html, "headers": {"Content-Type": "text/html"}},
            missing_att_url: {"status_code": 404, "text": "Attachment Not Found", "headers": {}},
        }
    )

    source = SourceRecord(source_id="missing_att_src", name="缺失附件渠道", base_url=detail_url, domain="school.edu.cn")
    data_dir = tmp_path / ".data"
    output = execute_production_acquisition(sources=[source], data_dir=data_dir, transport=transport)

    acq_res = output["acquisition_results"][0]
    assert acq_res.http_status == 200
    assert acq_res.technical_status == "success"
    assert acq_res.metadata["attachments_found_count"] == 1
    assert acq_res.metadata["attachments_acquired_count"] == 0

    att_audit = acq_res.metadata["attachment_audits"][0]
    assert att_audit["status"] == "failed"
    assert att_audit["http_status"] == 404

    packet = output["agent_evidence_packets"][0]
    assert len(packet["attachments"]) == 1
    assert packet["attachments"][0]["status"] == "failed"
    assert packet["attachment_tables"] == []


def test_corrupted_attachment_preserves_downloaded_bytes_and_records_parse_error(tmp_path: Path):
    """
    Issue #22 Error Boundary Invariant:
    Corrupted attachment bytes preserve downloaded bytes, file hash, local path, and record deterministic
    parsing failure in audit without crash or false observations.
    """
    detail_url = "https://www.school.edu.cn/zp_corrupt.html"
    corrupt_att_url = "https://www.school.edu.cn/attach/corrupt.xlsx"
    corrupt_bytes = b"NOT_A_VALID_ZIP_OR_XLSX_HEADER_GARBAGE_BYTES"

    detail_html = f"""<html><body><h1>招聘</h1><a href="{corrupt_att_url}">岗位表.xlsx</a></body></html>"""

    transport = FakeHttpTransport(
        responses={
            detail_url: {"status_code": 200, "text": detail_html, "headers": {"Content-Type": "text/html"}},
            corrupt_att_url: {
                "status_code": 200,
                "content": corrupt_bytes,
                "headers": {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            },
        }
    )

    source = SourceRecord(source_id="corrupt_src", name="损坏附件渠道", base_url=detail_url, domain="school.edu.cn")
    data_dir = tmp_path / ".data"
    output = execute_production_acquisition(sources=[source], data_dir=data_dir, transport=transport)

    acq_res = output["acquisition_results"][0]
    att_audit = acq_res.metadata["attachment_audits"][0]
    assert att_audit["status"] == "success"  # Network download succeeded
    assert att_audit["parse_status"] == "failed"  # Parser recorded deterministic failure
    assert att_audit["body_length"] == len(corrupt_bytes)
    assert Path(att_audit["local_evidence_path"]).read_bytes() == corrupt_bytes

    packet = output["agent_evidence_packets"][0]
    assert packet["attachments"][0]["status"] == "failed"
    assert packet["attachment_tables"] == []


def test_legacy_format_reported_truthfully_as_unsupported(tmp_path: Path):
    """
    Verifies that legacy formats (.xls, .doc) are reported truthfully without crashing.
    """
    detail_url = "https://www.school.edu.cn/legacy.html"
    detail_html = """<html><body><h1>招聘</h1><a href="/attach/old.xls">历史表.xls</a></body></html>"""

    transport = FakeHttpTransport(
        responses={
            detail_url: {"status_code": 200, "text": detail_html, "headers": {"Content-Type": "text/html"}},
        }
    )

    source = SourceRecord(source_id="legacy_src", name="旧格式渠道", base_url=detail_url, domain="school.edu.cn")
    data_dir = tmp_path / ".data"
    output = execute_production_acquisition(sources=[source], data_dir=data_dir, transport=transport)

    packet = output["agent_evidence_packets"][0]
    assert len(packet["attachments"]) == 1
    assert packet["attachments"][0]["status"] == "unsupported_legacy_format"
    assert packet["attachment_tables"] == []
