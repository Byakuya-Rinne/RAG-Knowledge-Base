from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState
from app.core.logger import logger

class NodeMdImg(NodeBase):
    """
    节点: 图片处理 (node_md_img)
    1. 扫描 Markdown 中的图片链接。
    2. 将图片上传到 MinIO 对象存储。
    3. (可选) 调用多模态模型生成图片描述。
    4. 替换 Markdown 中的图片链接为 MinIO URL。
    """

    name: str = "node_md_img"

    def process(self, state: ImportGraphState) -> ImportGraphState:

        return state