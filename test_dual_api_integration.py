#!/usr/bin/env python3
"""
Test script for OKX dual-API integration (regular + history)
验证级联API逻辑和智能随机回放点生成
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
from okx_cache_manager import OKXCacheManager


async def test_cascade_api():
    """测试级联API逻辑"""
    logger.info("=" * 80)
    logger.info("TEST 1: Cascade API Logic")
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
    cache_manager = okx_service.cache_manager

    test_cases = [
        {
            'name': 'Top currency - Long history (1H, 90 days ago)',
            'symbol': 'BTC-USDT',
            'interval': '1H',
            'days_ago': 90,
            'expected_source': 'history',
            'expected_data': True
        },
        {
            'name': 'Top currency - Short history (1H, 7 days ago)',
            'symbol': 'ETH-USDT',
            'interval': '1H',
            'days_ago': 7,
            'expected_source': 'regular',
            'expected_data': True
        },
        {
            'name': 'Top currency - Very long history (1m, 5 months ago)',
            'symbol': 'BTC-USDT',
            'interval': '1m',
            'days_ago': 150,
            'expected_source': 'history',
            'expected_data': True  # History API should have data
        },
        {
            'name': 'Regular currency - 1H (should use regular API)',
            'symbol': 'SHIB-USDT',
            'interval': '1H',
            'days_ago': 60,
            'expected_source': 'regular',
            'expected_data': False  # Regular API won't have data this far back
        }
    ]

    results = []

    for test in test_cases:
        logger.info(f"\n{'-' * 80}")
        logger.info(f"Test: {test['name']}")
        logger.info(f"  Symbol: {test['symbol']}")
        logger.info(f"  Interval: {test['interval']}")
        logger.info(f"  Days ago: {test['days_ago']}")

        # Calculate timestamps
        current_time = datetime.now()
        target_time = current_time - timedelta(days=test['days_ago'])
        end_time_ms = int(target_time.timestamp() * 1000)
        start_time_ms = end_time_ms - (10 * 60 * 1000)  # 10 minutes before

        try:
            # Test the cascade method directly
            klines = await cache_manager._fetch_klines_cascade(
                symbol=test['symbol'],
                interval=test['interval'],
                limit=10,
                start_time=start_time_ms,
                end_time=end_time_ms
            )

            has_data = len(klines) > 0
            logger.info(f"  Result: {'✓ HAS DATA' if has_data else '✗ NO DATA'} ({len(klines)} candles)")

            if has_data != test['expected_data']:
                logger.warning(f"  ⚠ Unexpected result! Expected {test['expected_data']}, got {has_data}")

            results.append({
                'name': test['name'],
                'has_data': has_data,
                'count': len(klines),
                'expected': test['expected_data']
            })

        except Exception as e:
            logger.error(f"  ✗ Error: {e}")
            results.append({
                'name': test['name'],
                'has_data': False,
                'count': 0,
                'expected': test['expected_data']
            })

    # Summary
    logger.info(f"\n{'=' * 80}")
    logger.info("TEST 1 SUMMARY")
    logger.info(f"{'=' * 80}")

    for r in results:
        status = '✓' if r['has_data'] == r['expected'] else '✗'
        logger.info(f"{status} {r['name']}: {r['count']} candles (expected: {r['expected']})")

    return results


async def test_smart_replay():
    """测试智能随机回放点生成"""
    logger.info(f"\n{'=' * 80}")
    logger.info("TEST 2: Smart Random Replay Point Generation")
    logger.info(f"{'=' * 80}")

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

    test_cases = [
        {
            'symbol': 'BTC-USDT',
            'interval': '1H',
            'bars_count': 150,
            'expected_source': 'history'
        },
        {
            'symbol': 'ETH-USDT',
            'interval': '1D',
            'bars_count': 150,
            'expected_source': 'history'
        },
        {
            'symbol': 'SHIB-USDT',
            'interval': '1H',
            'bars_count': 150,
            'expected_source': 'regular'
        }
    ]

    logger.info(f"\nTop currencies in cache manager: {okx_service.cache_manager.TOP_CURRENCIES}")
    logger.info(f"Data retention limits: {okx_service.cache_manager.DATA_RETENTION_LIMITS}\n")

    for test in test_cases:
        logger.info(f"{'-' * 80}")
        logger.info(f"Test: {test['symbol']} / {test['interval']}")

        replay_point = await okx_service.get_random_replay_point(
            symbol=test['symbol'],
            bars_count=test['bars_count'],
            interval=test['interval']
        )

        logger.info(f"  Generated replay point:")
        logger.info(f"    Symbol: {replay_point['symbol']}")
        logger.info(f"    Start time: {replay_point['start_time']} ({datetime.fromtimestamp(replay_point['start_time']).isoformat()})")
        logger.info(f"    Bars count: {replay_point['bars_count']}")
        logger.info(f"    Data source: {replay_point.get('data_source', 'unknown')}")

        # Calculate how far back this is
        current_time = datetime.now()
        replay_time = datetime.fromtimestamp(replay_point['start_time'])
        days_back = (current_time - replay_time).days

        logger.info(f"    Days back: {days_back} days")

        if replay_point.get('data_source') == test['expected_source']:
            logger.info(f"  ✓ Data source matches expected: {test['expected_source']}")
        else:
            logger.warning(f"  ⚠ Data source mismatch! Expected: {test['expected_source']}, Got: {replay_point.get('data_source')}")

    logger.info(f"\n{'=' * 80}")
    logger.info("TEST 2 COMPLETE")
    logger.info(f"{'=' * 80}")


async def test_end_to_end():
    """端到端测试：生成随机回放点并获取数据"""
    logger.info(f"\n{'=' * 80}")
    logger.info("TEST 3: End-to-End Random Replay + Data Fetch")
    logger.info(f"{'=' * 80}")

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

    # Test with BTC (top currency) on 1H interval
    logger.info("\nGenerating random replay point for BTC-USDT 1H...")
    replay_point = await okx_service.get_random_replay_point(
        symbol='BTC-USDT',
        bars_count=150,
        interval='1H'
    )

    logger.info(f"Generated point: {datetime.fromtimestamp(replay_point['start_time']).isoformat()}")
    logger.info(f"Data source: {replay_point.get('data_source')}")

    # Now try to fetch data at that point
    start_time_ms = replay_point['start_time'] * 1000
    end_time_ms = start_time_ms + (150 * 3600 * 1000)  # 150 hours later

    logger.info(f"\nFetching K-line data...")
    logger.info(f"  Start: {datetime.fromtimestamp(start_time_ms/1000).isoformat()}")
    logger.info(f"  End: {datetime.fromtimestamp(end_time_ms/1000).isoformat()}")

    klines = await okx_service.get_klines(
        symbol=replay_point['symbol'],
        interval='1H',
        limit=150,
        start_time=start_time_ms,
        end_time=end_time_ms
    )

    logger.info(f"\nResult: Got {len(klines)} candles")

    if klines:
        first_candle = klines[-1] if klines else None  # Oldest candle
        last_candle = klines[0] if klines else None   # Newest candle

        if first_candle:
            logger.info(f"  First candle: {datetime.fromtimestamp(first_candle['open_time']/1000).isoformat()}")
            logger.info(f"    Open: {first_candle['open_price']}, Close: {first_candle['close_price']}")

        if last_candle:
            logger.info(f"  Last candle: {datetime.fromtimestamp(last_candle['open_time']/1000).isoformat()}")
            logger.info(f"    Open: {last_candle['open_price']}, Close: {last_candle['close_price']}")

        logger.info(f"\n✓ SUCCESS: Random replay point successfully generated data!")
    else:
        logger.error(f"\n✗ FAILURE: No data returned for random replay point!")

    logger.info(f"\n{'=' * 80}")
    logger.info("TEST 3 COMPLETE")
    logger.info(f"{'=' * 80}")


async def main():
    """运行所有测试"""
    logger.info("\n" + "=" * 80)
    logger.info("OKX DUAL-API INTEGRATION TEST SUITE")
    logger.info("=" * 80)

    try:
        # Test 1: Cascade API logic
        await test_cascade_api()

        # Test 2: Smart replay point generation
        await test_smart_replay()

        # Test 3: End-to-end test
        await test_end_to_end()

        logger.info("\n" + "=" * 80)
        logger.info("ALL TESTS COMPLETE")
        logger.info("=" * 80)

    except Exception as e:
        logger.exception(f"Test suite failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
