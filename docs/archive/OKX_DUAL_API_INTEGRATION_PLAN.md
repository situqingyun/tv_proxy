# OKX双接口集成方案：结合candles和history-candles

## 日期：2025-10-07

## 接口对比分析

### 1. 两个K线接口

| 特性 | candles (普通K线) | history-candles (历史K线) |
|------|------------------|-------------------------|
| **端点路径** | `/api/v5/market/candles` | `/api/v5/market/history-candles` |
| **SDK方法** | `get_candlesticks()` | `get_history_candlesticks()` |
| **货币支持** | 所有交易对 | **仅主流货币**（top currencies only）|
| **数据保留期限** | 1m: 12小时<br>1H: 30天<br>1D: 2年+ | 可能更长（待验证） |
| **用途** | 实时/近期数据 | 历史回放/回测 |

### 2. 实际测试验证

根据我的测试结果：

**普通K线接口 (`/api/v5/market/candles`) 的数据保留期限：**
```
1m (1分钟): ✓ 0.5天前有数据  ✗ 1天前无数据
1H (1小时): ✓ 30天前有数据   ✗ 60天前无数据
1D (1天):   ✓ 730天前有数据（至少2年）
```

**历史K线接口的优势：**
- 提供更长时间跨度的历史数据
- 特别适合回放功能和历史分析
- 仅支持主流货币（BTC、ETH等top currencies）

## 集成策略设计

### 策略1：级联查询策略（推荐）

**原理：**先尝试history接口，失败或无数据时降级到candles接口

```python
async def get_klines_with_fallback(
    self, symbol: str, interval: str,
    limit: int, start_time: int, end_time: int
) -> List[Dict]:
    """
    级联查询：history接口 → candles接口
    """

    # Step 1: 尝试history接口（如果是主流货币）
    if symbol in self.TOP_CURRENCIES:  # BTC-USDT, ETH-USDT, etc.
        try:
            history_data = await self._fetch_history_candlesticks(
                symbol, interval, limit, start_time, end_time
            )
            if history_data:
                logger.info(f"[History API] Got {len(history_data)} candles")
                return history_data
        except Exception as e:
            logger.warning(f"[History API] Failed: {e}, falling back to regular API")

    # Step 2: 降级到普通candles接口
    regular_data = await self._fetch_regular_candlesticks(
        symbol, interval, limit, start_time, end_time
    )
    logger.info(f"[Regular API] Got {len(regular_data)} candles")
    return regular_data
```

**优势：**
- 自动选择最佳数据源
- 主流货币可获取更长历史
- 小币种自动降级，不影响使用
- 容错性强

### 策略2：时间范围智能路由策略

**原理：**根据请求的时间范围自动选择接口

```python
async def get_klines_smart_routing(
    self, symbol: str, interval: str,
    limit: int, start_time: int, end_time: int
) -> List[Dict]:
    """
    智能路由：根据时间范围和间隔选择接口
    """

    # 计算请求的时间跨度
    time_span_days = (end_time - start_time) / (1000 * 86400)

    # 根据interval和时间跨度判断数据可用性
    data_limits = {
        '1m': 0.5,   # 12小时
        '3m': 0.5,
        '5m': 0.5,
        '15m': 0.5,
        '30m': 0.5,
        '1H': 30,    # 30天
        '2H': 30,
        '4H': 30,
        '1D': 730,   # 2年
        '1W': 730,
        '1M': 730
    }

    regular_limit = data_limits.get(interval, 30)

    # 如果请求超出普通接口范围，且是主流货币，使用history接口
    if time_span_days > regular_limit and symbol in self.TOP_CURRENCIES:
        logger.info(f"[Smart Routing] Using history API (time span: {time_span_days:.1f} days > {regular_limit} days)")
        return await self._fetch_history_candlesticks(
            symbol, interval, limit, start_time, end_time
        )
    else:
        logger.info(f"[Smart Routing] Using regular API (time span: {time_span_days:.1f} days <= {regular_limit} days)")
        return await self._fetch_regular_candlesticks(
            symbol, interval, limit, start_time, end_time
        )
```

**优势：**
- 根据实际需求选择接口
- 避免不必要的history接口调用
- 更高效的资源利用

### 策略3：数据源优先级配置策略

**原理：**允许用户配置数据源优先级

```python
class DataSourceStrategy(Enum):
    HISTORY_FIRST = "history_first"  # 优先history
    REGULAR_FIRST = "regular_first"  # 优先regular
    SMART_ROUTING = "smart_routing"  # 智能路由
    HISTORY_ONLY = "history_only"    # 仅history
    REGULAR_ONLY = "regular_only"    # 仅regular

# 在配置文件中
OKX_DATA_SOURCE_STRATEGY = os.environ.get('OKX_DATA_SOURCE_STRATEGY', 'history_first')
```

## 实施方案

### 阶段1：增强okx_cache_manager.py

修改 `okx_cache_manager.py`，添加历史K线接口支持：

```python
class OKXCacheManager:

    # 主流货币列表（支持history接口）
    TOP_CURRENCIES = {
        'BTC-USDT', 'ETH-USDT', 'BTC-USDC', 'ETH-USDC',
        'SOL-USDT', 'XRP-USDT', 'DOGE-USDT', 'ADA-USDT',
        'MATIC-USDT', 'DOT-USDT', 'AVAX-USDT', 'LINK-USDT'
    }

    # 数据保留期限（天）
    DATA_RETENTION_LIMITS = {
        '1m': 0.5, '3m': 0.5, '5m': 0.5, '15m': 0.5, '30m': 0.5,
        '1H': 30, '2H': 30, '4H': 30, '6H': 30, '12H': 30,
        '1D': 730, '1W': 730, '1M': 730
    }

    async def get_klines_cached(
        self, symbol: str, interval: str = "1D",
        limit: int = 100, start_time: int = None, end_time: int = None
    ) -> List[Dict]:
        """获取K线数据，智能选择数据源"""

        # 1. 检查数据库缓存
        cached_data = await self._get_cached_klines(
            symbol, interval, start_time, end_time, limit
        )

        # 2. 查找缺失数据范围（修复后的逻辑）
        missing_ranges = self._find_missing_ranges_fixed(
            cached_data, start_time, end_time, interval, limit
        )

        # 3. 从API获取缺失数据（使用级联策略）
        api_data = []
        for start, end in missing_ranges:
            try:
                # 级联查询：先history，后regular
                data = await self._fetch_klines_cascade(
                    symbol, interval, limit, start, end
                )
                api_data.extend(data)

                # 缓存到数据库
                await self._cache_klines_batch(data)

            except Exception as e:
                logger.error(f"Error fetching klines: {e}")

        # 4. 合并、去重、排序
        all_data = cached_data + api_data
        all_data = self._deduplicate_klines(all_data)
        all_data.sort(key=lambda x: x['open_time'], reverse=True)

        return all_data[:limit]

    async def _fetch_klines_cascade(
        self, symbol: str, interval: str,
        limit: int, start_time: int, end_time: int
    ) -> List[Dict]:
        """级联查询：history接口 → regular接口"""

        # 计算时间跨度
        time_span_days = (end_time - start_time) / (1000 * 86400) if start_time and end_time else 0
        regular_limit = self.DATA_RETENTION_LIMITS.get(interval, 30)

        # 判断是否应该尝试history接口
        should_try_history = (
            symbol in self.TOP_CURRENCIES and
            time_span_days > regular_limit
        )

        # 尝试history接口（如果适用）
        if should_try_history:
            try:
                await self.rate_limiter.wait_if_needed('/api/v5/market/history-candles')

                params = {
                    'instId': symbol,
                    'bar': interval,
                    'limit': str(min(300, limit))
                }

                if end_time:
                    params['after'] = str(end_time)

                response = self.market_api.get_history_candlesticks(**params)

                if response['code'] == '0' and response['data']:
                    logger.info(f"[History API] Success: {len(response['data'])} candles for {symbol}")
                    return self._convert_kline_response(symbol, interval, response['data'])
                else:
                    logger.warning(f"[History API] No data: {response.get('msg', '')}")

            except Exception as e:
                logger.warning(f"[History API] Error: {e}, falling back to regular API")

        # 降级到regular接口
        await self.rate_limiter.wait_if_needed('/api/v5/market/candles')

        params = {
            'instId': symbol,
            'bar': interval,
            'limit': str(min(300, limit))
        }

        if end_time:
            params['after'] = str(end_time)

        response = self.market_api.get_candlesticks(**params)

        if response['code'] == '0' and response['data']:
            logger.info(f"[Regular API] Success: {len(response['data'])} candles for {symbol}")
            return self._convert_kline_response(symbol, interval, response['data'])

        return []

    def _find_missing_ranges_fixed(
        self, cached_data: List[Dict],
        start_time: int, end_time: int,
        interval: str, limit: int
    ) -> List[Tuple[int, int]]:
        """修复后的缺失范围查找逻辑"""

        if not start_time or not end_time:
            return [(start_time, end_time)]

        if not cached_data:
            return [(start_time, end_time)]

        # 排序缓存数据
        cached_data.sort(key=lambda x: x['open_time'])

        missing_ranges = []
        interval_ms = self._interval_to_ms(interval)

        # 检查开始时间之前的缺失
        if cached_data[0]['open_time'] > start_time:
            missing_ranges.append((
                start_time,
                cached_data[0]['open_time'] - interval_ms
            ))

        # 检查中间缺失的时间段
        for i in range(len(cached_data) - 1):
            current_end = cached_data[i]['open_time']
            next_start = cached_data[i + 1]['open_time']
            gap = next_start - current_end

            # 如果间隔大于1.5倍周期，说明有缺失
            if gap > interval_ms * 1.5:
                missing_ranges.append((
                    current_end + interval_ms,
                    next_start - interval_ms
                ))

        # 检查结束时间之后的缺失
        if cached_data[-1]['open_time'] < end_time:
            missing_ranges.append((
                cached_data[-1]['open_time'] + interval_ms,
                end_time
            ))

        return missing_ranges if missing_ranges else []
```

### 阶段2：增强okx_service.py

修改随机回放点生成逻辑：

```python
class OKXService:

    async def get_random_replay_point(
        self, symbol: Optional[str] = None,
        bars_count: Optional[int] = 150,
        interval: Optional[str] = '1D'
    ) -> Dict[str, Any]:
        """
        智能随机回放点生成
        - 主流货币：使用history接口，可以回放更久远的历史
        - 小币种：使用regular接口，受限于数据保留期限
        """

        if bars_count is None or bars_count <= 0:
            bars_count = 150

        # 随机选择货币
        if not symbol:
            symbol = random.choice(self.okx_replay_symbols)

        # 判断是否为主流货币
        is_top_currency = symbol in self.cache_manager.TOP_CURRENCIES

        # 获取该周期的数据保留期限
        interval_seconds = self._interval_to_seconds(interval)
        retention_days = self.cache_manager.DATA_RETENTION_LIMITS.get(interval, 30)

        # 主流货币可以使用更长的历史数据
        if is_top_currency:
            # 假设history接口支持5年的数据
            max_days = min(1825, retention_days * 10)  # 1825天 = 5年
            logger.info(f"[Replay] Using extended history for top currency {symbol}: {max_days} days")
        else:
            max_days = retention_days
            logger.info(f"[Replay] Using regular retention for {symbol}: {max_days} days")

        # 计算时间范围
        current_time = int(time.time())
        earliest_time = current_time - int(max_days * 86400)
        latest_time = current_time - (bars_count * interval_seconds)

        if latest_time < earliest_time:
            latest_time = earliest_time

        # 随机选择时间点
        if earliest_time >= latest_time:
            random_start_time = earliest_time
        else:
            random_start_time = random.randint(earliest_time, latest_time)

        return {
            'symbol': symbol,
            'start_time': random_start_time,
            'bars_count': bars_count,
            'data_source': 'history' if is_top_currency else 'regular'
        }
```

### 阶段3：添加数据验证和测试

创建验证脚本 `test_dual_api_integration.py`：

```python
async def test_dual_api():
    """测试双接口集成"""

    test_cases = [
        # 主流货币 - 长历史
        {
            'symbol': 'BTC-USDT',
            'interval': '1H',
            'days_ago': 60,  # 超出regular接口限制
            'expected_source': 'history'
        },
        # 主流货币 - 短历史
        {
            'symbol': 'BTC-USDT',
            'interval': '1H',
            'days_ago': 7,
            'expected_source': 'regular'
        },
        # 小币种 - 只能用regular
        {
            'symbol': 'SHIB-USDT',
            'interval': '1H',
            'days_ago': 60,
            'expected_source': 'regular'
        }
    ]

    for test in test_cases:
        klines = await okx_service.get_klines(
            symbol=test['symbol'],
            interval=test['interval'],
            limit=100,
            start_time=calculate_start_time(test['days_ago']),
            end_time=calculate_end_time(test['days_ago'])
        )

        print(f"Test: {test['symbol']} {test['interval']} {test['days_ago']}d ago")
        print(f"  Got {len(klines)} candles")
        print(f"  Expected source: {test['expected_source']}")
```

## 配置文件更新

在 `.env` 中添加：

```bash
# OKX数据源配置
OKX_DATA_SOURCE_STRATEGY=history_first  # history_first, regular_first, smart_routing
OKX_TOP_CURRENCIES=BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,DOGE-USDT,ADA-USDT,MATIC-USDT,DOT-USDT,AVAX-USDT,LINK-USDT

# 回放配置（根据是否为主流货币动态调整）
REPLAY_HISTORY_DAYS_TOP_CURRENCIES=1825  # 主流货币：5年
REPLAY_HISTORY_DAYS_OTHERS=30            # 其他货币：30天
```

## 优势总结

1. **更长的历史数据范围**：主流货币可访问更久远的历史数据
2. **自动降级机制**：小币种或history接口失败时自动降级
3. **智能路由**：根据时间范围自动选择最佳接口
4. **向后兼容**：不影响现有代码，透明集成
5. **容错性强**：多层fallback机制
6. **配置灵活**：可通过环境变量调整策略

## 实施优先级

1. **P0（立即）**：修复 `_find_missing_ranges` 缓存逻辑
2. **P1（本周）**：实现级联查询策略（history → regular）
3. **P2（下周）**：添加智能路由和数据验证
4. **P3（后续）**：性能优化和监控

## 测试计划

1. 验证history接口对不同货币的支持情况
2. 验证history接口的实际数据保留期限
3. 测试级联查询的性能和准确性
4. 压力测试：并发请求、大数据量、长时间范围

## 预期效果

- 主流货币（BTC、ETH等）：可回放**至少1年以上**的历史数据
- 小币种：回放范围受限于regular接口（1m: 12h, 1H: 30d, 1D: 2y）
- 用户体验：随机K线功能不再跳转到错误时间
- 性能：通过缓存减少API调用，提升响应速度
