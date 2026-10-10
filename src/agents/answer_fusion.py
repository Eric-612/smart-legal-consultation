"""
Answer Fusion Agent
Combines all agent outputs into a coherent final answer
（法律版：字段语义复用 symptoms→法律问题要点、departments→推荐律师、medications→引用条文、advice→诉讼流程建议）
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.prompts import ChatPromptTemplate

from src.common.llm import get_llm
from src.common.logger import setup_logger
from src.agents.state import AgentState

logger = setup_logger(__name__, "agents.log")


SYSTEM_PROMPT = """你是一个专业的法律咨询客服。请将以下信息整合成一条连贯、专业的回答。

要求：
1. 语言专业但易懂
2. 结构清晰，可以使用标题和列表
3. 确保免责声明在回答末尾
4. 如果有紧急提示，放在回答开头
5. 不预测具体判决结果，不承诺胜诉

用户问题：{query}

意图类型：{intent}

法律问题要点：{symptoms}

推荐律师：{departments}

引用条文：{medications}

法律知识：{knowledge}

诉讼/维权建议：{advice}

免责声明：{disclaimers}

紧急提示：{warnings}

请整合以上信息，生成最终回答。"""


class AnswerFusionAgent:
    """Answer Fusion Agent"""

    def __init__(self):
        self.llm = get_llm(temperature=0.3)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", "请整合信息生成回答")
        ])

    def __call__(self, state: AgentState) -> dict:
        """Process state and return update"""
        logger.info("[AnswerFusion] Fusing answers...")

        query = state.get("query", "")
        intent = state.get("intent", "")
        issues = state.get("symptoms", [])
        lawyers = state.get("departments", [])
        clauses = state.get("medications", [])
        knowledge = state.get("knowledge_answer", "")
        advice = state.get("advice", [])
        disclaimers = state.get("disclaimers", [])
        warnings = state.get("warnings", [])
        needs_clarify = state.get("needs_clarification", False)
        clarification = state.get("clarification", "")

        # 正文只放"前端未单独结构化渲染"的散文：
        #   问题要点/律师/条文 → 前端标签区(chips)；紧急提示 → 前端 el-alert；免责声明 → 前端免责块。
        #   故正文不再嵌入这些，避免同一条律师/免责声明在界面出现两次。
        parts = []

        if needs_clarify and clarification:
            # 追问话术没有对应的结构化字段，必须放进正文
            parts.append("❓ " + clarification)
        elif intent == "case_analysis":
            if not lawyers:
                # 有事实但仍未命中律师时的兜底引导（律师若有则由前端标签展示）
                parts.append("🏛️ 律师建议：建议先到法律服务中心/12348 法律援助热线初筛，或补充案情细节后我再为您精准推荐。")
                parts.append("")
            if advice:
                parts.append("📋 维权/诉讼流程建议：")
                for a in advice:
                    parts.append(f"  - {a}")
        elif intent == "law_query":
            if knowledge:
                parts.append(knowledge)
        elif intent == "legal_knowledge":
            if knowledge:
                parts.append(knowledge)
        elif intent == "urgent":
            parts.append("您正面临紧急法律事项，请尽快咨询专业律师或拨打 12348 法律援助热线（详见上方紧急提示）。")

        final_answer = "\n".join(parts).strip()

        logger.info(f"[AnswerFusion] Final answer: {len(final_answer)} chars")

        return {
            "final_answer": final_answer,
            "messages": [f"[AnswerFusion] Generated final answer: {len(final_answer)} chars"]
        }


# Singleton instance
answer_fusion = AnswerFusionAgent()
