"""
Deterministic Radar Pipeline Coordinator for Career Radar MVP-1.
Respects ADR-0002: The Agent is the sole Workflow Orchestrator and semantic authority.
This class acts as the deterministic helper coordinator for executing mechanical steps:
1. Load Candidate Profile, Public Source Seeds, Local Source State, Prior Opportunity State.
2. Apply Agent Source Lifecycle Decisions (Discovery / Degradation / Reactivation).
3. Record Mechanical Monitoring Facts (actual technical checks).
4. Process Observations via Incremental Working State (Candidate Retrieval, Agent Entity Resolution & Qualification Matching).
5. Single-shot persistence to .data/opportunities.jsonl and .data/sources.json.
6. Render 4-section Daily Digest (reports/YYYY-MM-DD.md).
7. Return RadarRunOutcome.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import yaml

from .evaluator import EvaluationValidator
from .models import (
    CandidateProfile,
    EntityResolutionDecision,
    EvaluationResult,
    Opportunity,
    OpportunityIntentDecision,
    SourceObservation,
)
from .runner import IncrementalResolutionSession
from .sources import MonitoringFact, SourceLifecycleDecision, SourceRecord, SourceRegistry


@dataclass
class RadarRunOutcome:
    """
    Standardized, coarse-grained outcome summary for the Agent Run.
    Suitable for scheduler status checks and human/IDE quick glances.
    """
    status: str  # "success", "partial", "failure", "attention"
    run_date: str
    monitored_sources_count: int
    discovered_sources_count: int
    new_opportunities_count: int
    updated_opportunities_count: int
    deduped_same_count: int
    recommended_count: int
    review_count: int
    network_changes_count: int
    report_path: str
    summary_message: str
    apply_now_count: int = 0
    conditional_count: int = 0
    watch_learn_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RadarOrchestrator:
    """
    Deterministic helper coordinator for the Career Radar pipeline.
    Executes mechanical stages while delegating all semantic and lifecycle decisions to the Agent.
    """

    def __init__(
        self,
        profile_path: Union[str, Path] = "profile.local.yaml",
        seed_sources_path: Union[str, Path] = "config/sources.seed.json",
        data_dir: Union[str, Path] = ".data",
        reports_dir: Union[str, Path] = "reports",
    ):
        self.profile_path = Path(profile_path)
        self.seed_sources_path = Path(seed_sources_path)
        self.data_dir = Path(data_dir)
        self.reports_dir = Path(reports_dir)

    def load_profile(self) -> CandidateProfile:
        if not self.profile_path.exists():
            fallback = Path("config/profile.example.yaml")
            if fallback.exists():
                with open(fallback, "r", encoding="utf-8") as f:
                    return CandidateProfile.from_dict(yaml.safe_load(f))
            raise FileNotFoundError(f"Profile configuration not found: {self.profile_path}")

        with open(self.profile_path, "r", encoding="utf-8") as f:
            return CandidateProfile.from_dict(yaml.safe_load(f))

    def run(
        self,
        observations: Optional[List[SourceObservation]] = None,
        source_decisions: Optional[List[SourceLifecycleDecision]] = None,
        monitoring_facts: Optional[List[MonitoringFact]] = None,
        entity_resolver_fn: Optional[
            Callable[[SourceObservation, List[Opportunity]], EntityResolutionDecision]
        ] = None,
        evaluator_fn: Optional[
            Callable[[CandidateProfile, SourceObservation], EvaluationResult]
        ] = None,
        intent_evaluator_fn: Optional[
            Callable[[CandidateProfile, SourceObservation, EvaluationResult], OpportunityIntentDecision]
        ] = None,
        run_date: Optional[str] = None,
    ) -> RadarRunOutcome:
        """
        Executes a deterministic pipeline run driven by Agent decisions and actual execution facts.
        """
        if not run_date:
            run_date = datetime.now().strftime("%Y-%m-%d")

        profile = self.load_profile()
        source_registry = SourceRegistry(
            seed_path=self.seed_sources_path, data_dir=self.data_dir
        )

        # 1. Apply Agent Source Lifecycle Decisions (Discovery / Degradation / Reactivation)
        if source_decisions:
            for s_dec in source_decisions:
                source_registry.apply_lifecycle_decision(s_dec)

        # 2. Record Mechanical Technical Execution Facts from actual monitoring
        actual_monitored_count = 0
        has_monitoring_failure = False
        if monitoring_facts:
            actual_monitored_count = len(monitoring_facts)
            for fact in monitoring_facts:
                source_registry.record_monitoring_fact(fact)
                if fact.technical_status not in ("success", "ok"):
                    has_monitoring_failure = True

        # 3. Process Observations via Incremental Working State
        incoming_observations = observations or []
        session = IncrementalResolutionSession(data_dir=self.data_dir)

        for i, obs in enumerate(incoming_observations):
            packet, candidates = session.prepare_observation_packet(obs)

            if entity_resolver_fn:
                decision = entity_resolver_fn(obs, candidates)
            elif len(session.working_opportunities) == 0:
                decision = EntityResolutionDecision(
                    resolution="different", rationale="Bootstrap initial opportunity"
                )
            else:
                raise ValueError(
                    f"Working state contains opportunities ({len(session.working_opportunities)} records), "
                    "but no entity_resolver_fn was provided. Entity resolution is required once working state contains opportunities."
                )

            eval_res = None
            intent_res = None
            if decision.resolution in ("different", "update", "uncertain"):
                if not evaluator_fn:
                    raise ValueError(
                        f"Missing required evaluator_fn for {decision.resolution} on observation '{obs.observation_id}'"
                    )
                eval_res = evaluator_fn(profile, obs)
                if intent_evaluator_fn:
                    intent_res = intent_evaluator_fn(profile, obs, eval_res)

            session.stage_decision(obs, decision, eval_res, intent_res)

        # 4. Atomic Commit of Opportunities and Sources
        network_changes = source_registry.network_changes
        summary = session.commit_and_finalize(
            reports_dir=self.reports_dir,
            run_date=run_date,
            network_changes=network_changes,
        )
        source_registry.save_local_state()

        # 5. Build Outcome
        discovered_count = sum(1 for c in network_changes if c.get("type") == "discovered")
        has_attention = (
            summary["review_count"] > 0
            or any(c.get("type") == "degraded" for c in network_changes)
            or has_monitoring_failure
        )
        status = "attention" if has_attention else "success"

        summary_msg = (
            f"Radar Run ({run_date}) 完成：实际监测 {actual_monitored_count} 个渠道，"
            f"新发现 {discovered_count} 个渠道；"
            f"新增机会 {summary['new_opportunities_count']} 个（资格建议关注 {summary['recommended_count']} 个，待人工确认 {summary['review_count']} 个）；"
            f"行动建议分布：即刻行动 {summary.get('apply_now_count', 0)} 个，"
            f"条件关注 {summary.get('conditional_count', 0)} 个，"
            f"情报观测 {summary.get('watch_learn_count', 0)} 个。"
        )

        return RadarRunOutcome(
            status=status,
            run_date=run_date,
            monitored_sources_count=actual_monitored_count,
            discovered_sources_count=discovered_count,
            new_opportunities_count=summary["new_opportunities_count"],
            updated_opportunities_count=summary["updated_opportunities_count"],
            deduped_same_count=summary["deduped_same_count"],
            recommended_count=summary["recommended_count"],
            review_count=summary["review_count"],
            network_changes_count=len(network_changes),
            report_path=summary["report_path"],
            summary_message=summary_msg,
            apply_now_count=summary.get("apply_now_count", 0),
            conditional_count=summary.get("conditional_count", 0),
            watch_learn_count=summary.get("watch_learn_count", 0),
        )
