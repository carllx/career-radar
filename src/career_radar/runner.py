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

from .evaluator import EvaluationValidator, IntentValidator, build_evaluation_packet
from .extractor import AnnouncementExtractor
from .fetcher import AnnouncementFetcher, AttachmentAccessError
from .models import (
    CandidateProfile,
    EntityResolutionDecision,
    EvaluationResult,
    Opportunity,
    OpportunityIntentDecision,
    SourceObservation,
)
from .parser import HTMLAnnouncementParser
from .reporter import DigestReporter
from .resolver import EntityResolutionApplier, build_entity_resolution_packet
from .retriever import CandidateRetriever
from .store import OpportunityStore


def fetch_and_extract_first_party_announcement(
    announcement_url: str,
    source_id: str,
    source_name: str,
    cache_dir: Optional[Path] = None,
    verify_ssl: bool = True,
    recruiting_organization: Optional[str] = None,
) -> Tuple[List[SourceObservation], Dict[str, Any]]:
    """
    Fetches a live first-party announcement page, downloads its discovered attachments,
    and slices them into discrete SourceObservations without business rules.
    Returns (observations, extraction_report).
    """
    cache_dir = cache_dir or Path(".data/announcements")
    fetcher = AnnouncementFetcher(cache_dir=cache_dir, verify_ssl=verify_ssl)
    fetched = fetcher.fetch_announcement_html(announcement_url)

    html_parser = HTMLAnnouncementParser()
    parsed_meta = html_parser.parse(fetched["html_content"], base_url=announcement_url)

    entry_dir = Path(fetched["entry_dir"])
    downloaded_attachments = []
    attachment_reports = []

    for att in parsed_meta["attachments"]:
        if not att.get("supported", True):
            attachment_reports.append({
                "name": att.get("name"),
                "url": att.get("url"),
                "extension": att.get("extension"),
                "status": "unsupported_legacy_format",
                "error": f"Legacy format {att.get('extension')} is not supported.",
            })
            continue

        try:
            local_att = fetcher.download_attachment(
                att["url"], entry_dir=entry_dir, attachment_meta=att
            )
            downloaded_attachments.append(local_att)
            attachment_reports.append({
                "name": att.get("name"),
                "url": att.get("url"),
                "extension": att.get("extension"),
                "status": "downloaded",
                "local_path": str(local_att),
            })
        except AttachmentAccessError as e:
            attachment_reports.append({
                "name": att.get("name"),
                "url": att.get("url"),
                "extension": att.get("extension"),
                "status": e.reason,
                "error": str(e),
            })
        except Exception as e:
            attachment_reports.append({
                "name": att.get("name"),
                "url": att.get("url"),
                "extension": att.get("extension"),
                "status": "download_failed",
                "error": str(e),
            })

    extractor = AnnouncementExtractor(cache_dir=cache_dir)
    observations = extractor.extract_from_html_and_attachments(
        html_content=fetched["html_content"],
        source_url=announcement_url,
        source_id=source_id,
        source_name=source_name,
        local_attachment_paths=downloaded_attachments,
        recruiting_organization=recruiting_organization,
        observed_at=fetched.get("fetched_at"),
    )

    has_captcha = any(r.get("status") == "blocked_by_captcha" for r in attachment_reports)
    has_type_mismatch = any(r.get("status") == "content_type_mismatch" for r in attachment_reports)

    if has_captcha:
        extraction_completeness = "incomplete"
        attachment_access = "blocked_by_captcha"
    elif has_type_mismatch:
        extraction_completeness = "incomplete"
        attachment_access = "content_type_mismatch"
    elif downloaded_attachments and not observations:
        extraction_completeness = "incomplete_or_no_jobs"
        attachment_access = "success"
    elif not downloaded_attachments and parsed_meta["attachments"]:
        extraction_completeness = "incomplete"
        attachment_access = "failed"
    else:
        extraction_completeness = "complete" if observations else "no_attachments"
        attachment_access = "success" if downloaded_attachments else "none"

    report = {
        "announcement_title": parsed_meta["title"],
        "source_url": announcement_url,
        "source_id": source_id,
        "source_name": source_name,
        "recruiting_organization": recruiting_organization,
        "verify_ssl": verify_ssl,
        "attachment_access": attachment_access,
        "extraction_completeness": extraction_completeness,
        "attachments": attachment_reports,
        "observations_count": len(observations),
    }

    return observations, report


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

        opp, action = self.applier.apply_decision(
            observation=observation,
            decision=decision,
            opportunities_map=self.working_map,
            evaluation_result=validated_eval,
            intent_decision=validated_intent,
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
    data_dir: Union[str, Path] = ".data",
    reports_dir: Union[str, Path] = "reports",
    run_date: Optional[str] = None,
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
        session.stage_decision(
            observation=obs,
            decision=decision,
            evaluation_result=eval_res,
            current_time=datetime.now().isoformat(),
        )
    return session.commit_and_finalize(reports_dir=reports_dir, run_date=run_date)


def finalize_evaluation_run(
    observations: List[SourceObservation],
    evaluation_results: List[EvaluationResult],
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
    return finalize_incremental_run(
        observations=observations,
        resolution_decisions=default_decisions,
        evaluation_results=eval_map,
        data_dir=data_dir,
        reports_dir=reports_dir,
        run_date=run_date,
    )


def run_radar_pipeline(
    profile_path: Union[str, Path],
    observations_source: Union[str, Path, List[Dict[str, Any]], List[SourceObservation]],
    evaluator_fn: Callable[[CandidateProfile, SourceObservation], EvaluationResult],
    intent_evaluator_fn: Optional[Callable[[CandidateProfile, SourceObservation, EvaluationResult], OpportunityIntentDecision]] = None,
    entity_resolver_fn: Optional[Callable[[SourceObservation, List[Opportunity]], EntityResolutionDecision]] = None,
    data_dir: Union[str, Path] = ".data",
    reports_dir: Union[str, Path] = "reports",
    run_date: Optional[str] = None,
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
        if decision.resolution in ("different", "update", "uncertain"):
            eval_res = evaluator_fn(profile, obs)
            if intent_evaluator_fn:
                intent_res = intent_evaluator_fn(profile, obs, eval_res)

        session.stage_decision(obs, decision, eval_res, intent_res)

    return session.commit_and_finalize(reports_dir=reports_dir, run_date=run_date)
