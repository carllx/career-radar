"""
Agent-driven execution entrypoint for Career Radar MVP-1.
Demonstrates the complete end-to-end Agent semantic evaluation flow.
"""

from pathlib import Path
import sys

from .models import (
    CandidateProfile,
    DimensionEvaluation,
    EvaluationResult,
    SourceObservation,
)
from .runner import run_radar_pipeline


def demo_agent_semantic_evaluator(
    profile: CandidateProfile, observation: SourceObservation
) -> EvaluationResult:
    """
    Demonstration of an Agent Semantic Evaluator fulfilling the SemanticEvaluatorProtocol.
    In real Agent execution, the Agent inspects the candidate profile and raw announcement
    text and produces this structured result without deterministic keyword rules.
    """
    obs_id = observation.observation_id
    now = "2026-08-15T16:40:00+08:00"
    reqs = observation.extracted_requirements

    if "001" in obs_id or "数字媒体" in observation.job_title:
        # Agent semantic judgment: candidate meets all qualifications with clear positive evidence
        return EvaluationResult(
            final_recommendation="建议关注",
            dimension_evaluations={
                "Age": DimensionEvaluation(
                    "Age", "PASS", reqs.get("age_text", ""), "候选人30岁在35周岁上限内，满足年龄门槛"
                ),
                "Education": DimensionEvaluation(
                    "Education", "PASS", reqs.get("education_text", ""), "候选人持硕士学位，满足硕士及以上学历学位要求"
                ),
                "Formal Qualification": DimensionEvaluation(
                    "Formal Qualification", "PASS", reqs.get("formal_qualification_text", ""), "候选人专业背景为计算机与数字媒体，与岗位方向完全一致"
                ),
                "Capability Fit": DimensionEvaluation(
                    "Capability Fit", "PASS", reqs.get("capability_fit_text", ""), "候选人技术栈涵盖数字交互设计与三维制作，胜任讲授要求"
                ),
                "Teaching Experience": DimensionEvaluation(
                    "Teaching Experience", "PASS", reqs.get("teaching_experience_text", ""), "具备3年高校教学经历，符合优先条件"
                ),
                "Industry Experience": DimensionEvaluation(
                    "Industry Experience", "PASS", reqs.get("industry_experience_text", ""), "具备4年数字文化产业项目实务经验，符合优先条件"
                ),
            },
            evaluated_at=now,
        )
    elif "002" in obs_id or "交叉学科" in observation.job_title:
        # Agent semantic judgment: candidate meets most criteria, but formal qualification is open/flexible
        return EvaluationResult(
            final_recommendation="需要人工确认",
            dimension_evaluations={
                "Age": DimensionEvaluation(
                    "Age", "PASS", reqs.get("age_text", ""), "适用特别优秀放宽考量"
                ),
                "Education": DimensionEvaluation(
                    "Education", "PASS", reqs.get("education_text", ""), "具备硕士研究生学历与相关成果"
                ),
                "Formal Qualification": DimensionEvaluation(
                    "Formal Qualification", "REVIEW", reqs.get("formal_qualification_text", ""), "岗位为跨学科交叉方向且未限定目录代码，存在学术裁量空间，需人工确认"
                ),
                "Capability Fit": DimensionEvaluation(
                    "Capability Fit", "PASS", reqs.get("capability_fit_text", ""), "具备跨学科综合课题研发与教学能力"
                ),
                "Teaching Experience": DimensionEvaluation(
                    "Teaching Experience", "PASS", reqs.get("teaching_experience_text", ""), "具备高校带教经验"
                ),
                "Industry Experience": DimensionEvaluation(
                    "Industry Experience", "N/A", reqs.get("industry_experience_text", ""), "无硬性行业年限限制"
                ),
            },
            evaluated_at=now,
        )
    else:
        # Agent semantic judgment: candidate is Master, post has hard PhD and sub-28 requirement
        return EvaluationResult(
            final_recommendation="明显不符合",
            dimension_evaluations={
                "Age": DimensionEvaluation(
                    "Age", "FAIL", reqs.get("age_text", ""), "候选人30岁超过28周岁硬性上限"
                ),
                "Education": DimensionEvaluation(
                    "Education", "FAIL", reqs.get("education_text", ""), "岗位硬性要求博士学位与博士后经历，候选人为硕士"
                ),
                "Formal Qualification": DimensionEvaluation(
                    "Formal Qualification", "FAIL", reqs.get("formal_qualification_text", ""), "理论物理专业与候选人计算机/数字媒体背景不符"
                ),
                "Capability Fit": DimensionEvaluation(
                    "Capability Fit", "FAIL", reqs.get("capability_fit_text", ""), "理论物理前沿课题与候选人能力领域不重合"
                ),
                "Teaching Experience": DimensionEvaluation(
                    "Teaching Experience", "FAIL", reqs.get("teaching_experience_text", ""), "未具备海外全英文主讲经历"
                ),
                "Industry Experience": DimensionEvaluation(
                    "Industry Experience", "N/A", reqs.get("industry_experience_text", ""), "不适用"
                ),
            },
            evaluated_at=now,
        )


def main():
    profile_file = Path("profile.local.yaml")
    if not profile_file.exists():
        profile_file = Path("config/profile.example.yaml")

    fixture_file = Path("config/fixtures/mock_observations.example.json")
    if not fixture_file.exists():
        print(f"Fixture not found: {fixture_file}")
        sys.exit(1)

    result = run_radar_pipeline(
        profile_path=profile_file,
        observations_source=fixture_file,
        evaluator_fn=demo_agent_semantic_evaluator,
        data_dir=".data",
        reports_dir="reports",
    )
    print(f"[Career Radar Agent Run Succeeded]")
    print(f"  - Total Evaluated: {result['total_evaluated']}")
    print(f"  - Recommended: {result['recommended_count']}")
    print(f"  - Needs Review: {result['review_count']}")
    print(f"  - Mismatched: {result['mismatch_count']}")
    print(f"  - Report: {result['report_path']}")


if __name__ == "__main__":
    main()
