"""
OKX API Rate Limiter
管理OKX API的速率限制，避免触发限制并优化请求效率
"""

import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger(__name__)

@dataclass
class RateLimit:
    requests_per_second: int
    requests_per_minute: int = None
    requests_per_hour: int = None
    window_size: int = 2  # 窗口大小（秒）

class OKXRateLimiter:
    """OKX API速率限制管理器"""
    
    # OKX API端点的速率限制配置
    RATE_LIMITS = {
        # 市场数据API
        '/api/v5/market/candles': RateLimit(10, 600),  # K线数据
        '/api/v5/market/history-candles': RateLimit(10, 600),  # 历史K线
        '/api/v5/market/books': RateLimit(10, 600),  # 深度数据
        '/api/v5/market/trades': RateLimit(10, 600),  # 成交记录
        '/api/v5/market/ticker': RateLimit(20, 1200),  # 行情数据
        '/api/v5/market/tickers': RateLimit(20, 1200),  # 所有行情
        
        # 账户API
        '/api/v5/account/balance': RateLimit(5, 300),  # 账户余额
        '/api/v5/account/bills': RateLimit(5, 300),  # 账户流水
        
        # 交易API  
        '/api/v5/trade/order': RateLimit(60, 3600),  # 下单
        '/api/v5/trade/batch-orders': RateLimit(20, 1200),  # 批量下单
        '/api/v5/trade/cancel-order': RateLimit(60, 3600),  # 撤单
        
        # 默认限制
        'default': RateLimit(10, 600)
    }
    
    def __init__(self, db_config: Dict):
        self.db_config = db_config
        self.request_history: Dict[str, list] = defaultdict(list)
        self.lock = asyncio.Lock()
        
    def get_db_connection(self):
        """获取数据库连接"""
        return psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)
        
    def _get_rate_limit(self, endpoint: str) -> RateLimit:
        """获取端点的速率限制配置"""
        return self.RATE_LIMITS.get(endpoint, self.RATE_LIMITS['default'])
        
    def _clean_old_requests(self, endpoint: str, current_time: float):
        """清理过期的请求记录"""
        rate_limit = self._get_rate_limit(endpoint)
        cutoff_time = current_time - rate_limit.window_size
        
        self.request_history[endpoint] = [
            req_time for req_time in self.request_history[endpoint] 
            if req_time > cutoff_time
        ]
    
    async def can_make_request(self, endpoint: str) -> Tuple[bool, Optional[float]]:
        """
        检查是否可以发起请求
        返回: (是否可以请求, 需要等待的秒数)
        """
        async with self.lock:
            current_time = time.time()
            rate_limit = self._get_rate_limit(endpoint)
            
            # 清理过期请求记录
            self._clean_old_requests(endpoint, current_time)
            
            # 检查当前窗口内的请求数量
            recent_requests = len(self.request_history[endpoint])
            
            if recent_requests < rate_limit.requests_per_second:
                return True, None
            
            # 计算需要等待的时间
            if self.request_history[endpoint]:
                oldest_request = min(self.request_history[endpoint])
                wait_time = rate_limit.window_size - (current_time - oldest_request)
                return False, max(0, wait_time)
            
            return False, rate_limit.window_size
    
    async def record_request(self, endpoint: str, response_status: int, 
                           response_time_ms: int, rate_limit_remaining: Optional[int] = None):
        """记录API请求"""
        async with self.lock:
            current_time = time.time()
            
            # 记录到内存
            self.request_history[endpoint].append(current_time)
            
            # 记录到数据库
            try:
                conn = self.get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute('''
                INSERT INTO okx_api_requests 
                (endpoint, response_status, rate_limit_remaining, response_time_ms)
                VALUES (%s, %s, %s, %s)
                ''', (endpoint, response_status, rate_limit_remaining, response_time_ms))
                
                conn.commit()
                conn.close()
                
            except Exception as e:
                logger.error(f"Failed to record API request: {e}")
    
    async def wait_if_needed(self, endpoint: str) -> bool:
        """如果需要等待则等待，返回是否进行了等待"""
        can_request, wait_time = await self.can_make_request(endpoint)
        
        if not can_request and wait_time:
            logger.info(f"Rate limit reached for {endpoint}, waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)
            return True
            
        return False
    
    async def get_request_stats(self, endpoint: str = None, 
                              hours: int = 24) -> Dict:
        """获取API请求统计数据"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            since_time = datetime.now() - timedelta(hours=hours)
            
            where_clause = "WHERE request_time >= %s"
            params = [since_time]
            
            if endpoint:
                where_clause += " AND endpoint = %s"
                params.append(endpoint)
            
            cursor.execute(f'''
            SELECT 
                endpoint,
                COUNT(*) as total_requests,
                AVG(response_time_ms) as avg_response_time,
                COUNT(CASE WHEN response_status >= 400 THEN 1 END) as error_count,
                MIN(rate_limit_remaining) as min_rate_limit_remaining
            FROM okx_api_requests
            {where_clause}
            GROUP BY endpoint
            ORDER BY total_requests DESC
            ''', params)
            
            stats = cursor.fetchall()
            conn.close()
            
            return {
                'period_hours': hours,
                'stats': [dict(row) for row in stats]
            }
            
        except Exception as e:
            logger.error(f"Failed to get request stats: {e}")
            return {'error': str(e)}
    
    async def cleanup_old_records(self, days: int = 7):
        """清理旧的请求记录"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            cutoff_date = datetime.now() - timedelta(days=days)
            
            cursor.execute('''
            DELETE FROM okx_api_requests 
            WHERE request_time < %s
            ''', (cutoff_date,))
            
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            logger.info(f"Cleaned up {deleted_count} old API request records")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old records: {e}")
            return 0

# 单例实例
_rate_limiter = None

def get_rate_limiter(db_config: Dict) -> OKXRateLimiter:
    """获取速率限制器单例"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = OKXRateLimiter(db_config)
    return _rate_limiter