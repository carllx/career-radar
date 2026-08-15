"""
Public transport-neutral runner entrypoint for Career Radar MVP-1.
Can be invoked by IDE Agent / Skill / script.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml

from .evaluator import DiscreteEvaluator
from .models import CandidateProfile, Opportunity, SourceObservation
from .reporter import DigestReporter
from .store import OpportunityStore


def run_radar_pipeline(
    profile_path: Union[str, Path],
    observations_source: Union[str, Path, List[Dict[str, Any]]],
    data_dir: Union[str, Path] = ".data",
    reports_dir: Union[str, Path] = "reports",
    run_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes a complete Career Radar Run:
    1. Loads private profile
    2. Loads SourceObservations
    3. Executes Agent discrete semantic evaluation across 6 canonical dimensions
    4. Forms Opportunity entities
    5. Persists state to .data/opportunities.jsonl
    6. Generates Markdown Daily Digest (reports/YYYY-MM-DD.md)
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

    # 3. Evaluate each observation
    evaluator = DiscreteEvaluator()
    opportunities: List[Opportunity] = []

    recommended_count = 0
    review_count = 0
    mismatch_count = 0

    for obs in observations:
        eval_result = evaluator.evaluate(profile, obs)

        rec = eval_result.final_recommendation
        if rec == "建议关注":
            recommended_count += 1
        elif rec == "需要人工确认":
            review_count += 1
        else:
            mismatch_count += 1

        opp = Opportunity(
            opportunity_id=f"opp_{obs.organization}_{obs.job_title}".replace(" ", "_"),
            canonical_job_title=obs.job_title,
            organization=obs.organization,
            location=obs.location,
            track=obs.track,
            official_url=obs.official_url,
            lifecycle_status="active",
            observations=[obs],
            latest_evaluation=eval_result,
            created_at=obs.observed_at,
            updated_at=obs.observed_at,
        )
        opportunities.append(opp)

    # 4. Save state to local store
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


def main():
    """CLI entrypoint for standalone run."""
    import sys

    profile_file = Path("profile.local.yaml")
    if not profile_file.exists():
        profile_file = Path("config/profile.example.yaml")

    fixture_file = Path("config/fixtures/mock_observations.example.json")
    if not fixture_file.exists():
        print(f"Fixture file not found: {fixture_file}")
        sys.exit(1)

    result = run_radar_pipeline(
        profile_path=profile_file,
        observations_source=fixture_file,
        data_dir=".data",
        reports_dir="reports",
    )
    print(f"[Career Radar Run Completed] Total: {result['total_evaluated']} | Recommended: {result['recommended_count']} | Review: {result['review_count']}")
    print(f"Daily Digest Report generated at: {result['report_path']}")


if __name__ == "__main__":
    main()
