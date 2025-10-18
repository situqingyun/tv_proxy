#!/usr/bin/env python3
"""
Test OKX history candlesticks API vs regular candlesticks API
Compare data availability between the two endpoints
"""

import okx.MarketData as Market
from datetime import datetime, timedelta
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_comparison():
    """Compare get_candlesticks vs get_history_candlesticks"""

    market_api = Market.MarketAPI('', '', '', False, '0')

    logger.info("=" * 80)
    logger.info("OKX API Comparison: get_candlesticks vs get_history_candlesticks")
    logger.info("=" * 80)

    current_time = datetime.now()
    logger.info(f"Current time: {current_time.isoformat()}\n")

    # Test cases for different time ranges and intervals
    test_cases = [
        {
            "name": "1m - 5 months ago (problematic range)",
            "interval": "1m",
            "days_ago": 150,
        },
        {
            "name": "1m - 1 day ago",
            "interval": "1m",
            "days_ago": 1,
        },
        {
            "name": "1m - 12 hours ago",
            "interval": "1m",
            "days_ago": 0.5,
        },
        {
            "name": "1H - 90 days ago",
            "interval": "1H",
            "days_ago": 90,
        },
        {
            "name": "1H - 60 days ago",
            "interval": "1H",
            "days_ago": 60,
        },
        {
            "name": "1H - 30 days ago",
            "interval": "1H",
            "days_ago": 30,
        },
        {
            "name": "1D - 365 days ago (1 year)",
            "interval": "1D",
            "days_ago": 365,
        },
        {
            "name": "1D - 730 days ago (2 years)",
            "interval": "1D",
            "days_ago": 730,
        },
    ]

    results = []

    for test in test_cases:
        logger.info("-" * 80)
        logger.info(f"Test: {test['name']}")
        logger.info(f"Interval: {test['interval']}, Days ago: {test['days_ago']}")

        target_time = current_time - timedelta(days=test['days_ago'])
        timestamp_ms = int(target_time.timestamp() * 1000)

        logger.info(f"Target time: {target_time.isoformat()} ({timestamp_ms})")

        params = {
            'instId': 'BTC-USDT',
            'bar': test['interval'],
            'limit': '10',
            'after': str(timestamp_ms)
        }

        # Test 1: get_candlesticks (regular API)
        logger.info("\n[Regular API] get_candlesticks...")
        try:
            response1 = market_api.get_candlesticks(**params)
            regular_count = len(response1.get('data', []))
            regular_status = "✓ HAS DATA" if regular_count > 0 else "✗ NO DATA"
            logger.info(f"  Result: {regular_status} ({regular_count} candles)")

            if regular_count > 0:
                first_time = int(response1['data'][0][0])
                logger.info(f"  First candle: {datetime.fromtimestamp(first_time/1000).isoformat()}")

            time.sleep(0.1)  # Rate limit
        except Exception as e:
            logger.error(f"  Error: {str(e)}")
            regular_count = 0
            regular_status = "✗ ERROR"

        # Test 2: get_history_candlesticks (history API)
        logger.info("\n[History API] get_history_candlesticks...")
        try:
            response2 = market_api.get_history_candlesticks(**params)
            history_count = len(response2.get('data', []))
            history_status = "✓ HAS DATA" if history_count > 0 else "✗ NO DATA"
            logger.info(f"  Result: {history_status} ({history_count} candles)")

            if history_count > 0:
                first_time = int(response2['data'][0][0])
                logger.info(f"  First candle: {datetime.fromtimestamp(first_time/1000).isoformat()}")

            time.sleep(0.1)  # Rate limit
        except Exception as e:
            logger.error(f"  Error: {str(e)}")
            history_count = 0
            history_status = "✗ ERROR"

        # Compare
        logger.info(f"\nComparison:")
        logger.info(f"  Regular API: {regular_count} candles")
        logger.info(f"  History API: {history_count} candles")

        if history_count > regular_count:
            logger.info(f"  ✓ History API has MORE data ({history_count - regular_count} more candles)")
        elif history_count == regular_count and history_count > 0:
            logger.info(f"  = Both APIs have SAME data")
        elif regular_count > history_count:
            logger.info(f"  ? Regular API has MORE data (unexpected)")
        else:
            logger.info(f"  ✗ Both APIs have NO data")

        results.append({
            'test': test['name'],
            'interval': test['interval'],
            'days_ago': test['days_ago'],
            'regular_count': regular_count,
            'history_count': history_count
        })

        logger.info("")

    # Summary
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info(f"\n{'Test':<50} | Regular | History | Winner")
    logger.info("-" * 80)

    for r in results:
        winner = ""
        if r['history_count'] > r['regular_count']:
            winner = "HISTORY ✓"
        elif r['history_count'] == r['regular_count']:
            winner = "SAME"
        else:
            winner = "REGULAR"

        logger.info(f"{r['test']:<50} | {r['regular_count']:>7} | {r['history_count']:>7} | {winner}")

    logger.info("\n" + "=" * 80)
    logger.info("CONCLUSION")
    logger.info("=" * 80)

    # Count how many tests history API performed better
    history_wins = sum(1 for r in results if r['history_count'] > r['regular_count'])
    same_results = sum(1 for r in results if r['history_count'] == r['regular_count'] and r['history_count'] > 0)

    logger.info(f"\nHistory API advantages: {history_wins} out of {len(results)} tests")
    logger.info(f"Same results: {same_results} out of {len(results)} tests")

    if history_wins > 0:
        logger.info("\n✓ History API DOES provide access to older historical data")
        logger.info("  Recommendation: Use get_history_candlesticks for historical data")
    else:
        logger.info("\n✗ History API does NOT provide additional data beyond regular API")

    logger.info("=" * 80)


if __name__ == "__main__":
    test_comparison()
