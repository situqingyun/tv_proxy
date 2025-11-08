#!/bin/bash
# OKX K线数据拉取测试 - 一键运行脚本

set -e  # 遇到错误时退出

echo "============================================================"
echo "OKX K线数据拉取测试套件"
echo "============================================================"
echo ""

# 检查是否在正确的目录
if [ ! -f "test_pagination_fix.py" ]; then
    echo "错误：请在项目根目录运行此脚本"
    exit 1
fi

# 创建测试结果目录
echo "创建测试结果目录..."
mkdir -p test_results
echo "✓ 目录已创建"
echo ""

# 询问用户要运行哪个测试
echo "请选择要运行的测试："
echo "  1) 快速测试 (test_pagination_fix.py) - 约 30 秒"
echo "  2) 全面测试 (test_kline_requests.py) - 约 3-5 分钟"
echo "  3) 两者都运行"
echo ""
read -p "请输入选择 (1/2/3): " choice

case $choice in
    1)
        echo ""
        echo "============================================================"
        echo "运行快速测试..."
        echo "============================================================"
        uv run python test_pagination_fix.py
        echo ""
        echo "✓ 快速测试完成"
        echo "查看日志: cat test_pagination_fix.log"
        ;;
    2)
        echo ""
        echo "============================================================"
        echo "运行全面测试..."
        echo "============================================================"
        uv run python test_kline_requests.py
        echo ""
        echo "✓ 全面测试完成"
        echo "查看日志: cat test_kline_requests.log"
        echo "查看结果: ls -lh test_results/"
        ;;
    3)
        echo ""
        echo "============================================================"
        echo "运行快速测试..."
        echo "============================================================"
        uv run python test_pagination_fix.py

        echo ""
        echo "============================================================"
        echo "运行全面测试..."
        echo "============================================================"
        uv run python test_kline_requests.py

        echo ""
        echo "✓ 所有测试完成"
        echo "查看快速测试日志: cat test_pagination_fix.log"
        echo "查看全面测试日志: cat test_kline_requests.log"
        echo "查看CSV结果: ls -lh test_results/"
        ;;
    *)
        echo "无效的选择: $choice"
        exit 1
        ;;
esac

echo ""
echo "============================================================"
echo "测试总结"
echo "============================================================"
echo ""
echo "日志文件："
if [ -f "test_pagination_fix.log" ]; then
    echo "  - test_pagination_fix.log ($(wc -l < test_pagination_fix.log) 行)"
fi
if [ -f "test_kline_requests.log" ]; then
    echo "  - test_kline_requests.log ($(wc -l < test_kline_requests.log) 行)"
fi
echo ""
echo "结果文件："
if [ -d "test_results" ]; then
    csv_count=$(ls test_results/*.csv 2>/dev/null | wc -l)
    if [ $csv_count -gt 0 ]; then
        echo "  - test_results/ 目录 ($csv_count 个 CSV 文件)"
        ls -lh test_results/*.csv 2>/dev/null | awk '{print "    " $9 " (" $5 ")"}'
    else
        echo "  - 无 CSV 文件生成"
    fi
fi
echo ""
echo "完整的测试指南请查看: TEST_GUIDE.md"
echo ""
