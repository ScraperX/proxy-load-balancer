import yaml
import asyncio
import logging
import argparse
import sqlite3

# Local
import api
from proxy import Proxy, ProxyPool
from server import Server
from utils import db_conn


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
    CONFIG = yaml.load(stream)

# Add pools to db
proxy_list = []
for pool_rank, pool in enumerate(CONFIG.get('Pools', [])):
    # Add proxies to list and to db
    for proxy in pool['Proxies']:
        # TODO: Add lots of validation to the config inputs
        port = proxy.get('Port', 80)
        proxy_list.append(Proxy(host=proxy['Host'],
                                port=port,
                                username=proxy.get('User'),
                                password=proxy.get('Pass'),
                                types=proxy.get('types', ('HTTP', 'HTTPS'))))
        try:
            with db_conn:
                db_conn.execute("INSERT INTO proxy (proxy, pool) VALUES (?,?)",
                                (f"{proxy['Host']}:{port}", pool['Name']))
        except sqlite3.IntegrityError:
            logger.critical("Failed to save proxy to database")

proxy_pool = ProxyPool(proxy_list)

# Add Rules to db (just worry about Domain rules for now)
for rule_rank, rule in enumerate(CONFIG['Rules']):
    rule_pools = ','.join(rule['Pools'])
    for re_rank, re_rule in enumerate(rule['Domains']):
        logger.debug(f"Save rule to the database. rule={rule['Name']}; re_rule={re_rule}; pool={rule_pools}; ")
        try:
            with db_conn:
                db_conn.execute("INSERT INTO pool_rule (pool, rank, rule, rule_re, rule_type) VALUES (?,?,?,?,?)",
                                (rule_pools, rule_rank + (re_rank / 100), rule['Name'], re_rule, 'domain'))
        except sqlite3.IntegrityError:
            logger.critical("Failed to save rules to database")

# Start pool server
server_pool_list.append(Server(CONFIG['Server'].get('Host', '0.0.0.0'), CONFIG['Server']['Port'], proxy_pool))

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
