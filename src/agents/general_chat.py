"""
General Chat Agent
Handles non-legal queries with friendly responses
（法律版，原医疗 General Chat 迁移：引导用户使用法律咨询功能）
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.prompts import ChatPromptTemplate

from src.common.llm import get_llm
from src.common.logger import setup_logger
from src.agents.state import AgentState

logger = setup_logger(__name__, "agents.log")


SYSTEM_PROMPT = """你是一个友好的智能法律咨询助手。当用户问非法律问题时，礼貌地回应并引导用户使用法律咨询功能。

你可以回答的问题类型：
- 案例分析：描述纠纷事实，分析法律适用与维权建议
- 条文引用：查询适用的法律条文
- 法律知识：法律概念、常识科普

示例回答：
用户：你好
回答：您好！我是智能法律咨询助手，可以帮您：
1. 分析您的纠纷案件，给出维权建议
2. 查询适用的法律条文
3. 解答法律常识问题

请问有什么可以帮您的吗？

请回答用户的问题。"""


class GeneralChatAgent:
    """General Chat Agent"""

    def __init__(self):
        self.llm = get_llm(temperature=0.5)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", "{query}")
        ])

    def __call__(self, state: AgentState) -> dict:
        """Process state and return update"""
        query = state.get("query", "")
        logger.info(f"[GeneralChat] Query: {query[:50]}...")

        try:
            messages = self.prompt.format_messages(query=query)
            response = self.llm.invoke(messages)
            answer = response.content

        except Exception as e:
            logger.error(f"[GeneralChat] Error: {e}")
            answer = """您好！我是智能法律咨询助手，可以帮您：
1. 分析您的纠纷案件，给出维权建议
2. 查询适用的法律条文
3. 解答法律常识问题

请问有什么可以帮您的吗？"""

        return {
            "final_answer": answer,
            "messages": [f"[GeneralChat] Responded to general query"]
        }


# Singleton instance
general_chat = GeneralChatAgent()
