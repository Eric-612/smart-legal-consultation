"""
Litigation Guide Agent（法律版，原 Pre-visit Advisor 迁移）
根据问题要点与推荐律师领域，给出简洁、实用且**与案情相关**的维权/诉讼流程指导。

为什么改：旧实现是"就医前建议"。法律版改为——LLM 依据问题要点+律师领域生成诉讼流程建议
（协商→投诉/仲裁→起诉 的路径、证据准备、时效提醒），并显式约束"建议必须与案情相关"；
LLM 失败时退回确定性通用建议。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.common.llm import get_llm
from src.common.logger import setup_logger
from src.agents.state import AgentState

logger = setup_logger(__name__, "agents.log")


class LitigationAdvice(BaseModel):
    """Litigation/维权流程指导结果"""
    advice: list[str] = Field(description="3-5 条简洁的维权/诉讼流程建议（每条一行，不含绝对化结论）")


SYSTEM_PROMPT = """你是资深诉讼/维权流程指导专家。根据当事人的【问题要点】与【推荐律师领域】，给出 3-5 条简洁、实用的维权/诉讼流程建议。

要求：
- 通用路径酌情包含：先与对方协商或书面函告 → 涉及劳动争议可先申请劳动仲裁 → 行政/消费类可向主管部门投诉举报 → 协商不成再考虑起诉/仲裁，注意主张的时效。
- 针对案情给出合理的**证据准备方向**（如欠薪→劳动合同、工资流水、考勤记录；借贷→借条/转账记录；合同违约→合同文本、往来函件），**绝不给出与案情无关的步骤**。
- 提醒常见时效（如劳动仲裁时效 1 年、普通诉讼时效 3 年）与管辖法院/仲裁机构，但不给出绝对化结论。
- 不替当事人下结论（不判断"必胜"），不承诺结果。
- 每条一行、简洁，不要寒暄。"""


class PreVisitAdvisorAgent:
    """Litigation Guide Agent (LLM-generated, case-relevant)."""

    def __init__(self):
        self.llm = get_llm(temperature=0.2)
        # 显式指定 function_calling：langchain-openai 1.x 默认 method="json_schema"，
        # DashScope 兼容接口不支持该 response_format（报 400 要求 messages 含 "json"）
        self.chain = self.llm.with_structured_output(LitigationAdvice, method="function_calling")
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", "【问题要点】{symptoms}\n【推荐律师领域】{departments}")
        ])

    def __call__(self, state: AgentState) -> dict:
        issues = state.get("symptoms", [])
        lawyers = state.get("departments", [])
        logger.info(f"[LitigationGuide] Issues: {issues}, Lawyers: {lawyers}")

        advice: list[str] = []
        try:
            msgs = self.prompt.format_messages(
                symptoms="、".join(issues) if issues else "（未明确）",
                departments="、".join(lawyers) if lawyers else "（未明确）",
            )
            advice = self.chain.invoke(msgs).advice or []
        except Exception as e:
            logger.warning(f"[LitigationGuide] LLM advice failed: {e}")
            advice = []

        # 确定性兜底（LLM 失败时仍给出安全的通用建议）
        if not advice:
            advice = [
                "先整理并保全证据（书面合同、转账/流水记录、聊天与函件等）",
                "明确自己的诉求与对方主体（单位全称/个人身份信息）",
                "劳动类纠纷可先向劳动监察投诉或申请劳动仲裁",
                "注意诉讼时效（普通 3 年），必要时尽快咨询律师",
            ]
            if lawyers:
                advice.append(f"建议咨询领域：{'、'.join(lawyers[:3])}")

        return {
            "advice": advice,
            "messages": [f"[LitigationGuide] Generated {len(advice)} advice items"]
        }


# 单例名保持 pre_visit_advisor → graph.py 零改动
pre_visit_advisor = PreVisitAdvisorAgent()
