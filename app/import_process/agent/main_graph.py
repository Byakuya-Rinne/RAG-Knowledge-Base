from dotenv import load_dotenv
from langgraph.constants import END
from langgraph.graph import StateGraph

from app.import_process.agent.nodes.node_bge_embedding import NodeBgeEmbedding
from app.import_process.agent.nodes.node_document_split import NodeDocumentSplit
from app.import_process.agent.nodes.node_entry import NodeEntry
from app.import_process.agent.nodes.node_import_milvus import NodeImportMilvus
from app.import_process.agent.nodes.node_item_name_recognition import NodeItemNameRecognition
from app.import_process.agent.nodes.node_md_img import NodeMdImg
from app.import_process.agent.nodes.node_pdf_to_md import NodePdfToMd
from app.import_process.agent.state import ImportGraphState

# 初始化环境变量：必须在配置读取前执行，确保后续节点能获取到环境变量中的配置信息
load_dotenv()

workflow = StateGraph(ImportGraphState)


#对象 = 类名( )  --> 调用__init__
#对象( ) --> 调用__call__
node_entry = NodeEntry()
node_pdf_to_md = NodePdfToMd()
node_md_img = NodeMdImg()
node_document_split = NodeDocumentSplit()
node_item_name_recognition = NodeItemNameRecognition()
node_bge_embedding = NodeBgeEmbedding()
node_import_milvus = NodeImportMilvus()

workflow.add_node("node_entry", node_entry)  # 流程入口：参数初始化、输入校验
workflow.add_node("node_pdf_to_md", node_pdf_to_md)  # PDF转MD：非MD格式文件的前置处理
workflow.add_node("node_md_img", node_md_img)  # MD图片处理：保证文档中图片的可访问性
workflow.add_node("node_document_split", node_document_split)  # 文档分块：解决大文本无法向量化/推理的问题
workflow.add_node("node_item_name_recognition", node_item_name_recognition)  # 项目名识别：业务定制化步骤，提取核心业务标识
workflow.add_node("node_bge_embedding", node_bge_embedding)  # BGE向量化：文本→向量，为Milvus存储做准备
workflow.add_node("node_import_milvus", node_import_milvus)  # 向量入库：将向量数据持久化到Milvus


# 设置入口，相当于添加START的边
workflow.set_entry_point("node_entry")


def route_after_entry(state: ImportGraphState) -> str:

    # 分支1：开启MD直接导入 → 跳过PDF转MD，直接执行MD图片处理
    if state.get("is_md_read_enabled"):
        return "node_md_img"

    # 分支2：开启PDF导入 → 执行PDF转MD，再走后续流程
    elif state.get("is_pdf_read_enabled"):
        return "node_pdf_to_md"

    # 分支3：未开启任何导入配置 → 直接终止工作流（END是LangGraph内置结束常量）
    else:
        return END

workflow.add_conditional_edges(
    "node_entry",
    route_after_entry,
    {
        "node_md_img": "node_md_img",
        "node_pdf_to_md": "node_pdf_to_md",
        END: END
    }
)


workflow.add_edge("node_pdf_to_md", "node_md_img")  # PDF转MD完成 → MD图片处理
workflow.add_edge("node_md_img", "node_document_split")  # MD处理完成 → 文档分块
workflow.add_edge("node_document_split", "node_item_name_recognition")  # 分块完成 → 项目名识别
workflow.add_edge("node_item_name_recognition", "node_bge_embedding")  # 项目名识别完成 → BGE向量化
workflow.add_edge("node_bge_embedding", "node_import_milvus")  # 向量化完成 → 导入Milvus向量库
workflow.add_edge("node_import_milvus", END)  # Milvus入库完成 → 工作流执行结束（END是内置结束节点）

kb_import_app = workflow.compile()


