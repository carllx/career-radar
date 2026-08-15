"""
Public transport-neutral runner entrypoint for Career Radar MVP-1.
Supports the IDE-Agent-facing two-phase workflow:
1. PREPARE: load inputs and assemble Evidence Packets for Agent inspection.
2. DECIDE: Agent (IDE Agent) performs semantic evaluation across canonical dimensions.
3. FINALIZE: mechanically validate schema, aggregate, persist atomically, render Daily Digest.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import yaml

from .evaluator import EvaluationValidator, build_evaluation_packet
from .models import (
    CandidateProfile,
    EvaluationResult,
    Opportunity,
    SourceObservation,
)
from .reporter import DigestReporter
from .store import OpportunityStore


def prepare_evaluation_run(
    profile_path: Union[str, Path],
    observations_source: Union[str, Path, List[Dict[str, Any]]],
) -> Tuple[CandidateProfile, List[SourceObservation], List[Dict[str, Any]]]:
    """
    Phase 1 (Deterministic Helper):
    Loads profile and observations, and prepares structured Evidence Packets for the Agent.
    Does NOT perform any semantic evaluation.
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
    else:
        raw_observations = observations_source

    observations = [SourceObservation.from_dict(obs) for obs in raw_observations]
    packets = [build_evaluation_packet(profile, obs) for obs in observations]

    return profile, observations, packets


def finalize_evaluation_run(
    observations: List[SourceObservation],
    evaluation_results: List[EvaluationResult],
    data_dir: Union[str, Path] = ".data",
    reports_dir: Union[str, Path] = "reports",
    run_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Phase 3 (Deterministic Helper):
    Validates Agent EvaluationResults, builds Opportunities with temporary opaque IDs,
    atomically persists local state, and renders the Daily Digest report.
    """
    if len(observations) != len(evaluation_results):
        raise ValueError(
            f"Mismatched counts: {len(observations)} observations vs {len(evaluation_results)} evaluation results"
        )

    data_dir = Path(data_dir)
    reports_dir = Path(reports_dir)

    if not run_date:
        run_date = datetime.now().strftime("%Y-%m-%d")

    opportunities: List[Opportunity] = []
    recommended_count = 0
    review_count = 0
    mismatch_count = 0

    for obs, raw_result in zip(observations, evaluation_results):
        validated_result = EvaluationValidator.validate_and_aggregate(raw_result)

        rec = validated_result.final_recommendation
        if rec == "建议关注":
            recommended_count += 1
        elif rec == "需要人工确认":
            review_count += 1
        else:
            mismatch_count += 1

        # Temporary opaque ID in #9 without premature entity resolution
        opp_id = f"opp_{obs.observation_id}"

        opp = Opportunity(
            opportunity_id=opp_id,
            canonical_job_title=obs.job_title,
            organization=obs.organization,
            location=obs.location,
            track=obs.track,
            official_url=obs.official_url,
            lifecycle_status="active",
            observations=[obs],
            latest_evaluation=validated_result,
            created_at=obs.observed_at,
            updated_at=obs.observed_at,
        )
        opportunities.append(opp)

    # Atomic persistence
    store = OpportunityStore(data_dir)
    store.save_opportunities(opportunities)

    # Render Markdown Daily Digest
    reporter = DigestReporter(reports_dir)
    report_file = reporter.generate_report(opportunities, run_date=run_date)

    return {
        "success": True,
        "run_date": run_date,
        "total_evaluated": len(opportunities),
        "recommended_count": recommended_count,
        "review_count": review_count,
        "mismatch_count": mismatch_count,
        "report_path": str(report_file),
        "opportunities": [opp.to_dict() for opp in opportunities],
    }


def run_radar_pipeline(
    profile_path: Union[str, Path],
    observations_source: Union[str, Path, List[Dict[str, Any]]],
    evaluator_fn: Callable[[CandidateProfile, SourceObservation], EvaluationResult],
    data_dir: Union[str, Path] = ".data",
    reports_dir: Union[str, Path] = "reports",
    run_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Unified execution entrypoint across the Highest Testing Seam:
    Prepare -> Evaluate (via injected evaluator) -> Finalize.
    """
    profile, observations, _ = prepare_evaluation_run(
        profile_path=profile_path, observations_source=observations_source
    )
    eval_results = [evaluator_fn(profile, obs) for obs in observations]
    return finalize_evaluation_run(
        observations=observations,
        evaluation_results=eval_results,
        data_dir=data_dir,
        reports_dir=reports_dir,
        run_date=run_date,
    )
