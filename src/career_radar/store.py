"""
Local state persistence for Career Radar opportunities.
Implements ADR-0003 & ADR-0004 (.data/opportunities.jsonl).
"""

import json
from pathlib import Path
from typing import List

from .models import Opportunity


class OpportunityStore:
    """
    Manages atomic reading and appending of Opportunities in local JSONL format.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.opps_file = self.data_dir / "opportunities.jsonl"

    def save_opportunities(self, opportunities: List[Opportunity]) -> None:
        """
        Saves opportunities by appending or updating them in opportunities.jsonl.
        """
        # Read existing
        existing_map = {}
        if self.opps_file.exists():
            with open(self.opps_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        item = json.loads(line)
                        existing_map[item["opportunity_id"]] = item

        # Update or add new
        for opp in opportunities:
            existing_map[opp.opportunity_id] = opp.to_dict()

        # Write back atomically
        with open(self.opps_file, "w", encoding="utf-8") as f:
            for item in existing_map.values():
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def load_all(self) -> List[dict]:
        """
        Loads all opportunities from disk.
        """
        if not self.opps_file.exists():
            return []
        items = []
        with open(self.opps_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    items.append(json.loads(line))
        return items
