"""
Knowledge Graph Module
Neo4j schema definitions and graph operations.
"""

from .schema import (
    NodeType,
    RelationType,
    NODE_SCHEMAS,
    RELATION_SCHEMAS,
    get_node_schema,
    get_relation_schema,
    get_all_node_types,
    get_all_relation_types,
)

# SchemaManager 属于图谱落库模块（建图/管理 Neo4j，见后续 build_graph 步骤）。
# 抽取链路（schema + extractor + run_extraction）不依赖它，故延迟导入；
# 实现 schema_manager.py 后自动可用。
try:
    from .schema_manager import SchemaManager
except ImportError:
    SchemaManager = None  # type: ignore

__all__ = [
    "NodeType",
    "RelationType",
    "NODE_SCHEMAS",
    "RELATION_SCHEMAS",
    "get_node_schema",
    "get_relation_schema",
    "get_all_node_types",
    "get_all_relation_types",
    "SchemaManager",
]
