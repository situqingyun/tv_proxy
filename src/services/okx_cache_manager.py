"""
OKX Data Cache Manager
基于python-okx SDK的数据缓存管理器，负责数据的获取、缓存和管理
"""

import asyncio
import time
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
import psycopg2
from psycopg2.extras import RealDictCursor, execute_batch
import okx.MarketData as Market
import okx.websocket as okxws

from services.okx_rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)

class OKXCacheManager:
    """OKX数据缓存管理器"""

    # 主流货币列表（支持history接口）
    TOP_CURRENCIES = {
        'BTC-USDT', 'ETH-USDT', 'BTC-USDC', 'ETH-USDC',
        'SOL-USDT', 'XRP-USDT', 'DOGE-USDT', 'ADA-USDT',
        'MATIC-USDT', 'DOT-USDT', 'AVAX-USDT', 'LINK-USDT'
    }

    # 数据保留期限（天）- 基于实际测试的regular API限制
    # 重要提示：这些值基于2025-11-02修复before/after参数后的实际测试结果
    # 修复前错误地使用参数导致误以为1H只有12.5天，实际Regular API有60天
    # History API至少可追溯365天
    # OKX可能随时更改数据保留策略，建议定期验证
    DATA_RETENTION_LIMITS = {
        '1m': 0.5, '3m': 0.5, '5m': 0.5, '15m': 0.5, '30m': 0.5,  # 短周期：约0.5天
        '1H': 60, '2H': 60, '4H': 60, '6H': 60, '12H': 60,  # 小时周期：60天（实测）
        '1D': 90, '1W': 90, '1M': 90  # 日周期：保守设为90天（待验证）
    }

    def __init__(self, db_config: Dict, okx_config: Dict):
        """
        初始化缓存管理器
        
        Args:
            db_config: 数据库配置
            okx_config: OKX API配置，包含api_key, secret_key, passphrase, flag
        """
        self.db_config = db_config
        self.okx_config = okx_config
        self.rate_limiter = get_rate_limiter(db_config)
        
        # 初始化OKX Market Data API
        # For public market data, empty credentials work fine
        self.market_api = Market.MarketAPI(
            okx_config.get('api_key', ''),
            okx_config.get('secret_key', ''),
            okx_config.get('passphrase', ''),
            False,  # use_server_time
            okx_config.get('flag', '0')  # 0: live, 1: demo
        )
        
        # Track if we have valid credentials for private endpoints
        self.has_credentials = all([
            okx_config.get('api_key'),
            okx_config.get('secret_key'),
            okx_config.get('passphrase')
        ])
        
        # WebSocket相关
        self.ws_client = None
        self.ws_subscriptions = {}
        
    def get_db_connection(self):
        """获取数据库连接"""
        return psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)
    
    async def get_klines_cached(self, symbol: str, interval: str = "1D",
                               start_time: int = None, end_time: int = None) -> List[Dict]:
        """
        获取K线数据

        注意：当前完全禁用缓存，总是从 OKX API 获取数据

        Args:
            symbol: 交易对，如 "BTC-USDT"
            interval: 时间周期
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）
        """
        # 0. 参数验证和默认值处理
        import time as time_module

        if end_time is None:
            end_time = int(time_module.time() * 1000)

        if start_time is None:
            # 如果没有提供 start_time，则无法确定范围，返回空
            # （在实际应用中，前端应该总是提供 start_time 和 end_time）
            logger.warning("get_klines_cached called without start_time. Returning empty list.")
            return []

        # 1. 跳过缓存读取（完全禁用缓存）
        cached_data = []  # 不读取缓存

        # 2. 检查是否需要从API获取更多数据
        missing_ranges = self._find_missing_ranges(cached_data, start_time, end_time, interval)
        
        # 3. 从API获取缺失数据（使用智能分段+分页策略）
        api_data = []
        for miss_start, miss_end in missing_ranges:
            try:
                logger.info(f"[Missing Range] {datetime.fromtimestamp(miss_start/1000).date()} → {datetime.fromtimestamp(miss_end/1000).date()}")

                # 计算该缺失范围的分段
                segments = self._calculate_time_segments(symbol, interval, miss_start, miss_end)

                # 逐段获取数据（支持分页）
                for seg_start, seg_end, api_type in segments:
                    logger.info(
                        f"[Fetching Segment] {api_type.upper()} API: "
                        f"{datetime.fromtimestamp(seg_start/1000).date()} → "
                        f"{datetime.fromtimestamp(seg_end/1000).date()}"
                    )

                    seg_data = await self._fetch_segment_with_pagination(
                        symbol, interval, seg_start, seg_end, api_type
                    )

                    if seg_data:
                        logger.info(f"[Segment] Got {len(seg_data)} candles from {api_type} API")
                        api_data.extend(seg_data)

                        # 缓存到数据库
                        await self._cache_klines_batch(seg_data)
                    else:
                        logger.warning(f"[Segment] No data from {api_type} API for this segment")

            except Exception as e:
                logger.error(f"Error fetching klines from API: {e}")
        
        # 4. 合并缓存数据和API数据，去重排序
        all_data = cached_data + api_data
        all_data = self._deduplicate_klines(all_data)
        # 关键修复：TradingView要求数据按时间升序排列 (oldest to newest)
        all_data.sort(key=lambda x: x['open_time'], reverse=False)

        # 5. 检测是否已到达历史边界（无更早数据）
        # 这个标志会在 _find_missing_ranges() 中设置
        if hasattr(self, '_reached_history_boundary') and self._reached_history_boundary:
            logger.info("[History Boundary] Reached OKX earliest data (2017-10-01), no earlier data available")
            # 这个标志会被路由层读取，用于返回 noData 给前端
            self._no_earlier_data = True
        else:
            self._no_earlier_data = False

        return all_data
    
    async def get_orderbook_cached(self, symbol: str, depth: int = 20) -> Optional[Dict]:
        """获取订单簿数据，优先从缓存读取"""
        # 1. 先查询最新缓存
        cached_book = await self._get_latest_orderbook(symbol)
        
        # 2. 如果缓存太旧（超过5秒）或不存在，从API获取
        current_time = int(time.time() * 1000)
        if not cached_book or (current_time - cached_book['timestamp']) > 5000:
            try:
                await self.rate_limiter.wait_if_needed('/api/v5/market/books')
                
                response = self.market_api.get_orderbook(instId=symbol, sz=str(depth))
                
                if response['code'] == '0' and response['data']:
                    book_data = response['data'][0]
                    orderbook = {
                        'symbol': symbol,
                        'timestamp': int(book_data['ts']),
                        'bids': [[float(bid[0]), float(bid[1])] for bid in book_data['bids']],
                        'asks': [[float(ask[0]), float(ask[1])] for ask in book_data['asks']]
                    }
                    
                    # 缓存到数据库
                    await self._cache_orderbook(orderbook)
                    return orderbook
                else:
                    logger.error(f"Failed to get orderbook: {response.get('msg', 'Unknown error')}")
                    
            except Exception as e:
                logger.error(f"Error fetching orderbook: {e}")
        
        return cached_book
    
    async def get_recent_trades_cached(self, symbol: str, limit: int = 100) -> List[Dict]:
        """获取最近成交记录"""
        try:
            await self.rate_limiter.wait_if_needed('/api/v5/market/trades')
            
            response = self.market_api.get_trades(instId=symbol, limit=str(limit))
            
            if response['code'] == '0':
                trades = []
                for item in response['data']:
                    trade = {
                        'symbol': symbol,
                        'trade_id': item['tradeId'],
                        'price': Decimal(item['px']),
                        'size': Decimal(item['sz']),
                        'side': item['side'],
                        'timestamp': int(item['ts'])
                    }
                    trades.append(trade)
                
                # 批量缓存成交记录
                await self._cache_trades_batch(trades)
                return trades
            else:
                logger.error(f"Failed to get trades: {response['msg']}")
                
        except Exception as e:
            logger.error(f"Error fetching trades: {e}")
        
        return []
    
    async def _get_cached_klines(self, symbol: str, interval: str, 
                               start_time: int, end_time: int, limit: int) -> List[Dict]:
        """从数据库获取缓存的K线数据"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            query = '''
            SELECT symbol, interval, open_time, close_time, open_price, high_price, 
                   low_price, close_price, volume, volume_currency
            FROM okx_klines 
            WHERE symbol = %s AND interval = %s
            '''
            params = [symbol, interval]
            
            if start_time:
                query += ' AND open_time >= %s'
                params.append(start_time)
            
            if end_time:
                query += ' AND open_time <= %s'
                params.append(end_time)
                
            query += ' ORDER BY open_time DESC LIMIT %s'
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
            
        except Exception as e:
            logger.error(f"Error getting cached klines: {e}")
            return []
    
    def _find_missing_ranges(self, cached_data: List[Dict], start_time: int,
                           end_time: int, interval: str) -> List[Tuple[int, int]]:
        """
        查找缺失的数据时间范围

        策略：完全禁用缓存，总是从 API 获取数据
        但添加历史边界保护，避免请求早于 OKX 最早数据的时间

        【关键】如果请求早于 OKX 最早数据，返回空列表并标记边界
        这样可以让前端收到空数组 + noData=true，符合 TradingView 规范
        """
        # 参数验证
        if start_time is None or end_time is None:
            logger.error(f"[Validation Error] start_time or end_time is None: start_time={start_time}, end_time={end_time}")
            self._reached_history_boundary = False
            return []

        # OKX 历史数据最早时间（2017年10月1日）
        okx_earliest = int(datetime(2017, 10, 1).timestamp() * 1000)

        # 如果请求的 start_time 早于 OKX 最早数据
        if start_time < okx_earliest:
            logger.warning(
                f"[Boundary Protection] 🛑 REJECTED - Requested start_time "
                f"{datetime.fromtimestamp(start_time/1000).isoformat()} "
                f"is earlier than OKX earliest data (2017-10-01)"
            )
            logger.warning(
                f"[Boundary Protection] Returning EMPTY range to trigger noData=true response"
            )
            logger.warning(
                f"[Boundary Protection] This prevents TradingView infinite loop when countBack cannot be satisfied"
            )

            # 标记已到达边界
            self._reached_history_boundary = True
            # 返回空列表，这样 get_klines_cached() 会返回空数据
            return []
        else:
            self._reached_history_boundary = False

        # 完全禁用缓存，总是返回整个范围
        logger.info(f"[No Cache] Fetching from API: {datetime.fromtimestamp(start_time/1000).date()} → {datetime.fromtimestamp(end_time/1000).date()}")
        return [(start_time, end_time)]

    def _calculate_time_segments(
        self, symbol: str, interval: str,
        start_time: int, end_time: int
    ) -> List[Tuple[int, int, str]]:
        """
        将时间范围智能分段，为每段选择合适的API

        Args:
            symbol: 交易对
            interval: 时间周期
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）

        Returns:
            List[(segment_start_ms, segment_end_ms, 'history'/'regular'), ...]

        示例:
            请求90天1H数据 (BTC-USDT, 主流货币)
            → [(90天前, 30天前, 'history'), (30天前, 现在, 'regular')]
        """
        import time as time_module

        current_time_ms = int(time_module.time() * 1000)
        regular_limit_days = self.DATA_RETENTION_LIMITS.get(interval, 30)
        is_top_currency = symbol in self.TOP_CURRENCIES

        # 计算regular API的边界时间（最早能获取的时间）
        regular_boundary_ms = current_time_ms - int(regular_limit_days * 86400 * 1000)

        segments = []

        # 判断是否需要分段
        if start_time < regular_boundary_ms:
            # 请求的数据超出了regular API的范围
            if is_top_currency:
                # 主流货币：可以使用history API获取旧数据
                # 【关键修复】history_end 应该取 end_time 和 regular_boundary 的较小值
                # 这样才能正确处理纯历史数据请求(例如请求2025-09-15的数据)
                history_end = min(end_time, regular_boundary_ms)
                # 段1: 旧数据段 [start_time, history_end) - 由History API负责
                segments.append((start_time, history_end, 'history'))

                # 段2: 新数据段 [regular_boundary, end_time] - 由Regular API负责
                # 只有当 end_time 超过 regular_boundary 时才需要这一段
                if end_time > regular_boundary_ms:
                    segments.append((regular_boundary_ms, end_time, 'regular'))

                logger.info(f"[Segments] Split into History+Regular for {symbol}")
            else:
                # 非主流货币：只能从regular boundary开始获取
                logger.warning(f"[Segments] Non-top currency {symbol} requested old data, adjusting to regular boundary")
                segments.append((regular_boundary_ms, end_time, 'regular'))
        else:
            # 请求的数据都在regular API范围内
            segments.append((start_time, end_time, 'regular'))
            logger.info(f"[Segments] Single Regular segment for {symbol}")

        # 记录分段信息（改进：显示更多细节）
        for i, (seg_start, seg_end, api_type) in enumerate(segments):
            from datetime import datetime
            days = (seg_end - seg_start) / (86400 * 1000)
            expected_bars = int(days * 24 * (3600000 / self._interval_to_ms(interval)))
            logger.info(
                f"[Segment {i+1}] {api_type.upper()}: "
                f"{datetime.fromtimestamp(seg_start/1000).date()} → "
                f"{datetime.fromtimestamp(seg_end/1000).date()} "
                f"({days:.1f}天, 预期~{expected_bars}根K线)"
            )

        return segments

    async def _fetch_segment_with_pagination(
        self, symbol: str, interval: str,
        start_time: int, end_time: int,
        api_type: str, max_bars_per_request: int = 300
    ) -> List[Dict]:
        """
        获取单个时间段的完整数据，严格按照OKX文档使用'after'参数进行分页。
        从end_time开始，向前（获取更旧的数据）循环拉取。

        注意：OKX API参数语义反直觉！
        - 'before': 时间范围的开始边界（不早于此时间） - start_time
        - 'after': 时间范围的结束边界（不晚于此时间） - end_time
        - 单独使用'after'时，返回该时间之前的更旧数据

        Args:
            symbol: 交易对
            interval: 时间周期
            start_time: 段开始时间（毫秒）
            end_time: 段结束时间（毫秒）
            api_type: 'history' 或 'regular'
            max_bars_per_request: 单次API请求最多获取的K线数量

        Returns:
            该时间段内的所有K线数据
        """
        all_klines = []
        # OKX的'after'参数用于获取指定时间戳之前的更旧的数据（反直觉但已验证）
        current_after = end_time

        # 选择API method和endpoint
        if api_type == 'history':
            api_method = self.market_api.get_history_candlesticks
            endpoint = '/api/v5/market/history-candles'
        else:
            api_method = self.market_api.get_candlesticks
            endpoint = '/api/v5/market/candles'

        # 最多循环20次，防止意外的无限循环
        # 添加卡死检测：记录上一次的after值，如果连续相同则停止
        last_after = None
        stuck_count = 0

        for page in range(20):
            try:
                # 检测分页是否卡住（连续收到相同数据）
                if current_after == last_after:
                    stuck_count += 1
                    if stuck_count >= 2:
                        logger.warning(
                            f"[Pagination] 检测到重复数据(after={current_after})，停止分页"
                        )
                        break
                else:
                    stuck_count = 0
                last_after = current_after

                await self.rate_limiter.wait_if_needed(endpoint)

                params = {
                    'instId': symbol,
                    'bar': interval,
                    'limit': str(max_bars_per_request),
                    'after': str(current_after)
                }

                logger.info(
                    f"[Pagination Page {page+1}] Fetching with after={current_after} "
                    f"({datetime.fromtimestamp(current_after/1000).isoformat()})"
                )
                response = api_method(**params)

                if response['code'] == '0' and response['data']:
                    # OKX API返回的数据是倒序的（新->旧），我们直接使用
                    batch = self._convert_kline_response(symbol, interval, response['data'])
                    logger.info(f"[Pagination Page {page+1}] Got {len(batch)} candles")

                    # 过滤出仍在请求时间范围内的数据
                    filtered_batch = [k for k in batch if k['open_time'] >= start_time]
                    all_klines.extend(filtered_batch)

                    # 获取本批次最旧的时间戳
                    oldest_time_in_batch = batch[-1]['open_time']

                    # 更新下一次请求的'after'参数（继续向更旧的方向分页）
                    current_after = oldest_time_in_batch

                    # 如果本批次最旧的数据已经早于或等于我们的目标开始时间，或者返回的数据量小于请求量，说明已经取完
                    if oldest_time_in_batch < start_time or len(batch) < max_bars_per_request:
                        logger.info(f"[Pagination] Reached end of data for this segment.")
                        break
                else:
                    logger.warning(f"[Pagination] No data in response: {response.get('msg', 'empty')}")
                    break  # 没有数据了，退出循环

            except Exception as e:
                logger.error(f"[Pagination] Error on page {page+1}: {e}")
                break

        logger.info(f"[Pagination] Total fetched: {len(all_klines)} candles for segment")
        return all_klines

    async def _fetch_klines_cascade(
        self, symbol: str, interval: str,
        limit: int, start_time: int, end_time: int
    ) -> List[Dict]:
        """
        级联查询K线数据：先尝试history接口，失败则降级到regular接口

        Args:
            symbol: 交易对
            interval: 时间周期
            limit: 数据条数
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）

        Returns:
            K线数据列表
        """
        import time as time_module

        # 计算数据的年龄（距离现在多久）
        # 关键修复：使用start_time（最旧的数据点）来判断数据年龄
        # 而不是end_time，因为end_time通常是"现在"或很近的时间
        current_time_ms = int(time_module.time() * 1000)
        data_age_days = 0

        if start_time:
            # 使用最旧的时间点来判断是否需要history API
            data_age_days = (current_time_ms - start_time) / (1000 * 86400)
        elif end_time:
            data_age_days = (current_time_ms - end_time) / (1000 * 86400)

        # 获取该周期的regular API数据保留期限
        regular_limit = self.DATA_RETENTION_LIMITS.get(interval, 30)

        # 判断是否应该尝试history接口
        # 条件：1. 是主流货币  2. 请求的数据超出regular API的保留期限
        should_try_history = (
            symbol in self.TOP_CURRENCIES and
            data_age_days > regular_limit
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

                # 正确使用before和after参数指定时间范围
                # before=开始时间(更早), after=结束时间(更晚)
                if start_time and end_time:
                    params['before'] = str(start_time)
                    params['after'] = str(end_time)
                elif start_time:
                    # 只指定开始时间，获取该时间之后的数据
                    params['before'] = str(start_time)
                elif end_time:
                    # 只指定结束时间，获取该时间之前的数据
                    params['after'] = str(end_time)

                logger.info(f"[History API] Trying for {symbol} {interval}, data_age={data_age_days:.1f}d > {regular_limit}d, params={params}")
                response = self.market_api.get_history_candlesticks(**params)

                if response['code'] == '0' and response['data']:
                    logger.info(f"[History API] ✓ Success: {len(response['data'])} candles for {symbol}")
                    return self._convert_kline_response(symbol, interval, response['data'])
                else:
                    logger.warning(f"[History API] No data: {response.get('msg', 'empty response')}")

            except Exception as e:
                logger.warning(f"[History API] Error for {symbol}: {e}, falling back to regular API")

        # 降级到regular接口
        await self.rate_limiter.wait_if_needed('/api/v5/market/candles')

        params = {
            'instId': symbol,
            'bar': interval,
            'limit': str(min(300, limit))
        }

        # 正确使用before和after参数指定时间范围
        if start_time and end_time:
            params['before'] = str(start_time)
            params['after'] = str(end_time)
        elif start_time:
            params['before'] = str(start_time)
        elif end_time:
            params['after'] = str(end_time)

        logger.info(f"[Regular API] Fetching {symbol} {interval}, params={params}")
        response = self.market_api.get_candlesticks(**params)

        if response['code'] == '0' and response['data']:
            logger.info(f"[Regular API] ✓ Success: {len(response['data'])} candles for {symbol}")
            return self._convert_kline_response(symbol, interval, response['data'])
        else:
            logger.warning(f"[Regular API] No data for {symbol}: {response.get('msg', 'empty response')}")

        return []

    def _convert_kline_response(self, symbol: str, interval: str, data: List) -> List[Dict]:
        """转换API响应为标准格式"""
        klines = []
        interval_ms = self._interval_to_ms(interval)
        
        for item in data:
            kline = {
                'symbol': symbol,
                'interval': interval,
                'open_time': int(item[0]),
                'close_time': int(item[0]) + interval_ms - 1,
                'open_price': Decimal(item[1]),
                'high_price': Decimal(item[2]),
                'low_price': Decimal(item[3]),
                'close_price': Decimal(item[4]),
                'volume': Decimal(item[5]),
                'volume_currency': Decimal(item[6]) if len(item) > 6 else Decimal('0')
            }
            klines.append(kline)
        
        return klines
    
    async def _cache_klines_batch(self, klines: List[Dict]):
        """批量缓存K线数据"""
        if not klines:
            return
        
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            # 使用UPSERT语句
            upsert_sql = '''
            INSERT INTO okx_klines (symbol, interval, open_time, close_time, 
                                   open_price, high_price, low_price, close_price, 
                                   volume, volume_currency, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (symbol, interval, open_time) 
            DO UPDATE SET
                close_time = EXCLUDED.close_time,
                open_price = EXCLUDED.open_price,
                high_price = EXCLUDED.high_price,
                low_price = EXCLUDED.low_price,
                close_price = EXCLUDED.close_price,
                volume = EXCLUDED.volume,
                volume_currency = EXCLUDED.volume_currency,
                updated_at = CURRENT_TIMESTAMP
            '''
            
            # 准备数据
            values = []
            for kline in klines:
                values.append((
                    kline['symbol'], kline['interval'], kline['open_time'], kline['close_time'],
                    kline['open_price'], kline['high_price'], kline['low_price'], kline['close_price'],
                    kline['volume'], kline['volume_currency']
                ))
            
            execute_batch(cursor, upsert_sql, values)
            conn.commit()
            conn.close()
            
            logger.info(f"Cached {len(klines)} klines for {klines[0]['symbol']}")
            
        except Exception as e:
            logger.error(f"Error caching klines: {e}")
    
    async def _get_latest_orderbook(self, symbol: str) -> Optional[Dict]:
        """获取最新的订单簿数据"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT symbol, timestamp, bids, asks, checksum
            FROM okx_orderbook 
            WHERE symbol = %s
            ORDER BY timestamp DESC 
            LIMIT 1
            ''', (symbol,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return dict(row)
            
        except Exception as e:
            logger.error(f"Error getting latest orderbook: {e}")
        
        return None
    
    async def _cache_orderbook(self, orderbook: Dict):
        """缓存订单簿数据"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT INTO okx_orderbook (symbol, timestamp, bids, asks, checksum)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (symbol, timestamp) DO NOTHING
            ''', (
                orderbook['symbol'],
                orderbook['timestamp'],
                json.dumps(orderbook['bids']),
                json.dumps(orderbook['asks']),
                orderbook.get('checksum')
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error caching orderbook: {e}")
    
    async def _cache_trades_batch(self, trades: List[Dict]):
        """批量缓存成交记录"""
        if not trades:
            return
            
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            upsert_sql = '''
            INSERT INTO okx_trades (symbol, trade_id, price, size, side, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, trade_id) DO NOTHING
            '''
            
            values = [
                (trade['symbol'], trade['trade_id'], trade['price'], 
                 trade['size'], trade['side'], trade['timestamp'])
                for trade in trades
            ]
            
            execute_batch(cursor, upsert_sql, values)
            conn.commit()
            conn.close()
            
            logger.info(f"Cached {len(trades)} trades for {trades[0]['symbol']}")
            
        except Exception as e:
            logger.error(f"Error caching trades: {e}")
    
    def _deduplicate_klines(self, klines: List[Dict]) -> List[Dict]:
        """去重K线数据"""
        seen = set()
        result = []
        
        for kline in klines:
            key = (kline['symbol'], kline['interval'], kline['open_time'])
            if key not in seen:
                seen.add(key)
                result.append(kline)
        
        return result
    
    def _interval_to_ms(self, interval: str) -> int:
        """将时间周期转换为毫秒"""
        # 验证输入
        if not interval or not isinstance(interval, str):
            logger.warning(f"Invalid interval: {interval}, using default 1H")
            return 60 * 60 * 1000  # 默认1小时

        interval_map = {
            '1m': 60 * 1000,
            '3m': 3 * 60 * 1000,
            '5m': 5 * 60 * 1000,
            '15m': 15 * 60 * 1000,
            '30m': 30 * 60 * 1000,
            '1H': 60 * 60 * 1000,
            '2H': 2 * 60 * 60 * 1000,
            '4H': 4 * 60 * 60 * 1000,
            '6H': 6 * 60 * 60 * 1000,
            '12H': 12 * 60 * 60 * 1000,
            '1D': 24 * 60 * 60 * 1000,
            '1W': 7 * 24 * 60 * 60 * 1000,
            '1M': 30 * 24 * 60 * 60 * 1000
        }
        result = interval_map.get(interval, 60 * 1000)
        if result is None:
            logger.warning(f"Interval {interval} not found in map, using default 1m")
            return 60 * 1000
        return result
    
    async def cleanup_old_data(self, days: int = 30):
        """清理旧数据"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            cutoff_date = datetime.now() - timedelta(days=days)
            
            # 清理旧K线数据
            cursor.execute('''
            DELETE FROM okx_klines 
            WHERE created_at < %s
            ''', (cutoff_date,))
            klines_deleted = cursor.rowcount
            
            # 清理旧订单簿数据
            cursor.execute('''
            DELETE FROM okx_orderbook 
            WHERE created_at < %s
            ''', (cutoff_date,))
            orderbook_deleted = cursor.rowcount
            
            # 清理旧成交记录
            cursor.execute('''
            DELETE FROM okx_trades 
            WHERE created_at < %s
            ''', (cutoff_date,))
            trades_deleted = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            logger.info(f"Cleaned up old data: {klines_deleted} klines, "
                       f"{orderbook_deleted} orderbooks, {trades_deleted} trades")
            
            return {
                'klines_deleted': klines_deleted,
                'orderbook_deleted': orderbook_deleted,
                'trades_deleted': trades_deleted
            }
            
        except Exception as e:
            logger.error(f"Error cleaning up old data: {e}")
            return None

# 单例管理
_cache_manager = None

def get_cache_manager(db_config: Dict, okx_config: Dict) -> OKXCacheManager:
    """获取缓存管理器单例"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = OKXCacheManager(db_config, okx_config)
    return _cache_manager
