# TV Proxy

A Flask-based TV proxy application that loads the charting_library from TradingView's official demo.

## Setup

This project uses uv for dependency management.

### Prerequisites

- Python 3.10 or higher
- uv package manager

### Installation

1. Clone the repository

2. Install dependencies using uv:
   ```
   uv sync
   ```

3. Create a `.env` file (already included with default settings)

### Running the Application

```
python main.py
```

The application will be available at http://localhost:5000

## Project Structure

```
├── main.py           # Flask application entry point
├── static/           # Static files (CSS, JS)
│   ├── css/          # CSS stylesheets
│   └── js/           # JavaScript files
│   └── charting_library/ # TradingView charting library obtained from official demo
├── templates/        # HTML templates
└── .env              # Environment variables
```

## Disclaimer

This project is for learning purposes only. The charting_library is obtained from TradingView's official demo.

**Important:** Please request authorization from TradingView's official website before using the charting_library in any production environment. Visit [TradingView's website](https://www.tradingview.com/HTML5-stock-forex-bitcoin-charting-library/) for more information on licensing.