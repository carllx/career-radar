"""
Incremental Change Detection & Mechanical Fingerprinting for Career Radar.
Respects CONTEXT.md, ADR-0002, Spec #20, Issue #21, #22, and #23.
Zero semantic recruitment keyword heuristics.
"""

import hashlib
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from .sources import SourceRecord, SourceRegistry


class IncrementalAcquisitionHelper:
    """
    Mechanically determines conditional headers and stable listing fingerprints.
    Distinguishes observed candidates from committed baselines.
    """

    @staticmethod
    def build_conditional_headers(source: SourceRecord) -> Dict[str, str]:
        """
        Builds HTTP conditional request headers from committed baseline metadata.
        """
        headers: Dict[str, str] = {}
        metadata = source.metadata or {}

        # Prioritize committed baseline, fall back to legacy/generic metadata if present
        etag = metadata.get("committed_etag") or metadata.get("etag")
        last_modified = metadata.get("committed_last_modified") or metadata.get("last_modified")

        if etag:
            headers["If-None-Match"] = str(etag).strip()
        if last_modified:
            headers["If-Modified-Since"] = str(last_modified).strip()

        return headers

    @classmethod
    def _extract_matching_urls(
        cls,
        links: List[Dict[str, Any]],
        listing_url: str,
        pattern: Optional[str] = None,
    ) -> List[str]:
        results: List[str] = []
        for lk in links:
            u = lk.get("url", "")
            if not u:
                continue
            if pattern is None or re.search(pattern, u):
                results.append(urljoin(listing_url, u))
        return results

    @staticmethod
    def compute_listing_fingerprint(
        listing_parsed: Dict[str, Any],
        source: SourceRecord,
        listing_url: str,
    ) -> str:
        """
        Computes a stable deterministic SHA-256 fingerprint from mechanically selected listing links.
        Canonical, sorted, unique URL set ensures order-only DOM noise does not trigger false change.
        Zero semantic keyword filtering (no '招聘' / '教师' heuristics).
        """
        links = listing_parsed.get("links", [])
        metadata = source.metadata or {}

        extracted_urls: List[str] = []

        # 1. Configured regex / pattern hint
        pattern_hint = metadata.get("detail_url_pattern") or metadata.get("url_pattern")
        if pattern_hint:
            extracted_urls = IncrementalAcquisitionHelper._extract_matching_urls(
                links, listing_url, pattern=pattern_hint
            )

        # 2. Configured explicit detail_url
        elif metadata.get("detail_url"):
            extracted_urls.append(urljoin(listing_url, metadata["detail_url"]))

        # 3. Configured link index
        elif metadata.get("detail_link_index") is not None:
            idx = metadata.get("detail_link_index")
            if isinstance(idx, int) and 0 <= idx < len(links):
                u = links[idx].get("url", "")
                if u:
                    extracted_urls.append(urljoin(listing_url, u))

        # 4. Without specific hints, no explicit selection exists: do not fingerprint arbitrary links
        if not extracted_urls:
            return None

        # Canonicalize: sort unique URLs
        canonical_urls = sorted(list(set(extracted_urls)))
        fingerprint_payload = json.dumps(canonical_urls, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()

    @staticmethod
    def is_source_unchanged(
        source: SourceRecord,
        observed_fingerprint: Optional[str] = None,
        observed_hash: Optional[str] = None,
        http_status: Optional[int] = None,
    ) -> bool:
        """
        Mechanically compares observed state with committed baseline.
        """
        if http_status == 304:
            return True

        metadata = source.metadata or {}
        committed_fingerprint = metadata.get("committed_listing_fingerprint") or metadata.get("listing_fingerprint")
        if committed_fingerprint and observed_fingerprint:
            return committed_fingerprint == observed_fingerprint

        committed_hash = metadata.get("committed_response_hash") or metadata.get("response_hash")
        if committed_hash and observed_hash:
            return committed_hash == observed_hash

        return False

    @staticmethod
    def should_commit_baseline(
        session_result: Any,
    ) -> bool:
        """
        Determines if an acquisition session succeeded sufficiently to advance the committed baseline.
        Rule:
        - If unchanged (304 or fingerprint equal), baseline is already committed/preserved.
        - If changed or new, detail and required attachments must have technical_status == 'success'.
        - If any required physical HTTP request failed or parser failed, returns False.
        """
        if session_result.monitoring_fact.technical_status != "success":
            return False

        # If any physical acquisition in the session failed, do not advance baseline
        for acq in session_result.acquisition_results:
            if acq.technical_status != "success":
                return False

        return True

    @staticmethod
    def extract_baseline_fields(
        session_result: Any,
    ) -> Dict[str, Any]:
        """
        Extracts mechanical baseline fields to commit from a successful session.
        """
        fields: Dict[str, Any] = {}
        for acq in session_result.acquisition_results:
            req_type = (acq.metadata or {}).get("request_type")
            if req_type == "listing":
                observed_fp = (acq.metadata or {}).get("observed_fingerprint")
                if observed_fp:
                    fields["listing_fingerprint"] = observed_fp
                if acq.etag:
                    fields["etag"] = acq.etag
                if acq.last_modified:
                    fields["last_modified"] = acq.last_modified
            elif req_type == "detail":
                if not fields.get("listing_fingerprint"):
                    # Direct source
                    if acq.response_hash:
                        fields["response_hash"] = acq.response_hash
                if acq.etag and not fields.get("etag"):
                    fields["etag"] = acq.etag
                if acq.last_modified and not fields.get("last_modified"):
                    fields["last_modified"] = acq.last_modified
        return fields

    @staticmethod
    def orchestrate_acquisition_and_state(
        executor: Any,
        registry: SourceRegistry,
        sources: Optional[List[SourceRecord]] = None,
    ) -> Dict[str, Any]:
        """
        Orchestrates acquisition execution with mechanical state tracking:
        1. Resolves target sources from registry.
        2. Executes source acquisition for each source.
        3. Records technical MonitoringFact.
        4. Commits mechanical baseline on successful changed runs.
        5. Atomically saves local runtime state to disk.
        """
        if sources is not None:
            target_sources = []
            for s in sources:
                existing = registry.get_source(s.source_id)
                if existing:
                    target_sources.append(existing)
                else:
                    registry.local_sources[s.source_id] = s
                    target_sources.append(s)
        else:
            target_sources = registry.get_active_sources()

        session_results: List[Any] = []
        all_acquisition_results: List[Any] = []

        for src in target_sources:
            # Ensure we use latest source state from registry
            current_src = registry.get_source(src.source_id) or src
            res = executor.acquire_source(current_src)
            session_results.append(res)
            all_acquisition_results.extend(res.acquisition_results)

            # Record technical fact first
            registry.record_monitoring_fact(res.monitoring_fact)

            # Then commit baseline if eligible so baseline fields are preserved
            if IncrementalAcquisitionHelper.should_commit_baseline(res):
                baseline_fields = IncrementalAcquisitionHelper.extract_baseline_fields(res)
                if baseline_fields:
                    registry.commit_mechanical_baseline(
                        source_id=src.source_id,
                        listing_fingerprint=baseline_fields.get("listing_fingerprint"),
                        response_hash=baseline_fields.get("response_hash"),
                        etag=baseline_fields.get("etag"),
                        last_modified=baseline_fields.get("last_modified"),
                    )

        registry.save_local_state()

        return {
            "session_results": session_results,
            "acquisition_results": all_acquisition_results,
            "monitoring_facts": [r.monitoring_fact for r in session_results],
            "agent_evidence_packets": [
                r.agent_evidence_packet for r in session_results if r.agent_evidence_packet is not None
            ],
        }
