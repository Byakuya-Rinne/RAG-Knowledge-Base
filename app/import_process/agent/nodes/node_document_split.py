from app.core.logger import logger
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState

class NodeDocumentSplit(NodeBase):
    """
    节点: 文档切分 (node_document_split)
    1. 基于 Markdown 标题层级进行递归切分。
    2. 对过长的段落进行二次切分。
    3. 生成包含 Metadata (标题路径) 的 Chunk 列表。
    """

    name: str = "node_document_split"

    def process(self, state: ImportGraphState) -> ImportGraphState:


        return state