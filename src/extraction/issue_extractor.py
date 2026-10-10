"""
Legal Issue Entity Extractor
Uses LLM to extract structured legal-issue information from raw issue description text.
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
    LegalIssueEntity,
    EvidenceEntity,
    ClauseEntity,
    NeedsEvidenceRelation,
    RelatedToRelation,
    IssueCategory,
    UrgencyLevel,
    EvidenceStrength,
)
from src.extraction.law_extractor import (
    SimpleClauseItem,
    _drop_placeholders,
    _parse_simple_llm_output,
)

logger = setup_logger(__name__, "extraction.log")


# ============================================================
# Simple LLM Output Schema
# ============================================================

class SimpleIssueInfo(BaseModel):
    """简单法律争议信息"""
    name: str = Field(description="法律争议名称，如：拖欠工资")
    description: Optional[str] = Field(default=None, description="争议描述")
    category: str = Field(description="争议类别：劳动/婚姻家事/合同/侵权/刑事/行政/物权房产/公司商事/知识产权/消费者/其他")
    urgency: str = Field(description="紧急性：低/中/高/紧急（涉拘留、立案、开庭、时效届满等为紧急）")


class SimpleIssueLLMOutput(BaseModel):
    """Simple output schema for issue extraction"""
    issue: SimpleIssueInfo = Field(description="法律争议基本信息")
    evidence_types: list[str] = Field(default_factory=list, description="处理该争议所需证据类型名称列表")
    related_clauses: list[SimpleClauseItem] = Field(default_factory=list, description="相关法条列表")
    related_issues: list[str] = Field(default_factory=list, description="相关争议名称列表")


# 争议类别 中文 -> 契约枚举 映射
_CATEGORY_MAP = {
    "劳动": IssueCategory.LABOR,
    "婚姻": IssueCategory.MARRIAGE_FAMILY,
    "家事": IssueCategory.MARRIAGE_FAMILY,
    "合同": IssueCategory.CONTRACT,
    "侵权": IssueCategory.TORT,
    "刑事": IssueCategory.CRIMINAL,
    "行政": IssueCategory.ADMINISTRATIVE,
    "物权": IssueCategory.PROPERTY,
    "房产": IssueCategory.PROPERTY,
    "公司": IssueCategory.COMPANY,
    "商事": IssueCategory.COMPANY,
    "知识": IssueCategory.INTELLECTUAL_PROPERTY,
    "消费": IssueCategory.CONSUMER,
    "其他": IssueCategory.OTHER,
}

# 紧急性 中文 -> 契约枚举 映射
_URGENCY_MAP = {
    "低": UrgencyLevel.LOW,
    "中": UrgencyLevel.MEDIUM,
    "高": UrgencyLevel.HIGH,
    "紧急": UrgencyLevel.URGENT,
}


def _map_category(text: str) -> IssueCategory:
    if not text:
        return IssueCategory.OTHER
    for key, value in _CATEGORY_MAP.items():
        if key in text:
            return value
    return IssueCategory.OTHER


def _map_urgency(text: str) -> UrgencyLevel:
    if not text:
        return UrgencyLevel.MEDIUM
    for key, value in _URGENCY_MAP.items():
        if key in text:
            return value
    return UrgencyLevel.MEDIUM


_CLOUD_EXTRACT_SYSTEM = """你是一个专业的法律争议抽取助手。请从以下文本中提取法律争议及其相关信息。

要求：
1. 争议名称使用规范表述（如"拖欠工资""违法解除劳动合同"）
2. 争议类别从：劳动、婚姻家事、合同、侵权、刑事、行政、物权房产、公司商事、知识产权、消费者、其他 中选择
3. 紧急性从：低、中、高、紧急 中选择；涉拘留、立案、开庭、时效届满等为"紧急"
4. 证据类型指处理该类纠纷通常需要的证据（如"劳动合同""工资银行流水"）
5. 相关法条给出该争议常援引的法条（条号+内容）
6. 相关争议指与该争议关联的争议类型
7. 如果没有相关信息，对应字段返回空列表
8. 严格按照 JSON 格式输出"""

_CLOUD_EXTRACT_USER = """请从以下文本中提取法律争议信息：

{text}

请以 JSON 格式输出，包含以下字段：
{{
    "issue": {{
        "name": "法律争议名称",
        "description": "争议描述",
        "category": "争议类别",
        "urgency": "紧急性"
    }},
    "evidence_types": ["证据类型1", "证据类型2"],
    "related_clauses": [{{"clause_no": "第三十条", "content": "条文内容"}}],
    "related_issues": ["相关争议1", "相关争议2"]
}}"""


class IssueExtractor:
    """
    法律争议实体抽取器

    从原始法律争议描述文本中抽取争议、类别、紧急性、所需证据与相关法条。
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
                SimpleIssueLLMOutput,
                method="json_mode"
            )

    def _convert_to_result(self, simple: SimpleIssueLLMOutput) -> LegalIssueEntity:
        """Convert simple LLM output to a LegalIssueEntity"""
        return LegalIssueEntity(
            name=simple.issue.name,
            description=simple.issue.description,
            category=_map_category(simple.issue.category),
            urgency=_map_urgency(simple.issue.urgency),
        )

    @retry_on_error(max_retries=3, delay=1.0)
    def extract(self, text: str) -> LegalIssueEntity:
        """从文本中抽取法律争议实体"""
        logger.info(f"[EXTRACT] Starting issue extraction, text length: {len(text)}")
        try:
            simple_result = self.chain.invoke({"text": text})
            issue = self._convert_to_result(simple_result)
            logger.info(f"[EXTRACT] Issue: {issue.name} ({issue.category.value}/{issue.urgency.value})")
            return issue
        except ValidationError as e:
            logger.error(f"[EXTRACT] Validation error: {e}")
            raise
        except Exception as e:
            logger.error(f"[EXTRACT] Extraction failed: {e}")
            raise

    def extract_from_dict(self, data: dict) -> LegalIssueEntity:
        """从字典数据创建 LegalIssueEntity"""
        return LegalIssueEntity(
            name=data.get("name", ""),
            description=data.get("description"),
            category=_map_category(data.get("category", "")),
            urgency=_map_urgency(data.get("urgency", "")),
        )


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Issue Extractor Test")
    print("=" * 60)

    extractor = IssueExtractor(temperature=0.1)
    print("[PASS] IssueExtractor created")

    test_data = {
        "name": "拖欠工资",
        "description": "用人单位未按约定支付劳动报酬",
        "category": "劳动",
        "urgency": "高",
    }

    issue = extractor.extract_from_dict(test_data)
    print(f"[PASS] Issue: {issue.name}")
    print(f"[PASS] Category: {issue.category.value}")
    print(f"[PASS] Urgency: {issue.urgency.value}")

    print("\n" + "=" * 60)
    print("[SUCCESS] Issue extractor tests passed!")
    print("=" * 60)
