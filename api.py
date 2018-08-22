import asyncio
import json
from aiohttp import web
import logging
import sqlite3
from utils import pool_stats, db_con
from pprint import pprint
logger = logging.getLogger(__name__)


@asyncio.coroutine
def hello(request):
    return web.Response(status=200,
                        body=json.dumps(),
                        content_type='application/json')


def start_server(host, port):
    app = web.Application()
    app.router.add_route('GET', '/', hello)
    loop = asyncio.get_event_loop()
    f = loop.create_server(app.make_handler(), host, port)
    srv = loop.run_until_complete(f)
    logger.info('Listening established on {0}'.format(
            srv.sockets[0].getsockname()))



def get_proxy_requests():
    data = []
    try:
        with db_con:
            cur = db_con.cursor()
            cur.execute("SELECT * FROM request")
            data = cur.fetchall()

    except sqlite3.IntegrityError:
        logger.critical("Failed to select all requests")

    return data
