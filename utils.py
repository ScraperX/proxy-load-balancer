import logging
import sqlite3

from errors import BadStatusLine

logger = logging.getLogger(__name__)

# Used globaly to keep track of the stats for a given pool
db_con = sqlite3.connect(":memory:", check_same_thread=False)
db_con.row_factory = sqlite3.Row
try:
    # Create the table each time since its in memory.
    with db_con:
        db_con.execute("""CREATE TABLE request (
                              proxy varchar(256),
                              domain varchar(256),
                              pool varchar(128),
                              path varchar(512),
                              scheme varchar(16),
                              bandwidth_up integer,
                              bandwidth_down integer,
                              status_code integer,
                              total_time integer,
                              time_of_request integer
                          );
                       """)
except sqlite3.IntegrityError:
    logger.critical("Could not create the in menory `request` table")

try:
    # Create the table each time since its in memory.
    with db_con:
        db_con.execute("""CREATE TABLE proxy (
                              proxy varchar(256),
                              pool varchar(126)
                          );
                       """)
except sqlite3.IntegrityError:
    logger.critical("Could not create the in menory `request` table")


def parse_status_line(line):
    _headers = {}
    is_response = line.startswith('HTTP/')
    try:
        if is_response:  # HTTP/1.1 200 OK
            version, status, *reason = line.split()
        else:  # GET / HTTP/1.1
            method, path, version = line.split()
    except ValueError:
        raise BadStatusLine(line)

    _headers['Version'] = version.upper()
    if is_response:
        _headers['Status'] = int(status)
        reason = ' '.join(reason)
        reason = reason.upper() if reason.lower() == 'ok' else reason.title()
        _headers['Reason'] = reason
    else:
        _headers['Method'] = method.upper()
        _headers['Path'] = path
        if _headers['Method'] == 'CONNECT':
            host, port = path.split(':')
            _headers['Host'], _headers['Port'] = host, int(port)
    return _headers


def parse_headers(headers):
    headers = headers.decode('utf-8', 'ignore').split('\r\n')
    _headers = {}
    _headers.update(parse_status_line(headers.pop(0)))

    for h in headers:
        if not h:
            break
        name, val = h.split(':', 1)
        _headers[name.strip().title()] = val.strip()

    if ':' in _headers.get('Host', ''):
        host, port = _headers['Host'].split(':')
        _headers['Host'], _headers['Port'] = host, int(port)
    return _headers
