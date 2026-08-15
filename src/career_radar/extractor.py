"""
Announcement and attachment slicing extractor for Career Radar MVP-1.
Implements Issue #10: slices 1 Announcement with attachment tables into N SourceObservations.
Preserves raw cells and provenance without applying candidate-matching business rules.
"""

from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .models import SourceObservation
from .parser import AttachmentParser, HTMLAnnouncementParser


class AnnouncementExtractor:
    """
    Slices first-party announcement HTML and attachment tables into discrete SourceObservations.
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
        observed_at: Optional[str] = None,
    ) -> List[SourceObservation]:
        if not observed_at:
            observed_at = datetime.now().isoformat()

        parsed_html = self.html_parser.parse(html_content, base_url=source_url)
        announcement_title = parsed_html["title"] or "招聘公告"
        announcement_id = f"ann_{hashlib.sha256(source_url.encode('utf-8')).hexdigest()[:12]}"

        # Infer default organization name from title or source_name
        org_name = source_name
        for prefix in ["广东轻工职业技术大学", "华南师范大学", "中山大学", "华南理工大学", "广州大学", "广州番禺职业技术学院"]:
            if prefix in announcement_title:
                org_name = prefix
                break

        observations: List[SourceObservation] = []
        attachment_paths = local_attachment_paths or []

        # 1. Parse all attachments
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
                    job_title = self._find_matching_cell(cells, ["岗位名称", "招聘岗位", "岗位", "职位", "工种"])
                    if not job_title:
                        # Skip empty rows without a identifiable title
                        continue

                    # Extract discrete requirement texts verbatim from cells
                    req_dict = {
                        "age_text": self._find_matching_cell(cells, ["年龄要求", "年龄", "年龄上限"]),
                        "education_text": self._find_matching_cell(cells, ["学历学位要求", "学历要求", "学历", "学位", "最低学历"]),
                        "formal_qualification_text": self._find_matching_cell(cells, ["专业及代码", "专业要求", "专业", "学科方向", "专业名称及代码"]),
                        "capability_fit_text": self._find_matching_cell(cells, ["其他条件", "能力要求", "岗位职责", "招聘条件", "备注"]),
                        "teaching_experience_text": self._find_matching_cell(cells, ["教学经历", "教学经验", "带教要求"]),
                        "industry_experience_text": self._find_matching_cell(cells, ["行业经历", "企业经历", "实务经验"]),
                    }

                    # Determine row-level organization / department if present
                    row_org = self._find_matching_cell(cells, ["用人单位", "用人部门", "招聘单位", "学院"])
                    effective_org = f"{org_name} ({row_org})" if row_org and row_org != org_name else org_name

                    obs_id = f"obs_{announcement_id}_{att_path.stem}_{row_idx}"
                    obs = SourceObservation(
                        observation_id=obs_id,
                        announcement_id=announcement_id,
                        source_id=source_id,
                        source_name=source_name,
                        announcement_title=announcement_title,
                        job_title=job_title,
                        organization=effective_org,
                        location="Guangzhou",
                        track="higher_education_teaching",
                        official_url=source_url,
                        observed_at=observed_at,
                        extracted_requirements=req_dict,
                        provenance={
                            "source_url": source_url,
                            "file_name": att_path.name,
                            "sheet_name": table.get("sheet_name"),
                            "row_index": row_idx,
                            "raw_cells": cells,
                        },
                    )
                    observations.append(obs)

        # 2. Fallback: If no attachment rows were found, slice from announcement body
        if not observations:
            obs_id = f"obs_{announcement_id}_main"
            obs = SourceObservation(
                observation_id=obs_id,
                announcement_id=announcement_id,
                source_id=source_id,
                source_name=source_name,
                announcement_title=announcement_title,
                job_title=announcement_title,
                organization=org_name,
                location="Guangzhou",
                track="higher_education_teaching",
                official_url=source_url,
                observed_at=observed_at,
                extracted_requirements={
                    "age_text": "",
                    "education_text": "",
                    "formal_qualification_text": "",
                    "capability_fit_text": parsed_html["body_text"][:500],
                    "teaching_experience_text": "",
                    "industry_experience_text": "",
                },
                provenance={
                    "source_url": source_url,
                    "file_name": "html_body",
                },
            )
            observations.append(obs)

        return observations

    def _find_matching_cell(self, cells: Dict[str, str], candidate_keys: List[str]) -> str:
        for key in candidate_keys:
            for col_header, val in cells.items():
                if key in col_header:
                    return val
        return ""
