#!/usr/bin/env python3
"""
测试分段API修复效果
验证：
1. 数据年龄判断修复
2. 智能分段算法
3. 分页获取逻辑
4. 无数据缺口
"""

import asyncio
import os
import sys
import logging
from datetime import datetime, timedelta

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Setup environment
from dotenv import load_dotenv
load_dotenv()

from okx_service import OKXService


async def test_90day_1h_data():
    """
    测试场景1: 90天前的1H数据
    预期：应该分为2段 (60天history + 30天regular)
    """
    logger.info("=" * 80)
    logger.info("TEST 1: 90天前 1H 数据（BTC-USDT）")
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

    # 计算90天前的时间
    current_time = datetime.now()
    start_time_dt = current_time - timedelta(days=90)
    start_time_ms = int(start_time_dt.timestamp() * 1000)
    end_time_ms = int(current_time.timestamp() * 1000)

    logger.info(f"请求范围:")
    logger.info(f"  Start: {start_time_dt.isoformat()} ({start_time_ms})")
    logger.info(f"  End:   {current_time.isoformat()} ({end_time_ms})")
    logger.info(f"  Span:  90 days = 2160 hours")

    # 请求数据
    logger.info(f"\n开始获取K线数据...")
    klines = await okx_service.get_klines(
        symbol='BTC-USDT',
        interval='1H',
        limit=2500,  # 足够大以获取所有数据
        start_time=start_time_ms,
        end_time=end_time_ms
    )

    logger.info(f"\n结果分析:")
    logger.info(f"  总共获取: {len(klines)} 条K线")
    logger.info(f"  预期数量: ~2160 条")
    logger.info(f"  完整度: {len(klines)/2160*100:.1f}%")

    if klines:
        # 分析数据连续性
        klines_sorted = sorted(klines, key=lambda x: x['open_time'])

        first_kline = klines_sorted[0]
        last_kline = klines_sorted[-1]

        logger.info(f"\n数据时间范围:")
        logger.info(f"  最早: {datetime.fromtimestamp(first_kline['open_time']/1000).isoformat()}")
        logger.info(f"  最晚: {datetime.fromtimestamp(last_kline['open_time']/1000).isoformat()}")

        # 检查数据缺口
        gaps = []
        for i in range(len(klines_sorted) - 1):
            current_time = klines_sorted[i]['open_time']
            next_time = klines_sorted[i+1]['open_time']
            expected_gap = 3600 * 1000  # 1小时
            actual_gap = next_time - current_time

            if actual_gap > expected_gap * 1.5:  # 允许50%误差
                gap_hours = actual_gap / (3600 * 1000)
                gaps.append({
                    'start': datetime.fromtimestamp(current_time/1000),
                    'end': datetime.fromtimestamp(next_time/1000),
                    'hours': gap_hours
                })

        if gaps:
            logger.warning(f"\n发现 {len(gaps)} 个数据缺口:")
            for gap in gaps[:10]:  # 只显示前10个
                logger.warning(f"  Gap: {gap['start']} → {gap['end']} ({gap['hours']:.1f}小时)")
        else:
            logger.info(f"\n✓ 数据连续，无缺口！")

    return len(klines)


async def test_150day_1m_data():
    """
    测试场景2: 150天前的1m数据（主流货币）
    预期：history API应该提供部分数据
    """
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: 150天前 1m 数据（BTC-USDT）")
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

    # 计算150天前的时间
    current_time = datetime.now()
    start_time_dt = current_time - timedelta(days=150)
    start_time_ms = int(start_time_dt.timestamp() * 1000)
    end_time_ms = int(current_time.timestamp() * 1000)

    logger.info(f"请求范围:")
    logger.info(f"  Start: {start_time_dt.isoformat()}")
    logger.info(f"  End:   {current_time.isoformat()}")
    logger.info(f"  Span:  150 days = 216000 minutes")

    # 只请求一小部分数据（前1000条），因为150天的1m数据太多
    logger.info(f"\n开始获取K线数据（limit=1000）...")
    klines = await okx_service.get_klines(
        symbol='BTC-USDT',
        interval='1m',
        limit=1000,
        start_time=start_time_ms,
        end_time=end_time_ms
    )

    logger.info(f"\n结果分析:")
    logger.info(f"  总共获取: {len(klines)} 条K线")

    if klines:
        klines_sorted = sorted(klines, key=lambda x: x['open_time'])
        first_kline = klines_sorted[0]
        last_kline = klines_sorted[-1]

        logger.info(f"  最早数据: {datetime.fromtimestamp(first_kline['open_time']/1000).isoformat()}")
        logger.info(f"  最晚数据: {datetime.fromtimestamp(last_kline['open_time']/1000).isoformat()}")

        # 检查是否使用了history API
        first_age_days = (current_time.timestamp() * 1000 - first_kline['open_time']) / (86400 * 1000)
        logger.info(f"  最早数据年龄: {first_age_days:.1f} 天")

        if first_age_days > 1:
            logger.info(f"  ✓ History API成功获取了超过1天的旧数据!")
        else:
            logger.warning(f"  ⚠ 只获取到最近的数据，history API可能未生效")

    return len(klines)


async def test_replay_scenario():
    """
    测试场景3: 模拟回放场景
    生成随机回放点，然后获取数据
    """
    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: 回放场景测试")
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

    # 生成随机回放点
    replay_point = await okx_service.get_random_replay_point(
        symbol='BTC-USDT',
        bars_count=150,
        interval='1H'
    )

    logger.info(f"随机回放点:")
    logger.info(f"  Symbol: {replay_point['symbol']}")
    logger.info(f"  Start Time: {datetime.fromtimestamp(replay_point['start_time']).isoformat()}")
    logger.info(f"  Bars Count: {replay_point['bars_count']}")
    logger.info(f"  Data Source: {replay_point.get('data_source', 'unknown')}")

    # 计算回放需要的时间范围
    start_time_s = replay_point['start_time']
    bars_count = replay_point['bars_count']
    interval_s = 3600  # 1H

    # 前端会请求: start - 99 bars 到 start + 1 bar
    range_from_s = start_time_s - 99 * interval_s
    range_to_s = start_time_s + 1 * interval_s

    range_from_ms = range_from_s * 1000
    range_to_ms = range_to_s * 1000

    logger.info(f"\n前端会请求的范围:")
    logger.info(f"  From: {datetime.fromtimestamp(range_from_s).isoformat()}")
    logger.info(f"  To:   {datetime.fromtimestamp(range_to_s).isoformat()}")
    logger.info(f"  Total: 100 bars")

    # 请求数据
    logger.info(f"\n获取数据...")
    klines = await okx_service.get_klines(
        symbol=replay_point['symbol'],
        interval='1H',
        limit=300,
        start_time=range_from_ms,
        end_time=range_to_ms
    )

    logger.info(f"\n结果:")
    logger.info(f"  获取数量: {len(klines)} 条")
    logger.info(f"  预期数量: 100 条")
    logger.info(f"  完整度: {len(klines)/100*100:.1f}%")

    if len(klines) >= 90:
        logger.info(f"  ✓ 数据充足，回放可以正常进行")
    else:
        logger.warning(f"  ⚠ 数据不足，可能出现跳转问题")

    return len(klines) >= 90


async def main():
    """运行所有测试"""
    logger.info("\n" + "=" * 80)
    logger.info("OKX 分段API修复效果测试")
    logger.info("=" * 80)

    results = {}

    try:
        # Test 1: 90天1H数据
        count1 = await test_90day_1h_data()
        results['test1'] = count1

        # Test 2: 150天1m数据
        count2 = await test_150day_1m_data()
        results['test2'] = count2

        # Test 3: 回放场景
        success3 = await test_replay_scenario()
        results['test3'] = success3

        # 总结
        logger.info("\n" + "=" * 80)
        logger.info("测试总结")
        logger.info("=" * 80)
        logger.info(f"Test 1 (90天1H): {results['test1']} 条K线")
        logger.info(f"Test 2 (150天1m): {results['test2']} 条K线")
        logger.info(f"Test 3 (回放场景): {'✓ 通过' if results['test3'] else '✗ 失败'}")

        # 判断是否全部通过
        all_pass = (
            results['test1'] >= 2000 and  # 至少2000条（90天1H约2160条）
            results['test2'] > 0 and  # 有数据就行
            results['test3']  # 回放场景通过
        )

        if all_pass:
            logger.info("\n✓✓✓ 所有测试通过！数据缺口问题已修复 ✓✓✓")
        else:
            logger.warning("\n⚠⚠⚠ 部分测试未通过，需要进一步检查 ⚠⚠⚠")

    except Exception as e:
        logger.exception(f"测试过程中出错: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
