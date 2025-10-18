"""
OKX数据服务层
提供OKX数据源的业务逻辑
"""

import time
import os
import logging
import random
from typing import Optional, Dict, Any, List
from datetime import datetime

from okx_cache_manager import get_cache_manager
from okx_rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)


class OKXService:
    """OKX数据服务类"""

    def __init__(self, db_config: Dict[str, Any], okx_config: Dict[str, Any]):
        """
        初始化OKX服务

        Args:
            db_config: 数据库配置
            okx_config: OKX API配置
        """
        self.db_config = db_config
        self.okx_config = okx_config
        self.cache_manager = get_cache_manager(db_config, okx_config)
        self.rate_limiter = get_rate_limiter(db_config)

        # Simple cache for OKX instruments
        self.instruments_cache = {
            'data': None,
            'timestamp': 0,
            'ttl': 300  # Cache for 5 minutes
        }

        # 回放配置
        self.replay_earliest_date = os.environ.get('REPLAY_EARLIEST_DATE', '2023-01-01')
        self.replay_earliest_timestamp = int(datetime.strptime(self.replay_earliest_date, '%Y-%m-%d').timestamp())
        self.okx_replay_symbols = os.environ.get('OKX_REPLAY_SYMBOLS', 'BTC-USDT,ETH-USDT').split(',')

        if not all([okx_config.get("api_key"), okx_config.get("secret_key"), okx_config.get("passphrase")]):
            logger.warning("OKX API credentials not configured, only public market data will be available")

    async def get_instruments(
        self,
        inst_type: str = "SPOT",
        uly: Optional[str] = None,
        inst_family: Optional[str] = None,
        inst_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取OKX交易对列表

        Args:
            inst_type: 交易对类型
            uly: 标的指数
            inst_family: 交易品种
            inst_id: 交易对ID

        Returns:
            交易对列表
        """
        try:
            import okx.PublicData as Public

            # Use public API (no credentials needed)
            api = Public.PublicAPI()

            # Get instruments
            response = api.get_instruments(
                instType=inst_type,
                uly=uly or '',
                instId=inst_id or '',
                instFamily=inst_family or ''
            )

            if response['code'] == '0' and response['data']:
                # Format for TradingView
                instruments = []
                for inst in response['data']:
                    # Only include active instruments
                    if inst.get('state') != 'live':
                        continue

                    # Format symbol for TradingView
                    symbol = inst['instId']
                    base_ccy = inst.get('baseCcy', '')
                    quote_ccy = inst.get('quoteCcy', 'USDT')

                    instrument = {
                        'symbol': symbol,
                        'ticker': symbol,
                        'full_name': f"{base_ccy}/{quote_ccy}" if base_ccy else symbol,
                        'description': f"{base_ccy}/{quote_ccy}" if base_ccy else symbol,
                        'exchange': 'OKX',
                        'type': 'crypto',
                        'base_currency': base_ccy,
                        'quote_currency': quote_ccy,
                        'min_size': float(inst.get('minSz', 0)),
                        'tick_size': float(inst.get('tickSz', 0.01)),
                        'lot_size': float(inst.get('lotSz', 1)),
                        'contract_val': float(inst.get('ctVal', 1)) if inst.get('ctVal') else None,
                        'listing_time': int(inst.get('listTime', 0))
                    }
                    instruments.append(instrument)

                # Sort by listing time (newest first) and then by symbol
                instruments.sort(key=lambda x: (-x['listing_time'], x['symbol']))

                return instruments
            else:
                logger.error(f"Failed to get instruments: {response.get('msg', 'Unknown error')}")
                return []

        except Exception as e:
            logger.exception(f"Error getting OKX instruments: {str(e)}")
            raise

    async def search_symbols(
        self,
        query: str = "",
        inst_type: str = "SPOT",
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        搜索OKX交易对（带缓存）

        Args:
            query: 搜索关键词
            inst_type: 交易对类型
            limit: 返回结果数量限制

        Returns:
            搜索结果列表
        """
        try:
            import okx.PublicData as Public
            current_time = time.time()

            # Check cache first
            cache_key = f"{inst_type}_instruments"
            if (self.instruments_cache.get('data') and
                self.instruments_cache.get('type') == cache_key and
                (current_time - self.instruments_cache['timestamp']) < self.instruments_cache['ttl']):

                logger.info(f"Using cached instruments for {inst_type}")
                response = {'code': '0', 'data': self.instruments_cache['data']}
            else:
                logger.info(f"Fetching fresh instruments for {inst_type}")
                # Use public API (no credentials needed)
                api = Public.PublicAPI()

                # Get all instruments of the specified type
                response = api.get_instruments(instType=inst_type)

                # Update cache if successful
                if response['code'] == '0' and response['data']:
                    self.instruments_cache['data'] = response['data']
                    self.instruments_cache['type'] = cache_key
                    self.instruments_cache['timestamp'] = current_time

            if response['code'] == '0' and response['data']:
                results = []
                query_lower = query.lower()

                for inst in response['data']:
                    # Only include active instruments
                    if inst.get('state') != 'live':
                        continue

                    symbol = inst['instId']
                    base_ccy = inst.get('baseCcy', '')
                    quote_ccy = inst.get('quoteCcy', '')

                    # Search in symbol, base currency, and quote currency
                    if (query_lower in symbol.lower() or
                        query_lower in base_ccy.lower() or
                        query_lower in quote_ccy.lower() or
                        not query):  # If no query, return all

                        result = {
                            'symbol': symbol,
                            'ticker': symbol,
                            'full_name': f"{base_ccy}/{quote_ccy}" if base_ccy else symbol,
                            'description': f"{base_ccy}/{quote_ccy}" if base_ccy else symbol,
                            'exchange': 'OKX',
                            'type': 'crypto'
                        }
                        results.append(result)

                        if len(results) >= limit:
                            break

                # Sort results by relevance (exact matches first)
                if query:
                    results.sort(key=lambda x: (
                        not x['symbol'].lower().startswith(query_lower),  # Exact prefix match first
                        not query_lower in x['symbol'].lower(),  # Contains match second
                        x['symbol']  # Alphabetical order
                    ))

                return results
            else:
                return []

        except Exception as e:
            logger.exception(f"Error searching OKX symbols: {str(e)}")
            return []

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1D",
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        获取OKX K线数据（带缓存）

        Args:
            symbol: 交易对
            interval: 时间周期
            limit: 返回数据条数
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）

        Returns:
            K线数据列表
        """
        if not self.cache_manager:
            raise Exception("OKX cache manager not available")

        klines = await self.cache_manager.get_klines_cached(
            symbol=symbol,
            interval=interval,
            limit=limit,
            start_time=start_time,
            end_time=end_time
        )

        return klines

    async def get_orderbook(
        self,
        symbol: str,
        depth: int = 20
    ) -> Optional[Dict[str, Any]]:
        """
        获取OKX订单簿数据（带缓存）

        Args:
            symbol: 交易对
            depth: 深度档位

        Returns:
            订单簿数据
        """
        if not self.cache_manager:
            raise Exception("OKX cache manager not available")

        orderbook = await self.cache_manager.get_orderbook_cached(
            symbol=symbol,
            depth=depth
        )

        return orderbook

    async def get_recent_trades(
        self,
        symbol: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取OKX最近成交记录

        Args:
            symbol: 交易对
            limit: 返回数据条数

        Returns:
            成交记录列表
        """
        if not self.cache_manager:
            raise Exception("OKX cache manager not available")

        trades = await self.cache_manager.get_recent_trades_cached(
            symbol=symbol,
            limit=limit
        )

        return trades

    async def get_rate_limit_stats(
        self,
        endpoint: Optional[str] = None,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        获取OKX API速率限制统计

        Args:
            endpoint: 特定端点
            hours: 统计时间范围（小时）

        Returns:
            统计数据
        """
        stats = await self.rate_limiter.get_request_stats(endpoint, hours)
        return stats

    async def cleanup_old_data(self, days: int = 30) -> Optional[Dict[str, int]]:
        """
        清理OKX旧数据

        Args:
            days: 清理多少天前的数据

        Returns:
            清理结果
        """
        if not self.cache_manager:
            raise Exception("OKX cache manager not available")

        result = await self.cache_manager.cleanup_old_data(days)
        return result

    async def cleanup_api_logs(self, days: int = 7) -> int:
        """
        清理OKX API请求日志

        Args:
            days: 清理多少天前的API日志

        Returns:
            删除的记录数
        """
        deleted_count = await self.rate_limiter.cleanup_old_records(days)
        return deleted_count

    async def get_random_replay_point(
        self,
        symbol: Optional[str] = None,
        bars_count: Optional[int] = 150,
        interval: Optional[str] = '1D'
    ) -> Dict[str, Any]:
        """
        获取OKX随机回放起始点（智能版本）
        根据货币类型和周期动态调整历史数据范围

        Args:
            symbol: 交易对（可选）
            bars_count: K线数量
            interval: 时间周期

        Returns:
            回放起始点信息
        """
        # Validate bars_count
        if bars_count is None or bars_count <= 0:
            bars_count = 150

        # 没有指定symbol则随机选择OKX格式的交易对
        if not symbol:
            symbol = random.choice(self.okx_replay_symbols)

        # interval转秒数
        interval_seconds = self._interval_to_seconds(interval)

        # 判断是否为主流货币（支持history接口）
        is_top_currency = symbol in self.cache_manager.TOP_CURRENCIES

        # 获取该周期的数据保留期限（天）
        retention_days = self.cache_manager.DATA_RETENTION_LIMITS.get(interval, 30)

        # 主流货币可以使用更长的历史数据
        # 根据测试，history API至少支持90天的1H数据，保守估计为180天
        if is_top_currency:
            # 对于主流货币，将历史范围扩展到180天（约6个月）
            max_days = 180
            logger.info(f"[Replay] Top currency {symbol}: using extended history ({max_days} days)")
        else:
            # 非主流货币使用regular API的保留期限
            max_days = retention_days
            logger.info(f"[Replay] Regular currency {symbol}: using regular retention ({max_days} days)")

        current_time = int(time.time())

        # 计算最早和最晚的起始时间
        earliest_time = current_time - int(max_days * 86400)
        latest_time = current_time - (bars_count * interval_seconds)

        # 确保latest_time不早于earliest_time
        if latest_time < earliest_time:
            latest_time = earliest_time

        # 随机选取
        if earliest_time >= latest_time:
            random_start_time = earliest_time
        else:
            random_start_time = random.randint(earliest_time, latest_time)

        logger.info(f"[Replay] Generated random point: {symbol} at {datetime.fromtimestamp(random_start_time).isoformat()}")

        return {
            'symbol': symbol,
            'start_time': random_start_time,
            'bars_count': bars_count,
            'interval': interval,
            'data_source': 'history' if is_top_currency else 'regular'
        }

    @staticmethod
    def _interval_to_seconds(interval: str) -> int:
        """
        将时间周期字符串转换为秒数

        Args:
            interval: 时间周期字符串

        Returns:
            秒数
        """
        if not interval:
            return 3600  # Default 1 hour

        try:
            # 解析最后一个字符作为单位
            if interval[-1].isdigit():
                # 纯数字，默认为分钟
                return int(interval) * 60

            unit = interval[-1]
            value_str = interval[:-1]
            value = int(value_str) if value_str else 1

            if unit == 's':
                return value
            elif unit == 'm':
                return value * 60
            elif unit in ['h', 'H']:
                return value * 3600
            elif unit == 'D':
                return value * 86400
            elif unit == 'W':
                return value * 86400 * 7
            elif unit == 'M':
                return value * 86400 * 30
            else:
                # Unknown unit, default to minutes
                return value * 60
        except Exception:
            return 3600  # Default 1 hour
