"""
Domain models and schema definitions for Career Radar MVP-1.
Respects CONTEXT.md and ADR-0001 ~ ADR-0004.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


CANONICAL_DIMENSIONS = [
    "Age",
    "Education",
    "Formal Qualification",
    "Capability Fit",
    "Teaching Experience",
    "Industry Experience",
]

VALID_EVIDENCE_STATES = {"PASS", "REVIEW", "FAIL", "UNKNOWN", "N/A"}
VALID_RECOMMENDATIONS = {"建议关注", "需要人工确认", "明显不符合"}


@dataclass
class CandidateProfile:
    age: int
    degree: str
    degree_field: str
    teaching_experience_years: int = 0
    industry_experience_years: int = 0
    tracks: List[Dict[str, Any]] = field(default_factory=list)
    regions: Dict[str, List[str]] = field(default_factory=dict)
    hard_constraints: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CandidateProfile":
        cand = data.get("candidate", data)
        return cls(
            age=cand.get("age", 0),
            degree=cand.get("degree", ""),
            degree_field=cand.get("degree_field", ""),
            teaching_experience_years=cand.get("teaching_experience_years", 0),
            industry_experience_years=cand.get("industry_experience_years", 0),
            tracks=cand.get("tracks", []),
            regions=cand.get("regions", {}),
            hard_constraints=cand.get("hard_constraints", {}),
        )


@dataclass
class DimensionEvaluation:
    dimension: str
    state: str  # PASS / REVIEW / FAIL / UNKNOWN / N/A
    requirement_evidence: str
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "state": self.state,
            "requirement_evidence": self.requirement_evidence,
            "rationale": self.rationale,
        }


@dataclass
class EvaluationResult:
    final_recommendation: str  # 建议关注 / 需要人工确认 / 明显不符合
    dimension_evaluations: Dict[str, DimensionEvaluation]
    evaluated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_recommendation": self.final_recommendation,
            "dimension_evaluations": {
                k: v.to_dict() for k, v in self.dimension_evaluations.items()
            },
            "evaluated_at": self.evaluated_at,
        }


@dataclass
class SourceObservation:
    observation_id: str
    announcement_id: str
    source_id: str
    source_name: str
    announcement_title: str
    job_title: str
    organization: str
    location: str
    track: str
    official_url: str
    observed_at: str
    extracted_requirements: Dict[str, str]
    provenance: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceObservation":
        return cls(
            observation_id=data["observation_id"],
            announcement_id=data["announcement_id"],
            source_id=data["source_id"],
            source_name=data.get("source_name", ""),
            announcement_title=data.get("announcement_title", ""),
            job_title=data["job_title"],
            organization=data["organization"],
            location=data.get("location", ""),
            track=data.get("track", ""),
            official_url=data.get("official_url", ""),
            observed_at=data.get("observed_at", datetime.now().isoformat()),
            extracted_requirements=data.get("extracted_requirements", {}),
            provenance=data.get("provenance"),
        )

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "observation_id": self.observation_id,
            "announcement_id": self.announcement_id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "announcement_title": self.announcement_title,
            "job_title": self.job_title,
            "organization": self.organization,
            "location": self.location,
            "track": self.track,
            "official_url": self.official_url,
            "observed_at": self.observed_at,
            "extracted_requirements": self.extracted_requirements,
        }
        if self.provenance:
            res["provenance"] = self.provenance
        return res


@dataclass
class Opportunity:
    opportunity_id: str
    canonical_job_title: str
    organization: str
    location: str
    track: str
    official_url: str
    lifecycle_status: str  # active / updated / closed
    observations: List[SourceObservation]
    latest_evaluation: EvaluationResult
    created_at: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "job_title": self.canonical_job_title,
            "organization": self.organization,
            "location": self.location,
            "track": self.track,
            "official_url": self.official_url,
            "lifecycle_status": self.lifecycle_status,
            "observations": [
                {
                    "observation_id": obs.observation_id,
                    "source_id": obs.source_id,
                    "observed_at": obs.observed_at,
                }
                for obs in self.observations
            ],
            "latest_evaluation": self.latest_evaluation.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
