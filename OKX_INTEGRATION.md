# OKX数据源集成

本项目集成了OKX交易所的市场数据API，支持K线数据、深度数据、成交记录的获取和缓存。

## 特性

- 基于官方python-okx SDK
- 智能缓存机制，减少API请求次数
- 速率限制管理，避免触发API限制
- PostgreSQL数据持久化
- 支持实时和历史数据获取

## 配置

### 1. 环境变量配置

复制 `.env.example` 到 `.env` 并配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# OKX API配置
OKX_API_KEY=your_okx_api_key
OKX_SECRET_KEY=your_okx_secret_key
OKX_PASSPHRASE=your_okx_passphrase
OKX_FLAG=1  # 0: 实盘, 1: 模拟盘
```

### 2. 获取OKX API凭证

1. 访问 [OKX API管理页面](https://www.okx.com/account/my-api)
2. 创建新的API Key
3. 设置权限：至少需要"读取"权限
4. 记录API Key、Secret Key和Passphrase

### 3. 安装依赖

```bash
pip install python-okx
```

或更新整个项目依赖：

```bash
uv pip install -e .
```

## API端点

### K线数据

```http
GET /api/okx/klines?symbol=BTC-USDT&interval=1D&limit=100
```

参数：
- `symbol`: 交易对，如 BTC-USDT
- `interval`: 时间周期，支持 1m, 3m, 5m, 15m, 30m, 1H, 2H, 4H, 6H, 12H, 1D, 1W, 1M
- `limit`: 返回数据条数 (1-300)
- `start_time`: 开始时间戳（毫秒，可选）
- `end_time`: 结束时间戳（毫秒，可选）

响应示例：
```json
{
  "status": "ok",
  "data": [
    {
      "symbol": "BTC-USDT",
      "interval": "1D",
      "open_time": 1704067200000,
      "close_time": 1704153599999,
      "open_price": 45000.5,
      "high_price": 46000.0,
      "low_price": 44500.0,
      "close_price": 45800.0,
      "volume": 1234.56,
      "volume_currency": 56789012.34
    }
  ],
  "count": 1
}
```

### 订单簿数据

```http
GET /api/okx/orderbook?symbol=BTC-USDT&depth=20
```

参数：
- `symbol`: 交易对
- `depth`: 深度档位 (1, 5, 10, 20, 50)

### 成交记录

```http
GET /api/okx/trades?symbol=BTC-USDT&limit=100
```

参数：
- `symbol`: 交易对
- `limit`: 返回数据条数 (1-500)

### 速率限制统计

```http
GET /api/okx/rate-limit-stats?hours=24
```

查看API请求统计和速率限制情况。

## 缓存机制

### 工作原理

1. **优先缓存**: 首先从PostgreSQL数据库查询缓存数据
2. **智能补全**: 检测缺失的时间范围，从API获取补充数据
3. **自动更新**: 实时数据自动更新缓存
4. **去重处理**: 合并数据时自动去重

### 缓存策略

- **K线数据**: 按symbol+interval+时间范围缓存
- **深度数据**: 保留最新快照，5秒过期
- **成交记录**: 按trade_id去重缓存

### 数据表结构

```sql
-- K线数据表
okx_klines (symbol, interval, open_time, close_time, open_price, high_price, low_price, close_price, volume, volume_currency)

-- 深度数据表
okx_orderbook (symbol, timestamp, bids, asks, checksum)

-- 成交记录表
okx_trades (symbol, trade_id, price, size, side, timestamp)

-- API请求记录表
okx_api_requests (endpoint, method, request_time, response_status, rate_limit_remaining)
```

## 速率限制管理

### 限制配置

不同API端点有不同的速率限制：

- K线数据: 10次/2秒, 600次/分钟
- 深度数据: 10次/2秒, 600次/分钟
- 成交记录: 10次/2秒, 600次/分钟
- 行情数据: 20次/2秒, 1200次/分钟

### 自动管理

- **请求前检查**: 自动检查是否超过限制
- **智能等待**: 如需等待会自动延迟请求
- **记录统计**: 所有请求都会记录用于分析

## 数据维护

### 清理旧数据

```http
POST /api/okx/cleanup?days=30
```

清理30天前的缓存数据。

### 清理API日志

```http
POST /api/okx/cleanup-api-logs?days=7
```

清理7天前的API请求日志。

## 使用示例

### Python客户端示例

```python
import requests
import asyncio

# 获取BTC-USDT的日K线数据
async def get_btc_klines():
    url = "http://localhost:5000/api/okx/klines"
    params = {
        "symbol": "BTC-USDT",
        "interval": "1D",
        "limit": 100
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    if data["status"] == "ok":
        klines = data["data"]
        print(f"获取到 {len(klines)} 条K线数据")
        
        # 打印最新K线
        latest = klines[0]
        print(f"最新价格: {latest['close_price']}")
    else:
        print("获取数据失败")

# JavaScript前端示例
```

### JavaScript示例

```javascript
// 获取实时订单簿数据
async function getOrderbook(symbol) {
    try {
        const response = await fetch(`/api/okx/orderbook?symbol=${symbol}&depth=20`);
        const data = await response.json();
        
        if (data.status === 'ok') {
            console.log('买盘:', data.data.bids);
            console.log('卖盘:', data.data.asks);
        }
    } catch (error) {
        console.error('获取订单簿失败:', error);
    }
}

// 使用
getOrderbook('BTC-USDT');
```

## 错误处理

### 常见错误

1. **503 Service Unavailable**: OKX API未配置
2. **429 Too Many Requests**: 超过速率限制
3. **404 Not Found**: 数据不存在
4. **500 Internal Server Error**: 服务器错误

### 错误响应格式

```json
{
    "detail": "错误描述"
}
```

## 监控和调试

### 查看API统计

访问 `/api/okx/rate-limit-stats` 查看：
- 请求次数统计
- 平均响应时间
- 错误率
- 剩余配额

### 日志记录

系统会自动记录：
- API请求响应时间
- 速率限制状态
- 错误信息
- 缓存命中率

## 性能优化建议

1. **合理设置limit**: 避免单次请求过多数据
2. **使用时间范围**: 指定start_time和end_time减少不必要的数据
3. **定期清理**: 设置定时任务清理旧数据
4. **监控API配额**: 定期查看速率限制统计

## 故障排除

### 常见问题

1. **API凭证错误**
   - 检查.env文件中的API配置
   - 确认API Key权限设置

2. **数据库连接失败**
   - 检查PostgreSQL服务状态
   - 验证数据库配置

3. **速率限制问题**
   - 查看API统计找出高频请求
   - 调整请求间隔

4. **缓存数据过期**
   - 检查数据库中的时间戳
   - 手动触发数据更新

### 联系支持

如有问题，请查看应用日志文件 `app.log` 获取详细错误信息。