from typing import List, Dict

from app.core.logger import logger
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState
from app.lm.embedding_utils import generate_embeddings


class NodeBgeEmbedding(NodeBase):
    """
    节点: 向量化 (node_bge_embedding)
    1. 加载 BGE-M3 模型。
    2. 对每个 Chunk 的文本进行 Dense (稠密) 和 Sparse (稀疏) 向量化。
    3. 准备好写入 Milvus 的数据格式。
    """

    name: str = "node_bge_embedding"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        """
        为chunks内容生成dense(稠密, 语义)向量, sparse(稀疏, )向量
        重要, 若无法生成, 则报错停止运行
        :param state:
        :return: state
        """
        # 步骤1：输入数据校验
        chunks = self._step_1_validate_input(state)

        # 批量生成双向量，为切片绑定向量字段
        new_chunks = self._step_2_generate_embeddings(chunks)

        state['chunks'] = new_chunks
        logger.info(f"--- BGE-M3 向量化处理完成，共处理 {len(new_chunks)} 条文本切片 ---")

        return state

    def _step_1_validate_input(self, state: ImportGraphState) -> List[Dict]:

        chunks = state.get("chunks")
        if not isinstance(chunks, List) or not chunks:
            logger.exception("警告! 警告! 向量校验失败, 无法提取到chunks有效文本信息, 无法向量化")
            raise ValueError("警告! 警告! 无法提取到chunks有效文本信息")

        logger.info(f"向量校验通过, 待处理文本切片数量: {len(chunks)}")
        return chunks

    def _step_2_generate_embeddings(self, chunks: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
            1. 文本拼接：item_name（商品名）+ 换行 + chunk的content（切片内容）
            2. 批量调用：传入拼接后的文本，生成双向量
            3. 向量绑定：为每个切片新增dense_vector/sparse_vector字段
        :param chunks:
        :return:

        如果 batch_size = 1，虽然显存压力最小，但会带来严重的性能浪费，原因主要有三点：
        A. 无法利用 GPU 的并行计算能力
        B. 频繁的 I/O 和 CPU-GPU 通信开销
        C. 算子启动开销（Kernel Overhead）
        (每次调用模型函数，系统都需要启动相应的 GPU 算子（Kernels）。启动算子是有时间成本的。频繁启动小任务的累计耗时，远高于一次启动一个大任务。)

        为什么“一次性生成”不可行？
        A. 显存溢出
        B. 动态长度导致的浪费 (Padding)
        在批量处理时，同一批次的所有文本必须对齐到该批次中最长的那句。
        如果一次性处理全部，只要有一条超长文本，所有短文本都要补零（Padding）到那个长度。
        分批处理可以将长度相近的文本放在一起，显著减少无效计算。
        batch_size 设为 2 的幂次（如 8, 16, 32, 64...）
        """
        # 1. 设置初始变量

        batch_size = 8

        total_count = len(chunks)

        # 为chunk新增两个向量字段后的新chunks
        new_chunks = []

        for i in range(0, total_count, batch_size):
            # 2. 批处理

            batch_contents = chunks[i : i + batch_size]

            # 计算当前循环批处理的数据是哪条 (输出日志提示时使用)
            start_idx = i + 1
            end_idx = min(i + batch_size, total_count)

            input_texts = []

            for input_content in batch_contents:
                # 文本拼接：item_name（商品名）+ 换行 + content（切片内容）
                item_name = input_content["item_name"]
                content = input_content["content"]
                input_text = f"{item_name}\n{content}"
                input_texts.append(input_text)

            # 调用向量模型封装好的函数批量生成双向量
            embedding_payloads = generate_embeddings(input_texts)

            if not embedding_payloads:
                error_msg = f"第{start_idx} - {end_idx}条切片，无返回结果"
                logger.error(error_msg)
                raise  RuntimeError(error_msg)

            # 将获取的双向量回填给chunks, 返还给state
            for j, batch_content in enumerate(batch_contents):
                new_chunk = batch_content.copy()
                new_chunk["dense_vector"] = embedding_payloads["dense"][j]
                new_chunk["sparse_vector"] = embedding_payloads["sparse"][j]

                new_chunks.append(new_chunk)

            logger.info(f"第{start_idx} - {end_idx} 条切片：双向量生成成功")

        return new_chunks



"""
    # 优化后的向量化步骤：引入长度排序以进一步减少 Padding 浪费
    def _step_2_generate_embeddings(self, texts_to_embed: List[Dict[str, str]]) -> List[Dict[str, str]]:

        # 1. 预处理：记录原始索引并计算拼接后的文本长度
        indexed_data = []
        for idx, doc in enumerate(texts_to_embed):
            full_text = f"{doc['item_name']}\n{doc['content']}"
            indexed_data.append({
                "original_index": idx,
                "data": doc,
                "text": full_text,
                "text_len": len(full_text)
            })

        # 2. 核心优化点：按文本长度进行排序
        # 这样长度接近的文本会被分配到同一个 Batch，极大地减少了 Padding
        indexed_data.sort(key=lambda x: x["text_len"])

        # 3. 准备分批处理
        batch_size = 5
        total = len(indexed_data)
        processed_results = []

        for i in range(0, total, batch_size):
            batch_chunk = indexed_data[i: i + batch_size]
            start_idx = i + 1
            end_idx = min(i + batch_size, total)

            # 提取当前批次的拼接文本
            input_texts = [item["text"] for item in batch_chunk]

            # 调用模型生成向量
            docs_embeddings = generate_embeddings(input_texts)

            if not docs_embeddings:
                error_msg = f"第{start_idx} - {end_idx}条切片，无返回结果"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            # 将向量结果回填，并保留原始索引
            for j, item in enumerate(batch_chunk):
                new_item = item["data"].copy()
                new_item["dense_vector"] = docs_embeddings["dense"][j]
                new_item["sparse_vector"] = docs_embeddings["sparse"][j]

                processed_results.append({
                    "original_index": item["original_index"],
                    "final_data": new_item
                })

            logger.info(f"第{start_idx} - {end_idx} 条切片（排序后）：双向量生成成功")

        # 4. 恢复原始顺序：根据 original_index 重新排序，确保下游节点拿到的数据顺序一致
        processed_results.sort(key=lambda x: x["original_index"])

        # 返回最终增强后的 chunks 列表
        return [res["final_data"] for res in processed_results]
"""















