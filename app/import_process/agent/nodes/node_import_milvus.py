from app.core.logger import logger
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState

class NodeImportMilvus(NodeBase):
    """
    节点: 导入向量库 (node_import_milvus)
    1. 连接 Milvus。
    2. 根据 item_name 删除旧数据 (幂等性)。
    3. 批量插入新的向量数据。
    """

    name: str = "node_import_milvus"

    def process(self, state: ImportGraphState) -> ImportGraphState:


        logger.info(f"【{self.name}】节点逻辑")

        return state