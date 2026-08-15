"""
Public transport-neutral runner entrypoint for Career Radar MVP-1.
Can be invoked by IDE Agent / Skill / script / test harness.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
import yaml

from .evaluator import EvaluationValidator
from .models import (
    CandidateProfile,
    DimensionEvaluation,
    EvaluationResult,
    Opportunity,
    SourceObservation,
)
from .reporter import DigestReporter
from .store import OpportunityStore


def run_radar_pipeline(
    profile_path: Union[str, Path],
    observations_source: Union[str, Path, List[Dict[str, Any]]],
    evaluator_fn: Callable[[CandidateProfile, SourceObservation], EvaluationResult],
    data_dir: Union[str, Path] = ".data",
    reports_dir: Union[str, Path] = "reports",
    run_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes a complete Career Radar Run at the highest seam:
    1. Loads private profile
    2. Loads SourceObservations
    3. Invokes the Agent semantic evaluator for 6-dimension discrete evaluation
    4. Validates structured evaluation result and computes canonical recommendation
    5. Forms Opportunity entities (using temporary/opaque ID in #9)
    6. Persists state atomically to .data/opportunities.jsonl
    7. Generates Markdown Daily Digest (reports/YYYY-MM-DD.md)
    """
    profile_path = Path(profile_path)
    data_dir = Path(data_dir)
    reports_dir = Path(reports_dir)

    if not run_date:
        run_date = datetime.now().strftime("%Y-%m-%d")

    # 1. Load Candidate Profile
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile configuration not found: {profile_path}")

    with open(profile_path, "r", encoding="utf-8") as f:
        raw_profile = yaml.safe_load(f)
    profile = CandidateProfile.from_dict(raw_profile)

    # 2. Load Source Observations
    if isinstance(observations_source, (str, Path)):
        obs_file = Path(observations_source)
        if not obs_file.exists():
            raise FileNotFoundError(f"Observations file not found: {obs_file}")
        with open(obs_file, "r", encoding="utf-8") as f:
            raw_observations = json.load(f)
    else:
        raw_observations = observations_source

    observations = [SourceObservation.from_dict(obs) for obs in raw_observations]

    # 3. Evaluate each observation via the Agent semantic seam
    opportunities: List[Opportunity] = []

    recommended_count = 0
    review_count = 0
    mismatch_count = 0

    for obs in observations:
        raw_result = evaluator_fn(profile, obs)
        validated_result = EvaluationValidator.validate_and_aggregate(raw_result)

        rec = validated_result.final_recommendation
        if rec == "建议关注":
            recommended_count += 1
        elif rec == "需要人工确认":
            review_count += 1
        else:
            mismatch_count += 1

        # In #9: Opaque/temporary Opportunity ID without claiming cross-channel deduplication
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

    # 4. Atomically persist state to local store
    store = OpportunityStore(data_dir)
    store.save_opportunities(opportunities)

    # 5. Generate Markdown Report
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
