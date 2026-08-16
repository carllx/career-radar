"""
Contract and Invariant Tests for Issue #16: Opportunity Intent.
Validates:
1. Canonical Opportunity Intent 3-state model (APPLY_NOW, CONDITIONAL, WATCH_LEARN) & serialization.
2. Intent rationale non-empty and non-whitespace validation.
3. Intent packet evidence delivery (including Profile v1 string tracks).
4. Opportunity store serialization & reload preservation of intent and rationale.
5. Legacy Opportunity compatibility (None intent on historical records loads safely).
6. Lowest seam fail-fast: different/update/uncertain require OpportunityIntentDecision before persistence.
"""

from pathlib import Path
import pytest

from career_radar.evaluator import (
    CANONICAL_DIMENSIONS,
    IntentValidator,
    build_intent_packet,
)
from career_radar.models import (
    CandidateProfile,
    DimensionEvaluation,
    EntityResolutionDecision,
    EvaluationResult,
    Opportunity,
    OpportunityIntentDecision,
    SourceObservation,
)
from career_radar.resolver import EntityResolutionApplier
from career_radar.store import OpportunityStore


@pytest.fixture
def temp_intent_env(tmp_path: Path):
    """Sets up clean environment for contract tests."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / ".data"
    reports_dir = tmp_path / "reports"
    for d in (config_dir, data_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)

    seed_file = config_dir / "sources.seed.json"
    seed_file.write_text("[]", encoding="utf-8")
    return tmp_path, config_dir, data_dir, reports_dir


def test_opportunity_intent_decision_model_and_validator():
    """Validates OpportunityIntentDecision schema, serialization, and canonical states."""
    decision = OpportunityIntentDecision(
        opportunity_intent="APPLY_NOW",
        intent_rationale="High compensation and strong creative autonomy match candidate preference.",
    )
    assert decision.opportunity_intent == "APPLY_NOW"
    assert "High compensation" in decision.intent_rationale

    # Validation succeeds
    validated = IntentValidator.validate(decision)
    assert validated.opportunity_intent == "APPLY_NOW"

    # Serialization roundtrip
    d_dict = decision.to_dict()
    assert d_dict["opportunity_intent"] == "APPLY_NOW"
    reconstructed = OpportunityIntentDecision.from_dict(d_dict)
    assert reconstructed.opportunity_intent == "APPLY_NOW"
    assert reconstructed.intent_rationale == decision.intent_rationale

    # Invalid state fails validation
    invalid = OpportunityIntentDecision(opportunity_intent="INVALID_STATE", intent_rationale="Valid rationale")
    with pytest.raises(ValueError, match="Invalid opportunity intent"):
        IntentValidator.validate(invalid)


def test_intent_rationale_blank_or_whitespace_rejection():
    """Validates that IntentValidator rejects empty or whitespace-only rationale."""
    with pytest.raises(ValueError, match="Missing or blank intent_rationale"):
        IntentValidator.validate(OpportunityIntentDecision(opportunity_intent="APPLY_NOW", intent_rationale=""))

    with pytest.raises(ValueError, match="Missing or blank intent_rationale"):
        IntentValidator.validate(OpportunityIntentDecision(opportunity_intent="APPLY_NOW", intent_rationale="   \t\n  "))


def test_intent_evidence_packet_assembly():
    """Validates that build_intent_packet exposes both candidate preferences and opportunity/eligibility context."""
    profile = CandidateProfile(
        age=30,
        degree="master",
        degree_field="Example Discipline",
        tracks=[
            {
                "name": "game_3d_production",
                "priority": 3,
                "default_intent": "CONDITIONAL",
                "notes": "Game 3D track conditional on terms",
            }
        ],
        benefit_preferences={"stability": "strong", "time_autonomy": "strong"},
        compensation_preferences={"evaluation_mode": "holistic_tradeoff"},
        regions={"p1": ["Example City A"]},
    )

    obs = SourceObservation(
        observation_id="obs_game_001",
        announcement_id="ann_game_001",
        source_id="example_studio_source",
        source_name="Example Studio HR",
        announcement_title="Lead 3D Role",
        job_title="Lead 3D Artist",
        organization="Example Studio",
        location="Example City A",
        track="game_3d_production",
        official_url="https://example.com/jobs/game01",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={"compensation": "High", "flexibility": "Remote allowed"},
    )

    dim_evals = {
        dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="Matches")
        for dim in CANONICAL_DIMENSIONS
    }
    eval_res = EvaluationResult(
        final_recommendation="建议关注",
        dimension_evaluations=dim_evals,
        evaluated_at="2026-08-16T08:00:00",
    )

    packet = build_intent_packet(profile, obs, eval_res)
    assert packet["candidate_evidence"]["matching_track"]["default_intent"] == "CONDITIONAL"
    assert packet["candidate_evidence"]["benefit_preferences"]["time_autonomy"] == "strong"
    assert packet["opportunity_evidence"]["organization"] == "Example Studio"
    assert packet["eligibility_context"]["final_recommendation"] == "建议关注"
    assert "valid_intents" in packet["canonical_contract"]


def test_intent_evidence_packet_legacy_string_tracks():
    """Validates that build_intent_packet cleanly supports Profile v1 string tracks without inventing default_intent."""
    profile = CandidateProfile(
        age=30,
        degree="master",
        degree_field="Example Discipline",
        tracks=["higher_education_teaching", "vocational_education"],
    )

    obs = SourceObservation(
        observation_id="obs_v1_str",
        announcement_id="ann_v1_str",
        source_id="uni_hr",
        source_name="Example University HR",
        announcement_title="Lecturer Post",
        job_title="Lecturer",
        organization="Example University",
        location="Example City A",
        track="higher_education_teaching",
        official_url="https://example.edu.cn/jobs/01",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={},
    )

    dim_evals = {
        dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="Matches")
        for dim in CANONICAL_DIMENSIONS
    }
    eval_res = EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")

    packet = build_intent_packet(profile, obs, eval_res)
    assert packet["candidate_evidence"]["matching_track"]["name"] == "higher_education_teaching"
    assert packet["candidate_evidence"]["track_priority"] is None
    assert packet["candidate_evidence"]["track_default_intent"] is None


def test_opportunity_persistence_and_reload_with_intent(temp_intent_env):
    """Proves Opportunity serialization and reload preserve opportunity_intent and intent_rationale."""
    _, _, data_dir, _ = temp_intent_env
    store = OpportunityStore(data_dir)

    dim_evals = {
        dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="Matches")
        for dim in CANONICAL_DIMENSIONS
    }
    eval_res = EvaluationResult(
        final_recommendation="建议关注",
        dimension_evaluations=dim_evals,
        evaluated_at="2026-08-16T08:00:00",
    )

    obs = SourceObservation(
        observation_id="obs_test_01",
        announcement_id="ann_test_01",
        source_id="src_01",
        source_name="Src 01",
        announcement_title="Faculty Role",
        job_title="Lecturer",
        organization="Example Univ",
        location="Example City A",
        track="higher_education_teaching",
        official_url="https://example.edu/01",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={},
    )

    opp = Opportunity(
        opportunity_id="opp_01",
        canonical_job_title="Lecturer",
        organization="Example Univ",
        location="Example City A",
        track="higher_education_teaching",
        official_url="https://example.edu/01",
        lifecycle_status="active",
        observations=[obs],
        latest_evaluation=eval_res,
        created_at="2026-08-16T08:00:00",
        updated_at="2026-08-16T08:00:00",
        opportunity_intent="APPLY_NOW",
        intent_rationale="Teaching track with stable employment meets primary career anchor.",
    )

    store.save_opportunities([opp])
    loaded = store.load_all_opportunities()
    assert len(loaded) == 1
    assert loaded[0].opportunity_id == "opp_01"
    assert loaded[0].opportunity_intent == "APPLY_NOW"
    assert "stable employment" in (loaded[0].intent_rationale or "")


def test_legacy_opportunity_compatibility_loading(temp_intent_env):
    """Proves legacy opportunities without intent fields load safely with None."""
    _, _, data_dir, _ = temp_intent_env
    store = OpportunityStore(data_dir)

    # Write legacy jsonl line without opportunity_intent
    legacy_json = (
        '{"opportunity_id": "opp_legacy_01", "job_title": "Legacy Role", "organization": "Legacy Org", '
        '"location": "City X", "track": "higher_education_teaching", "official_url": "https://legacy.org/1", '
        '"lifecycle_status": "active", "observations": [], '
        '"latest_evaluation": {"final_recommendation": "建议关注", "dimension_evaluations": {}, "evaluated_at": "2026-08-15T00:00:00"}, '
        '"created_at": "2026-08-15T00:00:00", "updated_at": "2026-08-15T00:00:00"}\n'
    )
    (data_dir / "opportunities.jsonl").write_text(legacy_json, encoding="utf-8")

    loaded = store.load_all_opportunities()
    assert len(loaded) == 1
    assert loaded[0].opportunity_id == "opp_legacy_01"
    assert loaded[0].opportunity_intent is None
    assert loaded[0].intent_rationale is None


def test_different_missing_intent_fails_fast_at_applier():
    """Validates that EntityResolutionApplier rejects 'different' resolution when intent is missing."""
    applier = EntityResolutionApplier()
    obs = SourceObservation(
        observation_id="obs_diff_no_intent",
        announcement_id="ann_01",
        source_id="src_01",
        source_name="Src",
        announcement_title="Title",
        job_title="Role",
        organization="Org",
        location="City",
        track="higher_education_teaching",
        official_url="https://example.com/1",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={},
    )
    dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
    eval_res = EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
    decision = EntityResolutionDecision(resolution="different", rationale="New post")
    opp_map = {}

    with pytest.raises(ValueError, match="requires a valid OpportunityIntentDecision"):
        applier.apply_decision(obs, decision, opp_map, evaluation_result=eval_res, intent_decision=None)


def test_update_missing_intent_fails_fast_at_applier():
    """Validates that EntityResolutionApplier rejects 'update' resolution when intent is missing."""
    applier = EntityResolutionApplier()
    dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
    prior_eval = EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-15T08:00:00")
    existing_opp = Opportunity(
        opportunity_id="opp_exist_01",
        canonical_job_title="Role",
        organization="Org",
        location="City",
        track="higher_education_teaching",
        official_url="https://example.com/1",
        lifecycle_status="active",
        observations=[],
        latest_evaluation=prior_eval,
        created_at="2026-08-15T08:00:00",
        updated_at="2026-08-15T08:00:00",
        opportunity_intent="CONDITIONAL",
        intent_rationale="Initial intent",
    )
    opp_map = {"opp_exist_01": existing_opp}

    obs = SourceObservation(
        observation_id="obs_update_01",
        announcement_id="ann_02",
        source_id="src_01",
        source_name="Src",
        announcement_title="Title Update",
        job_title="Role",
        organization="Org",
        location="City",
        track="higher_education_teaching",
        official_url="https://example.com/2",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={},
    )
    fresh_eval = EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
    decision = EntityResolutionDecision(resolution="update", target_opportunity_id="opp_exist_01", rationale="Extension")

    with pytest.raises(ValueError, match="requires a valid re-evaluated OpportunityIntentDecision"):
        applier.apply_decision(obs, decision, opp_map, evaluation_result=fresh_eval, intent_decision=None)


def test_uncertain_missing_intent_fails_fast_at_applier():
    """Validates that EntityResolutionApplier rejects 'uncertain' resolution when intent is missing."""
    applier = EntityResolutionApplier()
    dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
    prior_eval = EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-15T08:00:00")
    existing_opp = Opportunity(
        opportunity_id="opp_exist_02",
        canonical_job_title="Role",
        organization="Org",
        location="City",
        track="higher_education_teaching",
        official_url="https://example.com/1",
        lifecycle_status="active",
        observations=[],
        latest_evaluation=prior_eval,
        created_at="2026-08-15T08:00:00",
        updated_at="2026-08-15T08:00:00",
        opportunity_intent="CONDITIONAL",
        intent_rationale="Initial intent",
    )
    opp_map = {"opp_exist_02": existing_opp}

    obs = SourceObservation(
        observation_id="obs_unc_01",
        announcement_id="ann_03",
        source_id="src_02",
        source_name="Src2",
        announcement_title="Ambiguous Title",
        job_title="Role",
        organization="Org",
        location="City",
        track="higher_education_teaching",
        official_url="https://example.com/3",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={},
    )
    fresh_eval = EvaluationResult(final_recommendation="需要人工确认", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
    decision = EntityResolutionDecision(resolution="uncertain", target_opportunity_id="opp_exist_02", rationale="Ambiguous entity match")

    with pytest.raises(ValueError, match="requires a valid OpportunityIntentDecision"):
        applier.apply_decision(obs, decision, opp_map, evaluation_result=fresh_eval, intent_decision=None)
