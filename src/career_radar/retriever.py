"""
High-recall deterministic candidate retrieval for Career Radar MVP-1.
Selects historical Opportunities that should be presented to the Agent for entity resolution.
Policy-free: never excludes candidates based on title mismatch, keyword overlap, or similarity thresholds.
"""

from typing import List

from .models import Opportunity, SourceObservation


class CandidateRetriever:
    """
    Retrieves candidate historical Opportunities for a new SourceObservation.
    Only answers 'Which historical Opportunities should the Agent inspect?'.
    Never decides entity identity or eligibility.
    """

    def retrieve_candidates(
        self,
        observation: SourceObservation,
        historical_opportunities: List[Opportunity],
    ) -> List[Opportunity]:
        if not historical_opportunities:
            return []

        # 1. If recruiting organization is known, retrieve all active/updated opportunities from the same organization
        if observation.organization:
            matched_by_org = [
                opp
                for opp in historical_opportunities
                if opp.organization == observation.organization
                and opp.lifecycle_status != "closed"
            ]
            if matched_by_org:
                return matched_by_org

        # 2. If organization is unknown/empty or no exact organization match was found,
        # expand to active/updated opportunities in the historical pool without hard gating on title/keyword.
        return [
            opp
            for opp in historical_opportunities
            if opp.lifecycle_status != "closed"
        ]
