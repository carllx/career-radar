"""
Announcement and attachment slicing extractor for Career Radar MVP-1.
Implements Issue #10: slices 1 Announcement with attachment tables into N SourceObservations.
Preserves raw cells and provenance without applying candidate-matching business rules.
Strictly prohibits fake-observation fallback and hardcoded unknown facts.
"""

from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .fetcher import AnnouncementFetcher, AttachmentAccessError
from .models import SourceObservation
from .parser import AttachmentParser, HTMLAnnouncementParser


def fetch_and_extract_first_party_announcement(
    announcement_url: str,
    source_id: str,
    source_name: str,
    cache_dir: Optional[Path] = None,
    verify_ssl: bool = True,
    recruiting_organization: Optional[str] = None,
) -> Tuple[List[SourceObservation], Dict[str, Any]]:
    """
    Fetches a live first-party announcement page, downloads its discovered attachments,
    and slices them into discrete SourceObservations without business rules.
    Returns (observations, extraction_report).
    """
    cache_dir = cache_dir or Path(".data/announcements")
    fetcher = AnnouncementFetcher(cache_dir=cache_dir, verify_ssl=verify_ssl)
    fetched = fetcher.fetch_announcement_html(announcement_url)

    html_parser = HTMLAnnouncementParser()
    parsed_meta = html_parser.parse(fetched["html_content"], base_url=announcement_url)

    entry_dir = Path(fetched["entry_dir"])
    downloaded_attachments = []
    attachment_reports = []

    for att in parsed_meta["attachments"]:
        if not att.get("supported", True):
            attachment_reports.append({
                "name": att.get("name"),
                "url": att.get("url"),
                "extension": att.get("extension"),
                "status": "unsupported_legacy_format",
                "error": f"Legacy format {att.get('extension')} is not supported.",
            })
            continue

        try:
            local_att = fetcher.download_attachment(
                att["url"], entry_dir=entry_dir, attachment_meta=att
            )
            downloaded_attachments.append(local_att)
            attachment_reports.append({
                "name": att.get("name"),
                "url": att.get("url"),
                "extension": att.get("extension"),
                "status": "downloaded",
                "local_path": str(local_att),
            })
        except AttachmentAccessError as e:
            attachment_reports.append({
                "name": att.get("name"),
                "url": att.get("url"),
                "extension": att.get("extension"),
                "status": e.reason,
                "error": str(e),
            })
        except Exception as e:
            attachment_reports.append({
                "name": att.get("name"),
                "url": att.get("url"),
                "extension": att.get("extension"),
                "status": "download_failed",
                "error": str(e),
            })

    extractor = AnnouncementExtractor(cache_dir=cache_dir)
    observations = extractor.extract_from_html_and_attachments(
        html_content=fetched["html_content"],
        source_url=announcement_url,
        source_id=source_id,
        source_name=source_name,
        local_attachment_paths=downloaded_attachments,
        recruiting_organization=recruiting_organization,
        observed_at=fetched.get("fetched_at"),
    )

    has_captcha = any(r.get("status") == "blocked_by_captcha" for r in attachment_reports)
    has_type_mismatch = any(r.get("status") == "content_type_mismatch" for r in attachment_reports)

    if has_captcha:
        extraction_completeness = "incomplete"
        attachment_access = "blocked_by_captcha"
    elif has_type_mismatch:
        extraction_completeness = "incomplete"
        attachment_access = "content_type_mismatch"
    elif downloaded_attachments and not observations:
        extraction_completeness = "incomplete_or_no_jobs"
        attachment_access = "success"
    elif not downloaded_attachments and parsed_meta["attachments"]:
        extraction_completeness = "incomplete"
        attachment_access = "failed"
    else:
        extraction_completeness = "complete" if observations else "no_attachments"
        attachment_access = "success" if downloaded_attachments else "none"

    report = {
        "announcement_title": parsed_meta["title"],
        "source_url": announcement_url,
        "source_id": source_id,
        "source_name": source_name,
        "recruiting_organization": recruiting_organization,
        "verify_ssl": verify_ssl,
        "attachment_access": attachment_access,
        "extraction_completeness": extraction_completeness,
        "attachments": attachment_reports,
        "observations_count": len(observations),
    }

    return observations, report



class AnnouncementExtractor:
    """
    Slices first-party announcement HTML and attachment tables into discrete SourceObservations.
    If attachments fail or contain no concrete job rows, returns an empty list without fake jobs.
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path(".data/announcements")
        self.html_parser = HTMLAnnouncementParser()
        self.attachment_parser = AttachmentParser()

    def extract_from_html_and_attachments(
        self,
        html_content: str,
        source_url: str,
        source_id: str,
        source_name: str,
        local_attachment_paths: Optional[List[Path]] = None,
        recruiting_organization: Optional[str] = None,
        observed_at: Optional[str] = None,
    ) -> List[SourceObservation]:
        if not observed_at:
            observed_at = datetime.now().isoformat()

        parsed_html = self.html_parser.parse(html_content, base_url=source_url)
        announcement_title = parsed_html["title"] or "招聘公告"
        announcement_id = f"ann_{hashlib.sha256(source_url.encode('utf-8')).hexdigest()[:12]}"

        observations: List[SourceObservation] = []
        attachment_paths = local_attachment_paths or []

        # Parse all attachments
        for att_path in attachment_paths:
            try:
                tables = self.attachment_parser.parse_file(att_path)
            except Exception:
                tables = []

            for table in tables:
                rows = table.get("rows", [])
                for row_data in rows:
                    cells = row_data.get("cells", {})
                    row_idx = row_data.get("row_index", 0)

                    # Extract job title mechanically from cell headers
                    job_title = self._find_matching_cell(
                        cells,
                        ["岗位名称", "招聘岗位", "岗位", "职位", "工种", "岗位职责任务", "岗位职责"]
                    )
                    if not job_title:
                        # Skip empty rows or rows without an identifiable job title
                        continue

                    # Education & Degree combination
                    education_req = self._find_matching_cell(cells, ["学历要求", "学历学位要求", "最低学历", "学历"])
                    degree_req = self._find_matching_cell(cells, ["学位要求", "最低学位", "学位"])
                    if education_req and degree_req and education_req != degree_req:
                        education_text = f"{education_req}（{degree_req}）"
                    else:
                        education_text = education_req or degree_req

                    # Age combination
                    age_req = self._find_matching_cell(cells, ["年龄要求", "年龄", "年龄上限"])
                    relaxed_age = self._find_matching_cell(cells, ["（放宽年龄）硕士研究生年龄要求", "放宽年龄要求", "放宽年龄"])
                    if age_req and relaxed_age:
                        age_text = f"{age_req}（放宽：{relaxed_age}）"
                    else:
                        age_text = age_req or relaxed_age

                    # Extract discrete requirement texts verbatim from cells
                    req_dict = {
                        "age_text": age_text,
                        "education_text": education_text,
                        "formal_qualification_text": self._find_matching_cell(
                            cells,
                            ["专业及代码", "专业要求", "专业要求(研究生)", "专业要求(本科)", "专业", "学科方向", "专业名称及代码"]
                        ),
                        "capability_fit_text": self._find_matching_cell(cells, ["能力要求", "专业技能要求", "专业能力要求", "岗位技能要求"]),
                        "teaching_experience_text": self._find_matching_cell(cells, ["教学经历", "教学经验", "带教要求", "带教经历"]),
                        "industry_experience_text": self._find_matching_cell(cells, ["行业经历", "企业经历", "实务经验", "行业背景", "工作经历"]),
                        "other_conditions_text": self._find_matching_cell(cells, ["其他条件", "其他要求", "招聘条件", "备注", "说明"]),
                    }

                    # Determine canonical recruiting organization (institution-level)
                    row_inst = self._find_matching_cell(cells, ["招聘单位", "用人单位", "单位名称", "招聘机构", "用人机构"])
                    if row_inst:
                        effective_org = row_inst
                    elif recruiting_organization:
                        effective_org = recruiting_organization
                    else:
                        effective_org = ""

                    # Department / faculty level (preserved in provenance, never confused with organization)
                    department = self._find_matching_cell(cells, ["工作部门", "用人部门", "学院", "系所", "所属部门", "招聘部门"])

                    # Determine row-level location if present in cells (NO hardcoded location)
                    location = self._find_matching_cell(cells, ["考区", "工作地点", "地点", "城市", "工作地", "所在校区", "校区"])

                    # Determine row-level canonical track (NO job rank / grade mapping)
                    track = self._find_matching_cell(cells, ["招聘赛道", "业务赛道", "目标赛道"])

                    obs_id = f"obs_{announcement_id}_{att_path.stem}_{row_idx}"
                    obs = SourceObservation(
                        observation_id=obs_id,
                        announcement_id=announcement_id,
                        source_id=source_id,
                        source_name=source_name,
                        announcement_title=announcement_title,
                        job_title=job_title,
                        organization=effective_org,
                        location=location,
                        track=track,
                        official_url=source_url,
                        observed_at=observed_at,
                        extracted_requirements=req_dict,
                        provenance={
                            "source_url": source_url,
                            "file_name": att_path.name,
                            "sheet_name": table.get("sheet_name"),
                            "row_index": row_idx,
                            "department": department,
                            "raw_cells": cells,
                        },
                    )
                    observations.append(obs)

        # STRICT RULE: If no attachment rows were found, DO NOT fabricate fake job from announcement title.
        return observations

    def _find_matching_cell(self, cells: Dict[str, str], candidate_keys: List[str]) -> str:
        for key in candidate_keys:
            for col_header, val in cells.items():
                if key == col_header or (key in col_header and len(col_header) <= len(key) + 6):
                    if str(val).strip():
                        return str(val).strip()
        return ""
