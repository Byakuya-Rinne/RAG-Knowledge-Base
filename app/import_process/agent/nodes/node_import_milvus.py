import json
from typing import Dict, Any, List
from pymilvus import DataType
from app.clients.milvus_utils import get_milvus_client
from app.conf.milvus_config import milvus_config
from app.core.logger import logger
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState
from app.utils.milvus_utils import escape_milvus_string


class NodeImportMilvus(NodeBase):
    """
    节点: 导入向量库 (node_import_milvus)
    1. 连接 Milvus。
    2. 根据 item_name 删除旧数据 (幂等性)。
    3. 批量插入新的向量数据。
    """

    name: str = "node_import_milvus"

    def process(self, state: ImportGraphState) -> ImportGraphState:


        """
        LangGraph核心节点：Milvus切片数据入库主流程
        执行流程（串行执行，一步一校验，保证数据一致性）：
            1. 输入校验：验证切片有效性、向量字段完整性，提取向量维度
            2. 环境准备：连接Milvus，集合不存在则自动创建Schema与索引
            3. 幂等清理：删除item_name相同的旧数据，避免重复存储
            4. 批量插入：预处理数据后批量入库，把Milvus生成的自增chunk_id回填给chunk
            5. 状态更新：将回填了chunk_id的切片更新回全局状态，供下游使用

        异常处理：
            任一步骤失败抛出ValueError，都终止节点执行，保证数据不脏写

        必要参数：task_id、chunks
        更新参数：chunks字段回填chunk_id

        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """
        # 步骤1：输入数据有效性校验
        chunks_json_data, vector_dimension = self._step_1_check_input(state)

        # 步骤2：Milvus客户端连接+集合准备（自动建表）
        client = self._step_2_prepare_collection(vector_dimension)

        # 步骤3：幂等性处理 - 清理同item_name旧数据
        self._step_3_clean_old_data(client, chunks_json_data)

        # 步骤4：批量插入数据+主键chunk_id回填
        updated_chunks = self._step_4_insert_data(client, chunks_json_data)

        # 步骤5：更新全局状态，将回填后的切片回传下游
        state["chunks"] = updated_chunks

        return state


    def _step_1_check_input(self, state: Dict[str, Any]) -> tuple[List[Dict[str, Any]], int]:
        """
        步骤1：输入数据有效性校验
        核心校验项：
            1. chunks非空且为列表类型
            2. 切片包含dense_vector核心字段
            3. 提取向量维度，为集合创建/索引构建提供依据
        参数：
            state: Dict[str, Any] - 流程状态对象，包含上游传入的chunks数据
        返回：
            tuple - (校验通过的切片列表, 稠密向量维度)
        异常：
            任一校验项不通过，抛出ValueError终止入库流程，避免脏数据处理

        """

        # 校验1：chunks非空
        chunks = state.get("chunks", [])
        if not isinstance(chunks, list) or not chunks:
            raise ValueError("核心参数chunks为空或非列表类型")

        # 校验2：切片包含dense_vector字段
        chunk0 = chunks[0]
        if 'dense_vector' not in chunk0:
            raise ValueError("错误: 数据中缺失dense_vector字段")

        # 校验3：切片包含 sparse_vector 字段
        if 'sparse_vector' not in chunk0:
            raise ValueError("错误: 数据中缺失sparse_vector字段")

        # 提取向量维度和商品名称，用于后续集合创建/日志展示
        vector_dimension = len(chunk0["dense_vector"])
        item_name = chunk0.get('item_name', '未知商品名')
        logger.info(f"Milvus入库校验通过，待入库切片数：{len(chunks)} | 向量维度：{vector_dimension} | 商品名称：{item_name}")
        return chunks, vector_dimension




    def _step_2_prepare_collection(self, vector_dimension: int):
        """
        步骤2：Milvus客户端连接+集合准备
        核心逻辑：
            1. 获取Milvus单例客户端，验证连接有效性
            2. 集合不存在则自动创建（Schema+索引），存在则直接复用
        参数：
            vector_dimension: int - 稠密向量维度（步骤1提取）
        返回：
            MilvusClient - 已连接、集合准备完成的客户端实例
        异常：
            客户端获取失败/集合名称未配置，抛出ValueError终止流程
        """
        collection_name = milvus_config.chunks_collection
        if not collection_name:
            logger.error("Milvus集合名称未配置：CHUNKS_COLLECTION_NAME为空")
            raise ValueError("未配置CHUNKS_COLLECTION集合名称")

        client = get_milvus_client()
        if not client:
            logger.error("Milvus客户端获取失败：get_milvus_client()返回空，连接可能异常")
            raise ValueError("Milvus 连接失败：get_milvus_client() 返回空")

        # 集合不存在则自动创建
        if not client.has_collection(collection_name=collection_name):
            logger.info(f"Milvus集合{collection_name}不存在，开始自动创建Schema和索引")
            self._create_collection(client, collection_name, vector_dimension)
        else:
            logger.info(f"Milvus集合{collection_name}已存在，直接复用")
        return client


    def _create_collection(self, client, collection_name: str, vector_dimension: int):
        """
        辅助函数：Milvus集合+索引自动创建
        核心逻辑：
            1. 定义集合Schema：包含业务字段+双向量字段，自增主键chunk_id
            2. 构建向量索引：稠密向量用AUTOINDEX（Milvus自动选最优索引），稀疏向量用专用索引
        参数：
            client - MilvusClient实例（已连接）
            collection_name: str - 要创建的集合名称
            vector_dimension: int - 稠密向量维度（与向量化模型保持一致）
        """
        # create_schema -> add_field -> create_collection
        # prepare_index_params -> add_index -> create_collection

        schema = client.create_schema()
        schema.add_field(field_name="chunk_id", datatype=DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535)  # 切片内容
        schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=65535)  # 切片标题
        schema.add_field(field_name="parent_title", datatype=DataType.VARCHAR, max_length=65535)  # 父标题
        schema.add_field(field_name="part", datatype=DataType.INT8)  # 分片编号
        schema.add_field(field_name="file_title", datatype=DataType.VARCHAR, max_length=65535)  # 源文件标题
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=65535)  # 商品名称（幂等性依据）
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)  # 稀疏向量
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=vector_dimension)  # 稠密向量

        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector",
            index_name="dense_vector_index",
            index_type="AUTOINDEX",
            metric_type="COSINE"
        )

        index_params.add_index(
            field_name="sparse_vector",
            index_name="sparse_inverted_index",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="IP",
            params={"inverted_index_algo": "DAAT_MAXSCORE", "normalize": True, "quantization": "none"}
        )

        client.create_collection(collection_name=collection_name, schema=schema, index_params=index_params)
        logger.info(f"Milvus集合创建成功：{collection_name}，向量维度：{vector_dimension}")


    def _step_3_clean_old_data(self, client, chunks_json_data: List[Dict[str, Any]]):
        """
        步骤3：幂等性处理 - 基于item_name清理旧数据
        核心设计：
            插入新数据前删除同item_name的所有旧切片，确保多次执行仅保留最新数据
            支持多item_name批量清理，自动去重避免重复操作
        参数：
            client - MilvusClient实例
            chunks_json_data: List[Dict[str, Any]] - 待入库的切片列表
        """

        item_names = sorted(str(chunk.get("item_name", "")).strip()
                            for chunk in chunks_json_data or []
                            if str(chunk.get("item_name", "")).strip())

        """
        相当于: 
        # 1. 初始化一个空集合，用于自动去重
        temp_set = set()
        
        # 2. 这里的 chunks_json_data or [] 是为了防止 chunks_json_data 为 None 时报错
        data_source = chunks_json_data if chunks_json_data is not None else []
        
        # 3. 开始循环处理
        for item in data_source:
            # 提取 item_name，处理缺失值、强转字符串并去除首尾空格
            raw_name = item.get("item_name", "")
            clean_name = str(raw_name).strip()
        
            # 4. 过滤逻辑：只有当处理后的字符串不为空时，才加入集合
            if clean_name:
                temp_set.add(clean_name)
        
        # 5. 最后将集合转换为列表并进行排序
        item_names = sorted(list(temp_set))
        """

        if not item_names:
            logger.warning("Milvus幂等性清理跳过：切片中无有效item_name")
            return



        # 多item_name提示日志
        if len(item_names) > 1:
            logger.warning(f"Milvus幂等性清理：本次检测到多个item_name，将逐个清理：{item_names}")

        for item_name in item_names:
            self._clear_chunks_by_item_name(client, milvus_config.chunks_collection, item_name)



    def _clear_chunks_by_item_name(self, client, collection_name: str, item_name: str):
        """
        内部核心函数：根据item_name删除Milvus中的旧切片数据
        参数：
            client - MilvusClient实例
            collection_name: str - 集合名称
            item_name: str - 要清理的商品名称
        异常：
            清理失败抛出ValueError，终止整个入库流程（保证幂等性）
        """
        # 预处理：去除空格，空值直接返回
        item_name = (item_name or "").strip()
        if not item_name:
            logger.warning("Milvus单商品清理跳过：item_name为空")
            return
        if not collection_name:
            logger.warning("Milvus单商品清理跳过：集合名称未配置")
            return


        # 集合不存在则无需清理
        if not client.has_collection(collection_name=collection_name):
            logger.info(f"Milvus单商品清理跳过：集合{collection_name}不存在")
            return

        # 1. 商品名称安全转义，避免filter表达式报错
        safe_item_name = escape_milvus_string(item_name)
        filter_expr = f'item_name == "{safe_item_name}"'


    def _step_4_insert_data(self, client, chunks_json_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        步骤4：批量插入切片数据到Milvus+主键回填
        核心逻辑：
            1. 批量插入数据：提升入库效率，减少Milvus连接次数
            2. 回填chunk_id：将Milvus生成的自增主键回填到切片，供下游业务使用
        参数：
            client - MilvusClient实例
            chunks_json_data: List[Dict[str, Any]] - 待入库的切片列表
        返回：
            List[Dict[str, Any]] - 回填了chunk_id的切片列表
        """

        # chunks_json_data 部分有part字段, 部分没有 -> 补全part
        chunks_copy = []
        for chunk in chunks_json_data:
            chunk_copy = chunk.copy()
            if not chunk_copy.get("part"):
                chunk_copy["part"] = 0
            chunks_copy.append(chunk_copy)

        logger.info(f"开始批量插入{len(chunks_copy)}个切片")

        insert_result = client.insert(collection_name=milvus_config.chunks_collection, data=chunks_copy)

        insert_count = insert_result.get("insert_count", 0)
        logger.info(f"已批量插入{insert_count}个切片")

        # 获取返回的ids 并回填给chunks, 还给state
        ids = insert_result.get("ids", [])
        if not ids:
            for index, chunk in chunks_json_data:
                chunk["chunk_id"] = ids[index]
                logger.info(f"已回填第{index+1}个切片的chunk_id为{ids[index]}")
        return chunks_json_data





# 测试用代码
# if __name__ == "__main__":
#
#     import os
#     # 获取项目所在路径
#     from app.import_process.agent.state import create_default_state
#     from app.utils.path_util import PROJECT_ROOT
#
#
#     # 组装文件的绝对路径
#     chunks_path = PROJECT_ROOT / "output/hak180产品安全手册/chunks_with_vector.json"
#     # 读取切片
#     chunks_json = chunks_path.read_text(encoding="utf-8")
#     # 将json字符串chunks转成列表
#     chunks = json.loads(chunks_json)
#     # 当前节点图状态初始值
#     init_state = create_default_state(
#         task_id="task_001",
#         chunks=chunks
#     )
#
#     # 执行节点的业务调用
#     node_import_milvus = NodeImportMilvus()
#     final_state = node_import_milvus(init_state)