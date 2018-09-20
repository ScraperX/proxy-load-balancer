import asyncio
import sqlite3
import logging

# Local
import api
from config import CONFIG
from server import Server
from utils import db_conn


logger = logging.getLogger(__name__)

# Add proxies to the database
for pool_rank, pool in enumerate(CONFIG.get('Pools', [])):
    for proxy in pool['Proxies']:
        try:
            with db_conn:
                db_conn.execute("INSERT INTO proxy (host, username, password, port, types, pool) VALUES (?,?,?,?,?,?)",
                                (proxy['Host'],
                                 proxy.get('User'),
                                 proxy.get('Pass'),
                                 int(proxy.get('Port', 80)),
                                 ','.join(proxy.get('types', ('HTTP', 'HTTPS'))),
                                 pool['Name']))
        except sqlite3.IntegrityError:
            logger.critical("Failed to save proxy to database")

server_ports = set()
# Parse the rules in the config
for rule_rank, rule in enumerate(CONFIG['Rules']):
    rule_pools = ','.join(rule['Pools'])
    server_ports.add(rule['Port'])

    # Add rule to db
    for re_rank, re_rule in enumerate(rule['Domains']):
        logger.debug(f"Save rule to the database. rule={rule['Name']}; re_rule={re_rule}; pool={rule_pools};")
        rank = rule_rank + (re_rank / 100)
        try:
            with db_conn:
                db_conn.execute("""INSERT INTO pool_rule (pool, port, rank, rule, rule_re, rule_type)
                                   VALUES (?,?,?,?,?,?)""",
                                (rule_pools, rule['Port'], rank, rule['Name'], re_rule, 'domain'))
        except sqlite3.IntegrityError:
            logger.critical("Failed to save rules to database")


server_pool_list = []
# Add the server ports
for port in server_ports:
    server_pool_list.append(Server(CONFIG['Server'].get('Host', '0.0.0.0'), port))

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
