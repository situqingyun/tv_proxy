#!/usr/bin/env python3
"""
Test script to verify OKX data availability for historical time ranges
"""

import os
import sys
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import OKX service
sys.path.insert(0, '/home/user/tv_proxy')
from okx_service import OKXService

# Database configuration
DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "dbname": os.environ.get("DB_NAME"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD")
}

# OKX API configuration
OKX_CONFIG = {
    "api_key": os.environ.get("OKX_API_KEY", ""),
    "secret_key": os.environ.get("OKX_SECRET_KEY", ""),
    "passphrase": os.environ.get("OKX_PASSPHRASE", ""),
    "flag": os.environ.get("OKX_FLAG", "0")
}


async def test_data_availability():
    """Test OKX data availability for different time ranges"""

    logger.info("=" * 80)
    logger.info("OKX Data Availability Test")
    logger.info("=" * 80)

    # Initialize service
    okx_service = OKXService(DB_CONFIG, OKX_CONFIG)

    # Current time
    current_time = datetime.now()
    logger.info(f"\nCurrent time: {current_time.isoformat()}")

    # Test cases: different time ranges
    test_cases = [
        {
            "name": "5 months ago (problematic range)",
            "start_time": 1748222364000,  # 2025-05-25 19:32:44
            "end_time": 1748228364000,    # 2025-05-25 21:12:44
            "symbol": "BTC-USDT",
            "interval": "1m"
        },
        {
            "name": "1 week ago",
            "days_ago": 7,
            "symbol": "BTC-USDT",
            "interval": "1m",
            "duration_hours": 2
        },
        {
            "name": "1 month ago",
            "days_ago": 30,
            "symbol": "BTC-USDT",
            "interval": "1m",
            "duration_hours": 2
        },
        {
            "name": "2 months ago",
            "days_ago": 60,
            "symbol": "BTC-USDT",
            "interval": "1m",
            "duration_hours": 2
        },
        {
            "name": "3 months ago",
            "days_ago": 90,
            "symbol": "BTC-USDT",
            "interval": "1m",
            "duration_hours": 2
        }
    ]

    for test_case in test_cases:
        logger.info("\n" + "-" * 80)
        logger.info(f"Test: {test_case['name']}")
        logger.info("-" * 80)

        # Calculate timestamps
        if "start_time" in test_case:
            start_time = test_case["start_time"]
            end_time = test_case["end_time"]
        else:
            days_ago = test_case["days_ago"]
            duration_hours = test_case["duration_hours"]
            end_timestamp = int((current_time.timestamp() - days_ago * 86400) * 1000)
            start_timestamp = end_timestamp - duration_hours * 3600 * 1000
            start_time = start_timestamp
            end_time = end_timestamp

        symbol = test_case["symbol"]
        interval = test_case["interval"]

        logger.info(f"Symbol: {symbol}")
        logger.info(f"Interval: {interval}")
        logger.info(f"Start time: {start_time} ({datetime.fromtimestamp(start_time/1000).isoformat()})")
        logger.info(f"End time: {end_time} ({datetime.fromtimestamp(end_time/1000).isoformat()})")

        try:
            # Test OKX API
            klines = await okx_service.get_klines(
                symbol=symbol,
                interval=interval,
                limit=300,
                start_time=start_time,
                end_time=end_time
            )

            logger.info(f"✓ Result: Got {len(klines)} klines")

            if klines:
                # Show first and last kline
                first_kline = klines[0]
                last_kline = klines[-1]
                logger.info(f"  First kline: {datetime.fromtimestamp(first_kline['open_time']/1000).isoformat()} - Price: {first_kline['close_price']}")
                logger.info(f"  Last kline: {datetime.fromtimestamp(last_kline['open_time']/1000).isoformat()} - Price: {last_kline['close_price']}")
            else:
                logger.warning(f"✗ No data returned for this time range")

        except Exception as e:
            logger.error(f"✗ Error: {str(e)}")

    logger.info("\n" + "=" * 80)
    logger.info("Test completed")
    logger.info("=" * 80)


async def check_database_cache():
    """Check what's in the database cache"""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    logger.info("\n" + "=" * 80)
    logger.info("Database Cache Check")
    logger.info("=" * 80)

    try:
        conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
        cursor = conn.cursor()

        # Check total klines count
        cursor.execute("SELECT COUNT(*) as count FROM okx_klines")
        result = cursor.fetchone()
        logger.info(f"\nTotal klines in cache: {result['count']}")

        # Check for problematic time range (5 months ago)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM okx_klines
            WHERE symbol = 'BTC-USDT'
            AND interval = '1m'
            AND open_time >= 1748222364000
            AND open_time <= 1748228364000
        """)
        result = cursor.fetchone()
        logger.info(f"Klines for problematic range (2025-05-25): {result['count']}")

        # Check most recent data
        cursor.execute("""
            SELECT symbol, interval, open_time, close_price
            FROM okx_klines
            WHERE symbol = 'BTC-USDT'
            AND interval = '1m'
            ORDER BY open_time DESC
            LIMIT 5
        """)
        results = cursor.fetchall()
        logger.info(f"\nMost recent 5 klines:")
        for row in results:
            timestamp = datetime.fromtimestamp(row['open_time']/1000).isoformat()
            logger.info(f"  {timestamp} - Price: {row['close_price']}")

        # Check oldest data
        cursor.execute("""
            SELECT symbol, interval, open_time, close_price
            FROM okx_klines
            WHERE symbol = 'BTC-USDT'
            AND interval = '1m'
            ORDER BY open_time ASC
            LIMIT 5
        """)
        results = cursor.fetchall()
        logger.info(f"\nOldest 5 klines:")
        for row in results:
            timestamp = datetime.fromtimestamp(row['open_time']/1000).isoformat()
            logger.info(f"  {timestamp} - Price: {row['close_price']}")

        conn.close()

    except Exception as e:
        logger.error(f"Error checking database: {str(e)}")

    logger.info("\n" + "=" * 80)


async def main():
    """Main test function"""
    # Check database cache first
    await check_database_cache()

    # Test data availability
    await test_data_availability()


if __name__ == "__main__":
    asyncio.run(main())
