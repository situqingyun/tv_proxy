#!/usr/bin/env python3
"""Test script for OKX symbol search API"""

import requests
import json
import sys

def test_symbol_search(base_url="http://127.0.0.1:5000"):
    """Test the symbol search endpoint"""

    # Test cases
    test_queries = [
        {"query": "BTC", "inst_type": "SPOT", "limit": 5},
        {"query": "ETH", "inst_type": "SPOT", "limit": 5},
        {"query": "DOGE", "inst_type": "SPOT", "limit": 5},
        {"query": "", "inst_type": "SPOT", "limit": 10},  # Empty query for popular symbols
    ]

    print("Testing OKX Symbol Search API")
    print("=" * 50)

    for params in test_queries:
        try:
            url = f"{base_url}/api/okx/symbol-search"
            print(f"\nTesting: {params}")
            print(f"URL: {url}")

            response = requests.get(url, params=params, timeout=5)

            print(f"Status Code: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'ok':
                    symbols = data.get('data', [])
                    print(f"Found {len(symbols)} symbols")
                    for symbol in symbols[:3]:  # Show first 3 results
                        print(f"  - {symbol['symbol']}: {symbol.get('description', '')}")
                else:
                    print(f"API Error: {data.get('message', 'Unknown error')}")
            else:
                print(f"HTTP Error: {response.status_code}")
                print(f"Response: {response.text[:200]}")

        except requests.exceptions.ConnectionError:
            print(f"ERROR: Cannot connect to server at {base_url}")
            print("Make sure the FastAPI server is running: python main_fastapi.py")
            return False
        except Exception as e:
            print(f"ERROR: {e}")
            return False

    print("\n" + "=" * 50)
    print("Test completed successfully!")
    return True

if __name__ == "__main__":
    # Check if server URL is provided as argument
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"

    success = test_symbol_search(base_url)
    sys.exit(0 if success else 1)