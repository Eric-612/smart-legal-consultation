"""
Issue Extractor Agent（法律版，原 Symptom Detector 迁移）
从用户描述（含多轮历史）中提取法律问题要点，并评估法律事项紧急性。
当案例分析意图下检测不到任何问题要点时，触发追问（needs_clarification）。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.common.llm import get_llm
from src.common.logger import setup_logger
from src.common.memory import format_history
from src.agents.state import AgentState, SeverityLevel, IntentType

logger = setup_logger(__name__, "agents.log")

# 信息不足时的标准追问话术
CLARIFY_PROMPT = (
    "为了准确为您分析案情 / 推荐律师，还需要您补充一些信息：\n"
    "① 纠纷的**具体事实**（发生了什么、时间经过）；② 涉及的**主体**（对方是谁，单位还是个人）；"
    "③ 是否已**采取过措施**（协商、投诉、仲裁/诉讼）；④ 目前**最紧急的诉求**是什么。\n"
    "您可以直接把上述情况描述给我，我来帮您判断。"
)


class IssueResult(BaseModel):
    """法律问题提取结果"""
    symptoms: list[str] = Field(description="本轮应提取的法律问题要点（争议事实关键词，遵循'以本轮为主、历史仅承接'原则）")
    severity: str = Field(description="法律事项紧急性: low/medium/high/urgent")
    is_emergency: bool = Field(description="是否为紧急法律情况（如被拘留、被起诉、开庭临近、诉讼时效临近）")


SYSTEM_PROMPT = """你是一个专业的法律问题分析专家。请提取用户描述中的法律问题要点，严格遵守下面的原则。

【核心原则：以本轮为主，历史仅用于"承接"——绝不跨话题累加问题】
1. 优先提取【本轮用户输入】中描述的法律问题要点（如：拖欠工资、违法解除劳动合同、房屋租赁纠纷、离婚财产分割、交通事故赔偿、民间借贷、合同违约等）。
2. 历史对话**仅在本轮是承接/追问**时参考：本轮本身没有任何新的事实、只是"那怎么维权""能告吗""需要什么证据"等指代上文的句子时，才把上一轮的问题要点继承过来。
3. **一旦本轮提出新的纠纷或新的法律诉求（换了话题），就只取本轮问题，绝不把历史里其他不相关的问题累加进来。**

【其他要求】
- 使用标准法律术语（如"拖欠工资""违法解除劳动合同""劳动报酬争议"）。
- 判断整体紧急程度，并检测是否为紧急法律情况。
- 注意："咨询律师""写起诉状""请个律师"等是"法律诉求/操作"，不是问题要点，不要当作问题提取。

紧急性定义：
- low：一般咨询，可自行协商（一般合同履行、日常咨询）
- medium：需要关注，宜尽快处理（拖欠货款、轻微侵权）
- high：严重，应尽快采取法律行动（被违法解除、欠薪较多、被起诉准备应诉）
- urgent：紧急，需立即行动（被刑事拘留、被逮捕、收到传票、开庭日期临近、诉讼时效临近届满、被强制执行）

紧急法律情况关键词：刑事拘留、被逮捕、立案侦查、收到传票、被起诉、诉讼时效临近届满、开庭日期临近、被强制执行、财产保全

【对比示例（务必区分 A 与 B）】
示例 A（本轮是承接、无新事实 → 继承上一轮）：
历史：用户：我公司拖欠我三个月工资 / 助手：…
本轮：那我能申请劳动仲裁吗？
问题要点：["拖欠工资"]   ← 本轮无新事实，继承上一轮
紧急性：high；是否紧急：false

示例 B（本轮换了话题 → 只取本轮，绝不继承历史）：
历史：用户：我公司拖欠工资 / 助手：…可申请劳动仲裁…
本轮：我还想咨询一下交通事故赔偿
问题要点：[]   ← 本轮是新的法律诉求（交通事故），不继承历史的欠薪
紧急性：low；是否紧急：false

示例 C（本轮有新事实 → 取本轮；仅当确属同一纠纷延续时才并入上一轮相关问题，不并入无关历史问题）：
历史：用户：我公司拖欠我工资 / 助手：…
本轮：而且他们今天把我辞退了
问题要点：["拖欠工资", "违法解除劳动合同"]   ← 同一劳动争议的延续，可合并；但绝不并入与本次无关的历史问题
紧急性：high；是否紧急：false

请分析下面的对话与本轮输入，按上述原则提取法律问题要点。"""


class IssueExtractorAgent:
    """法律问题描述提取 Agent（原 SymptomDetectorAgent）"""

    def __init__(self):
        self.llm = get_llm(temperature=0.1)
        # 显式指定 function_calling：langchain-openai 1.x 默认 method="json_schema"，
        # DashScope 兼容接口不支持该 response_format（报 400 要求 messages 含 "json"）
        self.chain = self.llm.with_structured_output(IssueResult, method="function_calling")
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", "【对话历史】\n{history}\n\n【本轮用户输入】\n{query}")
        ])

    def __call__(self, state: AgentState) -> dict:
        """Process state and return update"""
        query = state.get("query", "")
        history = state.get("history", [])
        history_text = format_history(history)
        intent = state.get("intent", "")
        logger.info(f"[IssueExtractor] Processing: {query[:50]}... (history turns: {len(history)})")

        try:
            messages = self.prompt.format_messages(history=history_text, query=query)
            result = self.chain.invoke(messages)

            logger.info(f"[IssueExtractor] Found: {result.symptoms}, urgency: {result.severity}")

            update = {
                "symptoms": result.symptoms,
                "severity": result.severity,
                "is_emergency": result.is_emergency,
                "messages": [f"[IssueExtractor] Issues: {result.symptoms}, Urgency: {result.severity}"]
            }

            # 追问仅在「案例分析意图 + 欠规格（无问题要点）」时触发：没事实就无法分析案件，必须问。
            # 条文引用意图无问题要点是合法的（条文/法条名即锚点），不追问——交给 ReAct 知识 Agent 用工具答。
            if intent == IntentType.CASE_ANALYSIS and not result.symptoms:
                update["needs_clarification"] = True
                update["clarification"] = CLARIFY_PROMPT
                logger.info("[IssueExtractor] case_analysis without issues -> needs clarification")

            return update

        except Exception as e:
            logger.error(f"[IssueExtractor] Error: {e}")
            return {
                "symptoms": [],
                "severity": SeverityLevel.MEDIUM,
                "is_emergency": False,
                "messages": [f"[IssueExtractor] Error: {e}"]
            }


# 单例名保持 symptom_detector → graph.py 零改动
symptom_detector = IssueExtractorAgent()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("ISSUE EXTRACTOR AGENT TEST")
    print("=" * 60)

    test_cases = [
        {"query": "我公司拖欠我三个月工资，能告他们吗？", "history": []},
        {"query": "我被警察刑事拘留了，家属该怎么办？", "history": []},
        # 多轮：本轮无新事实，但历史里有
        {
            "query": "那我能申请劳动仲裁吗？",
            "history": [
                {"role": "user", "content": "我公司拖欠我三个月工资，还不给劳动合同"},
                {"role": "assistant", "content": "了解到您遭遇拖欠工资、未签劳动合同…"},
            ],
        },
    ]

    for tc in test_cases:
        print(f"\nQuery: {tc['query']}  | history turns: {len(tc['history'])}")
        state = {"query": tc["query"], "history": tc["history"], "intent": IntentType.CASE_ANALYSIS}
        result = symptom_detector(state)
        print(f"  Issues: {result['symptoms']}")
        print(f"  Needs clarification: {result.get('needs_clarification', False)}")

    print("\n" + "=" * 60)
    print("[SUCCESS] Issue extractor tests completed!")
