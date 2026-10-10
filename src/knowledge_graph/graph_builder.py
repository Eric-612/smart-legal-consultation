"""
Knowledge Graph Builder（法律版）
Imports entities and relations from JSON files into Neo4j database.

节点：Law / Clause / LegalIssue / Case / LegalConcept / Lawyer / LawFirm / Evidence
关系：CONTAINS / REGULATES / INVOLVES / CITES / SPECIALIZES_IN / EMPLOYS /
      NEEDS_EVIDENCE / DEFINES / RELATED_TO / APPLIES
"""

import sys
import json
from pathlib import Path
from collections import Counter
from datetime import datetime

# Ensure project root is in sys.path
_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from tqdm import tqdm

from config.settings import settings
from config.paths import DATA_KG_DIR, LOGS_DIR
from src.common.logger import setup_logger
from src.knowledge_graph.schema import NodeType, RelationType

logger = setup_logger(__name__, "graph_builder.log")


# ============================================================
# Default Paths
# ============================================================

ENTITIES_FILE = DATA_KG_DIR / "entities.json"
RELATIONS_FILE = DATA_KG_DIR / "relations.json"


# ============================================================
# Cypher Templates
# ============================================================

NODE_CYPHER_TEMPLATES = {
    NodeType.LAW.value: """
        MERGE (n:Law {name: $name})
        ON CREATE SET
            n.level = $level,
            n.publish_date = $publish_date,
            n.effective_date = $effective_date,
            n.issuing_authority = $issuing_authority,
            n.description = $description,
            n.created_at = datetime()
        ON MATCH SET
            n.level = coalesce($level, n.level),
            n.publish_date = coalesce($publish_date, n.publish_date),
            n.effective_date = coalesce($effective_date, n.effective_date),
            n.issuing_authority = coalesce($issuing_authority, n.issuing_authority),
            n.description = coalesce($description, n.description),
            n.updated_at = datetime()
    """,
    NodeType.CLAUSE.value: """
        MERGE (n:Clause {name: $name})
        ON CREATE SET
            n.clause_no = $clause_no,
            n.law_name = $law_name,
            n.content = $content,
            n.description = $description
        ON MATCH SET
            n.clause_no = coalesce($clause_no, n.clause_no),
            n.law_name = coalesce($law_name, n.law_name),
            n.content = coalesce($content, n.content),
            n.description = coalesce($description, n.description)
    """,
    NodeType.LEGAL_ISSUE.value: """
        MERGE (n:LegalIssue {name: $name})
        ON CREATE SET
            n.description = $description,
            n.category = $category,
            n.urgency = $urgency
        ON MATCH SET
            n.description = coalesce($description, n.description),
            n.category = coalesce($category, n.category),
            n.urgency = coalesce($urgency, n.urgency)
    """,
    NodeType.CASE.value: """
        MERGE (n:Case {name: $name})
        ON CREATE SET
            n.summary = $summary,
            n.court = $court,
            n.judgment_date = $judgment_date,
            n.result = $result
        ON MATCH SET
            n.summary = coalesce($summary, n.summary),
            n.court = coalesce($court, n.court),
            n.judgment_date = coalesce($judgment_date, n.judgment_date),
            n.result = coalesce($result, n.result)
    """,
    NodeType.LEGAL_CONCEPT.value: """
        MERGE (n:LegalConcept {name: $name})
        ON CREATE SET
            n.definition = $definition
        ON MATCH SET
            n.definition = coalesce($definition, n.definition)
    """,
    NodeType.LAWYER.value: """
        MERGE (n:Lawyer {name: $name})
        ON CREATE SET
            n.specialty = $specialty,
            n.experience_years = $experience_years,
            n.bar_number = $bar_number,
            n.firm_name = $firm_name
        ON MATCH SET
            n.specialty = coalesce($specialty, n.specialty),
            n.experience_years = coalesce($experience_years, n.experience_years),
            n.bar_number = coalesce($bar_number, n.bar_number),
            n.firm_name = coalesce($firm_name, n.firm_name)
    """,
    NodeType.LAW_FIRM.value: """
        MERGE (n:LawFirm {name: $name})
        ON CREATE SET
            n.city = $city,
            n.description = $description
        ON MATCH SET
            n.city = coalesce($city, n.city),
            n.description = coalesce($description, n.description)
    """,
    NodeType.EVIDENCE.value: """
        MERGE (n:Evidence {name: $name})
        ON CREATE SET
            n.description = $description,
            n.strength = $strength
        ON MATCH SET
            n.description = coalesce($description, n.description),
            n.strength = coalesce($strength, n.strength)
    """,
}

# 历史命名 → 规范命名（schema.py RelationType）。法律版第 3 步抽取产物已用规范名，
# 保留归一表以兼容旧版/手工数据（如 "REGULATE" → "REGULATES"）。
RELATION_TYPE_ALIASES = {}

RELATION_CYPHER_TEMPLATES = {
    RelationType.CONTAINS.value: """
        MATCH (l:Law {name: $law_name})
        MATCH (c:Clause {name: $clause_name})
        MERGE (l)-[r:CONTAINS]->(c)
    """,
    RelationType.REGULATES.value: """
        MATCH (c:Clause {name: $clause_name})
        MATCH (li:LegalIssue {name: $issue_name})
        MERGE (c)-[r:REGULATES]->(li)
    """,
    RelationType.INVOLVES.value: """
        MATCH (c:Case {name: $case_name})
        MATCH (li:LegalIssue {name: $issue_name})
        MERGE (c)-[r:INVOLVES]->(li)
    """,
    RelationType.CITES.value: """
        MATCH (c:Case {name: $case_name})
        MATCH (cl:Clause {name: $clause_name})
        MERGE (c)-[r:CITES]->(cl)
    """,
    RelationType.SPECIALIZES_IN.value: """
        MATCH (ly:Lawyer {name: $lawyer_name})
        MATCH (li:LegalIssue {name: $issue_name})
        MERGE (ly)-[r:SPECIALIZES_IN]->(li)
    """,
    RelationType.EMPLOYS.value: """
        MATCH (f:LawFirm {name: $firm_name})
        MATCH (ly:Lawyer {name: $lawyer_name})
        MERGE (f)-[r:EMPLOYS]->(ly)
    """,
    RelationType.NEEDS_EVIDENCE.value: """
        MATCH (li:LegalIssue {name: $issue_name})
        MATCH (e:Evidence {name: $evidence_name})
        MERGE (li)-[r:NEEDS_EVIDENCE]->(e)
        ON CREATE SET r.necessity = $necessity
    """,
    RelationType.DEFINES.value: """
        MATCH (c:Clause {name: $clause_name})
        MATCH (lc:LegalConcept {name: $concept_name})
        MERGE (c)-[r:DEFINES]->(lc)
    """,
    RelationType.RELATED_TO.value: """
        MATCH (a:LegalIssue {name: $issue1_name})
        MATCH (b:LegalIssue {name: $issue2_name})
        MERGE (a)-[r:RELATED_TO]->(b)
    """,
    RelationType.APPLIES.value: """
        MATCH (c:Case {name: $case_name})
        MATCH (l:Law {name: $law_name})
        MERGE (c)-[r:APPLIES]->(l)
    """,
}


# R1 验收（导入即生效）：模板键必须全部出自契约枚举
_AUX_NODE_TEMPLATE_KEYS = set()
assert set(NODE_CYPHER_TEMPLATES) <= {nt.value for nt in NodeType} | _AUX_NODE_TEMPLATE_KEYS,     f"节点模板键越界: {set(NODE_CYPHER_TEMPLATES) - {nt.value for nt in NodeType} - _AUX_NODE_TEMPLATE_KEYS}"
assert set(RELATION_CYPHER_TEMPLATES) <= {rt.value for rt in RelationType},     f"关系模板键越界: {set(RELATION_CYPHER_TEMPLATES) - {rt.value for rt in RelationType}}"


# ============================================================
# Knowledge Graph Builder
# ============================================================

class KnowledgeGraphBuilder:
    """
    Knowledge Graph Builder

    Imports entities and relations from JSON files into Neo4j.

    Usage:
        >>> builder = KnowledgeGraphBuilder()
        >>> builder.build_all()
        >>> builder.print_statistics()
    """

    def __init__(
        self,
        entities_file: Path = ENTITIES_FILE,
        relations_file: Path = RELATIONS_FILE,
        batch_size: int = 500
    ):
        """
        Initialize the builder

        Args:
            entities_file: Path to entities JSON file
            relations_file: Path to relations JSON file
            batch_size: Number of records per transaction
        """
        self.entities_file = entities_file
        self.relations_file = relations_file
        self.batch_size = batch_size

        self.entities: list[dict] = []
        self.relations: list[dict] = []

        self.stats = {
            "nodes_created": Counter(),
            "relations_created": Counter(),
            "nodes_failed": 0,
            "relations_failed": 0,
        }

        self._driver = None

    def get_driver(self):
        """Get Neo4j driver (lazy initialization)"""
        if self._driver is None:
            try:
                from neo4j import GraphDatabase
                self._driver = GraphDatabase.driver(
                    settings.neo4j_uri,
                    auth=(settings.neo4j_user, settings.neo4j_password)
                )
                logger.info(f"[NEO4J] Connected to {settings.neo4j_uri}")
            except Exception as e:
                logger.error(f"[NEO4J] Connection failed: {e}")
                raise
        return self._driver

    def close(self):
        """Close Neo4j driver"""
        if self._driver:
            self._driver.close()
            self._driver = None
            logger.info("[NEO4J] Connection closed")

    def load_data(self) -> bool:
        """
        Load entities and relations from JSON files

        Returns:
            True if data loaded successfully
        """
        # Load entities
        if self.entities_file.exists():
            try:
                with open(self.entities_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.entities = data.get("entities", [])
                logger.info(f"[LOAD] Loaded {len(self.entities)} entities from {self.entities_file}")
            except Exception as e:
                logger.error(f"[LOAD] Failed to load entities: {e}")
                return False
        else:
            logger.warning(f"[LOAD] Entities file not found: {self.entities_file}")

        # Load relations
        if self.relations_file.exists():
            try:
                with open(self.relations_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.relations = data.get("relations", [])
                logger.info(f"[LOAD] Loaded {len(self.relations)} relations from {self.relations_file}")
            except Exception as e:
                logger.error(f"[LOAD] Failed to load relations: {e}")
                return False
        else:
            logger.warning(f"[LOAD] Relations file not found: {self.relations_file}")

        return True

    def build_nodes(self) -> int:
        """
        Build nodes in Neo4j using MERGE

        Returns:
            Number of nodes processed
        """
        if not self.entities:
            logger.warning("[BUILD] No entities to build")
            return 0

        driver = self.get_driver()
        processed = 0

        logger.info(f"[BUILD] Starting node build: {len(self.entities)} entities")

        for i in tqdm(range(0, len(self.entities), self.batch_size), desc="Building nodes", unit="batch"):
            batch = self.entities[i:i + self.batch_size]

            with driver.session() as session:
                for entity in batch:
                    try:
                        node_type = entity.get("type", "")
                        data = entity.get("data", {})

                        template = NODE_CYPHER_TEMPLATES.get(node_type)
                        if not template:
                            logger.warning(f"[BUILD] Unknown node type: {node_type}")
                            self.stats["nodes_failed"] += 1
                            continue

                        # Prepare parameters
                        params = self._prepare_node_params(node_type, data)

                        # Execute
                        session.run(template, params)
                        self.stats["nodes_created"][node_type] += 1
                        processed += 1

                    except Exception as e:
                        logger.error(f"[BUILD] Failed to create node: {e}")
                        self.stats["nodes_failed"] += 1

        logger.info(f"[BUILD] Node build complete: {processed} processed")
        return processed

    def build_relations(self) -> int:
        """
        Build relations in Neo4j using MERGE

        Returns:
            Number of relations processed
        """
        if not self.relations:
            logger.warning("[BUILD] No relations to build")
            return 0

        driver = self.get_driver()
        processed = 0

        logger.info(f"[BUILD] Starting relation build: {len(self.relations)} relations")

        for i in tqdm(range(0, len(self.relations), self.batch_size), desc="Building relations", unit="batch"):
            batch = self.relations[i:i + self.batch_size]

            with driver.session() as session:
                for relation in batch:
                    try:
                        rel_type = relation.get("type", "")
                        # 归一历史命名（预留，法律版当前为空表）
                        rel_type = RELATION_TYPE_ALIASES.get(rel_type, rel_type)
                        data = relation.get("data", {})

                        template = RELATION_CYPHER_TEMPLATES.get(rel_type)
                        if not template:
                            logger.warning(f"[BUILD] Unknown relation type: {rel_type}")
                            self.stats["relations_failed"] += 1
                            continue

                        # Execute
                        session.run(template, data)
                        self.stats["relations_created"][rel_type] += 1
                        processed += 1

                    except Exception as e:
                        logger.error(f"[BUILD] Failed to create relation: {e}")
                        self.stats["relations_failed"] += 1

        logger.info(f"[BUILD] Relation build complete: {processed} processed")
        return processed

    def build_all(self) -> dict:
        """
        Build complete knowledge graph (nodes first, then relations)

        Returns:
            Statistics dictionary
        """
        print("=" * 60)
        print("KNOWLEDGE GRAPH BUILD (Legal)")
        print("=" * 60)

        # Load data
        if not self.load_data():
            return {"error": "Failed to load data"}

        # Build nodes first
        print("\n[STEP 1] Building nodes...")
        nodes_count = self.build_nodes()

        # Build relations
        print("\n[STEP 2] Building relations...")
        relations_count = self.build_relations()

        # Print statistics
        self.print_statistics()

        return {
            "nodes": nodes_count,
            "relations": relations_count,
            "stats": self.stats
        }

    def _prepare_node_params(self, node_type: str, data: dict) -> dict:
        """Prepare parameters for node creation"""
        params = {"name": data.get("name", "")}

        if node_type == "Law":
            params["level"] = data.get("level")
            params["publish_date"] = data.get("publish_date")
            params["effective_date"] = data.get("effective_date")
            params["issuing_authority"] = data.get("issuing_authority")
            params["description"] = data.get("description")
        elif node_type == "Clause":
            params["clause_no"] = data.get("clause_no")
            params["law_name"] = data.get("law_name")
            params["content"] = data.get("content")
            params["description"] = data.get("description")
        elif node_type == "LegalIssue":
            params["description"] = data.get("description")
            params["category"] = data.get("category", "other")
            params["urgency"] = data.get("urgency", "medium")
        elif node_type == "Case":
            params["summary"] = data.get("summary")
            params["court"] = data.get("court")
            params["judgment_date"] = data.get("judgment_date")
            params["result"] = data.get("result")
        elif node_type == "LegalConcept":
            params["definition"] = data.get("definition")
        elif node_type == "Lawyer":
            params["specialty"] = data.get("specialty")
            params["experience_years"] = data.get("experience_years")
            params["bar_number"] = data.get("bar_number")
            params["firm_name"] = data.get("firm_name")
        elif node_type == "LawFirm":
            params["city"] = data.get("city")
            params["description"] = data.get("description")
        elif node_type == "Evidence":
            params["description"] = data.get("description")
            params["strength"] = data.get("strength")

        return params

    def print_statistics(self):
        """Print build statistics"""
        print("\n" + "=" * 60)
        print("BUILD STATISTICS")
        print("=" * 60)

        # Node statistics
        total_nodes = sum(self.stats["nodes_created"].values())
        print(f"\n[NODES] Total: {total_nodes}")
        for node_type, count in self.stats["nodes_created"].most_common():
            print(f"  {node_type}: {count}")

        if self.stats["nodes_failed"] > 0:
            print(f"  Failed: {self.stats['nodes_failed']}")

        # Relation statistics
        total_relations = sum(self.stats["relations_created"].values())
        print(f"\n[RELATIONS] Total: {total_relations}")
        for rel_type, count in self.stats["relations_created"].most_common():
            print(f"  {rel_type}: {count}")

        if self.stats["relations_failed"] > 0:
            print(f"  Failed: {self.stats['relations_failed']}")

        # Graph density (relations / nodes)
        if total_nodes > 0:
            density = total_relations / total_nodes
            print(f"\n[GRAPH DENSITY] {density:.2f} relations per node")

        print("\n" + "=" * 60)

    def get_graph_statistics(self) -> dict:
        """
        Get statistics from Neo4j database

        Returns:
            Dictionary with node and relation counts
        """
        driver = self.get_driver()

        with driver.session() as session:
            # Count nodes by label
            result = session.run("""
                MATCH (n)
                RETURN labels(n)[0] AS label, count(n) AS count
                ORDER BY count DESC
            """)
            nodes = {record["label"]: record["count"] for record in result}

            # Count relations by type
            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) AS type, count(r) AS count
                ORDER BY count DESC
            """)
            relations = {record["type"]: record["count"] for record in result}

            # Total counts
            total_nodes = sum(nodes.values())
            total_relations = sum(relations.values())

            return {
                "nodes": nodes,
                "relations": relations,
                "total_nodes": total_nodes,
                "total_relations": total_relations,
                "density": total_relations / total_nodes if total_nodes > 0 else 0
            }

    def clear_graph(self, confirm: bool = False) -> bool:
        """
        Clear all nodes and relations (DANGEROUS!)

        Args:
            confirm: Must be True to proceed

        Returns:
            True if cleared successfully
        """
        if not confirm:
            logger.warning("[CLEAR] Set confirm=True to clear graph")
            return False

        logger.warning("[CLEAR] Clearing all nodes and relations!")

        driver = self.get_driver()

        with driver.session() as session:
            # Delete all relations first
            session.run("MATCH ()-[r]-() DELETE r")
            logger.info("[CLEAR] Deleted all relations")

            # Delete all nodes
            session.run("MATCH (n) DELETE n")
            logger.info("[CLEAR] Deleted all nodes")

        return True


# ============================================================
# Main: CLI Entry Point
# ============================================================

def main():
    import argparse

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Knowledge Graph Builder")
    parser.add_argument(
        "action",
        choices=["build", "stats", "clear"],
        help="Action to perform"
    )
    parser.add_argument(
        "--entities",
        type=str,
        default=str(ENTITIES_FILE),
        help="Entities JSON file path"
    )
    parser.add_argument(
        "--relations",
        type=str,
        default=str(RELATIONS_FILE),
        help="Relations JSON file path"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for transactions (default: 500)"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm destructive action (for clear)"
    )

    args = parser.parse_args()

    builder = KnowledgeGraphBuilder(
        entities_file=Path(args.entities),
        relations_file=Path(args.relations),
        batch_size=args.batch_size
    )

    try:
        if args.action == "build":
            builder.build_all()

        elif args.action == "stats":
            stats = builder.get_graph_statistics()
            print("\n[DATABASE STATISTICS]")
            print(f"  Total nodes: {stats['total_nodes']}")
            print(f"  Total relations: {stats['total_relations']}")
            print(f"  Density: {stats['density']:.2f}")
            print("\n  Nodes by type:")
            for label, count in stats["nodes"].items():
                print(f"    {label}: {count}")
            print("\n  Relations by type:")
            for rel_type, count in stats["relations"].items():
                print(f"    {rel_type}: {count}")

        elif args.action == "clear":
            if args.confirm:
                builder.clear_graph(confirm=True)
                print("[SUCCESS] Graph cleared")
            else:
                print("[ERROR] Use --confirm to clear graph")

    finally:
        builder.close()


if __name__ == "__main__":
    main()
