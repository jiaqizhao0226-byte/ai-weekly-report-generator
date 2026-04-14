#!/bin/bash
# AI 周报生成器 - 一键启动脚本

PROJECT_DIR="/Users/zhaojiaqi/CodeBuddy/20260305163653/ai-weekly-report-generator"
PORT=5050
URL="http://localhost:$PORT"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
DOCKER="/Applications/Docker.app/Contents/Resources/bin/docker"

# 检查端口是否已被占用（已在运行）
if lsof -i :$PORT > /dev/null 2>&1; then
    echo "✅ AI 周报生成器已经在运行中，正在打开浏览器..."
    open "$URL"
    exit 0
fi

echo "🚀 正在启动 AI 周报生成器..."

# 1. 启动 Docker Desktop（如果没在运行）
if ! $DOCKER info > /dev/null 2>&1; then
    echo "🐳 启动 Docker Desktop..."
    open /Applications/Docker.app
    for i in $(seq 1 30); do
        if $DOCKER info > /dev/null 2>&1; then
            echo "  Docker 已就绪"
            break
        fi
        sleep 2
    done
fi

# 2. 启动 WeWe RSS（如果没在运行）
if ! curl -s http://localhost:4000 > /dev/null 2>&1; then
    echo "📡 启动 WeWe RSS..."
    cd /Users/zhaojiaqi/wewe-rss
    export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
    docker compose up -d > /dev/null 2>&1
    sleep 5
    if curl -s http://localhost:4000 > /dev/null 2>&1; then
        echo "  WeWe RSS 已就绪"
    else
        echo "  ⚠️ WeWe RSS 启动失败，部分功能可能不可用"
    fi
fi

# 3. 启动 Flask 应用
cd "$PROJECT_DIR"
$PYTHON app.py > /dev/null 2>&1 &
APP_PID=$!

# 等待服务启动
echo "⏳ 等待服务启动..."
for i in $(seq 1 15); do
    if curl -s "$URL" > /dev/null 2>&1; then
        echo "✅ 启动成功！正在打开浏览器..."
        open "$URL"
        echo ""
        echo "📌 访问地址: $URL"
        echo "📌 关闭方法: 关闭此终端窗口，或运行 kill $APP_PID"
        echo ""
        echo "按任意键关闭服务并退出..."
        read -n 1
        kill $APP_PID 2>/dev/null
        exit 0
    fi
    sleep 1
done

echo "❌ 启动超时，请检查项目配置"
kill $APP_PID 2>/dev/null
exit 1
