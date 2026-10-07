"""Read-only FYERS holdings snapshot for portfolio reconciliation; no imports/orders."""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
from database.auth_db import get_auth_token
from broker.fyers.api.order_api import get_holdings
from utils.db_sessions import remove_all_scoped_sessions

try:
    configs = json.loads((ROOT / 'strategies/strategy_configs.json').read_text())
    owners = {row['user_id'] for row in configs.values()}
    assert len(owners) == 1
    token = get_auth_token(owners.pop())
    if not token:
        raise RuntimeError('No saved broker token; sign in to FYERS in OpenAlgo')
    result = get_holdings(token)
    if result.get('s') != 'ok':
        print(json.dumps({'status': result.get('s'), 'code': result.get('code'), 'message': result.get('message')}))
        raise SystemExit(1)
    fields = ('symbol', 'quantity', 'costPrice', 'ltp', 'pl', 'holdingType', 'remainingQuantity')
    output = {'checked_at': datetime.now(ZoneInfo('Asia/Kolkata')).isoformat(),
              'source': 'FYERS GET /api/v3/holdings',
              'holdings': [{k: row[k] for k in fields if k in row} for row in result.get('holdings', [])],
              'totals': result.get('overall'),
              'available_fields': sorted({k for row in result.get('holdings', []) for k in row}),
              'orders_submitted': 0, 'imported_holdings': 0}
    target = ROOT / 'db/investment_fyers_reconciliation.json'
    target.write_text(json.dumps(output, indent=2))
    target.chmod(0o600)
    print(json.dumps(output, indent=2))
finally:
    remove_all_scoped_sessions()
