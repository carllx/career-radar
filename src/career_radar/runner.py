"""
Public transport-neutral runner entrypoint for Career Radar MVP-1.
Supports the IDE-Agent-facing sequential and batch workflow with in-memory working state:
1. Sequential Working State: Newly created/updated Opportunities in the SAME Run are immediately visible to subsequent observations' candidate retrieval.
2. Atomicity: Failure in any observation fails fast; persistent disk store is only written once after the entire batch succeeds.
3. Seams: Prepare -> Decide (Agent entity resolution + qualification matching) -> Finalize.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import yaml

from .evaluator import (
    EvaluationValidator,
    IntentValidator,
    MarketIntelligenceValidator,
    build_evaluation_packet,
)
from .extractor import (
    AnnouncementExtractor,
    fetch_and_extract_first_party_announcement,
)
from .models import (
    CandidateProfile,
    EntityResolutionDecision,
    EvaluationResult,
    MarketIntelligence,
    Opportunity,
    OpportunityIntentDecision,
    SourceObservation,
)
from .reporter import DigestReporter
from .resolver import EntityResolutionApplier, build_entity_resolution_packet
from .retriever import CandidateRetriever
from .store import OpportunityStore


class IncrementalResolutionSession:
    """
    Manages sequential in-memory working Opportunity state for a single Run.
    Ensures earlier results in the same Run are immediately available to later observations
    for candidate retrieval, while guaranteeing atomic single-shot persistence.
    """

    def __init__(self, data_dir: Union[str, Path] = ".data"):
        self.data_dir = Path(data_dir)
        self.store = OpportunityStore(self.data_dir)
        self.prior_opportunities = self.store.load_all_opportunities()
        self.working_map: Dict[str, Opportunity] = {
            o.opportunity_id: o for o in self.prior_opportunities
        }
        self.retriever = CandidateRetriever()
        self.applier = EntityResolutionApplier()
        self.staged_observations: List[SourceObservation] = []
        self.new_opportunity_ids: List[str] = []
        self.updated_opportunity_ids: List[str] = []
        self.deduped_same_count = 0

    @property
    def working_opportunities(self) -> List[Opportunity]:
        return list(self.working_map.values())

    def prepare_observation_packet(
        self, observation: SourceObservation
    ) -> Tuple[Dict[str, Any], List[Opportunity]]:
        """
        Retrieves candidates from the current in-memory working state (including opportunities
        created/updated earlier in this run) and builds the Agent packet.
        """
        candidates = self.retriever.retrieve_candidates(observation, self.working_opportunities)
        packet = build_entity_resolution_packet(observation, candidates)
        return packet, candidates

    def stage_decision(
        self,
        observation: SourceObservation,
        decision: EntityResolutionDecision,
        evaluation_result: Optional[EvaluationResult] = None,
        intent_decision: Optional[OpportunityIntentDecision] = None,
        market_intelligence: Optional[MarketIntelligence] = None,
        current_time: Optional[str] = None,
    ) -> Tuple[Opportunity, str]:
        """
        Applies resolution decision to working state.
        Validates evaluation schemas immediately. Does NOT touch disk.
        """
        validated_eval = None
        if evaluation_result:
            validated_eval = EvaluationValidator.validate_and_aggregate(evaluation_result)

        validated_intent = None
        if intent_decision:
            validated_intent = IntentValidator.validate(intent_decision)

        validated_intel = None
        if market_intelligence:
            validated_intel = MarketIntelligenceValidator.validate_and_normalize(market_intelligence)

        opp, action = self.applier.apply_decision(
            observation=observation,
            decision=decision,
            opportunities_map=self.working_map,
            evaluation_result=validated_eval,
            intent_decision=validated_intent,
            market_intelligence=validated_intel,
            current_time=current_time or datetime.now().isoformat(),
        )

        self.staged_observations.append(observation)
        if action == "deduplicated_same":
            self.deduped_same_count += 1
        elif action == "updated_opportunity":
            self.updated_opportunity_ids.append(opp.opportunity_id)
        elif action in ("new_different", "new_uncertain"):
            self.new_opportunity_ids.append(opp.opportunity_id)

        return opp, action

    def commit_and_finalize(
        self,
        reports_dir: Union[str, Path] = "reports",
        run_date: Optional[str] = None,
        network_changes: Optional[List[Dict[str, Any]]] = None,
        acquisition_gaps: Optional[List[str]] = None,
        coverage_caveat: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Atomically persists the working state to disk and renders the Daily Digest.
        """
        if not run_date:
            run_date = datetime.now().strftime("%Y-%m-%d")

        all_opportunities = self.working_opportunities
        self.store.save_opportunities(all_opportunities)

        reports_dir = Path(reports_dir)
        reporter = DigestReporter(reports_dir)
        report_file = reporter.generate_report(
            all_opportunities,
            run_date=run_date,
            new_opportunity_ids=self.new_opportunity_ids,
            updated_opportunity_ids=self.updated_opportunity_ids,
            network_changes=network_changes,
            acquisition_gaps=acquisition_gaps,
            coverage_caveat=coverage_caveat,
        )

        recommended_count = sum(
            1 for o in all_opportunities
            if o.opportunity_id in self.new_opportunity_ids
            and o.latest_evaluation
            and o.latest_evaluation.final_recommendation == "建议关注"
        )
        review_count = sum(
            1 for o in all_opportunities
            if (o.opportunity_id in self.new_opportunity_ids or o.opportunity_id in self.updated_opportunity_ids)
            and (
                (o.latest_evaluation and o.latest_evaluation.final_recommendation == "需要人工确认")
                or o.uncertain_links
            )
        )
        mismatch_count = sum(
            1 for o in all_opportunities
            if o.opportunity_id in self.new_opportunity_ids
            and o.latest_evaluation
            and o.latest_evaluation.final_recommendation == "明显不符合"
        )
        apply_now_count = sum(
            1 for o in all_opportunities
            if (o.opportunity_id in self.new_opportunity_ids or o.opportunity_id in self.updated_opportunity_ids)
            and o.opportunity_intent == "APPLY_NOW"
        )
        conditional_count = sum(
            1 for o in all_opportunities
            if (o.opportunity_id in self.new_opportunity_ids or o.opportunity_id in self.updated_opportunity_ids)
            and o.opportunity_intent == "CONDITIONAL"
        )
        watch_learn_count = sum(
            1 for o in all_opportunities
            if (o.opportunity_id in self.new_opportunity_ids or o.opportunity_id in self.updated_opportunity_ids)
            and o.opportunity_intent == "WATCH_LEARN"
        )

        return {
            "success": True,
            "run_date": run_date,
            "total_evaluated": len(self.staged_observations),
            "total_in_store": len(all_opportunities),
            "new_opportunities_count": len(self.new_opportunity_ids),
            "updated_opportunities_count": len(self.updated_opportunity_ids),
            "deduped_same_count": self.deduped_same_count,
            "recommended_count": recommended_count,
            "review_count": review_count,
            "mismatch_count": mismatch_count,
            "apply_now_count": apply_now_count,
            "conditional_count": conditional_count,
            "watch_learn_count": watch_learn_count,
            "report_path": str(report_file),
            "opportunities": [opp.to_dict() for opp in all_opportunities],
        }


def prepare_evaluation_run(
    profile_path: Union[str, Path],
    observations_source: Union[str, Path, List[Dict[str, Any]], List[SourceObservation]],
    data_dir: Union[str, Path] = ".data",
) -> Tuple[CandidateProfile, List[SourceObservation], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Phase 1 (Deterministic Helper):
    Loads profile, prior opportunities, and new observations.
    Prepares structured Evidence Packets for both Entity Resolution and Eligibility.
    """
    profile_path = Path(profile_path)
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile configuration not found: {profile_path}")

    with open(profile_path, "r", encoding="utf-8") as f:
        raw_profile = yaml.safe_load(f)
    profile = CandidateProfile.from_dict(raw_profile)

    if isinstance(observations_source, (str, Path)):
        obs_file = Path(observations_source)
        if not obs_file.exists():
            raise FileNotFoundError(f"Observations file not found: {obs_file}")
        with open(obs_file, "r", encoding="utf-8") as f:
            raw_observations = json.load(f)
        observations = [SourceObservation.from_dict(obs) for obs in raw_observations]
    elif isinstance(observations_source, list) and observations_source and isinstance(observations_source[0], SourceObservation):
        observations = observations_source  # type: ignore
    elif isinstance(observations_source, list) and not observations_source:
        observations = []
    else:
        observations = [SourceObservation.from_dict(obs) for obs in observations_source]  # type: ignore

    store = OpportunityStore(Path(data_dir))
    prior_opportunities = store.load_all_opportunities()

    retriever = CandidateRetriever()
    resolution_packets = []
    for obs in observations:
        candidates = retriever.retrieve_candidates(obs, prior_opportunities)
        packet = build_entity_resolution_packet(obs, candidates)
        resolution_packets.append(packet)

    eligibility_packets = [build_evaluation_packet(profile, obs) for obs in observations]

    return profile, observations, resolution_packets, eligibility_packets


def finalize_incremental_run(
    observations: List[SourceObservation],
    resolution_decisions: List[EntityResolutionDecision],
    evaluation_results: Dict[str, EvaluationResult],
    intent_decisions: Optional[Dict[str, OpportunityIntentDecision]] = None,
    market_intelligence_results: Optional[Dict[str, MarketIntelligence]] = None,
    data_dir: Union[str, Path] = ".data",
    reports_dir: Union[str, Path] = "reports",
    run_date: Optional[str] = None,
    network_changes: Optional[List[Dict[str, Any]]] = None,
    acquisition_gaps: Optional[List[str]] = None,
    coverage_caveat: Optional[str] = None,
) -> Dict[str, Any]:
    """Applies Agent decisions sequentially to in-memory state and persists atomically."""
    if len(observations) != len(resolution_decisions):
        raise ValueError(
            f"Mismatched counts: {len(observations)} observations vs {len(resolution_decisions)} decisions"
        )
    session = IncrementalResolutionSession(data_dir=data_dir)
    for obs, decision in zip(observations, resolution_decisions):
        eval_res = evaluation_results.get(obs.observation_id) or (
            evaluation_results.get(decision.target_opportunity_id) if decision.target_opportunity_id else None
        )
        intent_res = None
        if intent_decisions:
            intent_res = intent_decisions.get(obs.observation_id) or (
                intent_decisions.get(decision.target_opportunity_id) if decision.target_opportunity_id else None
            )
        intel_res = None
        if market_intelligence_results:
            intel_res = market_intelligence_results.get(obs.observation_id) or (
                market_intelligence_results.get(decision.target_opportunity_id) if decision.target_opportunity_id else None
            )
        session.stage_decision(
            observation=obs,
            decision=decision,
            evaluation_result=eval_res,
            intent_decision=intent_res,
            market_intelligence=intel_res,
            current_time=datetime.now().isoformat(),
        )
    return session.commit_and_finalize(
        reports_dir=reports_dir,
        run_date=run_date,
        network_changes=network_changes,
        acquisition_gaps=acquisition_gaps,
        coverage_caveat=coverage_caveat,
    )


def finalize_evaluation_run(
    observations: List[SourceObservation],
    evaluation_results: List[EvaluationResult],
    intent_results: Optional[List[OpportunityIntentDecision]] = None,
    market_intelligence_results: Optional[List[MarketIntelligence]] = None,
    data_dir: Union[str, Path] = ".data",
    reports_dir: Union[str, Path] = "reports",
    run_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Standard finalize entrypoint. Requires Agent resolution if prior opportunities exist."""
    store = OpportunityStore(Path(data_dir))
    prior_opps = store.load_all_opportunities()
    if len(prior_opps) > 0:
        raise ValueError(
            f"Prior opportunities exist in store ({len(prior_opps)} records), but no Agent entity resolution was provided."
        )
    default_decisions = [
        EntityResolutionDecision(resolution="different", rationale="Bootstrap initial opportunity")
        for _ in observations
    ]
    eval_map = {obs.observation_id: ev for obs, ev in zip(observations, evaluation_results)}
    intent_map = {}
    if intent_results:
        intent_map = {obs.observation_id: it for obs, it in zip(observations, intent_results)}
    intel_map = {}
    if market_intelligence_results:
        intel_map = {obs.observation_id: mi for obs, mi in zip(observations, market_intelligence_results)}
    return finalize_incremental_run(
        observations=observations,
        resolution_decisions=default_decisions,
        evaluation_results=eval_map,
        intent_decisions=intent_map if intent_results else None,
        market_intelligence_results=intel_map if market_intelligence_results else None,
        data_dir=data_dir,
        reports_dir=reports_dir,
        run_date=run_date,
    )


def run_radar_pipeline(
    profile_path: Union[str, Path],
    observations_source: Union[str, Path, List[Dict[str, Any]], List[SourceObservation]],
    evaluator_fn: Callable[[CandidateProfile, SourceObservation], EvaluationResult],
    intent_evaluator_fn: Optional[Callable[[CandidateProfile, SourceObservation, EvaluationResult], OpportunityIntentDecision]] = None,
    market_intelligence_evaluator_fn: Optional[Callable[[CandidateProfile, SourceObservation, EvaluationResult, OpportunityIntentDecision], MarketIntelligence]] = None,
    entity_resolver_fn: Optional[Callable[[SourceObservation, List[Opportunity]], EntityResolutionDecision]] = None,
    data_dir: Union[str, Path] = ".data",
    reports_dir: Union[str, Path] = "reports",
    run_date: Optional[str] = None,
    network_changes: Optional[List[Dict[str, Any]]] = None,
    acquisition_gaps: Optional[List[str]] = None,
    coverage_caveat: Optional[str] = None,
) -> Dict[str, Any]:
    """Unified pipeline across highest testing seam with sequential in-memory working state."""
    profile_path = Path(profile_path)
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile configuration not found: {profile_path}")

    with open(profile_path, "r", encoding="utf-8") as f:
        raw_profile = yaml.safe_load(f)
    profile = CandidateProfile.from_dict(raw_profile)

    if isinstance(observations_source, (str, Path)):
        obs_file = Path(observations_source)
        if not obs_file.exists():
            raise FileNotFoundError(f"Observations file not found: {obs_file}")
        with open(obs_file, "r", encoding="utf-8") as f:
            raw_observations = json.load(f)
        observations = [SourceObservation.from_dict(obs) for obs in raw_observations]
    elif isinstance(observations_source, list) and observations_source and isinstance(observations_source[0], SourceObservation):
        observations = observations_source  # type: ignore
    elif isinstance(observations_source, list) and not observations_source:
        observations = []
    else:
        observations = [SourceObservation.from_dict(obs) for obs in observations_source]  # type: ignore

    session = IncrementalResolutionSession(data_dir=data_dir)

    for i, obs in enumerate(observations):
        packet, candidates = session.prepare_observation_packet(obs)
        if entity_resolver_fn:
            decision = entity_resolver_fn(obs, candidates)
        elif len(session.working_opportunities) == 0:
            decision = EntityResolutionDecision(resolution="different", rationale="Bootstrap initial opportunity")
        else:
            raise ValueError(
                f"Prior opportunities exist in store or working state contains opportunities ({len(session.working_opportunities)} records), "
                "but no entity_resolver_fn was provided. Helper is strictly prohibited from assuming 'different'."
            )

        eval_res = None
        intent_res = None
        intel_res = None
        if decision.resolution in ("different", "update", "uncertain"):
            if not evaluator_fn:
                raise ValueError(
                    f"Missing required evaluator_fn for {decision.resolution} on observation '{obs.observation_id}'"
                )
            eval_res = evaluator_fn(profile, obs)
            if not intent_evaluator_fn:
                raise ValueError(
                    f"Missing required intent_evaluator_fn for {decision.resolution} on observation '{obs.observation_id}'"
                )
            intent_res = intent_evaluator_fn(profile, obs, eval_res)
            if not intent_res:
                raise ValueError(
                    f"intent_evaluator_fn returned None for {decision.resolution} on observation '{obs.observation_id}'. A valid OpportunityIntentDecision is required."
                )

            if intent_res.opportunity_intent == "WATCH_LEARN":
                if not market_intelligence_evaluator_fn:
                    raise ValueError(
                        f"Missing required market_intelligence_evaluator_fn for WATCH_LEARN on observation '{obs.observation_id}'"
                    )
                intel_res = market_intelligence_evaluator_fn(profile, obs, eval_res, intent_res)
                if not intel_res:
                    raise ValueError(
                        f"market_intelligence_evaluator_fn returned None for WATCH_LEARN on observation '{obs.observation_id}'"
                    )

        session.stage_decision(obs, decision, eval_res, intent_res, intel_res)

    return session.commit_and_finalize(
        reports_dir=reports_dir,
        run_date=run_date,
        network_changes=network_changes,
        acquisition_gaps=acquisition_gaps,
        coverage_caveat=coverage_caveat,
    )
