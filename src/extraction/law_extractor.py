"""
Law Entity Extractor
Uses LLM to extract structured legal information from raw text.
"""

import json
import sys
from pathlib import Path

# Ensure project root is in sys.path
_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, ValidationError
from typing import Optional

from config.settings import settings
from src.common.llm import get_extract_llm, get_llm
from src.common.logger import setup_logger
from src.common.utils import retry_on_error
from src.extraction.schemas import (
    LawEntity,
    ClauseEntity,
    LegalIssueEntity,
    CaseEntity,
    LegalConceptEntity,
    EvidenceEntity,
    ContainsRelation,
    RegulatesRelation,
    InvolvesRelation,
    CitesRelation,
    AppliesRelation,
    DefinesRelation,
    NeedsEvidenceRelation,
    LawExtractionResult,
    LawLevel,
    UrgencyLevel,
    EvidenceStrength,
    IssueCategory,
)


# ============================================================
# Simple LLM Output Schema (for easier LLM generation)
# ============================================================

class SimpleClauseItem(BaseModel):
    """简单法条项，供 LLM 逐条输出"""
    clause_no: str = Field(description="条号，如：第三十条")
    content: str = Field(description="条文内容")


class SimpleCaseItem(BaseModel):
    """简单案例项，供 LLM 输出"""
    name: str = Field(description="案件名称，如：张某诉某公司劳动报酬纠纷案")
    summary: Optional[str] = Field(default=None, description="案情摘要")
    court: Optional[str] = Field(default=None, description="审理法院")
    result: Optional[str] = Field(default=None, description="裁判结果")


class SimpleLawInfo(BaseModel):
    """简单法律信息，供 LLM 输出"""
    name: str = Field(description="法律名称")
    level: str = Field(description="法律效力层级：法律/行政法规/司法解释/地方性法规/部门规章/宪法")
    description: Optional[str] = Field(default=None, description="法律概述")
    publish_date: Optional[str] = Field(default=None, description="发布日期，如 2007-06-29")
    effective_date: Optional[str] = Field(default=None, description="施行日期，如 2008-01-01")
    issuing_authority: Optional[str] = Field(default=None, description="发布机关")


class SimpleLLMOutput(BaseModel):
    """
    Simple output schema for LLM extraction.
    Uses string lists instead of entity objects for easier LLM generation.
    """
    law: SimpleLawInfo = Field(description="法律基本信息")
    clauses: list[SimpleClauseItem] = Field(default_factory=list, description="法条列表")
    application_scenarios: list[str] = Field(default_factory=list, description="适用场景/法律争议名称列表")
    related_cases: list[SimpleCaseItem] = Field(default_factory=list, description="相关案例列表")
    concepts: list[str] = Field(default_factory=list, description="法律概念名称列表")
    evidence_types: list[str] = Field(default_factory=list, description="所需证据类型名称列表")

logger = setup_logger(__name__, "extraction.log")


# vLLM 微调模型专用指令：与训练数据（data/finetune/ft_extract.json）的 instruction
# 逐字一致——原 system 提示词 + JSON 字段模板合并为一条指令。
_VLLM_EXTRACT_INSTRUCTION = """你是一个专业的法律信息抽取助手。请从以下文本中提取法律及其相关信息。

要求：
1. 法律名称使用规范全称（如"中华人民共和国劳动合同法"）
2. 法条按"条号 + 内容"逐条提取，条号用中文数字（如"第三十条"）
3. 适用场景指该法律主要解决的法律争议情形（如"拖欠工资""违法解除劳动合同"）
4. 相关案例给出案件名称、法院与裁判结果（如文本未提供则省略）
5. 法律概念指文本中的专业术语（如"劳动关系""举证责任"）
6. 证据类型指处理该类纠纷通常需要的证据（如"劳动合同""工资银行流水"）
7. 如果没有相关信息，对应字段返回空列表
8. 严格按照 JSON 格式输出

请以 JSON 格式输出，包含以下字段：
{{
    "law": {{
        "name": "法律名称",
        "level": "法律/行政法规/司法解释/地方性法规/部门规章",
        "description": "法律概述",
        "publish_date": "发布日期或 null",
        "effective_date": "施行日期或 null",
        "issuing_authority": "发布机关"
    }},
    "clauses": [{{"clause_no": "第三十条", "content": "条文内容"}}],
    "application_scenarios": ["适用场景1", "适用场景2"],
    "related_cases": [{{"name": "案件名称", "summary": "案情摘要", "court": "法院", "result": "裁判结果"}}],
    "concepts": ["法律概念1", "法律概念2"],
    "evidence_types": ["证据类型1", "证据类型2"]
}}"""


# 指令模板里的占位示例：微调模型在字段本应为空时偶尔原样回声这些占位符，
# 入图前统一过滤，避免图谱出现"适用场景1"之类的垃圾节点
_TEMPLATE_PLACEHOLDERS = {
    "法律名称", "法律/行政法规/司法解释/地方性法规/部门规章", "法律概述",
    "发布日期或 null", "施行日期或 null", "发布机关",
    "第三十条", "条文内容",
    "适用场景1", "适用场景2",
    "案件名称", "案情摘要", "法院", "裁判结果",
    "法律概念1", "法律概念2",
    "证据类型1", "证据类型2",
}


def _drop_placeholders(items: list) -> list:
    return [s for s in items if s and s not in _TEMPLATE_PLACEHOLDERS]


# 云端主 LLM 抽取用的原版双消息提示词（EXTRACTION_MODEL_BASE_URL 留空时的默认路径）
_CLOUD_EXTRACT_SYSTEM = """你是一个专业的法律信息抽取助手。请从以下文本中提取法律及其相关信息。

要求：
1. 法律名称使用规范全称（如"中华人民共和国劳动合同法"）
2. 法条按"条号 + 内容"逐条提取，条号用中文数字（如"第三十条"）
3. 适用场景指该法律主要解决的法律争议情形（如"拖欠工资""违法解除劳动合同"）
4. 相关案例给出案件名称、法院与裁判结果（如文本未提供则省略）
5. 法律概念指文本中的专业术语（如"劳动关系""举证责任"）
6. 证据类型指处理该类纠纷通常需要的证据（如"劳动合同""工资银行流水"）
7. 如果没有相关信息，对应字段返回空列表
8. 严格按照 JSON 格式输出"""

_CLOUD_EXTRACT_USER = """请从以下文本中提取法律信息：

{text}

请以 JSON 格式输出，包含以下字段：
{{
    "law": {{
        "name": "法律名称",
        "level": "法律/行政法规/司法解释/地方性法规/部门规章",
        "description": "法律概述",
        "publish_date": "发布日期或 null",
        "effective_date": "施行日期或 null",
        "issuing_authority": "发布机关"
    }},
    "clauses": [{{"clause_no": "第三十条", "content": "条文内容"}}],
    "application_scenarios": ["适用场景1", "适用场景2"],
    "related_cases": [{{"name": "案件名称", "summary": "案情摘要", "court": "法院", "result": "裁判结果"}}],
    "concepts": ["法律概念1", "法律概念2"],
    "evidence_types": ["证据类型1", "证据类型2"]
}}"""


def build_cloud_extract_chain(temperature: float = 0.1):
    """
    云端主 LLM 抽取链（json_mode 结构化输出）。

    两个用途：
    1. EXTRACTION_MODEL_BASE_URL 留空时的默认抽取路径；
    2. vLLM 微调模型抽取失败（失控生成/畸形 JSON）时的兜底，保证建图覆盖率。
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", _CLOUD_EXTRACT_SYSTEM),
        ("user", _CLOUD_EXTRACT_USER),
    ])
    return prompt | get_llm(temperature=temperature).with_structured_output(
        SimpleLLMOutput,
        method="json_mode"
    )


def _parse_simple_llm_output(raw) -> "SimpleLLMOutput":
    """
    手工解析微调模型的 JSON 输出。

    vLLM 路径不使用 with_structured_output(method="json_mode")：实测 response_format
    json_object 的引导解码会诱发微调模型失控生成（烧穿 max_tokens 后 finish_reason=length）。
    裸调用时模型稳定收尾，但常给 JSON 包 ```json 围栏，这里做容错解析。
    """
    text = raw.content if hasattr(raw, "content") else str(raw)
    text = text.strip()

    # 去掉 ```json ... ``` Markdown 围栏
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

    # 容错截取第一个 { 到最后一个 }
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"No JSON object in model output: {text[:120]!r}")

    data = json.loads(text[start:end + 1])
    return SimpleLLMOutput(**data)


# 法律效力层级 中文 -> 契约枚举 的映射（SimpleLawInfo.level 为自由文本）
_LEVEL_MAP = {
    "宪法": LawLevel.CONSTITUTION,
    "法律": LawLevel.LAW,
    "基本法律": LawLevel.LAW,
    "行政法规": LawLevel.ADMINISTRATIVE_REGULATION,
    "司法解释": LawLevel.JUDICIAL_INTERPRETATION,
    "地方性法规": LawLevel.LOCAL_REGULATION,
    "部门规章": LawLevel.DEPARTMENT_RULE,
    "规章": LawLevel.DEPARTMENT_RULE,
}


def _map_law_level(level_text: str) -> LawLevel:
    """将 LLM 输出的中文层级映射到契约枚举"""
    if not level_text:
        return LawLevel.LAW
    for key, value in _LEVEL_MAP.items():
        if key in level_text:
            return value
    return LawLevel.LAW


class LawExtractor:
    """
    法律实体抽取器

    从原始法律文本中抽取法律、法条、适用场景（法律争议）、相关案例、
    法律概念与所需证据类型。

    Usage:
        >>> extractor = LawExtractor()
        >>> result = extractor.extract("中华人民共和国劳动合同法...")
        >>> print(result.law.name)
        >>> print(result.clauses)
    """

    def __init__(self, temperature: float = 0.1):
        """
        初始化抽取器

        Args:
            temperature: LLM 温度参数，抽取任务建议低温度（0.1-0.3）
        """
        # 抽取专用入口：EXTRACTION_MODEL_BASE_URL 非空走本地 vLLM 微调模型，为空自动回退云端 get_llm()
        self.llm = get_extract_llm(temperature=temperature)

        if settings.extraction_model_base_url.strip():
            # vLLM 微调模型分支：消息结构与训练数据对齐（完整 instruction 作 system，
            # 纯法律文本作 user），裸调用 + 手工解析（json_mode 引导解码会诱发失控生成）
            self.prompt = ChatPromptTemplate.from_messages([
                ("system", _VLLM_EXTRACT_INSTRUCTION),
                ("user", "{text}"),
            ])
            self.chain = self.prompt | self.llm | _parse_simple_llm_output
        else:
            # 云端主 LLM 分支：原有双消息提示词 + json_mode 结构化输出
            self.prompt = ChatPromptTemplate.from_messages([
                ("system", _CLOUD_EXTRACT_SYSTEM),
                ("user", _CLOUD_EXTRACT_USER),
            ])
            self.chain = self.prompt | self.llm.with_structured_output(
                SimpleLLMOutput,
                method="json_mode"
            )

    def _convert_to_result(self, simple: SimpleLLMOutput) -> LawExtractionResult:
        """Convert simple LLM output to full LawExtractionResult"""
        # Build law entity
        law = LawEntity(
            name=simple.law.name,
            level=_map_law_level(simple.law.level),
            publish_date=simple.law.publish_date,
            effective_date=simple.law.effective_date,
            issuing_authority=simple.law.issuing_authority,
            description=simple.law.description,
        )

        # 法条实体：name = 法律名 + 空格 + 条号（图谱唯一约束键）
        clauses = [
            ClauseEntity(
                name=f"{law.name} {item.clause_no}",
                clause_no=item.clause_no,
                law_name=law.name,
                content=item.content,
            )
            for item in simple.clauses
            if item.clause_no and item.content
        ]

        # 适用场景 -> 法律争议实体（类别由后续 Agent 层细分，此处默认 other/medium）
        issues = [
            LegalIssueEntity(
                name=s,
                category=IssueCategory.OTHER,
                urgency=UrgencyLevel.MEDIUM,
            )
            for s in _drop_placeholders(simple.application_scenarios)
        ]

        # 相关案例实体
        related_cases = [
            CaseEntity(
                name=c.name,
                summary=c.summary,
                court=c.court,
                result=c.result,
            )
            for c in simple.related_cases
            if c.name
        ]

        # 法律概念实体
        concepts = [
            LegalConceptEntity(name=n)
            for n in _drop_placeholders(simple.concepts)
        ]

        # 证据类型实体
        evidence_types = [
            EvidenceEntity(name=e, strength=EvidenceStrength.B)
            for e in _drop_placeholders(simple.evidence_types)
        ]

        # Build relations
        contains_relations = [
            ContainsRelation(law_name=law.name, clause_name=c.name)
            for c in clauses
        ]

        regulates_relations = [
            RegulatesRelation(clause_name=c.name, issue_name=i.name)
            for c in clauses for i in issues
        ]

        defines_relations = [
            DefinesRelation(clause_name=c.name, concept_name=con.name)
            for c in clauses for con in concepts
        ]

        involves_relations = [
            InvolvesRelation(case_name=case.name, issue_name=i.name)
            for case in related_cases for i in issues
        ]

        cites_relations = [
            CitesRelation(case_name=case.name, clause_name=c.name)
            for case in related_cases for c in clauses
        ]

        applies_relations = [
            AppliesRelation(case_name=case.name, law_name=law.name)
            for case in related_cases
        ]

        needs_evidence_relations = [
            NeedsEvidenceRelation(issue_name=i.name, evidence_name=e.name, necessity="recommended")
            for i in issues for e in evidence_types
        ]

        return LawExtractionResult(
            law=law,
            clauses=clauses,
            issues=issues,
            concepts=concepts,
            related_cases=related_cases,
            evidence_types=evidence_types,
            contains_relations=contains_relations,
            regulates_relations=regulates_relations,
            defines_relations=defines_relations,
            involves_relations=involves_relations,
            cites_relations=cites_relations,
            applies_relations=applies_relations,
            needs_evidence_relations=needs_evidence_relations,
            extraction_confidence=0.9
        )

    @retry_on_error(max_retries=3, delay=1.0)
    def extract(self, text: str) -> LawExtractionResult:
        """
        从文本中抽取法律实体

        Args:
            text: 原始法律文本

        Returns:
            LawExtractionResult: 包含法律及所有相关实体和关系

        Raises:
            ValidationError: LLM 返回格式错误（会自动重试）
        """
        logger.info(f"[EXTRACT] Starting law extraction, text length: {len(text)}")

        try:
            # Invoke the chain - returns SimpleLLMOutput
            simple_result = self.chain.invoke({"text": text})

            # Convert to full LawExtractionResult
            result = self._convert_to_result(simple_result)

            # Validate and log
            logger.info(f"[EXTRACT] Law: {result.law.name}")
            logger.info(f"[EXTRACT] Clauses: {len(result.clauses)}")
            logger.info(f"[EXTRACT] Issues: {len(result.issues)}")
            logger.info(f"[EXTRACT] Related cases: {len(result.related_cases)}")

            return result

        except ValidationError as e:
            logger.error(f"[EXTRACT] Validation error: {e}")
            raise
        except Exception as e:
            logger.error(f"[EXTRACT] Extraction failed: {e}")
            raise

    def extract_from_dict(self, data: dict) -> LawExtractionResult:
        """
        从字典数据创建 LawExtractionResult（对应爬虫 data/processed/laws.json 的单条记录）

        Args:
            data: 包含法律信息的字典

        Returns:
            LawExtractionResult
        """
        # Build law entity
        law = LawEntity(
            name=data.get("name", ""),
            level=_map_law_level(data.get("level", "")),
            publish_date=data.get("publish_date"),
            effective_date=data.get("effective_date"),
            issuing_authority=data.get("issuing_authority"),
            description=data.get("description"),
        )

        # Build clause entities
        clauses = [
            ClauseEntity(
                name=f"{law.name} {item.get('clause_no', '')}",
                clause_no=item.get("clause_no", ""),
                law_name=law.name,
                content=item.get("content", ""),
            )
            for item in data.get("clauses", [])
            if item.get("clause_no") and item.get("content")
        ]

        # Build issue entities（适用场景）
        issues = [
            LegalIssueEntity(
                name=s,
                category=IssueCategory.OTHER,
                urgency=UrgencyLevel.MEDIUM,
            )
            for s in data.get("application_scenarios", [])
            if s
        ]

        # Build case entities（相关案例）
        related_cases = [
            CaseEntity(
                name=c.get("name", ""),
                summary=c.get("summary"),
                court=c.get("court"),
                result=c.get("result"),
            )
            for c in data.get("related_cases", [])
            if c.get("name")
        ]

        # Build relations
        contains_relations = [
            ContainsRelation(law_name=law.name, clause_name=c.name)
            for c in clauses
        ]

        regulates_relations = [
            RegulatesRelation(clause_name=c.name, issue_name=i.name)
            for c in clauses for i in issues
        ]

        involves_relations = [
            InvolvesRelation(case_name=case.name, issue_name=i.name)
            for case in related_cases for i in issues
        ]

        cites_relations = [
            CitesRelation(case_name=case.name, clause_name=c.name)
            for case in related_cases for c in clauses
        ]

        applies_relations = [
            AppliesRelation(case_name=case.name, law_name=law.name)
            for case in related_cases
        ]

        return LawExtractionResult(
            law=law,
            clauses=clauses,
            issues=issues,
            related_cases=related_cases,
            contains_relations=contains_relations,
            regulates_relations=regulates_relations,
            involves_relations=involves_relations,
            cites_relations=cites_relations,
            applies_relations=applies_relations,
            extraction_confidence=0.9
        )


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Law Extractor Test")
    print("=" * 60)

    # Test 1: Create extractor
    print("\n[TEST 1] Create LawExtractor")
    extractor = LawExtractor(temperature=0.1)
    print("[PASS] LawExtractor created")

    # Test 2: Extract from dict (no LLM call)
    print("\n[TEST 2] Extract from dict")
    test_data = {
        "name": "中华人民共和国劳动合同法",
        "level": "法律",
        "publish_date": "2007-06-29",
        "effective_date": "2008-01-01",
        "issuing_authority": "全国人民代表大会常务委员会",
        "description": "规范劳动合同的订立、履行、变更、解除和终止",
        "clauses": [
            {"clause_no": "第三十条", "content": "用人单位应当按照劳动合同约定和国家规定，向劳动者及时足额支付劳动报酬。"},
            {"clause_no": "第八十五条", "content": "用人单位未按照劳动合同的约定或者国家规定及时足额支付劳动者劳动报酬的，由劳动行政部门责令限期支付。"},
        ],
        "application_scenarios": ["拖欠工资", "违法解除劳动合同"],
        "related_cases": [
            {"name": "张某诉某公司劳动报酬纠纷案", "summary": "某公司拖欠张某三个月工资", "court": "北京市朝阳区人民法院", "result": "判决公司支付拖欠工资及经济补偿"}
        ],
    }

    result = extractor.extract_from_dict(test_data)
    print(f"[PASS] Law: {result.law.name} ({result.law.level.value})")
    print(f"[PASS] Clauses: {[c.clause_no for c in result.clauses]}")
    print(f"[PASS] Issues: {[i.name for i in result.issues]}")
    print(f"[PASS] Related cases: {[c.name for c in result.related_cases]}")
    print(f"[PASS] CONTAINS relations: {len(result.contains_relations)}")
    print(f"[PASS] REGULATES relations: {len(result.regulates_relations)}")

    print("\n" + "=" * 60)
    print("[SUCCESS] Law extractor tests passed!")
    print("=" * 60)
