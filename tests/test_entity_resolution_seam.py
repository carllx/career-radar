"""
Highest Seam TDD Test Suite for Issue #11:
High-recall Candidate Retrieval & Agent 4-state Entity Resolution (same/update/different/uncertain).
Respects CONTEXT.md and ADR-0001 ~ ADR-0004.
"""

from datetime import datetime
from pathlib import Path
import pytest
import yaml

from career_radar.models import (
    DimensionEvaluation,
    EntityResolutionDecision,
    EvaluationResult,
    Opportunity,
    OpportunityIntentDecision,
    SourceObservation,
)
from career_radar.resolver import build_entity_resolution_packet
from career_radar.retriever import CandidateRetriever
from career_radar.runner import run_radar_pipeline
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


def _create_sample_opportunity(
    opp_id: str,
    job_title: str,
    org: str,
    location: str = "广州",
    recommendation: str = "建议关注",
) -> Opportunity:
    now = datetime.now().isoformat()
    obs = SourceObservation(
        observation_id=f"obs_{opp_id}_1",
        announcement_id="ann_sample_1",
        source_id="src_official",
        source_name="官方主站",
        announcement_title=f"{org}人才招聘",
        job_title=job_title,
        organization=org,
        location=location,
        track="higher_education_teaching",
        official_url=f"https://example.edu.cn/jobs/{opp_id}",
        observed_at=now,
        extracted_requirements={"age_text": "35周岁以下", "education_text": "硕士及以上"},
        provenance={"source_url": f"https://example.edu.cn/jobs/{opp_id}"},
    )
    eval_res = EvaluationResult(
        final_recommendation=recommendation,
        dimension_evaluations={
            "Age": DimensionEvaluation("Age", "PASS", "35周岁以下", "符合年龄"),
            "Education": DimensionEvaluation("Education", "PASS", "硕士", "符合学历"),
            "Formal Qualification": DimensionEvaluation("Formal Qualification", "PASS", "计算机", "符合专业"),
            "Capability Fit": DimensionEvaluation("Capability Fit", "PASS", "", "符合胜任力"),
            "Teaching Experience": DimensionEvaluation("Teaching Experience", "PASS", "", "符合要求"),
            "Industry Experience": DimensionEvaluation("Industry Experience", "N/A", "", "不适用"),
        },
        evaluated_at=now,
    )
    return Opportunity(
        opportunity_id=opp_id,
        canonical_job_title=job_title,
        organization=org,
        location=location,
        track="higher_education_teaching",
        official_url=f"https://example.edu.cn/jobs/{opp_id}",
        lifecycle_status="active",
        observations=[obs],
        latest_evaluation=eval_res,
        created_at=now,
        updated_at=now,
    )


# --- 1. High-Recall Retrieval Unit & Seam Test (Title Mismatch Test) ---


def test_candidate_retriever_high_recall_regardless_of_title_difference():
    """
    CRITICAL SPEC REQUIREMENT:
    Prior Opportunity has a job title, and a new Observation from the same institution has a completely different title.
    CandidateRetriever MUST return the prior Opportunity in the candidate pool for Agent inspection.
    Title mismatch or zero keyword overlap must NEVER act as a hard exclusion gate.
    """
    retriever = CandidateRetriever()
    prior_opp = _create_sample_opportunity(
        opp_id="opp_gdpu_001",
        job_title="劳动卫生与环境卫生学系教学科研岗",
        org="广东药科大学",
    )

    # New observation from the same institution with a completely different title and zero keyword overlap
    new_obs = SourceObservation(
        observation_id="obs_gdpu_new_1",
        announcement_id="ann_gdpu_supplement",
        source_id="src_aggregator",
        source_name="人社局招聘网",
        announcement_title="广东药科大学高层次青年领军学者支持计划",
        job_title="高层次领军学者特别支持计划青年岗位",
        organization="广东药科大学",
        location="广州",
        track="",
        official_url="https://hrss.gd.gov.cn/post_new.html",
        observed_at=datetime.now().isoformat(),
        extracted_requirements={},
    )

    candidates = retriever.retrieve_candidates(new_obs, [prior_opp])

    assert len(candidates) == 1
    assert candidates[0].opportunity_id == "opp_gdpu_001"

    # Build Agent resolution packet and verify full evidence history is present
    packet = build_entity_resolution_packet(new_obs, candidates)
    assert packet["candidates_count"] == 1
    assert packet["candidates"][0]["job_title"] == "劳动卫生与环境卫生学系教学科研岗"
    assert len(packet["candidates"][0]["observations_history"]) == 1


# --- 2. Slice A — same ---


def test_entity_resolution_slice_a_same(tmp_path: Path, mock_profile_file: Path):
    """
    Slice A (same):
    Prior Opportunity exists. Second-source observation for the same job arrives.
    Agent resolves as 'same'.
    Result: 1 Opportunity in store with 2 observations, no duplicate opportunity, no duplicate new job alert.
    """
    data_dir, reports_dir = tmp_path / ".data", tmp_path / "reports"
    store = OpportunityStore(data_dir)

    prior_opp = _create_sample_opportunity(
        opp_id="opp_101", job_title="数字媒体应用技术专任教师", org="广东轻工职业技术大学"
    )
    store.save_opportunities([prior_opp])

    second_source_obs = SourceObservation(
        observation_id="obs_second_channel_101",
        announcement_id="ann_aggregator_2",
        source_id="src_gpc",
        source_name="高校人才网",
        announcement_title="广东轻工职业技术大学专任教师招聘",
        job_title="数字媒体应用技术专任教师",
        organization="广东轻工职业技术大学",
        location="广州",
        track="higher_education_teaching",
        official_url="https://www.gaoxiaojob.com/item/101.html",
        observed_at=datetime.now().isoformat(),
        extracted_requirements={"age_text": "35周岁以下", "education_text": "硕士及以上"},
        provenance={"source_url": "https://www.gaoxiaojob.com/item/101.html", "channel": "aggregator"},
    )

    def fake_entity_resolver(obs, candidates):
        assert len(candidates) >= 1
        return EntityResolutionDecision(
            resolution="same",
            target_opportunity_id="opp_101",
            rationale="高校人才网对广东轻工职业技术大学同一数字媒体教师岗位的跨渠道二次发布",
        )

    res = run_radar_pipeline(
        profile_path=mock_profile_file,
        observations_source=[second_source_obs],
        evaluator_fn=lambda prof, obs: prior_opp.latest_evaluation,
        entity_resolver_fn=fake_entity_resolver,
        data_dir=data_dir,
        reports_dir=reports_dir,
        run_date="2026-08-15",
    )

    assert res["success"] is True
    assert res["total_in_store"] == 1
    assert res["new_opportunities_count"] == 0
    assert res["deduped_same_count"] == 1

    saved_opps = store.load_all_opportunities()
    assert len(saved_opps) == 1
    opp = saved_opps[0]
    assert opp.opportunity_id == "opp_101"
    assert len(opp.observations) == 2
    assert opp.observations[0].source_name == "官方主站"
    assert opp.observations[1].source_name == "高校人才网"

    report_content = Path(res["report_path"]).read_text(encoding="utf-8")
    assert "本次巡检未发现新增高匹配度机会" in report_content


# --- 3. Slice B — update ---


def test_entity_resolution_slice_b_update(tmp_path: Path, mock_profile_file: Path):
    """
    Slice B (update):
    Prior Opportunity exists. Supplementary announcement arrives.
    Agent resolves as 'update', triggering eligibility re-evaluation.
    Result: Same Opportunity ID, lifecycle_status='updated', diff recorded, appears in Digest 重点岗位动态变更.
    """
    data_dir, reports_dir = tmp_path / ".data", tmp_path / "reports"
    store = OpportunityStore(data_dir)

    prior_opp = _create_sample_opportunity(
        opp_id="opp_201", job_title="中药资源与开发系教学科研岗", org="广东药科大学"
    )
    store.save_opportunities([prior_opp])

    update_obs = SourceObservation(
        observation_id="obs_update_201",
        announcement_id="ann_supp_201",
        source_id="gd_hrss_official",
        source_name="广东省人社厅",
        announcement_title="广东药科大学2026年招聘补充通知（延长报名并放宽年龄）",
        job_title="中药资源与开发系教学科研岗",
        organization="广东药科大学",
        location="广州",
        track="higher_education_teaching",
        official_url="https://hrss.gd.gov.cn/post_201_supp.html",
        observed_at=datetime.now().isoformat(),
        extracted_requirements={"age_text": "40周岁以下（放宽）", "other_conditions_text": "报名时间延期至2026年9月15日"},
        provenance={"source_url": "https://hrss.gd.gov.cn/post_201_supp.html"},
    )

    def fake_entity_resolver(obs, candidates):
        return EntityResolutionDecision(
            resolution="update",
            target_opportunity_id="opp_201",
            diff_summary="报名时间延长至2026-09-15，年龄要求放宽至40周岁以下",
            rationale="官方补充通知针对既有中药系岗位进行延期与年龄放宽",
        )

    def fake_re_evaluator(profile, obs):
        now = datetime.now().isoformat()
        return EvaluationResult(
            final_recommendation="建议关注",
            dimension_evaluations={
                "Age": DimensionEvaluation("Age", "PASS", "40周岁以下", "候选人30岁符合放宽后年龄"),
                "Education": DimensionEvaluation("Education", "PASS", "硕士", "符合要求"),
                "Formal Qualification": DimensionEvaluation("Formal Qualification", "PASS", "中药学", "符合要求"),
                "Capability Fit": DimensionEvaluation("Capability Fit", "PASS", "", "符合要求"),
                "Teaching Experience": DimensionEvaluation("Teaching Experience", "PASS", "", "符合要求"),
                "Industry Experience": DimensionEvaluation("Industry Experience", "N/A", "", "不适用"),
            },
            evaluated_at=now,
        )

    def fake_intent_evaluator(profile, obs, ev):
        return OpportunityIntentDecision(
            opportunity_intent="APPLY_NOW",
            intent_rationale="更新后条件符合即刻行动",
        )

    res = run_radar_pipeline(
        profile_path=mock_profile_file,
        observations_source=[update_obs],
        evaluator_fn=fake_re_evaluator,
        intent_evaluator_fn=fake_intent_evaluator,
        entity_resolver_fn=fake_entity_resolver,
        data_dir=data_dir,
        reports_dir=reports_dir,
        run_date="2026-08-15",
    )

    assert res["success"] is True
    assert res["total_in_store"] == 1
    assert res["updated_opportunities_count"] == 1

    saved_opps = store.load_all_opportunities()
    opp = saved_opps[0]
    assert opp.opportunity_id == "opp_201"
    assert opp.lifecycle_status == "updated"
    assert "报名时间延长至2026-09-15" in opp.update_summary
    assert len(opp.observations) == 2

    report_content = Path(res["report_path"]).read_text(encoding="utf-8")
    assert "## 🔄 重点岗位动态变更" in report_content
    assert "报名时间延长至2026-09-15，年龄要求放宽至40周岁以下" in report_content


# --- 4. Slice C — different ---


def test_entity_resolution_slice_c_different(tmp_path: Path, mock_profile_file: Path):
    """
    Slice C (different):
    Prior Opportunity exists in institution. New observation for a distinct post arrives.
    Agent resolves as 'different'.
    Result: 2 independent Opportunities created and persisted.
    """
    data_dir, reports_dir = tmp_path / ".data", tmp_path / "reports"
    store = OpportunityStore(data_dir)

    prior_opp = _create_sample_opportunity(
        opp_id="opp_301", job_title="计算机科学与技术专任教师", org="广东药科大学"
    )
    store.save_opportunities([prior_opp])

    new_obs = SourceObservation(
        observation_id="obs_302",
        announcement_id="ann_302",
        source_id="gd_hrss_official",
        source_name="广东省人社厅",
        announcement_title="广东药科大学2026年招聘公告",
        job_title="马克思主义理论专任教师",
        organization="广东药科大学",
        location="广州",
        track="higher_education_teaching",
        official_url="https://hrss.gd.gov.cn/post_302.html",
        observed_at=datetime.now().isoformat(),
        extracted_requirements={"age_text": "35周岁以下", "education_text": "博士研究生"},
        provenance={"department": "马克思主义学院"},
    )

    def fake_entity_resolver(obs, candidates):
        return EntityResolutionDecision(
            resolution="different",
            target_opportunity_id=None,
            rationale="马院思政专任教师与计院专任教师为完全不同的独立教学科研岗位",
        )

    def fake_evaluator(profile, obs):
        now = datetime.now().isoformat()
        return EvaluationResult(
            final_recommendation="明显不符合",
            dimension_evaluations={
                "Age": DimensionEvaluation("Age", "PASS", "35周岁以下", "符合年龄"),
                "Education": DimensionEvaluation("Education", "FAIL", "博士研究生", "学历不足"),
                "Formal Qualification": DimensionEvaluation("Formal Qualification", "FAIL", "马克思主义", "专业不符"),
                "Capability Fit": DimensionEvaluation("Capability Fit", "FAIL", "", "不符"),
                "Teaching Experience": DimensionEvaluation("Teaching Experience", "PASS", "", "具备经验"),
                "Industry Experience": DimensionEvaluation("Industry Experience", "N/A", "", "不适用"),
            },
            evaluated_at=now,
        )

    def fake_intent_evaluator(profile, obs, ev):
        return OpportunityIntentDecision(
            opportunity_intent="WATCH_LEARN",
            intent_rationale="不同岗位但资格明显不符，保持情报观察",
        )

    res = run_radar_pipeline(
        profile_path=mock_profile_file,
        observations_source=[new_obs],
        evaluator_fn=fake_evaluator,
        intent_evaluator_fn=fake_intent_evaluator,
        entity_resolver_fn=fake_entity_resolver,
        data_dir=data_dir,
        reports_dir=reports_dir,
        run_date="2026-08-15",
    )

    assert res["success"] is True
    assert res["total_in_store"] == 2
    assert res["new_opportunities_count"] == 1
    assert res["mismatch_count"] == 1

    saved_opps = store.load_all_opportunities()
    assert len(saved_opps) == 2
    opp_ids = {o.opportunity_id for o in saved_opps}
    assert "opp_301" in opp_ids
    assert "opp_obs_302" in opp_ids


# --- 5. Slice D — uncertain ---


def test_entity_resolution_slice_d_uncertain(tmp_path: Path, mock_profile_file: Path):
    """
    Slice D (uncertain):
    Prior Opportunity exists. Ambiguous observation arrives.
    Agent resolves as 'uncertain'.
    Result: NO force-merge. 2 independent Opportunities with bidirectional soft link.
    Eligibility dimension states are NOT modified. Digest displays '【实体同一性待确认】'.
    """
    data_dir, reports_dir = tmp_path / ".data", tmp_path / "reports"
    store = OpportunityStore(data_dir)

    prior_opp = _create_sample_opportunity(
        opp_id="opp_401", job_title="计算机视觉与数字媒体讲师", org="广东某职业技术大学", recommendation="建议关注"
    )
    store.save_opportunities([prior_opp])

    uncertain_obs = SourceObservation(
        observation_id="obs_402_snippet",
        announcement_id="ann_snippet_402",
        source_id="src_social",
        source_name="求职社群转发",
        announcement_title="广东某职大近期招聘快讯",
        job_title="视觉计算与多媒体技术岗",
        organization="广东某职业技术大学",
        location="广州",
        track="higher_education_teaching",
        official_url="https://wechat.example.com/post_402",
        observed_at=datetime.now().isoformat(),
        extracted_requirements={"age_text": "35周岁以下", "education_text": "硕士及以上"},
        provenance={"channel": "social_forward"},
    )

    def fake_entity_resolver(obs, candidates):
        return EntityResolutionDecision(
            resolution="uncertain",
            target_opportunity_id="opp_401",
            rationale="岗位名称部分重合但缺少官方院系与岗位代码，证据不足暂不合并",
        )

    def fake_evaluator(profile, obs):
        now = datetime.now().isoformat()
        return EvaluationResult(
            final_recommendation="建议关注",
            dimension_evaluations={
                "Age": DimensionEvaluation("Age", "PASS", "35周岁以下", "符合年龄"),
                "Education": DimensionEvaluation("Education", "PASS", "硕士研究生", "符合学历"),
                "Formal Qualification": DimensionEvaluation("Formal Qualification", "PASS", "计算机", "符合专业"),
                "Capability Fit": DimensionEvaluation("Capability Fit", "PASS", "视觉计算", "符合胜任力"),
                "Teaching Experience": DimensionEvaluation("Teaching Experience", "PASS", "", "具备经验"),
                "Industry Experience": DimensionEvaluation("Industry Experience", "N/A", "", "不适用"),
            },
            evaluated_at=now,
        )

    def fake_intent_evaluator(profile, obs, ev):
        return OpportunityIntentDecision(
            opportunity_intent="CONDITIONAL",
            intent_rationale="存疑岗位待进一步确认，保持条件关注",
        )

    res = run_radar_pipeline(
        profile_path=mock_profile_file,
        observations_source=[uncertain_obs],
        evaluator_fn=fake_evaluator,
        intent_evaluator_fn=fake_intent_evaluator,
        entity_resolver_fn=fake_entity_resolver,
        data_dir=data_dir,
        reports_dir=reports_dir,
        run_date="2026-08-15",
    )

    assert res["success"] is True
    assert res["total_in_store"] == 2
    assert res["new_opportunities_count"] == 1

    saved_opps = store.load_all_opportunities()
    opp_map = {o.opportunity_id: o for o in saved_opps}

    new_opp = opp_map["opp_obs_402_snippet"]
    prior_opp_in_store = opp_map["opp_401"]

    assert "opp_401" in new_opp.uncertain_links
    assert "opp_obs_402_snippet" in prior_opp_in_store.uncertain_links

    # Eligibility recommendation remains independent
    assert new_opp.latest_evaluation.final_recommendation == "建议关注"

    report_content = Path(res["report_path"]).read_text(encoding="utf-8")
    assert "实体同一性待确认" in report_content
    assert "opp_401" in report_content
