# InvestPilot - AI-Powered Investment Copilot

一款支持多模型的智能股票量化分析平台，支持 K 线趋势分析、智能选股推荐和持仓诊断。

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.9+-green.svg)

**⚠️ 免责声明**

本项目仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。

## ✨ 功能特点

### 📈 K线趋势分析
- **AI 驱动分析**：支持 Gemini、GPT、Claude 等多个主流模型，深度解析历史价格数据
- **买卖点标注**：在 K 线图上直观标记 AI 推荐的买入/卖出时机
- **交易回测**：展示历史交易明细，包含胜率、收益率等统计数据

### 🎯 智能选股推荐
- **实时市场扫描**：支持联网搜索获取最新市场资讯（Gemini/Grok/Qwen）
- **多维筛选**：支持按资金规模、风险偏好、交易频率进行筛选
- **专业评级**：为每只推荐股票提供信心等级（⭐⭐⭐、⭐⭐、⭐）

### 💊 持仓诊断
- **专业建议**：根据买入均价和仓位占比给出专业操作建议
- **实时定价**：自动获取最新市场价格进行对比分析
- **五档评级**：提供从"强烈买入"到"强烈卖出"的精细化评级

#### Local Strategy
- `local-strategy` - 本地量化策略（MA+RSI）

## 📦 安装部署

### 方式一：本地安装（推荐开发）

#### 1. 克隆项目
```bash
git clone git@github.com:chang1sun/InvestPilot.git
cd InvestPilot
```

#### 2. 创建虚拟环境
```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

#### 3. 安装依赖
```bash
pip install -r requirements.txt
```

#### 4. 配置环境变量
创建 `.env` 文件（参考 `env.example`）：
```env
# AI Model API Keys (根据需要配置，至少配置一个)
GEMINI_API_KEY=your_gemini_api_key_here      # Google Gemini 系列
OPENAI_API_KEY=your_openai_api_key_here       # OpenAI GPT-5 系列
ANTHROPIC_API_KEY=your_anthropic_api_key_here # Anthropic Claude 4.5 系列
QWEN_API_KEY=your_qwen_api_key_here           # 阿里通义千问系列（国内推荐）

# 数据库配置 (可选，默认使用 SQLite)
DATABASE_URL=sqlite:///investpilot.db

# Redis 配置 (可选，默认使用内存缓存)
REDIS_URL=redis://localhost:6379/0
```

> **💡 提示**：
> - **Gemini**：访问 [Google AI Studio](https://aistudio.google.com/app/apikey) 免费获取（推荐：1M-2M 上下文）
> - **OpenAI**：访问 [OpenAI Platform](https://platform.openai.com/api-keys)（GPT-5 系列）
> - **Claude**：访问 [Anthropic Console](https://console.anthropic.com/settings/keys)（Claude 4.5 系列，200K 上下文）
> - **Qwen**：访问 [阿里云 DashScope](https://dashscope.console.aliyun.com/)（国内速度快，最高 256K 上下文）

#### 5. 启动 Redis（可选）
如果本地有 Docker：
```bash
docker run -d -p 6379:6379 --name quant_redis redis:alpine
```

或使用 Docker Compose：
```bash
docker-compose up -d redis
```

#### 6. 初始化数据库
```bash
python tools/init_db.py
```

这将创建所有必需的数据库表，包括：
- `analysis_logs` - 分析结果缓存
- `stock_trade_signals` - 交易信号历史
- `recommendation_cache` - 选股推荐缓存（NEW）

#### 7. 启动应用

**方式 A：使用快速启动脚本（推荐）**

Linux/Mac:
```bash
./start.sh
```

Windows:
```bash
start.bat
```

**方式 B：手动启动**
```bash
python app.py
```

应用将运行在 `http://localhost:5000`

---

### 方式二：Docker 部署（推荐生产）

#### 1. 快速启动（仅 Flask + Redis）
```bash
# 修改 docker-compose.yml 中的 GEMINI_API_KEY
docker-compose up -d
```

访问 `http://localhost:5000`

#### 2. 完整部署（Flask + MySQL + Redis）
取消 `docker-compose.yml` 中 MySQL 服务的注释，并修改数据库连接配置：
```yaml
services:
  web:
    environment:
      - DATABASE_URL=mysql+pymysql://user:password@db/investpilot_db
      - REDIS_URL=redis://redis:6379/0
      - GEMINI_API_KEY=${GEMINI_API_KEY}
```

然后启动：
```bash
docker-compose up -d
```

#### 3. 查看日志
```bash
docker-compose logs -f web
```

#### 4. 停止服务
```bash
docker-compose down
```

---