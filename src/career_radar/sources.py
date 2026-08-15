"""
Source Registry and Local Source State Management for Career Radar.
Respects CONTEXT.md, ADR-0002, and ADR-0004.
Public Source Seeds (config/sources.seed.json) are the stable read-only SSOT.
Local runtime discovery and health states are maintained in .data/sources.json (gitignored).
Helper records mechanical execution facts; Agent owns lifecycle decisions (discover, degrade, reactivate).
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class SourceRecord:
    source_id: str
    name: str
    base_url: str
    domain: str
    source_type: str = "first_party_official"
    track: List[str] = field(default_factory=list)
    region: str = "guangdong"
    discovery_role: str = "monitoring"
    origin: str = "seed"  # "seed" or "discovered"
    lifecycle_status: str = "active"  # "active", "discovered", "degraded"
    discovered_at: Optional[str] = None
    last_monitored_at: Optional[str] = None
    last_technical_status: Optional[str] = None  # "success", "blocked_by_captcha", "failed", etc.
    degraded_reason: Optional[str] = None
    provenance: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceRecord":
        return cls(
            source_id=data.get("source_id", ""),
            name=data.get("name", ""),
            base_url=data.get("base_url", ""),
            domain=data.get("domain", ""),
            source_type=data.get("source_type", "first_party_official"),
            track=data.get("track", []) if isinstance(data.get("track"), list) else [data.get("track")] if data.get("track") else [],
            region=data.get("region", "guangdong"),
            discovery_role=data.get("discovery_role", "monitoring"),
            origin=data.get("origin", "seed"),
            lifecycle_status=data.get("lifecycle_status", "active"),
            discovered_at=data.get("discovered_at"),
            last_monitored_at=data.get("last_monitored_at"),
            last_technical_status=data.get("last_technical_status"),
            degraded_reason=data.get("degraded_reason"),
            provenance=data.get("provenance"),
            metadata=data.get("metadata"),
        )


@dataclass
class SourceLifecycleDecision:
    """
    Agent semantic decision on source lifecycle transitions.
    Actions:
    - 'discover': add newly discovered candidate recruitment channel
    - 'degrade': mark existing channel as degraded with explicit rationale
    - 'reactivate': restore degraded channel back to active
    - 'keep': maintain current status while updating monitoring timestamp
    """
    source_id: str
    action: str  # "discover", "degrade", "reactivate", "keep"
    rationale: str = ""
    name: Optional[str] = None
    base_url: Optional[str] = None
    domain: Optional[str] = None
    source_type: Optional[str] = None
    track: Optional[List[str]] = None
    region: Optional[str] = None
    provenance: Optional[Dict[str, Any]] = None


class SourceRegistry:
    """
    Manages merged view of Public Seed Sources and Local Runtime Sources.
    Provides atomic persistence to .data/sources.json without mutating config/sources.seed.json.
    """

    def __init__(
        self,
        seed_path: Union[str, Path] = "config/sources.seed.json",
        data_dir: Union[str, Path] = ".data",
    ):
        self.seed_path = Path(seed_path)
        self.data_dir = Path(data_dir)
        self.local_sources_path = self.data_dir / "sources.json"

        self.seed_sources: Dict[str, SourceRecord] = {}
        self.local_sources: Dict[str, SourceRecord] = {}
        self._network_changes: List[Dict[str, Any]] = []

        self._load_seed_sources()
        self._load_local_sources()

    def _load_seed_sources(self) -> None:
        if self.seed_path.exists():
            with open(self.seed_path, "r", encoding="utf-8") as f:
                raw_seeds = json.load(f)
            for item in raw_seeds:
                rec = SourceRecord.from_dict({
                    **item,
                    "origin": "seed",
                    "lifecycle_status": item.get("lifecycle_status", "active"),
                })
                self.seed_sources[rec.source_id] = rec

    def _load_local_sources(self) -> None:
        if self.local_sources_path.exists():
            try:
                with open(self.local_sources_path, "r", encoding="utf-8") as f:
                    raw_local = json.load(f)
                for item in raw_local:
                    rec = SourceRecord.from_dict(item)
                    self.local_sources[rec.source_id] = rec
            except Exception:
                self.local_sources = {}

    def get_all_sources(self) -> List[SourceRecord]:
        """
        Returns merged list of all sources. Local state overrides seed records.
        """
        merged: Dict[str, SourceRecord] = {}
        for sid, srec in self.seed_sources.items():
            merged[sid] = srec
        for sid, lrec in self.local_sources.items():
            merged[sid] = lrec
        return list(merged.values())

    def get_active_sources(self) -> List[SourceRecord]:
        return [s for s in self.get_all_sources() if s.lifecycle_status == "active"]

    def get_source(self, source_id: str) -> Optional[SourceRecord]:
        if source_id in self.local_sources:
            return self.local_sources[source_id]
        return self.seed_sources.get(source_id)

    def record_monitoring_fact(
        self,
        source_id: str,
        technical_status: str,
        monitored_at: Optional[str] = None,
    ) -> SourceRecord:
        """
        Mechanically records technical execution fact (e.g. success, captcha, failure)
        without mutating semantic lifecycle policy.
        """
        now = monitored_at or datetime.now().isoformat()
        src = self.get_source(source_id)
        if not src:
            raise KeyError(f"Source '{source_id}' not found in registry")

        # Copy to local state to record runtime facts
        updated = SourceRecord.from_dict({
            **src.to_dict(),
            "last_monitored_at": now,
            "last_technical_status": technical_status,
        })
        self.local_sources[source_id] = updated
        return updated

    def apply_lifecycle_decision(
        self, decision: SourceLifecycleDecision, timestamp: Optional[str] = None
    ) -> SourceRecord:
        """
        Applies Agent semantic decision on source lifecycle.
        """
        now = timestamp or datetime.now().isoformat()

        if decision.action == "discover":
            if not decision.base_url or not decision.name:
                raise ValueError("Source discovery decision requires 'name' and 'base_url'")
            domain = decision.domain or (decision.base_url.split("//")[-1].split("/")[0] if "//" in decision.base_url else decision.base_url)
            rec = SourceRecord(
                source_id=decision.source_id,
                name=decision.name,
                base_url=decision.base_url,
                domain=domain,
                source_type=decision.source_type or "discovered_channel",
                track=decision.track or [],
                region=decision.region or "guangdong",
                discovery_role="discovered",
                origin="discovered",
                lifecycle_status="discovered",
                discovered_at=now,
                provenance=decision.provenance or {"rationale": decision.rationale},
            )
            self.local_sources[decision.source_id] = rec
            self._network_changes.append({
                "type": "discovered",
                "source_id": rec.source_id,
                "name": rec.name,
                "base_url": rec.base_url,
                "rationale": decision.rationale,
            })
            return rec

        elif decision.action == "degrade":
            src = self.get_source(decision.source_id)
            if not src:
                raise KeyError(f"Source '{decision.source_id}' not found for degradation")
            updated = SourceRecord.from_dict({
                **src.to_dict(),
                "lifecycle_status": "degraded",
                "degraded_reason": decision.rationale or "渠道失效或不可访问",
            })
            self.local_sources[decision.source_id] = updated
            self._network_changes.append({
                "type": "degraded",
                "source_id": updated.source_id,
                "name": updated.name,
                "base_url": updated.base_url,
                "reason": decision.rationale,
            })
            return updated

        elif decision.action == "reactivate":
            src = self.get_source(decision.source_id)
            if not src:
                raise KeyError(f"Source '{decision.source_id}' not found for reactivation")
            updated = SourceRecord.from_dict({
                **src.to_dict(),
                "lifecycle_status": "active",
                "degraded_reason": None,
            })
            self.local_sources[decision.source_id] = updated
            self._network_changes.append({
                "type": "reactivated",
                "source_id": updated.source_id,
                "name": updated.name,
                "base_url": updated.base_url,
            })
            return updated

        elif decision.action == "keep":
            src = self.get_source(decision.source_id)
            if not src:
                raise KeyError(f"Source '{decision.source_id}' not found")
            return src

        raise ValueError(f"Unknown source lifecycle action: {decision.action}")

    def save_local_state(self) -> Path:
        """
        Persists all local runtime sources atomically to .data/sources.json.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        records = [s.to_dict() for s in self.local_sources.values()]
        temp_file = self.local_sources_path.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        temp_file.replace(self.local_sources_path)
        return self.local_sources_path

    @property
    def network_changes(self) -> List[Dict[str, Any]]:
        return list(self._network_changes)
