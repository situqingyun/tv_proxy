import okx.MarketData as Market
from datetime import datetime

symbol = "BTC-USDT"
interval = "1m"

print(f"\n=== OKX 实盘 vs 模拟盘 数据对比 ===")
print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"交易对: {symbol}")

# 1. 实盘数据 (flag=0)
print("\n1. 实盘数据 (flag='0'):")
live_api = Market.MarketAPI("", "", "", False, "0")
response = live_api.get_candlesticks(instId=symbol, bar=interval, limit="3")
if response['code'] == '0':
    for i, kline in enumerate(response['data']):
        timestamp = int(kline[0])
        dt = datetime.fromtimestamp(timestamp/1000)
        print(f"  [{i+1}] {dt.strftime('%H:%M:%S')} - O:{float(kline[1]):.2f} H:{float(kline[2]):.2f} L:{float(kline[3]):.2f} C:{float(kline[4]):.2f} V:{float(kline[5]):.4f}")
else:
    print(f"  错误: {response.get('msg', 'Unknown error')}")

# 2. 模拟盘数据 (flag=1)
print("\n2. 模拟盘数据 (flag='1'):")
demo_api = Market.MarketAPI("", "", "", False, "1")
response = demo_api.get_candlesticks(instId=symbol, bar=interval, limit="3")
if response['code'] == '0':
    for i, kline in enumerate(response['data']):
        timestamp = int(kline[0])
        dt = datetime.fromtimestamp(timestamp/1000)
        print(f"  [{i+1}] {dt.strftime('%H:%M:%S')} - O:{float(kline[1]):.2f} H:{float(kline[2]):.2f} L:{float(kline[3]):.2f} C:{float(kline[4]):.2f} V:{float(kline[5]):.4f}")
else:
    print(f"  错误: {response.get('msg', 'Unknown error')}")

# 3. 对比分析
print("\n3. 数据差异分析:")
print("  ⚠️ 注意：模拟盘数据通常与实盘数据不同")
print("  - 实盘: 真实市场交易数据")
print("  - 模拟盘: 用于测试的模拟数据")
print("\n  当前我们的API使用的是: flag='1' (模拟盘)")
print("  如需获取实盘数据，应设置 OKX_FLAG=0 或修改默认值")

print("\n=== 测试完成 ===")
