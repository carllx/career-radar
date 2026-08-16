"""
Production Source Acquisition Executor & Audit Contract for Career Radar.
Respects CONTEXT.md, ADR-0002, Issue #19 and parent Spec #20.

Establishes:
1. AcquisitionResult audit contract (mechanically recorded, traceable, hash-addressable);
2. SourceAcquisitionExecutor for deterministic HTTP acquisition & raw evidence persistence;
3. MonitoringFact derivation strictly anchored to AcquisitionResult in production;
4. Defense against manual fake MonitoringFact injection in production execution.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
import uuid

from bs4 import BeautifulSoup
import requests

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
        return requests.get(
            url, headers=headers, timeout=self.timeout, verify=self.verify_ssl
        )

    def _extract_dom_structure(self, html_text: str) -> Dict[str, Any]:
        """
        Deterministically extracts title, tables, and structured text from HTML.
        Does not perform semantic job matching.
        """
        soup = BeautifulSoup(html_text, "html.parser")
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text(strip=True)

        extracted_tables = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if cells:
                    rows.append(cells)
            if rows or headers:
                extracted_tables.append({"headers": headers, "rows": rows})

        # Clean text excerpt without excessive whitespace
        text_content = soup.get_text(separator="\n", strip=True)
        text_excerpt = "\n".join(
            line for line in text_content.splitlines() if line.strip()
        )[:3000]

        return {
            "title": title,
            "extracted_tables": extracted_tables,
            "text_excerpt": text_excerpt,
        }

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
            final_url = getattr(resp, "url", requested_url) or requested_url
            headers = dict(getattr(resp, "headers", {}) or {})
            content_type = headers.get("Content-Type", headers.get("content-type", "text/html"))

            raw_bytes = getattr(resp, "content", b"")
            if not raw_bytes and hasattr(resp, "text"):
                raw_bytes = resp.text.encode("utf-8")

            body_length = len(raw_bytes)
            response_hash = hashlib.sha256(raw_bytes).hexdigest()
            html_text = getattr(resp, "text", "") or raw_bytes.decode("utf-8", errors="replace")

            if status_code >= 400:
                technical_status = "failed"
                error_facts = {"http_status": status_code, "error": f"HTTP {status_code}"}
            else:
                technical_status = "success"
                error_facts = None

            # Persist raw evidence to disk
            source_evidence_dir = self.evidence_dir / source.source_id
            source_evidence_dir.mkdir(parents=True, exist_ok=True)
            raw_evidence_file = source_evidence_dir / f"{attempt_id}.html"
            raw_evidence_file.write_bytes(raw_bytes)

            dom_data = self._extract_dom_structure(html_text)

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

            agent_packet = {
                "source_id": source.source_id,
                "source_name": source.name,
                "url": final_url,
                "attempt_id": attempt_id,
                "response_hash": response_hash,
                "raw_evidence_path": str(raw_evidence_file),
                "title": dom_data["title"],
                "extracted_tables": dom_data["extracted_tables"],
                "text_excerpt": dom_data["text_excerpt"],
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
    manual_facts_override: Optional[List[MonitoringFact]] = None,
    require_genuine_acquisition: bool = True,
) -> Dict[str, Any]:
    """
    Top-level production acquisition entrypoint.
    Enforces that production monitoring facts must originate from genuine AcquisitionResult records.
    """
    if require_genuine_acquisition and manual_facts_override is not None:
        raise ValueError(
            "Production acquisition proof requires valid AcquisitionResult generated by SourceAcquisitionExecutor; "
            "manually supplied MonitoringFact objects are not valid production acquisition proof."
        )

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
            r.agent_evidence_packet for r in session_results if r.agent_evidence_packet
        ],
    }
