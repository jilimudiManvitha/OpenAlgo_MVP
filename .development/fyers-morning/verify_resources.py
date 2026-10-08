"""Isolated failure-path resource and bounded-counter verification."""
import gc
import json
import os
import runpy
import sys
import tempfile
import tracemalloc
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
runpy.run_path(str(ROOT/'test/conftest.py'))
import psutil
from broker.fyers.api import data_budget as b
with tempfile.TemporaryDirectory(dir=ROOT/'log/test/fyers-morning') as folder:
 os.environ['FYERS_DATA_BUDGET_DIR']=folder
 os.environ['BROKER_API_KEY']='resource-fixture'
 now=[1800000000.0]
 b.time.time=lambda:now[0]
 p=psutil.Process();tracemalloc.start()
 def cycle():
  b.acquire()
  b.cooldown(60)
  try: b.acquire()
  except b.DataRateLimited: pass
  now[0]+=61
 for _ in range(10): cycle()
 gc.collect();before=(p.num_fds(),tracemalloc.get_traced_memory()[0])
 for _ in range(300):cycle()
 gc.collect();after=(p.num_fds(),tracemalloc.get_traced_memory()[0])
 state=json.loads(b.state_path().read_text())
 assert before[0]==after[0]
 assert len(state['calls'])<=45
 result={'iterations':300,'fds_before':before[0],'fds_after':after[0],
         'retained_bytes_delta':after[1]-before[1],'counter_file_bytes':b.state_path().stat().st_size,
         'entries':len(state['calls'])}
 print(json.dumps(result))
 (ROOT/'log/test/fyers-morning/resources.json').write_text(json.dumps(result))
