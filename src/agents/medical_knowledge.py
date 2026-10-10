"""
Legal Knowledge Agent（法律版，原 Medical Knowledge 迁移）—— 企业级「强制检索打底 + 可选 ReAct 多跳」(grounded-ReAct)

设计动机（沿用医疗版两次迭代后的终态）：
  v1 纯 ReAct（检索为可选工具）：评测发现模型约半数知识题**跳过检索**、凭记忆作答 →
     KG 没被用上、答案不可溯源（faithfulness 极低）。
  v2 纯强制检索：grounding 有保证，但没有工具调用能力、无法多跳。
  v3（当前）grounded-ReAct：
     Step 1 强制混合检索（FAISS 召回 → Neo4j 取事实）——**grounding 底线，必走**，
            保证每条事实答案都可溯源、模型无法跳过。
     Step 2 在检索结果之上，可选启用 ReAct 工具调用层做**多跳补充**
            （如"某纠纷的适用条文 → 该条文对应的争议/要件"），复用 src/agents/tools.py 的 @tool；
            settings.text2cypher_enabled 开启时额外提供 natural_language_graph_query
            （Text2Cypher，只读事务五层防护）。
            即便模型在 ReAct 里不调工具，grounding 仍由 Step 1 兜住（检索内容始终在 prompt 里）。
     Step 3 分风险兜底：检索为空时——一般法律知识题用 LLM 通用知识并标注"非知识库内容"；
            高风险（预测刑期/承诺结果/涉及必须由律师介入的敏感问题）**绝不臆测**，直接建议咨询律师。

  开关：settings.enable_react_layer（默认 True）。关闭则 Step 2 退化为纯 grounded 生成（更快更省）。

只写 state["knowledge_answer"]（+ retrieved_contexts/retrieved_entities/linked_entities + 调试 messages）。
节点名与导出单例名 `medical_knowledge` 不变 → graph.py 的 import/add_node/所有边**零改动**；
其后 safety_checker -> answer_fusion 照常运行，免责声明不丢。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from config.settings import settings
from src.knowledge_graph.schema import NodeType
from src.common.llm import get_llm
from src.common.logger import setup_logger
from src.common.memory import format_history
from src.agents.state import AgentState
# 复用「已测能力」的 @tool 薄封装（强制检索之外，供 ReAct 多跳调用）——也使 tools.py 不成为死代码
from src.agents.tools import (
    search_knowledge_graph,
    semantic_search,
    get_medication_info,
    natural_language_graph_query,  # Text2Cypher，按 settings.text2cypher_enabled 条件启用
)

logger = setup_logger(__name__, "agents.log")

_FALLBACK = "抱歉，我暂时无法回答这个问题，请咨询专业律师。"

# 高风险关键词：检索为空时这些问题绝不让 LLM 凭空答（法律执业红线）
_HIGH_RISK_KW = ["坐几年", "判几年", "判多少年", "刑期", "死刑", "无期徒刑", "能不能赢",
                 "能赢吗", "必输", "稳赢", "包赢", "保证赢", "胜诉率", "几成把握",
                 "会不会判", "怎么判", "取保候审能不能办", "缓刑"]

SAFE_DEFERRAL = ("本系统知识库未检索到关于「{query}」的权威数据。该问题涉及具体法律后果的预判，"
                 "为避免误导，请务必咨询专业律师，结合案情和证据进行评估。")

_GROUNDED_SYSTEM = "你是严谨的法律知识问答助手。只依据提供的知识库内容作答，绝不编造。"

_GROUNDED_PROMPT = """请**仅依据**下面的【知识库检索内容】回答用户问题。
要求：
1. 不要引入检索内容之外的事实；检索内容不足以完整回答时，明确指出"知识库暂无该部分数据"。
2. 通俗中文，结构清晰，可用列表。
3. 涉及具体法律适用或诉讼时，提醒"请咨询专业律师，以律师意见为准"。

【知识库检索内容】
{contexts}

【用户问题】
{query}"""

# ReAct 多跳层：强制检索内容作为主要依据已给出，工具仅用于多跳补充
_REACT_GROUNDED_SYSTEM = """你是法律咨询系统的"法律知识"专家。系统已**强制检索知识库**，得到如下内容，这是你作答的主要依据：
{contexts}
{entity_hints}
工作准则：
1. 优先依据上面的检索内容作答；若问题需要多跳补充（如"某纠纷的适用条文 → 该条文的构成要件/相关概念"），可调用工具 search_knowledge_graph / semantic_search / get_medication_info 进一步取证；需要灵活的多跳/聚合/条件查询时，可调用 natural_language_graph_query（自动生成只读 Cypher 查图谱）。
2. 绝不编造检索与工具之外的事实；查不到就如实说"知识库暂无该数据"。
3. 通俗中文，结构清晰，可用列表；涉及具体法律适用时提醒"请咨询专业律师"。"""

_GENERAL_FALLBACK_PROMPT = """本系统知识库**未检索到**与下面问题相关的内容。请基于通用法律知识**简要**回答，并且：
1. 开头第一行必须写：（以下为通用法律信息，非本系统知识库内容，仅供参考）
2. 不得预测具体判决结果、不得断言刑期/赔偿数额；涉及具体案件一律建议咨询专业律师。
3. 结尾提醒"具体法律适用请咨询专业律师"。

【用户问题】
{query}"""


def _is_high_risk(query: str) -> bool:
    """规则判定高风险（预测刑期/承诺结果/需律师介入的敏感问题）——检索为空时绝不臆测。"""
    return any(k in query for k in _HIGH_RISK_KW)


class MedicalKnowledgeAgent:
    """Grounded-ReAct knowledge agent: forced retrieval (grounding floor) + optional ReAct multi-hop."""

    def __init__(self):
        self.llm = get_llm(temperature=0.1)
        self.react_enabled = settings.enable_react_layer
        # ReAct 工具调用层（create_react_agent 已在 langgraph 内，无需新增依赖）
        react_tools = [search_knowledge_graph, semantic_search, get_medication_info]
        if settings.text2cypher_enabled:
            react_tools.append(natural_language_graph_query)  # Text2Cypher（只读五层防护）
        self.agent = create_react_agent(
            get_llm(temperature=0.1),
            tools=react_tools,
        )

    # ---------------- Step 1a: 按实体类型扩展 Neo4j 结构化事实 ----------------
    @staticmethod
    def _expand_entity(q, name: str, typ: str):
        """返回该实体的一段事实摘要文本；查无返回 None。绝不抛异常。"""
        try:
            if typ == NodeType.LAW.value:
                # 契约：第 5 步 graph_queries.py 实现 get_law_full_info
                info = q.get_law_full_info(name)
                if not info:
                    return None
                parts = [f"法律：{info['name']}"]
                if info.get("level"):
                    parts.append(f"效力层级：{info['level']}")
                if info.get("description"):
                    parts.append(f"简介：{info['description']}")
                clauses = [c.get("name") for c in info.get("clauses", []) if c.get("name")]
                if clauses:
                    parts.append("主要条文：" + "、".join(clauses[:8]))
                return "；".join(parts)

            if typ == NodeType.CLAUSE.value:
                info = q.get_clause_info(name)
                if not info:
                    return None
                parts = [f"条文：{info.get('name', name)}"]
                if info.get("content"):
                    parts.append(f"内容：{info['content']}")
                return "；".join(parts)

            if typ == NodeType.LEGAL_ISSUE.value:
                clauses = q.get_issue_clauses(name)
                ctxt = "、".join(c.get("name") for c in clauses if c.get("name"))
                laws = q.get_issue_laws(name)
                ltxt = "、".join(l.get("name") for l in laws if l.get("name"))
                parts = [f"争议类型：{name}"]
                if ctxt:
                    parts.append(f"适用条文：{ctxt}")
                if ltxt:
                    parts.append(f"相关法律：{ltxt}")
                ev = q.get_issue_evidence(name)
                evtxt = "、".join(e.get("name") for e in ev if e.get("name"))
                if evtxt:
                    parts.append(f"常见证据：{evtxt}")
                return "；".join(parts)

            if typ in (NodeType.CASE.value, "Case"):  # "Case" 为历史别名
                info = q.get_case_info(name)
                if not info:
                    return None
                parts = [f"案例：{info.get('name', name)}"]
                if info.get("summary"):
                    parts.append(f"案情：{info['summary']}")
                if info.get("court"):
                    parts.append(f"审理法院：{info['court']}")
                if info.get("result"):
                    parts.append(f"裁判结果：{info['result']}")
                return "；".join(parts)

            if typ == NodeType.EVIDENCE.value:
                info = q.get_evidence_info(name)
                if info:
                    parts = [f"证据：{info.get('name', name)}"]
                    if info.get("strength"):
                        parts.append(f"证明力等级：{info['strength']}")
                    if info.get("description"):
                        parts.append(f"说明：{info['description']}")
                    return "；".join(parts)
        except Exception as e:
            logger.warning(f"[LegalKnowledge] expand '{name}' failed: {e}")
        return None

    # ---------------- Step 1: 强制混合检索（grounding 底线，必走） ----------------
    def _retrieve(self, text: str, retriever=None):
        """确定性强制检索：FAISS 语义召回(+Neo4j 精确) → 按类型扩展 Neo4j 事实。
        返回 (contexts, used_hits)。绝不抛异常；contexts 为空 == 知识库未覆盖。

        Args:
            text: 检索文本
            retriever: 可复用的 VectorRetriever 实例（Step 0 实体链接已创建则传入，避免重复加载索引）
        """
        hits = []
        try:
            from src.vector_store.search import get_shared_retriever
            vr = retriever or get_shared_retriever()
            hits = vr.search(text, top_k=5) or []
        except Exception as e:
            logger.warning(f"[LegalKnowledge] vector retrieval failed: {e}")

        contexts, used, seen = [], [], set()
        try:
            from src.knowledge_graph.graph_queries import GraphQueries
            q = GraphQueries()
            for h in hits:
                name, typ = h.get("name", ""), h.get("type", "")
                if not name or name in seen:
                    continue
                seen.add(name)
                ctx = self._expand_entity(q, name, typ)
                if ctx:
                    contexts.append(ctx)
                    used.append({k: h.get(k) for k in ("name", "type", "score", "source")})
            # 兜底：把 query 本身当实体名再各查一次（query 可能就是"劳动合同法""拖欠工资"）
            for typ in (NodeType.LAW.value, NodeType.CLAUSE.value, NodeType.LEGAL_ISSUE.value):
                ctx = self._expand_entity(q, text.strip(), typ)
                if ctx and ctx not in contexts:
                    contexts.append(ctx)
            q.close()
        except Exception as e:
            logger.warning(f"[LegalKnowledge] graph expansion failed: {e}")
        return contexts, used

    # ---------------- ReAct 解析辅助 ----------------
    @staticmethod
    def _tool_calls_of(msg) -> list[str]:
        tc = getattr(msg, "tool_calls", None)
        if not tc and isinstance(msg, dict):
            tc = msg.get("tool_calls")
        if not tc:
            return []
        return [(c.get("name") if isinstance(c, dict) else getattr(c, "name", "")) for c in tc]

    @staticmethod
    def _final_text(msgs) -> str:
        for m in reversed(msgs):
            if isinstance(m, AIMessage) and m.content:
                return m.content
            if isinstance(m, dict) and m.get("type") == "ai" and m.get("content"):
                return m["content"]
        return ""

    # ---------------- Step 2 生成方式 ----------------
    def _grounded_llm(self, user_text: str, contexts: list) -> str:
        """纯 grounded 生成（不开 ReAct 或 ReAct 失败时的退回路径）。"""
        prompt = _GROUNDED_PROMPT.format(contexts="\n".join(f"- {c}" for c in contexts), query=user_text)
        return self.llm.invoke([SystemMessage(content=_GROUNDED_SYSTEM),
                                HumanMessage(content=prompt)]).content

    def _react_answer(self, user_text: str, contexts: list, entity_hints: str = ""):
        """在强制检索内容之上跑 ReAct 多跳；返回 (answer, 工具新增上下文, 工具调用名单)。

        Args:
            entity_hints: Step 0 实体链接结果拼成的提示文本（注入系统消息，供
                          Text2Cypher 等工具做精确查询条件）；无链接时传空串。
        """
        hints_block = f"\n{entity_hints}\n" if entity_hints else ""
        sys = _REACT_GROUNDED_SYSTEM.format(
            contexts="\n".join(f"- {c}" for c in contexts),
            entity_hints=hints_block,
        )
        res = self.agent.invoke({"messages": [SystemMessage(content=sys), HumanMessage(content=user_text)]})
        msgs = res["messages"]
        tool_ctxs = [m.content for m in msgs if isinstance(m, ToolMessage) and m.content]
        tool_calls = [name for m in msgs for name in self._tool_calls_of(m)]
        final = self._final_text(msgs) or self._grounded_llm(user_text, contexts)
        return final, tool_ctxs, tool_calls

    def _general_llm(self, user_text: str) -> str:
        prompt = _GENERAL_FALLBACK_PROMPT.format(query=user_text)
        return self.llm.invoke([SystemMessage(content=_GROUNDED_SYSTEM),
                                HumanMessage(content=prompt)]).content

    # ---------------- 主流程 ----------------
    def __call__(self, state: AgentState) -> dict:
        query = state.get("query", "")
        history = state.get("history", [])
        logger.info(f"[LegalKnowledge] Query: {query[:50]}... (history {len(history)})")
        user_text = (f"【对话历史】\n{format_history(history)}\n\n【本轮问题】\n{query}") if history else query

        # Step 1：强制检索（grounding 底线，必走）
        # 复用进程级共享检索器（启动时已预热），避免每请求重读索引/重载模型
        retriever = None
        try:
            from src.vector_store.search import get_shared_retriever
            retriever = get_shared_retriever()
        except Exception as e:
            logger.warning(f"[LegalKnowledge] retriever init failed: {e}")
        contexts, used = self._retrieve(user_text, retriever=retriever)
        logger.info(f"[LegalKnowledge] forced retrieval: entities={[h.get('name') for h in used]} ctx={len(contexts)}")

        # Step 2：显式实体链接（高精度：用户表述/检索命中 → 图谱规范实体锚点）
        # terms = 本轮问题要点 + 检索命中实体名 + 问题本身。
        # 注意：仅用"整句问题"做链接几乎必然低于 0.85 阈值（句子嵌入 vs 实体名嵌入），
        # 必须并入检索命中的实体名才能得到可用的锚点集——这些锚点既是回答的 grounding 来源，
        # 也作为实体提示注入 ReAct 提示词，供 Text2Cypher 等工具做精确查询条件。
        linked, hints_text = [], ""
        if retriever is not None:
            try:
                terms = (
                    list(state.get("symptoms", []))
                    + [h.get("name", "") for h in used if h.get("name")]
                    + [query]
                )
                linked = retriever.link_entities(terms)
                # 同一规范实体只保留相似度最高的一条锚点
                # （否则近义实体互相交叉链接，如 拖欠工资/欠薪/拖欠劳动报酬 两两互链，锚点会刷屏）
                best: dict = {}
                for lk in linked:
                    key = lk["matched_entity"]
                    if key not in best or lk["similarity"] > best[key]["similarity"]:
                        best[key] = lk
                linked = sorted(best.values(), key=lambda x: x["similarity"], reverse=True)
                if linked:
                    hints_text = (
                        "【已链接实体（高置信链接，建议用下列规范名做精确查询条件）】\n"
                        + "；".join(
                            f"{lk['input_entity']}→{lk['matched_entity']}({lk['type']},{lk['similarity']:.2f})"
                            for lk in linked
                        )
                    )
            except Exception as e:
                logger.warning(f"[LegalKnowledge] entity linking failed: {e}")
        logger.info(f"[LegalKnowledge] entity linking: {[lk['matched_entity'] for lk in linked]}")

        # Step 2/3：生成（grounded+ReAct / 纯 grounded / 分风险兜底）
        tool_calls, mode = [], ""
        try:
            if contexts:
                if self.react_enabled:
                    answer, tool_ctxs, tool_calls = self._react_answer(
                        user_text, contexts, entity_hints=hints_text
                    )
                    contexts = contexts + tool_ctxs          # 工具多跳结果并入 grounding（供 RAGAS）
                    mode = "grounded+react"
                else:
                    answer = self._grounded_llm(user_text, contexts)
                    mode = "grounded"
            elif _is_high_risk(query):
                answer = SAFE_DEFERRAL.format(query=query)
                mode = "defer-high-risk"
            else:
                answer = self._general_llm(user_text)
                mode = "general-fallback"
        except Exception as e:
            logger.error(f"[LegalKnowledge] generation error: {e}")
            answer, mode = _FALLBACK, "error"

        logger.info(f"[LegalKnowledge] mode={mode} answer={len(answer)} chars tools={tool_calls}")
        return {
            "knowledge_answer": answer,
            "retrieved_entities": used,                       # list[dict]，供观测
            "retrieved_contexts": contexts,                   # list[str]，供 RAGAS faithfulness/context
            "linked_entities": linked,                        # list[dict]，实体链接结果（API/前端展示）
            "messages": [f"[LegalKnowledge] mode={mode} entities={[h.get('name') for h in used]} "
                         f"ctx={len(contexts)} tools={tool_calls} "
                         f"linked={[lk['matched_entity'] for lk in linked]}"],
        }


# 单例名保持 medical_knowledge → graph.py 零改动
medical_knowledge = MedicalKnowledgeAgent()
