#!/usr/bin/env python3
"""
启动Smithery api代理服务器

配置为与您的API配置截图匹配：
- 端口: 20179
- 模型: claude-4.5, gpt-5, gemini-2.5, grok-4等11个模型
- OpenAI兼容API
"""

import uvicorn
import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

# 设置环境变量
os.environ["PYTHONPATH"] = str(src_path)

def main():
    """启动服务器"""
    print("🚀 启动Smithery api代理服务器")
    print("=" * 50)
    print("📋 服务配置:")
    print("  • 端口: 20179")
    print("  • 模型: claude-4.5, gpt-5, gemini-2.5, grok-4等11个模型") 
    print("  • API规范: OpenAI兼容")
    print("  • 基础URL: http://localhost:20179/api/v1")
    print()
    print("⚠️  使用前请确保:")
    print("  1. 已获取有效的Smithery.ai认证token")
    print("  2. 在API调用中使用该token作为API密钥")
    print()
    print("🔗 API端点:")
    print("  • 聊天: POST /v1/chat/completions")
    print("  • 模型: GET /v1/models")
    print("  • 健康: GET /v1/health")
    print()
    
    try:
        # 启动服务器
        uvicorn.run(
            "smithery_proxy.main:app",
            host="0.0.0.0",
            port=20179,
            reload=True,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 服务器已停止")
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
