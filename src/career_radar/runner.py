"""
Public transport-neutral runner entrypoint for Career Radar MVP-1.
Supports the IDE-Agent-facing two-phase workflow:
1. PREPARE: load inputs / fetch first-party announcements, retrieve candidates, assemble Evidence Packets.
2. DECIDE: Agent (IDE Agent) performs entity resolution (same/update/different/uncertain) and discrete matching across canonical dimensions.
3. FINALIZE: mechanically apply resolution, validate schema, aggregate, persist atomically, render Daily Digest.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import yaml

from .evaluator import EvaluationValidator, build_evaluation_packet
from .extractor import AnnouncementExtractor
from .fetcher import AnnouncementFetcher, AttachmentAccessError
from .models import (
    CandidateProfile,
    EntityResolutionDecision,
    EvaluationResult,
    Opportunity,
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

    # Determine extraction completeness and mechanical technical status
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


def prepare_evaluation_run(
    profile_path: Union[str, Path],
    observations_source: Union[str, Path, List[Dict[str, Any]], List[SourceObservation]],
    data_dir: Union[str, Path] = ".data",
) -> Tuple[CandidateProfile, List[SourceObservation], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Phase 1 (Deterministic Helper):
    Loads profile, prior opportunities, and new observations.
    Retrieves candidates and prepares structured Evidence Packets for both Entity Resolution and Eligibility.
    Returns (profile, observations, resolution_packets, eligibility_packets).
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

    # Load prior historical opportunities from store
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
    """
    Phase 3 (Deterministic Helper):
    Applies Agent EntityResolutionDecisions to mutate Opportunity state,
    attaches validated Eligibility evaluations, atomically persists state,
    and renders the incremental Daily Digest.
    """
    if len(observations) != len(resolution_decisions):
        raise ValueError(
            f"Mismatched counts: {len(observations)} observations vs {len(resolution_decisions)} resolution decisions"
        )

    data_dir = Path(data_dir)
    reports_dir = Path(reports_dir)

    if not run_date:
        run_date = datetime.now().strftime("%Y-%m-%d")

    store = OpportunityStore(data_dir)
    prior_opps = store.load_all_opportunities()
    opps_map: Dict[str, Opportunity] = {o.opportunity_id: o for o in prior_opps}

    applier = EntityResolutionApplier()
    new_opp_ids: List[str] = []
    updated_opp_ids: List[str] = []
    deduped_same_count = 0

    # First validate and apply all decisions in memory before persisting
    for obs, decision in zip(observations, resolution_decisions):
        eval_res = evaluation_results.get(obs.observation_id)
        if not eval_res and decision.target_opportunity_id:
            eval_res = evaluation_results.get(decision.target_opportunity_id)

        validated_eval = None
        if eval_res:
            validated_eval = EvaluationValidator.validate_and_aggregate(eval_res)

        opp, action = applier.apply_decision(
            observation=obs,
            decision=decision,
            opportunities_map=opps_map,
            evaluation_result=validated_eval,
            current_time=datetime.now().isoformat(),
        )

        if action == "deduplicated_same":
            deduped_same_count += 1
        elif action == "updated_opportunity":
            updated_opp_ids.append(opp.opportunity_id)
        elif action in ("new_different", "new_uncertain"):
            new_opp_ids.append(opp.opportunity_id)

    # Persist all mutated/created opportunities atomically
    all_opportunities = list(opps_map.values())
    store.save_opportunities(all_opportunities)

    # Render Daily Digest
    reporter = DigestReporter(reports_dir)
    report_file = reporter.generate_report(
        all_opportunities,
        run_date=run_date,
        new_opportunity_ids=new_opp_ids,
        updated_opportunity_ids=updated_opp_ids,
    )

    recommended_count = sum(
        1 for o in all_opportunities
        if o.opportunity_id in new_opp_ids and o.latest_evaluation and o.latest_evaluation.final_recommendation == "建议关注"
    )
    review_count = sum(
        1 for o in all_opportunities
        if (o.opportunity_id in new_opp_ids or o.opportunity_id in updated_opp_ids)
        and (
            (o.latest_evaluation and o.latest_evaluation.final_recommendation == "需要人工确认")
            or o.uncertain_links
        )
    )
    mismatch_count = sum(
        1 for o in all_opportunities
        if o.opportunity_id in new_opp_ids and o.latest_evaluation and o.latest_evaluation.final_recommendation == "明显不符合"
    )

    return {
        "success": True,
        "run_date": run_date,
        "total_evaluated": len(observations),
        "total_in_store": len(all_opportunities),
        "new_opportunities_count": len(new_opp_ids),
        "updated_opportunities_count": len(updated_opp_ids),
        "deduped_same_count": deduped_same_count,
        "recommended_count": recommended_count,
        "review_count": review_count,
        "mismatch_count": mismatch_count,
        "report_path": str(report_file),
        "opportunities": [opp.to_dict() for opp in all_opportunities],
    }


def finalize_evaluation_run(
    observations: List[SourceObservation],
    evaluation_results: List[EvaluationResult],
    data_dir: Union[str, Path] = ".data",
    reports_dir: Union[str, Path] = "reports",
    run_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Standard finalize entrypoint.
    If prior opportunities exist in store, failing fast is REQUIRED unless explicit Agent resolution is provided.
    Defaulting to 'different' is permitted ONLY during initial empty-state bootstrap.
    """
    store = OpportunityStore(Path(data_dir))
    prior_opps = store.load_all_opportunities()
    if len(prior_opps) > 0:
        raise ValueError(
            f"Prior opportunities exist in store ({len(prior_opps)} records), but no Agent entity resolution was provided. "
            "Helper is prohibited from assuming 'different' when prior state exists."
        )

    default_decisions = [
        EntityResolutionDecision(resolution="different", rationale="Bootstrap initial opportunity")
        for _ in observations
    ]
    eval_map = {
        obs.observation_id: ev for obs, ev in zip(observations, evaluation_results)
    }
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
    entity_resolver_fn: Optional[Callable[[SourceObservation, List[Opportunity]], EntityResolutionDecision]] = None,
    data_dir: Union[str, Path] = ".data",
    reports_dir: Union[str, Path] = "reports",
    run_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Unified execution entrypoint across the Highest Testing Seam:
    Prepare -> Resolve Entity (via Agent resolver) -> Evaluate Eligibility -> Finalize.
    If prior state exists, entity_resolver_fn is strictly required.
    """
    profile, observations, res_packets, _ = prepare_evaluation_run(
        profile_path=profile_path,
        observations_source=observations_source,
        data_dir=data_dir,
    )

    store = OpportunityStore(Path(data_dir))
    prior_opps = store.load_all_opportunities()
    retriever = CandidateRetriever()

    if len(prior_opps) > 0 and entity_resolver_fn is None:
        raise ValueError(
            f"Prior opportunities exist in store ({len(prior_opps)} records), but no entity_resolver_fn was provided. "
            "Helper is strictly prohibited from assuming 'different' when prior state exists."
        )

    res_decisions: List[EntityResolutionDecision] = []
    eval_results_map: Dict[str, EvaluationResult] = {}

    for obs in observations:
        if entity_resolver_fn:
            candidates = retriever.retrieve_candidates(obs, prior_opps)
            decision = entity_resolver_fn(obs, candidates)
        else:
            decision = EntityResolutionDecision(resolution="different", rationale="Bootstrap initial opportunity")
        res_decisions.append(decision)

        # For different, update, and uncertain: evaluate eligibility
        if decision.resolution in ("different", "update", "uncertain"):
            eval_res = evaluator_fn(profile, obs)
            eval_results_map[obs.observation_id] = eval_res

    return finalize_incremental_run(
        observations=observations,
        resolution_decisions=res_decisions,
        evaluation_results=eval_results_map,
        data_dir=data_dir,
        reports_dir=reports_dir,
        run_date=run_date,
    )
