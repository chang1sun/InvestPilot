#!/bin/bash

echo "🔄 重新构建并重启 Docker Compose 服务"
echo "======================================"

# 检查是否有运行中的容器
if docker-compose ps | grep -q "Up"; then
    echo "📦 停止现有容器..."
    docker-compose down
fi

echo "🔨 重新构建镜像（包含最新代码）..."
docker-compose build --no-cache

echo "🚀 启动服务..."
docker-compose up -d

echo ""
echo "✅ 服务已更新并启动！"
echo ""
echo "📊 查看日志："
echo "   docker-compose logs -f web"
echo ""
echo "🔍 查看服务状态："
echo "   docker-compose ps"
echo ""

