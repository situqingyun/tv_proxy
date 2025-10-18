#!/usr/bin/env python3
"""
Direct test of OKX API to verify data availability
"""

import okx.MarketData as Market
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_okx_api():
    """Test OKX API directly without authentication"""

    # Initialize public API (no credentials needed)
    market_api = Market.MarketAPI('', '', '', False, '0')

    logger.info("=" * 80)
    logger.info("OKX API Direct Test")
    logger.info("=" * 80)

    # Test cases
    test_cases = [
        {
            "name": "5 months ago (2025-05-25) - The problematic range",
            "after": "1748228364000",  # 2025-05-25 21:12:44 (end time)
            "symbol": "BTC-USDT",
            "interval": "1m",
            "limit": "300"
        },
        {
            "name": "Recent data (last 300 candles)",
            "after": None,
            "symbol": "BTC-USDT",
            "interval": "1m",
            "limit": "300"
        },
        {
            "name": "1 hour data from 5 months ago",
            "after": "1748228364000",
            "symbol": "BTC-USDT",
            "interval": "1H",
            "limit": "100"
        }
    ]

    for test in test_cases:
        logger.info("\n" + "-" * 80)
        logger.info(f"Test: {test['name']}")
        logger.info("-" * 80)
        logger.info(f"Symbol: {test['symbol']}")
        logger.info(f"Interval: {test['interval']}")
        logger.info(f"Limit: {test['limit']}")
        if test['after']:
            logger.info(f"After: {test['after']} ({datetime.fromtimestamp(int(test['after'])/1000).isoformat()})")

        try:
            params = {
                'instId': test['symbol'],
                'bar': test['interval'],
                'limit': test['limit']
            }

            if test['after']:
                params['after'] = test['after']

            logger.info(f"Calling: market_api.get_candlesticks(**{params})")
            response = market_api.get_candlesticks(**params)

            logger.info(f"Response code: {response['code']}")
            logger.info(f"Response message: {response.get('msg', 'OK')}")

            if response['code'] == '0' and response['data']:
                data = response['data']
                logger.info(f"✓ Got {len(data)} candles")

                if data:
                    # Show first candle
                    first_candle = data[0]
                    timestamp_ms = int(first_candle[0])
                    timestamp = datetime.fromtimestamp(timestamp_ms/1000).isoformat()
                    logger.info(f"  First candle: {timestamp}")
                    logger.info(f"    Open: {first_candle[1]}, High: {first_candle[2]}, Low: {first_candle[3]}, Close: {first_candle[4]}, Volume: {first_candle[5]}")

                    # Show last candle
                    last_candle = data[-1]
                    timestamp_ms = int(last_candle[0])
                    timestamp = datetime.fromtimestamp(timestamp_ms/1000).isoformat()
                    logger.info(f"  Last candle: {timestamp}")
                    logger.info(f"    Open: {last_candle[1]}, High: {last_candle[2]}, Low: {last_candle[3]}, Close: {last_candle[4]}, Volume: {last_candle[5]}")

                    # Calculate time range
                    first_time = int(data[0][0])
                    last_time = int(data[-1][0])
                    time_diff_hours = (first_time - last_time) / (1000 * 3600)
                    logger.info(f"  Time range: {time_diff_hours:.2f} hours")
            else:
                logger.warning(f"✗ No data returned")
                logger.warning(f"  Response: {response}")

        except Exception as e:
            logger.error(f"✗ Error: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

    logger.info("\n" + "=" * 80)
    logger.info("Test completed")
    logger.info("=" * 80)


if __name__ == "__main__":
    test_okx_api()
