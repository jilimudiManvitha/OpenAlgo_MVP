"""Sequential normal-bundle UI checks; owns and reaps only its fixture children."""
import socket
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'log/test/oct8-project'
for lane,flags in [('investment',[]),('report-journal',[]),('report-journal',['--modes']),('trade-copier',[])]:
    tag=lane+('-modes' if flags else '')
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',5011))==0:raise RuntimeError('Port 5011 occupied; refusing to stop another process')
    with (OUT/(tag+'-server.log')).open('w') as log:
        child=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'.development'/lane/'browser_server.py'),'--production-bundle'],stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
        try:
            for _ in range(150):
                if child.poll() is not None:raise RuntimeError(tag+' server failed')
                with socket.socket() as s:
                    if s.connect_ex(('127.0.0.1',5011))==0:break
                time.sleep(.2)
            else:raise RuntimeError(tag+' startup timeout')
            with (OUT/(tag+'-browser.log')).open('w') as result:
                subprocess.run(['node',str(ROOT/'.development'/lane/'verify_ui.cjs'),*flags],stdout=result,stderr=subprocess.STDOUT,cwd=ROOT,check=True,timeout=180)
            print(tag+' browser checks passed',flush=True)
        finally:
            child.terminate()
            try:child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill();child.wait(timeout=5)
