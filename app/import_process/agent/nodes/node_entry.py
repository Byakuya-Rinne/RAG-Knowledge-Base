import os

from app.core.logger import logger
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState, create_custom_state


class NodeEntry(NodeBase):

    """
    1. 接收文件路径，获取local_file_path(原始文件路径)  local_dir(输出文件的放置路径)（？）
    2. 判断文件类型 (PDF/MD)。
    3. 设置 state 中的路由标记 (is_pdf_read_enabled / is_md_read_enabled)。
    4. 提取file_title (文件标题(不含扩展名))，填充pdf_path/md_path
    """

    name = "node_entry"

    def process(self, state: ImportGraphState) -> ImportGraphState:

        local_file_path = state.get("local_file_path", "")
        if local_file_path == "":
            # logger.error("未获取到文件路径，local_file_path为空")
            raise ValueError("未获取到文件路径，local_file_path为空")

        if local_file_path.endswith(".pdf"):
            state["is_pdf_read_enabled"] = True
            state["is_md_read_enabled"] = False
            state["pdf_path"] = local_file_path

        elif local_file_path.endswith(".md"):
            state["is_pdf_read_enabled"] = False
            state["is_md_read_enabled"] = True
            state["md_path"] = local_file_path

        else:
            # logger.error("文件类型错误，仅支持.md和.pdf格式")
            raise ValueError(f"不支持的文件类型: {local_file_path} 文件类型错误，仅支持.md和.pdf格式")


        # 3. 提取不包含后缀的文件名，作为全局业务标识
        file_name = os.path.basename(local_file_path) #含扩展名
        state["file_title"] = os.path.splitext(file_name)[0] # 不含扩展名

        return state

if __name__ == "__main__":
    node_entry = NodeEntry()
    node_state = create_custom_state(
        task_id="task_001",
        local_file_path="d:/abc.md",
        local_dir="d:/output"
    )
    # node_state_final = node_entry.process(node_state) #没有增强的版本
    node_state_final = node_entry(node_state) #增强的版本






