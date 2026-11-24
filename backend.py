"""Windows power controls. No game code or untrusted scripts are executed."""
import csv, ctypes, datetime, json, os, re, subprocess, time, uuid, functools, msvcrt
from pathlib import Path
BALANCED='381b4222-f694-41f0-9685-ff5bb260df2e'
SETTINGS={
 'cpu_min':('SUB_PROCESSOR','PROCTHROTTLEMIN',0,100),
 'cpu_max':('SUB_PROCESSOR','PROCTHROTTLEMAX',1,100),
 'epp':('SUB_PROCESSOR','36687f9e-e3a5-4dbf-b1dc-15eb381c6863',0,100),
 'boost':('SUB_PROCESSOR','be337238-0d82-4146-a960-4f3749d470c7',0,6),
 'display':('SUB_VIDEO','VIDEOIDLE',0,86400),
 'sleep':('SUB_SLEEP','STANDBYIDLE',0,86400),
 'disk':('SUB_DISK','DISKIDLE',0,86400),
 'pcie':('SUB_PCIEXPRESS','ASPM',0,2)}
PROFILES={
 'Quiet':dict(cpu_min=5,cpu_max=70,epp=80,boost=0,display=600,sleep=0,disk=0,pcie=1),
 'Everyday':dict(cpu_min=5,cpu_max=100,epp=50,boost=3,display=900,sleep=0,disk=0,pcie=1),
 'Create':dict(cpu_min=5,cpu_max=100,epp=20,boost=1,display=1800,sleep=0,disk=0,pcie=0),
 'Render':dict(cpu_min=5,cpu_max=100,epp=0,boost=2,display=600,sleep=0,disk=0,pcie=0)}
NAMES=list(PROFILES)
class PowerError(RuntimeError):pass

def execute(args):
 r=subprocess.run(args,capture_output=True,text=True,errors='replace',timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 if r.returncode:raise PowerError((r.stderr or r.stdout or 'Command failed').strip())
 return r.stdout.strip()

def active():
 text=execute(['powercfg','/getactivescheme']); match=re.search(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',text)
 if not match:raise PowerError('Cannot read current power scheme: '+text)
 return match[0].lower(),text

def read_setting(scheme,key):
 group,setting,_,_=SETTINGS[key];text=execute(['powercfg','/qh',scheme,group,setting]);nums=re.findall(r'0x([0-9a-fA-F]{8})',text)
 if len(nums)<2:raise PowerError('Setting unavailable: '+key)
 return int(nums[-2],16),int(nums[-1],16)

def validate(values):
 if set(values)!=set(SETTINGS):raise ValueError('Expected all eight Windows controls.')
 for key,value in values.items():
  if type(value)!=int or not SETTINGS[key][2]<=value<=SETTINGS[key][3]:raise ValueError('Out of range: '+key)
 if values['cpu_min']>values['cpu_max']:raise ValueError('CPU minimum cannot exceed maximum.')

def gpu():
 fields='uuid,name,power.draw,power.limit,power.min_limit,power.max_limit,power.default_limit,temperature.gpu,utilization.gpu'
 try:
  data=execute(['nvidia-smi','--query-gpu='+fields,'--format=csv,noheader,nounits']);result=[]
  for row in csv.reader(data.splitlines()):
   row=[x.strip() for x in row]
   d=dict(uuid=row[0],name=row[1]);
   for k,v in zip(['watts','limit','min','max','default','temperature','utilization'],row[2:]):
    try:d[k]=float(v)
    except ValueError:d[k]=None
   result.append(d)
  return result
 except (OSError,PowerError,subprocess.TimeoutExpired):return []


def exclusive(fn):
 @functools.wraps(fn)
 def wrapped(self,*args,**kwargs):
  with (self.home/'operation.lock').open('a+b') as lock:
   lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
   try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
   except OSError:raise PowerError('Another Power Desk operation is in progress.')
   try:
    if self.path.exists():self.state=json.loads(self.path.read_text())
    return fn(self,*args,**kwargs)
   finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
 return wrapped

class Controller:
 def __init__(self,state_dir=None):
  self.home=Path(state_dir or Path(os.environ.get('LOCALAPPDATA','.'))/'PowerDesk');self.home.mkdir(parents=True,exist_ok=True);self.path=self.home/'state.json'
  self.state=json.loads(self.path.read_text()) if self.path.exists() else {};self.commands=[]
 def save(self):
  temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.state,indent=2));temp.replace(self.path)
 def run(self,args):
  line=subprocess.list2cmdline(args);self.commands.append(line)
  with (self.home/'commands.log').open('a',encoding='utf-8') as f:f.write(datetime.datetime.now().isoformat()+' '+line+'\n')
  return execute(args)
 def inspect(self):
  scheme,label=active();values={};errors={}
  for key in SETTINGS:
   try:values[key]=read_setting(scheme,key)
   except (PowerError,subprocess.TimeoutExpired) as e:errors[key]=str(e)
  return dict(scheme=scheme,label=label,values=values,errors=errors,state=self.state)
 @exclusive
 def apply(self,name,values,gpu_limit=None):
  validate(values)
  if name not in NAMES:raise ValueError('Unknown mode')
  before,_=active();current_gpu=gpu();target=current_gpu[0] if current_gpu else None
  if gpu_limit is not None:
   if not target or any(target.get(k) is None for k in ['min','max','limit']):raise PowerError('GPU power-limit control unavailable.')
   if not target['min']<=gpu_limit<=target['max']:raise ValueError('GPU power limit outside driver range.')
  if not self.state.get('original_scheme'):
   snapshot=self.inspect()
   if snapshot['errors']:raise PowerError('Cannot back up all original settings: '+str(snapshot['errors']))
   (self.home/'original-plan.json').write_text(json.dumps(snapshot,indent=2))
   self.state['original_scheme']=before
   try:self.run(['powercfg','/export',str(self.home/'original-plan.pow'),before])
   except PowerError as e:self.state['backup_note']='Native .pow export unavailable; original plan is untouched and JSON settings backup saved. '+str(e)
  if target and 'original_gpu' not in self.state:self.state['original_gpu']={'uuid':target['uuid'],'limit':target['limit']}
  scheme=str(uuid.uuid4());self.state.setdefault('managed_schemes',[]).append(scheme);self.save()
  switched=False;gpu_changed=False;was_touched=self.state.get('gpu_touched',False)
  try:
   self.run(['powercfg','/duplicatescheme',BALANCED,scheme]);self.run(['powercfg','/changename',scheme,'Power Desk — '+name])
   for key,value in values.items():
    group,setting,_,_=SETTINGS[key];self.run(['powercfg','/setacvalueindex',scheme,group,setting,str(value)])
    ac,_=read_setting(scheme,key)
    if ac!=value:raise PowerError('Windows did not retain '+key)
   if gpu_limit is not None:
    self.run(['nvidia-smi','-i',target['uuid'],'-pl',str(gpu_limit)]);gpu_changed=True;self.state['gpu_touched']=True;self.save()
    check=gpu()
    if not check or check[0]['uuid']!=target['uuid'] or check[0]['limit'] is None or abs(check[0]['limit']-gpu_limit)>1:raise PowerError('GPU limit did not verify.')
   self.run(['powercfg','/setactive',scheme]);switched=True
   if active()[0]!=scheme:raise PowerError('Power scheme activation did not verify.')
   self.state.update(current_mode=name,current_scheme=scheme,last_values=values);self.save()
   return 'Applied '+name+'. Windows AC settings verified.'+(' GPU cap requested; inspect live limit.' if gpu_changed else '')
  except Exception as e:
   rollback=[]
   if switched:
    try:self.run(['powercfg','/setactive',before])
    except Exception as x:rollback.append(str(x))
   if gpu_changed:
    try:self.run(['nvidia-smi','-i',target['uuid'],'-pl',str(target['limit'])]);self.state['gpu_touched']=was_touched;self.save()
    except Exception as x:rollback.append(str(x))
   raise PowerError(str(e)+ (' | Rollback issue: '+'; '.join(rollback) if rollback else ' | Previous active plan preserved/restored.'))
 @exclusive
 def restore(self):
  original=self.state.get('original_scheme')
  if not original:return 'No settings have been applied by Power Desk.'
  self.run(['powercfg','/setactive',original])
  if active()[0]!=original:raise PowerError('Original plan activation failed verification.')
  g=self.state.get('original_gpu')
  if g and self.state.get('gpu_touched'):
   self.run(['nvidia-smi','-i',g['uuid'],'-pl',str(g['limit'])]);self.state['gpu_touched']=False
  self.state.pop('current_mode',None);self.state.pop('current_scheme',None);self.save();return 'Original Windows plan restored.'

def recommendation(processes):
 names={n.lower() for n in processes}
 if names.intersection({'blender.exe','unrealeditor.exe','resolve.exe','afterfx.exe'}):return 'Create'
 if names.intersection({'bittorrent.exe','qbittorrent.exe','chrome.exe','brave.exe','msedge.exe','firefox.exe'}):return 'Quiet'
 return 'Everyday'

class EnergyAudit:
 def __init__(self):self.rows=[];self.wh=0.;self.last=None
 def add(self,watts,**data):
  now=time.monotonic();valid=watts is not None and watts>=0
  if valid and self.last and 0<now-self.last[0]<=20:self.wh+=(watts+self.last[1])/2*(now-self.last[0])/3600
  self.last=(now,watts) if valid else None
  self.rows.append(dict(timestamp=datetime.datetime.now().astimezone().isoformat(),gpu_watts=watts,gpu_wh=self.wh,**data))
 def stats(self):
  vals=[r['gpu_watts'] for r in self.rows if r['gpu_watts'] is not None]
  return (sum(vals)/len(vals),max(vals),self.wh) if vals else (None,None,0)
 def export(self,path):
  if not self.rows:raise ValueError('No samples yet.')
  with open(path,'w',newline='',encoding='utf-8') as f:
   w=csv.DictWriter(f,fieldnames=self.rows[0]);w.writeheader();w.writerows(self.rows)
