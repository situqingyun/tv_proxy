#!/usr/bin/env python3
"""
重现用户报告的实际gap问题
倒数第3根：9月8号11点
倒数第2根：9月13号12点
中间缺失约120根K线！
"""

import asyncio
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

from okx_service import OKXService


def format_time(ts_ms):
    """格式化时间戳"""
    return datetime.fromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')


async def test_actual_gap():
    """测试用户报告的实际gap"""
    logger.info("=" * 80)
    logger.info("重现用户报告的Gap问题")
    logger.info("=" * 80)

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

    # 用户的visible range
    visible_from_s = 1756980000
    visible_to_s = 1757768400

    logger.info(f"\n用户的visible range:")
    logger.info(f"  from: {visible_from_s} ({format_time(visible_from_s * 1000)})")
    logger.info(f"  to:   {visible_to_s} ({format_time(visible_to_s * 1000)})")

    # 请求数据 - 使用和前端一样的参数
    start_time_ms = visible_from_s * 1000
    end_time_ms = visible_to_s * 1000

    logger.info(f"\n请求K线数据...")
    klines = await okx_service.get_klines(
        symbol='BTC-USDT',
        interval='1H',
        limit=300,  # 前端通常用300
        start_time=start_time_ms,
        end_time=end_time_ms
    )

    logger.info(f"获取到 {len(klines)} 根K线")

    # 排序
    klines_sorted = sorted(klines, key=lambda x: x['open_time'])

    # 显示所有K线的时间
    logger.info(f"\n所有K线列表（只显示时间）:")
    for i, k in enumerate(klines_sorted):
        logger.info(f"  [{i:3d}] {format_time(k['open_time'])}")

    # 特别关注倒数3根
    logger.info(f"\n倒数3根K线详情:")
    if len(klines_sorted) >= 3:
        for i in range(-3, 0):
            k = klines_sorted[i]
            logger.info(f"  倒数第{abs(i)}根: {format_time(k['open_time'])} ({k['open_time']})")
            logger.info(f"    Price: O:{k['open_price']} H:{k['high_price']} L:{k['low_price']} C:{k['close_price']}")

    # 检查9月8号11点和9月13号12点
    sep8_11 = int(datetime(2025, 9, 8, 11, 0, 0).timestamp() * 1000)
    sep13_12 = int(datetime(2025, 9, 13, 12, 0, 0).timestamp() * 1000)

    logger.info(f"\n查找特定时间的K线:")
    logger.info(f"  目标1: 9月8号11点 ({sep8_11})")
    logger.info(f"  目标2: 9月13号12点 ({sep13_12})")

    found_sep8_11 = None
    found_sep13_12 = None
    for i, k in enumerate(klines_sorted):
        if k['open_time'] == sep8_11:
            found_sep8_11 = (i, k)
            logger.info(f"  ✓ 找到9月8号11点: index={i}")
        if k['open_time'] == sep13_12:
            found_sep13_12 = (i, k)
            logger.info(f"  ✓ 找到9月13号12点: index={i}")

    if found_sep8_11 and found_sep13_12:
        idx1, k1 = found_sep8_11
        idx2, k2 = found_sep13_12

        gap_bars = idx2 - idx1 - 1
        gap_hours = (k2['open_time'] - k1['open_time']) / 3600000 - 1

        logger.error(f"\n!!! 发现Gap !!!")
        logger.error(f"  9月8号11点: index={idx1}")
        logger.error(f"  9月13号12点: index={idx2}")
        logger.error(f"  中间缺失: {gap_bars} 根K线")
        logger.error(f"  时间跨度: {gap_hours:.0f} 小时")

        # 显示gap前后的K线
        logger.info(f"\nGap前后的K线:")
        for i in range(max(0, idx1 - 2), min(len(klines_sorted), idx2 + 3)):
            k = klines_sorted[i]
            marker = ""
            if i == idx1:
                marker = " ← Gap前"
            elif i == idx2:
                marker = " ← Gap后"
            logger.info(f"  [{i:3d}] {format_time(k['open_time'])}{marker}")

    # 分析gap的位置
    logger.info(f"\n分析数据缺口:")
    expected_interval = 3600000  # 1H
    gap_count = 0
    for i in range(len(klines_sorted) - 1):
        current = klines_sorted[i]
        next_k = klines_sorted[i + 1]
        actual_gap = next_k['open_time'] - current['open_time']

        if actual_gap > expected_interval * 1.5:
            gap_count += 1
            missing_bars = int((actual_gap - expected_interval) / expected_interval)
            logger.error(f"\nGap #{gap_count}:")
            logger.error(f"  位置: index {i} → {i+1}")
            logger.error(f"  从: {format_time(current['open_time'])}")
            logger.error(f"  到: {format_time(next_k['open_time'])}")
            logger.error(f"  缺失: {missing_bars} 根K线 ({actual_gap/3600000:.1f}小时)")


if __name__ == "__main__":
    asyncio.run(test_actual_gap())
