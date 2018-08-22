import yaml
import asyncio
import logging
import argparse
import sqlite3
from pprint import pprint
# Local
import api
from proxy import Proxy
from server import Server
from utils import db_con


logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description='Sends tasks to Cerberus')
parser.add_argument('-c', '--config', help='yaml config file', required=True)
parser.add_argument('--host', default='0.0.0.0', nargs='?',
                    help='The ip to bind the api server to. Default: 0.0.0.0')
parser.add_argument('-p', '--port', default=8181, nargs='?', type=int,
                    help='Port for the api server. Default: 8181')
args = parser.parse_args()

server_pool_list = []

with open(args.config, 'r') as stream:
    proxy_pool_config = yaml.load(stream)

for pool in proxy_pool_config:
    proxy_list = []
    for proxy in pool['Proxies']:
        # TODO: Add lots of validation to the config inputs
        port = proxy.get('Port', 80)
        proxy_list.append(Proxy(host=proxy['Host'],
                                port=port,
                                username=proxy.get('User'),
                                password=proxy.get('Pass'),
                                types=proxy.get('types', ('HTTP', 'HTTPS'))))
        try:
            with db_con:
                db_con.execute("INSERT INTO proxy (proxy, pool) VALUES (?,?)",
                               (f"{proxy['Host']}:{port}", pool['Port']))
        except sqlite3.IntegrityError:
            logger.critical("Failed to save request data")

    server_pool_list.append(Server(pool.get('Host', '0.0.0.0'), pool['Port'], proxy_list))

# Start api server
api.start_server(args.host, args.port)

for server_pool in server_pool_list:
    server_pool.start()

loop = asyncio.get_event_loop()
try:
    loop.run_forever()
except KeyboardInterrupt:
    pass

logger.info('Servers shutting down.')
for server_pool in server_pool_list:
    server_pool.stop()
