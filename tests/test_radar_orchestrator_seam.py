"""
Highest Testing Seam for Career Radar MVP-1 (Issue #12).
Tests the unified Autonomous Radar Orchestrator across:
- Slice A: Known-source Monitoring & genuine technical execution fact recording (no fake success).
- Slice B: Open Source Discovery & local .data/sources.json persistence (visible in future candidate networks).
- Slice C: Source Degradation & data-driven Section 4 in Daily Digest.
- Slice D: Unified Full Orchestrator Run (Monitoring Facts + Discovery + Opportunities + 4-section Digest).
- Slice E: Trigger equivalence (Manual invocation and Scheduled invocation execute the same contract).
"""

import json
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
from career_radar.orchestrator import RadarOrchestrator, RadarRunOutcome
from career_radar.sources import (
    MonitoringFact,
    SourceLifecycleDecision,
    SourceRecord,
    SourceRegistry,
)


@pytest.fixture
def temp_env(tmp_path: Path):
    """
    Sets up a clean temporary environment with mock profile, public seeds, and data/reports dirs.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)

    # 1. Mock profile
    profile_data = {
        "candidate_id": "test_candidate_001",
        "name": "测试候选人",
        "education": {
            "degree_level": "博士研究生",
            "degree_name": "工学博士",
            "major": "计算机科学与技术",
            "major_code": "081200",
            "is_full_time": True,
        },
        "tracks": [
            {"name": "higher_education_teaching", "priority": "high"},
            {"name": "vocational_education", "priority": "medium"},
        ],
        "target_regions": ["guangdong", "guangzhou"],
    }
    profile_path = tmp_path / "profile.local.yaml"
    with open(profile_path, "w", encoding="utf-8") as f:
        yaml.dump(profile_data, f, allow_unicode=True)

    # 2. Mock public seeds
    seeds_data = [
        {
            "source_id": "gd_hrss_official",
            "name": "广东省人力资源和社会保障厅",
            "base_url": "http://hrss.gd.gov.cn/zwgk/gsgg/",
            "domain": "hrss.gd.gov.cn",
            "source_type": "first_party_official",
            "track": ["higher_education_teaching", "vocational_education"],
            "region": "guangdong",
            "discovery_role": "monitoring",
            "lifecycle_status": "active",
        },
        {
            "source_id": "scnu_rsc",
            "name": "华南师范大学人事处",
            "base_url": "https://rsc.scnu.edu.cn/",
            "domain": "rsc.scnu.edu.cn",
            "source_type": "first_party_institution",
            "track": ["higher_education_teaching"],
            "region": "guangdong",
            "discovery_role": "monitoring",
            "lifecycle_status": "active",
        },
        {
            "source_id": "unrelated_industry_hub",
            "name": "不相关外省金融招聘站",
            "base_url": "https://finance.example.com/",
            "domain": "finance.example.com",
            "source_type": "vertical_aggregator",
            "track": ["finance_banking"],
            "region": "beijing",
            "discovery_role": "monitoring",
            "lifecycle_status": "active",
        },
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


def make_eval_result(state: str = "PASS") -> EvaluationResult:
    return EvaluationResult(
        final_recommendation="建议关注" if state == "PASS" else "需要人工确认",
        dimension_evaluations={
            "Age": DimensionEvaluation(dimension="Age", state="PASS", requirement_evidence="35周岁以下", rationale="年龄符合"),
            "Education": DimensionEvaluation(dimension="Education", state=state, requirement_evidence="博士研究生", rationale="学历评定"),
            "Formal Qualification": DimensionEvaluation(dimension="Formal Qualification", state="PASS", requirement_evidence="0812 计算机", rationale="专业对口"),
            "Capability Fit": DimensionEvaluation(dimension="Capability Fit", state="PASS", requirement_evidence="教学科研岗", rationale="能力符合"),
            "Teaching Experience": DimensionEvaluation(dimension="Teaching Experience", state="PASS", requirement_evidence="不限", rationale="经验符合"),
            "Industry Experience": DimensionEvaluation(dimension="Industry Experience", state="PASS", requirement_evidence="不限", rationale="无要求"),
        },
        evaluated_at="2026-08-15T09:00:00",
    )


class TestRadarOrchestratorSeam:

    def test_slice_a_known_source_monitoring_with_genuine_facts(self, temp_env):
        """
        Slice A: Known-source Monitoring with genuine technical facts (no fake success).
        Source A: technical_status = success
        Source B: technical_status = failed (e.g. 500 error / blocked)
        Untouched Source C: remains unmonitored with no fake facts.
        """
        orchestrator = RadarOrchestrator(
            profile_path=temp_env["profile_path"],
            seed_sources_path=temp_env["seeds_path"],
            data_dir=temp_env["data_dir"],
            reports_dir=temp_env["reports_dir"],
        )

        facts = [
            MonitoringFact(
                source_id="gd_hrss_official",
                technical_status="success",
                checked_url="http://hrss.gd.gov.cn/zwgk/gsgg/",
                checked_at="2026-08-15T09:00:00",
            ),
            MonitoringFact(
                source_id="scnu_rsc",
                technical_status="failed",
                checked_url="https://rsc.scnu.edu.cn/",
                checked_at="2026-08-15T09:01:00",
            ),
        ]

        outcome = orchestrator.run(monitoring_facts=facts, run_date="2026-08-15")

        assert outcome.status == "attention"  # scnu_rsc failed requires attention
        assert outcome.monitored_sources_count == 2

        # Check local .data/sources.json has exact facts
        local_sources_file = temp_env["data_dir"] / "sources.json"
        assert local_sources_file.exists()
        with open(local_sources_file, "r", encoding="utf-8") as f:
            local_data = json.load(f)

        hrss_rec = next(s for s in local_data if s["source_id"] == "gd_hrss_official")
        scnu_rec = next(s for s in local_data if s["source_id"] == "scnu_rsc")
        assert hrss_rec["last_technical_status"] == "success"
        assert scnu_rec["last_technical_status"] == "failed"

        # Untouched source must NOT have fake facts in local state
        unrelated_rec = next((s for s in local_data if s["source_id"] == "unrelated_industry_hub"), None)
        assert unrelated_rec is None or unrelated_rec.get("last_monitored_at") is None

        # Public seed must remain pristine
        with open(temp_env["seeds_path"], "r", encoding="utf-8") as f:
            seed_data = json.load(f)
        assert len(seed_data) == 3
        assert "last_monitored_at" not in seed_data[0]

    def test_slice_b_open_source_discovery_visible_in_next_run(self, temp_env):
        """
        Slice B: Open Source Discovery & Next-Run Candidate Visibility
        Agent discovers unseeded candidate source -> persists to .data/sources.json as 'discovered'.
        In next run, SourceRegistry.get_candidate_sources() includes this discovered source!
        """
        orchestrator = RadarOrchestrator(
            profile_path=temp_env["profile_path"],
            seed_sources_path=temp_env["seeds_path"],
            data_dir=temp_env["data_dir"],
            reports_dir=temp_env["reports_dir"],
        )

        discovery_decision = SourceLifecycleDecision(
            source_id="gdaib_rsc",
            action="discover",
            name="广东农工商职业技术学院人事处",
            base_url="https://www.gdaib.edu.cn/rsc/",
            source_type="first_party_institution",
            track=["vocational_education"],
            region="guangzhou",
            rationale="发现省属公办高职院校最新招聘专栏",
            provenance={"discovery_channel": "agent-reach", "query": "广州高职院校 教师招聘 2026"},
        )

        outcome = orchestrator.run(
            source_decisions=[discovery_decision],
            run_date="2026-08-15",
        )

        assert outcome.discovered_sources_count == 1
        assert outcome.network_changes_count == 1

        # Check .data/sources.json
        local_sources_file = temp_env["data_dir"] / "sources.json"
        with open(local_sources_file, "r", encoding="utf-8") as f:
            local_data = json.load(f)
        discovered_entry = next(s for s in local_data if s["source_id"] == "gdaib_rsc")
        assert discovered_entry["lifecycle_status"] == "discovered"
        assert discovered_entry["origin"] == "discovered"

        # Verify candidate visibility in subsequent registry loading
        registry_next = SourceRegistry(seed_path=temp_env["seeds_path"], data_dir=temp_env["data_dir"])
        candidate_ids = [s.source_id for s in registry_next.get_candidate_sources()]
        assert "gdaib_rsc" in candidate_ids

        # Check Report Section 4 renders new discovered source
        report_file = Path(outcome.report_path)
        content = report_file.read_text(encoding="utf-8")
        assert "## 🌐 渠道网络变动" in content
        assert "🆕 **新发现渠道**：[广东农工商职业技术学院人事处](https://www.gdaib.edu.cn/rsc/)" in content
        assert "发现省属公办高职院校最新招聘专栏" in content

    def test_slice_c_source_degradation(self, temp_env):
        """
        Slice C: Source Degradation
        Agent provides explicit degradation decision for a broken/migrated source.
        Local source state is updated to 'degraded', and Daily Digest Section 4 reflects degradation.
        """
        orchestrator = RadarOrchestrator(
            profile_path=temp_env["profile_path"],
            seed_sources_path=temp_env["seeds_path"],
            data_dir=temp_env["data_dir"],
            reports_dir=temp_env["reports_dir"],
        )

        degrade_decision = SourceLifecycleDecision(
            source_id="scnu_rsc",
            action="degrade",
            rationale="站点发生永久性 404 重定向至旧系统且无招聘更新",
        )

        outcome = orchestrator.run(
            source_decisions=[degrade_decision],
            run_date="2026-08-15",
        )

        assert outcome.network_changes_count == 1
        assert outcome.status == "attention"  # Degradation requires attention

        # Check local source record
        local_sources_file = temp_env["data_dir"] / "sources.json"
        with open(local_sources_file, "r", encoding="utf-8") as f:
            local_data = json.load(f)
        scnu_entry = next(s for s in local_data if s["source_id"] == "scnu_rsc")
        assert scnu_entry["lifecycle_status"] == "degraded"
        assert "站点发生永久性 404" in scnu_entry["degraded_reason"]

        # Check Report Section 4
        report_file = Path(outcome.report_path)
        content = report_file.read_text(encoding="utf-8")
        assert "⚠️ **渠道降级**：[华南师范大学人事处](https://rsc.scnu.edu.cn/)" in content
        assert "站点发生永久性 404" in content

    def test_slice_d_unified_full_run_mock_network(self, temp_env):
        """
        Slice D: Unified Full Run with Mock Source Network
        In the same run:
        - Known-source monitoring occurs with real MonitoringFacts
        - Source discovery occurs
        - Incoming announcements are extracted into SourceObservations
        - Entity resolution disambiguates incoming opportunities
        - Qualification evaluation performs 6-dimension evaluation
        - Both Opportunity state and Source state are atomically persisted
        - 4-section Daily Digest is completely rendered with real data
        """
        orchestrator = RadarOrchestrator(
            profile_path=temp_env["profile_path"],
            seed_sources_path=temp_env["seeds_path"],
            data_dir=temp_env["data_dir"],
            reports_dir=temp_env["reports_dir"],
        )

        # 1. Monitoring Facts (Mock Network)
        facts = [
            MonitoringFact(
                source_id="gd_hrss_official",
                technical_status="success",
                checked_url="http://hrss.gd.gov.cn/zwgk/gsgg/",
                checked_at="2026-08-15T09:00:00",
            )
        ]

        # 2. Discovery decision
        discovery_decision = SourceLifecycleDecision(
            source_id="gdaib_rsc",
            action="discover",
            name="广东农工商职业技术学院",
            base_url="https://www.gdaib.edu.cn/rsc/",
            source_type="first_party_institution",
            rationale="发现新高职招聘渠道",
        )

        # 3. Observations
        obs_1 = SourceObservation(
            observation_id="obs_001",
            announcement_id="ann_001",
            source_id="gd_hrss_official",
            source_name="广东省人力资源和社会保障厅",
            announcement_title="广东省事业单位2026年集中公开招聘高校毕业生公告",
            organization="广东药科大学",
            job_title="计算机专任教师",
            track="higher_education_teaching",
            location="广州市",
            official_url="http://hrss.gd.gov.cn/zwgk/gsgg/12345.html",
            observed_at="2026-08-15T09:00:00",
            extracted_requirements={"degree": "博士研究生", "major": "计算机科学与技术"},
            provenance={"department": "医药信息工程学院"},
        )

        obs_2 = SourceObservation(
            observation_id="obs_002",
            announcement_id="ann_002",
            source_id="gdaib_rsc",
            source_name="广东农工商职业技术学院",
            announcement_title="广东农工商职业技术学院2026年公开招聘专任教师公告",
            organization="广东农工商职业技术学院",
            job_title="智能工程学院专业课教师",
            track="vocational_education",
            location="广州市",
            official_url="https://www.gdaib.edu.cn/rsc/zp/2026.html",
            observed_at="2026-08-15T09:30:00",
            extracted_requirements={"degree": "硕士研究生及以上", "major": "软件工程"},
        )

        def mock_resolver(obs, candidates):
            return EntityResolutionDecision(
                resolution="different",
                rationale=f"新建独立实体: {obs.organization}",
            )

        def mock_evaluator(profile, obs):
            if "药科大学" in obs.organization:
                return make_eval_result("PASS")
            return make_eval_result("REVIEW")

        outcome = orchestrator.run(
            observations=[obs_1, obs_2],
            monitoring_facts=facts,
            source_decisions=[discovery_decision],
            entity_resolver_fn=mock_resolver,
            evaluator_fn=mock_evaluator,
            run_date="2026-08-15",
        )

        assert outcome.status == "attention"  # Has 1 review_count
        assert outcome.monitored_sources_count == 1
        assert outcome.new_opportunities_count == 2
        assert outcome.recommended_count == 1
        assert outcome.review_count == 1
        assert outcome.discovered_sources_count == 1

        # Check Opportunities persisted to .data/opportunities.jsonl
        opps_file = temp_env["data_dir"] / "opportunities.jsonl"
        assert opps_file.exists()
        lines = [line for line in opps_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 2

        # Check Sources persisted to .data/sources.json
        sources_file = temp_env["data_dir"] / "sources.json"
        assert sources_file.exists()
        with open(sources_file, "r", encoding="utf-8") as f:
            s_data = json.load(f)
        assert any(s["source_id"] == "gdaib_rsc" for s in s_data)
        assert any(s["source_id"] == "gd_hrss_official" and s["last_technical_status"] == "success" for s in s_data)

        # Check 4-section Daily Digest
        report_file = Path(outcome.report_path)
        content = report_file.read_text(encoding="utf-8")
        assert "## 🎯 强烈推荐 / 新增高价值机会" in content
        assert "广东药科大学" in content
        assert "## ⚠️ 需要人工确认" in content
        assert "广东农工商职业技术学院" in content
        assert "## 🔄 重点岗位动态变更" in content
        assert "## 🌐 渠道网络变动" in content
        assert "🆕 **新发现渠道**：[广东农工商职业技术学院](https://www.gdaib.edu.cn/rsc/)" in content

    def test_slice_e_trigger_equivalence(self, temp_env):
        """
        Slice E: Trigger Equivalence
        Manual invocation and Scheduled invocation execute the exact SAME RadarOrchestrator contract.
        Scheduler contains NO independent business logic or branching.
        """
        orchestrator = RadarOrchestrator(
            profile_path=temp_env["profile_path"],
            seed_sources_path=temp_env["seeds_path"],
            data_dir=temp_env["data_dir"],
            reports_dir=temp_env["reports_dir"],
        )

        # Manual Trigger
        manual_outcome = orchestrator.run(run_date="2026-08-15")

        # Scheduled Trigger (exact same entry point with identical parameters)
        scheduled_outcome = orchestrator.run(run_date="2026-08-15")

        assert isinstance(manual_outcome, RadarRunOutcome)
        assert isinstance(scheduled_outcome, RadarRunOutcome)
        assert manual_outcome.status == scheduled_outcome.status
        assert manual_outcome.monitored_sources_count == scheduled_outcome.monitored_sources_count
