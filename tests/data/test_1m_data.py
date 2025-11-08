import requests
import time
from datetime import datetime
import okx.MarketData as Market

# 初始化OKX API（公共数据不需要密钥）
market_api = Market.MarketAPI("", "", "", False, "1")

# 获取最近10条1分钟K线数据
symbol = "BTC-USDT"
interval = "1m"

print(f"\n=== 验证 {symbol} 1分钟K线数据一致性 ===")
print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# 1. 直接调用OKX API
print("\n1. OKX直接API数据:")
response = market_api.get_candlesticks(instId=symbol, bar=interval, limit="10")
if response['code'] == '0':
    okx_data = []
    for i, kline in enumerate(response['data'][:5]):  # 只显示前5条
        timestamp = int(kline[0])
        open_price = float(kline[1])
        high_price = float(kline[2])
        low_price = float(kline[3])
        close_price = float(kline[4])
        volume = float(kline[5])
        dt = datetime.fromtimestamp(timestamp/1000)
        okx_data.append({
            'time': dt.strftime('%H:%M:%S'),
            'timestamp': timestamp,
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': volume
        })
        print(f"  [{i+1}] {dt.strftime('%H:%M:%S')} - O:{open_price:.2f} H:{high_price:.2f} L:{low_price:.2f} C:{close_price:.2f} V:{volume:.2f}")
else:
    print(f"  错误: {response['msg']}")
    okx_data = []

# 2. 调用我们的API（使用正确的端口）
print("\n2. 我们的API数据 (端口5004):")
api_url = "http://localhost:5004/api/okx/klines"
params = {
    "symbol": symbol,
    "interval": "1m",
    "limit": 10
}

our_data = []
try:
    response = requests.get(api_url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data['status'] == 'ok' and data['data']:
            for i, kline in enumerate(data['data'][:5]):  # 只显示前5条
                timestamp = kline['open_time']
                dt = datetime.fromtimestamp(timestamp/1000)
                open_price = float(kline['open_price'])
                high_price = float(kline['high_price'])
                low_price = float(kline['low_price'])
                close_price = float(kline['close_price'])
                volume = float(kline['volume'])
                our_data.append({
                    'time': dt.strftime('%H:%M:%S'),
                    'timestamp': timestamp,
                    'open': open_price,
                    'high': high_price,
                    'low': low_price,
                    'close': close_price,
                    'volume': volume
                })
                print(f"  [{i+1}] {dt.strftime('%H:%M:%S')} - O:{open_price:.2f} H:{high_price:.2f} L:{low_price:.2f} C:{close_price:.2f} V:{volume:.2f}")
        else:
            print(f"  错误: {data.get('detail', 'Unknown error')}")
    else:
        print(f"  HTTP错误: {response.status_code}")
except Exception as e:
    print(f"  请求失败: {e}")

# 3. 对比数据差异
print("\n3. 数据对比分析:")
if okx_data and our_data:
    print("  时间戳对比:")
    for i in range(min(3, len(okx_data), len(our_data))):
        okx_ts = okx_data[i]['timestamp']
        our_ts = our_data[i]['timestamp'] if i < len(our_data) else 0
        match = "✓" if okx_ts == our_ts else "✗"
        print(f"    [{i+1}] OKX: {okx_data[i]['time']} ({okx_ts}) vs 我们: {our_data[i]['time'] if i < len(our_data) else 'N/A'} ({our_ts}) {match}")
    
    print("\n  价格数据对比 (第1条):")
    if okx_data and our_data:
        okx = okx_data[0]
        our = our_data[0]
        print(f"    开盘价: OKX={okx['open']:.2f} vs 我们={our['open']:.2f} {'✓' if abs(okx['open'] - our['open']) < 0.01 else '✗'}")
        print(f"    最高价: OKX={okx['high']:.2f} vs 我们={our['high']:.2f} {'✓' if abs(okx['high'] - our['high']) < 0.01 else '✗'}")
        print(f"    最低价: OKX={okx['low']:.2f} vs 我们={our['low']:.2f} {'✓' if abs(okx['low'] - our['low']) < 0.01 else '✗'}")
        print(f"    收盘价: OKX={okx['close']:.2f} vs 我们={our['close']:.2f} {'✓' if abs(okx['close'] - our['close']) < 0.01 else '✗'}")
        print(f"    成交量: OKX={okx['volume']:.2f} vs 我们={our['volume']:.2f} {'✓' if abs(okx['volume'] - our['volume']) < 0.01 else '✗'}")

# 4. 再次调用验证实时更新
print("\n4. 等待10秒后再次调用（验证实时更新）:")
time.sleep(10)
response = market_api.get_candlesticks(instId=symbol, bar=interval, limit="1")
if response['code'] == '0' and response['data']:
    kline = response['data'][0]
    timestamp = int(kline[0])
    dt = datetime.fromtimestamp(timestamp/1000)
    new_close = float(kline[4])
    if okx_data and okx_data[0]['timestamp'] == timestamp:
        old_close = okx_data[0]['close']
        diff = new_close - old_close
        print(f"  同一根K线 {dt.strftime('%H:%M:%S')}:")
        print(f"    之前收盘价: {old_close:.2f}")
        print(f"    现在收盘价: {new_close:.2f}")
        print(f"    价格变化: {diff:+.2f} {'(实时更新中)' if abs(diff) > 0.01 else '(未变化)'}")
    else:
        print(f"  最新K线 {dt.strftime('%H:%M:%S')} - 收盘价: {new_close:.2f}")

print("\n=== 测试完成 ===")
