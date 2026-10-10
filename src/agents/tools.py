"""
Agent Tools (LangChain @tool)
把"已有且已测过的能力"（法律知识图谱查询 / 向量检索 / 条文查询）包装成工具，
供 ReAct 自主 Agent 在需要时调用。每个工具的 docstring 即模型判断"何时调用"的依据。
（法律版：工具名保持与医疗版一致，内部查询逻辑换为法律实体；图谱查询层契约见第 5 步 graph_queries.py）

注意：工具返回值一律为 str（create_react_agent 的 ToolNode 需要可序列化文本）。
工具内部对 Neo4j / 向量库的失败做兜底，返回"查询失败/未找到"文本，绝不抛异常打断 ReAct 循环。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.tools import tool

from src.common.logger import setup_logger

logger = setup_logger(__name__, "tools.log")


def _graph():
    from src.knowledge_graph.graph_queries import GraphQueries
    return GraphQueries()


@tool
def search_knowledge_graph(entity: str) -> str:
    """根据"法律名/条文名/争议类型"查询法律知识图谱，返回其 法律/条文/争议/相关证据 的摘要文本。
    当用户询问某部法律的适用范围、某条文的内容、某类纠纷的适用法律时使用。
    若图谱中查无该实体，返回"未找到"说明，不要据此编造。"""
    try:
        q = _graph()
        # 契约：第 5 步 graph_queries.py 实现 get_law_info / get_law_clauses / get_issue_clauses 等
        info = q.get_law_info(entity)
        if info:
            clauses = q.get_law_clauses(entity)
            clauses_txt = "、".join(c.get("name", "") for c in clauses if c.get("name"))
            parts = [f"法律：{info.get('name', '')}"]
            if info.get("level"):
                parts.append(f"效力层级：{info['level']}")
            if info.get("description"):
                parts.append(f"简介：{info['description']}")
            if clauses_txt:
                parts.append(f"主要条文：{clauses_txt}")
            q.close()
            return "；".join(parts)
        clause = q.get_clause_info(entity)
        if clause:
            q.close()
            parts = [f"条文：{clause.get('name', entity)}"]
            if clause.get("content"):
                parts.append(f"内容：{clause['content']}")
            return "；".join(parts)
        issue_clauses = q.get_issue_clauses(entity)
        q.close()
        if issue_clauses:
            return f"争议「{entity}」可能适用的条文：{'、'.join(c.get('name', '') for c in issue_clauses if c.get('name'))}"
        return f"未在法律知识图谱中找到实体「{entity}」"
    except Exception as e:
        logger.warning(f"[tool search_knowledge_graph] {e}")
        return f"查询法律知识图谱失败：{e}"


@tool
def semantic_search(query: str) -> str:
    """对法律知识库做语义（向量）检索，返回最相关实体列表（名称/类型/相似度）。
    当用户表述与图谱实体名不一致、需要模糊语义匹配时使用。"""
    try:
        # 进程级共享检索器（启动时已预热）：避免每次工具调用重读索引/重载模型
        from src.vector_store.search import get_shared_retriever
        vr = get_shared_retriever()
        hits = vr.search(query, top_k=5)
        if not hits:
            return "语义检索无相关结果"
        lines = [f"{h.get('name', '')}（{h.get('type', '')}, {h.get('score', 0):.2f}）" for h in hits]
        return "语义检索结果：" + "；".join(lines)
    except Exception as e:
        logger.warning(f"[tool semantic_search] {e}")
        return f"语义检索失败：{e}"


@tool
def get_medication_info(name: str) -> str:
    """查询某部法律/某条文的信息（效力层级/简介/主要条文内容/相关争议）。
    当用户询问某部法律或某条条文的具体内容、适用范围、相关争议时使用。"""
    try:
        q = _graph()
        info = q.get_law_info(name)
        if info:
            clauses = q.get_law_clauses(name)
            clauses_txt = "、".join(c.get("name", "") for c in clauses if c.get("name"))
            parts = [f"法律：{info.get('name', '')}"]
            if info.get("level"):
                parts.append(f"效力层级：{info['level']}")
            if info.get("description"):
                parts.append(f"简介：{info['description']}")
            if clauses_txt:
                parts.append(f"主要条文：{clauses_txt}")
            q.close()
            return "；".join(parts)
        clause = q.get_clause_info(name)
        q.close()
        if not clause:
            return f"未在法律知识图谱中找到「{name}」"
        parts = [f"条文：{clause.get('name', name)}"]
        if clause.get("content"):
            parts.append(f"内容：{clause['content']}")
        return "；".join(parts)
    except Exception as e:
        logger.warning(f"[tool get_medication_info] {e}")
        return f"查询法律信息失败：{e}"


@tool
def natural_language_graph_query(query: str) -> str:
    """用自然语言灵活查询法律知识图谱（内部自动生成并执行只读 Cypher，即 Text2Cypher）。
    比 search_knowledge_graph 更适合复杂/灵活的查询：多跳关系、条件过滤、聚合列举等
    （如"拖欠工资适用哪部法律的哪些条文""哪些条文规定了双倍工资赔偿"）。
    建议在 query 中带上已知的规范实体名（可先参考 semantic_search 的链接结果）。
    查询在只读事务中执行并有记录数上限；返回结构化图谱记录，无法生成有效查询时返回说明文本。"""
    try:
        from src.knowledge_graph.text2cypher import get_engine
        result = get_engine().run(query)
        return result.get("text") or "图谱查询无结果"
    except Exception as e:
        logger.warning(f"[tool natural_language_graph_query] {e}")
        return f"图谱查询失败：{e}"
