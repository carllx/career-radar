"""
Listing page mechanical link selector and helper for multi-hop acquisition.
Respects CONTEXT.md, ADR-0002, Spec #20, Issue #21 and Issue #22.
Zero semantic job keyword filtering (no "招聘"/"教师" heuristics).
"""

from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from .acquisition_models import AcquisitionResult
from .incremental_helper import IncrementalAcquisitionHelper
from .sources import MonitoringFact, SourceRecord


class ListingAcquisitionHelper:
    """
    Handles listing acquisition, evidence persistence, and mechanical detail-URL selection.
    Requires explicit configuration hints; never falls back to arbitrary unconfigured links.
    """

    @staticmethod
    def select_detail_url(
        listing_parsed: Dict[str, Any],
        source: SourceRecord,
        listing_url: str,
    ) -> Optional[str]:
        selected_urls = IncrementalAcquisitionHelper.extract_selected_urls(
            listing_parsed, source, listing_url
        )
        return selected_urls[0] if selected_urls else None

    @staticmethod
    def acquire_listing_page(
        source: SourceRecord,
        session_id: str,
        evidence_dir: Path,
        http_getter: Any,
        decode_html_fn: Any,
        html_parser: Any,
        conditional_headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[Optional[str], AcquisitionResult, MonitoringFact, Optional[str], bool, Optional[str]]:
        """
        Returns: (detail_url, listing_acq_res, monitoring_fact, raw_listing_path, is_unchanged, observed_fingerprint)
        """
        listing_attempt_id = f"{session_id}_listing"
        listing_url = source.base_url
        now_iso = datetime.now().isoformat()

        try:
            listing_resp = http_getter(listing_url, headers=conditional_headers)
        except Exception as listing_net_err:
            acq_res = AcquisitionResult(
                attempt_id=listing_attempt_id,
                source_id=source.source_id,
                requested_url=listing_url,
                final_url=listing_url,
                timestamp=now_iso,
                acquisition_method="native_http_get",
                technical_status="failed",
                http_status=None,
                content_type=None,
                body_length=0,
                response_hash="",
                error_facts={
                    "error": str(listing_net_err),
                    "exception_class": type(listing_net_err).__name__,
                    "stage": "listing_transport",
                },
                metadata={"request_type": "listing"},
            )
            monitoring_fact = MonitoringFact(
                source_id=source.source_id,
                technical_status="failed",
                checked_url=listing_url,
                checked_at=now_iso,
                metadata={"attempt_id": listing_attempt_id, "error": str(listing_net_err)},
            )
            return None, acq_res, monitoring_fact, None, False, None, [], []

        list_status = getattr(listing_resp, "status_code", 200)
        list_final_url = str(getattr(listing_resp, "url", listing_url) or listing_url)
        list_headers = dict(getattr(listing_resp, "headers", {}) or {})
        list_content_type = list_headers.get("Content-Type", list_headers.get("content-type", "text/html"))

        etag = list_headers.get("ETag") or list_headers.get("etag")
        last_modified = list_headers.get("Last-Modified") or list_headers.get("last-modified")

        # 1. Handle HTTP 304 Not Modified
        if list_status == 304:
            listing_acq_res = AcquisitionResult(
                attempt_id=listing_attempt_id,
                source_id=source.source_id,
                requested_url=listing_url,
                final_url=list_final_url,
                timestamp=now_iso,
                acquisition_method="native_http_get",
                technical_status="success",
                http_status=304,
                content_type=list_content_type,
                body_length=0,
                response_hash="",
                etag=etag,
                last_modified=last_modified,
                metadata={"request_type": "listing", "unchanged": True},
            )
            monitoring_fact = MonitoringFact(
                source_id=source.source_id,
                technical_status="success",
                checked_url=list_final_url,
                checked_at=now_iso,
                metadata={"attempt_id": listing_attempt_id, "http_status": 304, "unchanged": True},
            )
            return None, listing_acq_res, monitoring_fact, None, True, None, [], []

        list_raw_bytes = getattr(listing_resp, "content", b"") or (listing_resp.text.encode("utf-8") if hasattr(listing_resp, "text") else b"")
        list_body_len = len(list_raw_bytes)
        list_hash = hashlib.sha256(list_raw_bytes).hexdigest()

        source_evidence_dir = evidence_dir / source.source_id
        source_evidence_dir.mkdir(parents=True, exist_ok=True)
        listing_file = source_evidence_dir / f"{listing_attempt_id}.html"
        listing_file.write_bytes(list_raw_bytes)
        raw_listing_path = str(listing_file)

        listing_acq_res = AcquisitionResult(
            attempt_id=listing_attempt_id,
            source_id=source.source_id,
            requested_url=listing_url,
            final_url=list_final_url,
            timestamp=now_iso,
            acquisition_method="native_http_get",
            technical_status="success" if list_status < 400 else "failed",
            http_status=list_status,
            content_type=list_content_type,
            body_length=list_body_len,
            response_hash=list_hash,
            error_facts={"http_status": list_status, "error": f"HTTP {list_status}"} if list_status >= 400 else None,
            etag=etag,
            last_modified=last_modified,
            metadata={"request_type": "listing", "raw_evidence_path": raw_listing_path},
        )

        if list_status >= 400:
            monitoring_fact = MonitoringFact(
                source_id=source.source_id,
                technical_status="failed",
                checked_url=list_final_url,
                checked_at=now_iso,
                metadata={"attempt_id": listing_attempt_id, "http_status": list_status},
            )
            return None, listing_acq_res, monitoring_fact, raw_listing_path, False, None, [], []

        try:
            listing_html_text = decode_html_fn(list_raw_bytes, list_content_type)
            listing_parsed = html_parser.parse(listing_html_text, base_url=list_final_url)
            selected_urls = IncrementalAcquisitionHelper.extract_selected_urls(
                listing_parsed, source, list_final_url
            )
            observed_fingerprint = IncrementalAcquisitionHelper.compute_listing_fingerprint(
                listing_parsed, source, list_final_url
            )
            is_unchanged = IncrementalAcquisitionHelper.is_source_unchanged(
                source, observed_fingerprint=observed_fingerprint, observed_hash=list_hash
            )
            committed_urls = (source.metadata or {}).get("committed_listing_urls")
            new_urls = IncrementalAcquisitionHelper.diff_urls(selected_urls, committed_urls)
            detail_url = selected_urls[0] if selected_urls else None
        except Exception as parse_list_err:
            listing_acq_res.technical_status = "failed"
            listing_acq_res.error_facts = {"parse_error": str(parse_list_err), "stage": "listing_parsing"}
            monitoring_fact = MonitoringFact(
                source_id=source.source_id,
                technical_status="failed",
                checked_url=list_final_url,
                checked_at=now_iso,
                metadata={"attempt_id": listing_attempt_id, "parse_error": str(parse_list_err)},
            )
            return None, listing_acq_res, monitoring_fact, raw_listing_path, False, None, [], []

        monitoring_fact = MonitoringFact(
            source_id=source.source_id,
            technical_status="success",
            checked_url=list_final_url,
            checked_at=now_iso,
            metadata={
                "attempt_id": listing_attempt_id,
                "detail_discovered": bool(detail_url),
                "unchanged": is_unchanged,
                "observed_fingerprint": observed_fingerprint,
                "response_hash": list_hash,
                "selected_urls_count": len(selected_urls),
                "new_urls_count": len(new_urls),
            },
        )
        listing_acq_res.metadata["observed_fingerprint"] = observed_fingerprint
        listing_acq_res.metadata["selected_urls"] = selected_urls
        listing_acq_res.metadata["new_urls"] = new_urls
        listing_acq_res.metadata["unchanged"] = is_unchanged
        return detail_url, listing_acq_res, monitoring_fact, raw_listing_path, is_unchanged, observed_fingerprint, selected_urls, new_urls

    @staticmethod
    def acquire_all_details(
        source: SourceRecord,
        new_urls: List[str],
        session_id: str,
        listing_acq_res: AcquisitionResult,
        monitoring_fact: MonitoringFact,
        raw_listing_path: Optional[str],
        detail_acquirer: Any,
    ) -> Any:
        """
        Acquires every new detail URL mechanically.
        Maintains strict invariant: failure of ANY new detail prevents full baseline advance.
        """
        from .acquisition_models import SourceAcquisitionSessionResult

        all_acq_results: List[AcquisitionResult] = [listing_acq_res]
        all_agent_packets: List[Dict[str, Any]] = []
        overall_status = "success"

        for idx, u in enumerate(new_urls):
            sub_session_id = f"{session_id}_d{idx+1}"
            detail_session = detail_acquirer(
                source=source,
                detail_url=u,
                session_id=sub_session_id,
                listing_result=None,
            )
            all_acq_results.extend(detail_session.acquisition_results)
            if detail_session.agent_evidence_packet:
                all_agent_packets.append(detail_session.agent_evidence_packet)
            if detail_session.acquisition_result.technical_status != "success":
                overall_status = "failed"

        primary_packet = all_agent_packets[0] if all_agent_packets else None
        if overall_status == "failed":
            monitoring_fact.technical_status = "failed"

        return SourceAcquisitionSessionResult(
            source_id=source.source_id,
            acquisition_result=listing_acq_res,
            monitoring_fact=monitoring_fact,
            raw_evidence_path=raw_listing_path,
            agent_evidence_packet=primary_packet,
            agent_evidence_packets=all_agent_packets,
            acquisition_results=all_acq_results,
        )
