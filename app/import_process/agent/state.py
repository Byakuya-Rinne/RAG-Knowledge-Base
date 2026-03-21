import copy
from typing import TypedDict


class ImportGraphState(TypedDict):
    # 任务唯一ID，用于追踪日志
    task_id: str

    is_md_read_enabled: bool   # 是否启用 Markdown 读取路径
    is_pdf_read_enabled: bool  # 是否启用 PDF 读取路径

    # --- 切块相关 ---
    is_normal_split_enabled: bool
    is_silicon_flow_api_enabled: bool
    is_advanced_split_enabled: bool
    is_vllm_enabled: bool

    # --- 路径相关 ---
    local_dir: str        # 当前工作目录或输出目录
    local_file_path: str  # 原始输入文件路径
    file_title: str       # 文件标题（文件名去后缀）
    pdf_path: str         # PDF 文件路径 (如果输入是PDF)
    md_path: str          # Markdown 文件路径 (转换后或直接输入的)
    split_path: str       # 分块后的文件路径
    embeddings_path: str  # 向量数据库文件路径

    # --- 内容数据 ---
    md_content: str       # Markdown 的全文内容
    chunks: list          # 切片后的文本列表，包含 metadata
    item_name: str        # 识别出的主体名称 (如: "万用表")，用于增强检索

    # --- 数据库相关 ---
    embeddings_content: list # 包含向量数据的列表，准备写入 Milvus



# 备用的默认对象
graph_default_state : ImportGraphState = {
    "task_id": "",
    "is_pdf_read_enabled": False,
    "is_md_read_enabled": False,
    "is_normal_split_enabled": True,
    "is_silicon_flow_api_enabled": True,
    "is_advanced_split_enabled": False,
    "is_vllm_enabled": False,
    "local_dir": "",
    "local_file_path": "",
    "pdf_path": "",
    "md_path": "",
    "file_title": "",
    "split_path": "",
    "embeddings_path": "",
    "md_content": "",
    "chunks": [],
    "item_name": "",
    "embeddings_content": []
}

def get_default_state() -> ImportGraphState:
    # 获取一个纯正的默认state
    return copy.deepcopy(graph_default_state)

# *abc被打包成元组, **abc被打包成字典
def create_custom_state(**overrides) -> ImportGraphState:
    state = copy.deepcopy(graph_default_state)
    state.update(overrides)
    return state



















