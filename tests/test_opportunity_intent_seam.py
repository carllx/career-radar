"""
Highest Seam and Contract Tests for Issue #16: Opportunity Intent.
Validates:
1. Canonical Opportunity Intent 3-state model (APPLY_NOW, CONDITIONAL, WATCH_LEARN).
2. Intent packet evidence delivery to the Agent semantic boundary (including Profile v1 string tracks).
3. Intent rationale non-empty/whitespace validation.
4. Track default_intent is only a prior (Agent may upgrade/downgrade based on opportunity conditions).
5. Opportunity Intent and Eligibility orthogonality (FAIL remains FAIL regardless of attractive intent).
6. Opportunity store serialization & reload preservation of intent and rationale.
7. Legacy Opportunity compatibility (None intent on historical records loads safely).
8. Lowest seam fail-fast: different/update/uncertain require OpportunityIntentDecision before persistence.
9. Orchestrator & run_radar_pipeline fail-fast when intent_evaluator_fn is missing for semantic paths.
10. Update semantic flow: re-evaluation changes intent, preserves new rationale, and renders in Daily Digest.
11. "same" resolution retains existing Opportunity intent without requiring re-evaluation.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest
import yaml

from career_radar.evaluator import (
    CANONICAL_DIMENSIONS,
    VALID_EVIDENCE_STATES,
    VALID_OPPORTUNITY_INTENTS,
    VALID_RECOMMENDATIONS,
    EvaluationValidator,
    IntentValidator,
    build_evaluation_packet,
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
from career_radar.orchestrator import RadarOrchestrator, RadarRunOutcome
from career_radar.resolver import EntityResolutionApplier
from career_radar.runner import (
    IncrementalResolutionSession,
    finalize_evaluation_run,
    finalize_incremental_run,
    run_radar_pipeline,
)
from career_radar.store import OpportunityStore


@pytest.fixture
def temp_intent_env(tmp_path: Path):
    """Sets up clean environment for Issue #16 seam tests."""
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


def test_run_radar_pipeline_and_orchestrator_missing_intent_evaluator_fails_fast(temp_intent_env):
    """Validates that run_radar_pipeline and RadarOrchestrator fail fast when intent_evaluator_fn is omitted for semantic flows."""
    tmp_path, config_dir, data_dir, reports_dir = temp_intent_env
    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text("candidate:\n  age: 30\n  degree: 'master'\n", encoding="utf-8")

    obs = SourceObservation(
        observation_id="obs_guard_01",
        announcement_id="ann_guard_01",
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

    def dummy_evaluator(prof: CandidateProfile, o: SourceObservation) -> EvaluationResult:
        dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
        return EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")

    # 1. run_radar_pipeline missing intent_evaluator_fn
    with pytest.raises(ValueError, match="Missing required intent_evaluator_fn"):
        run_radar_pipeline(
            profile_path=profile_path,
            observations_source=[obs],
            evaluator_fn=dummy_evaluator,
            intent_evaluator_fn=None,
            data_dir=data_dir,
            reports_dir=reports_dir,
        )

    # 2. RadarOrchestrator missing intent_evaluator_fn
    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )
    with pytest.raises(ValueError, match="Missing required intent_evaluator_fn"):
        orchestrator.run(
            observations=[obs],
            evaluator_fn=dummy_evaluator,
            intent_evaluator_fn=None,
            run_date="2026-08-16",
        )


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


def test_update_semantic_flow_updates_intent_and_renders_in_digest(temp_intent_env):
    """
    Validates update semantic flow:
    1. Prior Opportunity had CONDITIONAL intent.
    2. Update observation arrives -> Agent re-evaluates and upgrades intent to APPLY_NOW.
    3. Persistence preserves new intent and new rationale.
    4. Daily Digest '重点岗位动态变更' section visibly renders latest recommendation, intent, and rationale.
    """
    tmp_path, config_dir, data_dir, reports_dir = temp_intent_env
    store = OpportunityStore(data_dir)

    dim_evals = {dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="OK") for dim in CANONICAL_DIMENSIONS}
    initial_eval = EvaluationResult(final_recommendation="需要人工确认", dimension_evaluations=dim_evals, evaluated_at="2026-08-15T08:00:00")

    prior_opp = Opportunity(
        opportunity_id="opp_update_test_01",
        canonical_job_title="Creative Technologist",
        organization="Example Tech Institute",
        location="Example City A",
        track="art_tech_creative_technology",
        official_url="https://example.org/jobs/ct01",
        lifecycle_status="active",
        observations=[],
        latest_evaluation=initial_eval,
        created_at="2026-08-15T08:00:00",
        updated_at="2026-08-15T08:00:00",
        opportunity_intent="CONDITIONAL",
        intent_rationale="Prior salary uncertain, conditional on budget release.",
    )
    store.save_opportunities([prior_opp])

    profile_yaml = "candidate:\n  age: 30\n  degree: 'master'\n  degree_field: 'Art Tech'\n"
    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text(profile_yaml, encoding="utf-8")

    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )

    update_obs = SourceObservation(
        observation_id="obs_ct_update_01",
        announcement_id="ann_ct_update_01",
        source_id="inst_hr",
        source_name="Institute HR",
        announcement_title="CT Role Budget Supplementary Announcement",
        job_title="Creative Technologist",
        organization="Example Tech Institute",
        location="Example City A",
        track="art_tech_creative_technology",
        official_url="https://example.org/jobs/ct01_supp",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={"budget": "Confirmed high tier", "schedule": "Flexible"},
    )

    def entity_resolver(obs: SourceObservation, candidates: List[Opportunity]) -> EntityResolutionDecision:
        return EntityResolutionDecision(
            resolution="update",
            target_opportunity_id="opp_update_test_01",
            diff_summary="补充薪酬预算与弹性工作细节",
            rationale="Official supplementary notice",
        )

    def agent_evaluator(prof: CandidateProfile, obs: SourceObservation) -> EvaluationResult:
        return EvaluationValidator.validate_and_aggregate(
            EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
        )

    def agent_intent_evaluator(prof: CandidateProfile, obs: SourceObservation, ev: EvaluationResult) -> OpportunityIntentDecision:
        return OpportunityIntentDecision(
            opportunity_intent="APPLY_NOW",
            intent_rationale="补充公告确认了优渥薪酬预算并允许弹性排期，消除了此前顾虑，升级为即刻行动。",
        )

    outcome = orchestrator.run(
        observations=[update_obs],
        entity_resolver_fn=entity_resolver,
        evaluator_fn=agent_evaluator,
        intent_evaluator_fn=agent_intent_evaluator,
        run_date="2026-08-16",
    )

    assert outcome.status == "success"
    assert outcome.updated_opportunities_count == 1
    assert outcome.apply_now_count == 1

    # Reload store and verify persistence
    reloaded = store.load_all_opportunities()
    assert len(reloaded) == 1
    assert reloaded[0].opportunity_intent == "APPLY_NOW"
    assert "消除了此前顾虑" in (reloaded[0].intent_rationale or "")

    # Check Daily Digest update block
    report_text = Path(outcome.report_path).read_text(encoding="utf-8")
    assert "## 🔄 重点岗位动态变更" in report_text
    assert "Creative Technologist" in report_text
    assert "- **变更摘要**：补充薪酬预算与弹性工作细节" in report_text
    assert "- **最新资格结论**：`建议关注`" in report_text
    assert "- **最新行动意图**：`APPLY_NOW / 即刻行动`" in report_text
    assert "- **意图理由**：补充公告确认了优渥薪酬预算并允许弹性排期，消除了此前顾虑，升级为即刻行动。" in report_text


def test_full_radar_orchestrator_run_with_intent_upgrade_and_orthogonality(temp_intent_env):
    """
    End-to-end highest test seam verifying:
    1. Track default CONDITIONAL upgraded by Agent to APPLY_NOW with rationale based on conditions.
    2. Eligibility FAIL remains FAIL even with attractive intent.
    3. Daily Digest renders Eligibility and Intent distinctly without conflation.
    4. RadarRunOutcome surfaces intent counts.
    """
    tmp_path, config_dir, data_dir, reports_dir = temp_intent_env

    profile_yaml = """
candidate:
  date_of_birth: "1995-05-20"
  age: 31
  degree: "master"
  degree_field: "Example Discipline"
  tracks:
    - name: "game_3d_production"
      priority: 3
      default_intent: "CONDITIONAL"
    - name: "higher_education_teaching"
      priority: 1
      default_intent: "APPLY_NOW"
  benefit_preferences:
    time_autonomy: "strong"
  regions:
    p1: ["Example City A"]
"""
    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text(profile_yaml, encoding="utf-8")

    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )

    # Obs 1: Game track role with excellent autonomy -> Agent upgrades CONDITIONAL to APPLY_NOW
    obs_game = SourceObservation(
        observation_id="obs_game_01",
        announcement_id="ann_game_01",
        source_id="game_studio",
        source_name="Example Game Studio",
        announcement_title="Lead 3D Role",
        job_title="Principal 3D Artist",
        organization="Creative Game Studio",
        location="Example City A",
        track="game_3d_production",
        official_url="https://example.com/jobs/game_lead",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={"degree": "硕士及以上", "experience": "3年以上"},
    )

    # Obs 2: High priority university role with impossible PhD requirement -> Eligibility FAIL
    obs_phd = SourceObservation(
        observation_id="obs_phd_01",
        announcement_id="ann_phd_01",
        source_id="top_uni",
        source_name="Public Top University",
        announcement_title="Professor Recruitment",
        job_title="Tenure-Track Professor",
        organization="Public Top University",
        location="Example City A",
        track="higher_education_teaching",
        official_url="https://example.edu.cn/jobs/phd_prof",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={"degree": "必须全日制博士学位"},
    )

    def agent_evaluator(prof: CandidateProfile, obs: SourceObservation) -> EvaluationResult:
        if obs.observation_id == "obs_game_01":
            dim_evals = {
                dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="符合", rationale="满足要求")
                for dim in CANONICAL_DIMENSIONS
            }
            return EvaluationValidator.validate_and_aggregate(
                EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
            )
        else:
            dim_evals = {
                dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="符合", rationale="满足要求")
                for dim in CANONICAL_DIMENSIONS
            }
            # Hard blocker on Education
            dim_evals["Education"] = DimensionEvaluation(
                dimension="Education", state="FAIL", requirement_evidence="必须全日制博士学位", rationale="候选人为硕士学历，未达博士门槛"
            )
            return EvaluationValidator.validate_and_aggregate(
                EvaluationResult(final_recommendation="明显不符合", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
            )

    def agent_intent_evaluator(
        prof: CandidateProfile, obs: SourceObservation, eval_res: EvaluationResult
    ) -> OpportunityIntentDecision:
        if obs.observation_id == "obs_game_01":
            # Dynamic upgrade: track prior is CONDITIONAL, but role has high autonomy and seniority -> APPLY_NOW
            return OpportunityIntentDecision(
                opportunity_intent="APPLY_NOW",
                intent_rationale="尽管所属游戏赛道默认条件关注，但该岗位提供高自主权与创意指导职责，符合当前行动意图，升级为即刻行动。",
            )
        else:
            return OpportunityIntentDecision(
                opportunity_intent="CONDITIONAL",
                intent_rationale="高校教职属于高优先级赛道，但因博士硬门槛不符合，维持条件观测。",
            )

    def entity_resolver(obs: SourceObservation, candidates: List[Opportunity]) -> EntityResolutionDecision:
        return EntityResolutionDecision(resolution="different", rationale="Distinct test positions")

    outcome = orchestrator.run(
        observations=[obs_game, obs_phd],
        entity_resolver_fn=entity_resolver,
        evaluator_fn=agent_evaluator,
        intent_evaluator_fn=agent_intent_evaluator,
        run_date="2026-08-16",
    )

    assert outcome.status == "success"
    assert outcome.new_opportunities_count == 2
    assert outcome.recommended_count == 1
    assert outcome.apply_now_count == 1
    assert outcome.conditional_count == 1
    assert outcome.watch_learn_count == 0

    # Verify daily digest report formatting
    report_text = Path(outcome.report_path).read_text(encoding="utf-8")
    assert "Principal 3D Artist" in report_text
    assert "- **行动意图**：`APPLY_NOW / 即刻行动`" in report_text
    assert "升级为即刻行动" in report_text
    assert "资格建议关注" in report_text or "建议关注" in report_text

    # Reload store and verify persistence
    store = OpportunityStore(data_dir)
    opps = store.load_all_opportunities()
    game_opp = next(o for o in opps if o.canonical_job_title == "Principal 3D Artist")
    assert game_opp.opportunity_intent == "APPLY_NOW"
    assert "升级为即刻行动" in (game_opp.intent_rationale or "")


def test_same_resolution_retains_existing_intent(temp_intent_env):
    """Proves 'same' deduplicated observations retain existing Opportunity intent without requiring re-evaluation."""
    tmp_path, config_dir, data_dir, reports_dir = temp_intent_env

    # Prepopulate prior opportunity with intent
    store = OpportunityStore(data_dir)
    dim_evals = {
        dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="OK", rationale="Matches")
        for dim in CANONICAL_DIMENSIONS
    }
    eval_res = EvaluationResult(
        final_recommendation="建议关注",
        dimension_evaluations=dim_evals,
        evaluated_at="2026-08-15T08:00:00",
    )
    prior_opp = Opportunity(
        opportunity_id="opp_existing_01",
        canonical_job_title="Lecturer Role",
        organization="Example College",
        location="Example City A",
        track="vocational_education",
        official_url="https://example.edu.cn/01",
        lifecycle_status="active",
        observations=[],
        latest_evaluation=eval_res,
        created_at="2026-08-15T08:00:00",
        updated_at="2026-08-15T08:00:00",
        opportunity_intent="APPLY_NOW",
        intent_rationale="Initial confirmed apply intent.",
    )
    store.save_opportunities([prior_opp])

    profile_yaml = "candidate:\n  age: 30\n  degree: 'master'\n  degree_field: 'Art'\n"
    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text(profile_yaml, encoding="utf-8")

    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )

    duplicate_obs = SourceObservation(
        observation_id="obs_dup_01",
        announcement_id="ann_dup_01",
        source_id="src_other",
        source_name="Other Source",
        announcement_title="Cross-posted Lecturer Role",
        job_title="Lecturer Role",
        organization="Example College",
        location="Example City A",
        track="vocational_education",
        official_url="https://other.com/01",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={},
    )

    def entity_resolver(obs: SourceObservation, candidates: List[Opportunity]) -> EntityResolutionDecision:
        return EntityResolutionDecision(
            resolution="same", target_opportunity_id="opp_existing_01", rationale="Cross-post duplicate"
        )

    # No intent_evaluator_fn or evaluator_fn is needed for a 'same'-only run
    outcome = orchestrator.run(
        observations=[duplicate_obs],
        entity_resolver_fn=entity_resolver,
        run_date="2026-08-16",
    )

    assert outcome.deduped_same_count == 1
    reloaded = store.load_all_opportunities()
    assert len(reloaded) == 1
    assert reloaded[0].opportunity_intent == "APPLY_NOW"
    assert reloaded[0].intent_rationale == "Initial confirmed apply intent."
