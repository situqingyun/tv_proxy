import requests
import okx.MarketData as Market
from datetime import datetime

symbol = "BTC-USDT"
interval = "1m"

print(f"\n=== 验证实盘数据一致性 ===")
print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# 1. OKX实盘API (flag=0)
print("\n1. OKX直接API (实盘 flag='0'):")
live_api = Market.MarketAPI("", "", "", False, "0")
response = live_api.get_candlesticks(instId=symbol, bar=interval, limit="5")
if response['code'] == '0':
    live_data = []
    for i, kline in enumerate(response['data']):
        timestamp = int(kline[0])
        dt = datetime.fromtimestamp(timestamp/1000)
        live_data.append({
            'time': dt.strftime('%H:%M:%S'),
            'close': float(kline[4]),
            'volume': float(kline[5])
        })
        print(f"  [{i+1}] {dt.strftime('%H:%M:%S')} - C:{float(kline[4]):.2f} V:{float(kline[5]):.4f}")
else:
    print(f"  错误: {response.get('msg')}")
    live_data = []

# 2. 我们的API (现在应该是实盘)
print("\n2. 我们的API (已改为实盘):")
api_url = "http://localhost:5004/api/okx/klines"
params = {"symbol": symbol, "interval": "1m", "limit": 5}

try:
    response = requests.get(api_url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data['status'] == 'ok' and data['data']:
            our_data = []
            for i, kline in enumerate(data['data']):
                timestamp = kline['open_time']
                dt = datetime.fromtimestamp(timestamp/1000)
                our_data.append({
                    'time': dt.strftime('%H:%M:%S'),
                    'close': float(kline['close_price']),
                    'volume': float(kline['volume'])
                })
                print(f"  [{i+1}] {dt.strftime('%H:%M:%S')} - C:{float(kline['close_price']):.2f} V:{float(kline['volume']):.4f}")
        else:
            print(f"  错误: {data.get('detail')}")
            our_data = []
    else:
        print(f"  HTTP错误: {response.status_code}")
        our_data = []
except Exception as e:
    print(f"  请求失败: {e}")
    our_data = []

# 3. 数据验证
print("\n3. 数据验证结果:")
if live_data and our_data and len(live_data) > 0 and len(our_data) > 0:
    match = True
    for i in range(min(3, len(live_data), len(our_data))):
        live = live_data[i]
        our = our_data[i]
        close_match = abs(live['close'] - our['close']) < 0.1
        vol_match = abs(live['volume'] - our['volume']) < 0.01
        
        if not (close_match and vol_match):
            match = False
        
        status = "✅" if (close_match and vol_match) else "❌"
        print(f"  [{i+1}] {live['time']} {status}")
        if not close_match:
            print(f"      收盘价差异: 实盘={live['close']:.2f} vs API={our['close']:.2f}")
        if not vol_match:
            print(f"      成交量差异: 实盘={live['volume']:.4f} vs API={our['volume']:.4f}")
    
    if match:
        print("\n  ✅ 结论: 数据完全一致，已成功切换到实盘数据！")
    else:
        print("\n  ⚠️ 结论: 存在数据差异，请检查配置")
else:
    print("  无法比较数据")

print("\n=== 测试完成 ===")
