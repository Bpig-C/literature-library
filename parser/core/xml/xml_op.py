from core.xml.html_convert_json import convert_html_to_json_list
import logging
import threading
from config import config
logger = logging.getLogger(__name__)
from pathlib import Path
import json


class XML_OP:
    """负责处理 xml 类型的任务"""
    def __init__(self):
        pass

    def push_task(self, file_path:str,file_type:str,task_id:str,callFun:callable) -> None:
        # 处理 html 类型文件
        if file_type in ["html","htm","mhtml"]:
            # 启用线程处理 ，线程执行convert_html_to_json_list，   完后调用 callFun
            def thread_worker():
                try:
                    source_path = Path(file_path)
                    result = convert_html_to_json_list(source_path)
                    with open(source_path.with_suffix(".json"), "w", encoding="utf-8") as f:
                        f.write(json.dumps(result, ensure_ascii=False, indent=4))
                    callFun(True, str(source_path.with_suffix(".json")), task_id)
                except Exception as e:
                    logger.error(f"Error processing HTML file {file_path}: {e}")
                    callFun(False, file_path, task_id)
            
            # 创建并启动线程
            thread = threading.Thread(target=thread_worker)
            thread.daemon = True  # 设置为守护线程，避免阻塞主程序
            thread.start()
    def is_parsed(self, folder_path: Path) -> bool:
        # 遍历文件夹下所有文件，寻找是否有json文件
        for file in folder_path.iterdir():
            if file.suffix == ".json":
                return True
        return False
        
