"""
Domain models and schema definitions for Career Radar MVP-1.
Respects CONTEXT.md and ADR-0001 ~ ADR-0004.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set


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
VALID_RESOLUTION_OUTCOMES = {"same", "update", "different", "uncertain"}


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

    def track_names(self) -> Set[str]:
        """Returns normalized set of target track names."""
        names = set()
        for t in self.tracks:
            if isinstance(t, dict):
                names.add(t.get("name") or t.get("track_id") or "")
            elif isinstance(t, str):
                names.add(t)
        return {n for n in names if n}

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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DimensionEvaluation":
        return cls(
            dimension=data["dimension"],
            state=data["state"],
            requirement_evidence=data.get("requirement_evidence", ""),
            rationale=data.get("rationale", ""),
        )


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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvaluationResult":
        dim_evals = {
            k: DimensionEvaluation.from_dict(v)
            for k, v in data.get("dimension_evaluations", {}).items()
        }
        return cls(
            final_recommendation=data["final_recommendation"],
            dimension_evaluations=dim_evals,
            evaluated_at=data.get("evaluated_at", datetime.now().isoformat()),
        )


@dataclass
class EntityResolutionDecision:
    resolution: str  # same / update / different / uncertain
    target_opportunity_id: Optional[str] = None
    rationale: str = ""
    diff_summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolution": self.resolution,
            "target_opportunity_id": self.target_opportunity_id,
            "rationale": self.rationale,
            "diff_summary": self.diff_summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityResolutionDecision":
        return cls(
            resolution=data["resolution"],
            target_opportunity_id=data.get("target_opportunity_id"),
            rationale=data.get("rationale", ""),
            diff_summary=data.get("diff_summary"),
        )


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
            announcement_id=data.get("announcement_id", ""),
            source_id=data.get("source_id", ""),
            source_name=data.get("source_name", ""),
            announcement_title=data.get("announcement_title", ""),
            job_title=data.get("job_title", ""),
            organization=data.get("organization", ""),
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
    change_diff: Optional[Dict[str, Any]] = None
    update_summary: Optional[str] = None
    uncertain_links: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Opportunity":
        raw_obs = data.get("observations", [])
        obs_list = []
        for o in raw_obs:
            if "job_title" in o:
                obs_list.append(SourceObservation.from_dict(o))
            else:
                obs_list.append(
                    SourceObservation(
                        observation_id=o.get("observation_id", ""),
                        announcement_id=o.get("announcement_id", ""),
                        source_id=o.get("source_id", ""),
                        source_name=o.get("source_name", ""),
                        announcement_title=o.get("announcement_title", ""),
                        job_title=data.get("job_title", data.get("canonical_job_title", "")),
                        organization=data.get("organization", ""),
                        location=data.get("location", ""),
                        track=data.get("track", ""),
                        official_url=data.get("official_url", ""),
                        observed_at=o.get("observed_at", data.get("created_at", "")),
                        extracted_requirements=o.get("extracted_requirements", {}),
                        provenance=o.get("provenance"),
                    )
                )

        eval_result = EvaluationResult.from_dict(data["latest_evaluation"])
        return cls(
            opportunity_id=data["opportunity_id"],
            canonical_job_title=data.get("job_title", data.get("canonical_job_title", "")),
            organization=data.get("organization", ""),
            location=data.get("location", ""),
            track=data.get("track", ""),
            official_url=data.get("official_url", ""),
            lifecycle_status=data.get("lifecycle_status", "active"),
            observations=obs_list,
            latest_evaluation=eval_result,
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            change_diff=data.get("change_diff"),
            update_summary=data.get("update_summary"),
            uncertain_links=data.get("uncertain_links", []),
        )

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "opportunity_id": self.opportunity_id,
            "job_title": self.canonical_job_title,
            "organization": self.organization,
            "location": self.location,
            "track": self.track,
            "official_url": self.official_url,
            "lifecycle_status": self.lifecycle_status,
            "observations": [obs.to_dict() for obs in self.observations],
            "latest_evaluation": self.latest_evaluation.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "uncertain_links": self.uncertain_links,
        }
        if self.change_diff:
            res["change_diff"] = self.change_diff
        if self.update_summary:
            res["update_summary"] = self.update_summary
        return res
