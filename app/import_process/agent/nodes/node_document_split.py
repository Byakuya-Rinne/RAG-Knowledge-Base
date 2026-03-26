import re
from typing import Tuple, List, Dict

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.logger import logger
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState





MIN_CONTENT_LENGTH = 500  #每一段content最短是多少
MAX_CONTENT_LENGTH = 1200  #每一段content最长是多少


class NodeDocumentSplit(NodeBase):
    """
    节点: 文档切分 (node_document_split)
    1. 基于 Markdown 标题层级进行递归切分。
    2. 对过长的段落进行二次切分。
    3. 生成包含 Metadata (标题路径) 的 Chunk 列表。
    """

    name: str = "node_document_split"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        """
        节点: 文档切分 (node_document_split)
        每个切片中保留 `file_title` 和 `parent_title`（父级标题）上下文
        基于 Markdown 标题层级进行递归切分。
        若达到长度上限，则切分规则：
        标题段 -> 自然段 -> 句子
        （最小单位为一句话，无视长度限制，拒绝截断）（合并过小的块）

        标题粗切 #
        加入没有标题的
        自然段 两个回车/换行
        句号（省略号、感叹号、问号等）

        输入：md_content
        输出：新增chunks键。每个Chunk为含title/content/parent_title的字典

        """


        # 1. 加载数据
        # 从状态字典提取MD内容、文件标题，统一换行符消除系统差异，做空值兜底
        # 输出：标准化后的md_content、文件标题；无有效MD内容则直接终止节点执行
        md_content, file_title = self._step_1_get_inputs(state)



        # 2. 按标题粗切
        # 输出：初切后的章节列表、识别到的有效标题数量、MD原始文本总行数
        sections, title_count, lines_count = self._step_2_split_by_titles(md_content, file_title)

        # "title": current_title,   # 当前章节的标题
        # "content":                # 当前标题到下个标题中间的内容
        # "file_title":             # 文件大标题



        # 3. 无标题处理
        # 如果全文都没出现过标题，则整体添加“无标题”的一级标题
        sections, title_count = self._step_3_handle_no_title(md_content, sections, title_count, file_title)



        # 4. 细切+合并
        # 每个过大的 section 切分为：文档标题、章节标题 - 索引（当前章节的第几部分）、正文
        # section 添加的字段:
        #           part(本段文字是本章节的第几部分)
        #           parent(父标题)
        # 每部分加起来小于最大长度
        #
        # 合并:
        # 前一part字数小于最小字数的, 如果加后一part小于最大长度, 则合并 (需相同父标题)
        sections = self._step_4_refine_chunks(sections)














        return state


    def _step_1_get_inputs(self, state: ImportGraphState):

        # 1、参数的非空校验
        md_path = state.get("md_path", "").strip()
        if not md_path:
            raise ValueError("核心参数md_path缺失")

        file_title = state.get("file_title", "").strip()
        if not file_title:
            raise ValueError("核心参数file_title缺失")

        # 2、获取文件内容
        md_content = state.get("md_content", "").strip()
        if not md_content:
            raise ValueError("核心参数md_content缺失")

        # 3、标准化换行符
        md_content = md_content.replace("\r\n", "\n").replace("\r", "\n")

        return md_content, file_title


    def _step_2_split_by_titles(self, content: str, file_title: str) -> Tuple[List[Dict[str, str]], int, int]:
        # 输入：标准化后的md_content、文件标题
        # 输出：初切后的章节列表、识别到的有效标题数量、MD原始文本总行数
        # 栈，遇到标题（以 # 开头的行）则入栈，如果入栈时栈内标题比当前入栈标题大，则把大于等于当前标题级数的正文和标题出栈再入栈

        # 返回值 List[Dict[str, str]], int, int
        #     sections章节字典｛title  content  file_title｝, title_count标题数量, 总行数


        lines = content.split("\n")
        sections = []  # 章节列表
        title_count = 0  # 标题数量
        current_title = ""  # 当前章节的标题
        current_lines = []  # 当前标题和下一个标题之间的文本内容

        in_code_block = False  # 代码块标记：False当前没在代码块中，True当前在代码块中

        title_pattern = r'\s*#{1,6}\s+.+'

        def _flush_section():
            """内部辅助函数：将当前缓存的章节写入sections，空缓存则跳过"""
            if not current_lines:
                return
            sections.append({
                "title": current_title, #当前章节的标题
                "content": "\n".join(current_lines), #当前标题到下个标题中间的内容
                "file_title": file_title,  #文件大标题
            })


        for line in lines:
            stripped_line = line.strip()

            #在代码块内, 当作普通行写入章节，只是防止干扰标题而加判断
            if stripped_line.startswith("```") or stripped_line.startswith("~~~"):
                in_code_block = not in_code_block
                current_lines.append(line)
                continue

            #匹配标题成功，且不在代码块中
            if re.match(title_pattern, line) and not in_code_block:

                _flush_section() #把上一个章节的写到返回值章节列表中sections

                current_title = stripped_line
                title_count = title_count + 1
                current_lines = [stripped_line] #当前章节内容目前只有标题这一行
                logger.info(f"识别标题：{current_title}")

            #不是标题，普通行或者代码块
            elif not re.match(title_pattern, line):
                current_lines.append(line)

        _flush_section() #遍历结束，把剩余的内容填充返回
        logger.info(f"文档粗切（按标题切分）完成，共{len(sections)}个章节，标题数量是{title_count}，文本共有{len(lines)}行")
        return sections, title_count, len(lines)


    def _step_3_handle_no_title(self, md_content: str, sections: List[Dict[str, str]], title_count: int, file_title: str):
        if title_count == 0:
            logger.warning(f"步骤3：未识别到任何MD标题，将全文作为单个章节处理，文件：{file_title}")
            title_added_section = [{"title": "本段无标题",
                                    "content":md_content,
                                    "file_title":file_title}]
            title_count = 1
        else:
            title_added_section = sections
            logger.info(f"已识别到 {title_count} 个标题，文件：{file_title}")
        return title_added_section, title_count



    def _step_4_refine_chunks(self, sections) -> List[Dict[str, str]]:
        """
        【步骤4】Chunk精细化处理（核心：长切短合，适配大模型/检索）
        执行流程：1.切分超长章节 2.合并过短章节 3.父标题兜底（适配Milvus向量库schema）
        :param sections: 步骤3处理后的章节列表
        :return: 长度适中、低碎片化的最终Chunk列表
        """
        # section:
        # "title": current_title,   # 当前章节的标题
        # "content":                # 当前标题到下个标题中间的内容
        # "file_title":             # 文件大标题

        not_long_sections = []
        for section in sections:
        #   切分长section
            not_long_sections.extend(self._split_long_section(section))
        logger.info(f"已切分超长章节，共生成{len(not_long_sections)}个chunk")

        #   合并短section，需要当前section与下一个section
        final_sections = self._merge_short_sections(not_long_sections)
        logger.info(f"已合并过短章节，最终得到{len(final_sections)}个chunk")


        return final_sections

    def _split_long_section(self, section: Dict[str, str]) -> List[Dict[str, str]]:
        """
        【辅助函数】超长章节二次切分（核心适配LangChain分割器）
        功能：单个章节内容超限时，按「段落→句子→空格」从粗到细切分，保留语义
        切分规则：1.先按空行(\n\n)(段落) 2.再按换行(\n) 3.最后按中英文标点/空格
        :param section: 原始章节字典，必须包含content键，可选title/file_title等
        :return: 切分后的子章节列表，每个子章节带父标题/序号等元信息
        """
        # 每个过大的 section 切分为：文档标题、章节标题 - 索引（当前章节的第几部分）、正文
        # 每部分加起来小于最大长度
        # 每部分切割结果:
            # title-part: chunk_text

        # section 添加的字段:
        #           part(本段文字是本章节的第几部分)
        #           parent(父标题)

        # section:
        # "title":        # 当前章节的标题
        # "content":      # 当前标题到下个标题中间的内容
        # "file_title":   # 文件大标题

        # 每一章节的内容
        content = section.get("content", "") or ""

        # 内容不超长
        if len(content) <= MAX_CONTENT_LENGTH:
            return [section]

        file_title = section.get("file_title")
        title = section.get("title", "") or ""
        prefix = f"{title}\n\n" if title else ""
        available_len = MAX_CONTENT_LENGTH - len(prefix)
        if available_len <= 0:
            logger.warning(f"章节标题过长，无法切分：{title[:20]}...")
            return [section]

        # # 清理正文重复标题：避免原章节中正文开头重复标题，导致子Chunk内容冗余
        # body = content
        # if title and body.lstrip().startswith(title):
        #     body = body[body.find(title) + len(title):].lstrip()


        # 初始化LangChain递归分割器（核心工具：按优先级分隔符切分，保留语义）
        # separators：分割符优先级（从粗到细），优先按大语义单元切分，最后才硬拆
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=available_len,  # 正文部分最大长度（已扣除标题）
            chunk_overlap=0,           # 无重叠：按标题切分后语义完整，无需重叠
            # 分割符优先级：空行(段落)→换行→中文标点→英文标点→空格，最后硬拆
            separators=["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " "],
        )

        sub_contents = []

        for index, chunk in enumerate(splitter.split_text(content), start=1):

            # 清理空内容：跳过切分后的空字符串
            chunk_text = chunk.strip()
            if chunk_text == "":
                continue

            # 每部分切割结果:
            # title-part: chunk_text

            chunk_text = prefix + chunk_text
            sub_contents.append({
                "title": f"{title}-{index}",
                "content": chunk_text,
                "parent_title": title,
                "part": index,
                "file_title": file_title
            })
        logger.debug(f"超长章节切分完成：{title} → 生成{len(sub_contents)}个子Chunk")


        return sub_contents

    def _merge_short_sections(self, not_long_sections) -> List[Dict[str, str]]:
        pass


















#       AI生成，未验证
# def _step_2_split_by_titles(self, content: str, file_title: str) -> Tuple[List[Dict[str, str]], int, int]:
    #     """
    #     【步骤2】按Markdown标题初次切分（核心：按#分级切分，跳过代码块内标题）
    #     LangChain前置预处理：将整份MD按标题拆分为独立章节，为后续精细化切分做基础
    #     :param content: 标准化后的MD完整内容（字符串）
    #     :param file_title: 所属文件标题，用于标记章节归属
    #     :return: 切分后的章节列表、有效标题数量、原始文本总行数
    #     """
    #     lines = content.split('\n')
    #     total_lines = len(lines)
    #
    #     heading_re = re.compile(r'^(#{1,6})\s+(.*)$')
    #
    #     current_heading_stack = []          # 栈，元素为 (level, title)
    #     chunks = []
    #     current_content_lines = []
    #     current_title = ""
    #     current_parent = ""
    #     has_heading = False
    #     title_count = 0
    #
    #     in_code_block = False
    #     i = 0
    #     while i < len(lines):
    #         line = lines[i]
    #         # 检查代码块边界（以 ``` 或 ~~~ 开头）
    #         stripped = line.strip()
    #         if stripped.startswith('```') or stripped.startswith('~~~'):
    #             # 切换代码块状态（进入或退出）
    #             in_code_block = not in_code_block
    #             # 代码块标记行本身也要作为内容保留
    #             current_content_lines.append(line)
    #             i += 1
    #             continue
    #
    #         # 不在代码块内时，检查是否为标题
    #         if not in_code_block:
    #             match = heading_re.match(line)
    #             if match:
    #                 has_heading = True
    #                 title_count += 1
    #                 # 结束当前块
    #                 self._flush_chunk(chunks, current_content_lines, current_title, current_parent)
    #                 # 解析标题层级和文本
    #                 level = len(match.group(1))
    #                 title = match.group(2).strip()
    #                 # 更新栈：弹出所有层级 >= 当前层级的标题
    #                 while current_heading_stack and current_heading_stack[-1][0] >= level:
    #                     current_heading_stack.pop()
    #                 current_heading_stack.append((level, title))
    #                 # 确定父标题
    #                 if len(current_heading_stack) >= 2:
    #                     current_parent = current_heading_stack[-2][1]
    #                 else:
    #                     current_parent = ""
    #                 current_title = title
    #                 # 重置内容行（标题行本身不加入内容）
    #                 current_content_lines = []
    #                 i += 1
    #                 continue
    #
    #         # 普通内容行（或代码块内的行）
    #         current_content_lines.append(line)
    #         i += 1
    #
    #     # 处理最后一个块
    #     self._flush_chunk(chunks, current_content_lines, current_title, current_parent)
    #
    #     # 如果没有标题，将整个文档作为一个块，标题使用 file_title
    #     if not has_heading:
    #         chunks = [{
    #             "title": file_title,
    #             "parent_title": "",
    #             "content": content.strip()
    #         }]
    #         title_count = 0
    #
    #     return chunks, title_count, total_lines
    #
    # def _flush_chunk(self, chunks: List[Dict], lines: List[str], title: str, parent: str) -> None:
    #     """将累积的行集合组装成一个章节块，添加到 chunks 列表中"""
    #     if lines:
    #         chunk_content = '\n'.join(lines).strip()
    #         if chunk_content:
    #             chunks.append({
    #                 "title": title,
    #                 "parent_title": parent,
    #                 "content": chunk_content
    #             })


























