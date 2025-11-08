# TV Proxy

一个基于FastAPI的TradingView图表代理服务,支持OKX数据源集成。

## ✨ 特性

- 📊 **TradingView图表库代理** - 完整的图表功能支持
- 💹 **OKX数据源集成** - 实时加密货币数据
- 💾 **图表存储** - 保存和加载图表布局、模板
- 🔄 **回放功能** - 历史数据回放和交易模拟
- ⚡ **WebSocket支持** - 实时数据推送
- 🎯 **速率限制管理** - 智能API调用优化

## 📁 项目结构

```
tv_proxy/
├── src/                    # 源代码
│   ├── routes/            # API路由
│   │   ├── okx_routes.py      # OKX数据API
│   │   ├── chart_routes.py    # 图表存储API
│   │   └── replay_routes.py   # 回放功能API
│   ├── services/          # 业务逻辑层
│   │   ├── okx_service.py         # OKX服务
│   │   ├── okx_cache_manager.py   # 数据缓存
│   │   └── okx_rate_limiter.py    # 速率限制
│   ├── models/            # 数据模型
│   │   └── database.py    # 数据库初始化
│   ├── utils/             # 工具函数
│   │   └── api_utils.py   # API工具
│   └── main.py            # 主应用入口
├── tests/                 # 测试代码
│   ├── okx/              # OKX相关测试
│   ├── data/             # 数据测试
│   └── api/              # API测试
├── docs/                  # 文档
│   ├── technical/        # 技术文档
│   └── archive/          # 归档报告
├── templates/             # HTML模板
├── archive/               # 归档代码
│   └── legacy/           # 旧版本代码
├── run.py                 # 启动脚本
├── pyproject.toml         # 项目配置
└── README.md
```

## 🚀 快速开始

### 前置要求

- Python 3.10 或更高版本
- PostgreSQL 数据库
- uv 包管理器 (推荐)

### 安装

1. 克隆仓库

2. 安装依赖:
   ```bash
   uv sync
   ```

3. 配置环境变量:
   创建 `.env` 文件 (参考 `.env.example`):
   ```
   # 数据库配置
   DB_HOST=localhost
   DB_PORT=5432
   DB_NAME=tvdb
   DB_USER=tvuser
   DB_PASSWORD=your_password

   # OKX API配置 (可选)
   OKX_API_KEY=your_api_key
   OKX_SECRET_KEY=your_secret_key
   OKX_PASSPHRASE=your_passphrase
   OKX_FLAG=0

   # 回放配置
   REPLAY_BARS_COUNT=150
   REPLAY_EARLIEST_DATE=2023-01-01
   ```

### 运行

```bash
# 使用uv运行
uv run run.py

# 或直接运行
python run.py
```

应用将在 http://localhost:5000 启动

## 📚 API文档

启动应用后,访问:
- Swagger文档: http://localhost:5000/docs
- ReDoc文档: http://localhost:5000/redoc

### 主要API端点

**OKX数据API:**
- `GET /api/okx/instruments` - 获取交易对列表
- `GET /api/okx/symbol-search` - 搜索交易对
- `GET /api/okx/klines` - 获取K线数据
- `GET /api/okx/orderbook` - 获取订单簿

**图表存储API:**
- `GET/POST/DELETE /saveload.tradingview.com/1.1/charts` - 图表管理
- `GET/POST/DELETE /saveload.tradingview.com/1.1/study_templates` - 指标模板
- `GET/POST/DELETE /saveload.tradingview.com/1.1/drawing_templates` - 绘图模板

**回放功能API:**
- `GET /api/replay/random` - 获取随机回放点
- `POST /save-trade` - 保存交易记录
- `GET /trade-statistics` - 获取交易统计
- `GET/POST /api/replay/sessions` - 回放会话管理

## 🛠️ 开发

### 运行测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/okx/
```

### 代码结构说明

- **routes/** - 处理HTTP请求,定义API端点
- **services/** - 业务逻辑,数据处理
- **models/** - 数据模型,数据库操作
- **utils/** - 通用工具函数

## 📋 环境变量说明

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `PORT` | 服务端口 | 5000 |
| `DB_HOST` | 数据库主机 | - |
| `DB_PORT` | 数据库端口 | 5432 |
| `DB_NAME` | 数据库名称 | tvdb |
| `OKX_API_KEY` | OKX API密钥 | - |
| `REPLAY_BARS_COUNT` | 回放K线数量 | 150 |
| `REPLAY_EARLIEST_DATE` | 最早回放日期 | 2023-01-01 |

## ⚠️ 免责声明

本项目仅供学习和研究使用。TradingView charting_library 来自官方demo。

**重要:** 在生产环境使用前,请向TradingView官方申请授权。访问 [TradingView官网](https://www.tradingview.com/HTML5-stock-forex-bitcoin-charting-library/) 了解更多授权信息。

## 📝 许可证

见 LICENSE 文件

## 🤝 贡献

欢迎提交Issue和Pull Request!

## 📧 联系方式

如有问题或建议,请提交Issue。
