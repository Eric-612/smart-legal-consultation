"""
Lawyer Recommender Agent（法律版，原 Department Recommender 迁移）
两级推荐 + 图谱兜底，推荐合适的律师/律所：
  Tier1 图谱候选（法律问题→专长律师 的宽松聚合）：作为可溯源参考喂给 LLM，含噪声，**不直接采用**。
  Tier2 LLM 取舍（结合 问题要点 + 图谱候选 + 对话历史 做最终决策）：过滤无关律师、图谱缺失时据法律常识补正；
        明确法律诉求（如"我要起诉离婚"）无需具体事实也可直接给出。
  兜底：LLM 返回空时回退 Tier1 图谱候选；两者皆空则置 needs_clarification 追问。
解决"知识图谱问题词表覆盖不足导致推荐为空"的问题——由 Tier2 LLM 据法律常识补正。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pydantic import BaseModel, Field

from src.common.llm import get_llm
from src.common.logger import setup_logger
from src.common.memory import format_history
from src.agents.state import AgentState

logger = setup_logger(__name__, "agents.log")


class LawyerFallback(BaseModel):
    """LLM 兜底律师推荐结果"""
    departments: list[str] = Field(description="推荐的合适律师/律所 1-3 位；若信息确实不足则返回空列表")
    reason: str = Field(default="", description="推荐理由（简短）")
    follow_up: str = Field(default="", description="若信息不足，需要向用户追问的具体内容")


LAWYER_FALLBACK_PROMPT = """你是资深法律咨询专家。请根据【问题要点】【本轮输入】【对话历史】推荐最合适的 1-3 位律师/律所。
【图谱参考候选律师】（由"法律问题→专长律师"宽松聚合而来，可能含噪声，仅供取舍参考）：{kg_candidates}

规则：
- 依据纠纷所属法律领域判断律师专长（如劳动纠纷→劳动法律师；离婚/继承→家事律师；房屋买卖/租赁→房产律师；交通事故/侵权→侵权律师；合同/借贷→合同律师；刑事案件→刑事辩护律师；公司/股权→公司法律师；知识产权→知产律师）。
- 给出 1-3 位律师，按优先级排序，并简述理由。
- 可参考图谱候选，但**必须过滤掉与本次纠纷明显不符的**（如劳动争议不应推荐刑事辩护律师，除非确有相关情形）；图谱缺了合适律师时可据法律常识补上（如"该领域资深律师"）。
- 若本轮是明确的法律诉求（如"我要起诉离婚""想请个刑事辩护律师"），即使没有具体事实也直接给出对应领域律师。
- 只有当信息确实太少、无法判断时，departments 才返回空列表，并在 follow_up 写明需要追问的内容（纠纷类型、争议金额、对方主体、所处阶段等）。
- 只输出结构化结果，不要寒暄。

示例：
- 本轮"我公司拖欠工资" → departments:["劳动法律师"]（或 ["劳动法律师","劳动争议仲裁代理律师"]）
- 本轮"我要起诉离婚" → departments:["婚姻家事律师"]（明确诉求，无需事实）
- 本轮"我该请什么律师"（无任何事实/诉求）→ departments:[]，follow_up:"请描述您的纠纷类型、争议金额、目前所处阶段等"。"""


class DepartmentRecommenderAgent:
    """Lawyer Recommender Agent with 2-tier fallback"""

    def __init__(self):
        self.llm = get_llm(temperature=0.1)
        # 显式指定 function_calling：langchain-openai 1.x 默认 method="json_schema"，
        # DashScope 兼容接口不支持该 response_format（报 400 要求 messages 含 "json"）
        self.fallback_chain = self.llm.with_structured_output(LawyerFallback, method="function_calling")

    # ---------- Tier 1: 图谱候选 ----------
    def _tier_graph(self, issues: list[str]) -> list[str]:
        lawyers: list[str] = []
        try:
            from src.knowledge_graph.graph_queries import GraphQueries
            q = GraphQueries()
            for issue in issues:
                # 契约：Lawyer 节点经 SPECIALIZES_IN 关联 LegalIssue；第 5 步实现 graph_queries.py
                for lawyer in q.get_issue_lawyers(issue)[:3]:
                    lawyers.append(lawyer.get("name") or lawyer)
            q.close()
        except Exception as e:
            logger.warning(f"[LawyerRecommender] graph tier error: {e}")
        return list(dict.fromkeys(lawyers))

    # ---------- Tier 2: LLM 推荐（结合问题 + 图谱候选，做最终取舍） ----------
    def _tier_llm(self, issues: list[str], query: str, history: list, kg_candidates: list[str]) -> LawyerFallback:
        from langchain_core.prompts import ChatPromptTemplate
        prompt = ChatPromptTemplate.from_messages([
            ("system", LAWYER_FALLBACK_PROMPT),
            ("user", "【问题要点】{symptoms}\n【本轮输入】{query}\n【对话历史】{history}")
        ])
        msgs = prompt.format_messages(
            kg_candidates="、".join(kg_candidates) if kg_candidates else "（无）",
            symptoms="、".join(issues) if issues else "（未明确）",
            query=query,
            history=format_history(history),
        )
        return self.fallback_chain.invoke(msgs)

    def __call__(self, state: AgentState) -> dict:
        issues = state.get("symptoms", [])
        query = state.get("query", "")
        history = state.get("history", [])
        logger.info(f"[LawyerRecommender] Issues: {issues}")

        # Tier 1：图谱候选（法律问题→专长律师的宽松聚合），用于溯源 + 给 LLM 当参考；含噪声，不直接采用
        kg_lawyers = self._tier_graph(issues) if issues else []

        # Tier 2：LLM 推荐做最终取舍——结合问题与图谱候选，过滤噪声，图谱缺失时补上正确领域律师
        lawyers: list[str] = []
        follow_up = ""
        try:
            fb = self._tier_llm(issues, query, history, kg_candidates=kg_lawyers)
            lawyers = (fb.departments or [])[:5]
            follow_up = fb.follow_up or ""
            logger.info(f"[LawyerRecommender] LLM -> {lawyers} | reason={fb.reason}")
        except Exception as e:
            logger.error(f"[LawyerRecommender] LLM error: {e}")

        # 融合：LLM 优先；LLM 为空时回退图谱候选
        if lawyers:
            source = "llm+graph" if kg_lawyers else "llm"
        elif kg_lawyers:
            lawyers = kg_lawyers[:5]
            source = "graph"
        else:
            source = "none"

        logger.info(f"[LawyerRecommender] Recommended: {lawyers} (source={source}, kg={kg_lawyers})")

        update = {
            "departments": lawyers,
            "messages": [f"[LawyerRecommender] Recommended: {lawyers} (source={source})"]
        }

        if lawyers:
            # 已能确定律师 → 取消上游"无事实→追问"的默认追问（如"我要起诉离婚"→家事律师，无需追问）
            update["needs_clarification"] = False
        elif follow_up:
            # 确实信息不足 → 追问
            update["needs_clarification"] = True
            update["clarification"] = follow_up

        return update


# 单例名保持 department_recommender → graph.py 零改动
department_recommender = DepartmentRecommenderAgent()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("LAWYER RECOMMENDER AGENT TEST (2-tier)")
    print("=" * 60)

    for issues in [["拖欠工资", "违法解除劳动合同"], ["离婚财产分割", "子女抚养权"]]:
        print(f"\nIssues: {issues}")
        result = department_recommender({"symptoms": issues, "query": "想请律师", "history": []})
        print(f"  -> {result['departments']}")

    print("\n" + "=" * 60)
