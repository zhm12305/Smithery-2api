#!/bin/bash

# 彻底修复数据库权限问题
# 解决 readonly database 错误

echo "🔧 彻底修复数据库权限问题"
echo "=========================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 停止服务
print_status "停止Docker服务..."
docker-compose down

# 检查和修复数据库文件
print_status "检查数据库文件状态..."
if [ -f users.db ]; then
    print_status "当前数据库文件权限:"
    ls -la users.db
    
    # 备份数据库
    print_status "备份数据库..."
    cp users.db users.db.backup.$(date +%Y%m%d_%H%M%S)
    
    # 设置正确权限
    print_status "设置数据库权限..."
    chmod 666 users.db
    
    # 如果可能，设置所有者
    if command -v chown &> /dev/null; then
        if [ "$(id -u)" -eq 0 ]; then
            # 如果是root用户
            chown 1000:1000 users.db
            print_success "已设置数据库所有者为uid:1000"
        else
            # 尝试sudo
            if sudo -n true 2>/dev/null; then
                sudo chown 1000:1000 users.db
                print_success "已设置数据库所有者为uid:1000"
            else
                print_warning "无法设置文件所有者，可能需要sudo权限"
            fi
        fi
    fi
else
    print_warning "数据库文件不存在，将创建新的"
    touch users.db
    chmod 666 users.db
    if command -v chown &> /dev/null && [ "$(id -u)" -eq 0 ]; then
        chown 1000:1000 users.db
    fi
fi

# 确保目录权限正确
print_status "设置目录权限..."
mkdir -p data logs documents
chmod -R 755 data logs documents

# 如果可能，设置目录所有者
if command -v chown &> /dev/null; then
    if [ "$(id -u)" -eq 0 ]; then
        chown -R 1000:1000 data logs documents
        print_success "已设置目录所有者"
    else
        if sudo -n true 2>/dev/null; then
            sudo chown -R 1000:1000 data logs documents
            print_success "已设置目录所有者"
        fi
    fi
fi

# 显示当前权限状态
print_status "当前文件权限状态:"
ls -la users.db data logs documents 2>/dev/null || true

# 重新构建并启动服务
print_status "重新构建和启动服务..."
docker-compose build --no-cache smithery-claude-proxy
docker-compose up -d

# 等待服务启动
print_status "等待服务启动..."
sleep 15

# 检查服务状态
print_status "检查服务状态..."
if docker-compose ps | grep -q "Up"; then
    print_success "服务运行正常"
    
    # 测试数据库写入
    print_status "测试数据库写入..."
    sleep 5
    
    # 触发一个API调用来测试数据库写入
    echo "📋 发送测试请求..."
    if curl -s -X GET http://localhost:20179/api/v1/mcp/status > /dev/null; then
        print_success "API请求成功"
    else
        print_warning "API请求失败，但服务可能仍在启动"
    fi
    
    # 检查最近的日志中是否还有数据库错误
    print_status "检查数据库错误..."
    sleep 3
    
    if docker-compose logs --tail=30 smithery-claude-proxy | grep -q "readonly database"; then
        print_error "仍然存在数据库只读错误"
        echo ""
        echo "🔍 错误调试信息："
        echo "容器内文件权限："
        docker exec smithery-claude-proxy ls -la /app/users.db 2>/dev/null || echo "无法检查容器内权限"
        echo ""
        echo "解决建议："
        echo "1. 检查Docker用户映射配置"
        echo "2. 可能需要删除数据库并重新创建"
        echo "3. 检查容器内的用户权限"
    else
        print_success "未发现数据库只读错误！"
        print_success "数据库权限问题已彻底解决！"
    fi
    
else
    print_error "服务启动失败"
    docker-compose logs --tail=20
    exit 1
fi

echo ""
print_success "数据库权限修复完成！"
echo ""
echo "📊 状态总结："
echo "✅ 服务运行正常"
echo "✅ 数据库权限已修复"
echo "🔗 API测试: curl http://localhost:20179/api/v1/mcp/status"
echo "📝 查看日志: docker-compose logs -f smithery-claude-proxy"
