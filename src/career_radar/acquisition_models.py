"""
Production Source Acquisition Models & Contracts for Career Radar.
Respects CONTEXT.md, ADR-0002, Issue #19, Spec #20, Issue #21 and Issue #22.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .sources import MonitoringFact


@dataclass
class AcquisitionResult:
    """
    Auditable mechanical acquisition record produced by actual network retrieval.
    Every physical HTTP request (listing GET, detail GET, attachment GET) produces one AcquisitionResult.
    """
    attempt_id: str
    source_id: str
    requested_url: str
    final_url: str
    timestamp: str
    acquisition_method: str = "native_http_get"
    technical_status: str = "success"  # "success", "failed", "blocked_by_captcha", "unsupported_dynamic"
    http_status: Optional[int] = None
    content_type: Optional[str] = None
    body_length: int = 0
    response_hash: str = ""
    error_facts: Optional[Dict[str, Any]] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AcquisitionResult":
        return cls(
            attempt_id=data["attempt_id"],
            source_id=data["source_id"],
            requested_url=data["requested_url"],
            final_url=data.get("final_url", data["requested_url"]),
            timestamp=data["timestamp"],
            acquisition_method=data.get("acquisition_method", "native_http_get"),
            technical_status=data.get("technical_status", "success"),
            http_status=data.get("http_status"),
            content_type=data.get("content_type"),
            body_length=data.get("body_length", 0),
            response_hash=data.get("response_hash", ""),
            error_facts=data.get("error_facts"),
            etag=data.get("etag"),
            last_modified=data.get("last_modified"),
            metadata=data.get("metadata"),
        )


@dataclass
class SourceAcquisitionSessionResult:
    """
    Vertical result combining primary audit record, all physical HTTP acquisition records,
    derived monitoring fact, persisted raw evidence path, and compact Agent-facing structured packet.
    """
    source_id: str
    acquisition_result: AcquisitionResult
    monitoring_fact: MonitoringFact
    raw_evidence_path: Optional[str] = None
    agent_evidence_packet: Optional[Dict[str, Any]] = None
    agent_evidence_packets: List[Dict[str, Any]] = field(default_factory=list)
    acquisition_results: List[AcquisitionResult] = field(default_factory=list)

    def __post_init__(self):
        if not self.acquisition_results and self.acquisition_result:
            self.acquisition_results = [self.acquisition_result]
        if not self.agent_evidence_packets and self.agent_evidence_packet is not None:
            self.agent_evidence_packets = [self.agent_evidence_packet]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "acquisition_result": self.acquisition_result.to_dict(),
            "acquisition_results": [r.to_dict() for r in self.acquisition_results],
            "monitoring_fact": asdict(self.monitoring_fact),
            "raw_evidence_path": self.raw_evidence_path,
            "agent_evidence_packet": self.agent_evidence_packet,
            "agent_evidence_packets": self.agent_evidence_packets,
        }
