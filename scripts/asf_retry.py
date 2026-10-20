"""Bounded retries for read-only NASA catalog requests, never fake observations."""
import time


def catalog_request(operation, *args, **kwargs):
    from asf_search.exceptions import ASFSearch5xxError, CMRIncompleteError
    from requests.exceptions import ConnectionError, Timeout

    delays = (20, 40)
    for attempt in range(3):
        try:
            return operation(*args, **kwargs)
        except (ASFSearch5xxError, CMRIncompleteError, ConnectionError, Timeout):
            if attempt == 2:
                raise
            print(f'NASA catalog temporarily unavailable; read-only retry in {delays[attempt]} seconds', flush=True)
            time.sleep(delays[attempt])
