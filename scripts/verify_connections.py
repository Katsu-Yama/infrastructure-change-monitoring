"""Read-only credential preflight; never print credentials or account details."""
import json
import math
import os
from pathlib import Path


def main():
    failures = []
    try:
        from scripts.pair_store import PairStore
        options = json.loads(Path('config/sentinel.json').read_text(encoding='utf-8'))
        store = PairStore(options)
        bucket = store.request('/storage/v1/bucket/' + store.bucket)
        if bucket.get('public') or bucket.get('id') != store.bucket:
            raise ValueError('Private bucket identity mismatch')
        print('PASS: Supabase server credential, private table and private bucket access', flush=True)
    except Exception as error:
        failures.append('Supabase')
        print(f'FAIL: Supabase private access ({type(error).__name__}); check SUPABASE_SECRET_KEY and project', flush=True)
    try:
        import hyp3_sdk
        api = hyp3_sdk.HyP3('https://hyp3-api.asf.alaska.edu',
            username=os.environ['EARTHDATA_USERNAME'], password=os.environ['EARTHDATA_PASSWORD'], prompt=False)
        remaining = api.check_credits()
        if remaining is None or not math.isfinite(float(remaining)) or remaining < 0:
            raise ValueError('Finite free processing allowance required')
        print(f'PASS: Earthdata authentication and HyP3 Basic access; remaining free credits: {remaining}', flush=True)
    except Exception as error:
        failures.append('Earthdata/HyP3')
        print(f'FAIL: Earthdata/HyP3 access ({type(error).__name__}); check username/password and ASF authorization', flush=True)
    if failures:
        raise SystemExit('Connection preflight failed: ' + ', '.join(failures))


if __name__ == '__main__':
    main()
