"""
回放功能API路由
处理TradingView回放会话和交易记录
"""

from fastapi import APIRouter, Query, Request, HTTPException
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import time
import uuid
import random
import logging
import traceback

logger = logging.getLogger(__name__)

router = APIRouter()


def get_db_connection(db_config):
    return psycopg2.connect(**db_config, cursor_factory=RealDictCursor)


def interval_to_seconds(interval):
    """将TradingView interval字符串转换为秒数"""
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
        else:  # 纯数字,默认为分钟
            return int(interval) * 60
    except Exception:
        return 60 * 60


def create_replay_router(db_config: dict, replay_config: dict) -> APIRouter:
    """创建回放路由"""

    @router.get('/api/replay/random')
    async def get_random_replay_point(
        symbol: Optional[str] = Query(None),
        bars_count: Optional[int] = Query(replay_config.get('REPLAY_BARS_COUNT', 150)),
        interval: Optional[str] = Query(replay_config.get('DEFAULT_REPLAY_INTERVAL', '1D'))
    ):
        """获取随机回放起始点"""
        try:
            if bars_count is None or bars_count <= 0:
                bars_count = replay_config.get('REPLAY_BARS_COUNT', 150)

            interval_seconds = interval_to_seconds(interval)

            if not symbol:
                symbol = random.choice(replay_config.get('REPLAY_SYMBOLS', ['BATS_DLY:AAPL']))

            current_time = int(time.time())
            earliest_time = replay_config.get('REPLAY_EARLIEST_TIMESTAMP', int(datetime.strptime('2023-01-01', '%Y-%m-%d').timestamp()))
            latest_time = current_time - (bars_count * interval_seconds)
            if latest_time < earliest_time:
                latest_time = earliest_time

            if earliest_time >= latest_time:
                random_start_time = earliest_time
            else:
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

    @router.post('/save-trade')
    async def save_trade(request: Request):
        """保存交易记录"""
        try:
            data = await request.json()
            if not data:
                raise HTTPException(status_code=400, detail="Missing trade data")

            required_fields = [
                'symbol', 'position_type', 'entry_time', 'exit_time',
                'entry_price', 'exit_price', 'pnl', 'timestamp',
                'quantity', 'leverage', 'margin'
            ]
            for field in required_fields:
                if field not in data:
                    raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

            conn = get_db_connection(db_config)
            cursor = conn.cursor()

            replay_session_id = data.get('replay_session_id', None)
            response_data = {}

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

            if data.get('is_first_trade', False):
                entry_price = data['entry_price']
                cursor.execute('''
                UPDATE replay_sessions
                SET price_start = %s
                WHERE session_uuid = %s
                ''', (entry_price, replay_session_id))

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

    @router.get('/trade-statistics')
    async def trade_statistics(
        symbol: Optional[str] = Query(None),
        interval: Optional[str] = Query(None)
    ):
        """获取交易统计数据"""
        try:
            logger.info(f"获取交易统计数据: symbol='{symbol}', interval='{interval}'")
            conn = get_db_connection(db_config)
            cursor = conn.cursor()

            query_conditions = []
            query_params = []

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

            where_clause = ""
            if query_conditions:
                where_clause = "WHERE " + " AND ".join(query_conditions)

            cursor.execute(f'''
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as profitable_trades,
                SUM(t.pnl) as total_pnl
            {base_query_from}
            {where_clause}
            ''', query_params)

            result = cursor.fetchone()

            total_trades = result['total_trades'] or 0
            profitable_trades = result['profitable_trades'] or 0
            total_pnl = result['total_pnl'] or 0

            win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0

            cursor.execute(f'''
            SELECT t.position_type, t.entry_price, t.exit_price, t.pnl
            {base_query_from}
            {where_clause}
            ''', query_params)

            trades = cursor.fetchall()

            total_invested = 0
            for trade in trades:
                total_invested += trade['entry_price']

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

    @router.post('/api/replay/sessions')
    async def create_replay_session(request: Request):
        """创建新的回放会话"""
        try:
            data = await request.json()
            if not data:
                raise HTTPException(status_code=400, detail="Missing session data")

            required_fields = ['symbol', 'interval', 'start_time', 'client_id', 'user_id']
            for field in required_fields:
                if field not in data:
                    raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

            session_uuid = str(uuid.uuid4())
            current_time = int(time.time())

            bars_count = data.get('bars_count', 150)
            try:
                bars_count = int(bars_count)
            except:
                bars_count = 150

            conn = get_db_connection(db_config)
            cursor = conn.cursor()

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

    @router.get('/api/replay/sessions/{session_uuid}')
    async def get_replay_session(session_uuid: str):
        """获取回放会话信息"""
        try:
            conn = get_db_connection(db_config)
            cursor = conn.cursor()

            cursor.execute('''
            SELECT id, session_uuid, client_id, user_id, symbol, interval,
                   start_time, end_time, bars_count, created_at, updated_at
            FROM replay_sessions
            WHERE session_uuid = %s
            ''', (session_uuid,))

            session = cursor.fetchone()
            if not session:
                raise HTTPException(status_code=404, detail="Replay session not found")

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

    @router.put('/api/replay/sessions/{session_uuid}')
    async def update_replay_session(session_uuid: str, request: Request):
        """更新回放会话信息"""
        try:
            data = await request.json()
            if not data:
                raise HTTPException(status_code=400, detail="Missing update data")

            current_time = int(time.time())

            conn = get_db_connection(db_config)
            cursor = conn.cursor()

            update_fields = []
            update_values = []

            allowed_fields = ['end_time', 'interval', 'bars_count']

            for field in allowed_fields:
                if field in data:
                    update_fields.append(f"{field} = %s")
                    update_values.append(data[field])

            update_fields.append("updated_at = %s")
            update_values.append(current_time)

            update_values.append(session_uuid)

            if not update_fields:
                raise HTTPException(status_code=400, detail="No valid fields to update")

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

    @router.post('/api/replay/sessions/{session_uuid}/market-price')
    async def update_session_market_price(session_uuid: str, request: Request):
        """更新会话的市场价格信息"""
        try:
            data = await request.json()
            if not data:
                raise HTTPException(status_code=400, detail="Missing price data")

            required_fields = ['price', 'price_type']
            for field in required_fields:
                if field not in data:
                    raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

            price = data['price']
            price_type = data['price_type']

            if price_type not in ['start', 'end']:
                raise HTTPException(status_code=400, detail='price_type must be "start" or "end"')

            conn = get_db_connection(db_config)
            cursor = conn.cursor()

            if price_type == 'start':
                cursor.execute('''
                UPDATE replay_sessions
                SET market_price_start = %s, updated_at = %s
                WHERE session_uuid = %s
                ''', (price, int(time.time()), session_uuid))
            else:
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

    @router.get('/api/replay/sessions')
    async def list_replay_sessions(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        client_id: Optional[str] = Query(None),
        user_id: Optional[str] = Query(None)
    ):
        """分页查询回放会话列表"""
        try:
            offset = (page - 1) * page_size

            conn = get_db_connection(db_config)
            cursor = conn.cursor()

            where_clauses = []
            params = []
            if client_id:
                where_clauses.append('rs.client_id = %s')
                params.append(client_id)
            if user_id:
                where_clauses.append('rs.user_id = %s')
                params.append(user_id)
            where_sql = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''

            cursor.execute(f'SELECT COUNT(*) FROM replay_sessions rs {where_sql}', params)
            total = cursor.fetchone()['count']

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

    return router
