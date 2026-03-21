from abc import ABC, abstractmethod
from time import sleep

from app.core.logger import logger
from app.import_process.agent.state import ImportGraphState
from app.utils.format_utils import format_state
from app.utils.task_utils import add_running_task, add_done_task

class NodeBase(ABC) :
    #   要求子类必须修改节点名: 创建实例时如果name等于默认名，则报错
    name: str = "default_name"

    def __init__(self):
        if self.name == "default_name":
            raise ValueError(f"子类{self.__class__.name}未定义!")

    def __call__(self, state: ImportGraphState) -> ImportGraphState:
        # 以NodeBase(xx)调用时会执行call方法

        # 节点启动日志，打印当前工作流状态
        logger.info(f"{'*' * 20}【{self.name}】节点启动{'*' * 20}")
        logger.debug(f"【{self.name}】节点当前工作流状态：{format_state(state)}")

        # 开始：记录节点运行状态
        # 此处为任务追踪，后面会讲
        add_running_task(state["task_id"], self.name)

        try:

            self.process(state)
            # 结束：记录节点运行状态
            # 此处为任务追踪，后面会讲
            add_done_task(state["task_id"], self.name)

            # 节点完成日志，打印当前工作流状态
            logger.debug(f"【{self.name}】节点更新后工作流状态：{format_state(state)}")
            logger.info(f"{'*' * 20}【{self.name}】节点执行完成{'*' * 20}\n")
            return state

        except Exception as e:
            exception_message = f"【{self.name}】执行失败，信息：{str(e)}"
            # logger.error(exception_message, exc_info = True )
            logger.exception(exception_message, e)
            raise

    @abstractmethod #表示抽象方法，必须被重写，否则报错
    def process(self, state: ImportGraphState) -> ImportGraphState:
        #业务逻辑
        pass