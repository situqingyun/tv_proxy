#!/usr/bin/env python3
"""
边界Gap诊断测试
分析用户报告的倒数第2、第3根K线之间的gap问题

用户报告的visible range:
- from: 1756980000 (秒)
- to: 1757768400 (秒)
"""

import asyncio
import os
import sys
import logging
from datetime import datetime, timedelta

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

from okx_service import OKXService


def format_timestamp(ts_ms):
    """格式化时间戳（毫秒）为可读字符串"""
    return datetime.fromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')


def analyze_gap(klines, interval='1H'):
    """
    分析K线数据中的gap

    Args:
        klines: K线数据列表
        interval: 时间周期

    Returns:
        gap信息列表
    """
    if not klines:
        return []

    # 按时间排序
    klines_sorted = sorted(klines, key=lambda x: x['open_time'])

    # 计算interval的毫秒数
    interval_map = {
        '1m': 60 * 1000,
        '3m': 3 * 60 * 1000,
        '5m': 5 * 60 * 1000,
        '15m': 15 * 60 * 1000,
        '30m': 30 * 60 * 1000,
        '1H': 60 * 60 * 1000,
        '2H': 2 * 60 * 60 * 1000,
        '4H': 4 * 60 * 60 * 1000,
        '1D': 24 * 60 * 60 * 1000
    }
    expected_interval_ms = interval_map.get(interval, 60 * 60 * 1000)

    gaps = []

    for i in range(len(klines_sorted) - 1):
        current = klines_sorted[i]
        next_k = klines_sorted[i + 1]

        actual_gap = next_k['open_time'] - current['open_time']

        # 如果gap大于预期间隔的1.5倍，认为是gap
        if actual_gap > expected_interval_ms * 1.5:
            gap_info = {
                'index': i,
                'from_time': current['open_time'],
                'to_time': next_k['open_time'],
                'from_str': format_timestamp(current['open_time']),
                'to_str': format_timestamp(next_k['open_time']),
                'gap_ms': actual_gap,
                'expected_ms': expected_interval_ms,
                'missing_bars': int((actual_gap - expected_interval_ms) / expected_interval_ms)
            }
            gaps.append(gap_info)

    return gaps


async def test_boundary_gap():
    """测试边界gap问题"""
    logger.info("=" * 80)
    logger.info("边界Gap诊断测试")
    logger.info("=" * 80)

    # 用户报告的visible range（秒）
    visible_from_s = 1756980000
    visible_to_s = 1757768400

    logger.info(f"\n用户提供的visible range (秒):")
    logger.info(f"  from: {visible_from_s} = {datetime.fromtimestamp(visible_from_s)}")
    logger.info(f"  to:   {visible_to_s} = {datetime.fromtimestamp(visible_to_s)}")
    logger.info(f"  span: {(visible_to_s - visible_from_s) / 86400:.2f} 天")

    # 转换为毫秒
    start_time_ms = visible_from_s * 1000
    end_time_ms = visible_to_s * 1000

    # 初始化服务
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

    # 猜测interval（基于时间跨度）
    # 9.125天 ≈ 219小时，如果是1H周期大约219根K线
    interval = '1H'

    logger.info(f"\n假设interval: {interval}")

    # 计算当前时间的regular boundary
    import time
    current_time_ms = int(time.time() * 1000)
    regular_limit_days = 30  # 1H的保留期限
    regular_boundary_ms = current_time_ms - int(regular_limit_days * 86400 * 1000)

    logger.info(f"\n分段边界计算:")
    logger.info(f"  当前时间:         {format_timestamp(current_time_ms)} ({current_time_ms})")
    logger.info(f"  Regular保留期限:  {regular_limit_days} 天")
    logger.info(f"  Regular边界:      {format_timestamp(regular_boundary_ms)} ({regular_boundary_ms})")

    # 判断请求范围与边界的关系
    logger.info(f"\n请求范围与边界关系:")
    logger.info(f"  请求开始:  {format_timestamp(start_time_ms)}")
    logger.info(f"  边界时间:  {format_timestamp(regular_boundary_ms)}")
    logger.info(f"  请求结束:  {format_timestamp(end_time_ms)}")

    if start_time_ms < regular_boundary_ms < end_time_ms:
        logger.info(f"  ✓ 边界在请求范围内，会触发分段!")
        logger.info(f"    Segment 1 (History): [{format_timestamp(start_time_ms)}, {format_timestamp(regular_boundary_ms)})")
        logger.info(f"    Segment 2 (Regular): [{format_timestamp(regular_boundary_ms)}, {format_timestamp(end_time_ms)}]")

        # 检查边界是否对齐到K线间隔
        interval_ms = 60 * 60 * 1000  # 1H
        aligned_boundary = (regular_boundary_ms // interval_ms) * interval_ms
        logger.info(f"\n边界对齐检查:")
        logger.info(f"  原始边界:  {format_timestamp(regular_boundary_ms)}")
        logger.info(f"  对齐边界:  {format_timestamp(aligned_boundary)}")
        logger.info(f"  偏移量:    {(regular_boundary_ms - aligned_boundary) / 1000:.1f} 秒")

        if regular_boundary_ms != aligned_boundary:
            logger.warning(f"  ⚠ 边界未对齐到K线间隔！这可能导致gap")
    elif start_time_ms >= regular_boundary_ms:
        logger.info(f"  ✓ 请求范围在Regular API范围内，不会分段")
    else:
        logger.info(f"  ✓ 请求范围完全在History API范围内")

    # 请求实际数据
    logger.info(f"\n开始请求K线数据...")
    logger.info(f"  Symbol: BTC-USDT")
    logger.info(f"  Interval: {interval}")
    logger.info(f"  Limit: 500")

    klines = await okx_service.get_klines(
        symbol='BTC-USDT',
        interval=interval,
        limit=500,
        start_time=start_time_ms,
        end_time=end_time_ms
    )

    logger.info(f"\n请求结果:")
    logger.info(f"  获取到 {len(klines)} 根K线")

    if not klines:
        logger.error("❌ 没有获取到数据!")
        return

    # 排序K线
    klines_sorted = sorted(klines, key=lambda x: x['open_time'])

    # 显示前5根和后5根K线
    logger.info(f"\n前5根K线:")
    for i, k in enumerate(klines_sorted[:5]):
        logger.info(f"  [{i}] {format_timestamp(k['open_time'])} - Close: {k['close_price']}")

    logger.info(f"\n后5根K线:")
    total = len(klines_sorted)
    for i, k in enumerate(klines_sorted[-5:]):
        actual_index = total - 5 + i
        logger.info(f"  [{actual_index}] {format_timestamp(k['open_time'])} - Close: {k['close_price']}")

    # 分析gap
    logger.info(f"\n检查数据连续性...")
    gaps = analyze_gap(klines_sorted, interval)

    if gaps:
        logger.error(f"\n❌ 发现 {len(gaps)} 个gap:")
        for gap in gaps:
            logger.error(f"  Gap位置: 第{gap['index']}根和第{gap['index']+1}根之间")
            logger.error(f"    从: {gap['from_str']} ({gap['from_time']})")
            logger.error(f"    到: {gap['to_str']} ({gap['to_time']})")
            logger.error(f"    实际间隔: {gap['gap_ms']/1000:.0f} 秒")
            logger.error(f"    预期间隔: {gap['expected_ms']/1000:.0f} 秒")
            logger.error(f"    缺失K线: {gap['missing_bars']} 根")

            # 检查gap是否在边界附近
            if abs(gap['from_time'] - regular_boundary_ms) < 3600000 * 2:  # 2小时内
                logger.error(f"    ⚠️ 此gap在regular_boundary附近！")
                logger.error(f"       边界时间: {format_timestamp(regular_boundary_ms)}")
                logger.error(f"       gap开始:   {gap['from_str']}")
                logger.error(f"       gap结束:   {gap['to_str']}")

            # 显示gap前后的K线
            logger.info(f"\n  Gap前后的K线详情:")
            idx = gap['index']
            for j in range(max(0, idx - 2), min(len(klines_sorted), idx + 4)):
                k = klines_sorted[j]
                marker = ""
                if j == idx:
                    marker = " ← gap前"
                elif j == idx + 1:
                    marker = " ← gap后"
                logger.info(f"    [{j}] {format_timestamp(k['open_time'])} - {k['close_price']}{marker}")
    else:
        logger.info(f"\n✓ 数据连续，无gap!")

    # 特别检查倒数第2、第3根
    logger.info(f"\n特别检查：倒数第2、第3根K线")
    if len(klines_sorted) >= 3:
        k3 = klines_sorted[-3]  # 倒数第3根
        k2 = klines_sorted[-2]  # 倒数第2根
        k1 = klines_sorted[-1]  # 倒数第1根

        logger.info(f"  倒数第3根: {format_timestamp(k3['open_time'])} ({k3['open_time']})")
        logger.info(f"  倒数第2根: {format_timestamp(k2['open_time'])} ({k2['open_time']})")
        logger.info(f"  倒数第1根: {format_timestamp(k1['open_time'])} ({k1['open_time']})")

        gap_3_to_2 = k2['open_time'] - k3['open_time']
        gap_2_to_1 = k1['open_time'] - k2['open_time']
        expected_gap = 3600000  # 1H

        logger.info(f"\n  间隔分析:")
        logger.info(f"    第3→第2: {gap_3_to_2/1000:.0f} 秒 (预期: {expected_gap/1000:.0f} 秒)")
        logger.info(f"    第2→第1: {gap_2_to_1/1000:.0f} 秒 (预期: {expected_gap/1000:.0f} 秒)")

        if gap_3_to_2 > expected_gap * 1.5:
            logger.error(f"  ❌ 倒数第3根和第2根之间有gap!")
            missing = int((gap_3_to_2 - expected_gap) / expected_gap)
            logger.error(f"     缺失 {missing} 根K线")
        else:
            logger.info(f"  ✓ 倒数第3根和第2根之间正常")


async def main():
    try:
        await test_boundary_gap()
    except Exception as e:
        logger.exception(f"测试过程中出错: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
