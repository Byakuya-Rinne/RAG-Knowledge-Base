from app.core.logger import logger
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState


class NodePdfToMd(NodeBase):

    """
    节点: PDF转Markdown (node_pdf_to_md)
    1. 调用 MinerU (magic-pdf) 工具。
    2. 将 PDF 转换成 Markdown 格式。
    3. 将结果保存到 state["md_content"]。
    """

    name = "node_pdf_to_md"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        #实际逻辑

        return state
