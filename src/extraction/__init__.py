"""
Entity and Relation Extraction Module
Provides Pydantic schemas for legal knowledge graph entities and relations.
"""

from .schemas import (
    # Entities
    LawEntity,
    ClauseEntity,
    LegalIssueEntity,
    CaseEntity,
    LegalConceptEntity,
    LawyerEntity,
    LawFirmEntity,
    EvidenceEntity,
    # Relations
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
    # Comprehensive
    LawExtractionResult,
    CaseExtractionResult,
    LawyerExtractionResult,
    # Utilities
    get_all_entity_types,
    get_all_relation_types,
)

# Extractors
from .law_extractor import LawExtractor, build_cloud_extract_chain
from .case_extractor import CaseExtractor
from .lawyer_extractor import LawyerExtractor
from .issue_extractor import IssueExtractor

__all__ = [
    # Entities
    "LawEntity",
    "ClauseEntity",
    "LegalIssueEntity",
    "CaseEntity",
    "LegalConceptEntity",
    "LawyerEntity",
    "LawFirmEntity",
    "EvidenceEntity",
    # Relations
    "ContainsRelation",
    "RegulatesRelation",
    "InvolvesRelation",
    "CitesRelation",
    "SpecializesInRelation",
    "EmploysRelation",
    "NeedsEvidenceRelation",
    "DefinesRelation",
    "RelatedToRelation",
    "AppliesRelation",
    # Comprehensive
    "LawExtractionResult",
    "CaseExtractionResult",
    "LawyerExtractionResult",
    # Utilities
    "get_all_entity_types",
    "get_all_relation_types",
    # Extractors
    "LawExtractor",
    "build_cloud_extract_chain",
    "CaseExtractor",
    "LawyerExtractor",
    "IssueExtractor",
]
