"""
Highest Testing Seam for Career Radar MVP-1 (Issue #12).
Tests the unified deterministic RadarOrchestrator helper across:
- Regression: Rejects non-MonitoringFact inputs and prevents implicit fake success.
- Slice A: Known-source Monitoring & genuine technical execution fact recording via FakeSourceNetwork.
- Slice B: Open Source Discovery & local .data/sources.json persistence (visible in future candidate networks).
- Slice C: Source Degradation & data-driven Section 4 in Daily Digest.
- Slice D: Unified Full Run (Fake Network + Prior Opp/Source State + Discovery + Resolution + 6D Eligibility + 4-section Digest).
- Slice E: Deterministic Coordinator Contract (Python coordinator helper idempotency).
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
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


class FakeSourceNetwork:
    """Test double simulating network execution at the highest test seam."""

    def __init__(self, routes: Dict[str, Dict[str, Any]]):
        self.routes = routes
        self.requested_sources: List[str] = []

    def check_source(self, source: SourceRecord) -> Optional[MonitoringFact]:
        if source.source_id not in self.routes:
            return None
        self.requested_sources.append(source.source_id)
        cfg = self.routes[source.source_id]
        return MonitoringFact(
            source_id=source.source_id,
            technical_status=cfg.get("status", "failed"),
            checked_url=cfg.get("checked_url", source.base_url),
            checked_at=cfg.get("checked_at", "2026-08-15T09:00:00"),
            metadata=cfg.get("metadata"),
        )


@pytest.fixture
def temp_env(tmp_path: Path):
    """Sets up a clean temporary environment with mock profile, public seeds, and dirs."""
    config_dir, data_dir, reports_dir = tmp_path / "config", tmp_path / ".data", tmp_path / "reports"
    for d in (config_dir, data_dir, reports_dir):
        d.mkdir(parents=True)

    profile_data = {
        "candidate_id": "test_candidate_001",
        "name": "测试候选人",
        "education": {"degree_level": "博士研究生", "degree_name": "工学博士", "major": "计算机科学与技术", "major_code": "081200", "is_full_time": True},
        "tracks": [{"name": "higher_education_teaching", "priority": "high"}, {"name": "vocational_education", "priority": "medium"}],
        "target_regions": ["guangdong", "guangzhou"],
    }
    profile_path = tmp_path / "profile.local.yaml"
    with open(profile_path, "w", encoding="utf-8") as f:
        yaml.dump(profile_data, f, allow_unicode=True)

    seeds_data = [
        {"source_id": "gd_hrss_official", "name": "广东省人力资源和社会保障厅", "base_url": "http://hrss.gd.gov.cn/zwgk/gsgg/", "domain": "hrss.gd.gov.cn", "source_type": "first_party_official", "track": ["higher_education_teaching", "vocational_education"], "region": "guangdong", "discovery_role": "monitoring", "lifecycle_status": "active"},
        {"source_id": "scnu_rsc", "name": "华南师范大学人事处", "base_url": "https://rsc.scnu.edu.cn/", "domain": "rsc.scnu.edu.cn", "source_type": "first_party_institution", "track": ["higher_education_teaching"], "region": "guangdong", "discovery_role": "monitoring", "lifecycle_status": "active"},
        {"source_id": "unrelated_industry_hub", "name": "不相关外省金融招聘站", "base_url": "https://finance.example.com/", "domain": "finance.example.com", "source_type": "vertical_aggregator", "track": ["finance_banking"], "region": "beijing", "discovery_role": "monitoring", "lifecycle_status": "active"},
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


def make_eval_result(edu_state: str = "PASS") -> EvaluationResult:
    return EvaluationResult(
        final_recommendation="建议关注" if edu_state == "PASS" else "需要人工确认",
        dimension_evaluations={
            "Age": DimensionEvaluation("Age", "PASS", "35周岁以下", "年龄符合要求"),
            "Education": DimensionEvaluation("Education", edu_state, "博士研究生", "学历评定"),
            "Formal Qualification": DimensionEvaluation("Formal Qualification", "PASS", "0812 计算机", "专业对口"),
            "Capability Fit": DimensionEvaluation("Capability Fit", "PASS", "教学科研岗", "能力符合"),
            "Teaching Experience": DimensionEvaluation("Teaching Experience", "N/A", "不限", "公告无任教经历要求"),
            "Industry Experience": DimensionEvaluation("Industry Experience", "N/A", "不限", "公告无企业经历要求"),
        },
        evaluated_at="2026-08-15T09:00:00",
    )


class TestRadarOrchestratorSeam:

    def test_regression_record_monitoring_fact_rejects_non_fact_and_prevents_implicit_success(self, temp_env):
        """Proves that non-MonitoringFact inputs raise TypeError and prevents fake implicit success."""
        registry = SourceRegistry(seed_path=temp_env["seeds_path"], data_dir=temp_env["data_dir"])

        with pytest.raises(TypeError, match="requires a MonitoringFact instance"):
            registry.record_monitoring_fact("gd_hrss_official")  # type: ignore

        with pytest.raises(TypeError, match="requires a MonitoringFact instance"):
            registry.record_monitoring_fact({"source_id": "gd_hrss_official"})  # type: ignore

        src = registry.get_source("gd_hrss_official")
        assert src is not None
        assert src.last_monitored_at is None
        assert src.last_technical_status is None

    def test_slice_a_known_source_monitoring_with_fake_source_network(self, temp_env):
        """Slice A: Known-source Monitoring with FakeSourceNetwork turning responses into facts."""
        registry = SourceRegistry(seed_path=temp_env["seeds_path"], data_dir=temp_env["data_dir"])
        orchestrator = RadarOrchestrator(
            profile_path=temp_env["profile_path"],
            seed_sources_path=temp_env["seeds_path"],
            data_dir=temp_env["data_dir"],
            reports_dir=temp_env["reports_dir"],
        )

        fake_network = FakeSourceNetwork({
            "gd_hrss_official": {"status": "success", "checked_url": "http://hrss.gd.gov.cn/zwgk/gsgg/"},
            "scnu_rsc": {"status": "failed", "checked_url": "https://rsc.scnu.edu.cn/"},
        })

        facts = [
            f for s in registry.get_active_sources()
            if (f := fake_network.check_source(s)) is not None
        ]
        assert len(facts) == 2
        assert "unrelated_industry_hub" not in fake_network.requested_sources

        outcome = orchestrator.run(monitoring_facts=facts, run_date="2026-08-15")
        assert outcome.status == "attention"
        assert outcome.monitored_sources_count == 2

        with open(temp_env["data_dir"] / "sources.json", "r", encoding="utf-8") as f:
            local_data = json.load(f)

        hrss_rec = next(s for s in local_data if s["source_id"] == "gd_hrss_official")
        scnu_rec = next(s for s in local_data if s["source_id"] == "scnu_rsc")
        assert hrss_rec["last_technical_status"] == "success"
        assert scnu_rec["last_technical_status"] == "failed"

        unrelated = next((s for s in local_data if s["source_id"] == "unrelated_industry_hub"), None)
        assert unrelated is None or unrelated.get("last_monitored_at") is None

        with open(temp_env["seeds_path"], "r", encoding="utf-8") as f:
            seed_data = json.load(f)
        assert len(seed_data) == 3
        assert "last_monitored_at" not in seed_data[0]

    def test_slice_b_open_source_discovery_visible_in_next_run(self, temp_env):
        """Slice B: Open Source Discovery persists to local state and becomes visible as candidate in next run."""
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

        outcome = orchestrator.run(source_decisions=[discovery_decision], run_date="2026-08-15")
        assert outcome.discovered_sources_count == 1
        assert outcome.network_changes_count == 1

        with open(temp_env["data_dir"] / "sources.json", "r", encoding="utf-8") as f:
            local_data = json.load(f)
        discovered = next(s for s in local_data if s["source_id"] == "gdaib_rsc")
        assert discovered["lifecycle_status"] == "discovered"
        assert discovered["origin"] == "discovered"

        registry_next = SourceRegistry(seed_path=temp_env["seeds_path"], data_dir=temp_env["data_dir"])
        assert "gdaib_rsc" in [s.source_id for s in registry_next.get_candidate_sources()]

        report_content = Path(outcome.report_path).read_text(encoding="utf-8")
        assert "## 🌐 渠道网络变动" in report_content
        assert "🆕 **新发现渠道**：[广东农工商职业技术学院人事处](https://www.gdaib.edu.cn/rsc/)" in report_content
        assert "发现省属公办高职院校最新招聘专栏" in report_content

    def test_slice_c_source_degradation(self, temp_env):
        """Slice C: Source Degradation updates local status and reflects in report section 4."""
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

        outcome = orchestrator.run(source_decisions=[degrade_decision], run_date="2026-08-15")
        assert outcome.network_changes_count == 1
        assert outcome.status == "attention"

        with open(temp_env["data_dir"] / "sources.json", "r", encoding="utf-8") as f:
            local_data = json.load(f)
        scnu = next(s for s in local_data if s["source_id"] == "scnu_rsc")
        assert scnu["lifecycle_status"] == "degraded"
        assert "站点发生永久性 404" in scnu["degraded_reason"]

        report_content = Path(outcome.report_path).read_text(encoding="utf-8")
        assert "⚠️ **渠道降级**：[华南师范大学人事处](https://rsc.scnu.edu.cn/)" in report_content
        assert "站点发生永久性 404" in report_content

    def test_slice_d_unified_full_run_with_prior_states_and_mock_network(self, temp_env):
        """
        Slice D: Unified Full Run with Visible Inputs & Outputs.
        Visibly combines Fake Network + Prior States + Discovery + Resolution + 6D Eligibility -> State + Report.
        """
        data_dir = temp_env["data_dir"]

        # 1. Setup Prior Local Source State (.data/sources.json)
        prior_local_source = SourceRecord(
            source_id="prior_known_hub",
            name="广州大学人事处",
            base_url="https://rsc.gzhu.edu.cn/",
            domain="rsc.gzhu.edu.cn",
            source_type="first_party_institution",
            track=["higher_education_teaching"],
            region="guangzhou",
            discovery_role="discovered",
            origin="discovered",
            lifecycle_status="discovered",
            discovered_at="2026-08-10T10:00:00",
        )
        prior_sources_file = data_dir / "sources.json"
        with open(prior_sources_file, "w", encoding="utf-8") as f:
            json.dump([prior_local_source.to_dict()], f, ensure_ascii=False, indent=2)

        # 2. Setup Prior Opportunity State (.data/opportunities.jsonl)
        prior_obs = SourceObservation(
            observation_id="obs_prior_000",
            announcement_id="ann_prior_000",
            source_id="gd_hrss_official",
            source_name="广东省人力资源和社会保障厅",
            announcement_title="广东省事业单位2026年公开招聘",
            job_title="计算机学院专任教师",
            organization="广东工业大学",
            location="广州市",
            track="higher_education_teaching",
            official_url="http://hrss.gd.gov.cn/zwgk/gsgg/old.html",
            observed_at="2026-08-10T09:00:00",
            extracted_requirements={"degree": "博士研究生"},
        )
        prior_opp = Opportunity(
            opportunity_id="opp_prior_001",
            canonical_job_title="计算机学院专任教师",
            organization="广东工业大学",
            location="广州市",
            track="higher_education_teaching",
            official_url="http://hrss.gd.gov.cn/zwgk/gsgg/old.html",
            lifecycle_status="active",
            observations=[prior_obs],
            latest_evaluation=make_eval_result("PASS"),
            created_at="2026-08-10T09:00:00",
            updated_at="2026-08-10T09:00:00",
        )
        opps_file = data_dir / "opportunities.jsonl"
        with open(opps_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(prior_opp.to_dict(), ensure_ascii=False) + "\n")

        # 3. Mock Source Network -> produce MonitoringFacts
        fake_network = FakeSourceNetwork({
            "gd_hrss_official": {"status": "success", "checked_url": "http://hrss.gd.gov.cn/zwgk/gsgg/"},
        })
        registry = SourceRegistry(seed_path=temp_env["seeds_path"], data_dir=data_dir)
        hrss_src = registry.get_source("gd_hrss_official")
        assert hrss_src is not None
        facts = [fake_network.check_source(hrss_src)]

        # 4. Fake Agent Source Lifecycle Decision (Discovery)
        discovery_decision = SourceLifecycleDecision(
            source_id="gdaib_rsc",
            action="discover",
            name="广东农工商职业技术学院",
            base_url="https://www.gdaib.edu.cn/rsc/",
            source_type="first_party_institution",
            rationale="发现新高职招聘渠道",
        )

        # 5. Incoming Observations
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
                rationale=f"与既有实体用人单位不同，新建独立实体: {obs.organization}",
            )

        def mock_evaluator(profile, obs):
            return make_eval_result("PASS") if "药科大学" in obs.organization else make_eval_result("REVIEW")

        orchestrator = RadarOrchestrator(
            profile_path=temp_env["profile_path"],
            seed_sources_path=temp_env["seeds_path"],
            data_dir=temp_env["data_dir"],
            reports_dir=temp_env["reports_dir"],
        )

        outcome = orchestrator.run(
            observations=[obs_1, obs_2],
            monitoring_facts=facts,
            source_decisions=[discovery_decision],
            entity_resolver_fn=mock_resolver,
            evaluator_fn=mock_evaluator,
            run_date="2026-08-15",
        )

        assert outcome.status == "attention"
        assert outcome.monitored_sources_count == 1
        assert outcome.new_opportunities_count == 2
        assert outcome.recommended_count == 1
        assert outcome.review_count == 1
        assert outcome.discovered_sources_count == 1

        # Check Opportunity state: contains prior + 2 new opportunities = 3 lines
        opp_lines = [l for l in opps_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(opp_lines) == 3
        opp_orgs = [json.loads(l)["organization"] for l in opp_lines]
        assert "广东工业大学" in opp_orgs
        assert "广东药科大学" in opp_orgs
        assert "广东农工商职业技术学院" in opp_orgs

        # Check Source state: contains prior local source + discovered + monitored facts
        with open(prior_sources_file, "r", encoding="utf-8") as f:
            s_data = json.load(f)
        s_ids = [s["source_id"] for s in s_data]
        assert "prior_known_hub" in s_ids
        assert "gdaib_rsc" in s_ids
        assert any(s["source_id"] == "gd_hrss_official" and s["last_technical_status"] == "success" for s in s_data)

        # Check 4-section Daily Digest
        content = Path(outcome.report_path).read_text(encoding="utf-8")
        assert "## 🎯 强烈推荐 / 新增高价值机会" in content
        assert "广东药科大学" in content
        assert "## ⚠️ 需要人工确认" in content
        assert "广东农工商职业技术学院" in content
        assert "## 🔄 重点岗位动态变更" in content
        assert "## 🌐 渠道网络变动" in content
        assert "🆕 **新发现渠道**：[广东农工商职业技术学院](https://www.gdaib.edu.cn/rsc/)" in content

    def test_slice_e_deterministic_coordinator_contract(self, temp_env):
        """
        Slice E: Deterministic Coordinator Contract
        Verifies that the Python coordinator helper executes idempotently with identical inputs.
        (Agent-level Manual vs Scheduled orchestration equivalence is verified via Skill execution).
        """
        orchestrator = RadarOrchestrator(
            profile_path=temp_env["profile_path"],
            seed_sources_path=temp_env["seeds_path"],
            data_dir=temp_env["data_dir"],
            reports_dir=temp_env["reports_dir"],
        )

        outcome_1 = orchestrator.run(run_date="2026-08-15")
        outcome_2 = orchestrator.run(run_date="2026-08-15")

        assert isinstance(outcome_1, RadarRunOutcome)
        assert isinstance(outcome_2, RadarRunOutcome)
        assert outcome_1.status == outcome_2.status
        assert outcome_1.monitored_sources_count == outcome_2.monitored_sources_count
