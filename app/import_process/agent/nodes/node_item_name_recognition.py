from app.core.logger import logger
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState

class NodeItemNameRecognition(NodeBase):
    """
    节点: 主体识别 (node_item_name_recognition)
    1. 取文档前几段内容。
    2. 调用 LLM 识别这篇文档讲的是什么东西 (如: "Fluke 17B+ 万用表")。
    3. 存入 state["item_name"] 用于后续数据幂等性清理。
    """

    name: str = "node_item_name_recognition"

    def process(self, state: ImportGraphState) -> ImportGraphState:


        return state