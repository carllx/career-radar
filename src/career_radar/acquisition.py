"""
Production Source Acquisition Executor & Audit Contract for Career Radar.
Respects CONTEXT.md, ADR-0002, Issue #19, Spec #20 and Issue #21.

Establishes:
1. AcquisitionResult audit contract (mechanically recorded, traceable, hash-addressable);
2. SourceAcquisitionExecutor for deterministic HTTP acquisition & raw evidence persistence;
3. Reuses HTMLAnnouncementParser for deterministic structure extraction;
4. MonitoringFact derivation strictly anchored to AcquisitionResult in production;
5. Failed technical acquisitions produce failure facts and are excluded from Agent content evidence;
6. Structural production entrypoint accepting only valid acquisition inputs.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid

import charset_normalizer
import httpx

from .parser import HTMLAnnouncementParser
from .sources import MonitoringFact, SourceRecord


@dataclass
class AcquisitionResult:
    """
    Auditable mechanical acquisition record produced by actual network retrieval.
    """
    attempt_id: str
    source_id: str
    requested_url: str
    final_url: str
    timestamp: str
    acquisition_method: str = "native_http_get"
    technical_status: str = "success"  # "success", "failed", "blocked_by_captcha", "unsupported_dynamic"
    http_status: Optional[int] = None
    content_type: Optional[str] = None
    body_length: int = 0
    response_hash: str = ""
    error_facts: Optional[Dict[str, Any]] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AcquisitionResult":
        return cls(
            attempt_id=data["attempt_id"],
            source_id=data["source_id"],
            requested_url=data["requested_url"],
            final_url=data.get("final_url", data["requested_url"]),
            timestamp=data["timestamp"],
            acquisition_method=data.get("acquisition_method", "native_http_get"),
            technical_status=data.get("technical_status", "success"),
            http_status=data.get("http_status"),
            content_type=data.get("content_type"),
            body_length=data.get("body_length", 0),
            response_hash=data.get("response_hash", ""),
            error_facts=data.get("error_facts"),
            etag=data.get("etag"),
            last_modified=data.get("last_modified"),
            metadata=data.get("metadata"),
        )


@dataclass
class SourceAcquisitionSessionResult:
    """
    Vertical result combining mechanical audit record, derived monitoring fact,
    persisted raw evidence path, and compact Agent-facing structured packet.
    """
    source_id: str
    acquisition_result: AcquisitionResult
    monitoring_fact: MonitoringFact
    raw_evidence_path: Optional[str] = None
    agent_evidence_packet: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "acquisition_result": self.acquisition_result.to_dict(),
            "monitoring_fact": asdict(self.monitoring_fact),
            "raw_evidence_path": self.raw_evidence_path,
            "agent_evidence_packet": self.agent_evidence_packet,
        }


class SourceAcquisitionExecutor:
    """
    Deterministic executor for acquiring recruitment channels and persisting raw evidence.
    Aligned with Spec #20 native HTTP baseline and reusing existing HTMLAnnouncementParser.
    """

    def __init__(
        self,
        data_dir: Union[str, Path] = ".data",
        transport: Any = None,
        timeout: int = 15,
        verify_ssl: bool = True,
        user_agent: Optional[str] = None,
    ):
        self.data_dir = Path(data_dir)
        self.evidence_dir = self.data_dir / "raw_evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.transport = transport
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36 CareerRadar/0.1.0"
        )
        self.html_parser = HTMLAnnouncementParser()

    def _execute_http_get(self, url: str) -> Any:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if self.transport is not None:
            return self.transport.get(
                url, headers=headers, timeout=self.timeout, verify=self.verify_ssl
            )
        return httpx.get(
            url,
            headers=headers,
            timeout=self.timeout,
            verify=self.verify_ssl,
            follow_redirects=True,
        )

    def _decode_html(self, raw_bytes: bytes, declared_content_type: str) -> str:
        """
        Truthfully decodes HTML bytes respecting declared charset with robust fallback.
        """
        if not raw_bytes:
            return ""
        # Check declared charset in header
        if "charset=" in declared_content_type.lower():
            charset = declared_content_type.lower().split("charset=")[-1].split(";")[0].strip("\"' ")
            try:
                return raw_bytes.decode(charset)
            except (LookupError, UnicodeDecodeError):
                pass

        # Try UTF-8 first
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            pass

        # Fallback to charset_normalizer
        try:
            detected = charset_normalizer.from_bytes(raw_bytes).best()
            if detected and detected.encoding:
                return raw_bytes.decode(detected.encoding, errors="replace")
        except Exception:
            pass

        # Fallback to GB18030 / GBK for Chinese institutions
        try:
            return raw_bytes.decode("gb18030", errors="replace")
        except Exception:
            return raw_bytes.decode("utf-8", errors="replace")

    def acquire_source(self, source: SourceRecord) -> SourceAcquisitionSessionResult:
        """
        Acquires a single source record, persists evidence, and derives monitoring fact.
        """
        attempt_id = f"acq_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now().isoformat()
        requested_url = source.base_url

        try:
            resp = self._execute_http_get(requested_url)
            status_code = getattr(resp, "status_code", 200)
            final_url = str(getattr(resp, "url", requested_url) or requested_url)
            headers = dict(getattr(resp, "headers", {}) or {})
            content_type = headers.get("Content-Type", headers.get("content-type", "text/html"))

            raw_bytes = getattr(resp, "content", b"")
            if not raw_bytes and hasattr(resp, "text"):
                raw_bytes = resp.text.encode("utf-8")

            body_length = len(raw_bytes)
            response_hash = hashlib.sha256(raw_bytes).hexdigest()

            if status_code >= 400:
                technical_status = "failed"
                error_facts = {"http_status": status_code, "error": f"HTTP {status_code}"}
            else:
                technical_status = "success"
                error_facts = None

            # Persist raw response for audit/debug
            source_evidence_dir = self.evidence_dir / source.source_id
            source_evidence_dir.mkdir(parents=True, exist_ok=True)
            raw_evidence_file = source_evidence_dir / f"{attempt_id}.html"
            raw_evidence_file.write_bytes(raw_bytes)

            acq_res = AcquisitionResult(
                attempt_id=attempt_id,
                source_id=source.source_id,
                requested_url=requested_url,
                final_url=final_url,
                timestamp=now_iso,
                acquisition_method="native_http_get",
                technical_status=technical_status,
                http_status=status_code,
                content_type=content_type,
                body_length=body_length,
                response_hash=response_hash,
                error_facts=error_facts,
                etag=headers.get("ETag") or headers.get("etag"),
                last_modified=headers.get("Last-Modified") or headers.get("last-modified"),
            )

            # Derive MonitoringFact from AcquisitionResult
            fact_metadata: Dict[str, Any] = {
                "attempt_id": attempt_id,
                "response_hash": response_hash,
                "body_length": body_length,
                "http_status": status_code,
            }
            if error_facts:
                fact_metadata.update(error_facts)

            monitoring_fact = MonitoringFact(
                source_id=source.source_id,
                technical_status=technical_status,
                checked_url=final_url,
                checked_at=now_iso,
                metadata=fact_metadata,
            )

            # Only construct Agent content evidence for successful acquisitions
            agent_packet = None
            if technical_status == "success":
                html_text = self._decode_html(raw_bytes, content_type)
                parsed = self.html_parser.parse(html_text, base_url=final_url)
                full_body = parsed.get("body_text", "")
                is_truncated = len(full_body) > 3000
                text_excerpt = full_body[:3000] if is_truncated else full_body

                agent_packet = {
                    "source_id": source.source_id,
                    "source_name": source.name,
                    "url": final_url,
                    "attempt_id": attempt_id,
                    "response_hash": response_hash,
                    "raw_evidence_path": str(raw_evidence_file),
                    "title": parsed.get("title", ""),
                    "extracted_tables": parsed.get("tables", []),
                    "headings": parsed.get("headings", []),
                    "attachments": parsed.get("attachments", []),
                    "text_excerpt": text_excerpt,
                    "is_excerpt": is_truncated,
                    "total_text_length": len(full_body),
                }

            return SourceAcquisitionSessionResult(
                source_id=source.source_id,
                acquisition_result=acq_res,
                monitoring_fact=monitoring_fact,
                raw_evidence_path=str(raw_evidence_file),
                agent_evidence_packet=agent_packet,
            )

        except Exception as e:
            acq_res = AcquisitionResult(
                attempt_id=attempt_id,
                source_id=source.source_id,
                requested_url=requested_url,
                final_url=requested_url,
                timestamp=now_iso,
                acquisition_method="native_http_get",
                technical_status="failed",
                http_status=None,
                content_type=None,
                body_length=0,
                response_hash="",
                error_facts={"error": str(e), "exception_class": type(e).__name__},
            )
            monitoring_fact = MonitoringFact(
                source_id=source.source_id,
                technical_status="failed",
                checked_url=requested_url,
                checked_at=now_iso,
                metadata={"attempt_id": attempt_id, "error": str(e)},
            )
            return SourceAcquisitionSessionResult(
                source_id=source.source_id,
                acquisition_result=acq_res,
                monitoring_fact=monitoring_fact,
                raw_evidence_path=None,
                agent_evidence_packet=None,
            )


def execute_production_acquisition(
    sources: List[SourceRecord],
    data_dir: Union[str, Path] = ".data",
    transport: Any = None,
) -> Dict[str, Any]:
    """
    Top-level production acquisition entrypoint.
    Executes real acquisition for given sources, persists evidence, and derives monitoring facts.
    """
    executor = SourceAcquisitionExecutor(data_dir=data_dir, transport=transport)
    session_results: List[SourceAcquisitionSessionResult] = []

    for src in sources:
        res = executor.acquire_source(src)
        session_results.append(res)

    return {
        "session_results": session_results,
        "acquisition_results": [r.acquisition_result for r in session_results],
        "monitoring_facts": [r.monitoring_fact for r in session_results],
        "agent_evidence_packets": [
            r.agent_evidence_packet for r in session_results if r.agent_evidence_packet is not None
        ],
    }
