import yaml
import asyncio
import sqlite3
import logging
import argparse
from collections import defaultdict

# Local
import api
from proxy import Proxy, ProxyPool
from server import Server
from utils import db_conn


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description='Run the Proxy Load Balancer')
parser.add_argument('-c', '--config', help='yaml config file', required=True)
# TODO: Make overrides for server config values
args = parser.parse_args()

server_pool_list = []

with open(args.config, 'r') as stream:
    CONFIG = yaml.load(stream)

# Add pools to db
pool_proxies = defaultdict(list)
for pool_rank, pool in enumerate(CONFIG.get('Pools', [])):
    # Add proxies to list and to db
    for proxy in pool['Proxies']:
        # TODO: Add lots of validation to the config inputs
        proxy_port = proxy.get('Port', 80)
        pool_proxies[pool['Name']].append(Proxy(host=proxy['Host'],
                                                port=proxy_port,
                                                username=proxy.get('User'),
                                                password=proxy.get('Pass'),
                                                types=proxy.get('types', ('HTTP', 'HTTPS'))))
        try:
            with db_conn:
                db_conn.execute("INSERT INTO proxy (proxy, pool) VALUES (?,?)",
                                (f"{proxy['Host']}:{proxy_port}", pool['Name']))
        except sqlite3.IntegrityError:
            logger.critical("Failed to save proxy to database")

port_proxies = defaultdict(list)
# Parse the rules in the config
for rule_rank, rule in enumerate(CONFIG['Rules']):
    rule_pools = ','.join(rule['Pools'])
    # Get all proxies in the pool
    all_rule_proxies = []
    for pool_name in rule['Pools']:
        all_rule_proxies.extend(pool_proxies[pool_name])
    port_proxies[rule['Port']].extend(all_rule_proxies)

    # Add rule to db
    for re_rank, re_rule in enumerate(rule['Domains']):
        logger.debug(f"Save rule to the database. rule={rule['Name']}; re_rule={re_rule}; pool={rule_pools}; ")
        rank = rule_rank + (re_rank / 100)
        try:
            with db_conn:
                db_conn.execute("""INSERT INTO pool_rule (pool, port, rank, rule, rule_re, rule_type)
                                   VALUES (?,?,?,?,?,?)""",
                                (rule_pools, rule['Port'], rank, rule['Name'], re_rule, 'domain'))
        except sqlite3.IntegrityError:
            logger.critical("Failed to save rules to database")

# Add the server ports
for port, proxy_list in port_proxies.items():
    server_pool_list.append(Server(CONFIG['Server'].get('Host', '0.0.0.0'), port, ProxyPool(proxy_list)))


# Start api server
api.start_server(CONFIG['Server'].get('Host', '0.0.0.0'), CONFIG['Server'].get('API_Port', 8181))

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
