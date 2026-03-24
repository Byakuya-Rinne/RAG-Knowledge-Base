import shutil
import time
import zipfile
from os import rename
from pathlib import Path
from time import sleep

import requests

from app.conf.mineru_config import mineru_config
from app.import_process.agent.node_base import NodeBase
from app.import_process.agent.state import ImportGraphState, create_custom_state
from app.core.logger import logger


class NodePdfToMd(NodeBase):

    """
    节点: PDF转Markdown (node_pdf_to_md)
    pdf转md，先获取文件全路径（local_file_path）和输出目录（local_dir）
    上传至minerU，且间隔固定时长查询进度，给到实时进度反馈
    转换完成后，下载解压获取的压缩包，且正确重命名
    读取文档内容md_content，填写md_path

    """

    name = "node_pdf_to_md"




    def process(self, state: ImportGraphState) -> ImportGraphState:

        #1. 校验文件输入输出位置是否已经填写，输出目录如果为空则新建文件夹
        pdf_path_obj, output_dir_obj = self._step_1_validate_paths(state)

        #2. 上传至minerU，且间隔固定时长查询进度，给到实时进度反馈
        full_zip_url = self._step_2_upload_and_poll(pdf_path_obj, output_dir_obj)

        #3. 下载解压获取的压缩包，且正确重命名
        md_path = self._step_3_download_and_extract(full_zip_url, output_dir_obj, pdf_path_obj.stem)

        #4. 读取文档内容md_content
        with open(md_path, 'r', encoding="utf-8") as f:
            md_content = f.read()

        # 步骤5：更新state状态值
        state["md_content"] = md_content
        state["md_path"] = md_path

        return state






    def _step_1_validate_paths(self, state:ImportGraphState ):
        if not state.get("local_dir", "").strip():
            raise ValueError["输出路径未填写，操作失败"]
        if not state.get("pdf_path", "").strip():
            raise ValueError["输入路径未填写，操作失败"]

        pdf_path_obj = Path(state.get("pdf_path", "").strip())
        output_dir_obj = Path(state.get("local_dir", "").strip()) #输出路径

        if not pdf_path_obj.exists():
            raise ValueError(f"PDF文件不存在，绝对路径: {pdf_path_obj.absolute()}")

        if not output_dir_obj.exists():
            logger.info("输出路径为空，开始创建文件夹")
            output_dir_obj.mkdir(parents=True, exist_ok=True)

        return pdf_path_obj, output_dir_obj













    def _step_2_upload_and_poll(self, pdf_path_obj: Path, output_dir_obj: Path):
        # 1、参数校验
        if not mineru_config.base_url or not mineru_config.api_token:
            raise ValueError("MinerU配置缺失：请在 .env 文件中正确配置 MINERU_API_TOKEN 和 MINERU_BASE_URL 参数")
        logger.info(f"【配置校验】MinerU配置校验成功，开始处理文件：{pdf_path_obj.name}")

        # 2、向MinerU服务器获取上传链接
        token = mineru_config.api_token
        url = f"{mineru_config.base_url}/file-urls/batch"
        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        data = {
            "files": [
                {"name":pdf_path_obj.name}
            ],
            "model_version":"vlm"
        }
        logger.info(f"【获取上传链接】调用接口：{url}，请求参数：{data}")

        get_link_res = requests.post(url, headers=header, json=data)
        # code int 接口状态码，成功：0
        # msg string 接口处理信息，成功："ok"
        # trace_id string 请求ID
        # data.task_id  string  提取任务id，可用于查询任务结果

        if get_link_res.status_code != 200:
            raise RuntimeError(f"【获取上传链接】响应失败：状态码：{get_link_res.status_code}，响应结果：{get_link_res.text}")

        get_link_res_json = get_link_res.json()

        if get_link_res_json.get("code") != 0 :
            raise RuntimeError(f"【获取上传链接】接口调用业务失败：返回数据：{get_link_res_json}")

        # 成功获取了上传链接
        upload_link = get_link_res_json["data"]["file_urls"][0]
        batch_id = get_link_res_json["data"]["batch_id"]

        # 3、准备上传
        logger.info(f"【准备上传】开始上传PDF文件：{pdf_path_obj.name}")

        with open(pdf_path_obj, "rb") as f:
            file_data = f.read()

        try:
            upload__resp = requests.put(url=upload_link, data=file_data, timeout=30)
            if upload__resp.status_code != 200:
                raise RuntimeError(f"【文件上传】上传失败：状态码：{upload__resp.status_code}")
            logger.info(f"【文件上传】上传成功，文件{pdf_path_obj.name}已进入云存储")
        except Exception as e:
            raise RuntimeError(f"【文件上传】上传失败：{str(e)}")


        # 4、轮询解析结果（batch_id）
        result_url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
        start_time = time.time() #记录开始时间
        timeout_seconds = 600 #最大超时时间
        sleep_time = 5 #轮询间隔时间

        logger.info(f"【任务轮询】开始轮询解析结果，请稍候...batch_id：{batch_id}")
        flag = True

        while flag:
            elapsed_time = time.time() - start_time
            if elapsed_time > timeout_seconds:
                raise TimeoutError(f"【任务轮询】超时，batch_id：{batch_id}")

            result = requests.get(result_url, headers=header)

            # 先检查http响应
            if result.status_code != 200:
                raise RuntimeError(f"【任务轮询】请求失败，状态码：{result.status_code}，batch_id：{batch_id}")
            # 校验任务的业务状态
            result_json = result.json()
            if result_json.get("code") != 0:
                raise RuntimeError(f"【任务轮询】接口调用业务失败：返回数据：{result_json}")

            extract_result = result_json["data"]["extract_result"]
            if not extract_result:
                logger.info(f"【任务轮询】结果为空：已耗时{int(elapsed_time)}s，继续等待")
                time.sleep(sleep_time)
                continue

            result_item = extract_result[0]
            analyze_state = result_item["state"]

            elapsed_time = time.time() - start_time
            if analyze_state == "waiting-file":
                logger.info(f"等待文件上传中, 已耗时{int(elapsed_time)}s")
                time.sleep(sleep_time)
            elif analyze_state == "pending":
                logger.info(f"排队中, 已耗时{int(elapsed_time)}s")
                time.sleep(sleep_time)
            elif analyze_state == "running":
                logger.info(f"正在解析, 已耗时{int(elapsed_time)}s")
                time.sleep(sleep_time)
            elif analyze_state == "converting":
                logger.info(f"格式转换中, 已耗时{int(elapsed_time)}s")
                time.sleep(sleep_time)
            elif analyze_state == "failed":
                logger.error(f"解析失败!!!, 已耗时{int(elapsed_time)}s, batch_id：{batch_id}")
                raise RuntimeError(f"【任务轮询】解析任务失败！batch_id：{batch_id}")

            elif analyze_state == "done":
                logger.info(f"解析完成, 已耗时{int(elapsed_time)}s，batch_id：{batch_id}")
                flag = False
                full_zip_url = result_item["full_zip_url"]
                logger.info(f"解析完成, zip下载地址{full_zip_url}")
                return full_zip_url









    def _step_3_download_and_extract(self, zip_url: str, output_dir_obj: Path, pdf_stem: str) -> str:

        # 下载解压获取的压缩包，且正确重命名
        logger.info(f"【ZIP下载】开始下载ZIP包：{zip_url} ...")
        download_response = requests.get(zip_url, timeout=120)

        if not download_response.status_code == 200:
            raise RuntimeError(f"【ZIP下载】ZIP包下载失败：状态码：{download_response.status_code}")


        # zip文件Path对象
        zip_save_path = output_dir_obj / f"{pdf_stem}_result.zip"


        with open(zip_save_path, "wb") as file:
            file.write(download_response.content)
        logger.info(f"【ZIP下载】ZIP包下载成功：保存路径：{zip_save_path}")

        # 清空旧的解压目录
        logger.info(f"【ZIP解压】开始解压ZIP包：{output_dir_obj} ...")
        # 要解压的目录
        extract_target_dir = output_dir_obj / pdf_stem

        # 清空要解压文件存放的目录
        if extract_target_dir.exists():
            try:
                shutil.rmtree(extract_target_dir)
                logger.info(f"【ZIP解压】已清空旧的解压目录：{extract_target_dir}")
            except Exception as e:
                logger.warning(f"【ZIP解压】清空旧的解压目录失败，但是不影响文件解压：{str(e)}")

        # 路径.mkdir( ) 新建文件夹
        extract_target_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_save_path, "r") as zip_file_obj:
            zip_file_obj.extractall(extract_target_dir)
        logger.info(f"【ZIP解压】ZIP解压完成，解压目录：{extract_target_dir}")

        # 重命名full.md文件
        md_file = extract_target_dir / "full.md"
        renamed_md_filepath = md_file.with_name(f"{pdf_stem}.md") #返回一个新的 Path 对象，即重命名的目标
        md_file.rename(renamed_md_filepath)
        logger.info(f"【MD重命名】重命名成功，文件名：{pdf_stem}.md")


        return str(renamed_md_filepath.absolute())
















if __name__ == "__main__":

    import os
    # 获取项目所在路径
    from app.utils.path_util import PROJECT_ROOT


    # 组装文件路径
    local_file= os.path.join("doc", "ADS技术的发展与应用.pdf")
    # 组装文件的绝对路径
    pdf_path = os.path.join(PROJECT_ROOT, local_file)
    # 组装输出路径
    local_dir = os.path.join(PROJECT_ROOT, "output")

    # 当前节点图状态初始值
    init_state = create_custom_state(
        task_id="task_001",
        pdf_path=pdf_path,
        local_dir=local_dir
    )

    # 执行节点的业务调用
    node_pdf_to_md = NodePdfToMd()
    final_state = node_pdf_to_md(init_state)








