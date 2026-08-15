"""
Highest Seam Tests for Issue #11 Sequential In-Memory Working State and Failure Atomicity.
Ensures:
1. Newly created Opportunities in the SAME Run are immediately visible in subsequent observations' candidate packets.
2. Cross-channel duplicate posts in the same run resolve to 1 Opportunity / 2 observations without duplicate alerts.
3. Failure in any observation fails fast and guarantees disk persistence atomicity (store remains unchanged).
"""

from datetime import datetime
from pathlib import Path
from typing import List
import pytest
import yaml

from career_radar.models import (
    DimensionEvaluation,
    EntityResolutionDecision,
    EvaluationResult,
    Opportunity,
    SourceObservation,
)
from career_radar.runner import (
    IncrementalResolutionSession,
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


def _create_eval_result() -> EvaluationResult:
    return EvaluationResult(
        final_recommendation="建议关注",
        dimension_evaluations={
            "Age": DimensionEvaluation("Age", "PASS", "35周岁以下", "符合年龄"),
            "Education": DimensionEvaluation("Education", "PASS", "硕士研究生", "符合学历"),
            "Formal Qualification": DimensionEvaluation("Formal Qualification", "PASS", "数字媒体", "符合专业"),
            "Capability Fit": DimensionEvaluation("Capability Fit", "PASS", "", "匹配"),
            "Teaching Experience": DimensionEvaluation("Teaching Experience", "PASS", "", "具备经验"),
            "Industry Experience": DimensionEvaluation("Industry Experience", "N/A", "", "不适用"),
        },
        evaluated_at=datetime.now().isoformat(),
    )


# --- 1. Same-run cross-channel observations sequential resolution ---


def test_same_run_cross_channel_observations_sequential_resolution(
    tmp_path: Path, mock_profile_file: Path
):
    """
    CRITICAL SPEC TEST:
    Initial store: EMPTY.
    Same run receives 2 observations for the same job from different channels (official site + HRSS).
    Observation A arrives first -> creates Opportunity.
    Observation B arrives second -> its Candidate Packet MUST contain Opportunity A (even if job title differs!).
    Agent resolves B as 'same(target=A)'.

    Assertions:
    1. B's candidate packet truly contains A's Opportunity;
    2. Final store has only 1 Opportunity;
    3. Opportunity has 2 SourceObservations (preserving both sources & provenance);
    4. new_opportunities_count == 1;
    5. deduped_same_count == 1;
    6. Daily Digest only announces 1 new opportunity.
    """
    data_dir, reports_dir = tmp_path / ".data", tmp_path / "reports"
    now = datetime.now().isoformat()

    # Observation A: University official site
    obs_a = SourceObservation(
        observation_id="obs_gpnu_official_001",
        announcement_id="ann_gpnu_official",
        source_id="gpnu_rsc",
        source_name="广东技术师范大学人事处",
        announcement_title="广东技术师范大学2026年专任教师招聘公告",
        job_title="数字媒体艺术专任教师",
        organization="广东技术师范大学",
        location="广州",
        track="higher_education_teaching",
        official_url="https://rsc.gpnu.edu.cn/post_001.html",
        observed_at=now,
        extracted_requirements={"age_text": "35周岁以下", "education_text": "硕士研究生及以上"},
        provenance={"source_url": "https://rsc.gpnu.edu.cn/post_001.html", "department": "美术学院"},
    )

    # Observation B: HRSS column (same institution, different job title string)
    obs_b = SourceObservation(
        observation_id="obs_hrss_channel_002",
        announcement_id="ann_hrss_batch",
        source_id="gd_hrss",
        source_name="广东省人力资源和社会保障厅招聘专栏",
        announcement_title="广东省直事业单位2026年集中招聘",
        job_title="数字媒体技术教学科研岗",
        organization="广东技术师范大学",
        location="广州",
        track="higher_education_teaching",
        official_url="https://hrss.gd.gov.cn/post_002_gpnu.html",
        observed_at=now,
        extracted_requirements={"age_text": "35周岁以下", "education_text": "硕士研究生及以上"},
        provenance={"source_url": "https://hrss.gd.gov.cn/post_002_gpnu.html", "channel": "hrss_aggregator"},
    )

    seen_candidates_for_b: List[Opportunity] = []

    def mock_agent_entity_resolver(obs: SourceObservation, candidates: List[Opportunity]) -> EntityResolutionDecision:
        if obs.observation_id == "obs_gpnu_official_001":
            # First observation in empty store -> candidates is empty -> different
            assert len(candidates) == 0
            return EntityResolutionDecision(
                resolution="different",
                target_opportunity_id=None,
                rationale="首次发现广东技术师范大学数字媒体专任教师编制岗位",
            )
        elif obs.observation_id == "obs_hrss_channel_002":
            # Second observation in SAME run -> candidates MUST contain Opportunity created from obs_a!
            seen_candidates_for_b.extend(candidates)
            assert len(candidates) >= 1
            matched_candidate = next(
                (c for c in candidates if c.organization == "广东技术师范大学"), None
            )
            assert matched_candidate is not None
            assert matched_candidate.opportunity_id == "opp_obs_gpnu_official_001"
            return EntityResolutionDecision(
                resolution="same",
                target_opportunity_id=matched_candidate.opportunity_id,
                rationale="人社厅集中招聘专栏与学校人事处官网属于同一数字媒体教师岗位跨渠道发布",
            )
        raise ValueError(f"Unexpected observation: {obs.observation_id}")

    res = run_radar_pipeline(
        profile_path=mock_profile_file,
        observations_source=[obs_a, obs_b],
        evaluator_fn=lambda prof, obs: _create_eval_result(),
        entity_resolver_fn=mock_agent_entity_resolver,
        data_dir=data_dir,
        reports_dir=reports_dir,
        run_date="2026-08-15",
    )

    # 1. Candidate retrieval during same run truly saw A
    assert len(seen_candidates_for_b) == 1
    assert seen_candidates_for_b[0].opportunity_id == "opp_obs_gpnu_official_001"

    # 2. Final store has only 1 Opportunity
    store = OpportunityStore(data_dir)
    saved_opps = store.load_all_opportunities()
    assert len(saved_opps) == 1
    opp = saved_opps[0]

    # 3. Opportunity has 2 SourceObservations from both channels
    assert opp.opportunity_id == "opp_obs_gpnu_official_001"
    assert len(opp.observations) == 2
    sources = {o.source_name for o in opp.observations}
    assert "广东技术师范大学人事处" in sources
    assert "广东省人力资源和社会保障厅招聘专栏" in sources

    # 4. Correct counts
    assert res["new_opportunities_count"] == 1
    assert res["deduped_same_count"] == 1
    assert res["total_in_store"] == 1

    # 5. Daily Digest only announces 1 new opportunity
    report_content = Path(res["report_path"]).read_text(encoding="utf-8")
    assert report_content.count("### [数字媒体") == 1


# --- 2. Failure atomicity across same run batch ---


def test_same_run_failure_atomicity_preserves_disk_store(
    tmp_path: Path, mock_profile_file: Path
):
    """
    FAILURE ATOMICITY TEST:
    Initial store is EMPTY.
    Batch has 2 observations:
    - Observation A is valid and staged as 'different'.
    - Observation B fails due to missing required evaluation (or invalid target).

    Assertion:
    The entire run fails fast, and disk store remains completely empty (Observation A is NOT partially persisted).
    """
    data_dir, reports_dir = tmp_path / ".data", tmp_path / "reports"
    now = datetime.now().isoformat()

    obs_a = SourceObservation(
        observation_id="obs_atomic_a",
        announcement_id="ann_a",
        source_id="src_a",
        source_name="人事处",
        announcement_title="招聘公告A",
        job_title="计算机专任教师",
        organization="某大学",
        location="广州",
        track="higher_education_teaching",
        official_url="https://example.edu.cn/a.html",
        observed_at=now,
        extracted_requirements={},
    )

    obs_b = SourceObservation(
        observation_id="obs_atomic_b",
        announcement_id="ann_b",
        source_id="src_b",
        source_name="人事处",
        announcement_title="补充公告B",
        job_title="计算机专任教师补充",
        organization="某大学",
        location="广州",
        track="higher_education_teaching",
        official_url="https://example.edu.cn/b.html",
        observed_at=now,
        extracted_requirements={},
    )

    def mock_resolver(obs: SourceObservation, candidates: List[Opportunity]) -> EntityResolutionDecision:
        if obs.observation_id == "obs_atomic_a":
            return EntityResolutionDecision(resolution="different", target_opportunity_id=None, rationale="新岗位")
        elif obs.observation_id == "obs_atomic_b":
            # Fails due to non-existent target ID
            return EntityResolutionDecision(resolution="uncertain", target_opportunity_id="non_existent_target_999", rationale="存疑")
        raise ValueError(obs.observation_id)

    with pytest.raises(ValueError) as excinfo:
        run_radar_pipeline(
            profile_path=mock_profile_file,
            observations_source=[obs_a, obs_b],
            evaluator_fn=lambda prof, obs: _create_eval_result(),
            entity_resolver_fn=mock_resolver,
            data_dir=data_dir,
            reports_dir=reports_dir,
        )
    assert "requires a valid target_opportunity_id present in the current state" in str(excinfo.value)

    # Disk store MUST be empty — Observation A was NOT partially persisted to disk
    store = OpportunityStore(data_dir)
    saved_opps = store.load_all_opportunities()
    assert len(saved_opps) == 0
