#!/usr/bin/env python3
"""
Test OKX historical data depth to find the actual data retention period
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


def test_data_depth():
    """Test different time ranges to find OKX data retention limit"""

    market_api = Market.MarketAPI('', '', '', False, '0')

    logger.info("=" * 80)
    logger.info("OKX Historical Data Depth Test")
    logger.info("=" * 80)

    current_time = datetime.now()
    logger.info(f"Current time: {current_time.isoformat()}")

    # Test different time ranges going back in time
    time_ranges = [
        ("6 hours ago", 6),
        ("12 hours ago", 12),
        ("1 day ago", 24),
        ("2 days ago", 48),
        ("3 days ago", 72),
        ("7 days ago", 168),
        ("14 days ago", 336),
        ("30 days ago", 720),
        ("60 days ago", 1440),
        ("90 days ago", 2160),
    ]

    results = []

    for name, hours_ago in time_ranges:
        logger.info("\n" + "-" * 80)
        logger.info(f"Test: {name}")

        target_time = current_time - timedelta(hours=hours_ago)
        timestamp_ms = int(target_time.timestamp() * 1000)

        logger.info(f"Target time: {target_time.isoformat()}")
        logger.info(f"Timestamp: {timestamp_ms}")

        try:
            params = {
                'instId': 'BTC-USDT',
                'bar': '1m',
                'limit': '10',
                'after': str(timestamp_ms)
            }

            response = market_api.get_candlesticks(**params)

            if response['code'] == '0' and response['data']:
                data = response['data']
                logger.info(f"✓ SUCCESS - Got {len(data)} candles")

                if data:
                    first_candle_time = datetime.fromtimestamp(int(data[0][0])/1000)
                    logger.info(f"  First candle: {first_candle_time.isoformat()}")
                    results.append((name, hours_ago, True, len(data)))
            else:
                logger.warning(f"✗ NO DATA")
                results.append((name, hours_ago, False, 0))

            # Rate limit: wait 100ms between requests
            time.sleep(0.1)

        except Exception as e:
            logger.error(f"✗ Error: {str(e)}")
            results.append((name, hours_ago, False, 0))

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)

    last_success_hours = None
    first_failure_hours = None

    for name, hours, success, count in results:
        status = "✓ HAS DATA" if success else "✗ NO DATA"
        logger.info(f"{name:20s} ({hours:4d}h): {status}")

        if success:
            last_success_hours = hours
        elif first_failure_hours is None:
            first_failure_hours = hours

    logger.info("\n" + "-" * 80)
    if last_success_hours is not None:
        logger.info(f"CONCLUSION: OKX has data up to at least {last_success_hours} hours ago")
        logger.info(f"            That's approximately {last_success_hours/24:.1f} days")

    if first_failure_hours is not None:
        logger.info(f"            But NO data at {first_failure_hours} hours ago ({first_failure_hours/24:.1f} days)")

    logger.info("=" * 80)


if __name__ == "__main__":
    test_data_depth()
