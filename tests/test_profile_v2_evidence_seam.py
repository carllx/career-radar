"""
Highest Seam and Evidence Contract Tests for Issue #15: Profile v2 Evidence Foundation.
Validates:
1. Profile v1 backward compatibility (loading & full Radar Run).
2. Profile v2 full schema parsing with generic synthetic data (DOB, 3-tier capabilities, 7 tracks, preferences, constraints).
3. Candidate Evidence packet richness reaching the Agent semantic boundary.
4. Learning target evidence separation at the Agent boundary.
5. Age architecture boundary (mechanical calculation with explicit cutoff, no Python semantic cutoff inference).
6. 6/5/3 Canonical Eligibility preservation under Profile v2.
"""

from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest
import yaml

from career_radar.evaluator import (
    CANONICAL_DIMENSIONS,
    VALID_EVIDENCE_STATES,
    VALID_RECOMMENDATIONS,
    EvaluationValidator,
    build_evaluation_packet,
)
from career_radar.models import (
    CandidateProfile,
    DimensionEvaluation,
    EntityResolutionDecision,
    EvaluationResult,
    Opportunity,
    SourceObservation,
    calculate_chronological_age,
)
from career_radar.orchestrator import RadarOrchestrator, RadarRunOutcome
from career_radar.sources import (
    MonitoringFact,
    SourceLifecycleDecision,
    SourceRecord,
    SourceRegistry,
)


@pytest.fixture
def temp_radar_env(tmp_path: Path):
    """Sets up a clean temporary environment with seeds and directories."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / ".data"
    reports_dir = tmp_path / "reports"
    for d in (config_dir, data_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)

    seed_file = config_dir / "sources.seed.json"
    seed_file.write_text("[]", encoding="utf-8")
    return tmp_path, config_dir, data_dir, reports_dir


def test_profile_v1_backward_compatibility_loading_and_full_run(temp_radar_env):
    """Tests that existing Profile v1 YAML loads cleanly with legacy defaults and executes full Radar Run."""
    tmp_path, config_dir, data_dir, reports_dir = temp_radar_env

    # Profile v1 YAML (MVP-1 legacy schema with generic synthetic data)
    v1_yaml = """
candidate:
  age: 30
  degree: "master"
  degree_field: "Example Field"
  teaching_experience_years: 2
  industry_experience_years: 3
  tracks:
    - name: "higher_education_teaching"
      priority: 1
    - name: "vocational_education"
      priority: 2
  regions:
    p1: ["Example City A"]
    p2: ["Example City B"]
  hard_constraints:
    min_degree: "master"
    max_age: 35
"""
    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text(v1_yaml, encoding="utf-8")

    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )
    profile = orchestrator.load_profile()

    # Verify v1 fields loaded correctly
    assert profile.age == 30
    assert profile.degree == "master"
    assert profile.degree_field == "Example Field"
    assert profile.teaching_experience_years == 2
    assert profile.industry_experience_years == 3
    assert profile.track_names() == {"higher_education_teaching", "vocational_education"}
    assert profile.hard_constraints["min_degree"] == "master"

    # Verify v2 optional fields default safely without breaking
    assert profile.date_of_birth is None
    assert profile.proven_capabilities == []
    assert profile.adjacent_capabilities == []
    assert profile.learning_targets == []
    assert profile.benefit_preferences == {}
    assert profile.engagement_preferences == {}
    assert profile.compensation_preferences == {}
    assert profile.availability_constraints == []
    assert profile.unresolved_facts == {}

    # Run full Radar Run with v1 profile
    obs = SourceObservation(
        observation_id="obs_v1_001",
        announcement_id="ann_v1_001",
        source_id="example_source",
        source_name="Example Source Name",
        announcement_title="2026 Example Recruitment",
        job_title="Example Role",
        organization="Example Vocational College",
        location="Example City A",
        track="vocational_education",
        official_url="https://example.edu.cn/jobs/001",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={"education": "硕士研究生及以上", "age": "35周岁以下"},
    )

    def dummy_evaluator(prof: CandidateProfile, o: SourceObservation) -> EvaluationResult:
        packet = build_evaluation_packet(prof, o)
        # Ensure packet receives v1 evidence safely
        assert packet["candidate_evidence"]["age"] == 30
        assert packet["candidate_evidence"]["proven_capabilities"] == []
        dim_evals = {
            dim: DimensionEvaluation(dimension=dim, state="PASS", requirement_evidence="满足条件", rationale="符合")
            for dim in CANONICAL_DIMENSIONS
        }
        return EvaluationValidator.validate_and_aggregate(
            EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
        )

    outcome = orchestrator.run(
        observations=[obs],
        evaluator_fn=dummy_evaluator,
        run_date="2026-08-16",
    )

    assert outcome.status == "success"
    assert outcome.recommended_count == 1
    assert Path(outcome.report_path).exists()


def test_profile_v2_schema_parsing_and_candidate_evidence_richness(temp_radar_env):
    """Tests that Profile v2 YAML loads all rich candidate fields and delivers them into the evaluation packet."""
    tmp_path, config_dir, data_dir, reports_dir = temp_radar_env

    v2_yaml = """
candidate:
  date_of_birth: "1995-05-20"
  age: 31
  degree: "master"
  degree_field: "Example Discipline"
  teaching_experience_years: 3
  industry_experience_years: 4
  proven_capabilities:
    - "Example Core Skill A"
    - "Example Core Skill B"
  adjacent_capabilities:
    - "Example Adjacent Tech C"
    - "Example Adjacent Tech D"
  learning_targets:
    - "Example Learning Target E"
    - "Example Learning Target F"
  tracks:
    - name: "higher_education_teaching"
      priority: 1
      default_intent: "APPLY_NOW"
      notes: "Public & private undergraduate teaching"
    - name: "vocational_education"
      priority: 1
      default_intent: "APPLY_NOW"
    - name: "art_tech_creative_technology"
      priority: 2
      default_intent: "APPLY_NOW"
    - name: "open_cross_disciplinary_discovery"
      priority: 2
      default_intent: "CONDITIONAL"
    - name: "game_3d_production"
      priority: 3
      default_intent: "CONDITIONAL"
    - name: "ai_content_planning"
      priority: 3
      default_intent: "CONDITIONAL"
    - name: "ai_video_market_intelligence"
      priority: 4
      default_intent: "WATCH_LEARN"
  benefit_preferences:
    social_insurance: "strong"
    medical_insurance: "strong"
    stability: "strong"
    time_autonomy: "strong"
  engagement_preferences:
    full_time_teaching: "preferred"
    adjunct_teaching: "acceptable_if_no_conflict"
  compensation_preferences:
    teaching_net_monthly_reference: "EXAMPLE_NET_REFERENCE"
    evaluation_mode: "holistic_tradeoff"
  regions:
    p1: ["Example City A"]
    p2: ["Example City B", "Example City C"]
  availability_constraints:
    - name: "Example Existing Commitment"
      period: "YYYY-MM"
      duration_weeks: "EXAMPLE_WEEKS"
      schedule_details: "UNKNOWN"
      conflict_rule: "DO_NOT_ASSUME_CONFLICT_UNTIL_SCHEDULED"
  unresolved_facts:
    example_disputed_fact: "NEEDS_USER_CONFIRMATION"
  hard_constraints:
    legacy_compatibility_only: true
"""
    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text(v2_yaml, encoding="utf-8")

    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )
    profile = orchestrator.load_profile()

    # Assert Profile v2 fields
    assert profile.date_of_birth == "1995-05-20"
    assert profile.age == 31
    assert "Example Core Skill A" in profile.proven_capabilities
    assert "Example Adjacent Tech C" in profile.adjacent_capabilities
    assert "Example Learning Target E" in profile.learning_targets
    assert len(profile.tracks) == 7
    assert profile.benefit_preferences["stability"] == "strong"
    assert profile.engagement_preferences["full_time_teaching"] == "preferred"
    assert profile.compensation_preferences["evaluation_mode"] == "holistic_tradeoff"
    assert len(profile.availability_constraints) == 1
    assert profile.availability_constraints[0]["conflict_rule"] == "DO_NOT_ASSUME_CONFLICT_UNTIL_SCHEDULED"
    assert profile.unresolved_facts["example_disputed_fact"] == "NEEDS_USER_CONFIRMATION"

    # Build evaluation packet and check delivery
    obs = SourceObservation(
        observation_id="obs_v2_001",
        announcement_id="ann_v2_001",
        source_id="example_dept",
        source_name="Example Department",
        announcement_title="Example Faculty Recruitment",
        job_title="Example Faculty Role",
        organization="Example University",
        location="Example City A",
        track="art_tech_creative_technology",
        official_url="https://example.edu.cn/jobs/art001",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={"skills": "熟练掌握相关专业核心技能与前沿技术"},
    )

    packet = build_evaluation_packet(profile, obs)
    cand_ev = packet["candidate_evidence"]
    assert cand_ev["date_of_birth"] == "1995-05-20"
    assert cand_ev["proven_capabilities"] == ["Example Core Skill A", "Example Core Skill B"]
    assert cand_ev["adjacent_capabilities"] == ["Example Adjacent Tech C", "Example Adjacent Tech D"]
    assert cand_ev["learning_targets"] == ["Example Learning Target E", "Example Learning Target F"]
    assert len(cand_ev["tracks"]) == 7
    assert cand_ev["benefit_preferences"]["time_autonomy"] == "strong"
    assert cand_ev["availability_constraints"][0]["name"] == "Example Existing Commitment"
    assert cand_ev["unresolved_facts"]["example_disputed_fact"] == "NEEDS_USER_CONFIRMATION"


def test_learning_target_evidence_remains_separate_at_agent_boundary():
    """Validates that learning targets are exposed separately as exploratory skills and do not blend into proven capability."""
    profile = CandidateProfile(
        age=30,
        degree="master",
        degree_field="Example Discipline",
        proven_capabilities=["Example Core Skill A"],
        adjacent_capabilities=["Example Adjacent Tech C"],
        learning_targets=["Example Learning Target E"],
    )

    obs = SourceObservation(
        observation_id="obs_synth_001",
        announcement_id="ann_synth_001",
        source_id="example_agency",
        source_name="Example Creative Agency",
        announcement_title="Example Creative Lead",
        job_title="Example Lead",
        organization="Example Studio",
        location="Example City A",
        track="ai_video_market_intelligence",
        official_url="https://example.com/synth001",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={"skills": "必须具备丰富的相关项目落地经验"},
    )

    packet = build_evaluation_packet(profile, obs)
    # The evaluation packet contract explicitly specifies the learning target safety rule
    assert "learning_targets_rule" in packet["canonical_contract"]
    assert packet["candidate_evidence"]["learning_targets"] == ["Example Learning Target E"]
    assert packet["candidate_evidence"]["proven_capabilities"] == ["Example Core Skill A"]
    assert packet["candidate_evidence"]["adjacent_capabilities"] == ["Example Adjacent Tech C"]


def test_chronological_age_calculation_helper():
    """Tests the mechanical chronological age helper with explicit reference dates."""
    dob = "1995-05-20"
    # Case 1: Birthday already occurred in reference year
    ref_after = "2026-08-16"
    assert calculate_chronological_age(dob, ref_after) == 31

    # Case 2: Birthday has not yet occurred in reference year
    ref_before = "2026-04-01"
    assert calculate_chronological_age(dob, ref_before) == 30

    # Case 3: Exactly on birthday
    ref_on = "2026-05-20"
    assert calculate_chronological_age(dob, ref_on) == 31

    # Case 4: Invalid/missing inputs return None safely without throwing
    assert calculate_chronological_age("", "2026-08-16") is None
    assert calculate_chronological_age(dob, "invalid-date") is None
    assert calculate_chronological_age(None, "2026-08-16") is None


def test_profile_v2_full_radar_orchestrator_run(temp_radar_env):
    """End-to-end highest test seam verifying a full Radar Run with Profile v2."""
    tmp_path, config_dir, data_dir, reports_dir = temp_radar_env

    v2_yaml = """
candidate:
  date_of_birth: "1995-05-20"
  age: 31
  degree: "master"
  degree_field: "Example Discipline"
  teaching_experience_years: 3
  industry_experience_years: 4
  proven_capabilities:
    - "Example Core Skill A"
    - "Example Higher Education Teaching"
  adjacent_capabilities:
    - "Example Adjacent Tech C"
  learning_targets:
    - "Example Learning Target E"
  tracks:
    - name: "higher_education_teaching"
      priority: 1
      default_intent: "APPLY_NOW"
  regions:
    p1: ["Example City A"]
"""
    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text(v2_yaml, encoding="utf-8")

    orchestrator = RadarOrchestrator(
        profile_path=profile_path,
        seed_sources_path=config_dir / "sources.seed.json",
        data_dir=data_dir,
        reports_dir=reports_dir,
    )

    obs = SourceObservation(
        observation_id="obs_v2_run_01",
        announcement_id="ann_v2_run_01",
        source_id="example_uni_hr",
        source_name="Example University HR",
        announcement_title="2026 Faculty Recruitment",
        job_title="Example Lecturer Role",
        organization="Example University",
        location="Example City A",
        track="higher_education_teaching",
        official_url="https://example.edu.cn/jobs/teach01",
        observed_at="2026-08-16T08:00:00",
        extracted_requirements={"age": "35周岁以下", "degree": "硕士及以上", "field": "相关专业"},
    )

    def agent_evaluator(prof: CandidateProfile, observation: SourceObservation) -> EvaluationResult:
        packet = build_evaluation_packet(prof, observation)
        assert packet["candidate_evidence"]["date_of_birth"] == "1995-05-20"
        assert "Example Core Skill A" in packet["candidate_evidence"]["proven_capabilities"]
        dim_evals = {
            "Age": DimensionEvaluation(dimension="Age", state="PASS", requirement_evidence="35周岁以下", rationale="候选人年龄符合要求"),
            "Education": DimensionEvaluation(dimension="Education", state="PASS", requirement_evidence="硕士及以上", rationale="具备硕士学位"),
            "Formal Qualification": DimensionEvaluation(dimension="Formal Qualification", state="PASS", requirement_evidence="相关专业", rationale="专业对口"),
            "Capability Fit": DimensionEvaluation(dimension="Capability Fit", state="PASS", requirement_evidence="课程教学", rationale="具备教学能力"),
            "Teaching Experience": DimensionEvaluation(dimension="Teaching Experience", state="PASS", requirement_evidence="不限", rationale="具备3年教学经历"),
            "Industry Experience": DimensionEvaluation(dimension="Industry Experience", state="PASS", requirement_evidence="不限", rationale="具备4年行业经验"),
        }
        return EvaluationValidator.validate_and_aggregate(
            EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dim_evals, evaluated_at="2026-08-16T08:00:00")
        )

    outcome = orchestrator.run(
        observations=[obs],
        evaluator_fn=agent_evaluator,
        run_date="2026-08-16",
    )

    assert outcome.status == "success"
    assert outcome.recommended_count == 1
    report_content = Path(outcome.report_path).read_text(encoding="utf-8")
    assert "Example Lecturer Role" in report_content
    assert "建议关注" in report_content
