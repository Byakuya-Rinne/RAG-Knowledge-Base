from app.core.logger import logger
from app.import_process.agent.main_graph import kb_import_app
from app.import_process.agent.state import create_custom_state

logger.info("===== 开始测试 =====")

initial_state = create_custom_state(
    task_id="task_001",
    local_file_path="万用表的使用.pdf"
)

# 只输出更最终的状态值（字典形式），不包含节点名称、执行日志、元数据等额外信息
# 执行工作流并返回最终状态

# 非流式输出
final_state = kb_import_app.invoke(initial_state)
logger.info(f"工作流执行完成！最终状态: {final_state}")

# 流式输出
# final_state = None
# for chunk in kb_import_app.stream(initial_state):
#     node_name, node_state = next(iter(chunk.items()))
#     final_state = node_state
#     logger.info(f"【{node_name}】流式输出，local_file_path={node_state['local_file_path']}")
#     pass
# logger.info(f"工作流执行完成！最终状态: {final_state}")

logger.info("图结构:")
# uv add grandalf
kb_import_app.get_graph().print_ascii()

logger.info("===== 测试结束 =====")
