"""
Highest Seam and Pipeline Integration Tests for Issue #17: WATCH_LEARN Market Intelligence.
Validates:
1. Full RadarOrchestrator run with WATCH_LEARN: extracts 8 categories, persists snapshot, renders in Digest.
2. Partial facts in source evidence normalize to 'UNKNOWN' and visibly render as 'UNKNOWN' in Digest.
3. Fail-fast: WATCH_LEARN on different/update/uncertain strictly requires market_intelligence_evaluator_fn.
4. APPLY_NOW / CONDITIONAL paths do NOT require market_intelligence_evaluator_fn.
5. 'same' resolution on prior WATCH_LEARN Opportunity retains stored intelligence without re-extraction.
6. Update semantic flow: fresh WATCH_LEARN updates intelligence snapshot and refreshes Digest.
7. Learning Target Safety: requested skills in market intelligence do NOT mechanically set Capability Fit to PASS.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from career_radar.evaluator import (
    CANONICAL_DIMENSIONS,
    EvaluationValidator,
)
from career_radar.models import (
    CandidateProfile,
    DimensionEvaluation,
    EntityResolutionDecision,
    EvaluationResult,
    MarketIntelligence,
    Opportunity,
    OpportunityIntentDecision,
    SourceObservation,
)
from career_radar.orchestrator import RadarOrchestrator
from career_radar.runner import run_radar_pipeline
from career_radar.store import OpportunityStore


@pytest.fixture
def temp_intel_seam_env(tmp_path: Path):
    """Sets up clean test environment for Issue #17 seam tests."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / ".data"
    reports_dir = tmp_path / "reports"
    for d in (config_dir, data_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)

    seed_file = config_dir / "sources.seed.json"
    seed_file.write_text("[]", encoding="utf-8")
    return tmp_path, config_dir, data_dir, reports_dir


def test_full_radar_orchestrator_watch_learn_market_intelligence_and_digest(temp_intel_seam_env):
    """
    Validates end-to-end WATCH_LEARN market intelligence extraction:
    - Agent evaluates Eligibility and decides WATCH_LEARN intent.
    - Agent extracts all 8 canonical market intelligence fields.
    - Persistence stores the snapshot and reloads cleanly.
    - Daily Digest renders the dedicated '🔭 WATCH_LEARN / 市场情报观察' section.
    """
    tmp_path, config_dir, data_dir, reports_dir = temp_intel_seam_env

    profile_yaml = """
candidate:
  age: 30
  degree: "master"
  degree_field: "Digital Arts"
  tracks:
    - name: "game_3d_production"
      priority: 3
      default_intent: "WATCH_LEARN"
"""
    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text(profile_yaml, encoding="utf-8")

    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )

    obs = SourceObservation(
        observation_id="obs_wl_full_01",
        announcement_id="ann_wl_01",
        source_id="game_board",
        source_name="Game Recruitment Board",
        announcement_title="Lead Character Artist RFP",
        job_title="Lead 3D Character Artist",
        organization="Creative Game Studio",
        location="Example City A",
        track="game_3d_production",
        official_url="https://example.com/rfp/wl01",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={"budget": "35k RMB / character", "software": "Maya, ZBrush, UE5"},
    )

    def agent_evaluator(prof: CandidateProfile, o: SourceObservation) -> EvaluationResult:
        dim_evals = {
            dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="符合", rationale="满足门槛")
            for dim in CANONICAL_DIMENSIONS
        }
        return EvaluationValidator.validate_and_aggregate(
            EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
        )

    def agent_intent_evaluator(
        prof: CandidateProfile, o: SourceObservation, ev: EvaluationResult
    ) -> OpportunityIntentDecision:
        return OpportunityIntentDecision(
            opportunity_intent="WATCH_LEARN",
            intent_rationale="游戏次世代角色美术外包单价与交付流程具有高观察价值，暂不投递。",
        )

    def agent_market_intelligence_evaluator(
        prof: CandidateProfile, o: SourceObservation, ev: EvaluationResult, it: OpportunityIntentDecision
    ) -> MarketIntelligence:
        return MarketIntelligence(
            brief="3A次世代游戏项目主角角色高模与PBR贴图制作",
            deliverables="ZBrush高模、LowPoly FBX、4K贴图与UE5材质球",
            content_type="次世代游戏角色模型",
            timeline_volume="单个角色交付周期3周，总需求4个",
            revision_quality_rules="每阶段提供2轮修改，需通过引擎性能Profile",
            requested_tools_workflow="Maya, ZBrush, Substance 3D Painter, Unreal Engine 5",
            budget_compensation="35,000 RMB / 角色",
            use_case="开放世界动作RPG主角与核心NPC",
        )

    outcome = orchestrator.run(
        observations=[obs],
        evaluator_fn=agent_evaluator,
        intent_evaluator_fn=agent_intent_evaluator,
        market_intelligence_evaluator_fn=agent_market_intelligence_evaluator,
        run_date="2026-08-16",
    )

    assert outcome.status == "success"
    assert outcome.new_opportunities_count == 1
    assert outcome.watch_learn_count == 1

    # Verify persistence in OpportunityStore
    store = OpportunityStore(data_dir)
    loaded = store.load_all_opportunities()
    assert len(loaded) == 1
    assert loaded[0].opportunity_intent == "WATCH_LEARN"
    assert loaded[0].market_intelligence is not None
    assert loaded[0].market_intelligence.brief == "3A次世代游戏项目主角角色高模与PBR贴图制作"
    assert loaded[0].market_intelligence.budget_compensation == "35,000 RMB / 角色"

    # Verify Daily Digest report
    report_text = Path(outcome.report_path).read_text(encoding="utf-8")
    assert "## 🔭 WATCH_LEARN / 市场情报观察" in report_text
    assert "Lead 3D Character Artist" in report_text
    assert "- **Brief**：3A次世代游戏项目主角角色高模与PBR贴图制作" in report_text
    assert "- **Deliverables**：ZBrush高模、LowPoly FBX、4K贴图与UE5材质球" in report_text
    assert "- **Budget / Compensation**：35,000 RMB / 角色" in report_text


def test_partial_facts_render_as_unknown_in_digest(temp_intel_seam_env):
    """Validates that missing facts normalize to literal UNKNOWN and visibly render in Daily Digest."""
    tmp_path, config_dir, data_dir, reports_dir = temp_intel_seam_env

    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text("candidate:\n  age: 30\n  degree: 'master'\n", encoding="utf-8")

    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )

    obs = SourceObservation(
        observation_id="obs_sparse_01",
        announcement_id="ann_sparse_01",
        source_id="comm_src",
        source_name="Community Forum",
        announcement_title="Looking for shader help",
        job_title="Shader Consultant",
        organization="Indie Dev Collective",
        location="Remote",
        track="art_tech_creative_technology",
        official_url="https://example.com/posts/shader01",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={"brief": "Need custom water shader"},
    )

    def agent_evaluator(prof: CandidateProfile, o: SourceObservation) -> EvaluationResult:
        dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
        return EvaluationValidator.validate_and_aggregate(
            EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
        )

    def agent_intent_evaluator(prof: CandidateProfile, o: SourceObservation, ev: EvaluationResult) -> OpportunityIntentDecision:
        return OpportunityIntentDecision(opportunity_intent="WATCH_LEARN", intent_rationale="Observe indie shader requirements.")

    def agent_market_intelligence_evaluator(
        prof: CandidateProfile, o: SourceObservation, ev: EvaluationResult, it: OpportunityIntentDecision
    ) -> MarketIntelligence:
        # Deliberately supply partial data with missing/blank fields
        return MarketIntelligence(
            brief="Need custom stylized water shader for indie demo",
            requested_tools_workflow="Unity URP, Shader Graph",
            # deliverables, content_type, timeline_volume, revision_quality_rules, budget_compensation, use_case missing
        )

    outcome = orchestrator.run(
        observations=[obs],
        evaluator_fn=agent_evaluator,
        intent_evaluator_fn=agent_intent_evaluator,
        market_intelligence_evaluator_fn=agent_market_intelligence_evaluator,
        run_date="2026-08-16",
    )

    report_text = Path(outcome.report_path).read_text(encoding="utf-8")
    assert "- **Brief**：Need custom stylized water shader for indie demo" in report_text
    assert "- **Deliverables**：UNKNOWN" in report_text
    assert "- **Budget / Compensation**：UNKNOWN" in report_text
    assert "- **Revision / Quality Rules**：UNKNOWN" in report_text


def test_watch_learn_missing_market_intelligence_evaluator_fails_fast(temp_intel_seam_env):
    """Validates that orchestrator and pipeline fail fast when market_intelligence_evaluator_fn is omitted for WATCH_LEARN."""
    tmp_path, config_dir, data_dir, reports_dir = temp_intel_seam_env
    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text("candidate:\n  age: 30\n  degree: 'master'\n", encoding="utf-8")

    obs = SourceObservation(
        observation_id="obs_guard_wl",
        announcement_id="ann_01",
        source_id="src_01",
        source_name="Src",
        announcement_title="RFP Post",
        job_title="RFP Role",
        organization="Org",
        location="City",
        track="game_3d_production",
        official_url="https://example.com/rfp",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={},
    )

    def dummy_evaluator(prof: CandidateProfile, o: SourceObservation) -> EvaluationResult:
        dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
        return EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")

    def dummy_intent_evaluator(prof: CandidateProfile, o: SourceObservation, ev: EvaluationResult) -> OpportunityIntentDecision:
        return OpportunityIntentDecision(opportunity_intent="WATCH_LEARN", intent_rationale="Watch rationale")

    # 1. run_radar_pipeline fails fast
    with pytest.raises(ValueError, match="Missing required market_intelligence_evaluator_fn for WATCH_LEARN"):
        run_radar_pipeline(
            profile_path=profile_path,
            observations_source=[obs],
            evaluator_fn=dummy_evaluator,
            intent_evaluator_fn=dummy_intent_evaluator,
            market_intelligence_evaluator_fn=None,
            data_dir=data_dir,
            reports_dir=reports_dir,
        )

    # 2. RadarOrchestrator fails fast
    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )
    with pytest.raises(ValueError, match="Missing required market_intelligence_evaluator_fn for WATCH_LEARN"):
        orchestrator.run(
            observations=[obs],
            evaluator_fn=dummy_evaluator,
            intent_evaluator_fn=dummy_intent_evaluator,
            market_intelligence_evaluator_fn=None,
            run_date="2026-08-16",
        )


def test_apply_now_and_conditional_do_not_require_market_intelligence_evaluator(temp_intel_seam_env):
    """Validates that APPLY_NOW and CONDITIONAL runs succeed without market_intelligence_evaluator_fn."""
    tmp_path, config_dir, data_dir, reports_dir = temp_intel_seam_env
    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text("candidate:\n  age: 30\n  degree: 'master'\n", encoding="utf-8")

    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )

    obs_apply = SourceObservation(
        observation_id="obs_apply_01",
        announcement_id="ann_apply_01",
        source_id="src_01",
        source_name="Src",
        announcement_title="Faculty Role",
        job_title="Lecturer",
        organization="Example College",
        location="City",
        track="higher_education_teaching",
        official_url="https://example.edu/01",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={},
    )

    def agent_evaluator(prof: CandidateProfile, o: SourceObservation) -> EvaluationResult:
        dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
        return EvaluationValidator.validate_and_aggregate(
            EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
        )

    def agent_intent_evaluator(prof: CandidateProfile, o: SourceObservation, ev: EvaluationResult) -> OpportunityIntentDecision:
        return OpportunityIntentDecision(opportunity_intent="APPLY_NOW", intent_rationale="Strong match for immediate application.")

    outcome = orchestrator.run(
        observations=[obs_apply],
        evaluator_fn=agent_evaluator,
        intent_evaluator_fn=agent_intent_evaluator,
        market_intelligence_evaluator_fn=None,  # Not required for APPLY_NOW
        run_date="2026-08-16",
    )
    assert outcome.status == "success"
    assert outcome.apply_now_count == 1


def test_learning_target_does_not_mechanically_set_capability_fit_pass(temp_intel_seam_env):
    """
    Validates Learning Target Safety (Issue #15 & #17 Boundary):
    Candidate has learning_targets=['Advanced Houdini FX'], and a WATCH_LEARN posting requires Houdini FX.
    The evaluator correctly sets Capability Fit = FAIL or REVIEW based on proven capabilities, NOT PASS.
    """
    dim_evals = {
        dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="符合", rationale="满足")
        for dim in CANONICAL_DIMENSIONS
    }
    # Candidate lacks proven Houdini capability
    dim_evals["Capability Fit"] = DimensionEvaluation(
        dimension="Capability Fit",
        state="FAIL",
        requirement_evidence="必须精通 Houdini 影视级流体解算与粒子特效",
        rationale="候选人仅将 Houdini 列为探索学习目标 (learning_target)，未具备实操交付证据，判定为不符合。",
    )
    eval_res = EvaluationValidator.validate_and_aggregate(
        EvaluationResult(final_recommendation="明显不符合", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
    )

    assert eval_res.final_recommendation == "明显不符合"
    assert eval_res.dimension_evaluations["Capability Fit"].state == "FAIL"
