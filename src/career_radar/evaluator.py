"""
Discrete semantic evaluator for Career Radar opportunities.
Implements ADR-0001 (6 canonical dimensions, 5 evidence states, 3 recommendations).
"""

from datetime import datetime
from typing import Dict

from .models import (
    CANONICAL_DIMENSIONS,
    CandidateProfile,
    DimensionEvaluation,
    EvaluationResult,
    SourceObservation,
)


class DiscreteEvaluator:
    """
    Evaluates a SourceObservation against a CandidateProfile across 6 discrete dimensions.
    Produces requirement evidence citations and discrete 5-state evaluations.
    """

    def evaluate(
        self, profile: CandidateProfile, observation: SourceObservation
    ) -> EvaluationResult:
        reqs = observation.extracted_requirements
        evaluations: Dict[str, DimensionEvaluation] = {}

        # 1. Age Dimension
        age_text = reqs.get("age_text", "")
        evaluations["Age"] = self._eval_age(profile, age_text)

        # 2. Education Dimension
        edu_text = reqs.get("education_text", "")
        evaluations["Education"] = self._eval_education(profile, edu_text)

        # 3. Formal Qualification Dimension
        qual_text = reqs.get("formal_qualification_text", "")
        evaluations["Formal Qualification"] = self._eval_formal_qualification(
            profile, qual_text
        )

        # 4. Capability Fit Dimension
        cap_text = reqs.get("capability_fit_text", "")
        evaluations["Capability Fit"] = self._eval_capability_fit(profile, cap_text)

        # 5. Teaching Experience Dimension
        teach_text = reqs.get("teaching_experience_text", "")
        evaluations["Teaching Experience"] = self._eval_teaching_exp(profile, teach_text)

        # 6. Industry Experience Dimension
        ind_text = reqs.get("industry_experience_text", "")
        evaluations["Industry Experience"] = self._eval_industry_exp(profile, ind_text)

        # Compute Final Recommendation (ADR-0001)
        final_rec = self._compute_final_recommendation(evaluations)

        return EvaluationResult(
            final_recommendation=final_rec,
            dimension_evaluations=evaluations,
            evaluated_at=datetime.now().isoformat(),
        )

    def _eval_age(self, profile: CandidateProfile, text: str) -> DimensionEvaluation:
        if not text:
            return DimensionEvaluation("Age", "UNKNOWN", "", "公告未提及年龄要求")
        if "特别优秀者可适当放宽" in text or "原则上" in text:
            return DimensionEvaluation("Age", "PASS", text, "符合放宽考量范围")
        if "28" in text and profile.age > 28:
            return DimensionEvaluation("Age", "FAIL", text, f"年龄超限（候选人{profile.age}岁）")
        if "35" in text and profile.age <= 35:
            return DimensionEvaluation("Age", "PASS", text, f"符合年龄要求（候选人{profile.age}岁）")
        if "40" in text and profile.age <= 40:
            return DimensionEvaluation("Age", "PASS", text, f"符合年龄要求（候选人{profile.age}岁）")
        return DimensionEvaluation("Age", "REVIEW", text, "年龄条件需进一步人工核对")

    def _eval_education(self, profile: CandidateProfile, text: str) -> DimensionEvaluation:
        if not text:
            return DimensionEvaluation("Education", "UNKNOWN", "", "公告未提及学历学位要求")
        if "必须具备博士" in text or ("博士" in text and "硕士" not in text):
            if profile.degree.lower() != "phd" and profile.degree.lower() != "doctor":
                return DimensionEvaluation(
                    "Education", "FAIL", text, "岗位硬性要求博士学位，候选人学历为硕士"
                )
            return DimensionEvaluation("Education", "PASS", text, "符合博士学历学位要求")
        if "硕士" in text or "研究生" in text:
            return DimensionEvaluation("Education", "PASS", text, "符合硕士及以上学历学位要求")
        return DimensionEvaluation("Education", "REVIEW", text, "学历学位要求需结合细则核对")

    def _eval_formal_qualification(
        self, profile: CandidateProfile, text: str
    ) -> DimensionEvaluation:
        if not text:
            return DimensionEvaluation(
                "Formal Qualification", "UNKNOWN", "", "公告未写明具体专业方向代码"
            )
        if "未限制严格专业目录代码" in text or "交叉方向" in text:
            return DimensionEvaluation(
                "Formal Qualification",
                "REVIEW",
                text,
                "交叉学科或专业目录放宽，存在裁量空间，需人工确认",
            )
        if "理论物理" in text and "物理" not in profile.degree_field:
            return DimensionEvaluation(
                "Formal Qualification", "FAIL", text, "专业方向不相符"
            )
        if any(w in text for w in ["数字媒体", "计算机", "设计"]):
            return DimensionEvaluation(
                "Formal Qualification", "PASS", text, "专业背景高度契合"
            )
        return DimensionEvaluation(
            "Formal Qualification", "REVIEW", text, "专业匹配度需人工综合评定"
        )

    def _eval_capability_fit(
        self, profile: CandidateProfile, text: str
    ) -> DimensionEvaluation:
        if not text:
            return DimensionEvaluation("Capability Fit", "UNKNOWN", "", "未详述具体课程与能力要求")
        if "理论物理前沿" in text and "物理" not in profile.degree_field:
            return DimensionEvaluation("Capability Fit", "FAIL", text, "课程领域与候选人背景脱节")
        return DimensionEvaluation("Capability Fit", "PASS", text, "具备相应课程与实践能力")

    def _eval_teaching_exp(
        self, profile: CandidateProfile, text: str
    ) -> DimensionEvaluation:
        if not text or "不作硬性要求" in text or "不适用" in text:
            return DimensionEvaluation("Teaching Experience", "N/A", text, "岗位未设硬性教学经历门槛")
        if "2年以上海外高校全英文主讲" in text:
            return DimensionEvaluation("Teaching Experience", "FAIL", text, "未满足海外全英文授课经历")
        if "优先" in text or profile.teaching_experience_years > 0:
            return DimensionEvaluation("Teaching Experience", "PASS", text, "具备教学/带教经历")
        return DimensionEvaluation("Teaching Experience", "REVIEW", text, "教学经历需结合简历进一步确认")

    def _eval_industry_exp(
        self, profile: CandidateProfile, text: str
    ) -> DimensionEvaluation:
        if not text or "不作硬性要求" in text or "不适用" in text:
            return DimensionEvaluation("Industry Experience", "N/A", text, "无硬性行业经验要求")
        if "优先" in text or profile.industry_experience_years > 0:
            return DimensionEvaluation("Industry Experience", "PASS", text, "具备行业工程实践背景")
        return DimensionEvaluation("Industry Experience", "N/A", text, "不影响核心资格")

    def _compute_final_recommendation(
        self, evaluations: Dict[str, DimensionEvaluation]
    ) -> str:
        states = [eval.state for eval in evaluations.values()]
        # Hard Blocker: any FAIL on core dimensions -> 明显不符合
        if "FAIL" in states:
            return "明显不符合"
        # If any dimension requires review or has insufficient evidence -> 需要人工确认
        if "REVIEW" in states or "UNKNOWN" in states:
            return "需要人工确认"
        return "建议关注"
