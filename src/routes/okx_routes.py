"""
OKX相关的API路由
包含OKX数据源的所有HTTP端点
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
import logging
import time
from datetime import datetime

from services.okx_service import OKXService

logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(prefix="/api/okx", tags=["OKX"])


def create_okx_router(okx_service: OKXService) -> APIRouter:
    """创建并配置OKX路由器"""

    @router.get('/instruments')
    async def get_okx_instruments(
        inst_type: str = Query("SPOT", description="Instrument type: SPOT, SWAP, FUTURES, OPTION"),
        uly: Optional[str] = Query(None, description="Underlying, e.g., BTC-USD"),
        inst_family: Optional[str] = Query(None, description="Instrument family"),
        inst_id: Optional[str] = Query(None, description="Instrument ID")
    ):
        """获取OKX交易对列表"""
        try:
            instruments = await okx_service.get_instruments(
                inst_type=inst_type,
                uly=uly,
                inst_family=inst_family,
                inst_id=inst_id
            )

            return {
                'status': 'ok',
                'data': instruments,
                'count': len(instruments)
            }
        except Exception as e:
            logger.exception(f"Error getting OKX instruments: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting OKX instruments: {str(e)}")

    @router.get('/symbol-search')
    async def search_okx_symbols(
        query: str = Query("", description="Search query"),
        inst_type: str = Query("SPOT", description="Instrument type: SPOT, SWAP, FUTURES, OPTION"),
        limit: int = Query(50, ge=1, le=200, description="Maximum results to return")
    ):
        """搜索OKX交易对（带缓存）"""
        try:
            results = await okx_service.search_symbols(
                query=query,
                inst_type=inst_type,
                limit=limit
            )

            return {
                'status': 'ok',
                'data': results,
                'count': len(results)
            }
        except Exception as e:
            logger.exception(f"Error searching OKX symbols: {str(e)}")
            return {
                'status': 'error',
                'message': str(e),
                'data': []
            }

    @router.get('/klines')
    async def get_okx_klines(
        symbol: str = Query(..., description="交易对，如BTC-USDT"),
        interval: str = Query("1D", description="时间周期，如1m,5m,1H,1D"),
        start_time: Optional[int] = Query(None, description="开始时间戳（毫秒）"),
        end_time: Optional[int] = Query(None, description="结束时间戳（毫秒）")
    ):
        """获取OKX K线数据（带缓存）"""
        # --- 循环问题调试日志 ---
        start_dt = datetime.fromtimestamp(start_time / 1000).isoformat() if start_time else "N/A"
        end_dt = datetime.fromtimestamp(end_time / 1000).isoformat() if end_time else "N/A"
        logger.info(
            f"[Klines Request] Symbol: {symbol}, Interval: {interval}, "
            f"Request Range: {start_dt} -> {end_dt}"
        )
        # --- 结束调试日志 ---

        try:
            klines = await okx_service.get_klines(
                symbol=symbol,
                interval=interval,
                start_time=start_time,
                end_time=end_time
            )

            # --- 循环问题调试日志 ---
            if klines:
                actual_start_dt = datetime.fromtimestamp(klines[0]['open_time'] / 1000).isoformat()
                actual_end_dt = datetime.fromtimestamp(klines[-1]['open_time'] / 1000).isoformat()
                logger.info(
                    f"[Klines Response] Returned {len(klines)} bars. "
                    f"Actual Range: {actual_start_dt} -> {actual_end_dt}"
                )
            else:
                logger.info("[Klines Response] Returned 0 bars (No data).")
            # --- 结束调试日志 ---

            # 构建响应
            response = {
                'status': 'ok',
                'data': klines,
                'count': len(klines)
            }

            # 检查是否已到达历史边界（无更早数据）
            cache_manager = okx_service.cache_manager
            if hasattr(cache_manager, '_no_earlier_data') and cache_manager._no_earlier_data:
                # 告诉前端没有更早的数据了
                response['noData'] = True
                logger.info(f"[API Response] Returning {len(klines)} klines with noData=True flag")

            # 如果完全没有数据，也标记 noData
            if len(klines) == 0:
                response['noData'] = True
                logger.info(f"[API Response] No klines available, returning noData=True")

            # --- 循环问题调试日志 ---
            final_no_data_status = response.get('noData', False)
            logger.info(f"[Klines Final] Final noData flag status: {final_no_data_status}")
            # --- 结束调试日志 ---

            return response

        except Exception as e:
            logger.exception(f"Error getting OKX klines: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting OKX klines: {str(e)}")

    @router.get('/orderbook')
    async def get_okx_orderbook(
        symbol: str = Query(..., description="交易对，如BTC-USDT"),
        depth: int = Query(20, ge=1, le=50, description="深度档位")
    ):
        """获取OKX订单簿数据（带缓存）"""
        try:
            orderbook = await okx_service.get_orderbook(
                symbol=symbol,
                depth=depth
            )

            if orderbook:
                return {
                    'status': 'ok',
                    'data': orderbook
                }
            else:
                raise HTTPException(status_code=404, detail="Orderbook data not available")
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error getting OKX orderbook: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting OKX orderbook: {str(e)}")

    @router.get('/trades')
    async def get_okx_trades(
        symbol: str = Query(..., description="交易对，如BTC-USDT"),
        limit: int = Query(100, ge=1, le=500, description="返回数据条数")
    ):
        """获取OKX最近成交记录"""
        try:
            trades = await okx_service.get_recent_trades(
                symbol=symbol,
                limit=limit
            )

            # 转换Decimal为float以便JSON序列化
            trades_data = []
            for trade in trades:
                trade_dict = dict(trade)
                trade_dict['price'] = float(trade_dict['price'])
                trade_dict['size'] = float(trade_dict['size'])
                trades_data.append(trade_dict)

            return {
                'status': 'ok',
                'data': trades_data,
                'count': len(trades_data)
            }
        except Exception as e:
            logger.exception(f"Error getting OKX trades: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting OKX trades: {str(e)}")

    @router.get('/rate-limit-stats')
    async def get_okx_rate_limit_stats(
        endpoint: Optional[str] = Query(None, description="特定端点"),
        hours: int = Query(24, ge=1, le=168, description="统计时间范围（小时）")
    ):
        """获取OKX API速率限制统计"""
        try:
            stats = await okx_service.get_rate_limit_stats(endpoint, hours)

            return {
                'status': 'ok',
                'data': stats
            }
        except Exception as e:
            logger.exception(f"Error getting rate limit stats: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting rate limit stats: {str(e)}")

    @router.post('/cleanup')
    async def cleanup_okx_data(
        days: int = Query(30, ge=1, le=365, description="清理多少天前的数据")
    ):
        """清理OKX旧数据"""
        try:
            result = await okx_service.cleanup_old_data(days)

            if result:
                return {
                    'status': 'ok',
                    'message': f'Successfully cleaned up data older than {days} days',
                    'data': result
                }
            else:
                raise HTTPException(status_code=500, detail="Cleanup failed")
        except Exception as e:
            logger.exception(f"Error cleaning up OKX data: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error cleaning up OKX data: {str(e)}")

    @router.post('/cleanup-api-logs')
    async def cleanup_okx_api_logs(
        days: int = Query(7, ge=1, le=30, description="清理多少天前的API日志")
    ):
        """清理OKX API请求日志"""
        try:
            deleted_count = await okx_service.cleanup_api_logs(days)

            return {
                'status': 'ok',
                'message': f'Successfully cleaned up {deleted_count} API log records older than {days} days',
                'deleted_count': deleted_count
            }
        except Exception as e:
            logger.exception(f"Error cleaning up API logs: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error cleaning up API logs: {str(e)}")

    @router.get('/replay/random')
    async def get_okx_random_replay_point(
        symbol: Optional[str] = Query(None),
        bars_count: Optional[int] = Query(150),
        interval: Optional[str] = Query('1D')
    ):
        """获取OKX随机回放起始点（使用OKX格式的交易对）"""
        try:
            replay_point = await okx_service.get_random_replay_point(
                symbol=symbol,
                bars_count=bars_count,
                interval=interval
            )

            return {
                'status': 'ok',
                'data': replay_point
            }
        except Exception as e:
            logger.exception(f"Error generating OKX random replay point: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error generating OKX random replay point: {str(e)}")

    return router
