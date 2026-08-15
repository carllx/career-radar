"""
Agent Entity Resolution Seam and state applier for Career Radar MVP-1.
Respects CONTEXT.md and ADR-0002 ~ ADR-0003.
Helper only prepares packets and applies Agent decisions deterministically.
Agent is the sole semantic authority on same / update / different / uncertain.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    CandidateProfile,
    DimensionEvaluation,
    EntityResolutionDecision,
    EvaluationResult,
    Opportunity,
    SourceObservation,
    VALID_RESOLUTION_OUTCOMES,
)


def build_entity_resolution_packet(
    observation: SourceObservation, candidates: List[Opportunity]
) -> Dict[str, Any]:
    """
    Constructs an evidence packet for the Agent to inspect for entity resolution.
    Contains the new observation and all candidate opportunities with their full observation history.
    """
    candidate_items = []
    for opp in candidates:
        candidate_items.append({
            "opportunity_id": opp.opportunity_id,
            "job_title": opp.canonical_job_title,
            "organization": opp.organization,
            "location": opp.location,
            "track": opp.track,
            "official_url": opp.official_url,
            "lifecycle_status": opp.lifecycle_status,
            "created_at": opp.created_at,
            "updated_at": opp.updated_at,
            "latest_evaluation": opp.latest_evaluation.to_dict() if opp.latest_evaluation else None,
            "observations_history": [obs.to_dict() for obs in opp.observations],
        })

    return {
        "observation": observation.to_dict(),
        "candidates_count": len(candidates),
        "candidates": candidate_items,
    }


class EntityResolutionApplier:
    """
    Mechanically applies the Agent's 4-state EntityResolutionDecision to the Opportunity state.
    """

    def apply_decision(
        self,
        observation: SourceObservation,
        decision: EntityResolutionDecision,
        opportunities_map: Dict[str, Opportunity],
        current_time: Optional[str] = None,
    ) -> Tuple[Opportunity, str]:
        """
        Applies resolution decision.
        Returns (affected_opportunity, action_type) where action_type is:
        - 'deduplicated_same': added to existing opportunity without re-evaluation or new alert
        - 'updated_opportunity': updated existing opportunity, triggers re-evaluation & update alert
        - 'new_different': created new opportunity, triggers initial evaluation & new alert
        - 'new_uncertain': created independent opportunity with soft link, triggers initial evaluation
        """
        if decision.resolution not in VALID_RESOLUTION_OUTCOMES:
            raise ValueError(f"Invalid resolution outcome: {decision.resolution}")

        if not current_time:
            current_time = datetime.now().isoformat()

        if decision.resolution == "same":
            target_id = decision.target_opportunity_id
            if not target_id or target_id not in opportunities_map:
                raise ValueError(
                    f"EntityResolutionDecision 'same' requires a valid target_opportunity_id in state, got {target_id}"
                )
            target_opp = opportunities_map[target_id]
            # Append new observation to history (preserving second-source evidence and provenance)
            target_opp.observations.append(observation)
            target_opp.updated_at = current_time
            return target_opp, "deduplicated_same"

        elif decision.resolution == "update":
            target_id = decision.target_opportunity_id
            if not target_id or target_id not in opportunities_map:
                raise ValueError(
                    f"EntityResolutionDecision 'update' requires a valid target_opportunity_id in state, got {target_id}"
                )
            target_opp = opportunities_map[target_id]
            target_opp.observations.append(observation)
            target_opp.lifecycle_status = "updated"
            target_opp.update_summary = decision.diff_summary or decision.rationale or "岗位信息发生补充/修订"
            target_opp.change_diff = {
                "diff_summary": decision.diff_summary or decision.rationale,
                "latest_observation_id": observation.observation_id,
                "updated_at": current_time,
            }
            target_opp.updated_at = current_time
            return target_opp, "updated_opportunity"

        elif decision.resolution == "different":
            new_opp_id = f"opp_{observation.observation_id}"
            # Create a placeholder initial evaluation (to be evaluated by Agent)
            placeholder_eval = EvaluationResult(
                final_recommendation="需要人工确认",
                dimension_evaluations={},
                evaluated_at=current_time,
            )
            new_opp = Opportunity(
                opportunity_id=new_opp_id,
                canonical_job_title=observation.job_title,
                organization=observation.organization,
                location=observation.location,
                track=observation.track,
                official_url=observation.official_url,
                lifecycle_status="active",
                observations=[observation],
                latest_evaluation=placeholder_eval,
                created_at=observation.observed_at or current_time,
                updated_at=observation.observed_at or current_time,
            )
            opportunities_map[new_opp_id] = new_opp
            return new_opp, "new_different"

        elif decision.resolution == "uncertain":
            # NO FORCE MERGE: Create independent Opportunity with soft bidirectional link
            new_opp_id = f"opp_{observation.observation_id}"
            soft_links = [decision.target_opportunity_id] if decision.target_opportunity_id else []
            placeholder_eval = EvaluationResult(
                final_recommendation="需要人工确认",
                dimension_evaluations={},
                evaluated_at=current_time,
            )
            new_opp = Opportunity(
                opportunity_id=new_opp_id,
                canonical_job_title=observation.job_title,
                organization=observation.organization,
                location=observation.location,
                track=observation.track,
                official_url=observation.official_url,
                lifecycle_status="active",
                observations=[observation],
                latest_evaluation=placeholder_eval,
                created_at=observation.observed_at or current_time,
                updated_at=observation.observed_at or current_time,
                uncertain_links=soft_links,
            )
            opportunities_map[new_opp_id] = new_opp

            # Also record soft link on the target opportunity if present
            if decision.target_opportunity_id and decision.target_opportunity_id in opportunities_map:
                target_opp = opportunities_map[decision.target_opportunity_id]
                if new_opp_id not in target_opp.uncertain_links:
                    target_opp.uncertain_links.append(new_opp_id)

            return new_opp, "new_uncertain"

        raise RuntimeError("Unreachable resolution branch")
