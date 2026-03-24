from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState
from app.core.logger import logger

class NodeMdImg(NodeBase):


    name: str = "node_md_img"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        """
        节点: MD图片处理 (node_md_img)
        1. 扫描 Markdown 中的图片链接。
            PDF转的MD：扫描output/文档文件夹/images中的每一张支持格式的图片，逐个去转换完的md验证是否存在，存在才进行后面步骤
            用户直接上传的MD：要求文件夹也是/images
        2. 将图片上传到 MinIO 对象存储。
        3. 调用多模态VLM模型生成图片描述。
        4. 替换 Markdown 中的图片链接为 MinIO URL，并在[]中填充ai的描述信息
        """











        return state