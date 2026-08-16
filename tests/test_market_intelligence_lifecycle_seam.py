"""
Highest Seam Lifecycle Tests for Issue #17: WATCH_LEARN Market Intelligence.
Validates:
1. Update semantic flow on WATCH_LEARN: fresh Market Intelligence replaces stale snapshot and updates Daily Digest.
2. 'same' resolution on prior WATCH_LEARN Opportunity retains stored intelligence without invoking semantic evaluators.
"""

from pathlib import Path
import pytest

from career_radar.evaluator import (
    CANONICAL_DIMENSIONS,
    EvaluationValidator,
)
from career_radar.models import (
    DimensionEvaluation,
    EntityResolutionDecision,
    EvaluationResult,
    MarketIntelligence,
    Opportunity,
    OpportunityIntentDecision,
    SourceObservation,
)
from career_radar.orchestrator import RadarOrchestrator
from career_radar.store import OpportunityStore


@pytest.fixture
def temp_intel_lifecycle_env(tmp_path: Path):
    """Sets up clean test environment for Issue #17 lifecycle seam tests."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / ".data"
    reports_dir = tmp_path / "reports"
    for d in (config_dir, data_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)

    seed_file = config_dir / "sources.seed.json"
    seed_file.write_text("[]", encoding="utf-8")
    return tmp_path, config_dir, data_dir, reports_dir


def test_update_watch_learn_market_intelligence_refreshes_snapshot_and_digest(temp_intel_lifecycle_env):
    """
    Validates highest seam vertical flow for UPDATE on WATCH_LEARN:
    1. Prepopulate Opportunity with old Market Intelligence snapshot.
    2. Process an update observation via RadarOrchestrator.
    3. Agent evaluates fresh Eligibility, WATCH_LEARN Intent, and fresh Market Intelligence.
    4. Assertions:
       - Stored Opportunity is updated with fresh MarketIntelligence (old values replaced).
       - Daily Digest dedicated '## 🔭 WATCH_LEARN / 市场情报观察' section renders the updated Opportunity and fresh 8 fields.
    """
    tmp_path, config_dir, data_dir, reports_dir = temp_intel_lifecycle_env

    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text("candidate:\n  age: 30\n  degree: 'master'\n", encoding="utf-8")

    # 1. Prepopulate existing WATCH_LEARN Opportunity with stale Market Intelligence
    store = OpportunityStore(data_dir)
    dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
    old_eval = EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-10T08:00:00")
    old_intel = MarketIntelligence(
        brief="Stale Old Brief 2025",
        deliverables="Old Prototype",
        content_type="Old Spec",
        timeline_volume="2 weeks",
        revision_quality_rules="None",
        requested_tools_workflow="Blender 2.8",
        budget_compensation="15k RMB",
        use_case="Internal Demo",
    )
    existing_opp = Opportunity(
        opportunity_id="opp_td_wl_01",
        canonical_job_title="Lead Technical Director",
        organization="Studio Vertex",
        location="Example City A",
        track="game_3d_production",
        official_url="https://example.com/rfp/td_v1",
        lifecycle_status="active",
        observations=[],
        latest_evaluation=old_eval,
        created_at="2026-08-10T08:00:00",
        updated_at="2026-08-10T08:00:00",
        opportunity_intent="WATCH_LEARN",
        intent_rationale="Initial observation of TD market rates.",
        market_intelligence=old_intel,
    )
    store.save_opportunities([existing_opp])

    # 2. Incoming update observation
    update_obs = SourceObservation(
        observation_id="obs_td_v2",
        announcement_id="ann_td_v2",
        source_id="game_board",
        source_name="Game Board",
        announcement_title="Lead Technical Director RFP Rev 2",
        job_title="Lead Technical Director",
        organization="Studio Vertex",
        location="Example City A",
        track="game_3d_production",
        official_url="https://example.com/rfp/td_v2",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={"budget": "80k RMB", "tools": "UE5.5, Houdini Engine"},
    )

    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )

    def fake_entity_resolver(obs, candidates):
        return EntityResolutionDecision(
            resolution="update",
            target_opportunity_id="opp_td_wl_01",
            diff_summary="增加制作体量并提升预算至80k",
        )

    def fake_evaluator(prof, o):
        return EvaluationValidator.validate_and_aggregate(
            EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
        )

    def fake_intent_evaluator(prof, o, ev):
        return OpportunityIntentDecision(
            opportunity_intent="WATCH_LEARN",
            intent_rationale="更新后预算显著提升，继续保持标杆情报观察。",
        )

    def fake_market_intelligence_evaluator(prof, o, ev, it):
        return MarketIntelligence(
            brief="Fresh 2026 AAA TD Pipeline Brief",
            deliverables="Full Pipeline Toolset & Asset Specs",
            content_type="AAA Game Engine Pipeline",
            timeline_volume="3 months full cycle",
            revision_quality_rules="Milestone acceptance by Technical Director",
            requested_tools_workflow="Unreal Engine 5.5, Houdini Engine, Python",
            budget_compensation="80,000 RMB",
            use_case="AAA Next-Gen Open World Production",
        )

    outcome = orchestrator.run(
        observations=[update_obs],
        entity_resolver_fn=fake_entity_resolver,
        evaluator_fn=fake_evaluator,
        intent_evaluator_fn=fake_intent_evaluator,
        market_intelligence_evaluator_fn=fake_market_intelligence_evaluator,
        run_date="2026-08-16",
    )

    assert outcome.status == "success"
    assert outcome.updated_opportunities_count == 1
    assert outcome.watch_learn_count == 1

    # Verify persistence has refreshed snapshot
    loaded = store.load_all_opportunities()
    assert len(loaded) == 1
    reloaded_opp = loaded[0]
    assert reloaded_opp.opportunity_id == "opp_td_wl_01"
    assert reloaded_opp.market_intelligence is not None
    assert reloaded_opp.market_intelligence.brief == "Fresh 2026 AAA TD Pipeline Brief"
    assert reloaded_opp.market_intelligence.budget_compensation == "80,000 RMB"
    assert reloaded_opp.market_intelligence.requested_tools_workflow == "Unreal Engine 5.5, Houdini Engine, Python"
    assert reloaded_opp.market_intelligence.brief != "Stale Old Brief 2025"

    # Verify Daily Digest renders updated Opportunity in dedicated WATCH_LEARN section
    report_text = Path(outcome.report_path).read_text(encoding="utf-8")
    assert "## 🔭 WATCH_LEARN / 市场情报观察" in report_text
    assert "Lead Technical Director" in report_text
    assert "- **Brief**：Fresh 2026 AAA TD Pipeline Brief" in report_text
    assert "- **Budget / Compensation**：80,000 RMB" in report_text
    assert "- **Requested Tools / Workflow**：Unreal Engine 5.5, Houdini Engine, Python" in report_text
    assert "Stale Old Brief 2025" not in report_text


def test_same_resolution_retains_market_intelligence_without_re_evaluation(temp_intel_lifecycle_env):
    """
    Validates that 'same' resolution on prior WATCH_LEARN Opportunity:
    1. Retains stored Market Intelligence unchanged.
    2. Does NOT require or invoke evaluator_fn, intent_evaluator_fn, or market_intelligence_evaluator_fn.
    """
    tmp_path, config_dir, data_dir, reports_dir = temp_intel_lifecycle_env

    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text("candidate:\n  age: 30\n  degree: 'master'\n", encoding="utf-8")

    store = OpportunityStore(data_dir)
    dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
    initial_eval = EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-15T08:00:00")
    initial_intel = MarketIntelligence(
        brief="Existing Stable Snapshot",
        deliverables="Rigged Character FBX",
        content_type="3D Character",
        timeline_volume="1 month",
        revision_quality_rules="2 rounds",
        requested_tools_workflow="Maya, ZBrush",
        budget_compensation="40k RMB",
        use_case="Character Asset",
    )
    existing_opp = Opportunity(
        opportunity_id="opp_char_01",
        canonical_job_title="Senior Character Artist",
        organization="Game Studio Alpha",
        location="City A",
        track="game_3d_production",
        official_url="https://example.com/alpha/01",
        lifecycle_status="active",
        observations=[],
        latest_evaluation=initial_eval,
        created_at="2026-08-15T08:00:00",
        updated_at="2026-08-15T08:00:00",
        opportunity_intent="WATCH_LEARN",
        intent_rationale="Benchmark rate",
        market_intelligence=initial_intel,
    )
    store.save_opportunities([existing_opp])

    duplicate_obs = SourceObservation(
        observation_id="obs_dup_01",
        announcement_id="ann_dup_01",
        source_id="aggregator",
        source_name="Aggregator",
        announcement_title="Senior Character Artist Repost",
        job_title="Senior Character Artist",
        organization="Game Studio Alpha",
        location="City A",
        track="game_3d_production",
        official_url="https://example.com/repost/01",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={},
    )

    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )

    def fake_entity_resolver(obs, candidates):
        return EntityResolutionDecision(
            resolution="same",
            target_opportunity_id="opp_char_01",
            rationale="Duplicate cross-channel post for same role",
        )

    # Pass None for all semantic evaluators to strictly prove they are not required on 'same'
    outcome = orchestrator.run(
        observations=[duplicate_obs],
        entity_resolver_fn=fake_entity_resolver,
        evaluator_fn=None,
        intent_evaluator_fn=None,
        market_intelligence_evaluator_fn=None,
        run_date="2026-08-16",
    )

    assert outcome.status == "success"
    assert outcome.new_opportunities_count == 0
    assert outcome.updated_opportunities_count == 0

    # Stored intelligence remains intact
    loaded = store.load_all_opportunities()
    assert len(loaded) == 1
    assert loaded[0].opportunity_id == "opp_char_01"
    assert loaded[0].market_intelligence == initial_intel
    assert loaded[0].market_intelligence.brief == "Existing Stable Snapshot"
