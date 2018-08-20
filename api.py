import asyncio
import json
from aiohttp import web
import logging
from utils import pool_stats

logger = logging.getLogger(__name__)


@asyncio.coroutine
def hello(request):
    return web.Response(status=200,
                        body=json.dumps(pool_stats),
                        content_type='application/json')


def start_server(host, port):
    app = web.Application()
    app.router.add_route('GET', '/', hello)
    loop = asyncio.get_event_loop()
    f = loop.create_server(app.make_handler(), host, port)
    srv = loop.run_until_complete(f)
    logger.info('Listening established on {0}'.format(
            srv.sockets[0].getsockname()))
