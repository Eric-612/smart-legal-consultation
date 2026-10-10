"""
Lawyer Entity Extractor
Uses LLM to extract structured lawyer/firm information from raw lawyer profile text.
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
    LawyerEntity,
    LawFirmEntity,
    LegalIssueEntity,
    EmploysRelation,
    SpecializesInRelation,
    LawyerExtractionResult,
    UrgencyLevel,
    IssueCategory,
)
from src.extraction.law_extractor import _drop_placeholders, _parse_simple_llm_output

logger = setup_logger(__name__, "extraction.log")


# ============================================================
# Simple LLM Output Schema
# ============================================================

class SimpleLawyerInfo(BaseModel):
    """简单律师信息"""
    name: str = Field(description="律师姓名")
    specialty: Optional[str] = Field(default=None, description="专长方向，如：劳动纠纷、婚姻家事")
    experience_years: Optional[int] = Field(default=None, description="执业年限")
    bar_number: Optional[str] = Field(default=None, description="律师执业证号")
    firm_name: Optional[str] = Field(default=None, description="所属律师事务所")


class SimpleFirmInfo(BaseModel):
    """简单律所信息"""
    name: str = Field(description="律所名称")
    city: Optional[str] = Field(default=None, description="所在城市")
    description: Optional[str] = Field(default=None, description="律所简介")


class SimpleLawyerLLMOutput(BaseModel):
    """Simple output schema for lawyer extraction"""
    lawyer: SimpleLawyerInfo = Field(description="律师基本信息")
    firm: Optional[SimpleFirmInfo] = Field(default=None, description="律所信息（如文本提供）")
    specialties: list[str] = Field(default_factory=list, description="律师专长方向（法律争议）名称列表")


_CLOUD_EXTRACT_SYSTEM = """你是一个专业的律师信息抽取助手。请从以下文本中提取律师及其相关信息。

要求：
1. 律师姓名直接提取
2. 专长方向指其擅长领域的法律争议（如"劳动纠纷""婚姻家事""合同纠纷"）
3. 律所信息如文本提供则提取，否则为 null
4. 专长方向如无明确表述，可依据其简介归纳
5. 如果没有相关信息，对应字段返回空列表或 null
6. 严格按照 JSON 格式输出"""

_CLOUD_EXTRACT_USER = """请从以下文本中提取律师信息：

{text}

请以 JSON 格式输出，包含以下字段：
{{
    "lawyer": {{
        "name": "律师姓名",
        "specialty": "专长方向",
        "experience_years": 执业年限或 null,
        "bar_number": "执业证号或 null",
        "firm_name": "所属律所或 null"
    }},
    "firm": {{
        "name": "律所名称",
        "city": "所在城市",
        "description": "律所简介"
    }},
    "specialties": ["专长方向1", "专长方向2"]
}}"""


class LawyerExtractor:
    """
    律师实体抽取器

    从原始律师/律所简介文本中抽取律师、律所与专长方向。
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
                SimpleLawyerLLMOutput,
                method="json_mode"
            )

    def _convert_to_result(self, simple: SimpleLawyerLLMOutput) -> LawyerExtractionResult:
        """Convert simple LLM output to full LawyerExtractionResult"""
        lawyer = LawyerEntity(
            name=simple.lawyer.name,
            specialty=simple.lawyer.specialty,
            experience_years=simple.lawyer.experience_years,
            bar_number=simple.lawyer.bar_number,
            firm_name=simple.lawyer.firm_name or (simple.firm.name if simple.firm else None),
        )

        firm = None
        if simple.firm and simple.firm.name:
            firm = LawFirmEntity(
                name=simple.firm.name,
                city=simple.firm.city,
                description=simple.firm.description,
            )

        specialties = [
            LegalIssueEntity(
                name=s,
                category=IssueCategory.OTHER,
                urgency=UrgencyLevel.MEDIUM,
            )
            for s in _drop_placeholders(simple.specialties)
        ]

        employs_relations = []
        if firm:
            employs_relations = [
                EmploysRelation(firm_name=firm.name, lawyer_name=lawyer.name)
            ]

        specializes_in_relations = [
            SpecializesInRelation(lawyer_name=lawyer.name, issue_name=s.name)
            for s in specialties
        ]

        return LawyerExtractionResult(
            lawyer=lawyer,
            firm=firm,
            specialties=specialties,
            employs_relations=employs_relations,
            specializes_in_relations=specializes_in_relations,
            extraction_confidence=0.9
        )

    @retry_on_error(max_retries=3, delay=1.0)
    def extract(self, text: str) -> LawyerExtractionResult:
        """从文本中抽取律师实体"""
        logger.info(f"[EXTRACT] Starting lawyer extraction, text length: {len(text)}")
        try:
            simple_result = self.chain.invoke({"text": text})
            result = self._convert_to_result(simple_result)
            logger.info(f"[EXTRACT] Lawyer: {result.lawyer.name}")
            return result
        except ValidationError as e:
            logger.error(f"[EXTRACT] Validation error: {e}")
            raise
        except Exception as e:
            logger.error(f"[EXTRACT] Extraction failed: {e}")
            raise

    def extract_from_dict(self, data: dict) -> LawyerExtractionResult:
        """从字典数据创建 LawyerExtractionResult"""
        lawyer = LawyerEntity(
            name=data.get("name", ""),
            specialty=data.get("specialty"),
            experience_years=data.get("experience_years"),
            bar_number=data.get("bar_number"),
            firm_name=data.get("firm_name"),
        )

        firm = None
        firm_data = data.get("firm")
        if firm_data and firm_data.get("name"):
            firm = LawFirmEntity(
                name=firm_data.get("name"),
                city=firm_data.get("city"),
                description=firm_data.get("description"),
            )

        specialties = [
            LegalIssueEntity(name=s, category=IssueCategory.OTHER, urgency=UrgencyLevel.MEDIUM)
            for s in data.get("specialties", []) if s
        ]

        employs_relations = []
        if firm:
            employs_relations = [EmploysRelation(firm_name=firm.name, lawyer_name=lawyer.name)]

        return LawyerExtractionResult(
            lawyer=lawyer,
            firm=firm,
            specialties=specialties,
            employs_relations=employs_relations,
            specializes_in_relations=[
                SpecializesInRelation(lawyer_name=lawyer.name, issue_name=s.name) for s in specialties
            ],
            extraction_confidence=0.9
        )


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Lawyer Extractor Test")
    print("=" * 60)

    extractor = LawyerExtractor(temperature=0.1)
    print("[PASS] LawyerExtractor created")

    test_data = {
        "name": "张三",
        "specialty": "劳动纠纷、合同纠纷",
        "experience_years": 8,
        "firm_name": "北京市盈科律师事务所",
        "firm": {"name": "北京市盈科律师事务所", "city": "北京", "description": "综合性大型律所"},
        "specialties": ["拖欠工资", "违法解除劳动合同"],
    }

    result = extractor.extract_from_dict(test_data)
    print(f"[PASS] Lawyer: {result.lawyer.name} ({result.lawyer.specialty})")
    print(f"[PASS] Firm: {result.firm.name if result.firm else 'None'}")
    print(f"[PASS] Specialties: {[s.name for s in result.specialties]}")
    print(f"[PASS] EMPLOYS relations: {len(result.employs_relations)}")
    print(f"[PASS] SPECIALIZES_IN relations: {len(result.specializes_in_relations)}")

    print("\n" + "=" * 60)
    print("[SUCCESS] Lawyer extractor tests passed!")
    print("=" * 60)
