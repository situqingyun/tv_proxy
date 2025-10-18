# Project Overview

This project is a FastAPI-based TV proxy application. It is designed to proxy requests to TradingView's charting library and data feeds. It also provides a WebSocket proxy for real-time data and a REST API for saving and loading chart layouts, study templates, and trade data. The application uses a PostgreSQL database to store user-specific information.

The project is currently in a transitional phase, with both a Flask (`main.py`) and a FastAPI (`main_fastapi.py`) implementation present. The FastAPI version appears to be the more current and feature-rich of the two.

## Building and Running

The project uses `uv` for dependency management.

**1. Install dependencies:**

```bash
uv sync
```

**2. Run the application:**

To run the FastAPI application:

```bash
uvicorn main_fastapi:app --reload
```

The application will be available at `http://localhost:5000`.

## Development Conventions

### API

The core of the application is the FastAPI server in `main_fastapi.py`. It exposes several endpoints:

*   `/`: Serves the main HTML page.
*   `/ws-proxy-url`: Provides the WebSocket proxy URL.
*   `/saveload.tradingview.com/...`: A series of endpoints that proxy requests to TradingView's save/load API for charts, study templates, and drawing templates.
*   `/api/...`: Custom API endpoints for saving and retrieving trade data and replay sessions.

### Database

The application uses a PostgreSQL database to store chart layouts, study templates, drawing templates, and trade data. The database schema is defined and initialized in the `init_db()` function in `main_fastapi.py`.

### WebSocket Proxy

The application includes a WebSocket proxy that forwards messages between the client and TradingView's WebSocket server. The proxy is implemented using `python-socketio` and is handled by the `TradingViewWSProxy` class.

### Frontend

The frontend consists of HTML templates located in the `templates` directory. The main page is `index.html`, which loads the TradingView charting library.
