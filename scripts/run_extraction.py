"""
Batch Entity Extraction Script
Reads processed legal data and extracts entities/relations using LLM.

Usage:
    python scripts/run_extraction.py
    python scripts/run_extraction.py --input data/processed/laws.json
    python scripts/run_extraction.py --resume  # Resume from checkpoint
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from collections import Counter

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from config.paths import DATA_PROCESSED_DIR, DATA_KG_DIR, LOGS_DIR
from config.settings import settings
from src.common.logger import setup_logger
from src.extraction.law_extractor import LawExtractor, build_cloud_extract_chain
# R1 名字唯一主人：类型名一律取自契约枚举，禁止字符串字面量
from src.knowledge_graph.schema import NodeType, RelationType

logger = setup_logger(__name__, "extraction.log")


# ============================================================
# Paths
# ============================================================

INPUT_FILE = DATA_PROCESSED_DIR / "laws.json"
ENTITIES_FILE = DATA_KG_DIR / "entities.json"
RELATIONS_FILE = DATA_KG_DIR / "relations.json"
CHECKPOINT_FILE = DATA_KG_DIR / ".extraction_checkpoint.json"


# ============================================================
# Checkpoint Management
# ============================================================

class CheckpointManager:
    """Manages extraction checkpoint for resume capability"""

    def __init__(self, checkpoint_path: Path):
        self.checkpoint_path = checkpoint_path
        self.data = self._load()

    def _load(self) -> dict:
        """Load checkpoint from file"""
        if self.checkpoint_path.exists():
            try:
                with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[CHECKPOINT] Failed to load checkpoint: {e}")
        return {
            "processed_indices": [],
            "entities": [],
            "relations": [],
            "stats": {
                "total": 0,
                "success": 0,
                "failed": 0,
            }
        }

    def save(self):
        """Save checkpoint to file"""
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def is_processed(self, index: int) -> bool:
        """Check if index already processed"""
        return index in self.data["processed_indices"]

    def add_result(self, index: int, entities: list, relations: list, success: bool):
        """Add extraction result to checkpoint"""
        self.data["processed_indices"].append(index)
        if success:
            self.data["entities"].extend(entities)
            self.data["relations"].extend(relations)
            self.data["stats"]["success"] += 1
        else:
            self.data["stats"]["failed"] += 1

    def get_stats(self) -> dict:
        """Get current stats"""
        return self.data["stats"]

    def clear(self):
        """Clear checkpoint"""
        self.data = {
            "processed_indices": [],
            "entities": [],
            "relations": [],
            "stats": {"total": 0, "success": 0, "failed": 0}
        }
        if self.checkpoint_path.exists():
            self.checkpoint_path.unlink()


# ============================================================
# Entity/Relation Serialization
# ============================================================

def serialize_entities(result) -> list[dict]:
    """Convert LawExtractionResult entities to serializable dicts（类型名取自 NodeType 枚举，R1）"""
    entities = []

    # Law entity
    entities.append({
        "type": NodeType.LAW.value,
        "data": result.law.model_dump()
    })

    # Clauses
    for c in result.clauses:
        entities.append({
            "type": NodeType.CLAUSE.value,
            "data": c.model_dump()
        })

    # Legal issues
    for i in result.issues:
        entities.append({
            "type": NodeType.LEGAL_ISSUE.value,
            "data": i.model_dump()
        })

    # Related cases
    for case in result.related_cases:
        entities.append({
            "type": NodeType.CASE.value,
            "data": case.model_dump()
        })

    # Legal concepts
    for con in result.concepts:
        entities.append({
            "type": NodeType.LEGAL_CONCEPT.value,
            "data": con.model_dump()
        })

    # Evidence types
    for e in result.evidence_types:
        entities.append({
            "type": NodeType.EVIDENCE.value,
            "data": e.model_dump()
        })

    return entities


def serialize_relations(result) -> list[dict]:
    """Convert LawExtractionResult relations to serializable dicts（类型名取自 RelationType 枚举，R1）"""
    relations = []

    # CONTAINS (Law -> Clause)
    for r in result.contains_relations:
        relations.append({
            "type": RelationType.CONTAINS.value,
            "data": r.model_dump()
        })

    # REGULATES (Clause -> LegalIssue)
    for r in result.regulates_relations:
        relations.append({
            "type": RelationType.REGULATES.value,
            "data": r.model_dump()
        })

    # DEFINES (Clause -> LegalConcept)
    for r in result.defines_relations:
        relations.append({
            "type": RelationType.DEFINES.value,
            "data": r.model_dump()
        })

    # INVOLVES (Case -> LegalIssue)
    for r in result.involves_relations:
        relations.append({
            "type": RelationType.INVOLVES.value,
            "data": r.model_dump()
        })

    # CITES (Case -> Clause)
    for r in result.cites_relations:
        relations.append({
            "type": RelationType.CITES.value,
            "data": r.model_dump()
        })

    # APPLIES (Case -> Law)
    for r in result.applies_relations:
        relations.append({
            "type": RelationType.APPLIES.value,
            "data": r.model_dump()
        })

    # NEEDS_EVIDENCE (LegalIssue -> Evidence)
    for r in result.needs_evidence_relations:
        relations.append({
            "type": RelationType.NEEDS_EVIDENCE.value,
            "data": r.model_dump()
        })

    return relations


# ============================================================
# Main Extraction Logic
# ============================================================

def load_input_data(input_path: Path) -> list[dict]:
    """Load processed legal data"""
    if not input_path.exists():
        logger.error(f"[ERROR] Input file not found: {input_path}")
        return []

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        laws = data.get("laws", [])
        logger.info(f"[LOAD] Loaded {len(laws)} laws from {input_path}")
        return laws

    except Exception as e:
        logger.error(f"[ERROR] Failed to load input: {e}")
        return []


def save_results(entities: list, relations: list, stats: dict):
    """Save extraction results to files"""
    DATA_KG_DIR.mkdir(parents=True, exist_ok=True)

    # Save entities
    entities_output = {
        "metadata": {
            "extracted_at": datetime.now().isoformat(),
            "total_entities": len(entities),
            "stats": stats
        },
        "entities": entities
    }
    with open(ENTITIES_FILE, "w", encoding="utf-8") as f:
        json.dump(entities_output, f, ensure_ascii=False, indent=2)
    logger.info(f"[SAVE] Entities saved to {ENTITIES_FILE}")

    # Save relations
    relations_output = {
        "metadata": {
            "extracted_at": datetime.now().isoformat(),
            "total_relations": len(relations)
        },
        "relations": relations
    }
    with open(RELATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(relations_output, f, ensure_ascii=False, indent=2)
    logger.info(f"[SAVE] Relations saved to {RELATIONS_FILE}")


def print_statistics(entities: list, relations: list, stats: dict):
    """Print extraction statistics"""
    print("\n" + "=" * 60)
    print("EXTRACTION STATISTICS")
    print("=" * 60)

    # Overall stats
    print(f"\n[OVERVIEW]")
    print(f"  Total records: {stats.get('total', 0)}")
    print(f"  Success: {stats.get('success', 0)}")
    print(f"  Failed: {stats.get('failed', 0)}")
    if stats.get("cloud_fallback"):
        print(f"  Cloud fallback (vLLM 失败后兜底): {stats.get('cloud_fallback')}")

    # Entity stats by type
    entity_counter = Counter(e["type"] for e in entities)
    print(f"\n[ENTITIES] Total: {len(entities)}")
    for etype, count in entity_counter.most_common():
        print(f"  {etype}: {count}")

    # Relation stats by type
    relation_counter = Counter(r["type"] for r in relations)
    print(f"\n[RELATIONS] Total: {len(relations)}")
    for rtype, count in relation_counter.most_common():
        print(f"  {rtype}: {count}")

    print("\n" + "=" * 60)


def run_extraction(
    input_path: Path = INPUT_FILE,
    resume: bool = False,
    use_llm: bool = True
):
    """
    Run batch entity extraction

    Args:
        input_path: Path to input JSON file
        resume: If True, resume from checkpoint
        use_llm: If True, use LLM extraction; else use dict-based extraction
    """
    print("=" * 60)
    print("BATCH ENTITY EXTRACTION")
    print("=" * 60)
    print(f"Input: {input_path}")
    print(f"Resume: {resume}")
    print(f"Use LLM: {use_llm}")
    print("=" * 60)

    # Load input data
    laws = load_input_data(input_path)
    if not laws:
        print("[ERROR] No data to process")
        return

    # Initialize checkpoint
    checkpoint = CheckpointManager(CHECKPOINT_FILE)
    if not resume:
        checkpoint.clear()
        logger.info("[CHECKPOINT] Cleared previous checkpoint")
    else:
        processed = len(checkpoint.data["processed_indices"])
        logger.info(f"[CHECKPOINT] Resuming from checkpoint, {processed} already processed")

    # Initialize extractor
    # temperature=0：微调模型在非零采样下更容易陷入"通用列表"失控生成；贪心解码最稳
    extractor = LawExtractor(temperature=0.0)

    # vLLM 微调模型偶发失控生成（长噪声输入下烧穿 max_tokens）或畸形 JSON，
    # 对这些样本用云端主 LLM 兜底，保证建图覆盖率；兜底次数单独计数、可观测
    use_vllm = bool(settings.extraction_model_base_url.strip())
    cloud_fallback_chain = build_cloud_extract_chain(temperature=0.1) if use_vllm else None
    if use_vllm:
        logger.info("[EXTRACT] vLLM 模式：失败样本将兜底云端主 LLM（单独计数）")

    # Process each law
    checkpoint.data["stats"]["total"] = len(laws)

    # vLLM continuous batching 与云端 API 均天然支持并发；并行化把串行数小时压到 ~30min。
    # checkpoint 写操作只发生在主线程（as_completed 循环内），无需加锁。
    MAX_WORKERS = 8

    def process_one(idx: int, law_data: dict):
        """单条法律抽取（工作线程内执行）。返回 (entities, relations, source)"""
        law_name = law_data.get("name", f"law_{idx}")

        # Build comprehensive text for LLM extraction
        text_parts = [f"法律名称：{law_name}"]

        if law_data.get('level'):
            text_parts.append(f"效力层级：{law_data['level']}")

        if law_data.get('description'):
            text_parts.append(f"法律概述：{law_data['description']}")

        if law_data.get('clauses'):
            # 拼接条文（控制长度避免 token 超限）
            clause_texts = []
            for c in law_data['clauses'][:20]:
                clause_texts.append(f"{c.get('clause_no', '')} {c.get('content', '')}")
            text_parts.append("条文内容：\n" + "\n".join(clause_texts))

        if law_data.get('application_scenarios'):
            text_parts.append(f"适用场景：{', '.join(law_data['application_scenarios'])}")

        if law_data.get('related_cases'):
            case_texts = []
            for c in law_data['related_cases'][:5]:
                case_texts.append(c.get('name', ''))
            text_parts.append(f"相关案例：{', '.join(case_texts)}")

        text = "\n".join(text_parts)
        if len(text) > 6000:
            text = text[:6000] + "..."

        # Use LLM extraction for better structured data
        if use_llm:
            logger.info(f"[EXTRACT] Using LLM for: {law_name}")
            try:
                result = extractor.extract(text)
                source = "vllm" if use_vllm else "cloud"
            except Exception as llm_err:
                if cloud_fallback_chain is None:
                    raise
                logger.warning(
                    f"[EXTRACT] vLLM 抽取失败，兜底云端主 LLM: {law_name} "
                    f"({type(llm_err).__name__})"
                )
                simple_result = cloud_fallback_chain.invoke({"text": text})
                result = extractor._convert_to_result(simple_result)
                source = "cloud_fallback"
        else:
            # Fallback to dict-based extraction (for testing/offline)
            result = extractor.extract_from_dict(law_data)
            source = "dict"

        return serialize_entities(result), serialize_relations(result), source

    pending = [
        (idx, law_data)
        for idx, law_data in enumerate(laws)
        if not (resume and checkpoint.is_processed(idx))
    ]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_one, idx, d): idx for idx, d in pending}
        done_count = 0
        for fut in tqdm(as_completed(futures), total=len(futures), desc="Extracting", unit="law"):
            idx = futures[fut]
            law_name = laws[idx].get("name", f"law_{idx}")
            try:
                entities, relations, source = fut.result()
                checkpoint.add_result(idx, entities, relations, success=True)
                if source == "cloud_fallback":
                    checkpoint.data["stats"]["cloud_fallback"] = (
                        checkpoint.data["stats"].get("cloud_fallback", 0) + 1
                    )
                logger.debug(
                    f"[EXTRACT] {law_name}: {len(entities)} entities, "
                    f"{len(relations)} relations ({source})"
                )
            except Exception as e:
                logger.error(f"[EXTRACT] Failed for {law_name}: {e}")
                checkpoint.add_result(idx, [], [], success=False)

            done_count += 1
            if done_count % 10 == 0:
                checkpoint.save()

    # Final save
    checkpoint.save()

    # Save final results
    all_entities = checkpoint.data["entities"]
    all_relations = checkpoint.data["relations"]
    stats = checkpoint.get_stats()

    save_results(all_entities, all_relations, stats)

    # Print statistics
    print_statistics(all_entities, all_relations, stats)

    print("\n[SUCCESS] Extraction completed!")
    print(f"  Entities: {ENTITIES_FILE}")
    print(f"  Relations: {RELATIONS_FILE}")
    print(f"  Checkpoint: {CHECKPOINT_FILE}")


# ============================================================
# CLI Entry Point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Batch Entity Extraction for Legal Knowledge Graph"
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(INPUT_FILE),
        help=f"Input JSON file path (default: {INPUT_FILE})"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint if exists"
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Use dict-based extraction (no LLM calls)"
    )
    parser.add_argument(
        "--clear-checkpoint",
        action="store_true",
        help="Clear checkpoint before starting"
    )

    args = parser.parse_args()

    if args.clear_checkpoint:
        checkpoint = CheckpointManager(CHECKPOINT_FILE)
        checkpoint.clear()
        print("[INFO] Checkpoint cleared")

    run_extraction(
        input_path=Path(args.input),
        resume=args.resume,
        use_llm=not args.no_llm
    )


if __name__ == "__main__":
    main()
