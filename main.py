# Apply gevent monkey patching before any other imports
from gevent import monkey
monkey.patch_all()

from flask import Flask, render_template, request, send_from_directory, Response, jsonify
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
import os
import requests
import logging
from urllib.parse import urljoin, urlparse, parse_qs
import mimetypes
import pathlib
import websocket
import json
import threading
import time
import uuid

# Load environment variables from .env file if it exists
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Initialize SocketIO with CORS support
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# WebSocket connections tracker
active_connections = {}

# WebSocket proxy handler class
class TradingViewWSProxy:
    def __init__(self, client_sid):
        self.client_sid = client_sid
        self.ws = None
        self.connected = False
        self.connection_id = str(uuid.uuid4())
    
    def connect_to_tradingview(self, url):
        logger.info(f"Connecting to TradingView WebSocket: {url}")
        
        def on_message(ws, message):
            logger.debug(f"Received message from TradingView: {message[:100]}...")
            # Forward the message to the client
            socketio.emit('tv_message', {'message': message}, room=self.client_sid)
        
        def on_error(ws, error):
            logger.error(f"Error in TradingView WebSocket connection: {error}")
            socketio.emit('tv_error', {'error': str(error)}, room=self.client_sid)
        
        def on_close(ws, close_status_code, close_msg):
            logger.info(f"TradingView WebSocket connection closed: {close_status_code} {close_msg}")
            self.connected = False
            socketio.emit('tv_disconnect', {}, room=self.client_sid)
        
        def on_open(ws):
            logger.info("TradingView WebSocket connection established")
            self.connected = True
            socketio.emit('tv_connect', {}, room=self.client_sid)
        
        # Create WebSocket connection to TradingView
        self.ws = websocket.WebSocketApp(url,
                                        on_open=on_open,
                                        on_message=on_message,
                                        on_error=on_error,
                                        on_close=on_close)
        
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
            logger.error("Cannot send message, WebSocket not connected")
            return False
    
    def disconnect(self):
        if self.ws:
            logger.info("Closing TradingView WebSocket connection")
            self.ws.close()
            self.ws = None
            self.connected = False

# Configure logging
logging.basicConfig(level=logging.INFO)
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

@app.route('/')
def home():
    return render_template('index.html', title='TV Proxy')

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
        logger.error(f"Unknown domain: {domain}")
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
            logger.error(f"Failed to download resource {cache_path}: Status {response.status_code}")
            return f"Failed to download resource: {response.status_code}", response.status_code
    
    except Exception as e:
        logger.error(f"Error downloading resource {cache_path}: {str(e)}")
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

if __name__ == "__main__":
    socketio.run(app, debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
