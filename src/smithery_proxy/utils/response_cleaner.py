"""
响应清理工具 - 专门解决RikkaHub的null值兼容性问题
"""

import logging
from typing import Any, Dict, List, Union

logger = logging.getLogger(__name__)


def clean_null_values(data: Any, remove_null_fields: bool = True) -> Any:
    """
    清理响应中的null值，确保RikkaHub兼容性
    
    Args:
        data: 要清理的数据
        remove_null_fields: 是否移除null字段（True）还是替换为默认值（False）
        
    Returns:
        清理后的数据
    """
    
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if value is None:
                if remove_null_fields:
                    # 跳过null字段（移除）
                    logger.debug(f"移除null字段: {key}")
                    continue
                else:
                    # 替换为默认值
                    cleaned[key] = get_default_value_for_field(key)
                    logger.debug(f"替换null字段 {key} 为默认值")
            else:
                # 递归清理嵌套结构
                cleaned[key] = clean_null_values(value, remove_null_fields)
        return cleaned
        
    elif isinstance(data, list):
        return [clean_null_values(item, remove_null_fields) for item in data]
        
    else:
        return data


def clean_null_values_selective(data: Any, preserve_tool_calls: bool = False) -> Any:
    """
    选择性清理响应中的null值，可以保留特定字段的null值

    Args:
        data: 要清理的数据
        preserve_tool_calls: 是否保留tool_calls的null值

    Returns:
        清理后的数据
    """

    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if value is None:
                # 如果是tool_calls字段且需要保留，则保留null值
                if key == 'tool_calls' and preserve_tool_calls:
                    cleaned[key] = None
                    logger.debug(f"保留tool_calls的null值")
                else:
                    # 其他null字段移除
                    logger.debug(f"移除null字段: {key}")
                    continue
            else:
                # 递归清理嵌套结构
                cleaned[key] = clean_null_values_selective(value, preserve_tool_calls)
        return cleaned

    elif isinstance(data, list):
        return [clean_null_values_selective(item, preserve_tool_calls) for item in data]

    else:
        return data


def get_default_value_for_field(field_name: str) -> Any:
    """
    为特定字段提供默认值
    
    Args:
        field_name: 字段名
        
    Returns:
        该字段的默认值
    """
    
    # 字符串字段默认为空字符串
    string_fields = ['name', 'content', 'role', 'finish_reason']
    if field_name in string_fields:
        return ""
    
    # 数值字段默认为0
    numeric_fields = ['index', 'prompt_tokens', 'completion_tokens', 'total_tokens']
    if field_name in numeric_fields:
        return 0
    
    # 其他字段默认为空字符串
    return ""


def clean_openai_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    专门清理OpenAI格式响应，确保RikkaHub兼容性

    Args:
        response: OpenAI格式的响应

    Returns:
        清理后的响应
    """

    logger.info("开始清理OpenAI响应中的null值")

    # 深度复制以避免修改原始数据
    import copy
    cleaned_response = copy.deepcopy(response)

    # 🎯 强制兼容性修复：检查是否需要简化响应格式
    # 这是最后的修复机会，在所有其他逻辑之后执行
    # 注意：这里无法区分原始请求是否包含tools参数，所以采用启发式方法
    if 'choices' in cleaned_response and cleaned_response['choices']:
        for choice in cleaned_response['choices']:
            if 'message' in choice and choice['message']:
                message = choice['message']
                # 精确判断：使用特殊标记来识别简化模式
                content = message.get('content', '')
                has_simplified_marker = '<!-- SIMPLIFIED_MODE -->' in content

                if has_simplified_marker and choice.get('finish_reason') == 'tool_calls':
                    # 清理标记
                    message['content'] = content.replace('<!-- SIMPLIFIED_MODE -->', '').strip()
                    logger.info("🎯 强制兼容性修复：检测到自动搜索工具调用，修改为简化格式")
                    # 强制设置为简化格式
                    choice['finish_reason'] = 'stop'
                    if 'tool_calls' in message:
                        del message['tool_calls']
                    logger.info("🎯 强制修复完成：finish_reason=stop, tool_calls已删除")

    # 检查是否是简化模式（不带tool_calls的响应）
    is_simplified_mode = False
    if 'choices' in cleaned_response and cleaned_response['choices']:
        for choice in cleaned_response['choices']:
            if 'finish_reason' in choice and choice['finish_reason'] == 'stop':
                if 'message' in choice and choice['message']:
                    message = choice['message']
                    if 'tool_calls' in message and message['tool_calls'] is None:
                        is_simplified_mode = True
                        break
    
    # 特殊处理choices字段
    if 'choices' in cleaned_response and cleaned_response['choices']:
        for i, choice in enumerate(cleaned_response['choices']):
            if 'message' in choice and choice['message']:
                message = choice['message']
                
                # 处理name字段 - 这是导致RikkaHub问题的主要原因
                if 'name' in message and message['name'] is None:
                    del message['name']  # 完全移除null的name字段
                    logger.debug(f"移除choices[{i}].message.name的null值")
                
                # 确保content不为null
                if 'content' in message and message['content'] is None:
                    message['content'] = ""
                    logger.warning(f"choices[{i}].message.content为null，替换为空字符串")
                
                # 确保role不为null
                if 'role' in message and message['role'] is None:
                    message['role'] = "assistant"
                    logger.warning(f"choices[{i}].message.role为null，替换为assistant")
            
            # 确保finish_reason不为null
            if 'finish_reason' in choice and choice['finish_reason'] is None:
                choice['finish_reason'] = "stop"
                logger.debug(f"choices[{i}].finish_reason为null，替换为stop")
    
    # 处理usage字段
    if 'usage' in cleaned_response and cleaned_response['usage']:
        usage = cleaned_response['usage']
        for field in ['prompt_tokens', 'completion_tokens', 'total_tokens']:
            if field in usage and usage[field] is None:
                usage[field] = 0
                logger.debug(f"usage.{field}为null，替换为0")
    
    # 通用null值清理
    if is_simplified_mode:
        # 简化模式：保留tool_calls为None，只清理其他null值
        logger.info("简化模式：保留tool_calls=None，清理其他null值")
        cleaned_response = clean_null_values_selective(cleaned_response, preserve_tool_calls=True)
    else:
        # 标准模式：清理所有null值
        cleaned_response = clean_null_values(cleaned_response, remove_null_fields=True)

    logger.info("OpenAI响应null值清理完成")
    return cleaned_response


def validate_rikkahub_compatibility(response: Dict[str, Any]) -> tuple[bool, List[str]]:
    """
    验证响应是否符合RikkaHub兼容性要求
    
    Args:
        response: 要验证的响应
        
    Returns:
        (是否兼容, 问题列表)
    """
    
    issues = []
    
    # 检查null值
    def find_nulls(obj, path=""):
        null_paths = []
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{path}.{key}" if path else key
                if value is None:
                    null_paths.append(current_path)
                elif isinstance(value, (dict, list)):
                    null_paths.extend(find_nulls(value, current_path))
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                current_path = f"{path}[{i}]"
                if value is None:
                    null_paths.append(current_path)
                elif isinstance(value, (dict, list)):
                    null_paths.extend(find_nulls(value, current_path))
        return null_paths
    
    null_paths = find_nulls(response)
    if null_paths:
        issues.extend([f"发现null值: {path}" for path in null_paths])
    
    # 检查必需字段
    required_fields = ['id', 'object', 'created', 'model', 'choices']
    for field in required_fields:
        if field not in response:
            issues.append(f"缺少必需字段: {field}")
        elif response[field] is None:
            issues.append(f"必需字段为null: {field}")
    
    # 检查choices结构
    if 'choices' in response and response['choices']:
        for i, choice in enumerate(response['choices']):
            if 'message' not in choice:
                issues.append(f"choices[{i}]缺少message字段")
            elif choice['message'] is None:
                issues.append(f"choices[{i}].message为null")
            else:
                message = choice['message']
                if 'content' not in message:
                    issues.append(f"choices[{i}].message缺少content字段")
                elif message['content'] is None:
                    issues.append(f"choices[{i}].message.content为null")
    
    is_compatible = len(issues) == 0
    return is_compatible, issues


def log_response_cleaning_stats(original: Dict[str, Any], cleaned: Dict[str, Any]) -> None:
    """
    记录响应清理的统计信息
    
    Args:
        original: 原始响应
        cleaned: 清理后的响应
    """
    
    def count_nulls(obj):
        count = 0
        if isinstance(obj, dict):
            for value in obj.values():
                if value is None:
                    count += 1
                elif isinstance(value, (dict, list)):
                    count += count_nulls(value)
        elif isinstance(obj, list):
            for item in obj:
                if item is None:
                    count += 1
                elif isinstance(item, (dict, list)):
                    count += count_nulls(item)
        return count
    
    original_nulls = count_nulls(original)
    cleaned_nulls = count_nulls(cleaned)
    
    logger.info(f"响应清理统计: 原始null值={original_nulls}, 清理后null值={cleaned_nulls}, 移除={original_nulls - cleaned_nulls}")
