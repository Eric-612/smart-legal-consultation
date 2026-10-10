"""
Safety Checker Agent (MOST IMPORTANT!)
Ensures all legal advice includes mandatory disclaimers and urgent-action warnings
（法律版，原医疗 Safety Checker 迁移：免责声明改为"不构成法律意见，请咨询专业律师"）
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.logger import setup_logger
from src.agents.state import AgentState

logger = setup_logger(__name__, "agents.log")


# Mandatory disclaimer (DO NOT MODIFY) —— 用户指定文案
MANDATORY_DISCLAIMER = """⚠️ 本建议仅供参考，不构成法律意见，请咨询专业律师。"""

# Urgent legal warning template
EMERGENCY_WARNING = """🚨 紧急提示：您正面临紧急法律事项（如被刑事拘留、被起诉、开庭临近、诉讼时效临近等），请立即咨询专业律师并尽快采取行动，切勿拖延！"""

# 紧急法律事项关键词（**高精度**确定性兜底：法务红旗词 + 少量无歧义的口语）。
# 口语化表述的高召回由意图识别(LLM)兜住（见 __call__ 中 intent=="urgent"）；
# 本列表是"即便意图识别失灵也必须拦下"的最后一道确定性防线，故宁精勿滥、不放宽泛词。
EMERGENCY_KEYWORDS = [
    # 人身自由
    "刑事拘留", "被拘留", "被逮捕", "逮捕", "羁押", "拘留所", "看守所", "立案侦查",
    # 诉讼程序
    "收到传票", "传票", "被起诉", "起诉了", "应诉", "开庭", "开庭日期", "判决书",
    # 强制执行 / 保全
    "被强制执行", "强制执行", "财产保全", "冻结账户", "查封", "纳入失信", "限制高消费",
    # 时效
    "诉讼时效", "时效快到了", "时效临近", "过了时效",
]


class SafetyCheckerAgent:
    """
    Safety Checker Agent

    This is the MOST IMPORTANT agent in the system.
    It ensures all legal advice includes mandatory disclaimers.
    The disclaimer is added programmatically, NOT by LLM.
    """

    def __call__(self, state: AgentState) -> dict:
        """Process state and return update"""
        query = state.get("query", "")
        intent = state.get("intent", "")
        issues = state.get("symptoms", [])
        is_emergency = state.get("is_emergency", False)
        severity = state.get("severity", "")
        medications = state.get("medications", [])

        logger.info(f"[SafetyChecker] Checking safety...")

        disclaimers = []
        warnings = []

        # 1. MANDATORY: Always add disclaimer (DO NOT SKIP!)
        disclaimers.append(MANDATORY_DISCLAIMER)

        # 2. Check for urgent legal keywords
        detected_emergency = False
        for keyword in EMERGENCY_KEYWORDS:
            if keyword in query or keyword in str(issues):
                detected_emergency = True
                break

        # 主信号 = 意图识别(LLM)判定为紧急：能覆盖口语化表述（"人被带走了""法院来通知了"），
        # 这是关键词精确匹配兜不住的高召回来源。紧急事项宁可误报、不可漏报（法律安全优先）。
        if detected_emergency or is_emergency or severity == "urgent" or intent == "urgent":
            warnings.append(EMERGENCY_WARNING)
            logger.warning(f"[SafetyChecker] URGENT detected! (keyword={detected_emergency}, intent={intent})")

        # 3. Legal citation safety reminders（条文引用意图一律提醒，即便未给出具体条文）
        if medications or intent == "law_query":
            disclaimers.append("⚠️ 法条引用提醒：法律适用需结合具体案情与证据，请以律师意见和裁判实践为准，不要仅凭条文自行判断。")

            # Check for special parties
            special_keywords = ["劳动者", "孕妇", "哺乳", "未成年人", "儿童", "老人", "老年", "残疾人", "农民工"]
            for kw in special_keywords:
                if kw in query:
                    disclaimers.append(f"⚠️ 特殊主体提醒：{kw}相关纠纷涉及特殊保护规定，请务必咨询专业律师。")
                    break

        # 4. High urgency warning
        if severity == "high":
            warnings.append("⚠️ 您的法律事项较为紧急，建议尽快咨询律师或采取法律行动，不要拖延。")

        logger.info(f"[SafetyChecker] Added {len(disclaimers)} disclaimers, {len(warnings)} warnings")

        return {
            "disclaimers": disclaimers,
            "warnings": warnings,
            "is_emergency": is_emergency or detected_emergency or intent == "urgent",
            "messages": [f"[SafetyChecker] Added {len(disclaimers)} disclaimers, {len(warnings)} warnings"]
        }


# Singleton instance
safety_checker = SafetyCheckerAgent()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("SAFETY CHECKER AGENT TEST")
    print("=" * 60)

    # Test 1: Normal query
    print("\n[Test 1] Normal query")
    state = {"query": "我公司拖欠工资", "symptoms": ["拖欠工资"], "severity": "medium", "medications": []}
    result = safety_checker(state)
    print(f"  Disclaimers: {len(result['disclaimers'])}")
    print(f"  Warnings: {len(result['warnings'])}")
    print(f"  Disclaimer text: {result['disclaimers'][0]}")

    # Test 2: Urgent query
    print("\n[Test 2] Urgent query")
    state = {"query": "我被刑事拘留了，家属该怎么办", "symptoms": ["刑事拘留"], "severity": "urgent", "medications": []}
    result = safety_checker(state)
    print(f"  Disclaimers: {len(result['disclaimers'])}")
    print(f"  Warnings: {len(result['warnings'])}")
    print(f"  Is Emergency: {result['is_emergency']}")

    print("\n" + "=" * 60)
