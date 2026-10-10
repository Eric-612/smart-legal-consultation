"""
Clause Citer Agent（法律版，原 Medication Advisor 迁移）
针对"有具体问题的条文引用"咨询，给出审慎、可溯源的法律条文引用。

为什么改：旧实现按"症状→疾病→药物"宽松聚合图谱并**直接列出药物**。法律版改为——
图谱条文仅作参考，由 LLM 按法律引用红线审慎取舍（不臆造条文、不遗漏关键构成要件），
并正面回答用户的实际问题（如"适用哪条法律""赔偿标准是多少"）。
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
from src.common.memory import format_history
from src.agents.state import AgentState

logger = setup_logger(__name__, "agents.log")


class ClauseAdvice(BaseModel):
    """LLM 法律条文引用结果"""
    advice: str = Field(description="针对用户法律问题的审慎解答（2-4 句）：可能的请求权基础、适用哪部法律、应关注哪些要件")
    medications: list[str] = Field(description="可引用的关键法律条文名称（0-3 条，如'中华人民共和国劳动合同法 第三十条'）；拿不准或不应自行引用时返回空列表")


SYSTEM_PROMPT = """你是严谨的法律条文引用专家。请根据【问题要点】【用户问题】给出**审慎、准确**的法律条文引用。
【图谱参考条文】（由"法律问题→条文"宽松聚合而来，可能含与本次问题无关或已失效的条文，仅供你判断参考，切勿直接照搬）：{kg_meds}

法律引用红线：
1. **绝不**引用与本次问题明显无关的条文，或虚构/篡改条文序号与内容；拿不准时就引用部法律层面（如"《劳动合同法》关于劳动报酬的规定"），不硬编具体条号。
2. 仅当确属常见问题时，提及 1-3 条直接相关的条文（写全法律全称 + 条号，如"《中华人民共和国劳动合同法》第三十条"）；拿不准就返回空列表并建议咨询律师。
3. 必须正面回答用户的实际问题（如"适用哪条法律""赔偿标准"）：明确指出请求权基础与构成要件（谁主张、对谁、什么事实、依据哪条），但**不代替法官下结论**。
4. 始终提醒"具体适用需结合案情，以律师意见和裁判实践为准"，不给出绝对化的胜诉判断。
只输出结构化结果，不要寒暄。"""


class MedicationAdvisorAgent:
    """Clause Citer Agent (LLM-based, citation-safe)."""

    def __init__(self):
        self.llm = get_llm(temperature=0.1)
        # 显式指定 function_calling：langchain-openai 1.x 默认 method="json_schema"，
        # DashScope 兼容接口不支持该 response_format（报 400 要求 messages 含 "json"）
        self.chain = self.llm.with_structured_output(ClauseAdvice, method="function_calling")
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", "【问题要点】{symptoms}\n【用户问题】{query}\n【对话历史】{history}")
        ])

    @staticmethod
    def _kg_clauses(issues: list[str]) -> list[str]:
        """图谱候选条文（仅作参考，含噪声）"""
        names: list[str] = []
        try:
            from src.knowledge_graph.graph_queries import GraphQueries
            q = GraphQueries()
            for issue in issues:
                # 契约：Clause 节点经 REGULATES 关联 LegalIssue；第 5 步实现 graph_queries.py
                for clause in q.get_issue_clauses(issue):
                    if clause.get("name"):
                        names.append(clause["name"])
            q.close()
        except Exception as e:
            logger.warning(f"[ClauseCiter] kg clauses failed: {e}")
        return list(dict.fromkeys(names))[:10]

    def __call__(self, state: AgentState) -> dict:
        query = state.get("query", "")
        issues = state.get("symptoms", [])
        history = state.get("history", [])
        logger.info(f"[ClauseCiter] Query: {query[:50]}..., issues={issues}")

        kg_clauses = self._kg_clauses(issues)
        advice_text = ""
        clause_names: list[str] = []
        try:
            msgs = self.prompt.format_messages(
                kg_meds="、".join(kg_clauses) if kg_clauses else "（无）",
                symptoms="、".join(issues) if issues else "（未明确）",
                query=query,
                history=format_history(history),
            )
            res = self.chain.invoke(msgs)
            advice_text = res.advice or ""
            clause_names = res.medications or []
            logger.info(f"[ClauseCiter] LLM clauses={clause_names}")
        except Exception as e:
            logger.error(f"[ClauseCiter] LLM error: {e}")

        # 兜底：LLM 失败也给安全建议，绝不输出空答案
        if not advice_text:
            advice_text = "该问题涉及具体法律适用，建议咨询专业律师，结合案情和证据评估适用的法律条文。"

        # 条文格式：{"name": 完整名, "law_name": 法律名, "clause_no": 条号, "content": ""}
        # 兼容两种写法："中华人民共和国劳动合同法 第三十条"（空格分隔）与 "《中华人民共和国劳动法》第五十条"（书名号+条号）
        import re
        clauses = []
        for n in clause_names[:3]:
            m = re.match(r'^(《?[^《》\s]+》?)\s*(第[^条\s]+条)$', n)
            if m:
                law_name, clause_no = m.group(1), m.group(2)
            else:
                parts = n.split()
                law_name = parts[0] if parts else n
                clause_no = parts[1] if len(parts) > 1 else ""
            clauses.append({"name": n, "clause_no": clause_no, "law_name": law_name, "content": ""})

        return {
            "medications": clauses,          # 引用的法律条文，由 answer_fusion 渲染
            "knowledge_answer": advice_text,  # 条文引用解答文本
            "messages": [f"[ClauseCiter] advice={len(advice_text)} chars, clauses={clause_names}"]
        }


# 单例名保持 medication_advisor → graph.py 零改动
medication_advisor = MedicationAdvisorAgent()
