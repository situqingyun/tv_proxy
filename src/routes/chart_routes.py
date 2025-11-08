"""
图表存储API路由
处理TradingView图表、模板的保存和加载
"""

from fastapi import APIRouter, Query, Form, HTTPException
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import json
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


def get_db_connection(db_config):
    return psycopg2.connect(**db_config, cursor_factory=RealDictCursor)


def create_chart_router(db_config: dict) -> APIRouter:
    """创建图表路由"""

    # ============= Chart Layouts =============

    @router.get('/saveload.tradingview.com/1.1/charts')
    async def list_charts(
        client: str = Query(..., alias="client"),
        user: str = Query(..., alias="user"),
        chart: Optional[str] = Query(None, alias="chart")
    ):
        """列出用户的所有图表或获取特定图表"""
        if not client or not user:
            raise HTTPException(status_code=400, detail="Missing client_id or user_id")

        if chart:
            return get_chart_content(db_config, client, user, chart)
        else:
            return get_all_users_charts(db_config, client, user)

    @router.post('/saveload.tradingview.com/1.1/charts')
    async def save_chart(
        client: str = Query(..., alias="client"),
        user: str = Query(..., alias="user"),
        chart: Optional[str] = Query(None, alias="chart"),
        name: str = Form(...),
        content: str = Form(...),
        symbol: str = Form(...),
        resolution: str = Form(...)
    ):
        """保存图表布局"""
        if not client or not user:
            raise HTTPException(status_code=400, detail="Missing client_id or user_id")

        if not content:
            raise HTTPException(status_code=400, detail="Missing content")

        timestamp = int(datetime.now().timestamp())
        conn = get_db_connection(db_config)
        cursor = conn.cursor()

        if chart:
            cursor.execute('''
            UPDATE chart_layouts
            SET name = %s, symbol = %s, resolution = %s, content = %s, timestamp = %s
            WHERE id = %s AND client_id = %s AND user_id = %s
            ''', (name, symbol, resolution, content, timestamp, chart, client, user))
        else:
            new_chart_id = str(uuid.uuid4())

            try:
                chart_data = json.loads(content)
                chart_data['id'] = new_chart_id
                content = json.dumps(chart_data)
            except (json.JSONDecodeError, ValueError):
                pass

            cursor.execute('''
            INSERT INTO chart_layouts (id, client_id, user_id, name, symbol, resolution, content, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (new_chart_id, client, user, name, symbol, resolution, content, timestamp))
            chart = new_chart_id

        conn.commit()
        conn.close()
        return {'status': 'ok', 'id': chart}

    @router.delete('/saveload.tradingview.com/1.1/charts')
    async def delete_chart(
        client: str = Query(..., alias="client"),
        user: str = Query(..., alias="user"),
        chart: str = Query(..., alias="chart")
    ):
        """删除特定图表布局"""
        if not client or not user:
            raise HTTPException(status_code=400, detail="Missing client_id or user_id")

        if not chart:
            raise HTTPException(status_code=400, detail="Missing chart_id")

        try:
            conn = get_db_connection(db_config)
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

    # ============= Study Templates =============

    @router.get('/saveload.tradingview.com/1.1/study_templates')
    async def list_study_templates(
        client: str = Query(..., alias="client"),
        user: str = Query(..., alias="user"),
        template: Optional[str] = Query(None, alias="template")
    ):
        """列出所有研究模板或获取特定模板"""
        if not client or not user:
            raise HTTPException(status_code=400, detail="Missing client_id or user_id")

        if template:
            return get_study_template(db_config, client, user, template)
        else:
            return get_all_study_templates_list(db_config, client, user)

    @router.post('/saveload.tradingview.com/1.1/study_templates')
    async def save_study_template(
        client: str = Query(..., alias="client"),
        user: str = Query(..., alias="user"),
        name: str = Form(...),
        content: str = Form(...)
    ):
        """保存研究模板"""
        if not client or not user:
            raise HTTPException(status_code=400, detail="Missing client_id or user_id")

        if not name or not content:
            raise HTTPException(status_code=400, detail="Missing template name or content")

        timestamp = int(datetime.now().timestamp())
        conn = get_db_connection(db_config)
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

    @router.delete('/saveload.tradingview.com/1.1/study_templates')
    async def delete_study_template(
        client: str = Query(..., alias="client"),
        user: str = Query(..., alias="user"),
        template: str = Query(..., alias="template")
    ):
        """删除特定研究模板"""
        if not client or not user:
            raise HTTPException(status_code=400, detail="Missing client_id or user_id")

        if not template:
            raise HTTPException(status_code=400, detail="Missing template name")

        try:
            conn = get_db_connection(db_config)
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

    # ============= Drawing Templates =============

    @router.get('/saveload.tradingview.com/1.1/drawing_templates')
    async def list_drawing_templates(
        client: str = Query(..., alias="client"),
        user: str = Query(..., alias="user"),
        name: Optional[str] = Query(None, alias="name"),
        tool: Optional[str] = Query(None, alias="tool")
    ):
        """列出所有绘图模板或获取特定模板"""
        if not client or not user:
            raise HTTPException(status_code=400, detail="Missing client_id or user_id")

        if name:
            return get_drawing_template(db_config, client, user, tool or '', name)
        else:
            return get_all_drawing_templates(db_config, client, user, tool or '')

    @router.post('/saveload.tradingview.com/1.1/drawing_templates')
    async def save_drawing_template(
        client: str = Query(..., alias="client"),
        user: str = Query(..., alias="user"),
        name: str = Query(..., alias="name"),
        tool: str = Query(..., alias="tool"),
        content: str = Form(...)
    ):
        """保存绘图模板"""
        if not client or not user:
            raise HTTPException(status_code=400, detail="Missing client_id or user_id")

        if not name or not tool or not content:
            raise HTTPException(status_code=400, detail="Missing name, tool, or content")

        timestamp = int(datetime.now().timestamp())
        conn = get_db_connection(db_config)
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

    @router.delete('/saveload.tradingview.com/1.1/drawing_templates')
    async def delete_drawing_template(
        client: str = Query(..., alias="client"),
        user: str = Query(..., alias="user"),
        tool: str = Query(..., alias="tool"),
        name: str = Query(..., alias="name")
    ):
        """删除特定绘图模板"""
        if not client or not user:
            raise HTTPException(status_code=400, detail="Missing client_id or user_id")

        if not tool or not name:
            raise HTTPException(status_code=400, detail="Missing tool or name")

        try:
            conn = get_db_connection(db_config)
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

    return router


# ============= Helper Functions =============

def get_all_users_charts(db_config, client_id, user_id):
    """获取用户的所有图表"""
    conn = get_db_connection(db_config)
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


def get_chart_content(db_config, client_id, user_id, chart_id):
    """获取特定图表的内容"""
    conn = get_db_connection(db_config)
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


def get_all_study_templates_list(db_config, client_id, user_id):
    """获取所有研究模板列表"""
    conn = get_db_connection(db_config)
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


def get_study_template(db_config, client_id, user_id, template_name):
    """获取特定研究模板"""
    conn = get_db_connection(db_config)
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


def get_drawing_template(db_config, client_id, user_id, tool, name):
    """获取特定绘图模板"""
    conn = get_db_connection(db_config)
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


def get_all_drawing_templates(db_config, client_id, user_id, tool):
    """获取所有绘图模板"""
    conn = get_db_connection(db_config)
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
