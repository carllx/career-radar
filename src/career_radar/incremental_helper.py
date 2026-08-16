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

from .sources import SourceRecord


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

        # 4. Without specific hints, use canonical unique set of all parsed links on the listing page
        if not extracted_urls:
            extracted_urls = IncrementalAcquisitionHelper._extract_matching_urls(
                links, listing_url, pattern=None
            )

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
