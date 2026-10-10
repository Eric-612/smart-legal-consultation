"""
Intent Classifier Agent
Classifies user query into intent types: case_analysis/law_query/legal_knowledge/urgent/general
（法律版：appointment→case_analysis、medication→law_query、knowledge→legal_knowledge、emergency→urgent）
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
from src.agents.state import AgentState, IntentType

logger = setup_logger(__name__, "agents.log")


class IntentResult(BaseModel):
    """Intent classification result"""
    intent: str = Field(description="Intent type: case_analysis/law_query/legal_knowledge/urgent/general")
    confidence: float = Field(description="Confidence score: 0-1")


SYSTEM_PROMPT = """你是一个专业的法律咨询意图识别专家。请分析用户的问题，判断其意图类型。

意图类型定义：
1. case_analysis（案例分析）：用户描述具体纠纷/争议事实，想知道适用什么法律、如何维权、胜算如何
2. law_query（条文引用）：用户询问某条法律怎么规定、适用哪条法律、条文具体内容
3. legal_knowledge（法律知识）：用户咨询法律概念、法律常识、权利义务等一般性知识
4. urgent（紧急情况）：用户面临紧急法律事项，如被刑事拘留、被逮捕、收到传票、被起诉、开庭临近、诉讼时效临近、被强制执行等
5. general（通用对话）：非法律相关问题，如问候、闲聊等

判断规则：
- 如果描述"被拖欠工资"、"被辞退怎么办"、"离婚财产怎么分"、"出了交通事故"、"对方不还钱"等具体纠纷事实，判断为 case_analysis
- 如果包含"需要什么手续"、"怎么办流程"、"怎么办理"、"如何申请"、"该走什么程序"等，**且涉及当事人自己办理具体事务**（如离婚、起诉、仲裁、继承、工伤认定、办证等），判断为 case_analysis（涉及具体事务办理，需分析流程并推荐律师）
- 如果包含"适用哪条法律"、"法律规定是"、"第几条"、"法条内容"、"赔偿标准是多少"等，判断为 law_query
- 如果包含"什么是"、"什么叫"、"有哪些权利义务"、"劳动合同和劳务合同区别"等，判断为 legal_knowledge
- 如果包含"被刑事拘留"、"被逮捕"、"收到传票"、"被起诉了"、"明天开庭"、"诉讼时效快到了"、"被强制执行"等紧急法律事项，判断为 urgent
- 其他非法律问题判断为 general

Few-shot 示例：
用户：我公司拖欠我三个月工资，能告他们吗？
意图：case_analysis，置信度：0.95

用户：离婚需要什么手续？
意图：case_analysis，置信度：0.90

用户：劳动合同法对拖欠工资是怎么规定的？
意图：law_query，置信度：0.92

用户：什么是诉讼时效？什么是劳动合同？
意图：legal_knowledge，置信度：0.93

用户：我被警察拘留了，家属该怎么办？
意图：urgent，置信度：0.98

用户：你好，今天天气怎么样？
意图：general，置信度：0.99

用户：我和房东签了合同，他想提前赶我走，怎么办？
意图：case_analysis，置信度：0.90

多轮示例：
历史：助手：为了准确分析您的案件，请补充纠纷细节… / 用户：就是工资没发
→ 结合历史，本轮是在补充案件事实，意图仍为 case_analysis。

请结合【对话历史】与【本轮用户输入】，返回意图类型和置信度。"""


class IntentClassifierAgent:
    """Intent Classifier Agent"""

    def __init__(self):
        self.llm = get_llm(temperature=0.1)
        # 显式指定 function_calling：langchain-openai 1.x 默认 method="json_schema"，
        # DashScope 兼容接口不支持该 response_format（报 400 要求 messages 含 "json"）
        self.chain = self.llm.with_structured_output(IntentResult, method="function_calling")
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", "【对话历史】\n{history}\n\n【本轮用户输入】\n{query}")
        ])

    def __call__(self, state: AgentState) -> dict:
        """Process state and return update"""
        query = state.get("query", "")
        history_text = format_history(state.get("history", []))
        logger.info(f"[IntentClassifier] Processing: {query[:50]}...")

        try:
            messages = self.prompt.format_messages(history=history_text, query=query)
            result = self.chain.invoke(messages)

            logger.info(f"[IntentClassifier] Result: {result.intent} ({result.confidence:.2f})")

            return {
                "intent": result.intent,
                "intent_confidence": result.confidence,
                "messages": [f"[IntentClassifier] Detected: {result.intent} ({result.confidence:.2f})"]
            }

        except Exception as e:
            logger.error(f"[IntentClassifier] Error: {e}")
            return {
                "intent": IntentType.GENERAL,
                "intent_confidence": 0.5,
                "messages": [f"[IntentClassifier] Error, default to general: {e}"]
            }


# Singleton instance
intent_classifier = IntentClassifierAgent()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("INTENT CLASSIFIER AGENT TEST")
    print("=" * 60)

    test_queries = [
        "我公司拖欠我三个月工资，能告他们吗？",
        "劳动合同法对拖欠工资是怎么规定的？",
        "什么是诉讼时效？",
        "我被警察拘留了，家属该怎么办？",
        "你好"
    ]

    for query in test_queries:
        print(f"\nQuery: {query}")
        state = {"query": query}
        result = intent_classifier(state)
        print(f"  Intent: {result['intent']} (confidence: {result['intent_confidence']:.2f})")

    print("\n" + "=" * 60)
    print("[SUCCESS] Intent classifier tests completed!")
