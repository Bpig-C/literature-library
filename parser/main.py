import logging
import sys
from pathlib import Path

# 确保 python/ 目录在 sys.path 中（方便直接 python main.py 运行）
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def setup_logging() -> None:
    log_dir = _HERE/ "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "server.log"

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def main() -> None:
    setup_logging()

    from config import config
    from server.app import create_app
    import uvicorn

    app = create_app()

    uvicorn.run(
        app,
        host=config.server_ip,
        port=config.server_port,
        log_config=None,   # 使用上面配置的 logging
    )

import os


def Datas_directory(folder_path):
    """
    清空指定文件夹及其子文件夹的所有内容，但保留文件夹本身
    :param folder_path: 要清空的文件夹路径
    """

    # 如果目录不存在，则创建它
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        return



if __name__ == "__main__":
    Datas_directory("./Datas")
    main()
