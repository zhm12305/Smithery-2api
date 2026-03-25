"""
MCP 管理 API 端点

提供 MCP 服务器和工具的管理接口。
"""

import logging
from typing import List, Optional, Dict, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse

from ...config import Settings, get_settings
from ...services.mcp_playground_client import MCPPlaygroundClient, MCPPlaygroundClientError
from ...services.tool_manager import get_tool_manager
from ...models.mcp_playground_models import (
    MCPServerSearchRequest,
    MCPServerSearchResponse,
    MCPServerInfo,
    MCPToolDefinition,
    MCPToolCall,
    MCPToolCallResult,
    MCPPagination
)
from ...models.tool_models import ToolConfig
from ..v1.chat import validate_request_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])


async def get_mcp_client(settings: Settings = Depends(get_settings)) -> MCPPlaygroundClient:
    """获取 MCP 客户端依赖"""
    if not settings.enable_mcp_tools:
        raise HTTPException(
            status_code=503,
            detail="MCP 工具功能未启用"
        )
    
    if not settings.smithery_auth_token:
        raise HTTPException(
            status_code=503,
            detail="Smithery 认证 token 未配置"
        )
    
    mcp_client = MCPPlaygroundClient(settings)
    await mcp_client.initialize()
    return mcp_client


@router.get("/servers", response_model=MCPServerSearchResponse)
async def list_mcp_servers(
    query: Optional[str] = Query(None, description="搜索查询"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=50, description="每页大小"),
    deployed_only: bool = Query(True, description="仅显示已部署的服务器"),
    remote_only: bool = Query(True, description="仅显示远程服务器"),
    _auth_token: str = Depends(validate_request_auth),
    mcp_client: MCPPlaygroundClient = Depends(get_mcp_client)
):
    """
    列出 MCP 服务器
    
    支持搜索和分页，可以筛选已部署和远程服务器。
    """
    try:
        # 构建搜索过滤器
        filters = {
            "page": page,
            "pageSize": page_size
        }
        
        if deployed_only:
            filters["is:deployed"] = True
        
        if remote_only:
            filters["is:remote"] = True
        
        # 构建搜索查询
        search_query = query or "tool"
        if deployed_only and remote_only:
            search_query += " is:deployed is:remote"
        elif deployed_only:
            search_query += " is:deployed"
        elif remote_only:
            search_query += " is:remote"
        
        # 执行搜索
        result = await mcp_client.search_mcp_servers(
            query=search_query,
            filters=filters,
            pagination=MCPPagination(page=page, page_size=page_size)
        )
        
        logger.info(f"搜索到 {len(result.servers)} 个 MCP 服务器")
        return result
        
    except MCPPlaygroundClientError as e:
        logger.error(f"MCP 服务器搜索失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"搜索失败: {str(e)}"
        )
    except Exception as e:
        logger.error(f"MCP 服务器列表获取失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取服务器列表失败: {str(e)}"
        )


@router.get("/servers/{server_id}", response_model=MCPServerInfo)
async def get_mcp_server(
    server_id: str,
    _auth_token: str = Depends(validate_request_auth),
    mcp_client: MCPPlaygroundClient = Depends(get_mcp_client)
):
    """获取指定 MCP 服务器的详细信息"""
    try:
        server_info = await mcp_client.get_server_info(server_id)
        
        if not server_info:
            raise HTTPException(
                status_code=404,
                detail=f"服务器 {server_id} 未找到"
            )
        
        return server_info
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取服务器信息失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取服务器信息失败: {str(e)}"
        )


@router.get("/servers/{server_id}/tools", response_model=List[MCPToolDefinition])
async def get_server_tools(
    server_id: str,
    _auth_token: str = Depends(validate_request_auth),
    mcp_client: MCPPlaygroundClient = Depends(get_mcp_client)
):
    """获取指定服务器的工具列表"""
    try:
        tools = await mcp_client.get_server_tools(server_id)
        
        logger.info(f"服务器 {server_id} 有 {len(tools)} 个工具")
        return tools
        
    except Exception as e:
        logger.error(f"获取服务器工具失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取服务器工具失败: {str(e)}"
        )


@router.post("/tools/test", response_model=MCPToolCallResult)
async def test_tool_call(
    tool_call: MCPToolCall,
    _auth_token: str = Depends(validate_request_auth),
    mcp_client: MCPPlaygroundClient = Depends(get_mcp_client)
):
    """测试 MCP 工具调用"""
    try:
        # 设置调用ID
        if not tool_call.call_id:
            tool_call.call_id = str(uuid4())
        
        # 执行工具调用
        result = await mcp_client.call_mcp_tool(
            server_id=tool_call.server_id,
            tool_name=tool_call.tool_name,
            parameters=tool_call.parameters
        )
        
        logger.info(f"工具调用测试完成: {tool_call.tool_name}, 成功: {result.success}")
        return result
        
    except Exception as e:
        logger.error(f"工具调用测试失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"工具调用测试失败: {str(e)}"
        )


@router.get("/tools", response_model=List[MCPToolDefinition])
async def list_all_tools(
    query: Optional[str] = Query(None, description="搜索查询"),
    _auth_token: str = Depends(validate_request_auth),
    settings: Settings = Depends(get_settings)
):
    """列出所有可用的 MCP 工具"""
    try:
        # 创建工具管理器
        tool_config = ToolConfig(
            google_search_api_key=settings.google_search_api_key,
            google_search_cx=settings.google_search_cx,
            code_execution_enabled=settings.code_execution_enabled,
            code_execution_timeout=settings.code_execution_timeout,
            web_fetch_timeout=settings.web_fetch_timeout,
            max_search_results=settings.max_search_results,
            gemini_api_key=getattr(settings, "gemini_api_key", None),
            gemini_base_url=getattr(settings, "gemini_base_url", None)
        )
        
        # 初始化 MCP 客户端
        mcp_client = None
        if settings.enable_mcp_tools and settings.smithery_auth_token:
            mcp_client = MCPPlaygroundClient(settings)
            await mcp_client.initialize()
        
        tool_manager = get_tool_manager(tool_config, mcp_client)
        
        # 获取 MCP 工具
        mcp_tools = await tool_manager.discover_mcp_tools(query)
        
        logger.info(f"发现 {len(mcp_tools)} 个 MCP 工具")
        return mcp_tools
        
    except Exception as e:
        logger.error(f"获取工具列表失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取工具列表失败: {str(e)}"
        )


@router.post("/tools/refresh")
async def refresh_tools_cache(
    _auth_token: str = Depends(validate_request_auth),
    settings: Settings = Depends(get_settings)
):
    """刷新工具缓存"""
    try:
        # 创建工具管理器
        tool_config = ToolConfig(
            google_search_api_key=settings.google_search_api_key,
            google_search_cx=settings.google_search_cx,
            code_execution_enabled=settings.code_execution_enabled,
            code_execution_timeout=settings.code_execution_timeout,
            web_fetch_timeout=settings.web_fetch_timeout,
            max_search_results=settings.max_search_results,
            gemini_api_key=getattr(settings, "gemini_api_key", None),
            gemini_base_url=getattr(settings, "gemini_base_url", None)
        )
        
        # 初始化 MCP 客户端
        mcp_client = None
        if settings.enable_mcp_tools and settings.smithery_auth_token:
            mcp_client = MCPPlaygroundClient(settings)
            await mcp_client.initialize()
        
        tool_manager = get_tool_manager(tool_config, mcp_client)
        
        # 刷新缓存
        await tool_manager.refresh_mcp_tools()
        
        return JSONResponse(
            content={"message": "工具缓存已刷新"},
            status_code=200
        )
        
    except Exception as e:
        logger.error(f"刷新工具缓存失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"刷新工具缓存失败: {str(e)}"
        )


@router.get("/status")
async def get_mcp_status(
    settings: Settings = Depends(get_settings)
):
    """获取 MCP 功能状态"""
    try:
        status = {
            "mcp_enabled": settings.enable_mcp_tools,
            "smithery_token_configured": bool(settings.smithery_auth_token),
            "cache_ttl": settings.mcp_cache_ttl,
            "max_concurrent_calls": settings.mcp_max_concurrent_calls,
            "tool_timeout": settings.mcp_tool_timeout,
            "search_page_size": settings.mcp_search_page_size
        }
        
        # 测试 MCP 客户端连接
        if settings.enable_mcp_tools and settings.smithery_auth_token:
            try:
                mcp_client = MCPPlaygroundClient(settings)
                await mcp_client.initialize()
                
                # 尝试搜索一个服务器来测试连接
                test_result = await mcp_client.search_mcp_servers(
                    query="test",
                    filters={"page": 1, "pageSize": 1}
                )
                
                status["connection_status"] = "connected"
                status["test_search_count"] = len(test_result.servers)
                
                await mcp_client.close()
                
            except Exception as e:
                status["connection_status"] = "failed"
                status["connection_error"] = str(e)
        else:
            status["connection_status"] = "not_configured"
        
        return JSONResponse(content=status)
        
    except Exception as e:
        logger.error(f"获取 MCP 状态失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取状态失败: {str(e)}"
        )
