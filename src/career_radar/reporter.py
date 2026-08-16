"""
Daily Markdown Digest generator for Career Radar.
Implements ADR-0004 (high signal-to-noise structured reporting).
Respects Issue #11 incremental entity resolution presentation.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Opportunity


class DigestReporter:
    """
    Renders structured Markdown daily reports categorized into:
    - 🎯 强烈推荐 / 新增高价值机会
    - 🔄 重点岗位动态变更
    - ⚠️ 需要人工确认
    - 🌐 渠道网络变动
    """

    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(
        self,
        opportunities: List[Opportunity],
        run_date: Optional[str] = None,
        new_opportunity_ids: Optional[List[str]] = None,
        updated_opportunity_ids: Optional[List[str]] = None,
        network_changes: Optional[List[Dict[str, Any]]] = None,
    ) -> Path:
        """
        Renders the daily markdown digest report to reports/YYYY-MM-DD.md.
        """
        if not run_date:
            run_date = datetime.now().strftime("%Y-%m-%d")

        report_path = self.reports_dir / f"{run_date}.md"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        if new_opportunity_ids is not None:
            target_opps = [
                o for o in opportunities if o.opportunity_id in new_opportunity_ids
            ]
        else:
            target_opps = opportunities

        if updated_opportunity_ids is not None:
            updated_posts = [
                o for o in opportunities if o.opportunity_id in updated_opportunity_ids
            ]
        else:
            updated_posts = [
                o for o in opportunities if o.lifecycle_status == "updated"
            ]

        recommended = [
            o
            for o in target_opps
            if o.latest_evaluation
            and o.latest_evaluation.final_recommendation == "建议关注"
            and not o.uncertain_links
        ]
        review_needed = [
            o
            for o in target_opps
            if (
                o.latest_evaluation
                and o.latest_evaluation.final_recommendation == "需要人工确认"
            )
            or o.uncertain_links
        ]

        lines = [
            f"# Career Radar 每日求职情报简报 ({run_date})",
            "",
            f"> **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
            f"> **本次巡检机会总数**：{len(target_opps)} 篇 | 资格建议关注：{len(recommended)} 个 | 待确认：{len(review_needed)} 个",
            "",
            "---",
            "",
            "## 🎯 资格建议关注 / 新增机会",
            "",
        ]

        if not recommended:
            lines.append("本次巡检未发现新增高匹配度机会。\n")
        else:
            for opp in recommended:
                lines.extend(self._format_opportunity_block(opp))

        lines.extend([
            "---",
            "",
            "## ⚠️ 需要人工确认",
            "",
        ])

        if not review_needed:
            lines.append("当前无存疑或需人工核对的边缘机会。\n")
        else:
            for opp in review_needed:
                lines.extend(self._format_opportunity_block(opp))

        lines.extend([
            "---",
            "",
            "## 🔄 重点岗位动态变更",
            "",
        ])

        if not updated_posts:
            lines.append("本次巡检暂无历史岗位补充公告或延期变更。\n")
        else:
            for opp in updated_posts:
                update_desc = opp.update_summary or "状态更新"
                update_url = (opp.change_diff or {}).get("latest_official_url") or opp.official_url
                lines.append(
                    f"- **{opp.organization}** · [{opp.canonical_job_title}]({update_url})：{update_desc}"
                )

        lines.extend([
            "",
            "---",
            "",
            "## 🌐 渠道网络变动",
            "",
        ])

        if not network_changes:
            lines.append("- 本轮无渠道网络状态变化。\n")
        else:
            for chg in network_changes:
                chg_type = chg.get("type")
                name = chg.get("name", "未知渠道")
                url = chg.get("base_url", "")
                link_text = f"[{name}]({url})" if url else f"**{name}**"
                if chg_type == "discovered":
                    rationale = chg.get("rationale") or "新发现可用招聘渠道"
                    lines.append(f"- 🆕 **新发现渠道**：{link_text} — {rationale}")
                elif chg_type == "degraded":
                    reason = chg.get("reason") or "渠道失效或不可访问"
                    lines.append(f"- ⚠️ **渠道降级**：{link_text} — {reason}")
                elif chg_type == "reactivated":
                    lines.append(f"- 🔄 **渠道恢复**：{link_text} — 重新恢复活跃监测")
                else:
                    lines.append(f"- ℹ️ **渠道变动**：{link_text}")
            lines.append("")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path

    def _format_opportunity_block(self, opp: Opportunity) -> List[str]:
        lines = [
            f"### [{opp.canonical_job_title}]({opp.official_url})",
            f"- **用人单位**：{opp.organization}",
            f"- **地点/赛道**：{opp.location} | {opp.track}",
            f"- **推荐结论**：`{opp.latest_evaluation.final_recommendation if opp.latest_evaluation else '待评定'}`",
        ]
        if opp.opportunity_intent:
            intent_cn = {
                "APPLY_NOW": "即刻行动",
                "CONDITIONAL": "条件关注",
                "WATCH_LEARN": "情报观测",
            }.get(opp.opportunity_intent, opp.opportunity_intent)
            lines.append(f"- **行动意图**：`{opp.opportunity_intent} / {intent_cn}`")
        if opp.intent_rationale:
            lines.append(f"- **意图理由**：{opp.intent_rationale}")

        if opp.uncertain_links:
            links_str = ", ".join(opp.uncertain_links)
            lines.append(f"- **实体消歧状态**：`实体同一性待确认`（与既有岗位 `{links_str}` 存在部分重合但证据不足）")

        if opp.latest_evaluation and opp.latest_evaluation.dimension_evaluations:
            lines.append("- **多维资格判定与原文证据 (Requirement Evidence)**：")
            for dim, ev in opp.latest_evaluation.dimension_evaluations.items():
                state_badge = f"`{ev.state}`"
                evidence_snippet = (
                    f"“{ev.requirement_evidence}”" if ev.requirement_evidence else "（无）"
                )
                lines.append(
                    f"  - **{dim}** {state_badge}：{ev.rationale}  \n    *证据原文*：{evidence_snippet}"
                )
        lines.append("")
        return lines
