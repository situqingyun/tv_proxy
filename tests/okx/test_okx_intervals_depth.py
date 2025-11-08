#!/usr/bin/env python3
"""
Test OKX data depth for different intervals (1m, 1H, 1D)
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


def test_interval_depth(interval, days_to_test):
    """Test specific interval depth"""

    market_api = Market.MarketAPI('', '', '', False, '0')

    logger.info(f"\nTesting interval: {interval}")
    logger.info("-" * 80)

    current_time = datetime.now()
    results = []

    for days_ago in days_to_test:
        target_time = current_time - timedelta(days=days_ago)
        timestamp_ms = int(target_time.timestamp() * 1000)

        try:
            params = {
                'instId': 'BTC-USDT',
                'bar': interval,
                'limit': '10',
                'after': str(timestamp_ms)
            }

            response = market_api.get_candlesticks(**params)

            has_data = response['code'] == '0' and len(response['data']) > 0
            status = "✓" if has_data else "✗"

            logger.info(f"{days_ago:6.2f} days ago: {status}")
            results.append((days_ago, has_data))

            time.sleep(0.1)  # Rate limit

        except Exception as e:
            logger.error(f"{days_ago:6.2f} days ago: Error - {str(e)}")
            results.append((days_ago, False))

    return results


def main():
    """Main test function"""

    logger.info("=" * 80)
    logger.info("OKX Historical Data Depth by Interval")
    logger.info("=" * 80)
    logger.info(f"Current time: {datetime.now().isoformat()}\n")

    # Test different intervals with appropriate day ranges
    test_configs = [
        {
            'interval': '1m',
            'days': [0.25, 0.5, 1, 2, 3, 7]  # Quarter day to week
        },
        {
            'interval': '1H',
            'days': [1, 2, 3, 7, 14, 30, 60, 90]  # 1 day to 3 months
        },
        {
            'interval': '1D',
            'days': [7, 14, 30, 60, 90, 180, 365, 730]  # 1 week to 2 years
        }
    ]

    all_results = {}

    for config in test_configs:
        interval = config['interval']
        days = config['days']
        results = test_interval_depth(interval, days)
        all_results[interval] = results

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)

    for interval, results in all_results.items():
        logger.info(f"\n{interval} interval:")

        last_success_days = None
        first_failure_days = None

        for days, has_data in results:
            if has_data:
                last_success_days = days
            elif first_failure_days is None:
                first_failure_days = days

        if last_success_days is not None:
            logger.info(f"  ✓ Has data up to at least {last_success_days} days ago")
        else:
            logger.info(f"  ✗ No data found even for very recent periods")

        if first_failure_days is not None:
            logger.info(f"  ✗ No data at {first_failure_days} days ago")

    logger.info("\n" + "=" * 80)


if __name__ == "__main__":
    main()
