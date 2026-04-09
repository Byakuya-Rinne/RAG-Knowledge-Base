import json
import os
from typing import Tuple, Dict, List, Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.clients.milvus_utils import get_milvus_client, create_hybrid_search_requests, hybrid_search
from app.clients.mongo_history_utils import get_recent_messages, save_chat_message, update_message_item_names
from app.conf.milvus_config import milvus_config
from app.core.load_prompt import load_prompt
from app.lm.embedding_utils import generate_embeddings
from app.lm.lm_utils import get_llm_client
from app.query_process.agent.node_base import NodeBase
from app.core.logger import logger
from app.query_process.agent.state import QueryGraphState, create_custom_state


class NodeItemNameConfirm(NodeBase):
    """
    节点功能：确认用户问题中的核心商品名称。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_item_name_confirm"

    def process(self, state: QueryGraphState) -> QueryGraphState:
        """
        必要参数：session_id、original_query
        更新参数：history

        节点逻辑
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """
        # 步骤1：校验参数
        session_id, original_query = self._step_1_validate_param(state)
        logger.info(f"步骤1：参数校验通过")

        # 步骤2：获取历史记录
        history = get_recent_messages(session_id)
        logger.info(f"步骤2：获取到 {len(history)} 条历史消息")
        # 更新状态
        state["history"] = history

        # 步骤3：用户初始消息保存
        message_id = save_chat_message(session_id, "user", original_query)
        logger.info(f"步骤3：用户消息已初始保存, ID: {message_id}")

        # 步骤4：提取信息
        extract_res = self._step_4_extract_info(original_query, history)
        item_names = extract_res.get("item_names", [])
        rewritten_query = extract_res.get("rewritten_query", original_query)
        # 更新状态
        state["rewritten_query"] = rewritten_query

        # 5. & 6. 如果有提取到商品名，进行搜索和对齐
        align_result = {}
        if len(item_names) > 0:
            query_results = self._step_5_vectorize_and_query(item_names)
            align_result = self._step_6_align_item_names(query_results)
        else:
            logger.info("Node: 未提取到商品名，跳过向量检索")

        # 7. 检查确认状态
        state = self._step_7_check_confirmation(state, align_result, history)

        # 8. 写入最终历史
        self._step_8_write_history(state, session_id, rewritten_query, message_id)

        return state



    def _step_1_validate_param(self, state: QueryGraphState) -> Tuple[str, str]:
        """
        必要参数：session_id、original_query
        """
        # 校验 session_id, original_query
        session_id = (state.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("核心参数session_id缺失")

        original_query = state.get("original_query") or "".strip()
        if not original_query:
            raise ValueError("核心参数original_query缺失")

        return session_id, original_query


    def _step_4_extract_info(self, query, history) -> Dict:
        """
            history = [{
                "session_id": session_id,  # 会话ID，关联维度
                "role": role,  # 消息角色
                "text": text,  # 消息内容
                "rewritten_query": rewritten_query or "",  # 重写查询，空值处理为空字符串
                "item_names": item_names,  # 关联商品名称列表
                "image_urls": image_urls,  # 关联图片URL列表
                "ts": ts  # 时间戳，排序和时间筛选维度
            }, {...}]

            利用 LLM 从用户当前问题及历史会话中提取核心信息。
            :return: 字典 - 提取结果，固定包含2个字段，格式：
             {
                 "item_names": ["商品名1", "商品名2", ...],  # 提取的商品名列表，无则空列表
                 "rewritten_query": "改写后的完整问题"       # 包含商品名的独立问题，无则返回原始query
             }
        """
        try:
            logger.info("步骤4：正在初始化 LLM 客户端...")
            llm = get_llm_client(json_mode=True)

            # 构建历史对话提示词, 格式:
            #   role: text\n role: text ...
            history_text = ""
            for message in history:
                history_text += f"{message.get("role")}: {message.get("text")}\n"
            logger.info(f"步骤4： 历史上下文准备完成 (长度: {len(history_text)})")

            # 处理和动态拼接提示词
            """
                  为了让 Python 把大括号当作 “普通字符” 保留下来，f-string 规定：用双大括号 {{ 表示普通的左大括号 {，双大括号 }} 表示普通的右大括号 }。
                """
            prompt = load_prompt("rewritten_query_and_itemnames", history_text=history_text, query=query)
            logger.info(f"步骤4： 提示词加载成功")

            # 构造LLM调用的消息列表，包含系统角色（定义助手身份）和用户角色（传入提示词）
            messages = [
                SystemMessage(content="你是一个专业的客服助手，擅长理解用户意图和提取关键信息。"),
                HumanMessage(content= prompt)
            ]
            """
                    # 替换后的通用格式（兼容绝大多数LLM接口）
                    messages = [
                        {
                            "role": "system",  # SystemMessage 对应 role: "system"
                            "content": "你是一个专业的客服助手，擅长理解用户意图和提取关键信息。"
                        },
                        {
                            "role": "user",    # HumanMessage 对应 role: "user"（也可写 "human"，按接口要求调整）
                            "content": prompt  # 原 HumanMessage 的 content 直接复用
                        }
                    ]
        
                    # 如果你需要外层包一层 "messages" 键（比如适配OpenAI API格式），则写成：
                    messages = {
                        "messages": [
                            {"role": "system", "content": "你是一个专业的客服助手，擅长理解用户意图和提取关键信息。"},
                            {"role": "user", "content": prompt}
                        ]
                    }
                """

            # 调用LLM客户端，发起请求获取提取结果
            logger.info("步骤4：正在调用 LLM...")
            response = llm.invoke(messages)
            logger.info("步骤4：收到 LLM 响应：", response)

            # 提取响应中的文本内容
            content = response.content
            # 数据清洗：处理LLM可能返回的代码块格式（如```json ... ```），去除包裹符
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "")

            # 8、数据解析：将JSON字符串转为字典
            result = json.loads(content)
            logger.info(f"步骤4： 解析 LLM 结果: {result}")

            # 9、健壮性处理
            # 确保返回结果包含item_names字段，无则设为空列表
            if "item_names" not in result:
                result["item_names"] = []
            # 确保返回结果包含rewritten_query字段，无则复用原始查询
            if "rewritten_query" not in result:
                result["rewritten_query"] = query

            # 10、返回解析后的提取结果
            return result
        except Exception as e:
            # 捕获所有异常（如LLM调用失败、JSON解析失败等），记录错误日志
            logger.error(f"步骤4： LLM 提取失败: {e}")
            # 异常时返回默认结果：空商品名列表+原始查询
            return {"item_names": [], "rewritten_query": query}


    def _step_5_vectorize_and_query(self, item_names) -> List[Dict]:
        """
           把分析出的item_names逐个向量化（BGEM3模型），并在Milvus向量数据库(kb_item_names)中执行混合搜索，获取匹配评分
           :param item_names: list[字符串] - 步骤4中 提取的商品名列表（如["苹果15", "华为P60"]）
           :return: 列表[字典] - 格式：
                [
                    {
                        "extracted_name": "提取的原始商品名",  # 如"苹果15"
                        "matches": [                          # 该商品名的TopN匹配结果，无则空列表
                            {
                                "item_name": "数据库中的商品名",  # Milvus中存储的标准化商品名
                                "score": 0.98                  # 混合搜索的相似度评分（0-1，越高越相似）
                            },
                            ...
                        ]
                    },
                    ...
                ]
        """
        results = []

        # 为item_names绑定向量
        logger.info(f"开始向量化并查询条目: {item_names}")
        embeddings = generate_embeddings(item_names)
        logger.info(f"已生成 {len(item_names)} 个商品名的向量。开始 Milvus 搜索...")


        milvus_client = get_milvus_client()
        if not milvus_client:
            logger.error("连接 Milvus 失败")
            return results

        collection_name = milvus_config.item_name_collection

        # 已获得 milvus 客户端、milvus 中的 collection_name、item_names 的向量们

        # 拿每个稠密+稀疏向量对，去milvus中进行混合搜索
        # 逐个构建搜索结果：extracted_name（传入的item_names）、[{数据库中的item_names, 匹配得分}, {...}]每个商品名最匹配的5个记录

        for i, item_name in enumerate(item_names):

            try:
                # 当前 item_name 对应的双向量
                dense = embeddings.get("dense")[i]
                sparse = embeddings.get("sparse")[i]

                reqs = create_hybrid_search_requests(dense_vector=dense, sparse_vector=sparse, limit=5)

                logger.info(f"正在 Milvus 集合 '{collection_name}' 中执行混合搜索: '{item_names[i]}'")
                search_res = hybrid_search(client=milvus_client,
                                          collection_name=collection_name,
                                          reqs=reqs,
                                          ranker_weights=(0.8, 0.2),
                                          norm_score= True,
                                          limit=5,
                                          output_fields=["item_name"]
                                          )

                """
                    在 Milvus 的 Python SDK 中，hybrid_search 返回的数据结构为：
                    [
                        [hit1, hit2, ...],   # 第一个查询请求的搜索结果列表，一个hit就是一个结果
                        [...], # 第二个查询请求的搜索结果列表
                        ...
                    ]
                    这次循环中只发起了一次请求, 所以要拿search_res[0]取
                    
                    return: results 列表[字典] - 格式：
                        [
                            {
                                "extracted_name": "提取的原始商品名",  # 如"苹果15"
                                "matches": [                          # 该商品名的TopN匹配结果，无则空列表
                                    {
                                        "item_name": "数据库中的商品名",  # Milvus中存储的标准化商品名
                                        "score": 0.98                  # 混合搜索的相似度评分（0-1，越高越相似）
                                    },
                                    ...
                                ]
                            },
                            ...
                        ]
                    """

                logger.info(f"'{item_names[i]}' 搜索完成。找到 {len(search_res[0]) if search_res else 0} 个匹配项。")

                # 组装返回结果
                matches = []
                if search_res and len(search_res) > 0:
                    for hit in search_res[0]:
                        matches.append({
                            "item_name": hit.get("entity", {}).get("item_name"),
                            "score": hit.get("distance", {})
                        })

                results.append({
                    "extracted_name": item_name,
                    "matches": matches
                })
            except Exception as e:
                logger.error(f"步骤5：查询商品名 '{item_names[i]}' 时出错: {e}。跳过本轮，继续操作；如果全部失败，交由下个环节处理")

        return results

    def _step_6_align_item_names(self, query_results) -> dict:
        """
        6 根据Milvus搜索评分，逐个对齐step5提取的item_names，生成「确认商品名」和「候选商品名」
        对齐规则（优先级a>b>c>d）：
                a  如果只有一个匹配结果评分高于0.85 → 直接确认该商品名
                b  如果多条匹配结果评分超过0.85 → 优先取与原始提取名相同的，无则取分数最高的
                c  如果无0.85分以上结果 → 取分数≥0.6的最高前5个作为候选
                d  如果无0.6分及以上结果 → 不返回任何商品名（确认+候选均为空）
        :param query_results: 列表[字典] - step5的返回结果，每个商品名的搜索匹配数据（格式同step5返回值）
                query_results 列表[字典] - 格式：
                                [
                                    {
                                        "extracted_name": "提取的原始商品名",  # 如"苹果15"
                                        "matches": [                          # 该商品名的TopN匹配结果，无则空列表
                                            {
                                                "item_name": "数据库中的商品名",  # Milvus中存储的标准化商品名
                                                "score": 0.98                  # 混合搜索的相似度评分（0-1，越高越相似）
                                            },
                                            ...
                                        ]
                                    },
                                    ...
                                ]
        :return: 字典 - 商品名对齐结果，包含确认列表和候选列表，格式：
                 {
                     "confirmed_item_names": ["确认商品名1", "确认商品名2"],  # 去重后的确认商品名，无则空列表
                     "options": ["候选商品名1", "候选商品名2", ...]          # 去重后的候选商品名，无则空列表
                 }
        """
        confirmed_item_names: List[str] = []
        options: List[str] = []

        logger.info(f"步骤6：获得待处理的数据源：{query_results}")

        for query_result in query_results:
            extracted_name = (query_result.get("extracted_name", "") or  "").strip()

            matches = query_result.get("matches", []) or []

            # 若无匹配结果，直接跳过当前商品名的对齐
            if not matches:
                continue

            # 筛选高置信度匹配结果：评分>0.85
            high = [m for m in matches if m.get("score", 0) > 0.85]
            # 筛选中置信度匹配结果：评分≥0.6（仅高置信度为空时生效）
            mid = [m for m in matches if m.get("score", 0) >= 0.6]

            # 规则a: 只有一个高置信度结果（>0.85）→ 直接确认该商品名
            if len(high) == 1:
                confirmed_item_names.append(high[0].get("item_name"))
                continue  # 匹配到规则a，跳过后续规则判断

            # 规则b: 多条高置信度结果（>0.85）
            if len(high) > 1:
                highest = {"item_name": "", "score": 0}
                for high_one in high:
                    if high_one.get("item_name") == extracted_name:
                        highest = high_one
                        break
                    if high_one.get("score") > highest.get("score"):
                        highest = high_one
                confirmed_item_names.append(highest.get("item_name"))
                continue

            # 规则c: 无0.85分以上结果，取≥0.6分的最高前5个作为候选
            # 注：高置信度列表high为空时才会走到此处（规则a/b均不满足）
            if len(mid) > 0:
                # 取中置信度结果的前5个，加入候选列表
                for m in mid[:5]:
                    # confirmed_item_names 为空
                    options.append(m.get("item_name"))

            # 规则d: 无0.6分及以上结果 → 不做任何操作，确认+候选列表均为空
        return {
                    "confirmed_item_names": list(set(confirmed_item_names)),  # 去重，避免重复确认
                    "options": list(set(options))  # 去重，避免重复候选
                }


    def _step_7_check_confirmation(self, state, align_result, history):
        """
        7 检查step6对齐后的商品名状态，分3种分支更新state，并同步更新历史消息的商品名关联
        :param state: 字典 - 原始会话状态，包含session_id/original_query等核心字段
        :param align_result: 字典 - step6的对齐结果
        :param history: 列表[字典] - 近期会话历史
        :return: 字典 - 更新后的会话状态，包含item_names/answer
        """
        # 从对齐结果中提取确认商品名列表，无则空列表
        confirmed = align_result.get("confirmed_item_names", [])
        # 从对齐结果中提取候选商品名列表，无则空列表
        options = align_result.get("options", [])

        # 分支A：有确认的商品名（高置信度，无需用户确认）
        if confirmed:
            # 收集历史消息中未关联商品名的消息ID（需批量更新关联）
            ids_to_update = []

            for message in history:
                if not message.get("item_names"):
                    message_id = message.get("_id")
                    if message_id:
                        ids_to_update.append(str(message_id))
            # 若存在需更新的消息ID，批量更新历史消息的商品名关联
            if ids_to_update:
                update_message_item_names(ids_to_update, confirmed)

            # 更新会话状态：设置确认商品名、改写后的查询
            state["item_names"] = confirmed
            # 若状态中存在旧答案，删除（避免干扰后续流程）
            if "answer" in state:
                del state["answer"]
            # 返回更新后的状态
            return state

        # 分支B：无确认商品名，但有候选商品名（中置信度，需拼接提示词让用户确认）
        if options:
            # 候选商品名拼接为字符串（取前3个，避免过长），格式："商品1、商品2、商品3"
            options_str = "、".join(options[:3])
            # 构造向用户确认的提示语
            answer = f"您是想问以下哪个产品：{options_str}？请明确一下型号。"
            # 更新会话状态：设置确认提示语、清空商品名列表
            state["answer"] = answer
            state["item_names"] = []
            return state

        # 分支C：无确认商品名，且无候选商品名（无匹配结果，需用户重新提供）
        state["answer"] = "抱歉，未找到相关产品，请提供准确型号以便我为您查询。"
        state["item_names"] = []
        return state


    def _step_8_write_history(self, state, session_id, rewritten_query, message_id):
        """
         8 把本次处理的核心信息（用户问题、助手答案、商品名、改写查询）写入MongoDB的会话历史
         包含2个核心操作：1. 写入助手答案（若有）；2. 更新用户原始问题的关联信息
         :param state: 字典 - step6更新后的会话状态，包含answer/item_names等字段
         :param session_id: 字符串 - 会话唯一标识
         :param rewritten_query: 字符串 - step3改写后的完整问题
         :param message_id: 字符串 - 本次用户问题的消息唯一ID
         :return:
         """
        # 若会话状态中有助手答案（分支B/C），写入助手消息到历史
        if state.get("answer"):
            save_chat_message(
                session_id=session_id,  # 会话ID，关联所属会话
                role="assistant",  # 消息角色：助手
                text=state["answer"],  # 消息内容：向用户确认的提示语/无结果提示语
                rewritten_query="",  # 助手消息无需改写查询，设为空
                item_names=state.get("item_names", [])  # 关联的商品名列表（分支B/C均为空）
            )

        # 强制更新本次用户原始问题的关联信息（核心：补充改写查询、商品名）
        save_chat_message(
            session_id=session_id,  # 会话ID，关联所属会话
            role="user",  # 消息角色：用户
            text=state["original_query"],  # 消息内容：用户原始查询
            rewritten_query=rewritten_query,  # 补充step3改写后的完整问题
            item_names=state.get("item_names", []),  # 补充关联的商品名列表
            message_id=message_id  # 消息ID，指定更新已存在的用户消息（而非新增）
        )

        # 返回最终会话状态，供下游节点使用
        return state


















