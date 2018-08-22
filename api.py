import asyncio
import json
from aiohttp import web
import logging
import sqlite3
from utils import db_con
from pprint import pprint
logger = logging.getLogger(__name__)


@asyncio.coroutine
def requests(request):
    return web.Response(status=200,
                        body=json.dumps(get_requests()),
                        content_type='application/json')


@asyncio.coroutine
def proxies(request):
    return web.Response(status=200,
                        body=json.dumps(get_proxies()),
                        content_type='application/json')


def start_server(host, port):
    app = web.Application()
    app.router.add_route('GET', '/requests', requests)
    app.router.add_route('GET', '/proxies', proxies)

    loop = asyncio.get_event_loop()
    f = loop.create_server(app.make_handler(), host, port)
    srv = loop.run_until_complete(f)
    logger.info('Listening established on {0}'.format(
            srv.sockets[0].getsockname()))



def get_requests():
    """Get requests

    Returns:
        list of dicts -- List of all the requests that have been made on the server
    """
    data = []
    try:
        with db_con:
            cur = db_con.cursor()
            cur.execute("SELECT * FROM request")
            data = cur.fetchall()

    except sqlite3.IntegrityError:
        logger.critical("Failed select requests")

    data = list(map(dict, data))
    return data

def get_proxies():
    """Get all proxies in the server

    Returns:
        list of dicts -- List of all the proxies that are in the server
    """
    data = []
    try:
        with db_con:
            cur = db_con.cursor()
            cur.execute("SELECT * FROM proxy")
            data = cur.fetchall()

    except sqlite3.IntegrityError:
        logger.critical("Failed select proxies")

    data = list(map(dict, data))
    return data
