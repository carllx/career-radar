"""
CLI entry point for Career Radar manual trigger and scheduler execution.
Invokes the unified RadarOrchestrator.
"""

import argparse
import json
import sys
from pathlib import Path

from .orchestrator import RadarOrchestrator


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Career Radar — Autonomous Intelligence and Recruitment Tracker"
    )
    parser.add_argument(
        "--profile",
        default="profile.local.yaml",
        help="Path to candidate profile (default: profile.local.yaml, falls back to config/profile.example.yaml)",
    )
    parser.add_argument(
        "--seeds",
        default="config/sources.seed.json",
        help="Path to public seeds (default: config/sources.seed.json)",
    )
    parser.add_argument(
        "--data-dir",
        default=".data",
        help="Data directory (default: .data)",
    )
    parser.add_argument(
        "--reports-dir",
        default="reports",
        help="Reports output directory (default: reports)",
    )
    parser.add_argument(
        "--run-date",
        default=None,
        help="Custom run date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output outcome summary in JSON format",
    )

    args = parser.parse_args()

    orchestrator = RadarOrchestrator(
        profile_path=args.profile,
        seed_sources_path=args.seeds,
        data_dir=args.data_dir,
        reports_dir=args.reports_dir,
    )

    outcome = orchestrator.run(run_date=args.run_date)

    if args.json:
        print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"[{outcome.status.upper()}] {outcome.summary_message}")
        print(f"Report saved to: {outcome.report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
