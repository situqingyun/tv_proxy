"""
TV Proxy - FastAPI主应用
TradingView图表代理服务,支持OKX数据源集成
"""

import asyncio
import ssl
import os
import logging
import base64
import uuid
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import socketio
from dotenv import load_dotenv
import requests
import websocket
import threading
from pydantic import BaseModel

# 导入内部模块
from models.database import init_db
from services.okx_service import OKXService
from routes.okx_routes import create_okx_router
from routes.chart_routes import create_chart_router
from routes.replay_routes import create_replay_router

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s() - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 初始化FastAPI应用
app = FastAPI(title="TV Proxy", description="TradingView数据代理服务", version="1.0.0")

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 模板引擎
templates = Jinja2Templates(directory="templates")

# SocketIO
sio = socketio.AsyncServer(cors_allowed_origins="*", async_mode='asgi')
socket_app = socketio.ASGIApp(sio, app)

# WebSocket连接跟踪
active_connections = {}

# ======================
# 配置加载
# ======================

# 数据库配置
DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "dbname": os.environ.get("DB_NAME"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD")
}

# OKX API配置
OKX_CONFIG = {
    "api_key": os.environ.get("OKX_API_KEY", ""),
    "secret_key": os.environ.get("OKX_SECRET_KEY", ""),
    "passphrase": os.environ.get("OKX_PASSPHRASE", ""),
    "flag": os.environ.get("OKX_FLAG", "0")
}

# 回放配置
REPLAY_CONFIG = {
    "REPLAY_BARS_COUNT": int(os.environ.get('REPLAY_BARS_COUNT', '150')),
    "REPLAY_SYMBOLS": os.environ.get('REPLAY_SYMBOLS', 'BATS_DLY:AAPL,BATS_DLY:AAPL').split(','),
    "DEFAULT_REPLAY_INTERVAL": os.environ.get('DEFAULT_REPLAY_INTERVAL', '1D'),
    "REPLAY_EARLIEST_DATE": os.environ.get('REPLAY_EARLIEST_DATE', '2023-01-01'),
    "REPLAY_EARLIEST_TIMESTAMP": int(datetime.strptime(
        os.environ.get('REPLAY_EARLIEST_DATE', '2023-01-01'), '%Y-%m-%d'
    ).timestamp())
}

# TradingView域名映射
DOMAIN_MAPPINGS = {
    "trading-terminal.tradingview-widget.com": "https://trading-terminal.tradingview-widget.com/",
    "demo-feed-data.tradingview.com": "https://demo-feed-data.tradingview.com/",
    "saveload.tradingview.com": "https://saveload.tradingview.com/",
    "www.tradingview.com": "https://www.tradingview.com/"
}

# 缓存目录
STATIC_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "static_cache")
SNAPSHOTS_DIR = os.path.join(os.path.dirname(__file__), "..", "snapshots")
os.makedirs(STATIC_CACHE_DIR, exist_ok=True)
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

# ======================
# 初始化服务
# ======================

# 初始化数据库
init_db(DB_CONFIG)

# 初始化OKX服务
okx_service = OKXService(DB_CONFIG, OKX_CONFIG)

# 注册路由
app.include_router(create_okx_router(okx_service))
app.include_router(create_chart_router(DB_CONFIG))
app.include_router(create_replay_router(DB_CONFIG, REPLAY_CONFIG))

# 挂载静态文件
app.mount("/snapshots", StaticFiles(directory=SNAPSHOTS_DIR), name="snapshots")


# ======================
# WebSocket代理类
# ======================

class TradingViewWSProxy:
    """TradingView WebSocket代理"""

    def __init__(self, client_sid, loop):
        self.client_sid = client_sid
        self.ws = None
        self.connected = False
        self.connection_id = str(uuid.uuid4())
        self.loop = loop

    def connect_to_tradingview(self, url):
        logger.info(f"Connecting to TradingView WebSocket: {url}")

        # 解析并修改 URL 参数
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        qs['page-uri'] = ['trading-terminal.tradingview-widget.com']
        qs['ancestor-origin'] = ['trading-terminal.tradingview-widget.com']
        new_query = urlencode(qs, doseq=True)
        new_url = urlunparse(parsed._replace(query=new_query))

        logger.info(f"Modified URL: {new_url}")

        # 设置必要的 headers
        headers = {
            "Origin": "https://trading-terminal.tradingview-widget.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        }

        def on_message(ws, message):
            logger.debug(f"Received message from TradingView: {message[:100]}...")
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

        sslopt = {
            "cert_reqs": ssl.CERT_NONE,
            "check_hostname": False,
            "ssl_version": ssl.PROTOCOL_TLS
        }

        # 创建 WebSocket 连接,使用修改后的 URL 和 headers
        self.ws = websocket.WebSocketApp(
            new_url,
            header=[f"{k}: {v}" for k, v in headers.items()],
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )

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
            logger.error("Cannot send message, WebSocket not connected")
            return False

    def disconnect(self):
        if self.ws:
            logger.info("Closing TradingView WebSocket connection")
            self.ws.close()
            self.ws = None
            self.connected = False


# ======================
# HTTP路由
# ======================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """首页"""
    return templates.TemplateResponse("index.html", {"request": request, "title": "TV Proxy"})


@app.get("/platform", response_class=HTMLResponse)
async def platform(request: Request):
    """交易平台页面"""
    return templates.TemplateResponse("platform.html", {"request": request, "title": "TV Proxy"})


@app.get("/okx", response_class=HTMLResponse)
async def okx_page(request: Request):
    """OKX数据源页面"""
    return templates.TemplateResponse("okx.html", {"request": request, "title": "OKX Data Source - Advanced Charts"})


@app.get("/favicon.ico")
async def favicon():
    raise HTTPException(status_code=404, detail="Not found")


@app.get('/ws-proxy-url')
async def ws_proxy_url(request: Request):
    """返回WebSocket代理URL"""
    base_url = str(request.base_url).replace('http://', 'ws://').replace('https://', 'wss://')
    if base_url.endswith('/'):
        base_url = base_url[:-1]
    return {'proxyUrl': base_url}


# 快照功能
class SnapshotData(BaseModel):
    data: str


@app.post("/api/snapshot")
async def create_snapshot(snapshot: SnapshotData, request: Request):
    """接收TradingView图表快照,保存为图片并返回URL"""
    try:
        header, encoded = snapshot.data.split(",", 1)
        image_data = base64.b64decode(encoded)

        filename = f"{uuid.uuid4()}.png"
        file_path = os.path.join(SNAPSHOTS_DIR, filename)

        with open(file_path, "wb") as f:
            f.write(image_data)

        logger.info(f"Snapshot saved to {file_path}")

        image_url = f"{str(request.base_url).rstrip('/')}/snapshots/{filename}"

        return {
            "status": "ok",
            "url": image_url
        }

    except Exception as e:
        logger.exception("Error processing snapshot")
        raise HTTPException(status_code=500, detail=f"Error processing snapshot: {str(e)}")


# TradingView资源代理
@app.get("/charting_library/{resource_path:path}")
async def proxy_charting_library(resource_path: str):
    domain = "trading-terminal.tradingview-widget.com"
    full_path = f"charting_library/{resource_path}"
    return await proxy_tradingview_resource(domain, full_path)


@app.get("/datafeeds/{resource_path:path}")
async def proxy_datafeeds(resource_path: str):
    domain = "trading-terminal.tradingview-widget.com"
    full_path = f"datafeeds/{resource_path}"
    return await proxy_tradingview_resource(domain, full_path)


@app.get("/broker-sample/{resource_path:path}")
async def proxy_broker_sample(resource_path: str):
    domain = "trading-terminal.tradingview-widget.com"
    full_path = f"broker-sample/{resource_path}"
    return await proxy_tradingview_resource(domain, full_path)


@app.get("/trading-terminal.tradingview-widget.com/{resource_path:path}")
async def proxy_trading_terminal(resource_path: str):
    return await proxy_tradingview_resource("trading-terminal.tradingview-widget.com", resource_path)


@app.get("/demo-feed-data.tradingview.com/{resource_path:path}")
async def proxy_demo_feed(resource_path: str):
    return await proxy_tradingview_resource("demo-feed-data.tradingview.com", resource_path)


@app.get("/www.tradingview.com/{resource_path:path}")
async def proxy_www_tradingview(resource_path: str):
    return await proxy_tradingview_resource("www.tradingview.com", resource_path)


@app.get("/{domain}/{resource_path:path}")
async def proxy_tradingview_resource(domain: str, resource_path: str):
    """TradingView资源代理处理器"""
    if domain in ["api", "static", "templates", "snapshots", "saveload.tradingview.com", "src"]:
        logger.error(f"Non-proxy route incorrectly routed to proxy handler: /{domain}/{resource_path}")
        raise HTTPException(status_code=404, detail=f"Invalid request.")

    if ".." in resource_path:
        raise HTTPException(status_code=400, detail="Invalid resource path")

    if domain not in DOMAIN_MAPPINGS:
        logger.error(f"Unknown domain: {domain}")
        raise HTTPException(status_code=400, detail=f"Unknown domain: {domain}")

    cache_path = os.path.join(domain, resource_path)
    local_path = os.path.join(STATIC_CACHE_DIR, cache_path)
    local_dir = os.path.dirname(local_path)

    if os.path.exists(local_path) and os.path.isfile(local_path):
        logger.info(f"Serving cached resource: {cache_path}")
        return FileResponse(local_path)

    logger.info(f"Resource not found locally, downloading: {cache_path}")

    os.makedirs(local_dir, exist_ok=True)

    full_url = urljoin(DOMAIN_MAPPINGS[domain], resource_path)
    logger.info(f"Downloading from: {full_url}")

    try:
        response = requests.get(full_url, stream=True)

        if response.status_code == 200:
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            logger.info(f"Successfully downloaded and saved: {cache_path}")
            return FileResponse(local_path)
        else:
            logger.error(f"Failed to download resource {cache_path}: Status {response.status_code}")
            raise HTTPException(status_code=response.status_code, detail=f"Failed to download resource")

    except Exception as e:
        logger.exception(f"Error downloading resource {cache_path}")
        raise HTTPException(status_code=500, detail=f"Error downloading resource: {str(e)}")


# ======================
# SocketIO事件处理
# ======================

@sio.event
async def connect(sid, environ):
    logger.info(f"Client connected: {sid}")


@sio.event
async def disconnect(sid):
    logger.info(f"Client disconnected: {sid}")
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

    if sid not in active_connections:
        active_connections[sid] = {}

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

    if not connection_id:
        if sid in active_connections and active_connections[sid]:
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


# ======================
# 应用启动
# ======================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
