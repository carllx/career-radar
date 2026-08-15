"""
Polite HTTP fetcher and attachment downloader with local file caching for Career Radar.
Implements ADR-0004 & Issue #10.
"""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
import requests


class AttachmentAccessError(Exception):
    """Raised when an attachment cannot be downloaded due to captcha, auth, or technical failure."""

    def __init__(self, reason: str, message: str, url: str):
        super().__init__(message)
        self.reason = reason  # e.g. "blocked_by_captcha", "http_error", "content_type_mismatch"
        self.url = url


class AnnouncementFetcher:
    """
    Polite, single-concurrency HTTP fetcher for first-party announcement pages and attachments.
    Caches raw responses in .data/announcements/<url_hash>/ for deterministic replay.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        timeout: int = 15,
        user_agent: Optional[str] = None,
        verify_ssl: bool = True,
    ):
        self.cache_dir = cache_dir or Path(".data/announcements")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36 CareerRadar/0.1.0"
        )

    def _get_url_hash(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    def fetch_announcement_html(
        self, url: str, force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Fetches the HTML of an announcement page with local caching.
        """
        url_hash = self._get_url_hash(url)
        entry_dir = self.cache_dir / url_hash
        entry_dir.mkdir(parents=True, exist_ok=True)

        html_file = entry_dir / "content.html"
        meta_file = entry_dir / "meta.json"

        if html_file.exists() and meta_file.exists() and not force_refresh:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            html_content = html_file.read_text(encoding="utf-8")
            return {
                "url": url,
                "html_content": html_content,
                "fetched_at": meta.get("fetched_at"),
                "status_code": meta.get("status_code", 200),
                "verify_ssl": meta.get("verify_ssl", self.verify_ssl),
                "cached": True,
                "entry_dir": str(entry_dir),
            }

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        resp = requests.get(
            url,
            headers=headers,
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        resp.raise_for_status()

        # Handle encoding properly
        if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"

        html_content = resp.text
        html_file.write_text(html_content, encoding="utf-8")

        meta = {
            "url": url,
            "fetched_at": datetime.now().isoformat(),
            "status_code": resp.status_code,
            "verify_ssl": self.verify_ssl,
            "headers": dict(resp.headers),
        }
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        return {
            "url": url,
            "html_content": html_content,
            "fetched_at": meta["fetched_at"],
            "status_code": resp.status_code,
            "verify_ssl": self.verify_ssl,
            "cached": False,
            "entry_dir": str(entry_dir),
        }

    def download_attachment(
        self,
        attachment_url: str,
        entry_dir: Path,
        attachment_meta: Optional[Dict[str, Any]] = None,
        force_refresh: bool = False,
    ) -> Path:
        """
        Downloads an attachment file into the announcement's cache entry directory.
        Detects captcha challenges and HTML responses for binary attachment requests.
        """
        ext = (attachment_meta.get("extension") if attachment_meta else "") or ".xlsx"
        suggested_name = attachment_meta.get("name") if attachment_meta else ""
        if suggested_name and any(suggested_name.endswith(e) for e in [".xlsx", ".docx", ".pdf"]):
            filename = suggested_name
        else:
            base = os.path.basename(attachment_url.split("?")[0])
            if any(base.endswith(e) for e in [".xlsx", ".docx", ".pdf"]):
                filename = base
            else:
                filename = f"attachment_{hashlib.md5(attachment_url.encode()).hexdigest()[:8]}{ext}"

        target_path = entry_dir / filename

        if target_path.exists() and not force_refresh:
            return target_path

        headers = {"User-Agent": self.user_agent}
        resp = requests.get(
            attachment_url,
            headers=headers,
            timeout=self.timeout,
            stream=True,
            verify=self.verify_ssl,
        )
        resp.raise_for_status()

        # Read content bytes
        first_chunk = resp.raw.read(8192) if hasattr(resp, "raw") else b""
        if not first_chunk:
            chunks = []
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    chunks.append(chunk)
            content_bytes = b"".join(chunks)
        else:
            remaining = resp.raw.read()
            content_bytes = first_chunk + remaining

        content_type = resp.headers.get("content-type", "").lower()

        # Check for captcha or HTML redirection when expecting binary attachment
        is_html_content = (
            "text/html" in content_type
            or content_bytes.lstrip().startswith(b"<!DOCTYPE html")
            or content_bytes.lstrip().startswith(b"<html")
        )

        is_captcha_challenge = (
            b"createimage.jsp" in content_bytes.lower()
            or b"codeimg" in content_bytes.lower()
            or b"codevalue" in content_bytes.lower()
            or b"captcha" in content_bytes.lower()
            or b"anti-bot" in content_bytes.lower()
            or b"\xd1\xe9\xd6\xa4\xc2\xeb" in content_bytes  # "验证码" in GBK/GB2312
            or b"\xe9\xaa\x8c\xe8\xaf\x81\xe7\xa0\x81" in content_bytes  # "验证码" in UTF-8
        )

        if is_html_content and is_captcha_challenge:
            raise AttachmentAccessError(
                reason="blocked_by_captcha",
                message=f"Attachment download blocked by captcha challenge at {attachment_url}",
                url=attachment_url,
            )

        if is_html_content and ext in {".xlsx", ".docx", ".pdf"}:
            raise AttachmentAccessError(
                reason="content_type_mismatch",
                message=f"Expected binary attachment ({ext}) but received HTML page from {attachment_url}",
                url=attachment_url,
            )

        # Check content disposition if present
        cd = resp.headers.get("content-disposition", "")
        if "filename=" in cd:
            import urllib.parse
            fname_part = cd.split("filename=")[-1].strip("\"'; ")
            fname_part = urllib.parse.unquote(fname_part)
            if fname_part and any(fname_part.endswith(e) for e in [".xlsx", ".docx", ".pdf"]):
                target_path = entry_dir / fname_part

        with open(target_path, "wb") as f:
            f.write(content_bytes)

        return target_path
