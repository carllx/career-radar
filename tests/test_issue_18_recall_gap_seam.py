"""
Synthetic Regression Tests for Issue #18: Real-world Recall Gap.
Tests:
1. CASE A: Unverified / Maintenance Source (HTTP 200 + Maintenance HTML -> Degrade / Contract rejection)
2. CASE B: First-party HTML / ATS Concrete Roles (HTML table -> SourceObservation -> Pipeline -> Digest)
3. CASE C: Generic HTML Page Without Concrete Role (0 SourceObservations, Anti-hallucination invariant)
4. Source Discovery Evidence Contract (discover without first-party verification fails validation)
5. Digest Coverage Truthfulness (materially incomplete acquisition caveat vs clean normal run)
"""

import json
from pathlib import Path
import pytest
import yaml

from career_radar.extractor import (
    AnnouncementExtractor,
    fetch_and_extract_first_party_announcement,
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
from career_radar.orchestrator import RadarOrchestrator, RadarRunOutcome
from career_radar.parser import HTMLAnnouncementParser
from career_radar.reporter import DigestReporter
from career_radar.runner import IncrementalResolutionSession, run_radar_pipeline
from career_radar.sources import (
    MonitoringFact,
    SourceLifecycleDecision,
    SourceRecord,
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


# ==============================================================================
# 1. Source Discovery Evidence Contract & Case A (Maintenance / Degradation)
# ==============================================================================

def test_source_discovery_requires_provenance_verification_evidence(temp_env: dict):
    """
    Contract test: Agent decision to 'discover' a new source MUST bear
    first-party verification evidence in provenance. Missing evidence must raise ValueError.
    """
    registry = SourceRegistry(seed_path=temp_env["seeds_path"], data_dir=temp_env["data_dir"])

    # Decision without provenance
    invalid_decision_1 = SourceLifecycleDecision(
        source_id="unverified_search_lead",
        action="discover",
        name="某大学招聘搜索线索",
        base_url="https://recruit.example.edu.cn/",
        provenance=None,
    )
    with pytest.raises(ValueError, match="provenance"):
        registry.apply_lifecycle_decision(invalid_decision_1)

    # Decision with empty provenance
    invalid_decision_2 = SourceLifecycleDecision(
        source_id="unverified_search_lead_empty",
        action="discover",
        name="某大学招聘搜索线索",
        base_url="https://recruit.example.edu.cn/",
        provenance={},
    )
    with pytest.raises(ValueError, match="provenance"):
        registry.apply_lifecycle_decision(invalid_decision_2)

    # Valid decision with first-party verification evidence in provenance
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


def test_case_a_maintenance_source_truthful_degrade(temp_env: dict):
    """
    CASE A Test:
    A source returning HTTP 200 with maintenance/unusable content:
    - Does NOT generate fake opportunities
    - Agent can issue 'degrade' decision
    - Registry updates lifecycle_status to 'degraded' with auditable rationale
    - Orchestrator reflects network changes in report and summary
    """
    orchestrator = RadarOrchestrator(
        profile_path=temp_env["profile_path"],
        seed_sources_path=temp_env["seeds_path"],
        data_dir=temp_env["data_dir"],
        reports_dir=temp_env["reports_dir"],
    )

    # HTML content is a maintenance page (HTTP 200)
    maintenance_html = """
    <!DOCTYPE html>
    <html>
      <head><title>系统升级维护公告</title></head>
      <body>
        <div class="maintenance-box">
          <h1>网站升级中</h1>
          <p>广东东软学院人才招聘系统正在进行服务器维护与升级，请稍后访问。</p>
        </div>
      </body>
    </html>
    """

    # Parser & Extractor verify 0 observations produced from maintenance page
    extractor = AnnouncementExtractor(cache_dir=temp_env["data_dir"] / "announcements")
    observations = extractor.extract_from_html_and_attachments(
        html_content=maintenance_html,
        source_url="https://jobs.neutech.cn/",
        source_id="neusoft_jobs",
        source_name="广东东软学院人才招聘网",
        local_attachment_paths=[],
    )
    assert observations == []

    # Agent records monitoring fact and degrades the unusable source
    monitoring_facts = [
        MonitoringFact(
            source_id="neusoft_jobs",
            technical_status="success",
            checked_url="https://jobs.neutech.cn/",
            checked_at="2026-08-16T09:00:00+08:00",
        )
    ]
    source_decisions = [
        SourceLifecycleDecision(
            source_id="neusoft_jobs",
            action="degrade",
            rationale="第一方招聘页面返回系统维护通知，当前不可用",
        )
    ]

    outcome = orchestrator.run(
        observations=[],
        source_decisions=source_decisions,
        monitoring_facts=monitoring_facts,
        run_date="2026-08-16",
    )

    assert outcome.status == "attention"
    assert outcome.new_opportunities_count == 0
    assert outcome.network_changes_count == 1

    # Verify report contains degradation entry
    report_content = Path(outcome.report_path).read_text(encoding="utf-8")
    assert "渠道降级" in report_content
    assert "广东东软学院人才招聘网" in report_content
    assert "系统维护通知" in report_content


# ==============================================================================
# 2. Case B: First-Party HTML / ATS Concrete Roles Ingestion
# ==============================================================================

def test_case_b_html_table_concrete_roles_end_to_end(temp_env: dict):
    """
    CASE B Test:
    An accessible first-party HTML page containing an HTML table with concrete roles (no attachment):
    - Mechanical parser extracts HTML table structure and raw cells
    - AnnouncementExtractor generates SourceObservations with rich provenance
    - Passes through Entity Resolution, 6D Eligibility, Opportunity Intent, Persistence, and Digest
    """
    html_page = """
    <!DOCTYPE html>
    <html>
      <head><title>广州新华学院2026年专任教师招聘公告</title></head>
      <body>
        <h1>广州新华学院2026年专任教师招聘</h1>
        <p>根据学校教学发展需要，现面向社会公开招聘专任教师，岗位信息如下：</p>
        <table class="job-table" border="1">
          <thead>
            <tr>
              <th>序号</th>
              <th>用人单位</th>
              <th>岗位名称</th>
              <th>学历要求</th>
              <th>专业及代码</th>
              <th>年龄要求</th>
              <th>能力要求</th>
              <th>工作地点</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>1</td>
              <td>广州新华学院</td>
              <td>交互设计与数字媒体教师</td>
              <td>硕士研究生及以上</td>
              <td>设计学（1305）、数字媒体艺术</td>
              <td>35周岁以下</td>
              <td>具备UI/UX教学与项目实战经验</td>
              <td>广州/东莞</td>
            </tr>
            <tr>
              <td>2</td>
              <td>广州新华学院</td>
              <td>高等数学教学科研岗</td>
              <td>博士研究生</td>
              <td>基础数学（070101）</td>
              <td>28周岁以下</td>
              <td>具有高校主讲经历</td>
              <td>广州</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """

    parser = HTMLAnnouncementParser()
    parsed = parser.parse(html_page, base_url="https://rsc.xhsysu.edu.cn/jobs/202601.html")

    assert len(parsed.get("tables", [])) == 1
    table = parsed["tables"][0]
    assert table["status"] == "success"
    assert len(table["rows"]) == 2
    assert table["rows"][0]["cells"]["岗位名称"] == "交互设计与数字媒体教师"

    extractor = AnnouncementExtractor(cache_dir=temp_env["data_dir"] / "announcements")
    observations = extractor.extract_from_html_and_attachments(
        html_content=html_page,
        source_url="https://rsc.xhsysu.edu.cn/jobs/202601.html",
        source_id="xinhua_rsc",
        source_name="广州新华学院人事处",
        local_attachment_paths=[],
        recruiting_organization="广州新华学院",
    )

    assert len(observations) == 2
    obs1 = observations[0]
    assert obs1.job_title == "交互设计与数字媒体教师"
    assert obs1.organization == "广州新华学院"
    assert obs1.location == "广州/东莞"
    assert obs1.extracted_requirements["age_text"] == "35周岁以下"
    assert obs1.extracted_requirements["education_text"] == "硕士研究生及以上"
    assert obs1.provenance is not None
    assert obs1.provenance["evidence_type"] == "html_table"
    assert obs1.provenance["raw_cells"]["专业及代码"] == "设计学（1305）、数字媒体艺术"

    # Now run orchestrator through full pipeline
    orchestrator = RadarOrchestrator(
        profile_path=temp_env["profile_path"],
        seed_sources_path=temp_env["seeds_path"],
        data_dir=temp_env["data_dir"],
        reports_dir=temp_env["reports_dir"],
    )

    def mock_evaluator(prof: CandidateProfile, obs: SourceObservation) -> EvaluationResult:
        is_match = "交互设计" in obs.job_title
        return EvaluationResult(
            final_recommendation="建议关注" if is_match else "明显不符合",
            dimension_evaluations={
                "Age": DimensionEvaluation("Age", "PASS" if is_match else "FAIL", obs.extracted_requirements["age_text"], "符合"),
                "Education": DimensionEvaluation("Education", "PASS" if is_match else "FAIL", obs.extracted_requirements["education_text"], "符合"),
                "Formal Qualification": DimensionEvaluation("Formal Qualification", "PASS" if is_match else "FAIL", obs.extracted_requirements["formal_qualification_text"], "符合"),
                "Capability Fit": DimensionEvaluation("Capability Fit", "PASS" if is_match else "FAIL", obs.extracted_requirements["capability_fit_text"], "符合"),
                "Teaching Experience": DimensionEvaluation("Teaching Experience", "PASS", "", "符合"),
                "Industry Experience": DimensionEvaluation("Industry Experience", "PASS", "", "符合"),
            },
            evaluated_at="2026-08-16T10:00:00+08:00",
        )

    def mock_intent(prof: CandidateProfile, obs: SourceObservation, ev: EvaluationResult) -> OpportunityIntentDecision:
        return OpportunityIntentDecision(
            opportunity_intent="APPLY_NOW" if ev.final_recommendation == "建议关注" else "WATCH_LEARN",
            intent_rationale="Case B HTML role intent",
        )

    outcome = orchestrator.run(
        observations=observations,
        entity_resolver_fn=lambda obs, cands: EntityResolutionDecision(resolution="different", rationale="Different role in same table"),
        evaluator_fn=mock_evaluator,
        intent_evaluator_fn=mock_intent,
        market_intelligence_evaluator_fn=lambda prof, obs, ev, it: MarketIntelligence(
            brief=f"{obs.organization} {obs.job_title} 市场事实",
            deliverables="工作合同",
            content_type="专任教师",
            timeline_volume="全职",
            revision_quality_rules="高校考核",
            requested_tools_workflow="高校教学科研",
            budget_compensation="学校标准待遇",
            use_case="教学科研",
        ),
        run_date="2026-08-16",
    )

    assert outcome.new_opportunities_count == 2
    assert outcome.recommended_count == 1
    assert outcome.apply_now_count == 1

    report_content = Path(outcome.report_path).read_text(encoding="utf-8")
    assert "交互设计与数字媒体教师" in report_content
    assert "广州新华学院" in report_content
    assert "https://rsc.xhsysu.edu.cn/jobs/202601.html" in report_content


# ==============================================================================
# 3. Case C: Generic HTML Page Without Concrete Roles (Anti-Hallucination)
# ==============================================================================

def test_case_c_generic_html_page_zero_observations(temp_env: dict):
    """
    CASE C Test:
    First-party HTML page contains only generic marketing / contact info ("欢迎关注"):
    - Extractor MUST produce exactly 0 SourceObservation
    - MUST NOT fabricate a fake Opportunity from the page title
    """
    generic_html = """
    <!DOCTYPE html>
    <html>
      <head><title>广东某民办学院2026年高层次人才招聘预告</title></head>
      <body>
        <h1>广东某民办学院2026年高层次人才招聘预告</h1>
        <p>欢迎广大优秀学者关注我校人才招聘工作，具体岗位与招聘条件近期将在本网站公布，敬请期待！</p>
        <p>联系电话：020-12345678</p>
      </body>
    </html>
    """

    parser = HTMLAnnouncementParser()
    parsed = parser.parse(generic_html, base_url="https://example.edu.cn/jobs/preview.html")

    assert parsed["title"] == "广东某民办学院2026年高层次人才招聘预告"
    assert parsed.get("tables", []) == []

    extractor = AnnouncementExtractor(cache_dir=temp_env["data_dir"] / "announcements")
    observations = extractor.extract_from_html_and_attachments(
        html_content=generic_html,
        source_url="https://example.edu.cn/jobs/preview.html",
        source_id="generic_preview_source",
        source_name="某学院招聘预告",
        local_attachment_paths=[],
    )

    assert observations == []


# ==============================================================================
# 4. Digest Coverage Truthfulness
# ==============================================================================

def test_digest_coverage_truthfulness_on_acquisition_gaps(temp_env: dict):
    """
    Digest Truthfulness Test:
    - Normal run with complete acquisition & 0 opps -> '本次巡检未发现新增高匹配度机会。\n'
    - Run with acquisition gaps / caveats & 0 opps -> Displays truthful coverage caveat
    """
    reporter = DigestReporter(reports_dir=temp_env["reports_dir"])

    # 1. Normal clean run with 0 opportunities
    clean_report_path = reporter.generate_report(
        opportunities=[],
        run_date="2026-08-16",
        new_opportunity_ids=[],
        updated_opportunity_ids=[],
        network_changes=[],
    )
    clean_text = clean_report_path.read_text(encoding="utf-8")
    assert "本次巡检未发现新增高匹配度机会" in clean_text
    assert "覆盖度提示" not in clean_text

    # 2. Run with acquisition gaps / degraded sources
    gaps_report_path = reporter.generate_report(
        opportunities=[],
        run_date="2026-08-17",
        new_opportunity_ids=[],
        updated_opportunity_ids=[],
        network_changes=[{"type": "degraded", "name": "某不可用渠道", "base_url": "https://degraded.com", "reason": "系统维护"}],
        acquisition_gaps=["部分渠道本轮不可访问或存在尚未完成解析的第一方页面，结果不代表市场不存在相关机会。"],
    )
    gaps_text = gaps_report_path.read_text(encoding="utf-8")
    assert "本轮未成功提取到新增机会" in gaps_text
    assert "覆盖度提示" in gaps_text
    assert "不代表市场不存在相关机会" in gaps_text
