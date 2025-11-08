"""
数据库初始化和管理
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger(__name__)


def get_db_connection(db_config: dict):
    """获取数据库连接"""
    return psycopg2.connect(**db_config, cursor_factory=RealDictCursor)


def init_db(db_config: dict):
    """初始化PostgreSQL数据库,创建必要的表"""
    conn = get_db_connection(db_config)
    cursor = conn.cursor()

    # 图表布局表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chart_layouts (
        id TEXT PRIMARY KEY,
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        symbol TEXT NOT NULL,
        resolution TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp BIGINT NOT NULL
    )
    ''')

    # 图表模板表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chart_templates (
        id SERIAL PRIMARY KEY,
        template_id TEXT NOT NULL,
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp BIGINT NOT NULL
    )
    ''')

    # 研究模板表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS study_templates (
        id SERIAL PRIMARY KEY,
        template_id TEXT NOT NULL,
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp BIGINT NOT NULL
    )
    ''')

    # 绘图模板表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS drawing_templates (
        id SERIAL PRIMARY KEY,
        template_id TEXT NOT NULL,
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        tool TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp BIGINT NOT NULL
    )
    ''')

    # 回放会话表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS replay_sessions (
        id SERIAL PRIMARY KEY,
        session_uuid TEXT NOT NULL UNIQUE,
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        interval TEXT NOT NULL,
        start_time BIGINT NOT NULL,
        end_time BIGINT,
        bars_count INTEGER NOT NULL DEFAULT 150,
        created_at BIGINT NOT NULL,
        updated_at BIGINT NOT NULL,
        price_start DOUBLE PRECISION,
        price_end DOUBLE PRECISION,
        price_change_percent DOUBLE PRECISION,
        market_price_start DOUBLE PRECISION,
        market_price_end DOUBLE PRECISION,
        market_price_change_percent DOUBLE PRECISION
    )
    ''')

    # 交易记录表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trades (
        id SERIAL PRIMARY KEY,
        replay_session_id TEXT,
        symbol TEXT NOT NULL,
        position_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'closed',

        entry_time BIGINT NOT NULL,
        exit_time BIGINT NOT NULL,
        entry_price DOUBLE PRECISION NOT NULL,
        exit_price DOUBLE PRECISION NOT NULL,

        quantity DOUBLE PRECISION NOT NULL,
        leverage INTEGER NOT NULL,
        margin DOUBLE PRECISION NOT NULL,

        pnl DOUBLE PRECISION NOT NULL,
        timestamp BIGINT NOT NULL
    )
    ''')

    # OKX K线数据缓存表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS okx_klines (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(50) NOT NULL,
        interval VARCHAR(10) NOT NULL,
        open_time BIGINT NOT NULL,
        close_time BIGINT NOT NULL,
        open_price DECIMAL(20,8) NOT NULL,
        high_price DECIMAL(20,8) NOT NULL,
        low_price DECIMAL(20,8) NOT NULL,
        close_price DECIMAL(20,8) NOT NULL,
        volume DECIMAL(20,8) NOT NULL,
        volume_currency DECIMAL(20,8),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, interval, open_time)
    )
    ''')

    # OKX 深度数据缓存表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS okx_orderbook (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(50) NOT NULL,
        timestamp BIGINT NOT NULL,
        bids JSONB NOT NULL,
        asks JSONB NOT NULL,
        checksum INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, timestamp)
    )
    ''')

    # OKX 成交记录缓存表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS okx_trades (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(50) NOT NULL,
        trade_id VARCHAR(50) NOT NULL,
        price DECIMAL(20,8) NOT NULL,
        size DECIMAL(20,8) NOT NULL,
        side VARCHAR(10) NOT NULL,
        timestamp BIGINT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, trade_id)
    )
    ''')

    # OKX API请求记录表(速率限制管理)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS okx_api_requests (
        id SERIAL PRIMARY KEY,
        endpoint VARCHAR(200) NOT NULL,
        method VARCHAR(10) NOT NULL DEFAULT 'GET',
        request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        response_status INTEGER,
        rate_limit_remaining INTEGER,
        rate_limit_reset TIMESTAMP,
        response_time_ms INTEGER
    )
    ''')

    # 创建索引优化查询性能
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_klines_symbol_interval_time
    ON okx_klines(symbol, interval, open_time DESC)
    ''')

    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_klines_time ON okx_klines(open_time DESC)
    ''')

    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_orderbook_symbol_time
    ON okx_orderbook(symbol, timestamp DESC)
    ''')

    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_trades_symbol_time
    ON okx_trades(symbol, timestamp DESC)
    ''')

    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_api_requests_endpoint_time
    ON okx_api_requests(endpoint, request_time)
    ''')

    conn.commit()
    conn.close()
    logger.info("数据库初始化完成")
