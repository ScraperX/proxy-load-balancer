import re
import time
import base64
import logging
import asyncio
import sqlite3
import ssl as _ssl
from utils import db_conn

from errors import (ProxyConnError, ProxySendError, ProxyTimeoutError)

logger = logging.getLogger(__name__)

_HTTP_PROTOS = {'HTTP', 'CONNECT:80', 'SOCKS4', 'SOCKS5'}
_HTTPS_PROTOS = {'HTTPS', 'SOCKS4', 'SOCKS5'}


class ProxyPool:
    """Imports and gives proxies from queue on demand."""

    def __init__(self, proxies):
        self._proxy_list = {}
        for proxy in proxies:
            proxy_key = f'{proxy.host}:{proxy.port}'
            self._proxy_list[proxy_key] = proxy

    async def get(self, host):
        proxy = None
        pool_name = None
        rules = self._get_rules()

        for rule in rules:
            # TODO: make a cache for already known matches (memoize?)
            logger.debug(f"Testing rule={rule[1]}; pool={rule[0]}; host={host};")
            match = re.search(rule[1], host)
            if match:
                logger.debug(f"Found a match for host={host};")
                proxy = self._get_proxy(rule[0])
                pool_name = rule[0]
                # TODO: If there are no more proxies left in this pool, the check other pools
                break

        return proxy, pool_name

    def _get_proxy(self, pools):
        proxy = None

        sql_pools = pools.split(',')
        desired_args = ','.join('?' * len(sql_pools))
        try:
            with db_conn:
                cur = db_conn.cursor()
                cur.execute(f"SELECT proxy FROM proxy WHERE pool in ({desired_args}) ORDER BY RANDOM() LIMIT 1",
                            sql_pools)
                proxy = dict(cur.fetchone())['proxy']
                proxy = self._proxy_list[proxy]

        except sqlite3.IntegrityError:
            logger.critical("Failed to select a proxy from the pool")

        return proxy

    def _get_rules(self):
        # TODO: On server start, get and compile all rules,
        #       re run if a rule is added/removed/modified while the server is running
        rules = None
        try:
            with db_conn:
                cur = db_conn.cursor()
                cur.execute("SELECT pool, rule_re FROM pool_rule ORDER BY rank ASC")
                rules = cur.fetchall()

        except sqlite3.IntegrityError:
            logger.critical("Failed to select rules from the db")

        return rules


class Proxy:
    """Proxy.

    :param str host: IP address of the proxy
    :param int port: Port of the proxy
    :param tuple types:
        (optional) List of types (protocols) which may be supported
        by the proxy and which can be checked to work with the proxy
    :param int timeout:
        (optional) Timeout of a connection and receive a response in seconds
    :param bool verify_ssl:
        (optional) Flag indicating whether to check the SSL certificates.
        Set to True to check ssl certifications

    :raises ValueError: If the host not is IP address, or if the port > 65535
    """
    def __init__(self, host=None, port=None, username=None, password=None, types=(),
                 timeout=8, verify_ssl=False, geo_alpha2='US'):
        self.host = host
        self.port = int(port) if port is not None else 80
        self._username = username
        self._password = password

        self._auth_token = None
        if self._username or self._password:
            self._auth_token = base64.encodestring(f'{self._username}:{self._password}'
                                                   .encode()).decode()

        if self.port > 65535:
            raise ValueError('The port of proxy cannot be greater than 65535')

        types = map(str.upper, types)
        self._types = set(types) & set(('HTTP', 'HTTPS', 'CONNECT:80',
                                        'CONNECT:25', 'SOCKS4', 'SOCKS5'))
        self._timeout = timeout
        self._ssl_context = (True if verify_ssl else
                             _ssl._create_unverified_context())
        self._geo = geo_alpha2
        self.set_defaults()

    def set_defaults(self):
        self._closed = True
        self.stats = {'total_time': 0,
                      'bandwidth_up': 0,
                      'bandwidth_down': 0,
                      'status_code': None,
                      }
        self._reader = {'conn': None, 'ssl': None}
        self._writer = {'conn': None, 'ssl': None}

    def __repr__(self):
        return '<Proxy {code} [{types}] {host}:{port}>'.format(
               code=self._geo, types=', '.join(self.types), host=self.host,
               port=self.port)

    @property
    def types(self):
        """Types (protocols) supported by the proxy.
        :rtype: tuple
        """
        return self._types

    @property
    def writer(self):
        return self._writer.get('ssl') or self._writer.get('conn')

    @property
    def reader(self):
        return self._reader.get('ssl') or self._reader.get('conn')

    def log(self, msg, stime=0, level='debug'):
        """Always log proxy logs the same

        Arguments:
            msg {[type]} -- [description]

        Keyword Arguments:
            stime {int} -- The start time of the process (default: {0})
            level {str} -- the level to log at (default: {'debug'})
        """
        log_levels = {'DEBUG': logger.debug, 'INFO': logger.info,
                      'WARNING': logger.warning, 'ERROR': logger.error,
                      'CRITICAL': logger.critical}
        log_using = log_levels.get(level.upper(), logger.debug)

        # Get runtime in ms
        runtime = int(time.time() * 1000 - stime * 1000) if stime else 0
        self.stats['total_time'] += runtime
        log_using(f"{self.host}:{self.port} - {msg.strip()} Runtime: {runtime}ms")

    async def connect(self, ssl=False):
        msg = 'SSL: ' if ssl else ''
        self.log(f'{msg}Initial connection')
        stime = time.time()
        try:
            if ssl:
                _type = 'ssl'
                sock = self._writer['conn'].get_extra_info('socket')
                params = {'ssl': self._ssl_context, 'sock': sock,
                          'server_hostname': self.host}
            else:
                _type = 'conn'
                params = {'host': self.host, 'port': self.port}
            self._reader[_type], self._writer[_type] = \
                await asyncio.wait_for(asyncio.open_connection(**params),
                                       timeout=self._timeout)

        except asyncio.TimeoutError:
            msg += 'Connection: timeout'
            raise ProxyTimeoutError(msg)
        except (ConnectionRefusedError, OSError, _ssl.SSLError):
            msg += 'Connection: failed'
            raise ProxyConnError(msg)
        else:
            msg += 'Connection: success'
            self._closed = False
        finally:
            self.log(msg, stime)

    def close(self):
        # TODO: Log all the data about the request here
        # time (ms), bytes (up/down), status code, domain
        self.log(f'Connection: closed')

        if self._closed:
            self.set_defaults()
            return

        if self.writer:
            self.writer.close()

        self.set_defaults()

    async def send(self, req):
        msg = ''

        if self._auth_token is not None:
            # Add proxy auth to header
            self.log("Setting Proxy-Authorization")
            req = req.replace(b'\r\n\r\n',
                              f'\r\nProxy-Authorization: Basic {self._auth_token.strip()}\r\n\r\n'.encode())

        _req = req.encode() if not isinstance(req, bytes) else req

        try:
            self.stats['bandwidth_up'] += len(_req)
            self.writer.write(_req)
            await self.writer.drain()
        except ConnectionResetError:
            msg = '; Sending: failed'
            raise ProxySendError(msg)
        finally:
            self.log(f'Request: {req}{msg}')
