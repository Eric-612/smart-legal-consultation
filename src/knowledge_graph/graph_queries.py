"""
Knowledge Graph Queries（法律版）
Provides query functions for Agents to access the legal knowledge graph.

节点：Law / Clause / LegalIssue / Case / LegalConcept / Lawyer / LawFirm / Evidence
关系：CONTAINS / REGULATES / INVOLVES / CITES / SPECIALIZES_IN / EMPLOYS /
      NEEDS_EVIDENCE / DEFINES / RELATED_TO / APPLIES
"""

import re
import sys
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config.settings import settings
from src.common.logger import setup_logger

logger = setup_logger(__name__, "graph_queries.log")


class GraphQueries:
    """
    Legal Knowledge Graph Query Interface

    Provides high-level query functions for Agents.

    Usage:
        >>> queries = GraphQueries()
        >>> lawyers = queries.get_issue_lawyers("拖欠工资")
        >>> clauses = queries.get_issue_clauses("拖欠工资")
        >>> info = queries.get_law_full_info("中华人民共和国劳动合同法")
    """

    def __init__(self):
        self._driver = None

    def get_driver(self):
        """Get Neo4j driver"""
        if self._driver is None:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password)
            )
        return self._driver

    def close(self):
        """Close driver"""
        if self._driver:
            self._driver.close()
            self._driver = None

    # ============================================================
    # Generic Cypher Execution (for Text2Cypher)
    # ============================================================

    # L2 安全层：写关键字拒绝正则（与只读事务构成双保险）
    _WRITE_KEYWORDS = re.compile(
        r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD|FOREACH)\b|CALL\s+db",
        re.IGNORECASE,
    )

    def check_cypher_syntax(self, cypher: str, params: Optional[dict] = None) -> tuple[bool, str]:
        """
        Validate Cypher syntax with EXPLAIN (plans but does not execute).

        Args:
            cypher: Cypher query string
            params: Optional query parameters

        Returns:
            (is_valid, message) tuple
        """
        try:
            from neo4j.exceptions import CypherSyntaxError
        except ImportError:  # pragma: no cover
            return False, "neo4j 驱动未安装"
        try:
            driver = self.get_driver()
            with driver.session() as session:
                session.run(f"EXPLAIN {cypher}", params or {})
            return True, "语法正确"
        except CypherSyntaxError as e:
            return False, f"语法错误: {e}"
        except Exception as e:
            return False, f"校验失败: {e}"

    def run_readonly_cypher(self, cypher: str, params: Optional[dict] = None,
                            max_records: int = 50) -> list[dict]:
        """
        Execute an LLM-generated Cypher in a READ-ONLY transaction.

        供 Text2Cypher 引擎调用。三层安全防线：
        1. L2 写关键字拒绝：发送前正则拦截 CREATE/MERGE/DELETE/SET/... 与 CALL db* 过程调用
        2. L1 只读事务：session(default_access_mode=READ_ACCESS)，驱动层保证即使绕过
           关键字检查也无法写入（数据库直接拒绝）
        3. L5 记录数截断：枚举到 max_records 立即停止，防全表扫描打爆上下文

        Args:
            cypher: Cypher query string (must be read-only)
            params: Optional query parameters
            max_records: Maximum number of records to return

        Returns:
            List of record dicts (each record via record.data())

        Raises:
            ValueError: If the query contains write keywords (L2 rejection)
            Exception: Neo4j connection/execution errors propagate to caller
                       (Text2CypherEngine 负责兜底，绝不向上打断 ReAct 循环)
        """
        # L2: 写关键字拒绝
        if self._WRITE_KEYWORDS.search(cypher):
            logger.warning(f"[run_readonly_cypher] REJECTED write attempt: {cypher[:200]}")
            raise ValueError("仅允许执行只读 Cypher 查询（检测到写操作关键字）")

        from neo4j import READ_ACCESS

        driver = self.get_driver()
        records: list[dict] = []

        with driver.session(default_access_mode=READ_ACCESS) as session:
            def _work(tx):
                result = tx.run(cypher, params or {})
                for i, record in enumerate(result):
                    if i >= max_records:  # L5: 记录数截断
                        break
                    records.append(record.data())

            session.execute_read(_work)

        return records

    # ============================================================
    # LegalIssue Queries
    # ============================================================

    def get_issue_lawyers(self, issue: str) -> list[dict]:
        """
        根据法律争议推荐擅长该领域的律师。
        (Lawyer)-[:SPECIALIZES_IN]->(LegalIssue {name: $issue})

        Args:
            issue: 法律争议名，如 "拖欠工资"

        Returns:
            List of lawyer dicts [{name, specialty, experience_years, firm_name}]
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (l:Lawyer)-[:SPECIALIZES_IN]->(li:LegalIssue {name: $name})
                RETURN l.name AS name,
                       l.specialty AS specialty,
                       l.experience_years AS experience_years,
                       l.firm_name AS firm_name
                ORDER BY l.experience_years DESC
            """, name=issue)
            return [
                {
                    "name": record["name"],
                    "specialty": record["specialty"],
                    "experience_years": record["experience_years"],
                    "firm_name": record["firm_name"],
                }
                for record in result
            ]

    def get_issue_clauses(self, issue: str) -> list[dict]:
        """
        获取规制某法律争议的条文。
        (Clause)-[:REGULATES]->(LegalIssue {name: $issue})

        Args:
            issue: 法律争议名，如 "拖欠工资"

        Returns:
            List of clause dicts [{name, content, law_name, clause_no}]
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (c:Clause)-[:REGULATES]->(li:LegalIssue {name: $name})
                RETURN c.name AS name,
                       c.content AS content,
                       c.law_name AS law_name,
                       c.clause_no AS clause_no
                ORDER BY c.name
            """, name=issue)
            return [
                {
                    "name": record["name"],
                    "content": record["content"],
                    "law_name": record["law_name"],
                    "clause_no": record["clause_no"],
                }
                for record in result
            ]

    def get_issue_laws(self, issue: str) -> list[dict]:
        """
        获取规制某法律争议的法律（经条文关联）。
        (Law)-[:CONTAINS]->(Clause)-[:REGULATES]->(LegalIssue {name: $issue})

        Args:
            issue: 法律争议名

        Returns:
            List of law dicts [{name, level}]
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (l:Law)-[:CONTAINS]->(c:Clause)-[:REGULATES]->(li:LegalIssue {name: $name})
                RETURN DISTINCT l.name AS name, l.level AS level
                ORDER BY l.name
            """, name=issue)
            return [{"name": record["name"], "level": record["level"]} for record in result]

    def get_issue_evidence(self, issue: str) -> list[dict]:
        """
        获取某法律争议所需的证据。
        (LegalIssue {name: $issue})-[:NEEDS_EVIDENCE]->(Evidence)

        Args:
            issue: 法律争议名

        Returns:
            List of evidence dicts [{name, strength, description}]
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (li:LegalIssue {name: $name})-[:NEEDS_EVIDENCE]->(e:Evidence)
                RETURN e.name AS name,
                       e.strength AS strength,
                       e.description AS description
                ORDER BY e.name
            """, name=issue)
            return [
                {
                    "name": record["name"],
                    "strength": record["strength"],
                    "description": record["description"],
                }
                for record in result
            ]

    def get_issue_cases(self, issue: str) -> list[dict]:
        """
        获取涉及某法律争议的案例。
        (Case)-[:INVOLVES]->(LegalIssue {name: $issue})

        Args:
            issue: 法律争议名

        Returns:
            List of case dicts [{name, summary, court, result}]
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (c:Case)-[:INVOLVES]->(li:LegalIssue {name: $name})
                RETURN c.name AS name,
                       c.summary AS summary,
                       c.court AS court,
                       c.result AS result
                ORDER BY c.name
                LIMIT 10
            """, name=issue)
            return [
                {
                    "name": record["name"],
                    "summary": record["summary"],
                    "court": record["court"],
                    "result": record["result"],
                }
                for record in result
            ]

    # ============================================================
    # Law Queries
    # ============================================================

    def get_law_info(self, law_name: str) -> Optional[dict]:
        """
        Get basic information about a law

        Args:
            law_name: Name of the law

        Returns:
            Dict with law info or None
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (l:Law {name: $name})
                RETURN l.name AS name,
                       l.level AS level,
                       l.description AS description,
                       l.effective_date AS effective_date
            """, name=law_name)
            record = result.single()
            if record:
                return {
                    "name": record["name"],
                    "level": record["level"],
                    "description": record["description"],
                    "effective_date": record["effective_date"],
                }
            return None

    def get_law_clauses(self, law_name: str) -> list[dict]:
        """
        Get all clauses of a law
        (Law)-[:CONTAINS]->(Clause)

        Args:
            law_name: Name of the law

        Returns:
            List of clause dicts [{name, clause_no}]
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (l:Law {name: $name})-[:CONTAINS]->(c:Clause)
                RETURN c.name AS name,
                       c.clause_no AS clause_no,
                       c.content AS content
                ORDER BY c.clause_no
            """, name=law_name)
            return [
                {
                    "name": record["name"],
                    "clause_no": record["clause_no"],
                    "content": record["content"],
                }
                for record in result
            ]

    def get_law_full_info(self, law_name: str) -> Optional[dict]:
        """
        Get complete information about a law (with its clauses)

        Args:
            law_name: Name of the law

        Returns:
            Dict with law info and clauses, or None
        """
        info = self.get_law_info(law_name)
        if not info:
            return None
        info["clauses"] = self.get_law_clauses(law_name)
        return info

    # ============================================================
    # Clause Queries
    # ============================================================

    def get_clause_info(self, clause_name: str) -> Optional[dict]:
        """
        Get information about a clause
        Clause.name 格式为「法律名+空格+条号」，如 "劳动合同法 第三十条"

        Args:
            clause_name: Name of the clause

        Returns:
            Dict with clause info or None
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (c:Clause {name: $name})
                RETURN c.name AS name,
                       c.content AS content,
                       c.law_name AS law_name,
                       c.clause_no AS clause_no
            """, name=clause_name)
            record = result.single()
            if record:
                return {
                    "name": record["name"],
                    "content": record["content"],
                    "law_name": record["law_name"],
                    "clause_no": record["clause_no"],
                }
            return None

    def search_clauses_by_text(self, keyword: str, limit: int = 10) -> list[dict]:
        """
        Search clauses by keyword in name/content

        Args:
            keyword: Search keyword
            limit: Max results

        Returns:
            List of clause dicts [{name}]
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (c:Clause)
                WHERE c.name CONTAINS $keyword OR c.content CONTAINS $keyword
                RETURN c.name AS name
                LIMIT $limit
            """, keyword=keyword, limit=limit)
            return [{"name": record["name"]} for record in result]

    # ============================================================
    # Case Queries
    # ============================================================

    def get_case_info(self, case_name: str) -> Optional[dict]:
        """
        Get information about a case

        Args:
            case_name: Name of the case

        Returns:
            Dict with case info or None
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (c:Case {name: $name})
                RETURN c.name AS name,
                       c.summary AS summary,
                       c.court AS court,
                       c.result AS result,
                       c.judgment_date AS judgment_date
            """, name=case_name)
            record = result.single()
            if record:
                return {
                    "name": record["name"],
                    "summary": record["summary"],
                    "court": record["court"],
                    "result": record["result"],
                    "judgment_date": record["judgment_date"],
                }
            return None

    def get_case_clauses(self, case_name: str) -> list[dict]:
        """
        Get clauses cited by a case
        (Case)-[:CITES]->(Clause)

        Args:
            case_name: Name of the case

        Returns:
            List of clause dicts [{name}]
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (c:Case {name: $name})-[:CITES]->(cl:Clause)
                RETURN cl.name AS name
                ORDER BY cl.name
            """, name=case_name)
            return [{"name": record["name"]} for record in result]

    # ============================================================
    # Evidence Queries
    # ============================================================

    def get_evidence_info(self, evidence_name: str) -> Optional[dict]:
        """
        Get information about an evidence type

        Args:
            evidence_name: Name of the evidence

        Returns:
            Dict with evidence info or None
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (e:Evidence {name: $name})
                RETURN e.name AS name,
                       e.strength AS strength,
                       e.description AS description
            """, name=evidence_name)
            record = result.single()
            if record:
                return {
                    "name": record["name"],
                    "strength": record["strength"],
                    "description": record["description"],
                }
            return None

    # ============================================================
    # LegalConcept Queries
    # ============================================================

    def get_concept_info(self, concept_name: str) -> Optional[dict]:
        """
        Get information about a legal concept
        (Clause)-[:DEFINES]->(LegalConcept {name: $name})

        Args:
            concept_name: Name of the legal concept

        Returns:
            Dict with concept info or None
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (c:LegalConcept {name: $name})
                RETURN c.name AS name, c.definition AS definition
            """, name=concept_name)
            record = result.single()
            if record:
                return {"name": record["name"], "definition": record["definition"]}
            return None

    # ============================================================
    # Search Queries
    # ============================================================

    def search_laws(self, keyword: str, limit: int = 10) -> list[str]:
        """
        Search laws by keyword

        Args:
            keyword: Search keyword
            limit: Max results

        Returns:
            List of law names
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (l:Law)
                WHERE l.name CONTAINS $keyword
                   OR l.description CONTAINS $keyword
                RETURN l.name AS name
                LIMIT $limit
            """, keyword=keyword, limit=limit)
            return [record["name"] for record in result]

    def search_issues(self, keyword: str, limit: int = 10) -> list[str]:
        """
        Search legal issues by keyword

        Args:
            keyword: Search keyword
            limit: Max results

        Returns:
            List of issue names
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (li:LegalIssue)
                WHERE li.name CONTAINS $keyword
                   OR li.description CONTAINS $keyword
                RETURN li.name AS name
                LIMIT $limit
            """, keyword=keyword, limit=limit)
            return [record["name"] for record in result]

    # ============================================================
    # Statistics Queries
    # ============================================================

    def get_statistics(self) -> dict:
        """
        Get graph statistics

        Returns:
            Dict with statistics
        """
        driver = self.get_driver()
        with driver.session() as session:
            # Node counts
            result = session.run("""
                MATCH (n)
                RETURN labels(n)[0] AS label, count(n) AS count
            """)
            nodes = {r["label"]: r["count"] for r in result}

            # Relation counts
            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) AS type, count(r) AS count
            """)
            relations = {r["type"]: r["count"] for r in result}

            return {
                "nodes": nodes,
                "relations": relations,
                "total_nodes": sum(nodes.values()),
                "total_relations": sum(relations.values())
            }


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Legal Knowledge Graph Queries Test")
    print("=" * 60)

    queries = GraphQueries()

    try:
        # Test statistics
        print("\n[TEST 1] Graph Statistics")
        stats = queries.get_statistics()
        print(f"  Total nodes: {stats['total_nodes']}")
        print(f"  Total relations: {stats['total_relations']}")
        print(f"  Node types: {list(stats['nodes'].keys())}")

        # Test issue query
        print("\n[TEST 2] Issue Query (拖欠工资)")
        lawyers = queries.get_issue_lawyers("拖欠工资")
        clauses = queries.get_issue_clauses("拖欠工资")
        print(f"  Lawyers: {[l['name'] for l in lawyers]}")
        print(f"  Clauses: {[c['name'] for c in clauses]}")

        # Test law query
        print("\n[TEST 3] Law Query (中华人民共和国劳动合同法)")
        info = queries.get_law_full_info("中华人民共和国劳动合同法")
        if info:
            print(f"  Name: {info['name']}")
            print(f"  Level: {info['level']}")
            print(f"  Clauses: {[c['name'] for c in info['clauses']]}")
        else:
            print("  Law not found")

        # Test search
        print("\n[TEST 4] Search Query (劳动)")
        results = queries.search_laws("劳动")
        print(f"  Laws: {results}")

        print("\n" + "=" * 60)
        print("[SUCCESS] All query tests completed!")
        print("=" * 60)

    finally:
        queries.close()


if __name__ == "__main__":
    main()
