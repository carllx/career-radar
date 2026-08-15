"""
Guard and Failure-Path Tests for Issue #11 Entity Resolution:
1. Prohibit implicit 'different' when prior state exists (fail fast without altering store).
2. Require real Eligibility EvaluationResult for update, different, and uncertain (prohibit placeholder evaluations).
3. Require valid target_opportunity_id present in current state for uncertain (prevent dangling/one-way soft links).
4. Update Digest must link the latest update evidence URL without corrupting canonical Opportunity URL.
"""

from datetime import datetime
from pathlib import Path
import pytest
import yaml

from career_radar.models import (
    CandidateProfile,
    DimensionEvaluation,
    EntityResolutionDecision,
    EvaluationResult,
    Opportunity,
    SourceObservation,
)
from career_radar.runner import (
    finalize_evaluation_run,
    finalize_incremental_run,
    run_radar_pipeline,
)
from career_radar.store import OpportunityStore


@pytest.fixture
def mock_profile_file(tmp_path: Path) -> Path:
    profile_data = {
        "candidate": {
            "age": 30,
            "degree": "硕士研究生",
            "degree_field": "计算机科学与技术",
            "teaching_experience_years": 3,
            "industry_experience_years": 4,
            "tracks": [{"name": "higher_education_teaching", "priority": "P1"}],
            "regions": {"P1": ["广州"]},
            "hard_constraints": {"min_degree": "硕士研究生", "max_age": 35},
        }
    }
    path = tmp_path / "profile.local.yaml"
    path.write_text(yaml.dump(profile_data, allow_unicode=True), encoding="utf-8")
    return path


def _create_base_opp(opp_id: str = "opp_base_001") -> Opportunity:
    now = datetime.now().isoformat()
    obs = SourceObservation(
        observation_id=f"obs_{opp_id}",
        announcement_id="ann_base",
        source_id="src_base",
        source_name="官方主站",
        announcement_title="广东药科大学2026年公开招聘公告",
        job_title="计算机科学专任教师",
        organization="广东药科大学",
        location="广州",
        track="higher_education_teaching",
        official_url="https://hrss.gd.gov.cn/post_base.html",
        observed_at=now,
        extracted_requirements={"age_text": "35周岁以下", "education_text": "硕士研究生"},
    )
    eval_res = EvaluationResult(
        final_recommendation="建议关注",
        dimension_evaluations={
            "Age": DimensionEvaluation("Age", "PASS", "35周岁以下", "符合"),
            "Education": DimensionEvaluation("Education", "PASS", "硕士研究生", "符合"),
            "Formal Qualification": DimensionEvaluation("Formal Qualification", "PASS", "计算机", "符合"),
            "Capability Fit": DimensionEvaluation("Capability Fit", "PASS", "", "符合"),
            "Teaching Experience": DimensionEvaluation("Teaching Experience", "PASS", "", "符合"),
            "Industry Experience": DimensionEvaluation("Industry Experience", "N/A", "", "不适用"),
        },
        evaluated_at=now,
    )
    return Opportunity(
        opportunity_id=opp_id,
        canonical_job_title="计算机科学专任教师",
        organization="广东药科大学",
        location="广州",
        track="higher_education_teaching",
        official_url="https://hrss.gd.gov.cn/post_base.html",
        lifecycle_status="active",
        observations=[obs],
        latest_evaluation=eval_res,
        created_at=now,
        updated_at=now,
    )


# --- Guard 1: Prohibit implicit 'different' when prior state exists ---


def test_stateful_run_without_entity_resolver_fails_fast_and_preserves_store(
    tmp_path: Path, mock_profile_file: Path
):
    """
    BLOCKER 1 TEST:
    When prior opportunities exist, omitting entity_resolver_fn MUST fail fast with clear error.
    Helper is strictly forbidden from assuming 'different'. Store must remain unchanged.
    """
    data_dir, reports_dir = tmp_path / ".data", tmp_path / "reports"
    store = OpportunityStore(data_dir)
    prior_opp = _create_base_opp("opp_prior_001")
    store.save_opportunities([prior_opp])

    incoming_obs = SourceObservation(
        observation_id="obs_incoming_002",
        announcement_id="ann_inc",
        source_id="src_inc",
        source_name="人社局",
        announcement_title="广东药科大学新公告",
        job_title="软件工程专任教师",
        organization="广东药科大学",
        location="广州",
        track="higher_education_teaching",
        official_url="https://hrss.gd.gov.cn/post_inc.html",
        observed_at=datetime.now().isoformat(),
        extracted_requirements={},
    )

    def dummy_evaluator(prof, obs):
        return prior_opp.latest_evaluation

    with pytest.raises(ValueError) as excinfo:
        run_radar_pipeline(
            profile_path=mock_profile_file,
            observations_source=[incoming_obs],
            evaluator_fn=dummy_evaluator,
            entity_resolver_fn=None,  # Missing entity resolver on stateful run
            data_dir=data_dir,
            reports_dir=reports_dir,
        )
    assert "Prior opportunities exist in store" in str(excinfo.value)
    assert "Helper is strictly prohibited from assuming 'different'" in str(excinfo.value)

    # Store must remain untouched
    saved_opps = store.load_all_opportunities()
    assert len(saved_opps) == 1
    assert saved_opps[0].opportunity_id == "opp_prior_001"


# --- Guard 2: Require real Eligibility EvaluationResult for update ---


def test_update_resolution_missing_evaluation_fails_fast_and_preserves_store(
    tmp_path: Path, mock_profile_file: Path
):
    """
    BLOCKER 2 TEST:
    Entity resolution 'update' requires a valid EvaluationResult.
    Missing evaluation must fail fast without mutating existing opportunity.
    """
    data_dir = tmp_path / ".data"
    store = OpportunityStore(data_dir)
    prior_opp = _create_base_opp("opp_prior_update_001")
    store.save_opportunities([prior_opp])

    update_obs = SourceObservation(
        observation_id="obs_supp_001",
        announcement_id="ann_supp",
        source_id="src_supp",
        source_name="人事处",
        announcement_title="补充公告",
        job_title="计算机科学专任教师",
        organization="广东药科大学",
        location="广州",
        track="",
        official_url="https://hrss.gd.gov.cn/supp.html",
        observed_at=datetime.now().isoformat(),
        extracted_requirements={},
    )

    update_decision = EntityResolutionDecision(
        resolution="update",
        target_opportunity_id="opp_prior_update_001",
        diff_summary="延期通知",
    )

    with pytest.raises(ValueError) as excinfo:
        finalize_incremental_run(
            observations=[update_obs],
            resolution_decisions=[update_decision],
            evaluation_results={},  # Missing evaluation result for update!
            data_dir=data_dir,
            reports_dir=tmp_path / "reports",
        )
    assert "requires a valid re-evaluated EvaluationResult" in str(excinfo.value)

    # Store must be unchanged
    saved_opps = store.load_all_opportunities()
    assert len(saved_opps) == 1
    assert saved_opps[0].lifecycle_status == "active"  # Not mutated to updated
    assert len(saved_opps[0].observations) == 1  # Observation not appended


# --- Guard 3: Require real Eligibility EvaluationResult for uncertain ---


def test_uncertain_resolution_missing_evaluation_fails_fast_and_creates_no_placeholder(
    tmp_path: Path,
):
    """
    BLOCKER 2 TEST:
    Entity resolution 'uncertain' must NOT fabricate a placeholder '需要人工确认' evaluation.
    Missing evaluation must fail fast.
    """
    data_dir = tmp_path / ".data"
    store = OpportunityStore(data_dir)
    prior_opp = _create_base_opp("opp_prior_unc_001")
    store.save_opportunities([prior_opp])

    unc_obs = SourceObservation(
        observation_id="obs_unc_001",
        announcement_id="ann_unc",
        source_id="src_unc",
        source_name="社群",
        announcement_title="招聘快讯",
        job_title="计算机与多媒体岗",
        organization="广东药科大学",
        location="广州",
        track="",
        official_url="https://example.com/unc.html",
        observed_at=datetime.now().isoformat(),
        extracted_requirements={},
    )

    unc_decision = EntityResolutionDecision(
        resolution="uncertain",
        target_opportunity_id="opp_prior_unc_001",
        rationale="证据不足",
    )

    with pytest.raises(ValueError) as excinfo:
        finalize_incremental_run(
            observations=[unc_obs],
            resolution_decisions=[unc_decision],
            evaluation_results={},  # Missing evaluation result for uncertain!
            data_dir=data_dir,
            reports_dir=tmp_path / "reports",
        )
    assert "requires a valid EvaluationResult" in str(excinfo.value)

    saved_opps = store.load_all_opportunities()
    assert len(saved_opps) == 1  # No placeholder opportunity was created


# --- Guard 4: Uncertain requires valid target in state ---


def test_uncertain_resolution_requires_valid_target_in_current_state(tmp_path: Path):
    """
    BLOCKER 3 TEST:
    resolution='uncertain' requires target_opportunity_id to exist in current state.
    Missing or non-existent target fails fast.
    """
    data_dir = tmp_path / ".data"
    store = OpportunityStore(data_dir)

    unc_obs = SourceObservation(
        observation_id="obs_unc_bad_target",
        announcement_id="ann_bad",
        source_id="src_bad",
        source_name="社群",
        announcement_title="快讯",
        job_title="测试岗",
        organization="某大学",
        location="",
        track="",
        official_url="https://example.com/bad.html",
        observed_at=datetime.now().isoformat(),
        extracted_requirements={},
    )

    # Decision with non-existent target
    bad_decision = EntityResolutionDecision(
        resolution="uncertain",
        target_opportunity_id="opp_non_existent_999",
        rationale="存疑关联",
    )

    valid_eval = EvaluationResult(
        final_recommendation="建议关注",
        dimension_evaluations={
            "Age": DimensionEvaluation("Age", "PASS", "", "符合"),
            "Education": DimensionEvaluation("Education", "PASS", "", "符合"),
            "Formal Qualification": DimensionEvaluation("Formal Qualification", "PASS", "", "符合"),
            "Capability Fit": DimensionEvaluation("Capability Fit", "PASS", "", "符合"),
            "Teaching Experience": DimensionEvaluation("Teaching Experience", "PASS", "", "符合"),
            "Industry Experience": DimensionEvaluation("Industry Experience", "N/A", "", "不适用"),
        },
        evaluated_at=datetime.now().isoformat(),
    )

    with pytest.raises(ValueError) as excinfo:
        finalize_incremental_run(
            observations=[unc_obs],
            resolution_decisions=[bad_decision],
            evaluation_results={"obs_unc_bad_target": valid_eval},
            data_dir=data_dir,
            reports_dir=tmp_path / "reports",
        )
    assert "requires a valid target_opportunity_id present in the current state" in str(excinfo.value)


# --- Guard 5: Update Digest links latest update evidence URL ---


def test_update_digest_links_latest_update_evidence_url(
    tmp_path: Path, mock_profile_file: Path
):
    """
    BLOCKER 4 TEST:
    In Daily Digest '重点岗位动态变更', the update entry MUST link the latest update observation URL,
    while canonical Opportunity official_url remains intact.
    """
    data_dir, reports_dir = tmp_path / ".data", tmp_path / "reports"
    store = OpportunityStore(data_dir)

    prior_opp = _create_base_opp("opp_link_test_001")
    prior_opp.official_url = "https://rsc.gpnu.edu.cn/post_002.html"
    store.save_opportunities([prior_opp])

    update_obs = SourceObservation(
        observation_id="obs_extension_link_002",
        announcement_id="ann_ext",
        source_id="src_rsc",
        source_name="人事处",
        announcement_title="延期补充公告",
        job_title="计算机科学专任教师",
        organization="广东药科大学",
        location="广州",
        track="higher_education_teaching",
        official_url="https://rsc.gpnu.edu.cn/post_002_extension.html",  # New extension URL
        observed_at=datetime.now().isoformat(),
        extracted_requirements={},
    )

    update_decision = EntityResolutionDecision(
        resolution="update",
        target_opportunity_id="opp_link_test_001",
        diff_summary="报名时间延长至2026-09-30",
    )

    re_eval = EvaluationResult(
        final_recommendation="建议关注",
        dimension_evaluations={
            "Age": DimensionEvaluation("Age", "PASS", "35周岁", "符合"),
            "Education": DimensionEvaluation("Education", "PASS", "硕士", "符合"),
            "Formal Qualification": DimensionEvaluation("Formal Qualification", "PASS", "计算机", "符合"),
            "Capability Fit": DimensionEvaluation("Capability Fit", "PASS", "", "符合"),
            "Teaching Experience": DimensionEvaluation("Teaching Experience", "PASS", "", "符合"),
            "Industry Experience": DimensionEvaluation("Industry Experience", "N/A", "", "不适用"),
        },
        evaluated_at=datetime.now().isoformat(),
    )

    summary = finalize_incremental_run(
        observations=[update_obs],
        resolution_decisions=[update_decision],
        evaluation_results={"obs_extension_link_002": re_eval},
        data_dir=data_dir,
        reports_dir=reports_dir,
        run_date="2026-08-15",
    )

    # 1. Canonical Opportunity official_url is preserved
    saved_opps = store.load_all_opportunities()
    assert saved_opps[0].official_url == "https://rsc.gpnu.edu.cn/post_002.html"

    # 2. Markdown Daily Digest specifically links the update extension URL!
    report_content = Path(summary["report_path"]).read_text(encoding="utf-8")
    assert "https://rsc.gpnu.edu.cn/post_002_extension.html" in report_content
    assert "报名时间延长至2026-09-30" in report_content
