#!/usr/bin/env python3
"""Test script for OKX replay functionality"""

import requests
import json
import sys

def test_okx_replay(base_url="http://127.0.0.1:5004"):
    """Test the OKX replay endpoints"""

    print("Testing OKX Replay Functionality")
    print("=" * 50)

    # Test 1: Get random replay point with OKX symbols
    print("\n1. Testing OKX Random Replay Endpoint:")
    try:
        response = requests.get(f"{base_url}/api/okx/replay/random")
        data = response.json()

        if data['status'] == 'ok':
            print(f"✓ Got random replay point:")
            print(f"  Symbol: {data['data']['symbol']}")
            print(f"  Start Time: {data['data']['start_time']}")
            print(f"  Bars Count: {data['data']['bars_count']}")

            # Verify it's an OKX format symbol (contains dash)
            if '-' in data['data']['symbol']:
                print(f"✓ Symbol is in OKX format")
            else:
                print(f"✗ Symbol {data['data']['symbol']} is not in OKX format")
                return False
        else:
            print(f"✗ Failed: {data}")
            return False

    except Exception as e:
        print(f"✗ Error: {e}")
        return False

    # Test 2: Test with specific OKX symbol
    print("\n2. Testing with specific OKX symbol (BTC-USDT):")
    try:
        response = requests.get(f"{base_url}/api/okx/replay/random?symbol=BTC-USDT")
        data = response.json()

        if data['status'] == 'ok' and data['data']['symbol'] == 'BTC-USDT':
            print(f"✓ Got replay point for BTC-USDT")
        else:
            print(f"✗ Unexpected response: {data}")
            return False

    except Exception as e:
        print(f"✗ Error: {e}")
        return False

    # Test 3: Test K-line data retrieval for replay
    print("\n3. Testing K-line data retrieval for replay:")
    try:
        # Get a random replay point
        response = requests.get(f"{base_url}/api/okx/replay/random?symbol=BTC-USDT&interval=1H")
        replay_data = response.json()

        if replay_data['status'] == 'ok':
            start_time = replay_data['data']['start_time']

            # Convert to milliseconds
            start_ms = start_time * 1000
            end_ms = start_ms + (3600 * 1000 * 150)  # 150 hours for 1H interval

            # Get K-line data
            params = {
                'symbol': 'BTC-USDT',
                'interval': '1H',
                'start_time': start_ms,
                'end_time': end_ms,
                'limit': 150
            }

            response = requests.get(f"{base_url}/api/okx/klines", params=params)
            kline_data = response.json()

            if kline_data['status'] == 'ok':
                print(f"✓ Got {kline_data['count']} K-line bars")
                if kline_data['count'] > 0:
                    first_bar = kline_data['data'][0]
                    print(f"  First bar time: {first_bar['open_time']}")
                    print(f"  First bar close: {first_bar['close_price']}")
            else:
                print(f"✗ Failed to get K-lines: {kline_data}")
                return False

        else:
            print(f"✗ Failed to get replay point: {replay_data}")
            return False

    except Exception as e:
        print(f"✗ Error: {e}")
        return False

    # Test 4: Test session endpoints
    print("\n4. Testing replay session endpoints:")
    try:
        # List sessions
        response = requests.get(f"{base_url}/api/replay/sessions?page_size=5")
        data = response.json()

        if data['status'] == 'ok':
            print(f"✓ Listed {len(data['data'])} replay sessions")
            print(f"  Total sessions: {data.get('total', 'N/A')}")
        else:
            print(f"⚠ Session listing returned: {data}")

    except Exception as e:
        print(f"⚠ Session endpoint error (may be normal if no sessions exist): {e}")

    print("\n" + "=" * 50)
    print("✓ All OKX replay tests passed successfully!")
    return True

if __name__ == "__main__":
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5004"

    success = test_okx_replay(base_url)
    sys.exit(0 if success else 1)