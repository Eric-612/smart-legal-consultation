"""
Knowledge Graph Schema Definitions
Pydantic models for 8 entity types and 10 relation types.

Based on TDD.md Section: Neo4j Schema Design
"""

from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field


# ============================================================
# Enums —— 统一定义于 src/knowledge_graph/schema.py（R1 名字唯一主人）
# 本文件仅转导入、不再就地定义。
# ============================================================

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.knowledge_graph.schema import (
    LawLevel,
    UrgencyLevel,
    EvidenceStrength,
    IssueCategory,
)


# ============================================================
# 1. Entity Types (8 types)
# ============================================================

class LawEntity(BaseModel):
    """
    法律实体
    Node label: Law
    """
    name: str = Field(
        ...,
        description="法律名称，如：中华人民共和国劳动合同法、民法典、刑法"
    )
    level: LawLevel = Field(
        default=LawLevel.LAW,
        description="法律效力层级：constitution（宪法）/law（法律）/administrative_regulation（行政法规）/judicial_interpretation（司法解释）/local_regulation（地方性法规）/department_rule（部门规章）"
    )
    publish_date: Optional[str] = Field(
        default=None,
        description="发布日期，如：2007-06-29"
    )
    effective_date: Optional[str] = Field(
        default=None,
        description="施行日期，如：2008-01-01"
    )
    issuing_authority: Optional[str] = Field(
        default=None,
        description="发布机关，如：全国人民代表大会常务委员会"
    )
    description: Optional[str] = Field(
        default=None,
        description="法律概述，说明该法律的调整对象与适用范围"
    )


class ClauseEntity(BaseModel):
    """
    法律条文实体
    Node label: Clause
    """
    name: str = Field(
        ...,
        description="条文唯一名：法律名 + 空格 + 条号，如：劳动合同法 第三十条"
    )
    clause_no: str = Field(
        ...,
        description="条号，如：第三十条、第二百六十四条"
    )
    law_name: str = Field(
        ...,
        description="所属法律名称，如：中华人民共和国劳动合同法"
    )
    content: str = Field(
        ...,
        description="条文内容"
    )
    description: Optional[str] = Field(
        default=None,
        description="条文说明/要点解析"
    )


class LegalIssueEntity(BaseModel):
    """
    法律争议实体
    Node label: LegalIssue
    """
    name: str = Field(
        ...,
        description="法律争议名称，如：拖欠工资、违法解除劳动合同、交通事故赔偿、离婚财产分割"
    )
    description: Optional[str] = Field(
        default=None,
        description="争议描述，说明争议焦点与常见情形"
    )
    category: IssueCategory = Field(
        default=IssueCategory.OTHER,
        description="争议类别：labor（劳动）/marriage_family（婚姻家事）/contract（合同）/tort（侵权）/criminal（刑事）/administrative（行政）/property（物权房产）/company（公司商事）/intellectual_property（知识产权）/consumer（消费者）/other（其他）"
    )
    urgency: UrgencyLevel = Field(
        default=UrgencyLevel.MEDIUM,
        description="紧急性：low/medium/high/urgent（urgent 表示涉拘留/立案/开庭/时效届满等紧急事项）"
    )


class CaseEntity(BaseModel):
    """
    案例实体
    Node label: Case
    """
    name: str = Field(
        ...,
        description="案件名称，如：张某诉某公司劳动报酬纠纷案"
    )
    summary: Optional[str] = Field(
        default=None,
        description="案情摘要"
    )
    court: Optional[str] = Field(
        default=None,
        description="审理法院"
    )
    judgment_date: Optional[str] = Field(
        default=None,
        description="裁判日期"
    )
    result: Optional[str] = Field(
        default=None,
        description="裁判结果"
    )


class LegalConceptEntity(BaseModel):
    """
    法律概念实体
    Node label: LegalConcept
    """
    name: str = Field(
        ...,
        description="概念名称，如：劳动关系、举证责任、诉讼时效、定金"
    )
    definition: Optional[str] = Field(
        default=None,
        description="概念定义，如：劳动关系是指用人单位与劳动者之间依法确立的用工关系"
    )


class LawyerEntity(BaseModel):
    """
    律师实体
    Node label: Lawyer
    """
    name: str = Field(
        ...,
        description="律师姓名，如：张三"
    )
    specialty: Optional[str] = Field(
        default=None,
        description="专长方向，如：劳动纠纷、婚姻家事、合同纠纷"
    )
    experience_years: Optional[int] = Field(
        default=None,
        description="执业年限"
    )
    bar_number: Optional[str] = Field(
        default=None,
        description="律师执业证号"
    )
    firm_name: Optional[str] = Field(
        default=None,
        description="所属律师事务所名称"
    )


class LawFirmEntity(BaseModel):
    """
    律师事务所实体
    Node label: LawFirm
    """
    name: str = Field(
        ...,
        description="律所名称，如：北京市盈科律师事务所"
    )
    city: Optional[str] = Field(
        default=None,
        description="所在城市"
    )
    description: Optional[str] = Field(
        default=None,
        description="律所简介"
    )


class EvidenceEntity(BaseModel):
    """
    证据实体
    Node label: Evidence
    """
    name: str = Field(
        ...,
        description="证据名称，如：劳动合同、工资银行流水、解除通知书"
    )
    description: Optional[str] = Field(
        default=None,
        description="证据说明"
    )
    strength: EvidenceStrength = Field(
        default=EvidenceStrength.B,
        description="证据强度：A（强，书面原件）/B（中）/C（弱，口头证言）/D（需补充）"
    )


# ============================================================
# 2. Relation Types (10 types)
# ============================================================

class ContainsRelation(BaseModel):
    """
    法律-法条关系
    Pattern: (l:Law)-[:CONTAINS]->(c:Clause)
    """
    law_name: str = Field(..., description="法律名称")
    clause_name: str = Field(..., description="条文唯一名（法律名+条号）")


class RegulatesRelation(BaseModel):
    """
    法条-法律争议关系
    Pattern: (c:Clause)-[:REGULATES]->(i:LegalIssue)
    """
    clause_name: str = Field(..., description="条文唯一名")
    issue_name: str = Field(..., description="法律争议名称")


class InvolvesRelation(BaseModel):
    """
    案例-法律争议关系
    Pattern: (c:Case)-[:INVOLVES]->(i:LegalIssue)
    """
    case_name: str = Field(..., description="案件名称")
    issue_name: str = Field(..., description="法律争议名称")


class CitesRelation(BaseModel):
    """
    案例-法条关系
    Pattern: (c:Case)-[:CITES]->(cl:Clause)
    """
    case_name: str = Field(..., description="案件名称")
    clause_name: str = Field(..., description="条文唯一名")


class SpecializesInRelation(BaseModel):
    """
    律师-法律争议关系
    Pattern: (ly:Lawyer)-[:SPECIALIZES_IN]->(i:LegalIssue)
    """
    lawyer_name: str = Field(..., description="律师姓名")
    issue_name: str = Field(..., description="法律争议名称")


class EmploysRelation(BaseModel):
    """
    律所-律师关系
    Pattern: (f:LawFirm)-[:EMPLOYS]->(ly:Lawyer)
    """
    firm_name: str = Field(..., description="律所名称")
    lawyer_name: str = Field(..., description="律师姓名")


class NeedsEvidenceRelation(BaseModel):
    """
    法律争议-证据关系
    Pattern: (i:LegalIssue)-[:NEEDS_EVIDENCE]->(e:Evidence)
    """
    issue_name: str = Field(..., description="法律争议名称")
    evidence_name: str = Field(..., description="证据名称")
    necessity: str = Field(
        default="recommended",
        description="必要性：required（必需）/recommended（推荐）/optional（可选）"
    )


class DefinesRelation(BaseModel):
    """
    法条-法律概念关系
    Pattern: (c:Clause)-[:DEFINES]->(con:LegalConcept)
    """
    clause_name: str = Field(..., description="条文唯一名")
    concept_name: str = Field(..., description="法律概念名称")


class RelatedToRelation(BaseModel):
    """
    法律争议-法律争议相关关系
    Pattern: (i1:LegalIssue)-[:RELATED_TO]->(i2:LegalIssue)
    """
    issue1_name: str = Field(..., description="法律争议1名称")
    issue2_name: str = Field(..., description="法律争议2名称")


class AppliesRelation(BaseModel):
    """
    案例-法律关系
    Pattern: (c:Case)-[:APPLIES]->(l:Law)
    """
    case_name: str = Field(..., description="案件名称")
    law_name: str = Field(..., description="法律名称")


# ============================================================
# 3. Comprehensive Extraction Results
# ============================================================

class LawExtractionResult(BaseModel):
    """
    法律抽取综合结果
    从一部法律/一份法律文本中抽取法律、法条、适用场景（争议）、相关案例、法律概念与证据。
    """
    # Core entity
    law: LawEntity = Field(..., description="法律实体")

    # Related entities
    clauses: list[ClauseEntity] = Field(
        default_factory=list,
        description="法条列表"
    )
    issues: list[LegalIssueEntity] = Field(
        default_factory=list,
        description="适用场景/法律争议列表"
    )
    concepts: list[LegalConceptEntity] = Field(
        default_factory=list,
        description="法律概念列表"
    )
    related_cases: list[CaseEntity] = Field(
        default_factory=list,
        description="相关案例列表"
    )
    evidence_types: list[EvidenceEntity] = Field(
        default_factory=list,
        description="证据类型列表"
    )

    # Relations
    contains_relations: list[ContainsRelation] = Field(
        default_factory=list,
        description="法律-法条关系"
    )
    regulates_relations: list[RegulatesRelation] = Field(
        default_factory=list,
        description="法条-争议关系"
    )
    defines_relations: list[DefinesRelation] = Field(
        default_factory=list,
        description="法条-概念关系"
    )
    involves_relations: list[InvolvesRelation] = Field(
        default_factory=list,
        description="案例-争议关系"
    )
    cites_relations: list[CitesRelation] = Field(
        default_factory=list,
        description="案例-法条关系"
    )
    applies_relations: list[AppliesRelation] = Field(
        default_factory=list,
        description="案例-法律关系"
    )
    needs_evidence_relations: list[NeedsEvidenceRelation] = Field(
        default_factory=list,
        description="争议-证据关系"
    )

    # Metadata
    source_text: Optional[str] = Field(
        default=None,
        description="原始文本来源"
    )
    extraction_confidence: float = Field(
        default=0.0,
        description="抽取置信度（0-1）"
    )


class CaseExtractionResult(BaseModel):
    """
    案例抽取综合结果
    从一份案例文本中抽取案例、争议、援引法条、适用法律。
    """
    case: CaseEntity = Field(..., description="案例实体")
    issues: list[LegalIssueEntity] = Field(
        default_factory=list,
        description="案例涉及的法律争议列表"
    )
    cited_clauses: list[ClauseEntity] = Field(
        default_factory=list,
        description="案例援引的法条列表"
    )
    applied_laws: list[LawEntity] = Field(
        default_factory=list,
        description="案例适用的法律列表"
    )

    involves_relations: list[InvolvesRelation] = Field(
        default_factory=list,
        description="案例-争议关系"
    )
    cites_relations: list[CitesRelation] = Field(
        default_factory=list,
        description="案例-法条关系"
    )
    applies_relations: list[AppliesRelation] = Field(
        default_factory=list,
        description="案例-法律关系"
    )

    extraction_confidence: float = Field(
        default=0.0,
        description="抽取置信度（0-1）"
    )


class LawyerExtractionResult(BaseModel):
    """
    律师抽取综合结果
    从一份律师/律所简介文本中抽取律师、律所、专长方向。
    """
    lawyer: LawyerEntity = Field(..., description="律师实体")
    firm: Optional[LawFirmEntity] = Field(
        default=None,
        description="所属律所实体"
    )
    specialties: list[LegalIssueEntity] = Field(
        default_factory=list,
        description="律师专长方向（法律争议）列表"
    )

    employs_relations: list[EmploysRelation] = Field(
        default_factory=list,
        description="律所-律师关系"
    )
    specializes_in_relations: list[SpecializesInRelation] = Field(
        default_factory=list,
        description="律师-专长方向关系"
    )

    extraction_confidence: float = Field(
        default=0.0,
        description="抽取置信度（0-1）"
    )


# ============================================================
# 4. Utility Functions
# ============================================================

def get_all_entity_types() -> list[type[BaseModel]]:
    """获取所有实体类型"""
    return [
        LawEntity,
        ClauseEntity,
        LegalIssueEntity,
        CaseEntity,
        LegalConceptEntity,
        LawyerEntity,
        LawFirmEntity,
        EvidenceEntity,
    ]


def get_all_relation_types() -> list[type[BaseModel]]:
    """获取所有关系类型"""
    return [
        ContainsRelation,
        RegulatesRelation,
        InvolvesRelation,
        CitesRelation,
        SpecializesInRelation,
        EmploysRelation,
        NeedsEvidenceRelation,
        DefinesRelation,
        RelatedToRelation,
        AppliesRelation,
    ]


# ============================================================
# Main: Self-test
# ============================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path

    # Fix Windows console encoding
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

    print("=" * 60)
    print("Knowledge Graph Schema Validation")
    print("=" * 60)

    # Test entity types
    print("\n[TEST 1] Entity Types (8)")
    entities = get_all_entity_types()
    print(f"  Total: {len(entities)}")
    for e in entities:
        print(f"  - {e.__name__}")
    assert len(entities) == 8, "Expected 8 entity types"

    # Test relation types
    print("\n[TEST 2] Relation Types (10)")
    relations = get_all_relation_types()
    print(f"  Total: {len(relations)}")
    for r in relations:
        print(f"  - {r.__name__}")
    assert len(relations) == 10, "Expected 10 relation types"

    # Test entity instantiation
    print("\n[TEST 3] Entity Instantiation")
    law = LawEntity(
        name="中华人民共和国劳动合同法",
        level=LawLevel.LAW,
        publish_date="2007-06-29",
        effective_date="2008-01-01",
        issuing_authority="全国人民代表大会常务委员会",
        description="规范劳动合同的订立、履行、变更、解除和终止",
    )
    print(f"  Law: {law.name} ({law.level.value})")

    clause = ClauseEntity(
        name="劳动合同法 第三十条",
        clause_no="第三十条",
        law_name="中华人民共和国劳动合同法",
        content="用人单位应当按照劳动合同约定和国家规定，向劳动者及时足额支付劳动报酬。",
    )
    print(f"  Clause: {clause.name}")

    issue = LegalIssueEntity(
        name="拖欠工资",
        category=IssueCategory.LABOR,
        urgency=UrgencyLevel.HIGH,
    )
    print(f"  LegalIssue: {issue.name} ({issue.category.value}/{issue.urgency.value})")

    case = CaseEntity(
        name="张某诉某公司劳动报酬纠纷案",
        summary="某公司拖欠张某三个月工资",
        court="北京市朝阳区人民法院",
        result="判决公司支付拖欠工资及经济补偿",
    )
    print(f"  Case: {case.name}")

    lawyer = LawyerEntity(
        name="张三",
        specialty="劳动纠纷、合同纠纷",
        experience_years=8,
        firm_name="北京市盈科律师事务所",
    )
    print(f"  Lawyer: {lawyer.name} ({lawyer.specialty})")

    # Test relation instantiation
    print("\n[TEST 4] Relation Instantiation")
    rel1 = ContainsRelation(law_name="中华人民共和国劳动合同法", clause_name="劳动合同法 第三十条")
    print(f"  CONTAINS: {rel1.law_name} -> {rel1.clause_name}")

    rel2 = RegulatesRelation(clause_name="劳动合同法 第三十条", issue_name="拖欠工资")
    print(f"  REGULATES: {rel2.clause_name} -> {rel2.issue_name}")

    rel3 = EmploysRelation(firm_name="北京市盈科律师事务所", lawyer_name="张三")
    print(f"  EMPLOYS: {rel3.firm_name} -> {rel3.lawyer_name}")

    # Test comprehensive result
    print("\n[TEST 5] Comprehensive Extraction Result")
    result = LawExtractionResult(
        law=law,
        clauses=[clause],
        issues=[issue],
        related_cases=[case],
        contains_relations=[rel1],
        regulates_relations=[rel2],
        extraction_confidence=0.95
    )
    print(f"  Law: {result.law.name}")
    print(f"  Clauses: {len(result.clauses)}")
    print(f"  Issues: {len(result.issues)}")
    print(f"  Related cases: {len(result.related_cases)}")
    print(f"  Confidence: {result.extraction_confidence}")

    print("\n" + "=" * 60)
    print("[SUCCESS] All schema tests passed!")
    print("=" * 60)
