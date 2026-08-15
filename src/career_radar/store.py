"""
Atomic local state persistence for Career Radar opportunities.
Implements ADR-0003 & ADR-0004 (.data/opportunities.jsonl).
"""

import json
import os
from pathlib import Path
import tempfile
from typing import List

from .models import Opportunity


class OpportunityStore:
    """
    Manages atomic reading and writing of Opportunities in local JSONL format.
    Uses safe temporary file writing and atomic file replacement.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.opps_file = self.data_dir / "opportunities.jsonl"

    def save_opportunities(self, opportunities: List[Opportunity]) -> None:
        """
        Saves opportunities atomically using a temporary file and replace.
        Updates existing opportunities by ID or appends new ones.
        """
        existing_map = {}
        if self.opps_file.exists():
            with open(self.opps_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        item = json.loads(line)
                        existing_map[item["opportunity_id"]] = item

        for opp in opportunities:
            existing_map[opp.opportunity_id] = opp.to_dict()

        temp_file_fd, temp_file_path = tempfile.mkstemp(
            dir=str(self.data_dir), prefix="opps_", suffix=".tmp"
        )
        try:
            with open(temp_file_fd, "w", encoding="utf-8") as f:
                for item in existing_map.values():
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())

            os.replace(temp_file_path, self.opps_file)
        except Exception:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            raise

    def load_all(self) -> List[dict]:
        """
        Loads all raw opportunity records from disk.
        """
        if not self.opps_file.exists():
            return []
        items = []
        with open(self.opps_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    items.append(json.loads(line))
        return items

    def load_all_opportunities(self) -> List[Opportunity]:
        """
        Loads all opportunities as typed domain objects from disk.
        """
        raw_items = self.load_all()
        return [Opportunity.from_dict(item) for item in raw_items]
