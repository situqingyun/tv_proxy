# Apply gevent monkey patching before any other imports
import traceback
from gevent import monkey
monkey.patch_all()

from flask import Flask, render_template, request, send_from_directory, Response, jsonify
from flask_socketio import SocketIO, emit
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
import sqlite3
from datetime import datetime
from api_utils import parse_request_data
import psycopg2
from psycopg2.extras import RealDictCursor

# Load environment variables from .env file if it exists
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Initialize SocketIO with CORS support
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# WebSocket connections tracker
active_connections = {}

# 从环境变量加载配置
REPLAY_BARS_COUNT = int(os.environ.get('REPLAY_BARS_COUNT', '150'))  # 默认回放K线数量
REPLAY_SYMBOLS = os.environ.get('REPLAY_SYMBOLS', 'BATS_DLY:AAPL,BATS_DLY:AAPL').split(',')  # 默认可用交易对
REPLAY_MAX_DAYS = int(os.environ.get('REPLAY_MAX_DAYS', '365'))  # 默认回放最大天数
DEFAULT_REPLAY_INTERVAL = os.environ.get('DEFAULT_REPLAY_INTERVAL', '1D')  # 默认回放周期
REPLAY_EARLIEST_DATE = os.environ.get('REPLAY_EARLIEST_DATE', '2023-01-01')
REPLAY_EARLIEST_TIMESTAMP = int(datetime.strptime(REPLAY_EARLIEST_DATE, '%Y-%m-%d').timestamp())

# PostgreSQL连接配置
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "43.156.51.247"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ.get("DB_NAME", "tvdb"),
    "user": os.environ.get("DB_USER", "tvuser"),
    "password": os.environ.get("DB_PASSWORD", "bsh25fdsad77bxcb")
}

# 连接函数
def get_db_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

# WebSocket proxy handler class
class TradingViewWSProxy:
    def __init__(self, client_sid):
        self.client_sid = client_sid
        self.ws = None
        self.connected = False
        self.connection_id = str(uuid.uuid4())
    
    def connect_to_tradingview(self, url):
        logger.info(f"Connecting to TradingView WebSocket: {url}")
        
        # # 解析并修改 URL 参数
        # parsed = urlparse(url)
        # qs = parse_qs(parsed.query)
        # qs['page-uri'] = ['trading-terminal.tradingview-widget.com']
        # qs['ancestor-origin'] = ['trading-terminal.tradingview-widget.com']
        # new_query = urlencode(qs, doseq=True)
        # new_url = urlunparse(parsed._replace(query=new_query))
        
        # # 设置必要的 headers
        # headers = {
        #     "Origin": "https://trading-terminal.tradingview-widget.com",
        #     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        #     "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        #     "Cache-Control": "no-cache",
        #     "Pragma": "no-cache"
        # }
        
        def on_message(ws, message):
            logger.debug(f"Received message from TradingView: {message[:100]}...")
            # Forward the message to the client
            socketio.emit('tv_message', {'message': message}, room=self.client_sid)
        
        def on_error(ws, error):
            logger.exception(f"Error in TradingView WebSocket connection: {error}")
            socketio.emit('tv_error', {'error': str(error)}, room=self.client_sid)
        
        def on_close(ws, close_status_code, close_msg):
            logger.info(f"TradingView WebSocket connection closed: {close_status_code} {close_msg}")
            self.connected = False
            socketio.emit('tv_disconnect', {}, room=self.client_sid)
        
        def on_open(ws):
            logger.info("TradingView WebSocket connection established")
            self.connected = True
            socketio.emit('tv_connect', {}, room=self.client_sid)
        
        # Create WebSocket connection to TradingView with headers
        self.ws = websocket.WebSocketApp(
            url,
            # header=[f"{k}: {v}" for k, v in headers.items()],
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        
        # Run the WebSocket connection in a separate thread
        wst = threading.Thread(target=self.ws.run_forever)
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

# Configure logging with detailed format
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

# Ensure the cache directory exists
os.makedirs(STATIC_CACHE_DIR, exist_ok=True)

# SQLite database setup
DB_PATH = os.path.join(os.path.dirname(__file__), "tv_charts.db")

def init_db():
    """初始化 PostgreSQL 数据库，创建必要的表"""
    conn = get_db_connection()
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
        position_type TEXT NOT NULL, -- 'long' or 'short'
        status TEXT NOT NULL DEFAULT 'closed', -- 'closed' 或 'liquidated'
        
        entry_time BIGINT NOT NULL,
        exit_time BIGINT NOT NULL,
        entry_price DOUBLE PRECISION NOT NULL,
        exit_price DOUBLE PRECISION NOT NULL,
        
        quantity DOUBLE PRECISION NOT NULL, -- 开仓的币数量
        leverage INTEGER NOT NULL,          -- 使用的杠杆倍数
        margin DOUBLE PRECISION NOT NULL,   -- 投入的保证金
        
        pnl DOUBLE PRECISION NOT NULL,      -- 最终盈亏
        timestamp BIGINT NOT NULL
    )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("数据库初始化完成")

# Initialize the database
init_db()

@app.route('/')
def home():
    return render_template('index.html', title='TV Proxy')

@app.route('/platform')
def platform():
    return render_template('platform.html', title='TV Proxy')

@app.route('/<domain>/<path:resource_path>')
def proxy_tradingview_resource(domain, resource_path):
    """
    Proxy handler for TradingView widget resources.
    If the resource exists locally, serve it from the local cache.
    Otherwise, download it from TradingView website and cache it for future use.
    """
    # Ensure the resource path is sanitized to prevent directory traversal
    if ".." in resource_path:
        return "Invalid resource path", 400
    
    # Check if this is a valid domain we can proxy
    if domain not in DOMAIN_MAPPINGS:
        logger.exception(f"Unknown domain: {domain}")
        return f"Unknown domain: {domain}", 400
    
    # Generate the cache path for storing the resource
    cache_path = os.path.join(domain, resource_path)
    local_path = os.path.join(STATIC_CACHE_DIR, cache_path)
    local_dir = os.path.dirname(local_path)

    # Check if the resource exists locally
    if os.path.exists(local_path) and os.path.isfile(local_path):
        logger.info(f"Serving cached resource: {cache_path}")
        return send_from_directory(os.path.dirname(local_path), os.path.basename(local_path))
    
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
            # Determine the content type
            content_type = response.headers.get('Content-Type')
            
            # Save the resource to local file
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"Successfully downloaded and saved: {cache_path}")
            
            # Serve the downloaded resource
            return send_from_directory(os.path.dirname(local_path), os.path.basename(local_path))
        else:
            logger.exception(f"Failed to download resource {cache_path}: Status {response.status_code}")
            return f"Failed to download resource: {response.status_code}", response.status_code
    
    except Exception as e:
        logger.exception(f"Error downloading resource {cache_path}")
        return f"Error downloading resource: {str(e)}", 500

@app.route('/charting_library/<path:resource_path>')
def proxy_charting_library(resource_path):
    """
    Special handler for charting_library resources which appear to be referenced
    directly without a domain in the HTML.
    """
    domain = "trading-terminal.tradingview-widget.com"
    full_path = f"charting_library/{resource_path}"
    return proxy_tradingview_resource(domain, full_path)

@app.route('/datafeeds/<path:resource_path>')
def proxy_datafeeds(resource_path):
    """
    Special handler for datafeeds resources which appear to be referenced
    directly without a domain in the HTML.
    """
    domain = "trading-terminal.tradingview-widget.com"
    full_path = f"datafeeds/{resource_path}"
    return proxy_tradingview_resource(domain, full_path)

@app.route('/broker-sample/<path:resource_path>')
def proxy_broker_sample(resource_path):
    """
    Special handler for broker-sample resources which appear to be referenced
    directly without a domain in the HTML.
    """
    domain = "trading-terminal.tradingview-widget.com"
    full_path = f"broker-sample/{resource_path}"
    return proxy_tradingview_resource(domain, full_path)

# TradingView Chart Storage API

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
    return jsonify({'status': 'ok', 'data': charts})

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
        return jsonify({'status': 'ok', 'data': {
            'id': row['id'],
            'timestamp': row['timestamp'],
            'name': row['name'],
            'content': row['content'],
            'symbol': row['symbol'],
            'resolution': row['resolution']
        }})
    else:
        return jsonify({'status': 'error', 'message': 'Chart not found'}), 404

@app.route('/saveload.tradingview.com/1.1/charts', methods=['GET'])
def list_charts():
    """List all charts for a user"""
    client_id = request.args.get('client')
    user_id = request.args.get('user')
    chart_id = request.args.get('chart')
    
    if not client_id or not user_id:
        return jsonify({
            'status': 'error',
            'message': 'Missing client_id or user_id'
        })
    

    if chart_id:
        return get_chart_content(client_id, user_id, chart_id)
    else:
        return get_all_users_charts(client_id, user_id)

@app.route('/saveload.tradingview.com/1.1/charts', methods=['POST'])
def save_chart():
    """Save a chart layout"""
    client_id = request.args.get('client')
    user_id = request.args.get('user')
    chart_id = request.args.get('chart')

    if not client_id or not user_id:
        return jsonify({'status': 'error', 'message': 'Missing client_id or user_id'}), 400

    name = request.form.get('name')
    content = request.form.get('content')
    symbol = request.form.get('symbol')
    resolution = request.form.get('resolution')
    
    if not content:
        return jsonify({'status': 'error', 'message': 'Missing content'}), 400

    timestamp = int(datetime.now().timestamp())
    conn = get_db_connection()
    cursor = conn.cursor()

    if chart_id:
        cursor.execute('''
        UPDATE chart_layouts
        SET name = %s, symbol = %s, resolution = %s, content = %s, timestamp = %s
        WHERE id = %s AND client_id = %s AND user_id = %s
        ''', (name, symbol, resolution, content, timestamp, chart_id, client_id, user_id))
    else:
        try:
            chart_data = json.loads(content)
            new_chart_id = str(chart_data.get('id'))
        except (json.JSONDecodeError, KeyError):
            return jsonify({'status': 'error', 'message': 'Invalid content format'}), 400
        
        cursor.execute('''
        INSERT INTO chart_layouts (id, client_id, user_id, name, symbol, resolution, content, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (new_chart_id, client_id, user_id, name, symbol, resolution, content, timestamp))
        chart_id = new_chart_id

    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'id': chart_id})

@app.route('/saveload.tradingview.com/1.1/charts', methods=['DELETE'])
def delete_chart():
    """Delete a specific chart layout"""
    client_id = request.args.get('client')
    user_id = request.args.get('user')
    if not client_id or not user_id:
        return jsonify({
            'status': 'error',
            'message': 'Missing client_id or user_id'
        })
    chart_id = request.args.get('chart')
    if not chart_id:
        return jsonify({
            'status': 'error',
            'message': 'Missing chart_id'
        })
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        DELETE FROM chart_layouts
        WHERE id = %s AND client_id = %s AND user_id = %s
        ''', (chart_id, client_id, user_id))
        conn.commit()
        conn.close()
        return jsonify({
            'status': 'ok'
        })
    except Exception as e:
        logger.exception(f"Error deleting chart {chart_id}")
        return jsonify({
            'status': 'error',
            'message': f'Error deleting chart: {str(e)}'
        }), 500


def get_all_tamplates_list(client_id, user_id):
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
    
    return jsonify({
        'status': 'ok',
        'data': templates
    })

def get_tamplate(client_id, user_id, template_name):
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
        return jsonify({
            'status': 'ok',
            'data': {
                'name': row['name'],
                'content': row['content']
            }
        })
    else:
        return jsonify({
            'status': 'error',
            'message': 'Template not found'
        }), 404

# Study Templates API endpoints
@app.route('/saveload.tradingview.com/1.1/study_templates', methods=['GET'])
def list_study_templates():
    """List all study templates for a user"""
    client_id = request.args.get('client')
    user_id = request.args.get('user')
    
    if not client_id or not user_id:
        return jsonify({
            'status': 'error',
            'message': 'Missing client_id or user_id'
        })
        
    template_name = request.args.get('template', '')
    
    if template_name:
        return get_tamplate(client_id, user_id, template_name)
    else:
        return get_all_tamplates_list(client_id, user_id)

@app.route('/saveload.tradingview.com/1.1/study_templates', methods=['POST'])
def save_study_template():
    """Save a study template"""
    client_id = request.args.get('client')
    user_id = request.args.get('user')
    
    if not client_id or not user_id:
        return jsonify({
            'status': 'error',
            'message': 'Missing client_id or user_id'
        })
    
    # TradingView uses multipart/form-data for POST requests
    template_name = request.form.get('name')
    content = request.form.get('content')
    timestamp = int(datetime.now().timestamp())
    
    if not template_name or not content:
        return jsonify({
            'status': 'error',
            'message': 'Missing template name or content'
        })
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT id FROM study_templates WHERE name = %s AND client_id = %s AND user_id = %s
    ''', (template_name, client_id, user_id))
    
    row = cursor.fetchone()
    if row:
        cursor.execute('''
        UPDATE study_templates
        SET content = %s, timestamp = %s
        WHERE name = %s AND client_id = %s AND user_id = %s
        ''', (content, timestamp, template_name, client_id, user_id))
    else:
        cursor.execute('''
        INSERT INTO study_templates (client_id, user_id, name, content, timestamp, template_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        ''', (client_id, user_id, template_name, content, timestamp, template_name))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'status': 'ok',
        'id': template_name
    })

@app.route('/saveload.tradingview.com/1.1/study_templates', methods=['DELETE'])
def delete_study_template():
    """Delete a specific study template"""
    client_id = request.args.get('client')
    user_id = request.args.get('user')
    template_name = request.args.get('template')

    if not client_id or not user_id:
        return jsonify({'status': 'error', 'message': 'Missing client_id or user_id'}), 400
    
    if not template_name:
        return jsonify({'status': 'error', 'message': 'Missing template name'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
        DELETE FROM study_templates
        WHERE name = %s AND client_id = %s AND user_id = %s
        ''', (template_name, client_id, user_id))
    
        conn.commit()
        conn.close()
    
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.exception(f"Error deleting study template {template_name}: {str(e)}")
        return jsonify({'status': 'error', 'message': f'Error deleting study template: {str(e)}'}), 500


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
        return jsonify({
            'status': 'ok',
            'data': {
                # 'id': row['template_id'],
                'name': row['name'],
                'content': row['content']
            }
        })
    else:
        return jsonify({
            'status': 'error',
            'message': 'Drawing template not found'
        }), 404

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
    
    return jsonify({
        'status': 'ok',
        'data': templates
    })

# Drawing Templates API
@app.route('/saveload.tradingview.com/1.1/drawing_templates', methods=['GET'])
def list_drawing_templates():
    """List all drawing templates for a user"""
    client_id = request.args.get('client')
    user_id = request.args.get('user')
    
    if not client_id or not user_id:
        return jsonify({
            'status': 'error',
            'message': 'Missing client_id or user_id'
        })
    
    name = request.args.get('name', '')
    tool = request.args.get('tool', '')
    if name:
        return get_drawing_template(client_id, user_id, tool, name)
    else:
        return get_all_drawing_templates(client_id, user_id, tool)

@app.route('/saveload.tradingview.com/1.1/drawing_templates', methods=['POST'])
def save_drawing_template():
    """Save a drawing template"""
    client_id = request.args.get('client')
    user_id = request.args.get('user')
    
    if not client_id or not user_id:
        return jsonify({
            'status': 'error',
            'message': 'Missing client_id or user_id'
        }), 400
    
    # TradingView uses multipart/form-data for POST requests
    # The name and tool are in the query string, content is in the form body
    name = request.args.get('name')
    tool = request.args.get('tool')
    content = request.form.get('content')
    
    if not name or not tool or not content:
        return jsonify({
            'status': 'error',
            'message': 'Missing name, tool, or content'
        }), 400
    timestamp = int(datetime.now().timestamp())
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        SELECT id FROM drawing_templates WHERE name = %s AND client_id = %s AND user_id = %s AND tool = %s
        ''', (name, client_id, user_id, tool))
        
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
            ''', (name, client_id, user_id, tool, content, timestamp, name))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception(f"Error saving drawing template: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()
    
    return jsonify({
        'status': 'ok'
    })

@app.route('/saveload.tradingview.com/1.1/drawing_templates', methods=['DELETE'])
def delete_drawing_template():
    """Delete a specific drawing template"""
    client_id = request.args.get('client')
    user_id = request.args.get('user')
    tool = request.args.get('tool')
    name = request.args.get('name')

    if not client_id or not user_id:
        return jsonify({'status': 'error', 'message': 'Missing client_id or user_id'}), 400
    
    if not tool or not name:
        return jsonify({'status': 'error', 'message': 'Missing tool or name'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
        DELETE FROM drawing_templates
        WHERE name = %s AND client_id = %s AND user_id = %s AND tool = %s
        ''', (name, client_id, user_id, tool))
    
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception(f"Error deleting drawing template {name} for tool {tool}: {str(e)}")
        return jsonify({'status': 'error', 'message': f'Error deleting drawing template: {str(e)}'}), 500
    finally:
        conn.close()
    
    return jsonify({'status': 'ok'})

# Socket.IO event handlers
@socketio.on('connect')
def handle_connect():
    logger.info(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"Client disconnected: {request.sid}")
    # Clean up any active connections
    if request.sid in active_connections:
        connection_ids = list(active_connections[request.sid].keys())
        for conn_id in connection_ids:
            proxy = active_connections[request.sid][conn_id]
            proxy.disconnect()
        del active_connections[request.sid]

@socketio.on('tv_ws_connect')
def handle_tv_ws_connect(data):
    url = data.get('url')
    if not url:
        emit('tv_ws_error', {'error': 'No URL provided'})
        return
    
    logger.info(f"Received WebSocket proxy request for: {url}")
    
    # Create a new proxy instance
    if request.sid not in active_connections:
        active_connections[request.sid] = {}
    
    proxy = TradingViewWSProxy(request.sid)
    connection_id = proxy.connect_to_tradingview(url)
    
    active_connections[request.sid][connection_id] = proxy
    emit('tv_ws_connected', {'connectionId': connection_id})

@socketio.on('tv_ws_send')
def handle_tv_ws_send(data):
    connection_id = data.get('connectionId')
    message = data.get('message')
    
    if not message:
        emit('tv_ws_error', {'error': 'Missing message'})
        return
        
    # If no connectionId provided, try to find the first available connection
    if not connection_id:
        if request.sid in active_connections and active_connections[request.sid]:
            # Use the first available connection
            connection_id = next(iter(active_connections[request.sid]))
            logger.info(f"No connectionId provided, using first available: {connection_id}")
        else:
            emit('tv_ws_error', {'error': 'No active connections found'})
            return
    
    if request.sid not in active_connections or connection_id not in active_connections[request.sid]:
        emit('tv_ws_error', {'error': f'Connection not found: {connection_id}'})
        return
    
    proxy = active_connections[request.sid][connection_id]
    success = proxy.send(message)
    
    if not success:
        emit('tv_ws_error', {'error': 'Failed to send message'})

@socketio.on('tv_ws_disconnect')
def handle_tv_ws_disconnect(data):
    connection_id = data.get('connectionId')
    
    if not connection_id:
        emit('tv_ws_error', {'error': 'Missing connectionId'})
        return
    
    if request.sid not in active_connections or connection_id not in active_connections[request.sid]:
        emit('tv_ws_error', {'error': 'Connection not found'})
        return
    
    proxy = active_connections[request.sid][connection_id]
    proxy.disconnect()
    del active_connections[request.sid][connection_id]
    emit('tv_ws_disconnected', {'connectionId': connection_id})

@app.route('/ws-proxy-url')
def ws_proxy_url():
    """Return the WebSocket proxy URL for the client"""
    base_url = request.host_url.replace('http://', 'ws://').replace('https://', 'wss://')
    if base_url.endswith('/'):
        base_url = base_url[:-1]
    return jsonify({'proxyUrl': base_url})

@app.route('/save-trade', methods=['POST'])
def save_trade():
    """Save a trade record"""
    try:
        data = request.json
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'Missing trade data'
            })
        
        # 验证必要字段
        required_fields = [
            'symbol', 'position_type', 'entry_time', 'exit_time',
            'entry_price', 'exit_price', 'pnl', 'timestamp',
            'quantity', 'leverage', 'margin'
        ]
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'status': 'error',
                    'message': f'Missing required field: {field}'
                })
        
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
                data.get('interval', '1D'), # 从新数据中获取或使用默认值
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
            data.get('status', 'closed'), # 'closed' 或 'liquidated'
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
        # 如果是首次交易，设置起始价格为入场价格
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
        
        return jsonify({
            'status': 'ok',
            'message': 'Trade record saved successfully',
            'data': response_data
        })
        
    except Exception as e:
        logger.exception(f"Error saving trade record: {traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': f'Error saving trade record: {str(e)}'
        })

@app.route('/trade-statistics', methods=['GET'])
def trade_statistics():
    """获取交易统计数据"""
    try:
        # 可选参数：symbol和interval用于过滤特定交易品种和时间周期
        symbol = request.args.get('symbol', '')
        interval = request.args.get('interval', '')
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
            # 简单地以入场价格作为投入资金计算
            total_invested += trade['entry_price']
        
        # 计算盈利率 = 总盈亏/总投入资金
        profit_rate = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        
        conn.close()
        
        return jsonify({
            'status': 'ok',
            'data': {
                'total_trades': total_trades,
                'profitable_trades': profitable_trades,
                'win_rate': round(win_rate, 2),  # 成功率，保留两位小数
                'total_pnl': round(total_pnl, 2),  # 总盈亏，保留两位小数
                'profit_rate': round(profit_rate, 2)  # 盈利率，保留两位小数
            }
        })
        
    except Exception as e:
        logger.exception(f"Error getting trade statistics: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error getting trade statistics: {str(e)}'
        })

@app.route('/api/replay/random', methods=['GET'])
def get_random_replay_point():
    """获取随机回放起始点（受最早回放日期和bars_count*interval限制）"""
    try:
        symbol = request.args.get('symbol', '')
        bars_count = request.args.get('bars_count', REPLAY_BARS_COUNT)
        interval = request.args.get('interval', DEFAULT_REPLAY_INTERVAL)  # 默认1天

        try:
            bars_count = int(bars_count)
            if bars_count <= 0:
                bars_count = REPLAY_BARS_COUNT
        except:
            bars_count = REPLAY_BARS_COUNT

        # interval转秒数
        interval_seconds = interval_to_seconds(interval)

        # 没有指定symbol则随机
        if not symbol:
            import random
            symbol = random.choice(REPLAY_SYMBOLS)

        import time
        import random
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
            random_start_time = random.randint(earliest_time, latest_time)

        return jsonify({
            'status': 'ok',
            'data': {
                'symbol': symbol,
                'start_time': random_start_time,
                'bars_count': bars_count
            }
        })
    except Exception as e:
        logger.exception(f"Error generating random replay point: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error generating random replay point: {str(e)}'
        })

@app.route('/api/replay/sessions', methods=['POST'])
def create_replay_session():
    """创建新的回放会话
    
    当用户进行第一次平仓操作时调用，创建一个新的回放会话记录
    """
    try:
        data = request.json
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'Missing session data'
            })
        
        # 验证必要字段
        required_fields = ['symbol', 'interval', 'start_time', 'client_id', 'user_id']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'status': 'error',
                    'message': f'Missing required field: {field}'
                })
        
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
        
        return jsonify({
            'status': 'ok',
            'data': {
                'session_id': session_id,
                'session_uuid': session_uuid
            }
        })
        
    except Exception as e:
        logger.exception(f"Error creating replay session: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error creating replay session: {str(e)}'
        }), 500

@app.route('/api/replay/sessions/<session_uuid>', methods=['GET'])
def get_replay_session(session_uuid):
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
            return jsonify({
                'status': 'error',
                'message': 'Replay session not found'
            })
        
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
        
        return jsonify({
            'status': 'ok',
            'data': session_data
        })
        
    except Exception as e:
        logger.exception(f"Error getting replay session: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error getting replay session: {str(e)}'
        })

@app.route('/api/replay/sessions/<session_uuid>', methods=['PUT'])
def update_replay_session(session_uuid):
    """更新回放会话信息
    
    可以更新会话的结束时间等信息
    """
    try:
        data = request.json
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'Missing update data'
            })
        
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
            return jsonify({
                'status': 'error',
                'message': 'No valid fields to update'
            })
        
        # 执行更新
        cursor.execute(f'''
        UPDATE replay_sessions
        SET {', '.join(update_fields)}
        WHERE session_uuid = %s
        ''', update_values)
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({
                'status': 'error',
                'message': 'Replay session not found'
            }), 404
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'ok',
            'message': 'Replay session updated successfully'
        })
        
    except Exception as e:
        logger.exception(f"Error updating replay session: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error updating replay session: {str(e)}'
        }), 500

@app.route('/api/replay/sessions/<session_uuid>/market-price', methods=['POST'])
def update_session_market_price(session_uuid):
    """更新会话的市场价格信息"""
    try:
        data = request.json
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'Missing price data'
            })
        
        # 验证必要字段
        required_fields = ['price', 'price_type']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'status': 'error',
                    'message': f'Missing required field: {field}'
                })
        
        price = data['price']
        price_type = data['price_type']  # 'start' or 'end'
        
        if price_type not in ['start', 'end']:
            return jsonify({
                'status': 'error',
                'message': 'price_type must be "start" or "end"'
            })
        
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
            return jsonify({
                'status': 'error',
                'message': 'Replay session not found'
            }), 404
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'ok',
            'message': 'Market price updated successfully'
        })
        
    except Exception as e:
        logger.exception(f"Error updating session market price: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error updating session market price: {str(e)}'
        }), 500

@app.route('/api/replay/sessions', methods=['GET'])
def list_replay_sessions():
    """分页查询回放会话列表，支持前端下滑翻页"""
    try:
        # 获取分页参数
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
        offset = (page - 1) * page_size

        # 可选过滤参数
        client_id = request.args.get('client_id', None)
        user_id = request.args.get('user_id', None)

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
        
        return jsonify({
            'status': 'ok',
            'data': sessions_list,
            'total': total,
            'page': page,
            'page_size': page_size
        })
    except Exception as e:
        logger.exception(f"Error listing replay sessions: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

def interval_to_seconds(interval):
    """将TradingView周期字符串（如'1D','5m','1h'）转为秒数"""
    if not interval:
        return 60 * 60  # 默认1小时
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
        else:  # 纯数字，默认为分钟
            return int(interval) * 60
    except Exception:
        return 60 * 60  # 默认1小时

if __name__ == "__main__":
    socketio.run(app, debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
