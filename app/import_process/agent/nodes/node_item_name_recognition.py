from typing import Tuple, List, Dict

from langchain_core.messages import SystemMessage, HumanMessage

from app.core.load_prompt import load_prompt
from app.core.logger import logger
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState
from app.lm.lm_utils import get_llm_client

# --- 配置参数 (Configuration) # --- 配置参数 (Configuration) ---
# 大模型识别商品名称的上下文切片数：取前5个切片，避免上下文过长导致大模型输入超限
DEFAULT_ITEM_NAME_CHUNK_K = 5
# 单个切片内容截断长度：防止单切片内容过长，占满大模型上下文
SINGLE_CHUNK_CONTENT_MAX_LEN = 800
# 大模型上下文总字符数上限：适配主流大模型输入限制，默认2500
CONTEXT_TOTAL_MAX_CHARS = 2500


class NodeItemNameRecognition(NodeBase):
    """
    节点: 主体识别 (node_item_name_recognition)
    1. 取文档前几段内容。
    2. 调用 LLM 识别这篇文档讲的是什么东西 (如: "Fluke 17B+ 万用表")。
    3. 存入 state["item_name"] 用于后续数据幂等性清理。
    """
    """
    LangGraph 核心节点：商品主体名称识别
    流程总览：
        1. 提取输入（文件标题+文本切片）
        2. 构建大模型上下文
        3. 调用大模型识别商品名称
        4. 回填商品名称到状态和切片
        5. 生成商品名称的稠密/稀疏向量
        6. 将数据存入Milvus向量数据库

    必要参数：task_id、file_title、chunks
    更新参数：item_name

    :param state: 工作流状态对象
    :return: 更新后的状态对象
    """

    name: str = "node_item_name_recognition"

    def process(self, state: ImportGraphState) -> ImportGraphState:

        # 步骤1：提取并校验输入
        file_title, chunks = self._step_1_get_inputs(state)

        # 步骤2：构建大模型识别的上下文
        context = self._step_2_build_context(chunks)

        # 步骤3：调用大模型识别商品名称
        item_name = self._step_3_call_llm(file_title, context)

        # 步骤4：回填商品名称到状态和切片
        self._step_4_update_chunks(state, chunks, item_name)

        # 步骤5：为商品名称生成稠密/稀疏向量
        dense_vector, sparse_vector = self._step_5_generate_vectors(item_name)

        # 步骤6：将数据存入Milvus向量数据库
        self._step_6_save_to_milvus(state, file_title, item_name, dense_vector, sparse_vector)

        # 打印识别结果
        logger.info(f"--- 识别完成: {item_name} ---")








        return state

    def _step_1_get_inputs(self, state: ImportGraphState) -> Tuple[str, List[Dict]]:
        """
        步骤 1: 接收并校验流程输入（商品名称识别的前置数据处理）
        核心作用：
            1. 从流程状态中提取文件标题、文本切片核心数据
            2. 做多层空值兜底，避免后续流程因空值报错
            3. 基础数据类型校验，保证下游流程输入有效性
        依赖的状态数据（上游节点产出）：
            - state["file_title"]: 上游提取的文件标题（优先使用）
            - state["file_name"]: 原始文件名（file_title为空时兜底）
            - state["chunks"]: 文本切片列表（每个切片为字典，含title/content等字段）
        返回值：
            Tuple[str, List[Dict]]: (处理后的文件标题, 校验后的文本切片列表)
            item_name  chunks
        """

        # 获取文本切片列表：空值时返回空列表，避免后续遍历报错
        chunks = state.get("chunks") or []


        file_title = state.get("file_title", "")

        # 二次兜底：file_title为空时，尝试从第一个有效切片中提取
        """
        part            (本段文字是本章节的第几部分)
        parent          (父标题)
        "title":        # 当前章节的标题
        "content":      # 当前标题到下个标题中间的内容
        "file_title":   # 文件大标题

        """
        if not file_title:
            file_title = chunks[0].get("file_title","")
            logger.warning("state中无有效file_title，已从第一个切片中提取兜底标题")

        # 空值日志提示：文件标题为空时不中断流程，仅记录警告
        if not file_title:
            logger.warning("state中缺少file_title和file_name，后续大模型识别可能精度下降")

        # 数据类型校验：确保chunks为有效非空列表，否则返回空列表
        if not isinstance(chunks, list) or not chunks:
            logger.warning("state中chunks为空或非列表类型，无法进行商品名称识别")
            return file_title, []

        logger.info(f"步骤1：输入校验完成，获取到{len(chunks)}个有效文本切片")
        return file_title, chunks


    def _step_2_build_context(self, chunks: List[Dict]) -> str:
        """
        步骤 2: 构造大模型商品名称识别的标准化上下文
        核心作用：
            1. 限制切片数量：仅取前k个切片，避免上下文过长
            2. 限制字符长度：总上下文字符限制，适配大模型输入上限
            3. 格式化内容：带序号的结构化格式，提升大模型识别精度
        参数说明：
            chunks: 文本切片列表
        返回值：
            str: 格式化后的上下文字符串
            给ai生成主题用的提示词，含标题、chunk内容
        """

        total_len = 0
        # 存储格式化后的切片片段，保证上下文结构化
        parts: List[str] = []

        for index, chunk in enumerate(chunks[:DEFAULT_ITEM_NAME_CHUNK_K], start=1):
            chunk_content = chunk.get("content", "").strip()

            # 结构化格式化切片：带序号+标题+内容，提升大模型识别效率
            part = f"【切片{index}】\n \n标题与内容：{chunk_content}"
            #   chunk_content 内部已经有了 f"{title}\n\n"
            total_len += len(part)

            parts.append(part)

            # 总字符数超限时立即停止下一次拼接，避免大模型输入超限
            #(有可能已经超限，需要后续硬裁切)
            if total_len >= CONTEXT_TOTAL_MAX_CHARS:
                logger.info(f"上下文总字数：{total_len}，已超限（{CONTEXT_TOTAL_MAX_CHARS}），已停止拼接后续切片")
                break

        # 3、用空行分隔切片片段，拼接为最终上下文，去重空格
        context = "\n\n".join(parts).strip()

        final_context = context[:CONTEXT_TOTAL_MAX_CHARS]
        logger.info(f"步骤2：上下文构建完成，最终长度{len(final_context)}字符")
        return final_context



    def _step_3_call_llm(self, file_title: str, context: str) -> str:
        """
        步骤 3: 调用大模型实现商品名称/型号精准识别
        核心逻辑：
            1. 上下文为空 → 直接返回file_title（兜底，无需调用大模型）
            2. 上下文非空 → 加载标准化prompt模板，构建大模型对话消息
            3. 调用LLM，过滤返回结果中的无效字符
            4. 大模型返回空/调用异常 → 均返回file_title兜底，保证流程不中断
        核心特性：
            - 提示词解耦：通过load_prompt加载本地模板，无需硬编码
            - 格式兼容：兼容不同LLM客户端返回格式，防止属性报错
            - 异常兜底：全异常捕获，大模型服务不可用时不影响主流程
        参数：
            file_title: 处理后的文件标题（异常/空值时的兜底值）
            context: 步骤2构建的结构化切片上下文（大模型识别的核心依据）
        返回值：
            str: 清洗后的商品名称（异常/空值时返回原始file_title）
        """
        logger.info("开始执行步骤3：调用大模型识别商品名称")

        try:
            if not context:
                logger.exception("警告！！！用来调用llm生成主体名的上下文为空！！！使用文件标题当作主体名")
                return file_title

            # 上一步结果正常
            else:
                human_prompt = load_prompt("item_name_recognition", file_title=file_title, context=context)
                system_prompt = load_prompt("product_recognition_system")
                logger.debug(
                    f"大模型调用提示词构建完成，系统提示词长度{len(system_prompt)}，人类提示词长度{len(human_prompt)}")

                llm = get_llm_client()

                if not llm:
                    logger.exception("大模型客户端创建失败，使用文件名称兜底")
                    return file_title

                messages = [
                    SystemMessage(content= system_prompt),
                    HumanMessage(content= human_prompt)
                ]

                response = llm.invoke(messages)

                # 不同的框架版本、不同llm接口返回的内容可能在不同的key中
                possible_fields = ["content", "text", "message", "response"]
                item_name = ""
                for field in possible_fields:
                    extracted_text = getattr(response, field, None)
                    if extracted_text:
                        item_name = extracted_text.strip()
                        break
                # 7、清洗返回结果：过滤空格、换行、回车、制表符等无效字符
                item_name = item_name.replace(" ", "").replace("\n", "").replace("\r", "").replace("\t", "")

                if not item_name:
                    logger.warning("大模型返回空结果，使用文件名称兜底")
                    return file_title
                logger.info(f"模型识别商品名称成功，识别结果是：{item_name}")

                return item_name


        except Exception as e:
            logger.exception("警告！！！调用LLM生成主体名失败！！！使用文件标题当作主体名")
            return file_title





    def _step_4_update_chunks(self, state: ImportGraphState, chunks: List[Dict], item_name: str):
        """
        步骤 4: 回填商品名称到流程状态和所有文本切片
        核心作用：
            1. 全局状态更新：将item_name存入state，供下游所有节点直接使用
            2. 切片数据补全：为每个切片添加item_name字段，保证数据一致性
            3. 状态同步：更新state中的chunks，确保切片修改全局生效
        设计思路：
            所有切片关联同一商品名称，保证后续向量入库、检索时的维度一致性
        参数：
            state: 流程状态对象（ImportGraphState），全局数据载体
            chunks: 校验后的文本切片列表（步骤1输出）
            item_name: 步骤3识别并清洗后的商品名称
        """

        state["item_name"] = item_name

        for chunk in chunks:
            chunk["item_name"] = item_name

        state["chunks"] = chunks
        logger.info(f"步骤4：商品名称回填完成，共为{len(chunks)}个切片添加item_name字段，值为：{item_name}")


    def _step_5_generate_vectors(self, item_name: str) -> Tuple[List | None, Dict | None] :
        """
        步骤 5: 为商品名称生成BGE-M3稠密+稀疏双向量（Milvus向量检索核心）
        核心说明：
            - 稠密向量（dense_vector）：BGE-M3固定1024维，记录文本深层语义信息
            - 稀疏向量（sparse_vector）：变长键值对，记录文本关键词/特征位置信息
        依赖工具：
            generate_embeddings：封装BGE-M3模型，批量生成双向量，兼容单条/批量输入
        参数：
            item_name: 步骤3识别的商品名称（非空，空值时直接返回空向量）
        返回值：
            Tuple[Any, Any]: (稠密向量列表, 稀疏向量字典)，空值/异常时返回(None, None)
        """




























