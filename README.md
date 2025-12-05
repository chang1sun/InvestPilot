# InvestPilot - AI-Powered Investment Copilot

一款支持多模型的智能股票量化分析平台，支持 K 线趋势分析、智能选股推荐和持仓诊断。

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.9+-green.svg)

**⚠️ 免责声明**

本项目仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。使用本系统进行投资决策的一切后果由用户自行承担。

## 🎯 项目亮点

- 🤖 **多模型支持**：深度集成 Gemini、GPT、Claude、Grok、Qwen 多个主流 AI 模型
- 🔍 **实时搜索**：支持联网搜索实时资讯（Gemini、Grok、Qwen）
- 📊 **数据可视化**：ECharts 高质量 K 线图表，买卖点直观标注
- 🌐 **双语支持**：中英文界面切换，AI 输出内容自适应
- ⚡ **智能缓存**：多层缓存策略，节省 API 配额，提升响应速度
- 🛡️ **容错设计**：API 失败自动降级到本地算法，零宕机风险
- 🐳 **一键部署**：Docker Compose 开箱即用，生产环境就绪

## ✨ 功能特点

### 📈 K线趋势分析
- **AI 驱动分析**：支持 Gemini、GPT-4、Claude 等多个主流模型，深度解析历史价格数据
- **技术指标计算**：自动计算 MA5、MA20、RSI 等常用技术指标
- **买卖点标注**：在 K 线图上直观标记 AI 推荐的买入/卖出时机
- **交易回测**：展示历史交易明细，包含胜率、收益率等统计数据
- **本地策略回退**：当 API 不可用时自动切换到本地量化算法（MA+RSI）

### 🎯 智能选股推荐
- **实时市场扫描**：支持联网搜索获取最新市场资讯（Gemini/Grok/Qwen）
- **多维筛选**：支持按资金规模、风险偏好、交易频率进行筛选
- **专业评级**：为每只推荐股票提供信心等级（⭐⭐⭐、⭐⭐、⭐）
- **智能缓存**：24 小时缓存机制，避免重复 API 调用，节省配额

### 🤖 支持的 AI 模型

#### Google Gemini（推荐：免费额度充足）
- `gemini-3-pro-preview` - 最新预览版，2M 上下文 🔍
- `gemini-2.5-flash` - 快速免费，1M 上下文 🔍

#### OpenAI GPT-5 Series
- `gpt-5.1` - 最强大，32K 上下文
- `gpt-5-mini` - 性价比高，16K 上下文
- `gpt-5-nano` - 快速低价，8K 上下文

#### Anthropic Claude 4.5 Series
- `claude-opus-4-5` - 最强大，200K 上下文
- `claude-sonnet-4-5` - 平衡性能，200K 上下文
- `claude-haiku-4-5` - 快速低价，200K 上下文

#### Alibaba Qwen（推荐：国内用户）
- `qwen3-max` - 最强性能，256K 上下文 🔍
- `qwen-plus` - 性价比高，128K 上下文 🔍
- `qwen-flash` - 快速低价，32K 上下文

#### Local Strategy
- `local-strategy` - 免费本地算法（MA+RSI）

### 💊 持仓诊断
- **个性化建议**：根据买入均价和仓位占比给出专业操作建议
- **实时定价**：自动获取最新市场价格进行对比分析
- **五档评级**：提供从"强烈买入"到"强烈卖出"的精细化评级

### 🌐 多语言支持
- **中英文切换**：界面和 AI 输出内容支持中英文双语
- **即时翻译**：对已生成的分析结果一键翻译
- **智能适配**：根据用户选择的语言生成对应内容

## 📦 安装部署

### 方式一：本地安装（推荐开发）

#### 1. 克隆项目
```bash
git clone git@github.com:chang1sun/investpilot.git
cd investpilot
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

## 🚀 使用指南

### 1️⃣ K线趋势分析
1. 在顶部搜索框输入股票代码（如 `AAPL`、`600519.SS`、`0700.HK`）
2. 点击"开始"按钮或直接按回车键
3. 等待 AI 分析完成（通常 10-30 秒）
4. 查看可视化 K 线图、交易明细和 AI 分析摘要
5. 点击交易明细可展开查看详细策略解释

**快捷入口**：首次进入时，可直接点击"热门标的快速分析"中的股票卡片

### 2️⃣ 智能选股推荐
1. 切换到"智能选股推荐"标签页
2. 根据需要选择筛选条件（资金规模、风险偏好、交易频率）
3. 点击"AI 智能扫描"按钮
4. 查看 AI 推荐的 10 只股票及市场风向分析
5. 点击任意推荐股票的"查看K线分析"快速跳转到趋势分析

**💡 提示**：推荐结果会缓存 24 小时，相同筛选条件下不会重复调用 API。

### 3️⃣ 持仓诊断
1. 在"智能选股推荐"页面右侧找到"持仓诊断"面板
2. 输入持有的股票代码、买入均价和仓位占比
3. 点击"开始诊断"
4. 查看 AI 给出的评级和操作建议（强烈买入/买入/持有/卖出/强烈卖出）

### 4️⃣ 语言切换与翻译
- **切换界面语言**：点击右上角的"中文/EN"按钮
- **翻译已有内容**：点击分析摘要、市场风向等文本块右上角的"Translate"按钮

---

## 🗂️ 缓存策略与维护

### 缓存机制
- **K线分析缓存**：同一股票同一天只分析一次，多次请求直接返回缓存（按 `symbol + market_date + model + language` 缓存）
- **选股推荐缓存**：相同筛选条件（资金规模 + 风险偏好 + 交易频率）每天只调用一次 AI，24 小时内走缓存
- **本地策略不缓存**：使用 `Local Algo (MA+RSI)` 模型时，每次实时计算，不使用缓存

### 数据维护工具
```bash
# 清理过期的推荐缓存（默认保留最近 7 天）
python tools/clean_old_cache.py

# 保留最近 3 天的缓存
python tools/clean_old_cache.py 3

# 清空所有缓存数据
python tools/clean_cache.py

# 重新初始化数据库（不会删除现有数据）
python tools/init_db.py
```

### 缓存标识
API 响应中会包含 `_cached` 字段：
- `"_cached": true` - 数据来自缓存
- `"_cached": false` - 数据为实时生成

