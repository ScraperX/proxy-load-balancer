import asyncio
import logging
from server import Server
from proxy import Proxy

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

proxies = []

s = Server('0.0.0.0', '8080', proxies, max_tries=1)
s.start()

loop = asyncio.get_event_loop()
try:
    loop.run_forever()
except KeyboardInterrupt:
    pass

print('Server shutting down.')
s.stop()
