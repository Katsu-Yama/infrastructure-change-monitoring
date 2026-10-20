"""Read-only HyP3 login diagnostics. Never log URLs, headers, bodies or secrets."""
import math
import os
import socket
import time
from urllib.parse import urlsplit
from unittest.mock import patch

import requests

HOSTS = ('urs.earthdata.nasa.gov', 'cumulus.asf.alaska.edu',
         'hyp3-api.asf.alaska.edu', 'cmr.earthdata.nasa.gov')


def error_types(error):
    """Only class names, never exception text (which can contain OAuth codes)."""
    pending = [error]; seen = set(); names = []
    while pending and len(seen) < 12:
        item = pending.pop(0)
        if not isinstance(item, BaseException) or id(item) in seen:
            continue
        seen.add(id(item))
        name = type(item).__name__
        if name not in names:
            names.append(name)
        pending += [item.__cause__, item.__context__, getattr(item, 'reason', None)]
        pending += [arg for arg in item.args if isinstance(arg, BaseException)]
    return ' > '.join(names)


class DiagnosticSession(requests.Session):
    def request(self, method, url, **kwargs):
        if kwargs.get('timeout') is None:
            kwargs['timeout'] = (10, 25)
        return super().request(method, url, **kwargs)

    def send(self, request, **kwargs):
        parts = urlsplit(request.url)
        if (request.method != 'GET' or parts.scheme != 'https' or
                parts.hostname not in HOSTS or parts.port not in (None, 443) or
                parts.username or parts.password):
            raise ValueError('Diagnostic request blocked by read-only host policy')
        if kwargs.get('timeout') is None:
            kwargs['timeout'] = (10, 25)
        started = time.monotonic()
        print(f'NET host={parts.hostname} method=GET start', flush=True)
        try:
            response = super().send(request, **kwargs)
        except requests.RequestException as error:
            print(f'NET host={parts.hostname} failure_types={error_types(error)} elapsed_s={time.monotonic() - started:.1f}', flush=True)
            raise
        print(f'NET host={parts.hostname} status={response.status_code} elapsed_s={time.monotonic() - started:.1f}', flush=True)
        return response


def main():
    import hyp3_sdk
    from hyp3_sdk.util import AUTH_URL

    print('Read-only diagnostic: no processing jobs, uploads, or report publication', flush=True)
    for host in HOSTS:
        try:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            families = sorted({'IPv4' if a[0] == socket.AF_INET else 'IPv6' for a in addresses})
            print(f'DNS host={host} families={",".join(families)}', flush=True)
        except OSError as error:
            print(f'DNS host={host} failure_types={error_types(error)}', flush=True)
    # An unauthenticated 401 at the login endpoint is expected, not bad credentials.
    with DiagnosticSession() as session:
        for url in (AUTH_URL, 'https://hyp3-api.asf.alaska.edu/',
                    'https://cmr.earthdata.nasa.gov/search/health'):
            try:
                session.get(url)
            except requests.RequestException:
                pass
    username = os.environ.get('EARTHDATA_USERNAME', '')
    password = os.environ.get('EARTHDATA_PASSWORD', '')
    for label, value in (('username', username), ('password', password)):
        print(f'SETTING {label} present={bool(value)} outer_whitespace={value != value.strip()} newline={chr(10) in value or chr(13) in value}', flush=True)
    if not username or not password:
        raise SystemExit('AUTH FAIL: missing credential setting')
    stage = 'login'
    try:
        # Keep the official SDK authentication flow; bound and trace its session.
        # Only the two Earthdata Actions secrets are made available to this job.
        with patch('hyp3_sdk.util.requests.Session', DiagnosticSession):
            api = hyp3_sdk.HyP3('https://hyp3-api.asf.alaska.edu',
                username=username, password=password, prompt=False)
            print('AUTH login initialization completed', flush=True)
            stage = 'quota'
            remaining = api.check_credits()
            if remaining is None or not math.isfinite(float(remaining)):
                raise ValueError('Finite free allowance not established')
            print(f'AUTH PASS: HyP3 Basic private account access; remaining_free_credits={remaining}', flush=True)
    except Exception as error:
        print(f'AUTH FAIL stage={stage} failure_types={error_types(error)}', flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Diagnostic failed safely: {error_types(error)}', flush=True)
        raise SystemExit(1) from None
