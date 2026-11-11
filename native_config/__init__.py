"""独立的三平台原生 Agent 配置核心；导入不发现文件、不启动宿主。"""

from .service import ModelService

__all__ = ["ModelService"]
