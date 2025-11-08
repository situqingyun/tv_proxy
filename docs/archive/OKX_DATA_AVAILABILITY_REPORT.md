# OKX 历史数据可用性分析报告

## 日期：2025-10-07

## 问题描述

用户在使用随机K线功能时遇到以下问题：
- 设置可视范围：`{from: 1748222364, to: 1748228364}` (2025-05-25)
- 实际获取范围：`{from: 1759791720, to: 1759791780}` (2025-10-06)
- 图表自动跳转到完全不同的时间

## 根本原因

经过实际测试OKX API，发现**OKX不同周期的历史数据保留期限差异巨大**：

### 测试结果

| 周期 | 数据保留期限 | 说明 |
|------|-------------|------|
| **1m (1分钟)** | **约12小时** | ✓ 0.5天前有数据<br>✗ 1天前无数据 |
| **1H (1小时)** | **约30天** | ✓ 30天前有数据<br>✗ 60天前无数据 |
| **1D (1天)** | **至少2年** | ✓ 730天前有数据 |

### 详细测试日志

#### 1分钟周期测试
```
  0.25 days ago: ✓ 有数据
  0.50 days ago: ✓ 有数据
  1.00 days ago: ✗ 无数据
  2.00 days ago: ✗ 无数据
  3.00 days ago: ✗ 无数据
  7.00 days ago: ✗ 无数据
```

#### 1小时周期测试
```
   1 days ago: ✓ 有数据
   2 days ago: ✓ 有数据
   3 days ago: ✓ 有数据
   7 days ago: ✓ 有数据
  14 days ago: ✓ 有数据
  30 days ago: ✓ 有数据
  60 days ago: ✗ 无数据
  90 days ago: ✗ 无数据
```

#### 1日周期测试
```
   7 days ago: ✓ 有数据
  14 days ago: ✓ 有数据
  30 days ago: ✓ 有数据
  60 days ago: ✓ 有数据
  90 days ago: ✓ 有数据
 180 days ago: ✓ 有数据
 365 days ago: ✓ 有数据
 730 days ago: ✓ 有数据
```

## 问题分析

### 1. 当前配置问题

在 `.env` 配置中：
```bash
REPLAY_EARLIEST_DATE=2023-01-01  # 距今约640天
```

这个配置在不同周期下的实际可用性：
- **1m周期**：❌ 完全不可用（仅支持12小时内）
- **1H周期**：❌ 完全不可用（仅支持30天内）
- **1D周期**：✅ 可以使用（支持2年内）

### 2. 数据流程分析

```
前端: setVisibleRange({from: 1748222364, to: 1748228364})  // 5个月前
  ↓
TradingView调用: getBars({from: 1748222364, to: 1748228364})
  ↓
后端请求: /api/okx/klines?symbol=BTC-USDT&interval=1m&start_time=1748222364000
  ↓
OKX API: market_api.get_candlesticks(instId='BTC-USDT', bar='1m', after='1748228364000')
  ↓
OKX返回: {'code': '0', 'msg': '', 'data': []}  // 空数组
  ↓
前端处理: onHistoryCallback([], { noData: true })
  ↓
TradingView行为: 检测到无数据，自动跳转到最新可用数据（当前时间）
```

### 3. 缓存管理器问题

在 `okx_cache_manager.py` 第240-242行发现：

```python
def _find_missing_ranges(self, cached_data: List[Dict], start_time: int,
                       end_time: int, interval: str, limit: int) -> List[Tuple[int, int]]:
    """查找缺失的数据时间范围"""
    # 暂时禁用缓存，总是从 API 获取最新数据
    # 这样可以确保数据的准确性
    return [(start_time, end_time)]
```

**这个函数完全绕过了数据库缓存，总是直接请求OKX API！**

即使数据库中有缓存数据，也会被忽略，直接向OKX API请求。由于OKX历史数据有限，导致大量请求返回空数组。

## 解决方案

### 方案1：根据周期动态限制回放时间范围（推荐）

修改 `okx_service.py` 的 `get_random_replay_point` 方法：

```python
async def get_random_replay_point(
    self,
    symbol: Optional[str] = None,
    bars_count: Optional[int] = 150,
    interval: Optional[str] = '1D'
) -> Dict[str, Any]:
    """根据周期动态计算最早回放时间"""

    # 根据周期确定OKX数据可用性
    interval_data_limits = {
        '1m': 0.5,    # 12小时（0.5天）
        '3m': 0.5,
        '5m': 0.5,
        '15m': 0.5,
        '30m': 0.5,
        '1H': 30,     # 30天
        '2H': 30,
        '4H': 30,
        '6H': 30,
        '12H': 30,
        '1D': 730,    # 2年
        '1W': 730,
        '1M': 730
    }

    # 获取该周期的最大回溯天数
    max_days = interval_data_limits.get(interval, 30)  # 默认30天

    # 计算最早时间（确保在OKX数据范围内）
    current_time = int(time.time())
    earliest_time = current_time - int(max_days * 86400)

    # 计算interval秒数
    interval_seconds = self._interval_to_seconds(interval)

    # 计算最晚时间（确保有足够的bars_count）
    latest_time = current_time - (bars_count * interval_seconds)

    # 如果最晚时间早于最早时间，使用最早时间
    if latest_time < earliest_time:
        latest_time = earliest_time

    # 随机选择时间点
    if earliest_time >= latest_time:
        random_start_time = earliest_time
    else:
        random_start_time = random.randint(earliest_time, latest_time)

    return {
        'symbol': symbol or random.choice(self.okx_replay_symbols),
        'start_time': random_start_time,
        'bars_count': bars_count
    }
```

### 方案2：修复缓存管理器

修改 `okx_cache_manager.py` 的 `_find_missing_ranges` 方法，实现真正的缓存逻辑：

```python
def _find_missing_ranges(self, cached_data: List[Dict], start_time: int,
                       end_time: int, interval: str, limit: int) -> List[Tuple[int, int]]:
    """查找缺失的数据时间范围（真正的缓存逻辑）"""

    if not start_time or not end_time:
        return [(start_time, end_time)]

    if not cached_data:
        # 没有缓存数据，请求完整范围
        return [(start_time, end_time)]

    # 排序缓存数据
    cached_data.sort(key=lambda x: x['open_time'])

    # 找出缺失的时间段
    missing_ranges = []
    interval_ms = self._interval_to_ms(interval)

    # 检查开始时间之前的缺失
    if cached_data[0]['open_time'] > start_time:
        missing_ranges.append((start_time, cached_data[0]['open_time'] - interval_ms))

    # 检查中间缺失的时间段
    for i in range(len(cached_data) - 1):
        current_end = cached_data[i]['open_time']
        next_start = cached_data[i + 1]['open_time']
        gap = next_start - current_end

        # 如果间隔大于一个周期，说明有缺失
        if gap > interval_ms * 1.5:  # 1.5倍容差
            missing_ranges.append((current_end + interval_ms, next_start - interval_ms))

    # 检查结束时间之后的缺失
    if cached_data[-1]['open_time'] < end_time:
        missing_ranges.append((cached_data[-1]['open_time'] + interval_ms, end_time))

    return missing_ranges if missing_ranges else []
```

### 方案3：前端增加数据范围验证

修改 `templates/okx.html` 的 `requestRandomReplayPoint` 函数，增加验证：

```javascript
async function requestRandomReplayPoint() {
    // ... 现有代码 ...

    const data = await response.json();

    if (data.status === 'ok' && data.data) {
        const { symbol, start_time, bars_count } = data.data;

        // 验证：尝试获取该时间点的数据
        const testResponse = await fetch(
            `/api/okx/klines?symbol=${symbol}&interval=${serverInterval}&limit=1&start_time=${start_time * 1000}`
        );
        const testData = await testResponse.json();

        if (!testData.data || testData.data.length === 0) {
            console.warn('[requestRandomReplayPoint] Selected time has no data, retrying...');
            // 重试或使用当前时间
            return requestRandomReplayPoint();
        }

        // 继续设置图表...
    }
}
```

## 推荐实施步骤

1. **立即修复**：实施方案1，根据周期动态限制回放时间
2. **中期优化**：实施方案2，修复缓存管理器逻辑
3. **长期改进**：实施方案3，增加前端验证

## 测试验证

运行以下测试脚本验证修复：
```bash
source .venv/bin/activate
python test_okx_api_direct.py      # 测试OKX API
python test_okx_data_depth.py      # 测试1分钟数据深度
python test_okx_intervals_depth.py # 测试不同周期数据深度
```

## 总结

**问题根源**：OKX API对不同周期的历史数据保留期限差异巨大（1m仅12小时，1H约30天，1D至少2年），而当前配置固定使用2023-01-01作为最早回放时间，导致1分钟和1小时周期的随机回放完全无法使用。

**解决办法**：根据当前图表周期动态计算最早可回放时间，确保始终在OKX数据可用范围内。
