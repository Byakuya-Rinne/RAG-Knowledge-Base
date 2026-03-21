from app.core.logger import logger
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState


class NodeEntry(NodeBase):

    """
    1. 接收文件路径。
    2. 判断文件类型 (PDF/MD)。
    3. 设置 state 中的路由标记 (is_pdf_read_enabled / is_md_read_enabled)。
    """

    name = "node_entry"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        #实际逻辑
        logger.info(f"【{self.name}】节点逻辑")
        return state







