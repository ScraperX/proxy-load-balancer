import time
import base64
import logging
import asyncio
import warnings
import ssl as _ssl
from collections import Counter

from errors import (
    ProxyEmptyRecvError, ProxyConnError, ProxyRecvError,
    ProxySendError, ProxyTimeoutError, ResolveError)
from utils import parse_headers


logger = logging.getLogger(__name__)

_HTTP_PROTOS = {'HTTP', 'CONNECT:80', 'SOCKS4', 'SOCKS5'}
_HTTPS_PROTOS = {'HTTPS', 'SOCKS4', 'SOCKS5'}


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
        self.port = int(port)
        self._username = username
        self._password = password

        self._auth_token = None
        if self._username or self._password:
            self._auth_token = base64.encodestring(f'{self._username}:{self._password}'
                                                    .encode()).decode()

        if self.port > 65535:
            raise ValueError('The port of proxy cannot be greater than 65535')

        self._types = set(types) & set(('HTTP', 'HTTPS', 'CONNECT:80',
                                        'CONNECT:25', 'SOCKS4', 'SOCKS5'))
        self._timeout = timeout
        self._ssl_context = (True if verify_ssl else
                             _ssl._create_unverified_context())
        self._geo = geo_alpha2
        self.set_defaults()

    def set_defaults(self):
        self._closed = True
        self._stats = {'total_time': 0,
                       'bandwidth': {'up': 0, 'down': 0},
                       'status_code': None,
                       }
        self._reader = {'conn': None, 'ssl': None}
        self._writer = {'conn': None, 'ssl': None}

    def __repr__(self):
        # <Proxy US 1.12 [HTTP, HTTPS] 10.0.0.1:8080>
        tpinfo = []
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
        runtime = int(time.time()*1000 - stime*1000) if stime else 0
        self._stats['total_time'] += runtime
        log_using(f"{self.host}:{self.port} - {msg.strip()} Runtime: {runtime}ms")

    async def connect(self, ssl=False):
        err = None
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
            err = ProxyTimeoutError(msg)
            raise err
        except (ConnectionRefusedError, OSError, _ssl.SSLError):
            msg += 'Connection: failed'
            err = ProxyConnError(msg)
            raise err
        else:
            msg += 'Connection: success'
            self._closed = False
        finally:
            self.log(msg, stime)

    def close(self):
        # TODO: Log all the data about the request here
        # time (ms), bytes (up/down), status code, domain
        self.log(f'Connection: closed {self._stats}')

        if self._closed:
            self.set_defaults()
            return

        if self.writer:
            self.writer.close()

        self.set_defaults()

    async def send(self, req):
        msg, err = '', None

        if self._auth_token is not None:
            # Add proxy auth to header
            logger.debug("Setting Proxy-Authorization")
            req = req.replace(b'\r\n\r\n',
                              f'\r\nProxy-Authorization: Basic {self._auth_token.strip()}\r\n\r\n'.encode())

        _req = req.encode() if not isinstance(req, bytes) else req

        try:
            self._stats['bandwidth']['up'] = len(_req)
            self.writer.write(_req)
            await self.writer.drain()
        except ConnectionResetError:
            msg = '; Sending: failed'
            err = ProxySendError(msg)
            raise err
        finally:
            self.log('Request: %s%s' % (req, msg))

    async def recv(self, length=0, head_only=False):
        resp, msg, err = b'', '', None
        stime = time.time()
        try:
            resp = await asyncio.wait_for(
                self._recv(length, head_only), timeout=self._timeout)
        except asyncio.TimeoutError:
            msg = 'Received: timeout'
            err = ProxyTimeoutError(msg)
            raise err
        except (ConnectionResetError, OSError) as e:
            msg = 'Received: failed'  # (connection is reset by the peer)
            err = ProxyRecvError(msg)
            raise err
        else:
            msg = 'Received: %s bytes' % len(resp)
            if not resp:
                err = ProxyEmptyRecvError(msg)
                raise err
        finally:
            if resp:
                msg += ': %s' % resp[:12]
            self.log(msg, stime)

        return resp

    async def _recv(self, length=0, head_only=False):
        resp = b''
        if length:
            try:
                resp = await self.reader.readexactly(length)
            except asyncio.IncompleteReadError as e:
                resp = e.partial
        else:
            body_size, body_recv, chunked = 0, 0, None
            while not self.reader.at_eof():
                line = await self.reader.readline()
                resp += line
                if body_size:
                    body_recv += len(line)
                    if body_recv >= body_size:
                        break
                elif chunked and line == b'0\r\n':
                    break
                elif not body_size and line == b'\r\n':
                    if head_only:
                        break
                    headers = parse_headers(resp)
                    body_size = int(headers.get('Content-Length', 0))
                    if not body_size:
                        chunked = headers.get('Transfer-Encoding') == 'chunked'
        return resp
