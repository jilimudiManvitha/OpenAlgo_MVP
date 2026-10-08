"""Review commit candidates without printing credential values."""
import gzip,hashlib,json,re,subprocess
from pathlib import Path
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[2]
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT).decode().split('\0')
tracked=set(filter(None,git('diff','--name-only','-z','HEAD')))
new=set(filter(None,git('ls-files','--others','--exclude-standard','-z')))
# Already tracked production bundle requires its new content-hashed files too.
bundle={str(p.relative_to(ROOT)) for p in (ROOT/'frontend/dist').rglob('*') if p.is_file() and not p.name.endswith(('.gz','.br','.tmp'))}
candidates=sorted(tracked|new|bundle)
values=dotenv_values(ROOT/'.env');secrets={k:v for k,v in values.items() if re.search(r'(SECRET|PASSWORD|PEPPER|TOKEN|API_KEY|APP_KEY|SALT)',k) and v and len(v)>=10 and 'your_' not in v.lower() and v.lower() not in ('none','changeme')}
findings=[];large=[];counts={'files':0,'bytes':0,'compressed_scanned':0}
for name in candidates:
 p=ROOT/name
 if not p.is_file():continue
 assert not name.startswith(('db/','log/','.venv/')),name
 raw=p.read_bytes();counts['files']+=1;counts['bytes']+=len(raw)
 if len(raw)>95_000_000:large.append(name)
 if name.endswith('.gz'):
  raw=gzip.decompress(raw);counts['compressed_scanned']+=1
 for key,value in secrets.items():
  if value.encode() in raw:findings.append({'path':name,'environment_key':key})
 for label,pattern in [('private_key',rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),('github_token',rb'gh[pousr]_[A-Za-z0-9]{30,}'),('jwt',rb'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}')]:
  if re.search(pattern,raw):findings.append({'path':name,'pattern':label})
print(json.dumps({'counts':counts,'findings':findings,'oversized':large},indent=2))
Path('/tmp/openalgo-stage-paths').write_bytes(b'\0'.join(n.encode() for n in candidates)+b'\0')
assert not findings and not large,'Review findings before staging'
