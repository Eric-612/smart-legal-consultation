"""
Legal Consultation System Test Suite（第五步：测试与验证）

1. 单元测试：每个 Agent 的输出格式正确
2. 集成测试：意图识别 → 业务处理 → 安全检查 → 答案融合 全流程
3. 端到端测试：
   - "离婚需要什么手续？"      → 法条 + 律师推荐 + 免责声明
   - "公司不发工资怎么办？"    → 劳动法条文 + 仲裁流程 + 免责声明
   - "你好"                   → 友好回复 + 功能引导
4. 安全检查：所有法律建议类回答必须包含法律领域免责声明
   （口径：general 闲聊走 general_chat→END，不产生法律建议，故不要求免责声明；
    其余意图的业务回答一律必须带免责声明。）

用法：
    python scripts/test_agents.py             # 全部测试（消耗 LLM token）
    python scripts/test_agents.py --unit       # 仅单元测试
    python scripts/test_agents.py --integration # 仅集成测试
    python scripts/test_agents.py --e2e        # 仅端到端测试
退出码：0 = 全部通过；非 0 = 存在失败（可接入 CI）。
"""

import sys
import argparse
from pathlib import Path

_project_root = Path(__file__).parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.agents.state import AgentState, IntentType, UrgencyLevel
from src.agents.safety_checker import safety_checker, MANDATORY_DISCLAIMER
from src.agents.answer_fusion import answer_fusion
from src.agents.general_chat import general_chat
from src.agents.graph import run

PASS = "✅ PASS"
FAIL = "❌ FAIL"

_results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = ""):
    _results.append((name, ok, detail))
    print(f"  {PASS if ok else FAIL} {name}" + (f" — {detail}" if detail else ""))


# ============================================================
# 1. 单元测试：每个 Agent 输出格式正确
# ============================================================

def test_unit():
    print("\n[1] 单元测试：每个 Agent 输出格式")
    from src.agents.intent_classifier import intent_classifier
    from src.agents.symptom_detector import symptom_detector
    from src.agents.department_recommender import department_recommender
    from src.agents.medication_advisor import medication_advisor
    from src.agents.medical_knowledge import medical_knowledge
    from src.agents.pre_visit_advisor import pre_visit_advisor

    # --- intent_classifier ---
    r = intent_classifier({"query": "公司拖欠工资怎么办？"})
    ok = r.get("intent") in IntentType.ALL and 0.0 <= r.get("intent_confidence", -1) <= 1.0
    record("intent_classifier 输出格式", ok,
           f"intent={r.get('intent')} conf={r.get('intent_confidence'):.2f}")

    # --- symptom_detector (IssueExtractor) ---
    r = symptom_detector({"query": "公司拖欠工资三个月", "history": [], "intent": IntentType.CASE_ANALYSIS})
    ok = isinstance(r.get("symptoms"), list) and r.get("severity") in {lv.value for lv in UrgencyLevel} \
        and isinstance(r.get("is_emergency"), bool)
    record("symptom_detector 输出格式", ok,
           f"issues={r.get('symptoms')} urgency={r.get('severity')}")

    # --- department_recommender (LawyerRecommender) ---
    r = department_recommender({"symptoms": ["拖欠工资"], "query": "想请律师", "history": []})
    ok = isinstance(r.get("departments"), list) and isinstance(r.get("needs_clarification"), bool)
    record("department_recommender 输出格式", ok,
           f"lawyers={r.get('departments')} source={r.get('messages', [''])[0]}")

    # --- medication_advisor (ClauseCiter) ---
    r = medication_advisor({"query": "拖欠工资适用哪部法律？", "symptoms": ["拖欠工资"], "history": []})
    meds = r.get("medications") or []
    ok = isinstance(meds, list) and all(isinstance(m, dict) and m.get("name") for m in meds) \
        and isinstance(r.get("knowledge_answer"), str) and r.get("knowledge_answer")
    record("medication_advisor 输出格式", ok,
           f"clauses={[m.get('name') for m in meds]}")

    # --- medical_knowledge (LegalKnowledge, grounded-ReAct) ---
    r = medical_knowledge({"query": "什么是诉讼时效？", "history": []})
    ok = isinstance(r.get("knowledge_answer"), str) and r.get("knowledge_answer") \
        and isinstance(r.get("retrieved_entities"), list)
    record("medical_knowledge 输出格式", ok,
           f"mode=含于messages answer={len(r.get('knowledge_answer', ''))}chars")

    # --- pre_visit_advisor (LitigationGuide) ---
    r = pre_visit_advisor({"symptoms": ["拖欠工资"], "departments": ["劳动法律师"]})
    ok = isinstance(r.get("advice"), list) and len(r.get("advice")) >= 3
    record("pre_visit_advisor 输出格式", ok, f"advice={len(r.get('advice'))}条")

    # --- safety_checker ---
    r = safety_checker({"query": "公司拖欠工资", "symptoms": ["拖欠工资"], "severity": "high",
                        "medications": [], "intent": "case_analysis"})
    ok = isinstance(r.get("disclaimers"), list) and r.get("disclaimers") \
        and any(MANDATORY_DISCLAIMER in d for d in r["disclaimers"]) \
        and isinstance(r.get("warnings"), list)
    record("safety_checker 输出格式 + 免责声明", ok,
           f"disclaimers={len(r.get('disclaimers', []))} warnings={len(r.get('warnings', []))}")

    # --- answer_fusion ---
    r = answer_fusion({"query": "q", "intent": "case_analysis", "symptoms": ["拖欠工资"],
                       "departments": ["劳动法律师"], "medications": [], "knowledge_answer": "",
                       "advice": ["先协商", "再仲裁"], "disclaimers": [MANDATORY_DISCLAIMER],
                       "warnings": [], "needs_clarification": False, "clarification": ""})
    ok = isinstance(r.get("final_answer"), str)
    record("answer_fusion 输出格式", ok, f"final_answer={len(r.get('final_answer', ''))}chars")

    # --- general_chat ---
    r = general_chat({"query": "你好"})
    ok = isinstance(r.get("final_answer"), str) and r.get("final_answer")
    record("general_chat 输出格式", ok, f"answer={len(r.get('final_answer', ''))}chars")


# ============================================================
# 2. 集成测试：完整 LangGraph 流程
# ============================================================

def test_integration():
    print("\n[2] 集成测试：意图识别 → 问题提取 → 律师推荐 → 诉讼指导 → 安全检查 → 答案融合")
    query = "我公司拖欠我三个月工资，能申请劳动仲裁吗？"
    state = run(query)

    ok_intent = state.get("intent") == IntentType.CASE_ANALYSIS
    record("意图识别", ok_intent, f"intent={state.get('intent')} conf={state.get('intent_confidence'):.2f}")

    ok_issue = len(state.get("symptoms", [])) > 0
    record("问题描述提取", ok_issue, f"issues={state.get('symptoms')}")

    ok_lawyer = len(state.get("departments", [])) > 0
    record("律师推荐", ok_lawyer, f"lawyers={state.get('departments')}")

    ok_advice = len(state.get("advice", [])) > 0
    record("诉讼流程指导", ok_advice, f"advice={len(state.get('advice', []))}条")

    ok_disclaimer = any(MANDATORY_DISCLAIMER in d for d in state.get("disclaimers", []))
    record("安全检查（免责声明）", ok_disclaimer, f"disclaimers={len(state.get('disclaimers', []))}")

    ok_final = len(state.get("final_answer", "")) > 0
    record("答案融合", ok_final, f"final_answer={len(state.get('final_answer', ''))}chars")

    # 链路完整性：7 步执行链（START + 6 节点）
    n_steps = len(state.get("messages", []))
    record("执行链路节点数", n_steps >= 6, f"{n_steps} steps")

    print("  —— 执行链 ——")
    for m in state.get("messages", []):
        print(f"     {m}")


# ============================================================
# 3. 端到端测试（用户指定场景）+ 4. 安全检查
# ============================================================

def test_e2e():
    print("\n[3] 端到端测试 + [4] 免责声明安全检查")

    # 场景 1：离婚需要什么手续？
    print("\n  —— 场景 1：离婚需要什么手续？")
    s1 = run("离婚需要什么手续？")
    _check_scenario("离婚需要什么手续", s1,
                    expect_law_knowledge=True, expect_lawyer=True)

    # 场景 2：公司不发工资怎么办？
    print("\n  —— 场景 2：公司不发工资怎么办？")
    s2 = run("公司不发工资怎么办？")
    _check_scenario("公司不发工资怎么办", s2,
                    expect_lawyer=True, expect_arbitration=True)

    # 场景 3：你好（闲聊 → 功能引导，不要求免责声明）
    print("\n  —— 场景 3：你好")
    s3 = run("你好")
    ok_general = s3.get("intent") == IntentType.GENERAL and s3.get("final_answer")
    ok_guide = ("法律" in s3.get("final_answer", "")) or ("咨询" in s3.get("final_answer", ""))
    record("你好 → 友好回复", ok_general,
           f"intent={s3.get('intent')} answer={len(s3.get('final_answer', ''))}chars")
    record("你好 → 功能引导", ok_guide, "final_answer 提及法律咨询功能")


def _check_scenario(name: str, state: dict, expect_law_knowledge: bool = False,
                    expect_lawyer: bool = False, expect_arbitration: bool = False):
    """通用场景断言：免责声明必含 + 法律信息 + 按场景可选律师/条文/仲裁"""
    intent = state.get("intent")
    final = state.get("final_answer", "")

    # 4. 安全检查：法律建议类回答必须含免责声明（general 除外）
    has_disclaimer = any(MANDATORY_DISCLAIMER in d for d in state.get("disclaimers", []))
    record(f"{name} → 免责声明", has_disclaimer,
           f"intent={intent} disclaimers={len(state.get('disclaimers', []))}")

    # 法律信息（法条 / 流程 / 知识回答）
    texts = " ".join([
        final,
        " ".join(state.get("advice", [])),
        state.get("knowledge_answer", ""),
    ])
    has_law_info = any(k in texts for k in ["法", "条", "仲裁", "法院", "起诉", "诉讼", "离婚"])
    record(f"{name} → 法律信息", has_law_info, f"final={len(final)}chars")

    # 律师推荐（在 case_analysis 路由下应有）
    if expect_lawyer:
        lawyers = state.get("departments", [])
        ok = len(lawyers) > 0
        detail = f"lawyers={lawyers}" if ok else f"intent={intent}（非 case_analysis 路由时无律师字段属正常）"
        record(f"{name} → 律师推荐", ok, detail)

    # 仲裁流程（场景 2 专项）
    if expect_arbitration:
        ok = "仲裁" in texts
        record(f"{name} → 仲裁流程", ok, "advice/final 提及劳动仲裁")


def main():
    ap = argparse.ArgumentParser(description="法律问答系统测试套件")
    ap.add_argument("--unit", action="store_true", help="仅单元测试")
    ap.add_argument("--integration", action="store_true", help="仅集成测试")
    ap.add_argument("--e2e", action="store_true", help="仅端到端测试")
    args = ap.parse_args()

    only = args.unit or args.integration or args.e2e

    print("=" * 60)
    print("LEGAL CONSULTATION SYSTEM TEST SUITE")
    print("=" * 60)

    if args.unit or not only:
        test_unit()
    if args.integration or not only:
        test_integration()
    if args.e2e or not only:
        test_e2e()

    failed = [n for n, ok, _ in _results if not ok]
    print("\n" + "=" * 60)
    if failed:
        print(f"[FAILED] {len(failed)} 项未通过：{failed}")
        sys.exit(1)
    print(f"[SUCCESS] 全部 {len(_results)} 项通过")
    sys.exit(0)


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    main()
