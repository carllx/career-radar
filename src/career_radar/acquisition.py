"""
Production Source Acquisition Executor for Career Radar.
Respects CONTEXT.md, ADR-0002, Issue #19, Spec #20, Issue #21, #22, and #23.
"""

from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid

import charset_normalizer
import httpx

from .acquisition_models import AcquisitionResult, SourceAcquisitionSessionResult
from .attachment_helper import AttachmentAcquisitionHelper
from .incremental_helper import IncrementalAcquisitionHelper
from .listing_helper import ListingAcquisitionHelper
from .parser import AttachmentParser, HTMLAnnouncementParser
from .sources import MonitoringFact, SourceRecord, SourceRegistry


class SourceAcquisitionExecutor:
    """
    Deterministic executor for acquiring recruitment channels and persisting raw evidence.
    Aligned with Spec #20 native HTTP baseline and reusing HTMLAnnouncementParser + AttachmentParser.
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
        self.attachment_parser = AttachmentParser()
        self.attachment_helper = AttachmentAcquisitionHelper(
            evidence_dir=self.evidence_dir, attachment_parser=self.attachment_parser
        )

    def _execute_http_get(self, url: str, headers: Optional[Dict[str, str]] = None) -> Any:
        req_headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if headers:
            req_headers.update(headers)

        if self.transport is not None:
            return self.transport.get(
                url, headers=req_headers, timeout=self.timeout, verify=self.verify_ssl
            )
        return httpx.get(
            url,
            headers=req_headers,
            timeout=self.timeout,
            verify=self.verify_ssl,
            follow_redirects=True,
        )

    def _decode_html(self, raw_bytes: bytes, declared_content_type: str) -> str:
        if not raw_bytes:
            return ""
        if "charset=" in declared_content_type.lower():
            charset = declared_content_type.lower().split("charset=")[-1].split(";")[0].strip("\"' ")
            try:
                return raw_bytes.decode(charset)
            except (LookupError, UnicodeDecodeError):
                pass
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            pass
        try:
            detected = charset_normalizer.from_bytes(raw_bytes).best()
            if detected and detected.encoding:
                return raw_bytes.decode(detected.encoding, errors="replace")
        except Exception:
            pass
        try:
            return raw_bytes.decode("gb18030", errors="replace")
        except Exception:
            return raw_bytes.decode("utf-8", errors="replace")

    def acquire_source(self, source: SourceRecord) -> SourceAcquisitionSessionResult:
        session_id = f"acq_{uuid.uuid4().hex[:12]}"
        metadata = source.metadata or {}
        is_listing_source = bool(metadata.get("is_listing", False))
        conditional_headers = IncrementalAcquisitionHelper.build_conditional_headers(source)

        if not is_listing_source:
            return self._acquire_detail_and_attachments(
                source=source,
                detail_url=source.base_url,
                session_id=session_id,
                listing_result=None,
                conditional_headers=conditional_headers,
            )

        (
            detail_url,
            listing_acq_res,
            monitoring_fact,
            raw_listing_path,
            is_unchanged,
            observed_fingerprint,
        ) = ListingAcquisitionHelper.acquire_listing_page(
            source=source,
            session_id=session_id,
            evidence_dir=self.evidence_dir,
            http_getter=self._execute_http_get,
            decode_html_fn=self._decode_html,
            html_parser=self.html_parser,
            conditional_headers=conditional_headers,
        )

        if is_unchanged or not detail_url or listing_acq_res.technical_status == "failed":
            return SourceAcquisitionSessionResult(
                source_id=source.source_id,
                acquisition_result=listing_acq_res,
                monitoring_fact=monitoring_fact,
                raw_evidence_path=raw_listing_path,
                agent_evidence_packet=None,
                acquisition_results=[listing_acq_res],
            )

        return self._acquire_detail_and_attachments(
            source=source,
            detail_url=detail_url,
            session_id=session_id,
            listing_result=listing_acq_res,
        )

    def _acquire_detail_and_attachments(
        self,
        source: SourceRecord,
        detail_url: str,
        session_id: str,
        listing_result: Optional[AcquisitionResult] = None,
        conditional_headers: Optional[Dict[str, str]] = None,
    ) -> SourceAcquisitionSessionResult:
        now_iso = datetime.now().isoformat()
        detail_attempt_id = f"{session_id}_detail" if listing_result else session_id
        all_acq_results: List[AcquisitionResult] = [listing_result] if listing_result else []

        try:
            resp = self._execute_http_get(detail_url, headers=conditional_headers)
        except Exception as detail_net_err:
            detail_acq_res = AcquisitionResult(
                attempt_id=detail_attempt_id,
                source_id=source.source_id,
                requested_url=detail_url,
                final_url=detail_url,
                timestamp=now_iso,
                acquisition_method="native_http_get",
                technical_status="failed",
                http_status=None,
                content_type=None,
                body_length=0,
                response_hash="",
                error_facts={
                    "error": str(detail_net_err),
                    "exception_class": type(detail_net_err).__name__,
                    "stage": "detail_transport",
                },
                metadata={"request_type": "detail", "parent_attempt_id": listing_result.attempt_id if listing_result else None},
            )
            all_acq_results.append(detail_acq_res)
            monitoring_fact = MonitoringFact(
                source_id=source.source_id,
                technical_status="failed",
                checked_url=detail_url,
                checked_at=now_iso,
                metadata={"attempt_id": detail_attempt_id, "error": str(detail_net_err)},
            )
            return SourceAcquisitionSessionResult(
                source_id=source.source_id,
                acquisition_result=detail_acq_res,
                monitoring_fact=monitoring_fact,
                raw_evidence_path=None,
                agent_evidence_packet=None,
                acquisition_results=all_acq_results,
            )

        status_code = getattr(resp, "status_code", 200)
        final_url = str(getattr(resp, "url", detail_url) or detail_url)
        headers = dict(getattr(resp, "headers", {}) or {})
        content_type = headers.get("Content-Type", headers.get("content-type", "text/html"))
        etag = headers.get("ETag") or headers.get("etag")
        last_modified = headers.get("Last-Modified") or headers.get("last-modified")

        # Handle HTTP 304 on direct detail source
        if status_code == 304:
            detail_acq_res = AcquisitionResult(
                attempt_id=detail_attempt_id,
                source_id=source.source_id,
                requested_url=detail_url,
                final_url=final_url,
                timestamp=now_iso,
                acquisition_method="native_http_get",
                technical_status="success",
                http_status=304,
                content_type=content_type,
                body_length=0,
                response_hash="",
                etag=etag,
                last_modified=last_modified,
                metadata={"request_type": "detail", "unchanged": True},
            )
            all_acq_results.append(detail_acq_res)
            monitoring_fact = MonitoringFact(
                source_id=source.source_id,
                technical_status="success",
                checked_url=final_url,
                checked_at=now_iso,
                metadata={"attempt_id": detail_attempt_id, "http_status": 304, "unchanged": True},
            )
            return SourceAcquisitionSessionResult(
                source_id=source.source_id,
                acquisition_result=detail_acq_res,
                monitoring_fact=monitoring_fact,
                raw_evidence_path=None,
                agent_evidence_packet=None,
                acquisition_results=all_acq_results,
            )

        raw_bytes = getattr(resp, "content", b"") or (resp.text.encode("utf-8") if hasattr(resp, "text") else b"")
        body_length = len(raw_bytes)
        response_hash = hashlib.sha256(raw_bytes).hexdigest()

        # Check if direct detail source is unchanged based on response hash
        if not listing_result and IncrementalAcquisitionHelper.is_source_unchanged(source, observed_hash=response_hash):
            detail_acq_res = AcquisitionResult(
                attempt_id=detail_attempt_id,
                source_id=source.source_id,
                requested_url=detail_url,
                final_url=final_url,
                timestamp=now_iso,
                acquisition_method="native_http_get",
                technical_status="success",
                http_status=status_code,
                content_type=content_type,
                body_length=body_length,
                response_hash=response_hash,
                etag=etag,
                last_modified=last_modified,
                metadata={"request_type": "detail", "unchanged": True},
            )
            all_acq_results.append(detail_acq_res)
            monitoring_fact = MonitoringFact(
                source_id=source.source_id,
                technical_status="success",
                checked_url=final_url,
                checked_at=now_iso,
                metadata={"attempt_id": detail_attempt_id, "response_hash": response_hash, "unchanged": True},
            )
            return SourceAcquisitionSessionResult(
                source_id=source.source_id,
                acquisition_result=detail_acq_res,
                monitoring_fact=monitoring_fact,
                raw_evidence_path=None,
                agent_evidence_packet=None,
                acquisition_results=all_acq_results,
            )

        source_evidence_dir = self.evidence_dir / source.source_id
        source_evidence_dir.mkdir(parents=True, exist_ok=True)
        raw_evidence_file = source_evidence_dir / f"{detail_attempt_id}.html"
        raw_evidence_file.write_bytes(raw_bytes)
        raw_evidence_path = str(raw_evidence_file)

        if status_code >= 400:
            detail_acq_res = AcquisitionResult(
                attempt_id=detail_attempt_id,
                source_id=source.source_id,
                requested_url=detail_url,
                final_url=final_url,
                timestamp=now_iso,
                acquisition_method="native_http_get",
                technical_status="failed",
                http_status=status_code,
                content_type=content_type,
                body_length=body_length,
                response_hash=response_hash,
                error_facts={"http_status": status_code, "error": f"HTTP {status_code}"},
                etag=etag,
                last_modified=last_modified,
                metadata={"request_type": "detail", "raw_evidence_path": raw_evidence_path},
            )
            all_acq_results.append(detail_acq_res)
            monitoring_fact = MonitoringFact(
                source_id=source.source_id,
                technical_status="failed",
                checked_url=final_url,
                checked_at=now_iso,
                metadata={"attempt_id": detail_attempt_id, "response_hash": response_hash, "http_status": status_code},
            )
            return SourceAcquisitionSessionResult(
                source_id=source.source_id,
                acquisition_result=detail_acq_res,
                monitoring_fact=monitoring_fact,
                raw_evidence_path=raw_evidence_path,
                agent_evidence_packet=None,
                acquisition_results=all_acq_results,
            )

        try:
            html_text = self._decode_html(raw_bytes, content_type)
            parsed = self.html_parser.parse(html_text, base_url=final_url)
            full_body = parsed.get("body_text", "")
            is_truncated = len(full_body) > 3000
            text_excerpt = full_body[:3000] if is_truncated else full_body

            discovered_attachments = parsed.get("attachments", [])
            (
                attachment_reports,
                parsed_attachment_tables,
                parsed_attachment_pages,
                attachment_audit_facts,
                attachment_acq_results,
            ) = self.attachment_helper.acquire_and_parse(
                attachments_meta=discovered_attachments,
                source_id=source.source_id,
                attempt_id=detail_attempt_id,
                base_url=final_url,
                http_getter=self._execute_http_get,
                parent_attempt_id=detail_attempt_id,
            )

            all_acq_results.extend(attachment_acq_results)
            combined_tables = list(parsed.get("tables", [])) + parsed_attachment_tables

            agent_packet = {
                "source_id": source.source_id,
                "source_name": source.name,
                "url": final_url,
                "attempt_id": detail_attempt_id,
                "response_hash": response_hash,
                "raw_evidence_path": raw_evidence_path,
                "title": parsed.get("title", ""),
                "extracted_tables": combined_tables,
                "html_tables": parsed.get("tables", []),
                "attachment_tables": parsed_attachment_tables,
                "attachment_pages": parsed_attachment_pages,
                "headings": parsed.get("headings", []),
                "attachments": attachment_reports,
                "discovered_attachments": discovered_attachments,
                "text_excerpt": text_excerpt,
                "is_excerpt": is_truncated,
                "total_text_length": len(full_body),
            }

            detail_acq_res = AcquisitionResult(
                attempt_id=detail_attempt_id,
                source_id=source.source_id,
                requested_url=detail_url,
                final_url=final_url,
                timestamp=now_iso,
                acquisition_method="native_http_get",
                technical_status="success",
                http_status=status_code,
                content_type=content_type,
                body_length=body_length,
                response_hash=response_hash,
                error_facts=None,
                etag=etag,
                last_modified=last_modified,
                metadata={
                    "request_type": "detail",
                    "raw_evidence_path": raw_evidence_path,
                    "attachments_found_count": len(discovered_attachments),
                    "attachments_acquired_count": len([a for a in attachment_audit_facts if a.get("status") == "success"]),
                    "attachments_parsed_count": len([a for a in attachment_audit_facts if a.get("parse_status") == "success"]),
                    "attachment_audits": attachment_audit_facts,
                    "physical_requests_count": len(all_acq_results) + 1,
                },
            )
            if listing_result:
                all_acq_results.insert(1, detail_acq_res)
            else:
                all_acq_results.insert(0, detail_acq_res)

            monitoring_fact = MonitoringFact(
                source_id=source.source_id,
                technical_status="success",
                checked_url=final_url,
                checked_at=now_iso,
                metadata={
                    "attempt_id": detail_attempt_id,
                    "response_hash": response_hash,
                    "body_length": body_length,
                    "http_status": status_code,
                    "attachments_count": len(discovered_attachments),
                },
            )
            return SourceAcquisitionSessionResult(
                source_id=source.source_id,
                acquisition_result=detail_acq_res,
                monitoring_fact=monitoring_fact,
                raw_evidence_path=raw_evidence_path,
                agent_evidence_packet=agent_packet,
                acquisition_results=all_acq_results,
            )

        except Exception as parse_err:
            detail_acq_res = AcquisitionResult(
                attempt_id=detail_attempt_id,
                source_id=source.source_id,
                requested_url=detail_url,
                final_url=final_url,
                timestamp=now_iso,
                acquisition_method="native_http_get",
                technical_status="failed",
                http_status=status_code,
                content_type=content_type,
                body_length=body_length,
                response_hash=response_hash,
                error_facts={"parse_error": str(parse_err), "stage": "evidence_parsing"},
                etag=etag,
                last_modified=last_modified,
                metadata={"request_type": "detail", "evidence_parsing_status": "failed", "raw_evidence_path": raw_evidence_path},
            )
            if listing_result:
                all_acq_results.insert(1, detail_acq_res)
            else:
                all_acq_results.insert(0, detail_acq_res)

            monitoring_fact = MonitoringFact(
                source_id=source.source_id,
                technical_status="failed",
                checked_url=final_url,
                checked_at=now_iso,
                metadata={
                    "attempt_id": detail_attempt_id,
                    "response_hash": response_hash,
                    "body_length": body_length,
                    "http_status": status_code,
                    "parse_error": str(parse_err),
                },
            )
            return SourceAcquisitionSessionResult(
                source_id=source.source_id,
                acquisition_result=detail_acq_res,
                monitoring_fact=monitoring_fact,
                raw_evidence_path=raw_evidence_path,
                agent_evidence_packet=None,
                acquisition_results=all_acq_results,
            )


def execute_production_acquisition(
    sources: Optional[List[SourceRecord]] = None,
    data_dir: Union[str, Path] = ".data",
    seed_sources_path: Union[str, Path] = "config/sources.seed.json",
    transport: Any = None,
    registry: Optional[SourceRegistry] = None,
) -> Dict[str, Any]:
    """
    Production Acquisition Entrypoint.
    Owns and drives the mechanical runtime-state lifecycle:
    1. Resolves active sources from SourceRegistry (including local runtime state).
    2. Builds conditional headers from committed baselines and executes acquisition.
    3. Records MonitoringFact for every checked source.
    4. When change acquisition/parsing succeeds, commits new mechanical baseline.
    5. Atomically persists local runtime state to .data/sources.json.
    """
    data_path = Path(data_dir)
    if registry is None:
        registry = SourceRegistry(seed_path=seed_sources_path, data_dir=data_path)

    executor = SourceAcquisitionExecutor(data_dir=data_path, transport=transport)
    return IncrementalAcquisitionHelper.orchestrate_acquisition_and_state(
        executor=executor,
        registry=registry,
        sources=sources,
    )
