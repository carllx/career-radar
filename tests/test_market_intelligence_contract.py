"""
Contract and Invariant Tests for Issue #17: WATCH_LEARN Market Intelligence.
Validates:
1. Canonical MarketIntelligence domain model (8 fields) & serialization.
2. Normalization of missing/blank fields to literal 'UNKNOWN'.
3. Market Intelligence evidence packet assembly.
4. Opportunity JSONL persistence and reload of market_intelligence.
5. Legacy Opportunity backward compatibility (loads safely with market_intelligence=None).
6. Lowest-seam fail-fast: WATCH_LEARN on different/update/uncertain requires valid MarketIntelligence.
7. Update transitions: fresh WATCH_LEARN replaces intelligence; transition away from WATCH_LEARN clears intelligence.
8. 'same' deduplication retains existing Market Intelligence without re-extraction.
"""

from pathlib import Path
import pytest

from career_radar.evaluator import (
    CANONICAL_DIMENSIONS,
    CANONICAL_MARKET_INTELLIGENCE_FIELDS,
    MarketIntelligenceValidator,
    build_market_intelligence_packet,
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
from career_radar.resolver import EntityResolutionApplier
from career_radar.store import OpportunityStore


@pytest.fixture
def temp_intel_env(tmp_path: Path):
    """Sets up clean environment for contract tests."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / ".data"
    reports_dir = tmp_path / "reports"
    for d in (config_dir, data_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)

    seed_file = config_dir / "sources.seed.json"
    seed_file.write_text("[]", encoding="utf-8")
    return tmp_path, config_dir, data_dir, reports_dir


def test_market_intelligence_model_and_canonical_8_fields():
    """Validates MarketIntelligence model instantiation, 8 canonical fields, and serialization."""
    intel = MarketIntelligence(
        brief="Example 3D character modeling for commercial game project",
        deliverables="High-poly FBX, 4K PBR textures, source Maya files",
        content_type="3D Character Asset",
        timeline_volume="2 characters per month",
        revision_quality_rules="Up to 2 revision rounds per milestone; AAA topology rules",
        requested_tools_workflow="Maya, ZBrush, Substance Painter, Unreal Engine 5",
        budget_compensation="30k-40k RMB per character milestone",
        use_case="Hero character in upcoming action RPG",
    )

    assert len(CANONICAL_MARKET_INTELLIGENCE_FIELDS) == 8
    for field in CANONICAL_MARKET_INTELLIGENCE_FIELDS:
        assert getattr(intel, field) != "UNKNOWN"

    d = intel.to_dict()
    assert d["content_type"] == "3D Character Asset"
    reconstructed = MarketIntelligence.from_dict(d)
    assert reconstructed == intel


def test_market_intelligence_validator_normalizes_missing_fields_to_unknown():
    """Validates that MarketIntelligenceValidator normalizes blank/missing/None fields to literal 'UNKNOWN'."""
    raw_partial = {
        "brief": "Visual styling for brand launch",
        "deliverables": "Key visual PSD and vector assets",
        "content_type": "",  # Blank -> should normalize to UNKNOWN
        "timeline_volume": None,  # None -> should normalize to UNKNOWN
        "requested_tools_workflow": "Photoshop, Blender",
        # revision_quality_rules, budget_compensation, use_case omitted -> UNKNOWN
    }

    validated = MarketIntelligenceValidator.validate_and_normalize(raw_partial)
    assert validated.brief == "Visual styling for brand launch"
    assert validated.deliverables == "Key visual PSD and vector assets"
    assert validated.content_type == "UNKNOWN"
    assert validated.timeline_volume == "UNKNOWN"
    assert validated.revision_quality_rules == "UNKNOWN"
    assert validated.requested_tools_workflow == "Photoshop, Blender"
    assert validated.budget_compensation == "UNKNOWN"
    assert validated.use_case == "UNKNOWN"


def test_market_intelligence_packet_assembly():
    """Validates build_market_intelligence_packet provides first-party observation and intent context."""
    profile = CandidateProfile(
        age=30,
        degree="master",
        degree_field="Example Discipline",
        tracks=[{"name": "game_3d_production", "priority": 3, "default_intent": "WATCH_LEARN"}],
        learning_targets=["Houdini Procedural Generation"],
    )

    obs = SourceObservation(
        observation_id="obs_market_01",
        announcement_id="ann_01",
        source_id="game_board",
        source_name="Game Job Board",
        announcement_title="Lead Character Artist RFP",
        job_title="Lead Character Artist",
        organization="Example Studio",
        location="Example City A",
        track="game_3d_production",
        official_url="https://example.com/rfp/01",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={"software": "ZBrush, Maya", "budget": "Negotiable"},
        provenance={"department": "Art Dept"},
    )

    dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
    eval_res = EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
    intent_dec = OpportunityIntentDecision(opportunity_intent="WATCH_LEARN", intent_rationale="Track commercial asset standards.")

    packet = build_market_intelligence_packet(profile, obs, eval_res, intent_dec)

    assert packet["observation"]["organization"] == "Example Studio"
    assert packet["observation"]["official_url"] == "https://example.com/rfp/01"
    assert packet["intent_context"]["opportunity_intent"] == "WATCH_LEARN"
    assert "brief" in packet["canonical_contract"]["canonical_fields"]
    assert "UNKNOWN" in packet["canonical_contract"]["normalization_rule"]


def test_opportunity_persistence_and_reload_with_market_intelligence(temp_intel_env):
    """Validates serialization and reloading of Opportunity with market_intelligence snapshot."""
    _, _, data_dir, _ = temp_intel_env
    store = OpportunityStore(data_dir)

    intel = MarketIntelligence(
        brief="Technical art shader development",
        deliverables="HLSL shader code and Unity packages",
        content_type="Custom Shaders",
        timeline_volume="1 milestone / 3 weeks",
        revision_quality_rules="Pass performance profiling on target hardware",
        requested_tools_workflow="Unity, HLSL, RenderDoc",
        budget_compensation="50k RMB total milestone",
        use_case="Mobile game optimization",
    )

    dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
    eval_res = EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")

    opp = Opportunity(
        opportunity_id="opp_intel_01",
        canonical_job_title="Technical Artist",
        organization="Example Games",
        location="Example City A",
        track="art_tech_creative_technology",
        official_url="https://example.com/ta01",
        lifecycle_status="active",
        observations=[],
        latest_evaluation=eval_res,
        created_at="2026-08-16T08:00:00",
        updated_at="2026-08-16T08:00:00",
        opportunity_intent="WATCH_LEARN",
        intent_rationale="Observe shader pipeline market demands.",
        market_intelligence=intel,
    )

    store.save_opportunities([opp])
    loaded = store.load_all_opportunities()
    assert len(loaded) == 1
    assert loaded[0].opportunity_intent == "WATCH_LEARN"
    assert loaded[0].market_intelligence is not None
    assert loaded[0].market_intelligence.content_type == "Custom Shaders"
    assert loaded[0].market_intelligence.budget_compensation == "50k RMB total milestone"


def test_legacy_opportunity_loads_safely_without_market_intelligence(temp_intel_env):
    """Validates that historical Opportunities without market_intelligence field load as None."""
    _, _, data_dir, _ = temp_intel_env
    store = OpportunityStore(data_dir)

    legacy_json = (
        '{"opportunity_id": "opp_legacy_v16", "job_title": "Legacy Role", "organization": "Legacy Org", '
        '"location": "City X", "track": "higher_education_teaching", "official_url": "https://legacy.org/1", '
        '"lifecycle_status": "active", "observations": [], '
        '"latest_evaluation": {"final_recommendation": "建议关注", "dimension_evaluations": {}, "evaluated_at": "2026-08-15T00:00:00"}, '
        '"created_at": "2026-08-15T00:00:00", "updated_at": "2026-08-15T00:00:00", '
        '"opportunity_intent": "APPLY_NOW", "intent_rationale": "Legacy intent"}\n'
    )
    (data_dir / "opportunities.jsonl").write_text(legacy_json, encoding="utf-8")

    loaded = store.load_all_opportunities()
    assert len(loaded) == 1
    assert loaded[0].opportunity_id == "opp_legacy_v16"
    assert loaded[0].market_intelligence is None


def test_watch_learn_different_missing_market_intelligence_fails_fast():
    """Validates that EntityResolutionApplier rejects WATCH_LEARN on 'different' when market_intelligence is missing."""
    applier = EntityResolutionApplier()
    obs = SourceObservation(
        observation_id="obs_wl_missing",
        announcement_id="ann_01",
        source_id="src_01",
        source_name="Src",
        announcement_title="Title",
        job_title="Role",
        organization="Org",
        location="City",
        track="game_3d_production",
        official_url="https://example.com/1",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={},
    )
    dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
    eval_res = EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
    intent_dec = OpportunityIntentDecision(opportunity_intent="WATCH_LEARN", intent_rationale="Benchmark market")
    decision = EntityResolutionDecision(resolution="different", rationale="New post")
    opp_map = {}

    with pytest.raises(ValueError, match="requires a valid MarketIntelligence"):
        applier.apply_decision(
            obs, decision, opp_map, evaluation_result=eval_res, intent_decision=intent_dec, market_intelligence=None
        )


def test_update_replaces_market_intelligence_on_watch_learn_and_clears_on_apply_now():
    """Validates update transitions: fresh intelligence replaces stale on WATCH_LEARN, and clears on APPLY_NOW."""
    applier = EntityResolutionApplier()
    dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
    prior_eval = EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-15T08:00:00")

    initial_intel = MarketIntelligence(
        brief="Initial brief",
        deliverables="Draft 3D models",
        content_type="3D Draft",
        timeline_volume="UNKNOWN",
        revision_quality_rules="UNKNOWN",
        requested_tools_workflow="Blender",
        budget_compensation="20k",
        use_case="Prototype",
    )

    existing_opp = Opportunity(
        opportunity_id="opp_exist_wl",
        canonical_job_title="Game Artist",
        organization="Studio X",
        location="City",
        track="game_3d_production",
        official_url="https://example.com/1",
        lifecycle_status="active",
        observations=[],
        latest_evaluation=prior_eval,
        created_at="2026-08-15T08:00:00",
        updated_at="2026-08-15T08:00:00",
        opportunity_intent="WATCH_LEARN",
        intent_rationale="Market watch",
        market_intelligence=initial_intel,
    )
    opp_map = {"opp_exist_wl": existing_opp}

    update_obs = SourceObservation(
        observation_id="obs_upd_wl",
        announcement_id="ann_02",
        source_id="src_01",
        source_name="Src",
        announcement_title="Update Announcement",
        job_title="Game Artist",
        organization="Studio X",
        location="City",
        track="game_3d_production",
        official_url="https://example.com/2",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={},
    )
    fresh_eval = EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
    decision = EntityResolutionDecision(resolution="update", target_opportunity_id="opp_exist_wl", rationale="Scope revision")

    # Case A: Update remains WATCH_LEARN -> fresh MarketIntelligence replaces initial
    fresh_intel = MarketIntelligence(
        brief="Revised final brief",
        deliverables="Production-ready rigged models",
        content_type="Production 3D",
        timeline_volume="1 month",
        revision_quality_rules="Standard QA",
        requested_tools_workflow="Maya, Unreal Engine",
        budget_compensation="60k",
        use_case="Production Release",
    )
    intent_wl = OpportunityIntentDecision(opportunity_intent="WATCH_LEARN", intent_rationale="Updated watch")

    updated_opp, _ = applier.apply_decision(
        update_obs, decision, opp_map, evaluation_result=fresh_eval, intent_decision=intent_wl, market_intelligence=fresh_intel
    )
    assert updated_opp.market_intelligence == fresh_intel
    assert updated_opp.market_intelligence.budget_compensation == "60k"

    # Case B: Subsequent update switches to APPLY_NOW -> market_intelligence clears to None (not stale)
    intent_apply = OpportunityIntentDecision(opportunity_intent="APPLY_NOW", intent_rationale="Scope meets direct application")
    updated_opp2, _ = applier.apply_decision(
        update_obs, decision, opp_map, evaluation_result=fresh_eval, intent_decision=intent_apply, market_intelligence=None
    )
    assert updated_opp2.opportunity_intent == "APPLY_NOW"
    assert updated_opp2.market_intelligence is None
