"""
Deterministic attachment acquisition and multi-format parsing helper.
Respects CONTEXT.md, ADR-0002, Spec #20, Issue #21 and Issue #22.

Security & Lineage Invariants:
1. Prevent path traversal attacks from untrusted remote filenames / headers.
2. Prevent same-name attachment overwrite collisions using deterministic hashing.
3. Record physical HTTP AcquisitionResult for every attachment download request.
"""

from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin
import uuid

from .acquisition_models import AcquisitionResult
from .parser import AttachmentParser

SUPPORTED_ATTACHMENT_EXTENSIONS = (".xlsx", ".docx", ".pdf", ".xls", ".doc")


class AttachmentAcquisitionHelper:
    """
    Handles safe attachment filename resolution, disk persistence, physical AcquisitionResult creation,
    and deterministic parsing.
    """

    def __init__(self, evidence_dir: Path, attachment_parser: Optional[AttachmentParser] = None):
        self.evidence_dir = evidence_dir
        self.attachment_parser = attachment_parser or AttachmentParser()

    def sanitize_filename(self, raw_name: str) -> str:
        """
        Sanitizes untrusted filenames from remote servers to prevent path traversal (../, ..\\, absolute paths).
        """
        if not raw_name:
            return ""
        # Remove any leading path prefixes, slashes, or backslashes
        cleaned = re.split(r"[\\/]", raw_name)[-1].strip()
        # Remove null bytes or dangerous characters
        cleaned = re.sub(r"[\x00\r\n\t]", "", cleaned)
        # Ensure no residual relative path traversal
        while cleaned.startswith("..") or cleaned.startswith("."):
            cleaned = cleaned.lstrip(".")
        return cleaned.strip()

    def determine_filename(
        self, att_url: str, att_meta: Dict[str, Any], headers: Dict[str, str], seen_filenames: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Determines target filename for attachment from metadata, Content-Disposition, or URL.
        Guarantees path traversal prevention and same-name collision disambiguation.
        """
        candidate = ""

        # 1. Content-Disposition
        cd = headers.get("Content-Disposition") or headers.get("content-disposition", "")
        if cd:
            if "filename*=" in cd:
                part = cd.split("filename*=")[-1].split(";")[0].strip("\"' ")
                if "''" in part:
                    part = part.split("''")[-1]
                extracted = unquote(part)
                clean_ext = self.sanitize_filename(extracted)
                if clean_ext and any(clean_ext.lower().endswith(ext) for ext in SUPPORTED_ATTACHMENT_EXTENSIONS):
                    candidate = clean_ext
            elif "filename=" in cd:
                part = cd.split("filename=")[-1].split(";")[0].strip("\"' ")
                extracted = unquote(part)
                clean_ext = self.sanitize_filename(extracted)
                if clean_ext and any(clean_ext.lower().endswith(ext) for ext in SUPPORTED_ATTACHMENT_EXTENSIONS):
                    candidate = clean_ext

        # 2. Link text / title in metadata
        if not candidate:
            name = self.sanitize_filename(att_meta.get("name", ""))
            if name and any(name.lower().endswith(ext) for ext in SUPPORTED_ATTACHMENT_EXTENSIONS):
                candidate = name

        # 3. URL path basename
        if not candidate:
            base = self.sanitize_filename(os.path.basename(att_url.split("?")[0]))
            if any(base.lower().endswith(ext) for ext in SUPPORTED_ATTACHMENT_EXTENSIONS):
                candidate = base

        # 4. Fallback and collision disambiguation
        url_hash_short = hashlib.sha256(att_url.encode("utf-8")).hexdigest()[:8]
        if not candidate:
            ext = att_meta.get("extension", ".xlsx") or ".xlsx"
            candidate = f"attachment_{url_hash_short}{ext}"

        if seen_filenames is not None:
            if candidate in seen_filenames and seen_filenames[candidate] != att_url:
                stem, ext = os.path.splitext(candidate)
                candidate = f"{stem}_{url_hash_short}{ext}"
            seen_filenames[candidate] = att_url

        return candidate

    def acquire_and_parse(
        self,
        attachments_meta: List[Dict[str, Any]],
        source_id: str,
        attempt_id: str,
        base_url: str,
        http_getter: Any,
        parent_attempt_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[AcquisitionResult]]:
        reports: List[Dict[str, Any]] = []
        tables: List[Dict[str, Any]] = []
        pages: List[Dict[str, Any]] = []
        audits: List[Dict[str, Any]] = []
        physical_acq_results: List[AcquisitionResult] = []
        seen_filenames: Dict[str, str] = {}

        target_dir = self.evidence_dir / source_id / "attachments" / attempt_id
        target_dir.mkdir(parents=True, exist_ok=True)

        for idx, att in enumerate(attachments_meta):
            att_url = att.get("url", "")
            if not att_url:
                continue

            full_url = urljoin(base_url, att_url) if base_url else att_url
            ext = att.get("extension", "")
            child_attempt_id = f"{attempt_id}_att{idx+1}_{uuid.uuid4().hex[:6]}"
            now_iso = datetime.now().isoformat()

            if not att.get("supported", True) or ext in {".xls", ".doc"}:
                reports.append({
                    "name": att.get("name", f"attachment_{idx}"),
                    "url": full_url,
                    "extension": ext,
                    "status": "unsupported_legacy_format",
                    "error": f"Legacy format '{ext}' is not supported by deterministic parser.",
                })
                audits.append({
                    "url": full_url,
                    "status": "unsupported_legacy_format",
                    "extension": ext,
                    "error": f"Legacy format '{ext}' not supported.",
                })
                continue

            # Execute physical HTTP request for attachment
            try:
                resp = http_getter(full_url)
            except Exception as net_err:
                att_acq_res = AcquisitionResult(
                    attempt_id=child_attempt_id,
                    source_id=source_id,
                    requested_url=full_url,
                    final_url=full_url,
                    timestamp=now_iso,
                    acquisition_method="native_http_get",
                    technical_status="failed",
                    http_status=None,
                    content_type=None,
                    body_length=0,
                    response_hash="",
                    error_facts={
                        "error": str(net_err),
                        "exception_class": type(net_err).__name__,
                        "stage": "attachment_transport",
                    },
                    metadata={"request_type": "attachment", "parent_attempt_id": parent_attempt_id or attempt_id},
                )
                physical_acq_results.append(att_acq_res)
                reports.append({
                    "name": att.get("name", f"attachment_{idx}"),
                    "url": full_url,
                    "extension": ext,
                    "status": "failed",
                    "error": str(net_err),
                    "exception_class": type(net_err).__name__,
                })
                audits.append({"url": full_url, "status": "failed", "error": str(net_err)})
                continue

            status = getattr(resp, "status_code", 200)
            headers = dict(getattr(resp, "headers", {}) or {})
            content_type = headers.get("Content-Type", headers.get("content-type", ""))
            raw_bytes = getattr(resp, "content", b"") or (resp.text.encode("utf-8") if hasattr(resp, "text") else b"")
            body_len = len(raw_bytes)
            file_hash = hashlib.sha256(raw_bytes).hexdigest()
            etag = headers.get("ETag") or headers.get("etag")
            last_modified = headers.get("Last-Modified") or headers.get("last-modified")

            if status >= 400:
                att_acq_res = AcquisitionResult(
                    attempt_id=child_attempt_id,
                    source_id=source_id,
                    requested_url=full_url,
                    final_url=str(getattr(resp, "url", full_url) or full_url),
                    timestamp=now_iso,
                    acquisition_method="native_http_get",
                    technical_status="failed",
                    http_status=status,
                    content_type=content_type,
                    body_length=body_len,
                    response_hash=file_hash,
                    error_facts={"http_status": status, "error": f"HTTP {status}"},
                    etag=etag,
                    last_modified=last_modified,
                    metadata={"request_type": "attachment", "parent_attempt_id": parent_attempt_id or attempt_id},
                )
                physical_acq_results.append(att_acq_res)
                reports.append({
                    "name": att.get("name", f"attachment_{idx}"),
                    "url": full_url,
                    "extension": ext,
                    "status": "failed",
                    "http_status": status,
                    "error": f"HTTP {status}",
                    "body_length": body_len,
                    "attachment_hash": file_hash,
                })
                audits.append({
                    "url": full_url,
                    "status": "failed",
                    "http_status": status,
                    "error": f"HTTP {status}",
                })
                continue

            # Safe filename determination preventing traversal and collision
            filename = self.determine_filename(full_url, att, headers, seen_filenames=seen_filenames)
            file_path = target_dir / filename
            file_path.write_bytes(raw_bytes)
            local_path = str(file_path)

            att_acq_res = AcquisitionResult(
                attempt_id=child_attempt_id,
                source_id=source_id,
                requested_url=full_url,
                final_url=str(getattr(resp, "url", full_url) or full_url),
                timestamp=now_iso,
                acquisition_method="native_http_get",
                technical_status="success",
                http_status=status,
                content_type=content_type,
                body_length=body_len,
                response_hash=file_hash,
                error_facts=None,
                etag=etag,
                last_modified=last_modified,
                metadata={
                    "request_type": "attachment",
                    "parent_attempt_id": parent_attempt_id or attempt_id,
                    "local_evidence_path": local_path,
                    "filename": filename,
                },
            )
            physical_acq_results.append(att_acq_res)

            audit_item = {
                "url": full_url,
                "status": "success",
                "http_status": status,
                "content_type": content_type,
                "body_length": body_len,
                "attachment_hash": file_hash,
                "local_evidence_path": local_path,
                "filename": filename,
                "extension": ext,
                "attempt_id": child_attempt_id,
            }

            try:
                parsed = self.attachment_parser.parse_file(file_path)
                has_err = any(t.get("status") == "error" for t in parsed)
                if has_err:
                    err_msg = next((t.get("error", "Parse error") for t in parsed if t.get("status") == "error"), "Parse error")
                    att_acq_res.technical_status = "failed"
                    att_acq_res.error_facts = {
                        "parse_error": err_msg,
                        "stage": "attachment_parsing",
                    }
                    att_acq_res.metadata["evidence_parsing_status"] = "failed"
                    reports.append({
                        "name": filename,
                        "url": full_url,
                        "extension": ext,
                        "status": "failed",
                        "error": err_msg,
                        "body_length": body_len,
                        "attachment_hash": file_hash,
                        "local_evidence_path": local_path,
                    })
                    audit_item["parse_status"] = "failed"
                    audit_item["parse_error"] = err_msg
                else:
                    for tbl in parsed:
                        if tbl.get("file_type") == "pdf" and "pages" in tbl:
                            pages.extend(tbl.get("pages", []))
                        if tbl.get("rows"):
                            tables.append(tbl)
                    reports.append({
                        "name": filename,
                        "url": full_url,
                        "extension": ext,
                        "status": "success",
                        "body_length": body_len,
                        "attachment_hash": file_hash,
                        "local_evidence_path": local_path,
                        "tables_count": len([t for t in parsed if t.get("rows")]),
                        "pages_count": len(pages),
                    })
                    audit_item["parse_status"] = "success"
            except Exception as p_err:
                att_acq_res.technical_status = "failed"
                att_acq_res.error_facts = {
                    "parse_error": str(p_err),
                    "exception_class": type(p_err).__name__,
                    "stage": "attachment_parsing",
                }
                att_acq_res.metadata["evidence_parsing_status"] = "failed"
                audit_item["parse_status"] = "failed"
                audit_item["parse_error"] = str(p_err)
                reports.append({
                    "name": filename,
                    "url": full_url,
                    "extension": ext,
                    "status": "failed",
                    "error": str(p_err),
                    "body_length": body_len,
                    "attachment_hash": file_hash,
                    "local_evidence_path": local_path,
                })

            audits.append(audit_item)

        return reports, tables, pages, audits, physical_acq_results
