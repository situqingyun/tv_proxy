import traceback
import asyncio
import ssl
from fastapi import FastAPI, Request, HTTPException, Form, Query, Depends
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import socketio
from dotenv import load_dotenv
import os
import requests
import logging
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
import mimetypes
import pathlib
import websocket
import json
import threading
import time
import uuid
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, Dict, Any
from pydantic import BaseModel
import base64

# Load environment variables from .env file if it exists
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="TV Proxy", description="A FastAPI-based TV proxy application", version="0.1.0")

# --- START: Snapshot-related setup ---

# Create a directory for snapshots
SNAPSHOTS_DIR = os.path.join(os.path.dirname(__file__), "snapshots")
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

# Mount the snapshots directory to serve static files
app.mount("/snapshots", StaticFiles(directory=SNAPSHOTS_DIR), name="snapshots")

# Define the request body model for snapshot data
class SnapshotData(BaseModel):
    data: str

# --- END: Snapshot-related setup ---

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize templates
templates = Jinja2Templates(directory="templates")

# Initialize SocketIO with CORS support
sio = socketio.AsyncServer(cors_allowed_origins="*", async_mode='asgi')
socket_app = socketio.ASGIApp(sio, app)

# WebSocket connections tracker
active_connections = {}

# Configuration from environment variables
REPLAY_BARS_COUNT = int(os.environ.get('REPLAY_BARS_COUNT', '150'))
REPLAY_SYMBOLS = os.environ.get('REPLAY_SYMBOLS', 'BATS_DLY:AAPL,BATS_DLY:AAPL').split(',')
REPLAY_MAX_DAYS = int(os.environ.get('REPLAY_MAX_DAYS', '365'))
DEFAULT_REPLAY_INTERVAL = os.environ.get('DEFAULT_REPLAY_INTERVAL', '1D')
REPLAY_EARLIEST_DATE = os.environ.get('REPLAY_EARLIEST_DATE', '2023-01-01')
REPLAY_EARLIEST_TIMESTAMP = int(datetime.strptime(REPLAY_EARLIEST_DATE, '%Y-%m-%d').timestamp())

# PostgreSQL connection configuration
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "43.156.51.247"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ.get("DB_NAME", "tvdb"),
    "user": os.environ.get("DB_USER", "tvuser"),
    "password": os.environ.get("DB_PASSWORD", "bsh25fdsad77bxcb")
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

# WebSocket proxy handler class
class TradingViewWSProxy:
    def __init__(self, client_sid, loop):
        self.client_sid = client_sid
        self.ws = None
        self.connected = False
        self.connection_id = str(uuid.uuid4())
        self.loop = loop  # Store the event loop reference
    
    def connect_to_tradingview(self, url):
        logger.info(f"Connecting to TradingView WebSocket: {url}")
        
        def on_message(ws, message):
            logger.debug(f"Received message from TradingView: {message[:100]}...")
            # Forward the message to the client using asyncio.run_coroutine_threadsafe
            try:
                asyncio.run_coroutine_threadsafe(
                    sio.emit('tv_message', {'message': message}, room=self.client_sid),
                    self.loop
                )
            except Exception as e:
                logger.error(f"Failed to emit tv_message: {e}")
        
        def on_error(ws, error):
            logger.error(f"Error in TradingView WebSocket connection: {error}")
            try:
                asyncio.run_coroutine_threadsafe(
                    sio.emit('tv_error', {'error': str(error)}, room=self.client_sid),
                    self.loop
                )
            except Exception as e:
                logger.error(f"Failed to emit tv_error: {e}")
        
        def on_close(ws, close_status_code, close_msg):
            logger.info(f"TradingView WebSocket connection closed: {close_status_code} {close_msg}")
            self.connected = False
            try:
                asyncio.run_coroutine_threadsafe(
                    sio.emit('tv_disconnect', {}, room=self.client_sid),
                    self.loop
                )
            except Exception as e:
                logger.error(f"Failed to emit tv_disconnect: {e}")
        
        def on_open(ws):
            logger.info("TradingView WebSocket connection established")
            self.connected = True
            try:
                asyncio.run_coroutine_threadsafe(
                    sio.emit('tv_connect', {}, room=self.client_sid),
                    self.loop
                )
            except Exception as e:
                logger.error(f"Failed to emit tv_connect: {e}")
        
        # SSL configuration for better compatibility
        sslopt = {
            "cert_reqs": ssl.CERT_NONE,
            "check_hostname": False,
            "ssl_version": ssl.PROTOCOL_TLS
        }
        
        # Create WebSocket connection to TradingView with SSL options
        self.ws = websocket.WebSocketApp(
            url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        
        # Run the WebSocket connection in a separate thread with SSL options
        wst = threading.Thread(target=self.ws.run_forever, kwargs={'sslopt': sslopt})
        wst.daemon = True
        wst.start()
        
        return self.connection_id
    
    def send(self, message):
        if self.ws and self.connected:
            logger.debug(f"Sending message to TradingView: {message[:100]}...")
            self.ws.send(message)
            return True
        else:
            logger.exception("Cannot send message, WebSocket not connected")
            return False
    
    def disconnect(self):
        if self.ws:
            logger.info("Closing TradingView WebSocket connection")
            self.ws.close()
            self.ws = None
            self.connected = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s() - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Base URLs for TradingView resources
DOMAIN_MAPPINGS = {
    "trading-terminal.tradingview-widget.com": "https://trading-terminal.tradingview-widget.com/",
    "demo-feed-data.tradingview.com": "https://demo-feed-data.tradingview.com/",
    "saveload.tradingview.com": "https://saveload.tradingview.com/",
    "www.tradingview.com": "https://www.tradingview.com/"
}

# Directory to store cached resources
STATIC_CACHE_DIR = os.path.join(os.path.dirname(__file__), "static_cache")
os.makedirs(STATIC_CACHE_DIR, exist_ok=True)

def init_db():
    """Initialize PostgreSQL database, create necessary tables"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Chart layouts table
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
    
    # Chart templates table
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
    
    # Study templates table
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
    
    # Drawing templates table
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

    # Replay sessions table
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

    # Trades table
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
    
    conn.commit()
    conn.close()
    logger.info("Database initialization completed")

# Initialize the database
init_db()

# Routes - Order matters! Most specific routes first, generic routes last

# Static page routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "title": "TV Proxy"})

@app.get("/platform", response_class=HTMLResponse)
async def platform(request: Request):
    return templates.TemplateResponse("platform.html", {"request": request, "title": "TV Proxy"})

# Handle favicon.ico requests
@app.get("/favicon.ico")
async def favicon():
    raise HTTPException(status_code=404, detail="Not found")

# WebSocket proxy URL endpoint
@app.get('/ws-proxy-url')
async def ws_proxy_url(request: Request):
    """Return the WebSocket proxy URL for the client"""
    base_url = str(request.base_url).replace('http://', 'ws://').replace('https://', 'wss://')
    if base_url.endswith('/'):
        base_url = base_url[:-1]
    return {'proxyUrl': base_url}

@app.post("/api/snapshot")
async def create_snapshot(snapshot: SnapshotData, request: Request):
    """
    Receives a TradingView chart snapshot, saves it as an image, and returns the URL.
    """
    try:
        # The Base64 data from TradingView is in the format "data:image/png;base64,iVBORw0KGgo..."
        # We need to remove the header and keep only the Base64 encoded part.
        header, encoded = snapshot.data.split(",", 1)
        
        # Decode the Base64 data
        image_data = base64.b64decode(encoded)
        
        # Generate a unique filename
        filename = f"{uuid.uuid4()}.png"
        file_path = os.path.join(SNAPSHOTS_DIR, filename)
        
        # Write the image data to a file
        with open(file_path, "wb") as f:
            f.write(image_data)
            
        logger.info(f"Snapshot saved to {file_path}")
        
        # Construct the publicly accessible URL
        # request.base_url will be something like http://127.0.0.1:5000/
        image_url = f"{str(request.base_url).rstrip('/')}/snapshots/{filename}"
        
        # TradingView expects a JSON response in this format
        return {
            "status": "ok",
            "url": image_url
        }
        
    except Exception as e:
        logger.exception("Error processing snapshot")
        raise HTTPException(status_code=500, detail=f"Error processing snapshot: {str(e)}")

# API routes - All specific API routes must come before generic proxy routes
@app.get('/api/replay/random')
async def get_random_replay_point(
    symbol: Optional[str] = Query(None),
    bars_count: Optional[int] = Query(REPLAY_BARS_COUNT),
    interval: Optional[str] = Query(DEFAULT_REPLAY_INTERVAL)
):
    """获取随机回放起始点（受最早回放日期和bars_count*interval限制）"""
    try:
        # Validate bars_count
        if bars_count is None or bars_count <= 0:
            bars_count = REPLAY_BARS_COUNT
        
        # interval转秒数
        interval_seconds = interval_to_seconds(interval)
        
        # 没有指定symbol则随机
        if not symbol:
            import random
            symbol = random.choice(REPLAY_SYMBOLS)
        
        current_time = int(time.time())
        
        # 计算最早和最晚的起始时间
        earliest_time = REPLAY_EARLIEST_TIMESTAMP
        latest_time = current_time - (bars_count * interval_seconds)
        if latest_time < earliest_time:
            latest_time = earliest_time
        
        # 随机选取
        if earliest_time >= latest_time:
            random_start_time = earliest_time
        else:
            import random
            random_start_time = random.randint(earliest_time, latest_time)
        
        return {
            'status': 'ok',
            'data': {
                'symbol': symbol,
                'start_time': random_start_time,
                'bars_count': bars_count
            }
        }
    except Exception as e:
        logger.exception(f"Error generating random replay point: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating random replay point: {str(e)}")

@app.post('/save-trade')
async def save_trade(request: Request):
    """Save a trade record"""
    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail="Missing trade data")
        
        # 验证必要字段
        required_fields = [
            'symbol', 'position_type', 'entry_time', 'exit_time',
            'entry_price', 'exit_price', 'pnl', 'timestamp',
            'quantity', 'leverage', 'margin'
        ]
        for field in required_fields:
            if field not in data:
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 检查是否有会话ID
        replay_session_id = data.get('replay_session_id', None)
        response_data = {}
        
        # 如果没有会话ID，并且这是首次交易，则创建新的回放会话
        if not replay_session_id or data.get('is_first_trade', False):
            session_uuid = str(uuid.uuid4())
            current_time = int(time.time())
            bars_count = data.get('bars_count', 150)
            client_id = data.get('client_id', 'default_client')
            user_id = data.get('user_id', 'default_user')
            
            cursor.execute('''
            INSERT INTO replay_sessions (
                session_uuid, client_id, user_id, symbol, interval,
                start_time, bars_count, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                session_uuid, client_id, user_id,
                data['symbol'],
                data.get('interval', '1D'),
                data.get('entry_time'),
                bars_count, current_time, current_time
            ))
            
            replay_session_id = session_uuid
            response_data['session_uuid'] = session_uuid
        
        # 插入交易记录
        cursor.execute('''
        INSERT INTO trades (
            replay_session_id, symbol, position_type, status,
            entry_time, exit_time, entry_price, exit_price,
            quantity, leverage, margin,
            pnl, timestamp
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            replay_session_id,
            data['symbol'],
            data['position_type'],
            data.get('status', 'closed'),
            data['entry_time'],
            data['exit_time'],
            data['entry_price'],
            data['exit_price'],
            data['quantity'],
            data['leverage'],
            data['margin'],
            data['pnl'],
            data['timestamp']
        ))
        
        # 更新会话的价格信息
        if data.get('is_first_trade', False):
            entry_price = data['entry_price']
            cursor.execute('''
            UPDATE replay_sessions
            SET price_start = %s
            WHERE session_uuid = %s
            ''', (entry_price, replay_session_id))
        
        # 每次交易都更新结束价格和价格变化百分比
        exit_price = data['exit_price']
        cursor.execute('''
        SELECT price_start FROM replay_sessions WHERE session_uuid = %s
        ''', (replay_session_id,))
        session_row = cursor.fetchone()
        
        if session_row and session_row['price_start']:
            price_start = session_row['price_start']
            price_change_percent = ((exit_price - price_start) / price_start) * 100
            
            cursor.execute('''
            UPDATE replay_sessions
            SET price_end = %s, price_change_percent = %s
            WHERE session_uuid = %s
            ''', (exit_price, price_change_percent, replay_session_id))
        
        conn.commit()
        conn.close()
        
        return {
            'status': 'ok',
            'message': 'Trade record saved successfully',
            'data': response_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error saving trade record: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error saving trade record: {str(e)}")

@app.get('/trade-statistics')
async def trade_statistics(
    symbol: Optional[str] = Query(None),
    interval: Optional[str] = Query(None)
):
    """获取交易统计数据"""
    try:
        logger.info(f"获取交易统计数据: symbol='{symbol}', interval='{interval}'")
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 构建查询条件
        query_conditions = []
        query_params = []
        
        # Base query with JOIN
        base_query_from = '''
        FROM trades t
        JOIN replay_sessions s ON t.replay_session_id = s.session_uuid
        '''

        if symbol:
            query_conditions.append("t.symbol = %s")
            query_params.append(symbol)
        
        if interval:
            query_conditions.append("s.interval = %s")
            query_params.append(interval)
        
        # 组合查询条件
        where_clause = ""
        if query_conditions:
            where_clause = "WHERE " + " AND ".join(query_conditions)
        
        # 执行统计查询
        cursor.execute(f'''
        SELECT
            COUNT(*) as total_trades,
            SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as profitable_trades,
            SUM(t.pnl) as total_pnl
        {base_query_from}
        {where_clause}
        ''', query_params)
        
        result = cursor.fetchone()
        
        # 计算统计数据
        total_trades = result['total_trades'] or 0
        profitable_trades = result['profitable_trades'] or 0
        total_pnl = result['total_pnl'] or 0
        
        # 计算成功率和盈利率
        win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0
        
        # 获取所有交易记录以计算盈利率
        cursor.execute(f'''
        SELECT t.position_type, t.entry_price, t.exit_price, t.pnl
        {base_query_from}
        {where_clause}
        ''', query_params)
        
        trades = cursor.fetchall()
        
        # 计算总投入资金（按照入场价格计算）
        total_invested = 0
        for trade in trades:
            total_invested += trade['entry_price']
        
        # 计算盈利率 = 总盈亏/总投入资金
        profit_rate = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        
        conn.close()
        
        return {
            'status': 'ok',
            'data': {
                'total_trades': total_trades,
                'profitable_trades': profitable_trades,
                'win_rate': round(win_rate, 2),
                'total_pnl': round(total_pnl, 2),
                'profit_rate': round(profit_rate, 2)
            }
        }
        
    except Exception as e:
        logger.exception(f"Error getting trade statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting trade statistics: {str(e)}")

# Replay Sessions API endpoints
@app.post('/api/replay/sessions')
async def create_replay_session(request: Request):
    """创建新的回放会话
    
    当用户进行第一次平仓操作时调用，创建一个新的回放会话记录
    """
    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail="Missing session data")
        
        # 验证必要字段
        required_fields = ['symbol', 'interval', 'start_time', 'client_id', 'user_id']
        for field in required_fields:
            if field not in data:
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
        
        # 生成会话UUID
        session_uuid = str(uuid.uuid4())
        current_time = int(time.time())
        
        # 获取K线数量，如果未提供则使用默认值
        bars_count = data.get('bars_count', 150)
        try:
            bars_count = int(bars_count)
        except:
            bars_count = 150
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 插入回放会话记录
        cursor.execute('''
        INSERT INTO replay_sessions (
            session_uuid, client_id, user_id, symbol, interval, 
            start_time, bars_count, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            session_uuid,
            data['client_id'],
            data['user_id'],
            data['symbol'],
            data['interval'],
            data['start_time'],
            bars_count,
            current_time,
            current_time
        ))
        
        session_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return {
            'status': 'ok',
            'data': {
                'session_id': session_id,
                'session_uuid': session_uuid
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating replay session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating replay session: {str(e)}")

@app.get('/api/replay/sessions/{session_uuid}')
async def get_replay_session(session_uuid: str):
    """获取回放会话信息"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 查询回放会话
        cursor.execute('''
        SELECT id, session_uuid, client_id, user_id, symbol, interval, 
               start_time, end_time, bars_count, created_at, updated_at
        FROM replay_sessions
        WHERE session_uuid = %s
        ''', (session_uuid,))
        
        session = cursor.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Replay session not found")
        
        # 查询该会话下的交易记录
        cursor.execute('''
        SELECT id, symbol, position_type, entry_time, exit_time,
               entry_price, exit_price, pnl, timestamp
        FROM trades
        WHERE replay_session_id = %s
        ORDER BY timestamp ASC
        ''', (session_uuid,))
        
        trades = cursor.fetchall()
        trades_list = []
        for trade in trades:
            trades_list.append(dict(trade))
        
        conn.close()
        
        # 构建会话信息
        session_data = dict(session)
        session_data['trades'] = trades_list
        
        return {
            'status': 'ok',
            'data': session_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting replay session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting replay session: {str(e)}")

@app.put('/api/replay/sessions/{session_uuid}')
async def update_replay_session(session_uuid: str, request: Request):
    """更新回放会话信息
    
    可以更新会话的结束时间等信息
    """
    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail="Missing update data")
        
        current_time = int(time.time())
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 构建更新字段
        update_fields = []
        update_values = []
        
        # 可更新的字段列表
        allowed_fields = ['end_time', 'interval', 'bars_count']
        
        for field in allowed_fields:
            if field in data:
                update_fields.append(f"{field} = %s")
                update_values.append(data[field])
        
        # 添加更新时间
        update_fields.append("updated_at = %s")
        update_values.append(current_time)
        
        # 添加会话UUID到更新参数
        update_values.append(session_uuid)
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="No valid fields to update")
        
        # 执行更新
        cursor.execute(f'''
        UPDATE replay_sessions
        SET {', '.join(update_fields)}
        WHERE session_uuid = %s
        ''', update_values)
        
        if cursor.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="Replay session not found")
        
        conn.commit()
        conn.close()
        
        return {
            'status': 'ok',
            'message': 'Replay session updated successfully'
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating replay session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating replay session: {str(e)}")

@app.post('/api/replay/sessions/{session_uuid}/market-price')
async def update_session_market_price(session_uuid: str, request: Request):
    """更新会话的市场价格信息"""
    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail="Missing price data")
        
        # 验证必要字段
        required_fields = ['price', 'price_type']
        for field in required_fields:
            if field not in data:
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
        
        price = data['price']
        price_type = data['price_type']  # 'start' or 'end'
        
        if price_type not in ['start', 'end']:
            raise HTTPException(status_code=400, detail='price_type must be "start" or "end"')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if price_type == 'start':
            # 更新开始价格
            cursor.execute('''
            UPDATE replay_sessions 
            SET market_price_start = %s, updated_at = %s
            WHERE session_uuid = %s
            ''', (price, int(time.time()), session_uuid))
        else:
            # 更新结束价格，同时计算价格变化百分比
            cursor.execute('''
            SELECT market_price_start FROM replay_sessions WHERE session_uuid = %s
            ''', (session_uuid,))
            session_row = cursor.fetchone()
            
            if session_row and session_row['market_price_start']:
                market_price_start = session_row['market_price_start']
                market_price_change_percent = ((price - market_price_start) / market_price_start) * 100
                
                cursor.execute('''
                UPDATE replay_sessions 
                SET market_price_end = %s, market_price_change_percent = %s, updated_at = %s
                WHERE session_uuid = %s
                ''', (price, market_price_change_percent, int(time.time()), session_uuid))
            else:
                cursor.execute('''
                UPDATE replay_sessions 
                SET market_price_end = %s, updated_at = %s
                WHERE session_uuid = %s
                ''', (price, int(time.time()), session_uuid))
        
        if cursor.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="Replay session not found")
        
        conn.commit()
        conn.close()
        
        return {
            'status': 'ok',
            'message': 'Market price updated successfully'
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating session market price: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating session market price: {str(e)}")

@app.get('/api/replay/sessions')
async def list_replay_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    client_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """分页查询回放会话列表，支持前端下滑翻页"""
    try:
        offset = (page - 1) * page_size

        conn = get_db_connection()
        cursor = conn.cursor()

        # 构建where条件
        where_clauses = []
        params = []
        if client_id:
            where_clauses.append('rs.client_id = %s')
            params.append(client_id)
        if user_id:
            where_clauses.append('rs.user_id = %s')
            params.append(user_id)
        where_sql = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''

        # 查询总数
        cursor.execute(f'SELECT COUNT(*) FROM replay_sessions rs {where_sql}', params)
        total = cursor.fetchone()['count']

        # 使用LEFT JOIN一次性查询所有数据，避免循环查询
        cursor.execute(f'''
            SELECT 
                rs.session_uuid, 
                rs.symbol, 
                rs.interval, 
                rs.start_time, 
                rs.end_time, 
                rs.bars_count,
                rs.price_start, 
                rs.price_end, 
                rs.price_change_percent,
                rs.market_price_start,
                rs.market_price_end,
                rs.market_price_change_percent,
                COALESCE(t.total_pnl, 0) as total_pnl,
                COALESCE(t.trade_count, 0) as trade_count,
                t.min_entry_time as hold_time_start,
                t.max_exit_time as hold_time_end,
                CASE 
                    WHEN t.min_entry_time IS NOT NULL AND t.max_exit_time IS NOT NULL 
                    THEN t.max_exit_time - t.min_entry_time 
                    ELSE 0 
                END as hold_time_length
            FROM replay_sessions rs
            LEFT JOIN (
                SELECT 
                    replay_session_id,
                    SUM(pnl) as total_pnl,
                    MIN(entry_time) as min_entry_time,
                    MAX(exit_time) as max_exit_time,
                    COUNT(*) as trade_count
                FROM trades
                GROUP BY replay_session_id
            ) t ON rs.session_uuid = t.replay_session_id
            {where_sql}
            ORDER BY rs.created_at DESC
            LIMIT %s OFFSET %s
        ''', params + [page_size, offset])
        
        sessions = cursor.fetchall()
        conn.close()
        
        # 转换为字典列表
        sessions_list = [dict(session) for session in sessions]
        
        return {
            'status': 'ok',
            'data': sessions_list,
            'total': total,
            'page': page,
            'page_size': page_size
        }
    except Exception as e:
        logger.exception(f"Error listing replay sessions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# TradingView Chart Storage API - specific domain routes
@app.get('/saveload.tradingview.com/1.1/charts')
async def list_charts(
    client: str = Query(..., alias="client"),
    user: str = Query(..., alias="user"),
    chart: Optional[str] = Query(None, alias="chart")
):
    """List all charts for a user"""
    if not client or not user:
        raise HTTPException(status_code=400, detail="Missing client_id or user_id")
    
    if chart:
        return get_chart_content(client, user, chart)
    else:
        return get_all_users_charts(client, user)

@app.post('/saveload.tradingview.com/1.1/charts')
async def save_chart(
    client: str = Query(..., alias="client"),
    user: str = Query(..., alias="user"),
    chart: Optional[str] = Query(None, alias="chart"),
    name: str = Form(...),
    content: str = Form(...),
    symbol: str = Form(...),
    resolution: str = Form(...)
):
    """Save a chart layout"""
    if not client or not user:
        raise HTTPException(status_code=400, detail="Missing client_id or user_id")

    if not content:
        raise HTTPException(status_code=400, detail="Missing content")

    timestamp = int(datetime.now().timestamp())
    conn = get_db_connection()
    cursor = conn.cursor()

    if chart:
        cursor.execute('''
        UPDATE chart_layouts
        SET name = %s, symbol = %s, resolution = %s, content = %s, timestamp = %s
        WHERE id = %s AND client_id = %s AND user_id = %s
        ''', (name, symbol, resolution, content, timestamp, chart, client, user))
    else:
        # 创建新图表 - 使用服务器生成的UUID作为主键
        new_chart_id = str(uuid.uuid4())
        
        # 可选：如果content是JSON，尝试更新其中的id字段以保持一致性
        try:
            chart_data = json.loads(content)
            chart_data['id'] = new_chart_id
            content = json.dumps(chart_data)
        except (json.JSONDecodeError, ValueError):
            # 如果content不是有效JSON，保持原样
            pass
        
        cursor.execute('''
        INSERT INTO chart_layouts (id, client_id, user_id, name, symbol, resolution, content, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (new_chart_id, client, user, name, symbol, resolution, content, timestamp))
        chart = new_chart_id

    conn.commit()
    conn.close()
    return {'status': 'ok', 'id': chart}

@app.delete('/saveload.tradingview.com/1.1/charts')
async def delete_chart(
    client: str = Query(..., alias="client"),
    user: str = Query(..., alias="user"),
    chart: str = Query(..., alias="chart")
):
    """Delete a specific chart layout"""
    if not client or not user:
        raise HTTPException(status_code=400, detail="Missing client_id or user_id")
    
    if not chart:
        raise HTTPException(status_code=400, detail="Missing chart_id")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        DELETE FROM chart_layouts
        WHERE id = %s AND client_id = %s AND user_id = %s
        ''', (chart, client, user))
        conn.commit()
        conn.close()
        return {'status': 'ok'}
    except Exception as e:
        logger.exception(f"Error deleting chart {chart}")
        raise HTTPException(status_code=500, detail=f"Error deleting chart: {str(e)}")

# Study Templates API endpoints
@app.get('/saveload.tradingview.com/1.1/study_templates')
async def list_study_templates(
    client: str = Query(..., alias="client"),
    user: str = Query(..., alias="user"),
    template: Optional[str] = Query(None, alias="template")
):
    """List all study templates for a user"""
    if not client or not user:
        raise HTTPException(status_code=400, detail="Missing client_id or user_id")
        
    if template:
        return get_study_template(client, user, template)
    else:
        return get_all_study_templates_list(client, user)

@app.post('/saveload.tradingview.com/1.1/study_templates')
async def save_study_template(
    client: str = Query(..., alias="client"),
    user: str = Query(..., alias="user"),
    name: str = Form(...),
    content: str = Form(...)
):
    """Save a study template"""
    if not client or not user:
        raise HTTPException(status_code=400, detail="Missing client_id or user_id")
    
    if not name or not content:
        raise HTTPException(status_code=400, detail="Missing template name or content")
    
    timestamp = int(datetime.now().timestamp())
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT id FROM study_templates WHERE name = %s AND client_id = %s AND user_id = %s
    ''', (name, client, user))
    
    row = cursor.fetchone()
    if row:
        cursor.execute('''
        UPDATE study_templates
        SET content = %s, timestamp = %s
        WHERE name = %s AND client_id = %s AND user_id = %s
        ''', (content, timestamp, name, client, user))
    else:
        cursor.execute('''
        INSERT INTO study_templates (client_id, user_id, name, content, timestamp, template_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        ''', (client, user, name, content, timestamp, name))
    
    conn.commit()
    conn.close()
    
    return {'status': 'ok', 'id': name}

@app.delete('/saveload.tradingview.com/1.1/study_templates')
async def delete_study_template(
    client: str = Query(..., alias="client"),
    user: str = Query(..., alias="user"),
    template: str = Query(..., alias="template")
):
    """Delete a specific study template"""
    if not client or not user:
        raise HTTPException(status_code=400, detail="Missing client_id or user_id")
    
    if not template:
        raise HTTPException(status_code=400, detail="Missing template name")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
        DELETE FROM study_templates
        WHERE name = %s AND client_id = %s AND user_id = %s
        ''', (template, client, user))
    
        conn.commit()
        conn.close()
    
        return {'status': 'ok'}
    except Exception as e:
        logger.exception(f"Error deleting study template {template}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting study template: {str(e)}")

# Drawing Templates API endpoints
@app.get('/saveload.tradingview.com/1.1/drawing_templates')
async def list_drawing_templates(
    client: str = Query(..., alias="client"),
    user: str = Query(..., alias="user"),
    name: Optional[str] = Query(None, alias="name"),
    tool: Optional[str] = Query(None, alias="tool")
):
    """List all drawing templates for a user"""
    if not client or not user:
        raise HTTPException(status_code=400, detail="Missing client_id or user_id")
    
    if name:
        return get_drawing_template(client, user, tool or '', name)
    else:
        return get_all_drawing_templates(client, user, tool or '')

@app.post('/saveload.tradingview.com/1.1/drawing_templates')
async def save_drawing_template(
    client: str = Query(..., alias="client"),
    user: str = Query(..., alias="user"),
    name: str = Query(..., alias="name"),
    tool: str = Query(..., alias="tool"),
    content: str = Form(...)
):
    """Save a drawing template"""
    if not client or not user:
        raise HTTPException(status_code=400, detail="Missing client_id or user_id")
    
    if not name or not tool or not content:
        raise HTTPException(status_code=400, detail="Missing name, tool, or content")
    
    timestamp = int(datetime.now().timestamp())
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        SELECT id FROM drawing_templates WHERE name = %s AND client_id = %s AND user_id = %s AND tool = %s
        ''', (name, client, user, tool))
        
        row = cursor.fetchone()
        if row:
            cursor.execute('''
            UPDATE drawing_templates
            SET content = %s, timestamp = %s
            WHERE id = %s
            ''', (content, timestamp, row['id']))
        else:
            cursor.execute('''
            INSERT INTO drawing_templates (name, client_id, user_id, tool, content, timestamp, template_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (name, client, user, tool, content, timestamp, name))
        
        conn.commit()
        conn.close()
        return {'status': 'ok'}
    except Exception as e:
        logger.exception(f"Error saving drawing template: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete('/saveload.tradingview.com/1.1/drawing_templates')
async def delete_drawing_template(
    client: str = Query(..., alias="client"),
    user: str = Query(..., alias="user"),
    tool: str = Query(..., alias="tool"),
    name: str = Query(..., alias="name")
):
    """Delete a specific drawing template"""
    if not client or not user:
        raise HTTPException(status_code=400, detail="Missing client_id or user_id")
    
    if not tool or not name:
        raise HTTPException(status_code=400, detail="Missing tool or name")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
        DELETE FROM drawing_templates
        WHERE name = %s AND client_id = %s AND user_id = %s AND tool = %s
        ''', (name, client, user, tool))
    
        conn.commit()
        conn.close()
        return {'status': 'ok'}
    except Exception as e:
        logger.exception(f"Error deleting drawing template {name} for tool {tool}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting drawing template: {str(e)}")

# Specific proxy routes for TradingView resources - must come before generic proxy route
@app.get("/charting_library/{resource_path:path}")
async def proxy_charting_library(resource_path: str):
    """Special handler for charting_library resources"""
    domain = "trading-terminal.tradingview-widget.com"
    full_path = f"charting_library/{resource_path}"
    return await proxy_tradingview_resource(domain, full_path)

@app.get("/datafeeds/{resource_path:path}")
async def proxy_datafeeds(resource_path: str):
    """Special handler for datafeeds resources"""
    domain = "trading-terminal.tradingview-widget.com"
    full_path = f"datafeeds/{resource_path}"
    return await proxy_tradingview_resource(domain, full_path)

@app.get("/broker-sample/{resource_path:path}")
async def proxy_broker_sample(resource_path: str):
    """Special handler for broker-sample resources"""
    domain = "trading-terminal.tradingview-widget.com"
    full_path = f"broker-sample/{resource_path}"
    return await proxy_tradingview_resource(domain, full_path)

# Generic proxy route - MUST come LAST to avoid conflicting with specific routes
@app.get("/{domain}/{resource_path:path}")
async def proxy_tradingview_resource(domain: str, resource_path: str):
    """
    Proxy handler for TradingView widget resources.
    If the resource exists locally, serve it from the local cache.
    Otherwise, download it from TradingView website and cache it for future use.
    """
    # Ensure the resource path is sanitized to prevent directory traversal
    if ".." in resource_path:
        raise HTTPException(status_code=400, detail="Invalid resource path")
    
    # Check if this is a valid domain we can proxy
    if domain not in DOMAIN_MAPPINGS:
        logger.error(f"Unknown domain: {domain}")
        raise HTTPException(status_code=400, detail=f"Unknown domain: {domain}")
    
    # Generate the cache path for storing the resource
    cache_path = os.path.join(domain, resource_path)
    local_path = os.path.join(STATIC_CACHE_DIR, cache_path)
    local_dir = os.path.dirname(local_path)

    # Check if the resource exists locally
    if os.path.exists(local_path) and os.path.isfile(local_path):
        logger.info(f"Serving cached resource: {cache_path}")
        return FileResponse(local_path)
    
    # Resource doesn't exist locally, download it
    logger.info(f"Resource not found locally, downloading: {cache_path}")
    
    # Create the directory structure if it doesn't exist
    os.makedirs(local_dir, exist_ok=True)
    
    # Construct the full URL to download the resource
    full_url = urljoin(DOMAIN_MAPPINGS[domain], resource_path)
    logger.info(f"Downloading from: {full_url}")
    
    try:
        # Download the resource
        response = requests.get(full_url, stream=True)
        
        # Check if the download was successful
        if response.status_code == 200:
            # Save the resource to local file
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"Successfully downloaded and saved: {cache_path}")
            
            # Serve the downloaded resource
            return FileResponse(local_path)
        else:
            logger.error(f"Failed to download resource {cache_path}: Status {response.status_code}")
            raise HTTPException(status_code=response.status_code, detail=f"Failed to download resource: {response.status_code}")
    
    except Exception as e:
        logger.exception(f"Error downloading resource {cache_path}")
        raise HTTPException(status_code=500, detail=f"Error downloading resource: {str(e)}")

# Chart Storage API
def get_all_users_charts(client_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT id, name, symbol, resolution, timestamp
    FROM chart_layouts
    WHERE client_id = %s AND user_id = %s
    ORDER BY timestamp DESC
    ''', (client_id, user_id))
    charts = cursor.fetchall()
    conn.close()
    return {'status': 'ok', 'data': charts}

# Study Templates API helper functions
def get_all_study_templates_list(client_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT name, content
    FROM study_templates
    WHERE client_id = %s AND user_id = %s
    ORDER BY timestamp DESC
    ''', (client_id, user_id))
    
    templates = cursor.fetchall()
    conn.close()
    
    return {'status': 'ok', 'data': templates}

def get_study_template(client_id, user_id, template_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT name, content
    FROM study_templates
    WHERE client_id = %s AND user_id = %s AND name = %s
    ''', (client_id, user_id, template_name))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {'status': 'ok', 'data': {
            'name': row['name'],
            'content': row['content']
        }}
    else:
        raise HTTPException(status_code=404, detail="Template not found")

# Drawing Templates API helper functions
def get_drawing_template(client_id, user_id, tool, name):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT name, content
    FROM drawing_templates
    WHERE name = %s AND client_id = %s AND user_id = %s AND tool = %s
    ''', (name, client_id, user_id, tool))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {'status': 'ok', 'data': {
            'name': row['name'],
            'content': row['content']
        }}
    else:
        raise HTTPException(status_code=404, detail="Drawing template not found")

def get_all_drawing_templates(client_id, user_id, tool):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT name
    FROM drawing_templates
    WHERE client_id = %s AND user_id = %s AND tool = %s
    ORDER BY timestamp DESC
    ''', (client_id, user_id, tool))
    
    templates = cursor.fetchall()
    conn.close()
    
    return {'status': 'ok', 'data': templates}

def get_chart_content(client_id, user_id, chart_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT id, name, content, timestamp, symbol, resolution
    FROM chart_layouts
    WHERE client_id = %s AND user_id = %s AND id = %s
    ''', (client_id, user_id, chart_id))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {'status': 'ok', 'data': {
            'id': row['id'],
            'timestamp': row['timestamp'],
            'name': row['name'],
            'content': row['content'],
            'symbol': row['symbol'],
            'resolution': row['resolution']
        }}
    else:
        raise HTTPException(status_code=404, detail="Chart not found")

# SocketIO Event Handlers
@sio.event
async def connect(sid, environ):
    logger.info(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    logger.info(f"Client disconnected: {sid}")
    # Clean up any active connections
    if sid in active_connections:
        connection_ids = list(active_connections[sid].keys())
        for conn_id in connection_ids:
            proxy = active_connections[sid][conn_id]
            proxy.disconnect()
        del active_connections[sid]

@sio.event
async def tv_ws_connect(sid, data):
    url = data.get('url')
    if not url:
        await sio.emit('tv_ws_error', {'error': 'No URL provided'}, room=sid)
        return
    
    logger.info(f"Received WebSocket proxy request for: {url}")
    
    # Create a new proxy instance
    if sid not in active_connections:
        active_connections[sid] = {}
    
    # Get the current event loop
    loop = asyncio.get_event_loop()
    
    proxy = TradingViewWSProxy(sid, loop)
    connection_id = proxy.connect_to_tradingview(url)
    
    active_connections[sid][connection_id] = proxy
    await sio.emit('tv_ws_connected', {'connectionId': connection_id}, room=sid)

@sio.event
async def tv_ws_send(sid, data):
    connection_id = data.get('connectionId')
    message = data.get('message')
    
    if not message:
        await sio.emit('tv_ws_error', {'error': 'Missing message'}, room=sid)
        return
        
    # If no connectionId provided, try to find the first available connection
    if not connection_id:
        if sid in active_connections and active_connections[sid]:
            # Use the first available connection
            connection_id = next(iter(active_connections[sid]))
            logger.info(f"No connectionId provided, using first available: {connection_id}")
        else:
            await sio.emit('tv_ws_error', {'error': 'No active connections found'}, room=sid)
            return
    
    if sid not in active_connections or connection_id not in active_connections[sid]:
        await sio.emit('tv_ws_error', {'error': f'Connection not found: {connection_id}'}, room=sid)
        return
    
    proxy = active_connections[sid][connection_id]
    success = proxy.send(message)
    
    if not success:
        await sio.emit('tv_ws_error', {'error': 'Failed to send message'}, room=sid)

@sio.event
async def tv_ws_disconnect(sid, data):
    connection_id = data.get('connectionId')
    
    if not connection_id:
        await sio.emit('tv_ws_error', {'error': 'Missing connectionId'}, room=sid)
        return
    
    if sid not in active_connections or connection_id not in active_connections[sid]:
        await sio.emit('tv_ws_error', {'error': 'Connection not found'}, room=sid)
        return
    
    proxy = active_connections[sid][connection_id]
    proxy.disconnect()
    del active_connections[sid][connection_id]
    await sio.emit('tv_ws_disconnected', {'connectionId': connection_id}, room=sid)

# Additional utility functions
def interval_to_seconds(interval):
    """Convert TradingView interval string (like '1D','5m','1h') to seconds"""
    if not interval:
        return 60 * 60  # Default 1 hour
    try:
        unit = interval[-1]
        value = int(interval[:-1]) if not interval[-1].isdigit() else int(interval)
        if unit == 's':
            return value
        elif unit == 'm':
            return value * 60
        elif unit == 'h':
            return value * 60 * 60
        elif unit == 'D':
            return value * 86400
        elif unit == 'W':
            return value * 86400 * 7
        elif unit == 'M':
            return value * 86400 * 30
        else:  # Pure number, default to minutes
            return int(interval) * 60
    except Exception:
        return 60 * 60  # Default 1 hour

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))