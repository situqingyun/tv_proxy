"""
TradingView API工具函数
用于处理TradingView请求的通用函数
"""
import logging
import json
from flask import request, jsonify

logger = logging.getLogger(__name__)

def parse_request_data():
    """
    通用函数，用于解析TradingView发送的请求数据
    无论Content-Type是什么，都尝试解析JSON数据
    """
    try:
        json.dumps
        # 记录请求信息，用于调试
        logger.info(f"接收到请求，Content-Type: {request.content_type}")
        logger.info(f"请求参数: {request.args}")
        
        if request.is_json:
            # 标准JSON格式
            data = request.json
            logger.info("成功从json中解析数据")
            return data
        
        # 处理multipart/form-data类型 (TradingView使用这种方式传输图表数据)
        if request.content_type and request.content_type.startswith('multipart/form-data'):
            # TradingView通常将JSON数据放在名为'content'的字段中
            if 'content' in request.form:
                data = request.form
                logger.info("成功从multipart/form-data的content字段解析数据")
                return data
            
            # 如果没有content字段，尝试解析第一个字段
            if request.form:
                form_keys = list(request.form.keys())
                if form_keys:
                    try:
                        # 尝试将第一个表单字段解析为JSON
                        data = json.loads(form_keys[0])
                        logger.info("成功从第一个表单字段解析数据")
                        return data
                    except json.JSONDecodeError:
                        # 如果第一个字段不是JSON，尝试字段的值
                        try:
                            data = json.loads(request.form[form_keys[0]])
                            logger.info("成功从第一个表单字段的值解析数据")
                            return data
                        except:
                            pass
        
        # 尝试从原始请求体解析JSON
        if request.data:
            try:
                data = json.loads(request.data.decode('utf-8'))
                logger.info("成功从请求体解析数据")
                return data
            except:
                pass
        
        # 尝试从查询参数构造数据
        if request.args:
            # 如果所有其他方法都失败，尝试从URL参数构建一个基本对象
            data = dict(request.args)
            logger.info("从URL参数构造的数据")
            return data
            
        # 记录所有可能的数据源，用于调试
        logger.warning("无法找到有效的数据源")
        logger.warning(f"Form数据: {request.form}")
        logger.warning(f"Files: {request.files}")
        logger.warning(f"Values: {request.values}")
        
        return None
    except Exception as e:
        logger.error(f"解析请求数据时发生错误: {str(e)}")
        logger.error(f"请求的Content-Type: {request.content_type}")
        logger.error(f"请求headers: {dict(request.headers)}")
        return None
