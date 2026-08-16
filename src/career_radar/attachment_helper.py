"""
Deterministic attachment acquisition and multi-format parsing helper.
Respects CONTEXT.md, ADR-0002, Spec #20 and Issue #22.
"""

from datetime import datetime
import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin

from .parser import AttachmentParser


class AttachmentAcquisitionHelper:
    """
    Handles attachment filename resolution, disk persistence, and deterministic parsing.
    """

    def __init__(self, evidence_dir: Path, attachment_parser: Optional[AttachmentParser] = None):
        self.evidence_dir = evidence_dir
        self.attachment_parser = attachment_parser or AttachmentParser()

    def determine_filename(
        self, att_url: str, att_meta: Dict[str, Any], headers: Dict[str, str]
    ) -> str:
        cd = headers.get("Content-Disposition") or headers.get("content-disposition", "")
        if cd:
            if "filename*=" in cd:
                part = cd.split("filename*=")[-1].split(";")[0].strip("\"' ")
                if "''" in part:
                    part = part.split("''")[-1]
                extracted = unquote(part)
                if any(extracted.lower().endswith(ext) for ext in [".xlsx", ".docx", ".pdf", ".xls", ".doc"]):
                    return extracted
            elif "filename=" in cd:
                part = cd.split("filename=")[-1].split(";")[0].strip("\"' ")
                extracted = unquote(part)
                if any(extracted.lower().endswith(ext) for ext in [".xlsx", ".docx", ".pdf", ".xls", ".doc"]):
                    return extracted

        name = att_meta.get("name", "")
        if name and any(name.lower().endswith(ext) for ext in [".xlsx", ".docx", ".pdf", ".xls", ".doc"]):
            return name

        base = os.path.basename(att_url.split("?")[0])
        if any(base.lower().endswith(ext) for ext in [".xlsx", ".docx", ".pdf", ".xls", ".doc"]):
            return base

        ext = att_meta.get("extension", ".xlsx") or ".xlsx"
        url_hash = hashlib.sha256(att_url.encode("utf-8")).hexdigest()[:8]
        return f"attachment_{url_hash}{ext}"

    def acquire_and_parse(
        self,
        attachments_meta: List[Dict[str, Any]],
        source_id: str,
        attempt_id: str,
        base_url: str,
        http_getter: Any,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        reports: List[Dict[str, Any]] = []
        tables: List[Dict[str, Any]] = []
        pages: List[Dict[str, Any]] = []
        audits: List[Dict[str, Any]] = []

        target_dir = self.evidence_dir / source_id / "attachments" / attempt_id
        target_dir.mkdir(parents=True, exist_ok=True)

        for idx, att in enumerate(attachments_meta):
            att_url = att.get("url", "")
            if not att_url:
                continue

            full_url = urljoin(base_url, att_url) if base_url else att_url
            ext = att.get("extension", "")

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

            try:
                resp = http_getter(full_url)
            except Exception as net_err:
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

            if status >= 400:
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

            filename = self.determine_filename(full_url, att, headers)
            file_path = target_dir / filename
            file_path.write_bytes(raw_bytes)
            local_path = str(file_path)

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
            }

            try:
                parsed = self.attachment_parser.parse_file(file_path)
                has_err = any(t.get("status") == "error" for t in parsed)
                if has_err:
                    err_msg = next((t.get("error", "Parse error") for t in parsed if t.get("status") == "error"), "Parse error")
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

        return reports, tables, pages, audits
