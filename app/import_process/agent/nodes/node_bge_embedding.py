from app.core.logger import logger
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState

class NodeBgeEmbedding(NodeBase):
    """
    节点: 向量化 (node_bge_embedding)
    1. 加载 BGE-M3 模型。
    2. 对每个 Chunk 的文本进行 Dense (稠密) 和 Sparse (稀疏) 向量化。
    3. 准备好写入 Milvus 的数据格式。
    """

    name: str = "node_bge_embedding"

    def process(self, state: ImportGraphState) -> ImportGraphState:


        return state