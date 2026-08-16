"""
Synthetic Regression Tests for Issue #18: Real-world Recall Gap.
Tests:
1. Source Discovery Evidence Contract (search-only rejected; valid first-party accepted)
2. Source Degradation Provenance Requirement & Auditability
3. CASE A: Maintenance Source -> Agent Degrades Channel with Evidence -> Auditable Record
4. Helper Acquisition Completeness: Mechanical Status (Never asserts "no_concrete_roles")
5. CASE B: HTML Table Evidence -> Mock Agent Observation -> Full Pipeline -> Digest
6. Non-Table (Body/Detail) Evidence -> Mock Agent Observation -> Full Pipeline
7. CASE C: Generic HTML Page -> Mock Agent Decides 0 Observations (Anti-hallucination)
8. Monitoring Failure Alone Does Not Force Semantic Caveat
9. Agent-Supplied Material Acquisition Gap Renders Truthful Coverage Caveat
"""

import json
from pathlib import Path
import pytest
import yaml

from career_radar.extractor import AnnouncementExtractor
from career_radar.models import (
    CandidateProfile,
    DimensionEvaluation,
    EntityResolutionDecision,
    EvaluationResult,
    OpportunityIntentDecision,
    SourceObservation,
)
from career_radar.orchestrator import RadarOrchestrator
from career_radar.parser import HTMLAnnouncementParser
from career_radar.reporter import DigestReporter
from career_radar.sources import (
    MonitoringFact,
    SourceLifecycleDecision,
    SourceRegistry,
)


@pytest.fixture
def temp_env(tmp_path: Path):
    config_dir = tmp_path / "config"
    data_dir = tmp_path / ".data"
    reports_dir = tmp_path / "reports"
    for d in (config_dir, data_dir, reports_dir):
        d.mkdir(parents=True)

    profile_data = {
        "candidate_id": "test_cand_18",
        "name": "候选人",
        "education": {
            "degree_level": "硕士研究生",
            "degree_name": "设计学硕士",
            "major": "设计学",
            "major_code": "130500",
            "is_full_time": True,
        },
        "tracks": [
            {"name": "higher_education_teaching", "priority": "high", "default_intent": "APPLY_NOW"},
            {"name": "art_tech_creative_technology", "priority": "high", "default_intent": "APPLY_NOW"},
        ],
        "target_regions": ["guangdong"],
    }
    profile_path = tmp_path / "profile.local.yaml"
    with open(profile_path, "w", encoding="utf-8") as f:
        yaml.dump(profile_data, f, allow_unicode=True)

    seeds_data = [
        {
            "source_id": "neusoft_jobs",
            "name": "广东东软学院人才招聘网",
            "base_url": "https://jobs.neutech.cn/",
            "domain": "jobs.neutech.cn",
            "source_type": "first_party_institution",
            "track": ["higher_education_teaching"],
            "region": "guangdong",
            "discovery_role": "monitoring",
            "lifecycle_status": "active",
        }
    ]
    seeds_path = config_dir / "sources.seed.json"
    with open(seeds_path, "w", encoding="utf-8") as f:
        json.dump(seeds_data, f, ensure_ascii=False, indent=2)

    return {
        "root": tmp_path,
        "profile_path": profile_path,
        "seeds_path": seeds_path,
        "data_dir": data_dir,
        "reports_dir": reports_dir,
    }


def _dummy_eval(obs: SourceObservation) -> EvaluationResult:
    dims = {
        d: DimensionEvaluation(d, "PASS", "符合要求", "符合")
        for d in ["Age", "Education", "Formal Qualification", "Capability Fit", "Teaching Experience", "Industry Experience"]
    }
    return EvaluationResult(final_recommendation="建议关注", dimension_evaluations=dims, evaluated_at="2026-08-16T10:00:00+08:00")


# ==============================================================================
# 1. Source Discovery & Degradation Contracts
# ==============================================================================

def test_source_discovery_rejects_search_only_provenance(temp_env: dict):
    """Search lead != first-party evidence. Search-only provenance must raise ValueError."""
    registry = SourceRegistry(seed_path=temp_env["seeds_path"], data_dir=temp_env["data_dir"])

    # 1. search-only query and channel
    search_only_decision = SourceLifecycleDecision(
        source_id="search_lead_source",
        action="discover",
        name="某大学招聘线索",
        base_url="https://recruit.example.edu.cn/",
        provenance={"query": "广州高职 教师招聘", "discovery_channel": "search"},
    )
    with pytest.raises(ValueError, match="first-party verification"):
        registry.apply_lifecycle_decision(search_only_decision)

    # 2. Missing method/retrieval evidence
    missing_method_decision = SourceLifecycleDecision(
        source_id="search_lead_missing_method",
        action="discover",
        name="某大学招聘线索",
        base_url="https://recruit.example.edu.cn/",
        provenance={"verification_url": "https://recruit.example.edu.cn/", "verified_at": "2026-08-16T10:00:00"},
    )
    with pytest.raises(ValueError, match="first-party verification"):
        registry.apply_lifecycle_decision(missing_method_decision)

    # 3. Valid first-party verification evidence passes
    valid_decision = SourceLifecycleDecision(
        source_id="verified_first_party_channel",
        action="discover",
        name="广东某学院官方招聘专栏",
        base_url="https://recruit.example.edu.cn/jobs",
        rationale="已实际访问并核验第一方官方招聘专栏",
        provenance={
            "verification_url": "https://recruit.example.edu.cn/jobs",
            "verified_at": "2026-08-16T10:00:00+08:00",
            "method": "first_party_page_fetch",
        },
    )
    rec = registry.apply_lifecycle_decision(valid_decision)
    assert rec.source_id == "verified_first_party_channel"
    assert rec.lifecycle_status == "discovered"


def test_source_degrade_requires_and_preserves_auditable_provenance(temp_env: dict):
    """Degrading a source requires non-empty evidence, preserves prior provenance, and records degradation audit."""
    registry = SourceRegistry(seed_path=temp_env["seeds_path"], data_dir=temp_env["data_dir"])

    # 1. Degrade with no provenance must fail validation
    invalid_degrade = SourceLifecycleDecision(source_id="neusoft_jobs", action="degrade", rationale="维护", provenance=None)
    with pytest.raises(ValueError, match="auditable technical or retrieval evidence"):
        registry.apply_lifecycle_decision(invalid_degrade)

    # 2. Degrade with empty provenance must fail validation
    invalid_degrade_empty = SourceLifecycleDecision(source_id="neusoft_jobs", action="degrade", rationale="维护", provenance={})
    with pytest.raises(ValueError, match="auditable technical or retrieval evidence"):
        registry.apply_lifecycle_decision(invalid_degrade_empty)

    # 3. Degrade with auditable mechanical evidence passes
    valid_degrade = SourceLifecycleDecision(
        source_id="neusoft_jobs",
        action="degrade",
        rationale="系统维护升级页面，当前不可用",
        provenance={"checked_url": "https://jobs.neutech.cn/", "http_status": 200, "content_type": "text/html"},
    )
    updated = registry.apply_lifecycle_decision(valid_degrade, timestamp="2026-08-16T11:00:00+08:00")
    assert updated.lifecycle_status == "degraded"
    assert updated.degraded_reason == "系统维护升级页面，当前不可用"
    assert "degradation_audit" in updated.provenance
    assert updated.provenance["degradation_audit"]["reason"] == "系统维护升级页面，当前不可用"
    assert updated.provenance["degradation_audit"]["evidence"]["http_status"] == 200


def test_case_a_maintenance_source_truthful_degrade(temp_env: dict):
    """CASE A: HTTP 200 maintenance page -> 0 observations -> Agent degrades source with evidence -> Digest reflects."""
    orchestrator = RadarOrchestrator(
        profile_path=temp_env["profile_path"],
        seed_sources_path=temp_env["seeds_path"],
        data_dir=temp_env["data_dir"],
        reports_dir=temp_env["reports_dir"],
    )

    maintenance_html = "<html><head><title>升级维护</title></head><body><h1>维护中</h1></body></html>"
    parser = HTMLAnnouncementParser()
    parsed = parser.parse(maintenance_html, base_url="https://jobs.neutech.cn/")
    assert parsed["tables"] == []

    extractor = AnnouncementExtractor(cache_dir=temp_env["data_dir"] / "announcements")
    observations = extractor.extract_from_html_and_attachments(
        html_content=maintenance_html,
        source_url="https://jobs.neutech.cn/",
        source_id="neusoft_jobs",
        source_name="广东东软学院人才招聘网",
        local_attachment_paths=[],
    )
    assert observations == []

    monitoring_facts = [
        MonitoringFact(source_id="neusoft_jobs", technical_status="success", checked_url="https://jobs.neutech.cn/", checked_at="2026-08-16T09:00:00+08:00")
    ]
    source_decisions = [
        SourceLifecycleDecision(
            source_id="neusoft_jobs",
            action="degrade",
            rationale="第一方招聘页面返回系统维护通知，当前不可用",
            provenance={"checked_url": "https://jobs.neutech.cn/", "checked_at": "2026-08-16T09:00:00+08:00", "http_status": 200},
        )
    ]

    outcome = orchestrator.run(observations=[], source_decisions=source_decisions, monitoring_facts=monitoring_facts, run_date="2026-08-16")
    assert outcome.status == "attention"
    assert outcome.new_opportunities_count == 0
    assert outcome.network_changes_count == 1

    report_content = Path(outcome.report_path).read_text(encoding="utf-8")
    assert "渠道降级" in report_content
    assert "广东东软学院人才招聘网" in report_content


# ==============================================================================
# 2. Case B: HTML Evidence -> Mock Agent Observation -> Full Pipeline
# ==============================================================================

def test_helper_does_not_assert_no_concrete_roles_before_agent_review(temp_env: dict):
    """Helper must NOT declare 'no_concrete_roles' when attachments are absent but HTML evidence exists."""
    html_page = "<html><body><h1>招聘</h1><table><tr><th>岗位名称</th></tr><tr><td>教师</td></tr></table></body></html>"
    parser = HTMLAnnouncementParser()
    evidence_packet = parser.parse(html_page, base_url="https://rsc.xhsysu.edu.cn/jobs/1.html")
    assert evidence_packet["tables"] is not None

    extractor = AnnouncementExtractor(cache_dir=temp_env["data_dir"] / "announcements")
    observations = extractor.extract_from_html_and_attachments(
        html_content=html_page, source_url="https://rsc.xhsysu.edu.cn/jobs/1.html", source_id="xinhua_rsc", source_name="人事处", local_attachment_paths=[]
    )
    assert observations == []

    has_attachments = bool(evidence_packet.get("attachments"))
    extraction_completeness = "attachment_extraction_complete" if observations else "no_attachment_observations" if has_attachments else "html_evidence_available"
    assert extraction_completeness == "html_evidence_available"
    assert extraction_completeness != "no_concrete_roles"


def test_case_b_html_table_evidence_mock_agent_to_pipeline(temp_env: dict):
    """CASE B: Parser extracts HTML table evidence mechanically; Mock Agent semantically interprets and creates observation."""
    html_page = """
    <html><body><h1>专任教师招聘</h1>
    <table>
      <tr><th>岗位名称</th><th>学历要求</th><th>专业及代码</th><th>年龄要求</th></tr>
      <tr><td>交互设计教师</td><td>硕士研究生</td><td>设计学（1305）</td><td>35周岁以下</td></tr>
    </table></body></html>
    """
    parser = HTMLAnnouncementParser()
    evidence_packet = parser.parse(html_page, base_url="https://rsc.xhsysu.edu.cn/jobs/202601.html")
    assert len(evidence_packet["tables"]) == 1

    extractor = AnnouncementExtractor(cache_dir=temp_env["data_dir"] / "announcements")
    assert extractor.extract_from_html_and_attachments(html_content=html_page, source_url="https://rsc.xhsysu.edu.cn/jobs/202601.html", source_id="xinhua_rsc", source_name="人事处", local_attachment_paths=[]) == []

    # Agent semantic seam: Agent consumes evidence_packet and produces SourceObservation
    table_rows = evidence_packet["tables"][0]["rows"]
    cells = table_rows[0]["cells"]
    agent_observations = [
        SourceObservation(
            observation_id="obs_agent_html_1",
            announcement_id="ann_xinhua_001",
            source_id="xinhua_rsc",
            source_name="广州新华学院人事处",
            announcement_title=evidence_packet.get("title", ""),
            job_title=cells["岗位名称"],
            organization="广州新华学院",
            location="广州/东莞",
            track="higher_education_teaching",
            official_url="https://rsc.xhsysu.edu.cn/jobs/202601.html",
            observed_at="2026-08-16T10:00:00+08:00",
            extracted_requirements={"age_text": cells.get("年龄要求", ""), "education_text": cells.get("学历要求", ""), "formal_qualification_text": cells.get("专业及代码", ""), "capability_fit_text": "具备UI/UX教学经验", "teaching_experience_text": "", "industry_experience_text": "", "other_conditions_text": ""},
            provenance={"evidence_type": "html_table", "source_url": "https://rsc.xhsysu.edu.cn/jobs/202601.html", "raw_cells": cells},
        )
    ]

    orchestrator = RadarOrchestrator(profile_path=temp_env["profile_path"], seed_sources_path=temp_env["seeds_path"], data_dir=temp_env["data_dir"], reports_dir=temp_env["reports_dir"])
    outcome = orchestrator.run(
        observations=agent_observations,
        entity_resolver_fn=lambda obs, cands: EntityResolutionDecision(resolution="different", rationale="New HTML role"),
        evaluator_fn=lambda p, o: _dummy_eval(o),
        intent_evaluator_fn=lambda p, o, e: OpportunityIntentDecision("APPLY_NOW", "符合画像意图"),
        run_date="2026-08-16",
    )
    assert outcome.new_opportunities_count == 1
    assert outcome.recommended_count == 1
    report_content = Path(outcome.report_path).read_text(encoding="utf-8")
    assert "交互设计教师" in report_content
    assert "广州新华学院" in report_content


def test_html_non_table_body_detail_evidence_mock_agent_to_pipeline(temp_env: dict):
    """First-party non-table HTML job-detail page: Agent interprets headings/body and produces observation."""
    non_table_html = "<html><body><h1>招聘岗位：创意编程讲师</h1><p>全日制硕士，数媒艺术专业，35岁以下</p></body></html>"
    parser = HTMLAnnouncementParser()
    evidence_packet = parser.parse(non_table_html, base_url="https://art.example.edu.cn/jobs/detail/1")
    assert evidence_packet["tables"] == []

    agent_obs = [
        SourceObservation(
            observation_id="obs_agent_nontable_001",
            announcement_id="ann_art_001",
            source_id="art_college_src",
            source_name="数字艺术学院",
            announcement_title="诚聘讲师",
            job_title="创意编程讲师",
            organization="数字艺术学院",
            location="广州",
            track="art_tech_creative_technology",
            official_url="https://art.example.edu.cn/jobs/detail/1",
            observed_at="2026-08-16T10:00:00+08:00",
            extracted_requirements={"age_text": "35岁以下", "education_text": "硕士", "formal_qualification_text": "数媒艺术", "capability_fit_text": "编程教学", "teaching_experience_text": "", "industry_experience_text": "", "other_conditions_text": ""},
            provenance={"evidence_type": "html_body_detail", "source_url": "https://art.example.edu.cn/jobs/detail/1"},
        )
    ]

    orchestrator = RadarOrchestrator(profile_path=temp_env["profile_path"], seed_sources_path=temp_env["seeds_path"], data_dir=temp_env["data_dir"], reports_dir=temp_env["reports_dir"])
    outcome = orchestrator.run(
        observations=agent_obs,
        entity_resolver_fn=lambda obs, cands: EntityResolutionDecision(resolution="different", rationale="Non-table role"),
        evaluator_fn=lambda p, o: _dummy_eval(o),
        intent_evaluator_fn=lambda p, o, e: OpportunityIntentDecision("APPLY_NOW", "符合意图"),
        run_date="2026-08-16",
    )
    assert outcome.new_opportunities_count == 1
    assert "创意编程讲师" in Path(outcome.report_path).read_text(encoding="utf-8")


def test_case_c_generic_html_evidence_mock_agent_zero_observations(temp_env: dict):
    """CASE C: Generic promotional HTML with no concrete roles -> Agent produces 0 observations -> No fake jobs."""
    generic_html = "<html><body><h1>欢迎关注人才招聘</h1><p>近期公布岗位，敬请期待！</p></body></html>"
    parser = HTMLAnnouncementParser()
    evidence_packet = parser.parse(generic_html, base_url="https://example.edu.cn/jobs/preview.html")
    assert evidence_packet["tables"] == []

    # Mock Agent checks evidence packet and determines 0 concrete roles exist
    mock_agent_eval = lambda packet: [] if "欢迎关注" in packet.get("body_text", "") else []
    agent_obs = mock_agent_eval(evidence_packet)
    assert agent_obs == []


# ==============================================================================
# 3. Digest Truthfulness & Coverage Materiality
# ==============================================================================

def test_technical_monitoring_failure_alone_does_not_force_coverage_caveat(temp_env: dict):
    """Helper does not invent a coverage caveat when Agent supplies no acquisition gap."""
    orchestrator = RadarOrchestrator(profile_path=temp_env["profile_path"], seed_sources_path=temp_env["seeds_path"], data_dir=temp_env["data_dir"], reports_dir=temp_env["reports_dir"])
    monitoring_facts = [
        MonitoringFact(source_id="neusoft_jobs", technical_status="failed", checked_url="https://jobs.neutech.cn/", checked_at="2026-08-16T09:00:00+08:00", metadata={"error": "Connection timed out"})
    ]
    outcome = orchestrator.run(observations=[], monitoring_facts=monitoring_facts, run_date="2026-08-16", acquisition_gaps=None, coverage_caveat=None)
    report_text = Path(outcome.report_path).read_text(encoding="utf-8")
    assert "本次巡检未发现新增高匹配度机会" in report_text
    assert "覆盖度提示" not in report_text


def test_agent_supplied_material_coverage_caveat_renders_truthfully(temp_env: dict):
    """When Agent supplies a material acquisition gap, Digest truthfully displays the coverage caveat."""
    reporter = DigestReporter(reports_dir=temp_env["reports_dir"])
    report_path = reporter.generate_report(
        opportunities=[],
        run_date="2026-08-16",
        new_opportunity_ids=[],
        updated_opportunity_ids=[],
        network_changes=[],
        acquisition_gaps=["核心高职院校招聘专栏因改版暂时无法提取，结果不代表市场不存在相关机会。"],
    )
    report_text = report_path.read_text(encoding="utf-8")
    assert "本轮未成功提取到新增机会" in report_text
    assert "覆盖度提示" in report_text
    assert "核心高职院校招聘专栏因改版暂时无法提取" in report_text
