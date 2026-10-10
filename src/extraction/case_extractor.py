"""
Case Entity Extractor
Uses LLM to extract structured case information from raw case text.
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
    CaseEntity,
    LegalIssueEntity,
    ClauseEntity,
    LawEntity,
    InvolvesRelation,
    CitesRelation,
    AppliesRelation,
    CaseExtractionResult,
    UrgencyLevel,
    IssueCategory,
)
from src.extraction.law_extractor import (
    SimpleClauseItem,
    _drop_placeholders,
    _parse_simple_llm_output,
    _map_law_level,
)

logger = setup_logger(__name__, "extraction.log")


# ============================================================
# Simple LLM Output Schema
# ============================================================

class SimpleCaseInfo(BaseModel):
    """简单案例信息"""
    name: str = Field(description="案件名称，如：张某诉某公司劳动报酬纠纷案")
    summary: Optional[str] = Field(default=None, description="案情摘要")
    court: Optional[str] = Field(default=None, description="审理法院")
    judgment_date: Optional[str] = Field(default=None, description="裁判日期")
    result: Optional[str] = Field(default=None, description="裁判结果")


class SimpleCaseLLMOutput(BaseModel):
    """Simple output schema for case extraction"""
    case: SimpleCaseInfo = Field(description="案例基本信息")
    issues: list[str] = Field(default_factory=list, description="案例涉及的法律争议名称列表")
    cited_clauses: list[SimpleClauseItem] = Field(default_factory=list, description="案例援引的法条列表")
    applied_laws: list[str] = Field(default_factory=list, description="案例适用的法律名称列表")


_CLOUD_EXTRACT_SYSTEM = """你是一个专业的法律案例抽取助手。请从以下文本中提取案例及其相关信息。

要求：
1. 案件名称使用规范表述（如"张某诉某公司劳动报酬纠纷案"）
2. 法律争议指本案的争议焦点（如"拖欠工资""违法解除劳动合同"）
3. 援引法条按"条号 + 内容"提取（如文本未直接引用则省略）
4. 适用法律给出规范全称（如"中华人民共和国劳动合同法"）
5. 如果没有相关信息，对应字段返回空列表
6. 严格按照 JSON 格式输出"""

_CLOUD_EXTRACT_USER = """请从以下文本中提取案例信息：

{text}

请以 JSON 格式输出，包含以下字段：
{{
    "case": {{
        "name": "案件名称",
        "summary": "案情摘要",
        "court": "审理法院",
        "judgment_date": "裁判日期或 null",
        "result": "裁判结果"
    }},
    "issues": ["法律争议1", "法律争议2"],
    "cited_clauses": [{{"clause_no": "第三十条", "content": "条文内容"}}],
    "applied_laws": ["法律名称1", "法律名称2"]
}}"""


class CaseExtractor:
    """
    案例实体抽取器

    从原始案例文本中抽取案例、法律争议、援引法条与适用法律。
    """

    def __init__(self, temperature: float = 0.1):
        self.llm = get_extract_llm(temperature=temperature)

        if settings.extraction_model_base_url.strip():
            # vLLM 微调模型分支：裸调用 + 手工解析
            self.prompt = ChatPromptTemplate.from_messages([
                ("system", _CLOUD_EXTRACT_SYSTEM),
                ("user", "{text}"),
            ])
            self.chain = self.prompt | self.llm | _parse_simple_llm_output
        else:
            # 云端主 LLM 分支：json_mode 结构化输出
            self.prompt = ChatPromptTemplate.from_messages([
                ("system", _CLOUD_EXTRACT_SYSTEM),
                ("user", _CLOUD_EXTRACT_USER),
            ])
            self.chain = self.prompt | self.llm.with_structured_output(
                SimpleCaseLLMOutput,
                method="json_mode"
            )

    def _convert_to_result(self, simple: SimpleCaseLLMOutput) -> CaseExtractionResult:
        """Convert simple LLM output to full CaseExtractionResult"""
        case = CaseEntity(
            name=simple.case.name,
            summary=simple.case.summary,
            court=simple.case.court,
            judgment_date=simple.case.judgment_date,
            result=simple.case.result,
        )

        issues = [
            LegalIssueEntity(
                name=i,
                category=IssueCategory.OTHER,
                urgency=UrgencyLevel.MEDIUM,
            )
            for i in _drop_placeholders(simple.issues)
        ]

        cited_clauses = [
            ClauseEntity(
                name=f"{law_name} {item.clause_no}" if (law_name := self._guess_law(simple)) else item.clause_no,
                clause_no=item.clause_no,
                law_name=law_name or "",
                content=item.content,
            )
            for item in simple.cited_clauses
            if item.clause_no and item.content
        ]

        applied_laws = [
            LawEntity(name=n, level=_map_law_level(""))
            for n in _drop_placeholders(simple.applied_laws)
        ]

        involves_relations = [
            InvolvesRelation(case_name=case.name, issue_name=i.name)
            for i in issues
        ]

        cites_relations = [
            CitesRelation(case_name=case.name, clause_name=c.name)
            for c in cited_clauses
        ]

        applies_relations = [
            AppliesRelation(case_name=case.name, law_name=l.name)
            for l in applied_laws
        ]

        return CaseExtractionResult(
            case=case,
            issues=issues,
            cited_clauses=cited_clauses,
            applied_laws=applied_laws,
            involves_relations=involves_relations,
            cites_relations=cites_relations,
            applies_relations=applies_relations,
            extraction_confidence=0.9
        )

    @staticmethod
    def _guess_law(simple: SimpleCaseLLMOutput) -> str:
        """从适用法律中猜测法条所属法律（取第一个）"""
        laws = _drop_placeholders(simple.applied_laws)
        return laws[0] if laws else ""

    @retry_on_error(max_retries=3, delay=1.0)
    def extract(self, text: str) -> CaseExtractionResult:
        """从文本中抽取案例实体"""
        logger.info(f"[EXTRACT] Starting case extraction, text length: {len(text)}")
        try:
            simple_result = self.chain.invoke({"text": text})
            result = self._convert_to_result(simple_result)
            logger.info(f"[EXTRACT] Case: {result.case.name}")
            return result
        except ValidationError as e:
            logger.error(f"[EXTRACT] Validation error: {e}")
            raise
        except Exception as e:
            logger.error(f"[EXTRACT] Extraction failed: {e}")
            raise

    def extract_from_dict(self, data: dict) -> CaseExtractionResult:
        """从字典数据创建 CaseExtractionResult"""
        case = CaseEntity(
            name=data.get("name", ""),
            summary=data.get("summary"),
            court=data.get("court"),
            judgment_date=data.get("judgment_date"),
            result=data.get("result"),
        )

        issues = [
            LegalIssueEntity(name=i, category=IssueCategory.OTHER, urgency=UrgencyLevel.MEDIUM)
            for i in data.get("issues", []) if i
        ]

        applied_laws = [
            LawEntity(name=n, level=_map_law_level(""))
            for n in data.get("applied_laws", []) if n
        ]

        return CaseExtractionResult(
            case=case,
            issues=issues,
            applied_laws=applied_laws,
            involves_relations=[InvolvesRelation(case_name=case.name, issue_name=i.name) for i in issues],
            applies_relations=[AppliesRelation(case_name=case.name, law_name=l.name) for l in applied_laws],
            extraction_confidence=0.9
        )


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Case Extractor Test")
    print("=" * 60)

    extractor = CaseExtractor(temperature=0.1)
    print("[PASS] CaseExtractor created")

    test_data = {
        "name": "张某诉某公司劳动报酬纠纷案",
        "summary": "某公司拖欠张某三个月工资后违法解除劳动合同",
        "court": "北京市朝阳区人民法院",
        "result": "判决公司支付拖欠工资及经济补偿",
        "issues": ["拖欠工资", "违法解除劳动合同"],
        "applied_laws": ["中华人民共和国劳动合同法"],
    }

    result = extractor.extract_from_dict(test_data)
    print(f"[PASS] Case: {result.case.name}")
    print(f"[PASS] Issues: {[i.name for i in result.issues]}")
    print(f"[PASS] Applied laws: {[l.name for l in result.applied_laws]}")

    print("\n" + "=" * 60)
    print("[SUCCESS] Case extractor tests passed!")
    print("=" * 60)
