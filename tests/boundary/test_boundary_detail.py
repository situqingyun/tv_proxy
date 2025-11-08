#!/usr/bin/env python3
"""
边界附近K线详细分析
检查分段边界附近的K线情况
"""

import asyncio
import os
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

from okx_service import OKXService


def format_timestamp(ts_ms):
    """格式化时间戳（毫秒）"""
    return datetime.fromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


async def test_boundary_detail():
    """详细检查边界附近的K线"""
    logger.info("=" * 80)
    logger.info("边界附近K线详细分析")
    logger.info("=" * 80)

    # 初始化
    db_config = {
        'host': os.environ.get('DB_HOST', 'localhost'),
        'port': int(os.environ.get('DB_PORT', 5432)),
        'database': os.environ.get('DB_NAME', 'tv_proxy'),
        'user': os.environ.get('DB_USER', 'postgres'),
        'password': os.environ.get('DB_PASSWORD', 'password')
    }

    okx_config = {
        'api_key': os.environ.get('OKX_API_KEY', ''),
        'secret_key': os.environ.get('OKX_SECRET_KEY', ''),
        'passphrase': os.environ.get('OKX_PASSPHRASE', ''),
        'flag': os.environ.get('OKX_FLAG', '1')
    }

    okx_service = OKXService(db_config, okx_config)

    # 用户的范围
    visible_from_s = 1756980000
    visible_to_s = 1757768400
    start_time_ms = visible_from_s * 1000
    end_time_ms = visible_to_s * 1000

    # 计算当前的regular boundary
    import time
    current_time_ms = int(time.time() * 1000)
    regular_limit_days = 30
    regular_boundary_ms = current_time_ms - int(regular_limit_days * 86400 * 1000)

    logger.info(f"Regular边界: {format_timestamp(regular_boundary_ms)} ({regular_boundary_ms})")

    # 请求数据
    klines = await okx_service.get_klines(
        symbol='BTC-USDT',
        interval='1H',
        limit=500,
        start_time=start_time_ms,
        end_time=end_time_ms
    )

    # 排序
    klines_sorted = sorted(klines, key=lambda x: x['open_time'])

    # 找出边界附近的K线（边界前后各5根）
    logger.info(f"\n边界附近的K线 (±5根):")

    boundary_klines = []
    for i, k in enumerate(klines_sorted):
        # 检查是否在边界前后2小时内
        if abs(k['open_time'] - regular_boundary_ms) < 3600000 * 5:  # 5小时
            boundary_klines.append((i, k))

    if boundary_klines:
        logger.info(f"找到 {len(boundary_klines)} 根边界附近的K线:")
        for idx, k in boundary_klines:
            diff_hours = (k['open_time'] - regular_boundary_ms) / 3600000
            position = "边界前" if k['open_time'] < regular_boundary_ms else "边界后"
            logger.info(f"  [{idx:3d}] {format_timestamp(k['open_time'])} ({k['open_time']}) "
                       f"- {position} {abs(diff_hours):.2f}小时")

        # 检查相邻K线的间隔
        logger.info(f"\n边界附近K线的间隔检查:")
        for i in range(len(boundary_klines) - 1):
            idx1, k1 = boundary_klines[i]
            idx2, k2 = boundary_klines[i + 1]

            interval = k2['open_time'] - k1['open_time']
            expected = 3600000  # 1H

            if interval > expected * 1.5:
                logger.error(f"  ❌ Gap: [{idx1}] → [{idx2}]")
                logger.error(f"     {format_timestamp(k1['open_time'])} → {format_timestamp(k2['open_time'])}")
                logger.error(f"     间隔: {interval/1000:.0f}秒 (预期: {expected/1000:.0f}秒)")
                logger.error(f"     缺失: {int((interval - expected) / expected)} 根K线")
            else:
                logger.info(f"  ✓ [{idx1}] → [{idx2}]: {interval/1000:.0f}秒")

    # 检查是否有K线正好在边界上
    logger.info(f"\n检查边界对齐:")
    interval_ms = 3600000  # 1H
    aligned_boundary = (regular_boundary_ms // interval_ms) * interval_ms
    logger.info(f"  原始边界: {format_timestamp(regular_boundary_ms)}")
    logger.info(f"  对齐边界: {format_timestamp(aligned_boundary)}")
    logger.info(f"  偏移: {(regular_boundary_ms - aligned_boundary)/1000:.1f}秒")

    # 找出对齐边界前后的K线
    for k in klines_sorted:
        if abs(k['open_time'] - aligned_boundary) < interval_ms:
            diff = (k['open_time'] - aligned_boundary) / 1000
            logger.info(f"  K线: {format_timestamp(k['open_time'])} (偏移对齐边界: {diff:.0f}秒)")


if __name__ == "__main__":
    asyncio.run(test_boundary_detail())
