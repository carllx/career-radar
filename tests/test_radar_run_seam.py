import json
from pathlib import Path
import pytest
import yaml

from career_radar.runner import run_radar_pipeline


@pytest.fixture
def mock_radar_env(tmp_path: Path):
    # 1. Prepare private profile fixture
    profile_path = tmp_path / "profile.local.yaml"
    profile_data = {
        "candidate": {
            "age": 30,
            "degree": "master",
            "degree_field": "Computer Science & Digital Media",
            "teaching_experience_years": 3,
            "industry_experience_years": 4,
            "tracks": [
                {"name": "higher_education_teaching", "priority": 1},
                {"name": "vocational_education", "priority": 2},
            ],
            "regions": {
                "p1": ["Guangzhou"],
                "p2": ["Foshan", "Dongguan"],
                "p3": ["Greater Bay Area"],
            },
            "hard_constraints": {
                "min_degree": "master",
                "max_age": 35,
            },
        }
    }
    with open(profile_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(profile_data, f)

    # 2. Prepare mock SourceObservation fixture
    observations_fixture_path = tmp_path / "mock_observations.json"
    observations = [
        {
            "observation_id": "obs_mock_001",
            "announcement_id": "ann_mock_001",
            "source_id": "gd_hrss_official",
            "source_name": "广东省人力资源和社会保障厅",
            "announcement_title": "2026年广东省属高校专任教师公开招聘公告",
            "job_title": "数字媒体技术专任教师",
            "organization": "广东轻工职业技术大学",
            "location": "Guangzhou",
            "track": "vocational_education",
            "official_url": "http://hrss.gd.gov.cn/zwgk/gsgg/content_001.html",
            "observed_at": "2026-08-15T09:00:00+08:00",
            "extracted_requirements": {
                "age_text": "35周岁以下（1991年1月1日以后出生）",
                "education_text": "具有硕士研究生及以上学历并取得硕士及以上学位",
                "formal_qualification_text": "计算机科学与技术（0812）、数字媒体技术（0854）专业方向",
                "capability_fit_text": "能胜任数字交互设计、三维动画与虚拟制作相关课程讲授",
                "teaching_experience_text": "具有高校或职校相关课程带教或教学经验者优先",
                "industry_experience_text": "具有相关行业工程实务经验者优先",
            },
        },
        {
            "observation_id": "obs_mock_002",
            "announcement_id": "ann_mock_002",
            "source_id": "scnu_rsc",
            "source_name": "华南师范大学人事处",
            "announcement_title": "华南师范大学2026年高层次与紧缺人才引进公告",
            "job_title": "交叉学科创新教师",
            "organization": "华南师范大学",
            "location": "Guangzhou",
            "track": "higher_education_teaching",
            "official_url": "https://rsc.scnu.edu.cn/recruit/2026_002.html",
            "observed_at": "2026-08-15T09:10:00+08:00",
            "extracted_requirements": {
                "age_text": "原则上不超过35周岁，特别优秀者可适当放宽",
                "education_text": "硕士研究生及以上，具备相关学术成果",
                "formal_qualification_text": "设计学、计算机科学交叉方向（未限制严格专业目录代码）",
                "capability_fit_text": "承担跨学科综合实践课程与科研课题",
                "teaching_experience_text": "具备带教能力",
                "industry_experience_text": "不作硬性要求",
            },
        },
        {
            "observation_id": "obs_mock_003",
            "announcement_id": "ann_mock_003",
            "source_id": "sysu_rcb",
            "source_name": "中山大学人才招聘网",
            "announcement_title": "中山大学2026年专任教师招聘启事",
            "job_title": "理论物理教授/副教授",
            "organization": "中山大学",
            "location": "Guangzhou",
            "track": "higher_education_teaching",
            "official_url": "https://rcb.sysu.edu.cn/recruit/2026_003.html",
            "observed_at": "2026-08-15T09:20:00+08:00",
            "extracted_requirements": {
                "age_text": "28周岁以下",
                "education_text": "必须具备博士研究生学历与博士学位，博士后出站人员优先",
                "formal_qualification_text": "理论物理（070201）专业博士",
                "capability_fit_text": "主讲理论物理前沿课程并主持国家级项目",
                "teaching_experience_text": "需具备2年以上海外高校全英文主讲经历",
                "industry_experience_text": "不适用",
            },
        },
    ]
    with open(observations_fixture_path, "w", encoding="utf-8") as f:
        json.dump(observations, f, ensure_ascii=False, indent=2)

    data_dir = tmp_path / ".data"
    reports_dir = tmp_path / "reports"

    return {
        "profile_path": profile_path,
        "observations_fixture_path": observations_fixture_path,
        "data_dir": data_dir,
        "reports_dir": reports_dir,
    }


def test_career_radar_highest_seam_full_run(mock_radar_env):
    """
    Test the Highest Testing Seam:
    Public Entrypoint -> Mock Observation Fixture + Private Profile Fixture + Prior State
    Assert Opportunity state persistence and Daily Digest Markdown report.
    """
    result = run_radar_pipeline(
        profile_path=mock_radar_env["profile_path"],
        observations_source=mock_radar_env["observations_fixture_path"],
        data_dir=mock_radar_env["data_dir"],
        reports_dir=mock_radar_env["reports_dir"],
        run_date="2026-08-15",
    )

    # 1. Check return summary
    assert result["success"] is True
    assert result["total_evaluated"] == 3
    assert result["recommended_count"] == 1
    assert result["review_count"] == 1
    assert result["mismatch_count"] == 1

    # 2. Check local persistence (.data/opportunities.jsonl)
    opps_file = mock_radar_env["data_dir"] / "opportunities.jsonl"
    assert opps_file.exists(), "opportunities.jsonl must be persisted"

    opportunities = []
    with open(opps_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                opportunities.append(json.loads(line))

    assert len(opportunities) == 3

    # Check Opportunity A (Strong match -> 建议关注)
    opp_a = next(o for o in opportunities if o["job_title"] == "数字媒体技术专任教师")
    assert opp_a["latest_evaluation"]["final_recommendation"] == "建议关注"
    eval_a = opp_a["latest_evaluation"]["dimension_evaluations"]
    assert eval_a["Age"]["state"] == "PASS"
    assert "35周岁以下" in eval_a["Age"]["requirement_evidence"]
    assert eval_a["Education"]["state"] == "PASS"
    assert eval_a["Formal Qualification"]["state"] == "PASS"
    assert eval_a["Capability Fit"]["state"] == "PASS"

    # Check Opportunity B (Borderline/Review -> 需要人工确认)
    opp_b = next(o for o in opportunities if o["job_title"] == "交叉学科创新教师")
    assert opp_b["latest_evaluation"]["final_recommendation"] == "需要人工确认"
    eval_b = opp_b["latest_evaluation"]["dimension_evaluations"]
    assert eval_b["Formal Qualification"]["state"] == "REVIEW"
    assert "未限制严格专业目录代码" in eval_b["Formal Qualification"]["requirement_evidence"]

    # Check Opportunity C (Hard Blocker -> 明显不符合)
    opp_c = next(o for o in opportunities if o["job_title"] == "理论物理教授/副教授")
    assert opp_c["latest_evaluation"]["final_recommendation"] == "明显不符合"
    eval_c = opp_c["latest_evaluation"]["dimension_evaluations"]
    assert eval_c["Education"]["state"] == "FAIL"
    assert "必须具备博士研究生学历" in eval_c["Education"]["requirement_evidence"]

    # 3. Check Daily Digest Markdown report (reports/2026-08-15.md)
    report_file = mock_radar_env["reports_dir"] / "2026-08-15.md"
    assert report_file.exists(), "Daily digest report must be generated"

    report_content = report_file.read_text(encoding="utf-8")
    assert "# 🎯 强烈推荐 / 新增高价值机会" in report_content
    assert "数字媒体技术专任教师" in report_content
    assert "广东轻工职业技术大学" in report_content
    assert "http://hrss.gd.gov.cn/zwgk/gsgg/content_001.html" in report_content
    assert "# ⚠️ 需要人工确认" in report_content
    assert "交叉学科创新教师" in report_content
    assert "# 🔄 重点岗位动态变更" in report_content
    assert "# 🌐 渠道网络变动" in report_content
