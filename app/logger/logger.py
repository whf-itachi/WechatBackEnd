import os
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

# 创建日志目录
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# 日志文件路径
LOG_FILE = os.path.join(LOG_DIR, 'app.log')
ERROR_LOG_FILE = os.path.join(LOG_DIR, 'error.log')

class ErrorFilter(logging.Filter):
    """错误日志过滤器"""
    def filter(self, record):
        return record.levelno >= logging.ERROR

class InfoFilter(logging.Filter):
    """信息日志过滤器"""
    def filter(self, record):
        return record.levelno < logging.ERROR

def setup_logger():
    """配置日志系统"""
    # 创建根日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # 清除所有已存在的处理器
    logger.handlers = []
    
    # 创建格式化器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 普通日志文件处理器（按大小轮转）
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(InfoFilter())  # 只记录非错误日志
    logger.addHandler(file_handler)

    # 错误日志处理器（按大小轮转）
    error_handler = RotatingFileHandler(
        ERROR_LOG_FILE,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=30,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    error_handler.addFilter(ErrorFilter())  # 只记录错误日志
    logger.addHandler(error_handler)

    # 测试日志是否正常工作
    logger.debug("日志系统初始化完成")   
    
    return logger

def get_logger(name: str) -> logging.Logger:
    """获取指定名称的日志记录器"""
    logger = logging.getLogger(name)
    # 确保子日志记录器也使用相同的配置
    if not logger.handlers:
        logger.setLevel(logging.INFO)  # 子日志记录器默认级别设为 INFO
        logger.propagate = True
    return logger 