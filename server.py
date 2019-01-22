import time
import asyncio
import logging
from config import CONFIG
from proxy import get_proxy
from errors import (
    BadStatusLine, BadResponseError, ErrorOnStream,
    NoProxyError, ProxyRecvError, ProxyTimeoutError)
from utils import parse_headers, parse_status_line

logger = logging.getLogger(__name__)
request_logger = logging.getLogger('proxy_request')

global_requests = []

CONNECTED = b'HTTP/1.1 200 Connection established\r\n\r\n'


class Server:
    """Server distributes incoming requests to its pool of proxies.
    Each instance of this calss is a 'pool' which has proxies.
    TODOs:
    - The pool should at all times have calculated stats about the proxies in its pool

    """

    def __init__(self, host, port, timeout=30, loop=None):
        self.host = host
        self.port = int(port)
        self._loop = loop or asyncio.get_event_loop()
        self._timeout = timeout

        self._server = None
        self._connections = {}

    def start(self):
        srv = asyncio.start_server(
            self._accept, host=self.host, port=self.port, loop=self._loop)
        self._server = self._loop.run_until_complete(srv)

        logger.info('Listening established on {0}'.format(
            self._server.sockets[0].getsockname()))

    def stop(self):
        if not self._server:
            return
        for conn in self._connections:
            if not conn.done():
                conn.cancel()
        self._server.close()
        if not self._loop.is_running():
            self._loop.run_until_complete(self._server.wait_closed())
            # Time to close the running futures in self._connections
            self._loop.run_until_complete(asyncio.sleep(0.5))
        self._server = None
        self._loop.stop()
        logger.info('Server is stopped')

    def _accept(self, client_reader, client_writer):
        def _on_completion(f):
            reader, writer = self._connections.pop(f)
            writer.close()
            logger.debug('client: %d; closed' % id(client_reader))
            try:
                exc = f.exception()
            except asyncio.CancelledError:
                logger.error('CancelledError in server._handle:_on_completion')
                exc = None
            if exc:
                if isinstance(exc, NoProxyError):
                    self.stop()
                else:
                    raise exc
        f = asyncio.ensure_future(self._handle(client_reader, client_writer))
        f.add_done_callback(_on_completion)
        self._connections[f] = (client_reader, client_writer)

    async def _handle(self, client_reader, client_writer):
        logger.debug(f"Accepted connection from {client_writer.get_extra_info('peername')}")

        time_of_request = int(time.time())  # The time the request was requested
        request, headers = await self._parse_request(client_reader)
        scheme = self._identify_scheme(headers)
        client = id(client_reader)
        error = None
        stime = 0
        proxy, pool = await get_proxy(headers['Host'], self.port)
        proto = self._choice_proto(proxy, scheme)
        logger.debug(f'client: {client}; request: {request}; headers: {headers}; '
                     f'scheme: {scheme}; proxy: {proxy}; proto: {proto}')
        try:
            await proxy.connect()

            if proto in ('CONNECT:80', 'SOCKS4', 'SOCKS5'):
                if scheme == 'HTTPS' and proto in ('SOCKS4', 'SOCKS5'):
                    client_writer.write(CONNECTED)
                    await client_writer.drain()
                else:  # HTTP
                    await proxy.send(request)
            else:  # proto: HTTP & HTTPS
                await proxy.send(request)

            stime = time.time()
            stream = [asyncio.ensure_future(self._stream(reader=client_reader, writer=proxy.writer)),
                      asyncio.ensure_future(self._stream(reader=proxy.reader, writer=client_writer, scheme=scheme))
                      ]
            await asyncio.gather(*stream, loop=self._loop)

        except asyncio.CancelledError:
            logger.error('Cancelled in server._handle')
            error = 'Cancelled in server._handle'

        except ErrorOnStream as e:
            logger.error(f'client: {client}; EOF: {client_reader.at_eof()}; Error: {e}')
            for task in stream:
                if not task.done():
                    task.cancel()
            if client_reader.at_eof() and 'Timeout' in repr(e):
                # Proxy may not be able to receive EOF and will raise a
                # TimeoutError, but all the data has already successfully
                # returned, so do not consider this error of proxy
                error = 'TimeoutError'

            if scheme == 'HTTPS':  # SSL Handshake probably failed
                error = 'SSL Error'

        except ProxyTimeoutError:
            logger.error("Proxy timeout")
            error = 'Proxy Timeout'
            # TODO: Send client a 408 status code

        except Exception as e:
            # Catch anything that falls through
            logger.exception("Catch all in server")
            error = repr(e)

        finally:
            proxy.log(request.decode(), stime)
            # At this point, the client has already disconnected and now the stats can be processed and saved
            try:
                if CONFIG.get('Server', {}).get('Log_Requests', True):
                    proxy_url = f'{proxy.host}:{proxy.port}'
                    path = None
                    # Can get path for http requests, but not for https
                    if '/' in headers.get('Path', ''):
                        path = '/' + headers.get('Path', '').split('/')[-1]

                    try:
                        status_code = parse_status_line(stream[1].result().split(b'\r\n', 1)[0].decode()).get('Status')
                    except Exception as e:
                        logger.warning(f"Issue saving status code: proxy={proxy_url}; host={headers.get('Host')}")
                        status_code = None
                        if error is None:
                            error = repr(e)

                    try:
                        proxy_bandwidth_up = len(stream[0].result()) + proxy.stats.get('bandwidth_up', 0)
                        proxy_bandwidth_down = len(stream[1].result()) + proxy.stats.get('bandwidth_down', 0)
                    except Exception:
                        # Happens if something goes wrong with the connection
                        logger.warning(f"Issue saving bandwidth: proxy={proxy_url}; host={headers.get('Host')}")
                        proxy_bandwidth_up = None
                        proxy_bandwidth_down = None

                    request_log = {'host': headers.get('Host'),
                                   'proxy': proxy_url,
                                   'path': path,
                                   'scheme': scheme,
                                   'bw_up': proxy_bandwidth_up,
                                   'bw_down': proxy_bandwidth_down,
                                   'status_code': status_code,
                                   'error': error,
                                   'total_time': proxy.stats['total_time'],
                                   'ts': time_of_request,
                                   'pool_name': pool,
                                   'proxy_port': self.port
                                   }
                    request_logger.info('Request made', extra=request_log)

            except Exception:
                logger.exception("Failed to save request data")

            proxy.close()

    async def _parse_request(self, reader, length=65536):
        request = await reader.read(length)
        headers = parse_headers(request)
        if headers['Method'] == 'POST' and request.endswith(b'\r\n\r\n'):
            # For aiohttp. POST data returns on second reading
            request += await reader.read(length)
        return request, headers

    def _identify_scheme(self, headers):
        if headers['Method'] == 'CONNECT':
            return 'HTTPS'
        else:
            return 'HTTP'

    def _choice_proto(self, proxy, scheme):
        if scheme == 'HTTP':
            if 'CONNECT:80' in proxy.types:
                proto = 'CONNECT:80'
            else:
                relevant = ({'HTTP', 'CONNECT:80', 'SOCKS4', 'SOCKS5'} &
                            proxy.types)
                proto = relevant.pop()
        else:  # HTTPS
            relevant = {'HTTPS', 'SOCKS4', 'SOCKS5'} & proxy.types
            proto = relevant.pop()
        return proto

    async def _stream(self, reader, writer, length=65536, scheme=None):
        checked = False
        total_data = b''
        try:
            while not reader.at_eof():
                data = await asyncio.wait_for(reader.read(length), self._timeout)
                if not data:
                    writer.close()
                    break

                elif scheme and not checked:
                    self._check_response(data, scheme)
                    checked = True

                total_data += data
                writer.write(data)
                await writer.drain()

        except (asyncio.TimeoutError, ConnectionResetError, OSError,
                ProxyRecvError, BadResponseError) as e:
            raise ErrorOnStream(e)

        return total_data

    def _check_response(self, data, scheme):
        if scheme.startswith('HTTP'):
            # Check both HTTP & HTTPS requests
            line = data.split(b'\r\n', 1)[0].decode()
            try:
                parse_status_line(line)
            except BadStatusLine:
                raise BadResponseError
