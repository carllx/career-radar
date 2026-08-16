"""
Semantic evaluation contract, validation, and context builder for Career Radar.
Implements ADR-0001 & ADR-0002.

Strict Boundary:
- Agent possesses full semantic and business decision authority (interpreting requirements,
  judging fit, deciding dimension states, formulating rationales).
- Deterministic code ONLY assembles evaluation context packets and mechanically validates
  structured evaluation results against canonical schemas and vocabulary.
- ZERO deterministic keyword/if-else business filtering rules.
"""

from typing import Any, Callable, Dict, Protocol

from .models import (
    CANONICAL_DIMENSIONS,
    VALID_EVIDENCE_STATES,
    VALID_RECOMMENDATIONS,
    CandidateProfile,
    DimensionEvaluation,
    EvaluationResult,
    SourceObservation,
)


class SemanticEvaluatorProtocol(Protocol):
    """
    Protocol defining the Agent semantic decision boundary.
    Any Agent or provider implementing this protocol takes candidate profile evidence
    and job requirement evidence, and produces a structured EvaluationResult.
    """

    def __call__(
        self, profile: CandidateProfile, observation: SourceObservation
    ) -> EvaluationResult:
        ...


def build_evaluation_packet(
    profile: CandidateProfile, observation: SourceObservation
) -> Dict[str, Any]:
    """
    Assembles a clean, structured evidence packet for an Agent to evaluate.
    Exposes full Profile v2 candidate evidence with explicit capability layers.
    """
    return {
        "candidate_evidence": {
            "date_of_birth": profile.date_of_birth,
            "age": profile.age,
            "degree": profile.degree,
            "degree_field": profile.degree_field,
            "teaching_experience_years": profile.teaching_experience_years,
            "industry_experience_years": profile.industry_experience_years,
            "proven_capabilities": profile.proven_capabilities,
            "adjacent_capabilities": profile.adjacent_capabilities,
            "learning_targets": profile.learning_targets,
            "tracks": profile.tracks,
            "benefit_preferences": profile.benefit_preferences,
            "engagement_preferences": profile.engagement_preferences,
            "compensation_preferences": profile.compensation_preferences,
            "regions": profile.regions,
            "availability_constraints": profile.availability_constraints,
            "unresolved_facts": profile.unresolved_facts,
            "hard_constraints": profile.hard_constraints,
        },
        "observation_evidence": {
            "organization": observation.organization,
            "job_title": observation.job_title,
            "location": observation.location,
            "track": observation.track,
            "official_url": observation.official_url,
            "requirements": observation.extracted_requirements,
        },
        "canonical_contract": {
            "dimensions": CANONICAL_DIMENSIONS,
            "evidence_states": list(VALID_EVIDENCE_STATES),
            "recommendations": list(VALID_RECOMMENDATIONS),
            "learning_targets_rule": "Learning targets indicate exploring/learning skills and must NOT mechanically imply Capability Fit: PASS",
        },
    }


class EvaluationValidator:
    """
    Deterministic layer: strictly validates schema integrity, canonical vocabulary,
    and computes standard recommendation aggregation without embedding business heuristics.
    """

    @staticmethod
    def validate_and_aggregate(result: EvaluationResult) -> EvaluationResult:
        """
        Validates that all canonical dimensions are evaluated with valid states
        and computes the canonical final recommendation per ADR-0001 aggregation rules.
        """
        evals = result.dimension_evaluations

        # 1. Validate all canonical dimensions exist
        for dim in CANONICAL_DIMENSIONS:
            if dim not in evals:
                raise ValueError(f"Missing canonical dimension evaluation: {dim}")
            eval_item = evals[dim]
            if eval_item.state not in VALID_EVIDENCE_STATES:
                raise ValueError(
                    f"Invalid evidence state '{eval_item.state}' for dimension '{dim}'. "
                    f"Must be one of {VALID_EVIDENCE_STATES}"
                )

        # 2. Compute canonical aggregation (ADR-0001)
        states = [evals[dim].state for dim in CANONICAL_DIMENSIONS]

        if "FAIL" in states:
            computed_rec = "明显不符合"
        elif "REVIEW" in states or "UNKNOWN" in states:
            computed_rec = "需要人工确认"
        else:
            computed_rec = "建议关注"

        # Update final recommendation if not set or ensure consistency
        result.final_recommendation = computed_rec
        return result
