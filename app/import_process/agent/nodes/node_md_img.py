import os

import base64
import re
from collections import deque
from pathlib import Path
from typing import Tuple, List, Dict

from langchain_core.messages import HumanMessage
from minio import Minio
from minio.deleteobjects import DeleteObject

from app.conf.lm_config import lm_config
from app.conf.minio_config import minio_config
from app.core.load_prompt import load_prompt
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState, create_custom_state
from app.core.logger import logger
from app.lm.lm_utils import get_llm_client
from app.utils.rate_limit_utils import apply_api_rate_limit


class NodeMdImg(NodeBase):


    name: str = "node_md_img"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        """
        节点: MD图片处理 (node_md_img)
        1. 扫描 Markdown 中的图片链接。
            PDF转的MD：扫描output/文档文件夹/images中的每一张支持格式的图片，逐个去转换完的md验证是否存在，存在才进行后面步骤
            用户直接上传的MD：要求文件夹也是/images
        2. 将图片上传到 MinIO 对象存储。
        3. 调用多模态VLM模型生成图片描述。
        4. 替换 Markdown 中的图片链接为 MinIO URL，并在[]中填充ai的描述信息
        """
        """
        1. 获取MD内容、文件路径、图片文件夹路径
        2. 扫描图片文件夹，筛选MD中实际引用的支持格式图片
        3. 调用多模态模型为图片生成内容摘要
        4. 将图片上传至MinIO，替换MD中本地图片路径为MinIO访问URL，并填充图片摘要
        5. 备份原MD文件，保存处理后的新MD文件并更新状态
        """
        # 步骤1：初始化数据，获取MD核心信息
        md_content, md_path_obj, images_dir = self._step_1_get_content(state)

        # 无图片文件夹，直接跳过图片处理逻辑
        if not images_dir.exists():
            logger.info(f"图片文件夹不存在，跳过图片处理：{images_dir.absolute()}")
            return state

        # 步骤2：扫描并筛选MD中已引用的图片(文件夹内有部分图片在md中没用到)
        target_images = self._step_2_scan_images(md_content, images_dir)
        if not target_images:
            logger.info("未检测到MD中引用的支持格式图片，跳过后续处理")
            return state

        # 步骤3：调用多模态大模型生成图片摘要
        summaries = self._step_3_generate_summaries(md_path_obj.stem, target_images)

        # 步骤4：上传图片至MinIO，替换MD图片路径并填充摘要
        new_md_content = self._step_4_upload_and_replace(md_path_obj.stem, target_images, summaries, md_content)

        # 步骤5：备份并保存新MD文件，更新状态中的文件路径
        new_md_file_name = self._step_5_backup_new_md_file(state['md_path'], new_md_content)

        # 步骤6：更新state状态值
        state["md_content"] = new_md_content
        state["md_path"] = new_md_file_name

        return state

    def _step_1_get_content(self, state: ImportGraphState) -> Tuple[str, Path, Path]:
        # 获取路径
        md_path = state.get("md_path", "").strip()

        # 1、参数的非空校验
        if not md_path:
            raise ValueError("核心参数md_path缺失")

        # 2、路径转换
        md_path_obj = Path(md_path)

        # 3、检查PDF文件的有效性
        if not md_path_obj.exists():
            raise ValueError(f"MD文件不存在，绝对路径: {md_path_obj.absolute()}")

        md_content = state.get("md_content", "")
        if not md_content:
            md_content = md_path_obj.read_text(encoding="utf-8")
            state["md_content"] = md_content
            logger.info(f"从文件读取MD内容完成，文件大小：{len(md_content)} 字符")
        else:
            md_content = state["md_content"]
            logger.info(f"从状态中获取MD内容完成，文件大小：{len(md_content)} 字符")

        # 5、组装图片文件夹路径：images
        images_dir = md_path_obj.parent / "images"

        return md_content, md_path_obj, images_dir

    def _step_2_scan_images(self, md_content: str, images_dir: Path) -> List[Tuple[str, str, Tuple[str, str]]]:
        """
        :param md_content: MD文件完整内容
        :param images_dir: 图片文件夹路径对象
        :return: 待处理图片列表，每个元素为(图片文件名, 图片完整路径, 图片上下文)元组
        """

        image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".jfif", ".jp2", ".avif", ".heif", ".dng"}

        target_images = []

        for image_file in os.listdir(images_dir):
            extension = os.path.splitext(image_file)[1].lower()
            if extension not in image_extensions:
                logger.warning(f"图片文件格式不支持, 跳过：{image_file}")
                continue

            # 1.2、组装完整的图片路径字符串
            img_path = str(images_dir / image_file)

            # 上下文 Tuple[str, str]
            context = self._find_context_in_md(md_content, image_file)
            if not context:
                logger.warning(f"图片未在MD中找到引用，跳过：{image_file}")
                continue
            target_images.append((image_file, img_path, context))
            logger.info(f"当前图片元数据组装完成：{image_file}，并已加入图片列表")
        logger.info(f"图片文件夹扫描完成，共{len(target_images)}张图片")
        return target_images



    def _find_context_in_md(self, md_content: str, image_file: str, context_len: int = 100) -> Tuple[str, str] | None:
        # 拿 image_file 去 md_content 里找它前后各 context_len 长度的字符

        pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_file) + r".*?\)")
        matched = pattern.match(md_content)

        # md中未出现该图片
        if not matched:
            return None

        # 正则匹配的子串在字符串 str 中的起始和结束索引位置
        start, end = matched.span()

        # 前文: start 前面 context_len 到前一个的字符串
        context_before = md_content[max(0, start - context_len):start]
        # 后文: start 前面 context_len 到前一个的字符串
        context_after = md_content[end:min(len(md_content), end + context_len)]

        # 打印上文和下文
        logger.info(f"图片{image_file}的上文：{context_before}")
        logger.info(f"图片{image_file}的下文：{context_after}")

        return context_before, context_after



    def _step_3_generate_summaries(self, doc_stem: str, target_images: List[Tuple[str, str, Tuple[str, str]]]) -> Dict[str, str]:
        # 调用 llm 生成图片摘要, 且要限制速率

        """
        :param doc_stem: 文档文件名（不含后缀），作为大模型prompt上下文
        :param targets: 待处理图片列表，元素为(图片文件名, 图片完整路径, 图片上下文)
        :param requests_per_minute: 每分钟最大API请求数，默认9次（按大模型限制调整）
        :return: 图片摘要字典，键：图片文件名，值：图片内容摘要
        """
        summaries = { }
        request_deque = deque()

        for image_file, image_path, context in target_images:

            # 速率限制
            apply_api_rate_limit(request_deque, max_requests=20, window_seconds=60)

            logger.info(f"开始生成图片摘要：{image_file}")







        pass

    def _summarize_image(self, image_path: str, root_folder: str, image_content: Tuple[str, str]) -> str:
        # 把图片文件上传给 VLM, 生成摘要

        # 1、加载并渲染提示词
        prompt_text = load_prompt(
            name="image_summary",
            root_folder=root_folder,
            image_content=image_content
        )

        # base64 格式把图片编码成字符串, 上传给 vlm
        with open(image_path, "rb") as img_file:
            img_base64_byte = base64.b64encode(img_file.read())
            img_base64 = img_base64_byte.decode("utf-8")

        # 获取VLM客户端
        vlm_client = get_llm_client(model=lm_config.lv_model)


        # 构建LangChain的message对象
        messages = [
            HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": prompt_text
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            )
        ]

        response = vlm_client.invoke(messages)

        # 6、解析模型响应
        summary = response.content.strip().replace("\n", "")
        logger.info(f"图片摘要生成成功：{image_path}，摘要：{summary}")
        return summary







    def _step_4_upload_and_replace(self, stem, target_images, summaries, md_content):
        pass

    def _step_5_backup_new_md_file(self, param, new_md_content):
        pass

