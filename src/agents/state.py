"""
LangGraph Agent State Definition
Defines the global state shared across all agents in the legal consultation system.

Usage:
    from src.agents.state import AgentState

    # Initialize state
    state: AgentState = {
        "query": "我公司拖欠工资三个月，可以申请劳动仲裁吗？",
        "messages": []
    }
"""

import operator
from typing import TypedDict, Optional, Annotated


# ============================================================
# Intent Types（法律版：case_analysis / law_query / legal_knowledge / urgent / general）
# 保留旧名作为别名，兼容 graph 路由与 API 层引用（状态图结构不变）
# ============================================================

class IntentType:
    """Intent type constants"""
    CASE_ANALYSIS = "case_analysis"      # 案例分析：描述纠纷事实，想了解法律适用与建议
    LAW_QUERY = "law_query"              # 条文引用：询问适用哪条法律、条文内容
    LEGAL_KNOWLEDGE = "legal_knowledge"  # 法律知识：咨询法律概念、常识
    URGENT = "urgent"                    # 紧急情况：刑事拘留、被起诉、开庭临近等，需立即行动
    GENERAL = "general"                  # 通用对话：非法律问题

    # 旧名别名（医疗版→法律版意图映射：appointment→case_analysis、medication→law_query、knowledge→legal_knowledge）
    APPOINTMENT = CASE_ANALYSIS
    MEDICATION = LAW_QUERY
    KNOWLEDGE = LEGAL_KNOWLEDGE
    EMERGENCY = URGENT

    ALL = [CASE_ANALYSIS, LAW_QUERY, LEGAL_KNOWLEDGE, URGENT, GENERAL]


# ============================================================
# Urgency Levels —— 统一定义于 src/knowledge_graph/schema.py（R1），此处转导入
# 原医疗版为 SeverityLevel；法律版语义为"法律事项紧急性"，保留 SeverityLevel 兼容别名
# ============================================================

from src.knowledge_graph.schema import UrgencyLevel  # noqa: E402

# 兼容旧的 SeverityLevel 引用
SeverityLevel = UrgencyLevel

# 兼容旧的 .ALL 用法（本文件自测与历史引用）
SEVERITY_ALL = [lvl.value for lvl in UrgencyLevel]


# ============================================================
# Agent State Definition
# ============================================================

class AgentState(TypedDict, total=False):
    """
    LangGraph Global State for Legal Consultation System

    All agents read from and write to this shared state.
    List fields use Annotated[..., operator.add] for accumulation across agents.

    字段语义（医疗版→法律版，字段名保持不变以保证状态图结构与接口稳定）：
        query: 用户原始问题
        intent: 意图类型 (case_analysis/law_query/legal_knowledge/urgent/general)
        symptoms: 提取出的法律问题要点（争议事实/关键词，原"症状"字段复用）
        severity: 法律事项紧急性 (low/medium/high/urgent)
        is_emergency: 是否为紧急法律情况（如被拘留、开庭临近）
        departments: 推荐的律师（原"科室"字段复用）
        medications: 引用的法律条文（原"药物"字段复用）
        knowledge_answer: 法律知识回答
        advice: 诉讼流程指导建议
        disclaimers: 强制法律免责声明
        warnings: 紧急法律警示（如尽快咨询律师）
        final_answer: 最终回答
        retrieved_entities: 从法律知识图谱检索到的实体
        linked_entities: 实体链接结果（用户表述 → 图谱规范实体）
        messages: 调试消息
    """

    # ===== User Input =====
    query: str  # 用户原始问题

    # ===== Conversation Memory（由 API 按 session_id 注入，不参与累加）=====
    history: list  # 历史轮次 [{role, content, ...}]，供 Agent 读取上下文

    # ===== Clarification（信息不足时的追问机制）=====
    needs_clarification: bool  # 是否需要向用户追问
    clarification: str         # 追问话术

    # ===== Intent Classification =====
    intent: str  # 意图类型: case_analysis | law_query | legal_knowledge | urgent | general
    intent_confidence: float  # 意图识别置信度 (0-1)

    # ===== 法律问题描述提取（原 Symptom Detection 字段复用）=====
    symptoms: Annotated[list[str], operator.add]  # 法律问题要点列表（累加）
    severity: str  # 法律事项紧急性: low | medium | high | urgent
    is_emergency: bool  # 是否为紧急法律情况

    # ===== 律师推荐（原 Department Recommendation 字段复用）=====
    departments: Annotated[list[str], operator.add]  # 推荐律师列表（累加）

    # ===== 条文引用（原 Medication Advice 字段复用）=====
    medications: Annotated[list[dict], operator.add]  # 引用法律条文列表（累加）
    # 每条条文: {"name": str, "clause_no": str, "law_name": str, "content": str}

    # ===== 法律知识 =====
    knowledge_answer: str  # 法律知识回答

    # ===== 诉讼流程指导（原 Pre-visit Advice 字段复用）=====
    advice: Annotated[list[str], operator.add]  # 诉讼流程指导建议列表（累加）

    # ===== Safety Check (Mandatory) =====
    disclaimers: Annotated[list[str], operator.add]  # 免责声明（累加，必须！）
    warnings: Annotated[list[str], operator.add]  # 紧急法律警示（累加）

    # ===== Final Output =====
    final_answer: str  # 最终回答

    # ===== Retrieved Entities =====
    retrieved_entities: Annotated[list[dict], operator.add]  # 检索到的法律知识图谱实体（累加）
    # 每个实体: {"name": str, "type": str, "score": float, "source": str}
    retrieved_contexts: Annotated[list, operator.add]  # ReAct 工具返回的检索上下文（供 RAGAS 评估）

    # ===== Linked Entities (Entity Linking) =====
    linked_entities: Annotated[list[dict], operator.add]  # 实体链接结果（累加）
    # 每条链接: {"input_entity": str, "matched_entity": str, "type": str, "similarity": float}
    # 由 legal_knowledge 的 Step0 显式实体链接产生，供 API 响应/前端展示/Text2Cypher 提示

    # ===== Debug Messages =====
    messages: Annotated[list[str], operator.add]  # 调试消息（累加）


# ============================================================
# Helper Functions
# ============================================================

def create_initial_state(query: str, history: list | None = None) -> AgentState:
    """
    Create initial state with user query (and optional conversation history)

    Args:
        query: User's question
        history: Prior conversation turns (from session memory)

    Returns:
        Initialized AgentState
    """
    return AgentState(
        query=query,
        history=history or [],
        needs_clarification=False,
        clarification="",
        intent="",
        intent_confidence=0.0,
        symptoms=[],
        severity="",
        is_emergency=False,
        departments=[],
        medications=[],
        knowledge_answer="",
        advice=[],
        disclaimers=[],
        warnings=[],
        final_answer="",
        retrieved_entities=[],
        retrieved_contexts=[],
        linked_entities=[],
        messages=[f"[START] User query: {query}"]
    )


def add_message(state: AgentState, message: str) -> dict:
    """
    Create update dict to add a debug message

    Args:
        state: Current state
        message: Message to add

    Returns:
        Update dict for state
    """
    return {"messages": [message]}


# ============================================================
# Main: Self-test
# ============================================================

if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("AGENT STATE TEST")
    print("=" * 60)

    # Test 1: Create initial state
    print("\n[TEST 1] Create initial state")
    state = create_initial_state("我公司拖欠工资三个月，可以申请劳动仲裁吗？")
    print(f"  query: {state['query']}")
    print(f"  intent: '{state['intent']}' (empty)")
    print(f"  symptoms: {state['symptoms']}")
    print(f"  messages: {state['messages']}")

    # Test 2: Simulate agent updates
    print("\n[TEST 2] Simulate agent updates")

    # Intent classifier update
    intent_update = {
        "intent": IntentType.CASE_ANALYSIS,
        "intent_confidence": 0.95,
        "messages": ["[IntentClassifier] Detected: case_analysis (0.95)"]
    }
    print(f"  Intent update: {intent_update['intent']}")

    # Issue extractor update
    issue_update = {
        "symptoms": ["拖欠工资", "违法解除劳动合同"],
        "severity": SeverityLevel.HIGH,
        "messages": "[IssueExtractor] Found: 拖欠工资, 违法解除劳动合同"
    }
    print(f"  Issue update: {issue_update['symptoms']}")

    # Lawyer recommender update
    lawyer_update = {
        "departments": ["张律师（劳动纠纷）", "李律师（劳动争议）"],
        "messages": "[LawyerRecommender] Recommended: 张律师, 李律师"
    }
    print(f"  Lawyer update: {lawyer_update['departments']}")

    # Safety checker update (mandatory!)
    safety_update = {
        "disclaimers": ["⚠️ 本建议仅供参考，不构成法律意见，请咨询专业律师。"],
        "messages": "[SafetyChecker] Added disclaimer"
    }
    print(f"  Safety update: disclaimer added")

    # Test 3: Verify list accumulation works
    print("\n[TEST 3] Verify list accumulation")
    print("  (In LangGraph, Annotated[list, operator.add] accumulates lists)")
    print("  Example: issues from multiple agents will be merged")

    # Test 4: Intent types
    print("\n[TEST 4] Intent types")
    for intent in IntentType.ALL:
        print(f"  - {intent}")

    # Test 5: Urgency levels (兼容别名 SeverityLevel)
    print("\n[TEST 5] Urgency levels")
    for level in SEVERITY_ALL:
        print(f"  - {level}")

    # Test 6: 旧名别名兼容（appointment→case_analysis 等）
    print("\n[TEST 6] Legacy aliases (appointment->case_analysis etc.)")
    assert IntentType.APPOINTMENT == IntentType.CASE_ANALYSIS == "case_analysis"
    assert IntentType.MEDICATION == IntentType.LAW_QUERY == "law_query"
    assert IntentType.KNOWLEDGE == IntentType.LEGAL_KNOWLEDGE == "legal_knowledge"
    assert IntentType.EMERGENCY == IntentType.URGENT == "urgent"
    print("  All legacy aliases map correctly")

    print("\n" + "=" * 60)
    print("[SUCCESS] Agent state tests passed!")
    print("=" * 60)
