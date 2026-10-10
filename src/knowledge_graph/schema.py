"""
Neo4j Knowledge Graph Schema Definitions
Defines 8 node types and 10 relation types for the legal knowledge graph.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# Node Types (8 types)
# ============================================================

class NodeType(str, Enum):
    """Neo4j node labels"""
    LAW = "Law"
    CLAUSE = "Clause"
    LEGAL_ISSUE = "LegalIssue"
    CASE = "Case"
    LEGAL_CONCEPT = "LegalConcept"
    LAWYER = "Lawyer"
    LAW_FIRM = "LawFirm"
    EVIDENCE = "Evidence"


@dataclass
class NodeSchema:
    """Schema definition for a node type"""
    label: str
    properties: dict[str, str]  # property_name: data_type
    unique_constraint: Optional[str] = None  # property for unique constraint
    indexes: list[str] = field(default_factory=list)  # properties to index
    description: str = ""


# Node schemas with properties and constraints
NODE_SCHEMAS: dict[NodeType, NodeSchema] = {
    NodeType.LAW: NodeSchema(
        label="Law",
        properties={
            "name": "string",
            "level": "string",  # constitution/law/administrative_regulation/judicial_interpretation/local_regulation/department_rule
            "publish_date": "string",
            "effective_date": "string",
            "issuing_authority": "string",
            "description": "string",
            "created_at": "datetime",
            "updated_at": "datetime",
        },
        unique_constraint="name",
        indexes=["name", "level"],
        description="法律法规节点，如：中华人民共和国劳动合同法、民法典"
    ),
    NodeType.CLAUSE: NodeSchema(
        label="Clause",
        properties={
            "name": "string",  # 唯一名：法律名 + 条号，如 "劳动合同法 第三十条"
            "clause_no": "string",  # 条号，如：第三十条
            "law_name": "string",  # 所属法律名称
            "content": "string",  # 条文内容
            "description": "string",
        },
        unique_constraint="name",
        indexes=["name", "law_name", "clause_no"],
        description="法律条文节点，如：劳动合同法第三十条、刑法第二百六十四条"
    ),
    NodeType.LEGAL_ISSUE: NodeSchema(
        label="LegalIssue",
        properties={
            "name": "string",
            "description": "string",
            "category": "string",  # labor/marriage_family/contract/tort/criminal/administrative/property/company/ip/consumer/other
            "urgency": "string",  # low/medium/high/urgent
        },
        unique_constraint="name",
        indexes=["name", "category", "urgency"],
        description="法律争议节点，如：拖欠工资、违法解除劳动合同、交通事故赔偿"
    ),
    NodeType.CASE: NodeSchema(
        label="Case",
        properties={
            "name": "string",  # 案件标题，如：张某诉某公司劳动报酬纠纷案
            "summary": "string",
            "court": "string",
            "judgment_date": "string",
            "result": "string",  # 裁判结果
        },
        unique_constraint="name",
        indexes=["name", "court"],
        description="案例节点，如：王某诉某科技公司解除劳动合同案"
    ),
    NodeType.LEGAL_CONCEPT: NodeSchema(
        label="LegalConcept",
        properties={
            "name": "string",
            "definition": "string",  # 概念定义
        },
        unique_constraint="name",
        indexes=["name"],
        description="法律概念节点，如：劳动关系、举证责任、诉讼时效"
    ),
    NodeType.LAWYER: NodeSchema(
        label="Lawyer",
        properties={
            "name": "string",
            "specialty": "string",  # 专长方向，如：劳动纠纷、婚姻家事
            "experience_years": "integer",
            "bar_number": "string",  # 执业证号
            "firm_name": "string",  # 所属律所
        },
        unique_constraint="name",
        indexes=["name", "specialty", "firm_name"],
        description="律师节点，如：张三（劳动法专业律师）"
    ),
    NodeType.LAW_FIRM: NodeSchema(
        label="LawFirm",
        properties={
            "name": "string",
            "city": "string",
            "description": "string",
        },
        unique_constraint="name",
        indexes=["name", "city"],
        description="律师事务所节点，如：北京市盈科律师事务所"
    ),
    NodeType.EVIDENCE: NodeSchema(
        label="Evidence",
        properties={
            "name": "string",
            "description": "string",
            "strength": "string",  # A/B/C/D 证据强度
        },
        unique_constraint="name",
        indexes=["name"],
        description="证据类型节点，如：劳动合同、工资银行流水、录音录像"
    ),
}


# ============================================================
# Relation Types (10 types)
# ============================================================

class RelationType(str, Enum):
    """Neo4j relationship types"""
    CONTAINS = "CONTAINS"                    # (Law)-[:CONTAINS]->(Clause)
    REGULATES = "REGULATES"                  # (Clause)-[:REGULATES]->(LegalIssue)
    INVOLVES = "INVOLVES"                    # (Case)-[:INVOLVES]->(LegalIssue)
    CITES = "CITES"                          # (Case)-[:CITES]->(Clause)
    SPECIALIZES_IN = "SPECIALIZES_IN"        # (Lawyer)-[:SPECIALIZES_IN]->(LegalIssue)
    EMPLOYS = "EMPLOYS"                      # (LawFirm)-[:EMPLOYS]->(Lawyer)
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"        # (LegalIssue)-[:NEEDS_EVIDENCE]->(Evidence)
    DEFINES = "DEFINES"                      # (Clause)-[:DEFINES]->(LegalConcept)
    RELATED_TO = "RELATED_TO"                # (LegalIssue)-[:RELATED_TO]->(LegalIssue)
    APPLIES = "APPLIES"                      # (Case)-[:APPLIES]->(Law)


# ============================================================
# Value-Vocabulary Enums（抽取层与 Agent 层共用的值域契约）
# ============================================================

class LawLevel(str, Enum):
    """法律效力层级（超集契约：抽取层与 Agent 层共用此定义）"""
    CONSTITUTION = "constitution"
    LAW = "law"
    ADMINISTRATIVE_REGULATION = "administrative_regulation"
    JUDICIAL_INTERPRETATION = "judicial_interpretation"
    LOCAL_REGULATION = "local_regulation"
    DEPARTMENT_RULE = "department_rule"


class UrgencyLevel(str, Enum):
    """法律事项紧急性"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class EvidenceStrength(str, Enum):
    """证据强度等级"""
    A = "A"  # 强证据（如书面合同原件）
    B = "B"  # 中证据（如银行流水）
    C = "C"  # 弱证据（如口头证言）
    D = "D"  # 需补充的证据


class IssueCategory(str, Enum):
    """法律争议类别（抽取层概念）。

    注意：这是描述法律争议语义类别的抽取字段值，不是图关系类型。
    """
    LABOR = "labor"                    # 劳动纠纷
    MARRIAGE_FAMILY = "marriage_family"  # 婚姻家事
    CONTRACT = "contract"              # 合同纠纷
    TORT = "tort"                      # 侵权纠纷
    CRIMINAL = "criminal"              # 刑事
    ADMINISTRATIVE = "administrative"  # 行政
    PROPERTY = "property"              # 物权/房产
    COMPANY = "company"                # 公司/商事
    INTELLECTUAL_PROPERTY = "intellectual_property"  # 知识产权
    CONSUMER = "consumer"              # 消费者权益
    OTHER = "other"                    # 其他


@dataclass
class RelationSchema:
    """Schema definition for a relation type"""
    type: str
    start_node: NodeType
    end_node: NodeType
    properties: dict[str, str] = field(default_factory=dict)
    description: str = ""


# Relation schemas with start/end nodes and properties
RELATION_SCHEMAS: dict[RelationType, RelationSchema] = {
    RelationType.CONTAINS: RelationSchema(
        type="CONTAINS",
        start_node=NodeType.LAW,
        end_node=NodeType.CLAUSE,
        properties={},
        description="法律-法条关系（法律包含法条）"
    ),
    RelationType.REGULATES: RelationSchema(
        type="REGULATES",
        start_node=NodeType.CLAUSE,
        end_node=NodeType.LEGAL_ISSUE,
        properties={},
        description="法条-法律争议关系（法条规制某类争议）"
    ),
    RelationType.INVOLVES: RelationSchema(
        type="INVOLVES",
        start_node=NodeType.CASE,
        end_node=NodeType.LEGAL_ISSUE,
        properties={},
        description="案例-法律争议关系（案例涉及某类争议）"
    ),
    RelationType.CITES: RelationSchema(
        type="CITES",
        start_node=NodeType.CASE,
        end_node=NodeType.CLAUSE,
        properties={},
        description="案例-法条关系（案例援引某法条）"
    ),
    RelationType.SPECIALIZES_IN: RelationSchema(
        type="SPECIALIZES_IN",
        start_node=NodeType.LAWYER,
        end_node=NodeType.LEGAL_ISSUE,
        properties={},
        description="律师-法律争议关系（律师专长方向）"
    ),
    RelationType.EMPLOYS: RelationSchema(
        type="EMPLOYS",
        start_node=NodeType.LAW_FIRM,
        end_node=NodeType.LAWYER,
        properties={},
        description="律所-律师关系（律所聘用律师）"
    ),
    RelationType.NEEDS_EVIDENCE: RelationSchema(
        type="NEEDS_EVIDENCE",
        start_node=NodeType.LEGAL_ISSUE,
        end_node=NodeType.EVIDENCE,
        properties={"necessity": "string"},  # required/recommended/optional
        description="法律争议-证据关系（争议所需证据）"
    ),
    RelationType.DEFINES: RelationSchema(
        type="DEFINES",
        start_node=NodeType.CLAUSE,
        end_node=NodeType.LEGAL_CONCEPT,
        properties={},
        description="法条-法律概念关系（法条界定某概念）"
    ),
    RelationType.RELATED_TO: RelationSchema(
        type="RELATED_TO",
        start_node=NodeType.LEGAL_ISSUE,
        end_node=NodeType.LEGAL_ISSUE,
        properties={},
        description="法律争议-法律争议相关关系"
    ),
    RelationType.APPLIES: RelationSchema(
        type="APPLIES",
        start_node=NodeType.CASE,
        end_node=NodeType.LAW,
        properties={},
        description="案例-法律关系（案例适用某法律）"
    ),
}


# ============================================================
# Utility Functions
# ============================================================

def get_node_schema(node_type: NodeType) -> NodeSchema:
    """Get schema for a node type"""
    return NODE_SCHEMAS[node_type]


def get_relation_schema(relation_type: RelationType) -> RelationSchema:
    """Get schema for a relation type"""
    return RELATION_SCHEMAS[relation_type]


def get_all_node_types() -> list[NodeType]:
    """Get all node types"""
    return list(NodeType)


def get_all_relation_types() -> list[RelationType]:
    """Get all relation types"""
    return list(RelationType)


# ============================================================
# Cypher Generation
# ============================================================

def generate_constraint_cypher() -> list[str]:
    """Generate Cypher statements for unique constraints"""
    statements = []
    for node_type, schema in NODE_SCHEMAS.items():
        if schema.unique_constraint:
            prop = schema.unique_constraint
            stmt = f"""
CREATE CONSTRAINT {schema.label.lower()}_{prop}_unique IF NOT EXISTS
FOR (n:{schema.label}) REQUIRE n.{prop} IS UNIQUE"""
            statements.append(stmt.strip())
    return statements


def generate_index_cypher() -> list[str]:
    """Generate Cypher statements for indexes"""
    statements = []
    for node_type, schema in NODE_SCHEMAS.items():
        for prop in schema.indexes:
            if prop != schema.unique_constraint:  # Skip if already has constraint
                stmt = f"""
CREATE INDEX {schema.label.lower()}_{prop}_idx IF NOT EXISTS
FOR (n:{schema.label}) ON (n.{prop})"""
                statements.append(stmt.strip())
    return statements


def generate_full_schema_cypher() -> str:
    """Generate complete schema initialization Cypher script"""
    lines = [
        "// ============================================",
        "// Legal Knowledge Graph Schema",
        "// Generated by schema.py",
        "// ============================================",
        "",
        "// ===== Unique Constraints =====",
    ]

    for stmt in generate_constraint_cypher():
        lines.append(stmt + ";")
        lines.append("")

    lines.append("// ===== Indexes =====")

    for stmt in generate_index_cypher():
        lines.append(stmt + ";")
        lines.append("")

    lines.append("// ===== Verification =====")
    lines.append("CALL db.constraints();")
    lines.append("CALL db.indexes();")

    return "\n".join(lines)


def generate_llm_schema_text() -> str:
    """Generate a compact graph Schema description for LLM prompts (Text2Cypher).

    供 Text2Cypher 引擎注入系统提示词：让 LLM 看着 Schema 生成合法 Cypher。
    纯静态生成（基于 NODE_SCHEMAS / RELATION_SCHEMAS），不依赖数据库连接。
    三段式：节点类型（含属性）/ 关系类型（含方向三元组）/ 查询约定（只读+LIMIT）。
    """
    lines = ["【节点类型】"]
    for schema in NODE_SCHEMAS.values():
        props = ", ".join(schema.properties.keys())
        lines.append(f"- {schema.label}（{schema.description}）属性: {props}")

    lines.append("")
    lines.append("【关系类型】格式：(起点)-[:关系]->(终点)")
    for schema in RELATION_SCHEMAS.values():
        rel_props = (
            f"，关系属性: {', '.join(schema.properties.keys())}"
            if schema.properties else ""
        )
        lines.append(
            f"- ({schema.start_node.value})-[:{schema.type}]->({schema.end_node.value}) "
            f"{schema.description}{rel_props}"
        )

    lines.append("")
    lines.append("【查询约定】")
    lines.append("- 节点一般用 name 属性匹配；Clause 节点的 name 为『法律名+空格+条号』（如：劳动合同法 第三十条）")
    lines.append("- 只读查询：仅可用 MATCH / OPTIONAL MATCH / WHERE / WITH / UNWIND / RETURN，"
                 "禁止 CREATE / MERGE / DELETE / SET / REMOVE 等任何写操作")
    lines.append("- 查询末尾必须附带 LIMIT（不超过 50）")
    return "\n".join(lines)


# ============================================================
# Main: Self-test
# ============================================================

if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Knowledge Graph Schema Validation")
    print("=" * 60)

    # Test node types
    print("\n[NODE TYPES] 8 types")
    for nt in get_all_node_types():
        schema = get_node_schema(nt)
        print(f"  {nt.value}: {len(schema.properties)} properties, constraint={schema.unique_constraint}")

    # Test relation types
    print("\n[RELATION TYPES] 10 types")
    for rt in get_all_relation_types():
        schema = get_relation_schema(rt)
        print(f"  {rt.value}: {schema.start_node.value} -> {schema.end_node.value}")

    # Generate Cypher
    print("\n[CONSTRAINTS]")
    constraints = generate_constraint_cypher()
    print(f"  Generated {len(constraints)} unique constraints")

    print("\n[INDEXES]")
    indexes = generate_index_cypher()
    print(f"  Generated {len(indexes)} indexes")

    # Show sample Cypher
    print("\n[SAMPLE CYPHER]")
    print("-" * 40)
    print(generate_full_schema_cypher()[:500])
    print("...")

    # LLM-facing schema text
    print("\n[LLM SCHEMA TEXT]")
    print("-" * 40)
    llm_text = generate_llm_schema_text()
    print(llm_text[:400])
    print(f"... ({len(llm_text)} chars total)")

    print("\n" + "=" * 60)
    print("[SUCCESS] Schema validation passed!")
    print("=" * 60)
