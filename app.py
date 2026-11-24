import sys,os,json,time,subprocess,csv
from pathlib import Path
from PyQt5 import QtCore,QtGui,QtWidgets as W
import psutil
from backend import Controller,EnergyAudit,PROFILES,NAMES,SETTINGS,gpu,active,recommendation
BASE=Path(__file__).resolve().parent
class Job(QtCore.QThread):
 result=QtCore.pyqtSignal(object);failed=QtCore.pyqtSignal(str)
 def __init__(self,fn):super().__init__();self.fn=fn
 def run(self):
  try:self.result.emit(self.fn())
  except Exception as e:self.failed.emit(str(e))
class Trace(W.QWidget):
 def __init__(self):super().__init__();self.values=[];self.setMinimumHeight(150)
 def paintEvent(self,event):
  p=QtGui.QPainter(self);p.setRenderHint(p.Antialiasing);r=self.rect().adjusted(12,14,-16,-25);p.fillRect(self.rect(),QtGui.QColor('#101214'))
  p.setPen(QtGui.QColor('#353b3e'));p.drawLine(r.bottomLeft(),r.bottomRight());p.drawLine(r.topLeft(),r.topRight())
  if len(self.values)<2:p.setPen(QtGui.QColor('#a7adb1'));p.drawText(r,QtCore.Qt.AlignCenter,'Waiting for live GPU samples');return
  peak=max(100,max(self.values)*1.15);path=QtGui.QPainterPath()
  for i,v in enumerate(self.values):
   x=r.left()+r.width()*i/max(1,len(self.values)-1);y=r.bottom()-v/peak*r.height()
   if i==0:path.moveTo(x,y)
   else:path.lineTo(x,y)
  p.setPen(QtGui.QPen(QtGui.QColor('#cdd2d5'),2));p.drawPath(path);p.setPen(QtGui.QColor('#a7adb1'));p.drawText(12,12,f'{peak:.0f} W');p.drawText(12,self.height()-5,'GPU board power · latest 120 samples')
class Window(W.QMainWindow):
 def __init__(self):
  super().__init__();self.setWindowTitle('Power Desk — V1');self.resize(1180,850);self.setMinimumSize(1020,740)
  self.c=Controller();self.audit=EnergyAudit();self.session_id=__import__('uuid').uuid4().hex;self.work=None;self.sensor=None;self.snapshot={};self.gpus=[];self.last_switch=0;self.stable=None;self.stable_since=0;self.closing=False
  root=W.QWidget();self.setCentralWidget(root);outer=W.QVBoxLayout(root);outer.setContentsMargins(24,20,24,16);outer.setSpacing(14)
  head=W.QHBoxLayout();title=W.QLabel('Power Desk');title.setObjectName('title');head.addWidget(title);version=W.QLabel('V1  /  LOCAL CONTROL');version.setObjectName('muted');head.addWidget(version);head.addStretch();self.live=W.QLabel('Reading hardware…');head.addWidget(self.live);outer.addLayout(head)
  self.current=W.QLabel('Inspecting your active Windows plan…');self.current.setObjectName('muted');outer.addWidget(self.current)
  metrics=W.QHBoxLayout();self.metric_labels=[]
  for label in ['CPU activity','GPU power','GPU temperature','GPU session energy']:
   box=W.QVBoxLayout();name=W.QLabel(label);name.setObjectName('muted');val=W.QLabel('—');val.setObjectName('metric');box.addWidget(name);box.addWidget(val);metrics.addLayout(box);self.metric_labels.append(val)
  outer.addLayout(metrics)
  self.tabs=W.QTabWidget();outer.addWidget(self.tabs,1)
  self.mode_page();self.advanced_page();self.audit_page();self.automation_page();self.commands_page()
  foot=W.QHBoxLayout();self.status=W.QLabel('Ready. Opening this app does not change power settings.');self.status.setWordWrap(True);foot.addWidget(self.status,1);self.restore=W.QPushButton('Restore original settings');self.restore.clicked.connect(self.restore_all);foot.addWidget(self.restore);outer.addLayout(foot)
  self.setStyleSheet((BASE/'theme.qss').read_text());self.jobs=[];self.load_rules();self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(4000);self.slider.setValue(1);self.select_mode(1);self.refresh();self.poll()
 def page(self,title):
  w=W.QWidget();l=W.QVBoxLayout(w);l.setContentsMargins(20,20,20,20);l.setSpacing(14);scroll=W.QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(W.QFrame.NoFrame);scroll.setWidget(w);self.tabs.addTab(scroll,title);return l
 def label(self,text,muted=False):
  w=W.QLabel(text);w.setWordWrap(True)
  if muted:w.setObjectName('muted')
  return w
 def mode_page(self):
  l=self.page('Modes');l.addWidget(self.label('One mode for the work in front of you.'))
  self.slider=W.QSlider(QtCore.Qt.Horizontal);self.slider.setRange(0,3);self.slider.setTickPosition(W.QSlider.TicksBelow);self.slider.setTickInterval(1);self.slider.setSingleStep(1);self.slider.setAccessibleName('Power mode');self.slider.valueChanged.connect(self.select_mode);l.addWidget(self.slider)
  labels=W.QHBoxLayout()
  for i,n in enumerate(NAMES):
   b=W.QPushButton(n);b.clicked.connect(lambda _,x=i:self.slider.setValue(x));labels.addWidget(b)
  l.addLayout(labels);self.mode_title=W.QLabel();self.mode_title.setObjectName('heading');l.addWidget(self.mode_title);self.description=self.label('');l.addWidget(self.description)
  self.preview=W.QTableWidget(0,2);self.preview.setHorizontalHeaderLabels(['Control','Proposed value']);self.preview.setFixedHeight(270);self.preview.verticalHeader().setDefaultSectionSize(24);self.preview.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch);self.preview.setEditTriggers(W.QAbstractItemView.NoEditTriggers);l.addWidget(self.preview,1)
  self.suggestion=self.label('Task suggestion: reading running applications…',True);l.addWidget(self.suggestion)
  row=W.QHBoxLayout();self.apply_button=W.QPushButton('Apply selected mode');self.apply_button.setObjectName('primary');self.apply_button.clicked.connect(self.apply);row.addWidget(self.apply_button);self.refresh_button=W.QPushButton('Read active settings');self.refresh_button.clicked.connect(self.refresh);row.addWidget(self.refresh_button);row.addStretch();l.addLayout(row)
 def advanced_page(self):
  l=self.page('Advanced');l.addWidget(self.label('Edit the selected mode before applying. Windows settings below affect plugged-in power only; battery settings inherit Balanced. Processor percentages are performance policy, not watt limits.',True))
  form=W.QFormLayout();self.inputs={};descriptions={
  'cpu_min':'Minimum CPU performance (%)','cpu_max':'Maximum CPU performance (%)','epp':'CPU energy preference (0 = speed, 100 = saving)',
  'boost':'CPU boost policy','display':'Turn display off after (minutes; 0 = never)','sleep':'Sleep after (minutes; 0 = never)',
  'disk':'Disk idle timeout (minutes; 0 = never)','pcie':'PCIe link power saving'}
  for key in SETTINGS:
   if key in ['boost','pcie']:
    field=W.QComboBox();field.addItems(['Disabled','Enabled','Aggressive','Efficient enabled','Efficient aggressive','Aggressive at guaranteed','Efficient aggressive at guaranteed'] if key=='boost' else ['Off','Moderate','Maximum']);field.currentIndexChanged.connect(self.update_preview)
   else:
    field=W.QSpinBox();field.setRange(SETTINGS[key][2],1440 if key in ['display','sleep','disk'] else SETTINGS[key][3]);field.valueChanged.connect(self.update_preview)
   field.setAccessibleName(descriptions[key]);self.inputs[key]=field;form.addRow(descriptions[key],field)
  l.addLayout(form)
  self.gpu_enabled=W.QCheckBox('Also set GPU board power limit (driver permission required)');self.gpu_enabled.toggled.connect(self.update_preview);l.addWidget(self.gpu_enabled)
  self.gpu_limit=W.QSpinBox();self.gpu_limit.setRange(1,2000);self.gpu_limit.setSuffix(' W');self.gpu_limit.valueChanged.connect(self.update_preview);form2=W.QFormLayout();form2.addRow('GPU power ceiling',self.gpu_limit);l.addLayout(form2)
  self.gpu_support=self.label('Detecting driver limits…',True);l.addWidget(self.gpu_support)
  l.addWidget(self.label('Sleep defaults to Never so downloads and renders continue. Disk sleep stays disabled for active work. CPU policy effectiveness depends on hardware. No voltage, fan curve, overclock, BIOS or PSU changes.',True))
  b=W.QPushButton('Apply these settings');b.clicked.connect(self.apply);l.addWidget(b);self.actual=W.QPlainTextEdit();self.actual.setReadOnly(True);self.actual.setMaximumHeight(145);l.addWidget(self.actual);l.addStretch()
 def audit_page(self):
  l=self.page('Energy audit');l.addWidget(self.label('Measured GPU energy, with coverage stated explicitly.'))
  self.trace=Trace();l.addWidget(self.trace);self.audit_summary=self.label('Collecting samples…');l.addWidget(self.audit_summary)
  self.sensor_table=W.QTableWidget(0,4);self.sensor_table.setHorizontalHeaderLabels(['Sensor','Reading','Source','Coverage']);self.sensor_table.setMinimumHeight(225);self.sensor_table.verticalHeader().setDefaultSectionSize(28);self.sensor_table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch);self.sensor_table.setEditTriggers(W.QAbstractItemView.NoEditTriggers);l.addWidget(self.sensor_table)
  self.cost=W.QDoubleSpinBox();self.cost.setDecimals(3);self.cost.setRange(0,10);self.cost.setValue(.20);self.cost.setSuffix(' $ / kWh');row=W.QHBoxLayout();row.addWidget(self.label('Electricity price'));row.addWidget(self.cost);self.cost_label=self.label('');row.addWidget(self.cost_label);row.addStretch();l.addLayout(row)
  l.addWidget(self.label('Wh is integrated from sampled GPU board power; gaps over 20 seconds are excluded. This is not wall power, total PC energy, or proof of efficiency. Compare the same task and completion time across modes.',True))
  row=W.QHBoxLayout();export=W.QPushButton('Export session CSV');export.clicked.connect(self.export_audit);row.addWidget(export);hw=W.QPushButton('Open installed HWMonitor');hw.clicked.connect(self.open_hwmonitor);row.addWidget(hw);row.addStretch();l.addLayout(row)
  l.addWidget(self.label('CPUID HWMonitor is installed. Its commercial sensor SDK is not bundled here. CPU package watts and PSU / wall watts are unavailable in this V1; the audit never estimates them from CPU usage.',True))
 def automation_page(self):
  l=self.page('Automation');l.addWidget(self.label('Optional task-based switching'));self.auto=W.QCheckBox('Enable automatic Windows modes while Power Desk is open');l.addWidget(self.auto)
  l.addWidget(self.label('A task must remain detected for 30 seconds, with at least 60 seconds between automatic changes. Manual Apply turns automation off. Automatic rules do not change GPU limits.',True))
  self.rules=W.QTableWidget(0,2);self.rules.setHorizontalHeaderLabels(['Application process','Mode']);self.rules.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
  for process,mode in [('blender.exe','Create'),('unrealeditor.exe','Create'),('resolve.exe','Create'),('afterfx.exe','Create'),('bittorrent.exe','Quiet'),('qbittorrent.exe','Quiet'),('chrome.exe','Quiet'),('brave.exe','Quiet')]:
   row=self.rules.rowCount();self.rules.insertRow(row);self.rules.setItem(row,0,W.QTableWidgetItem(process));combo=W.QComboBox();combo.addItems(NAMES);combo.setCurrentText(mode);self.rules.setCellWidget(row,1,combo)
  l.addWidget(self.rules);buttons=W.QHBoxLayout();add=W.QPushButton('Add rule');add.clicked.connect(self.add_rule);save=W.QPushButton('Save rules');save.clicked.connect(self.save_rules);buttons.addWidget(add);buttons.addWidget(save);buttons.addStretch();l.addLayout(buttons);self.auto_status=self.label('Automatic switching is off.');l.addWidget(self.auto_status);l.addWidget(self.label('Rules use running process names, not a claim that a render is active. If multiple rules match, the higher-performance mode wins. With no matches, use Everyday. Automation stops when this app closes.',True))
 def load_rules(self):
  path=self.c.home/'rules.json'
  if not path.exists():return
  try:
   rows=json.loads(path.read_text(encoding='utf-8'))
   if not isinstance(rows,list):return
   self.rules.setRowCount(0)
   for item in rows[:100]:
    if item.get('mode') not in NAMES:continue
    r=self.rules.rowCount();self.rules.insertRow(r);self.rules.setItem(r,0,W.QTableWidgetItem(str(item['process'])));combo=W.QComboBox();combo.addItems(NAMES);combo.setCurrentText(item['mode']);self.rules.setCellWidget(r,1,combo)
  except (ValueError,KeyError,TypeError):self.status.setText('Saved automation rules could not be read; using defaults.')
 def save_rules(self):
  rows=[dict(process=self.rules.item(r,0).text(),mode=self.rules.cellWidget(r,1).currentText()) for r in range(self.rules.rowCount()) if self.rules.item(r,0)]
  (self.c.home/'rules.json').write_text(json.dumps(rows,indent=2),encoding='utf-8');self.status.setText('Automation rules saved. Switching remains opt-in.')
 def add_rule(self):
  r=self.rules.rowCount();self.rules.insertRow(r);self.rules.setItem(r,0,W.QTableWidgetItem('application.exe'));combo=W.QComboBox();combo.addItems(NAMES);self.rules.setCellWidget(r,1,combo)
 def commands_page(self):
  l=self.page('Commands');l.addWidget(self.label('Power commands and automation entry points'))
  self.command_preview=W.QPlainTextEdit();self.command_preview.setReadOnly(True);l.addWidget(self.command_preview,1)
  row=W.QHBoxLayout();save=W.QPushButton('Export PowerShell entry points');save.clicked.connect(self.export_scripts);row.addWidget(save);folder=W.QPushButton('Open local logs');folder.clicked.connect(lambda:os.startfile(str(self.c.home)));row.addWidget(folder);row.addStretch();l.addLayout(row)
  self.log=W.QPlainTextEdit();self.log.setReadOnly(True);l.addWidget(self.log,1);l.addWidget(self.label('Commands use argument lists, never downloaded scripts or an unrestricted shell. CLI: app.py --apply Quiet | --restore | --inspect | --audit-seconds 60 --csv path.csv. Run in an elevated terminal only if Windows reports a permission failure.',True))
 def values(self):
  return {k:(f.currentIndex() if isinstance(f,W.QComboBox) else f.value()*(60 if k in ['display','sleep','disk'] else 1)) for k,f in self.inputs.items()}
 def select_mode(self,index):
  if not hasattr(self,'inputs'):return
  name=NAMES[index];self.mode_title.setText(name);self.description.setText({'Quiet':'Browsing and downloads. Lower CPU policy and no boost; the computer stays awake.','Everyday':'Responsive desktop work with a balanced energy preference.','Create':'Blender, Unreal and editing. Full CPU range with a performance preference.','Render':'Sustained jobs. Full CPU range and aggressive boost; compare energy per completed job.'}[name])
  for k,v in PROFILES[name].items():
   f=self.inputs[k];f.blockSignals(True)
   if isinstance(f,W.QComboBox):f.setCurrentIndex(v)
   else:f.setValue(v//60 if k in ['display','sleep','disk'] else v)
   f.blockSignals(False)
  if self.gpus and self.gpus[0]['min'] is not None and self.gpus[0]['default'] is not None:
   g=self.gpus[0];self.gpu_limit.setValue(round(g['min']+(g['default']-g['min'])*index/3))
  self.update_preview()
 def update_preview(self,*_):
  if not hasattr(self,'inputs') or len(self.inputs)!=len(SETTINGS) or not hasattr(self,'gpu_enabled'):return
  vals=self.values();rows=[(k.replace('_',' ').title(),str(v)+(' seconds' if k in ['display','sleep','disk'] else '')) for k,v in vals.items()]
  rows.append(('GPU power limit',str(self.gpu_limit.value())+' W' if self.gpu_enabled.isChecked() else 'Unchanged'))
  self.preview.setRowCount(len(rows))
  for i,(a,b) in enumerate(rows):self.preview.setItem(i,0,W.QTableWidgetItem(a));self.preview.setItem(i,1,W.QTableWidgetItem(b))
  commands=['# Preview only. A fresh Balanced-based plan is created on Apply.','powercfg /duplicatescheme '+__import__('backend').BALANCED+' <new-plan-guid>']
  commands+=['powercfg /setacvalueindex <new-plan-guid> '+SETTINGS[k][0]+' '+SETTINGS[k][1]+' '+str(v) for k,v in vals.items()]
  if self.gpu_enabled.isChecked():commands.append('nvidia-smi -i <detected-gpu-uuid> -pl '+str(self.gpu_limit.value()))
  commands.append('powercfg /setactive <new-plan-guid>');self.command_preview.setPlainText('\n'.join(commands))
 def run_job(self,fn,callback):
  if self.work and self.work.isRunning():return
  self.apply_button.setEnabled(False);self.restore.setEnabled(False);self.refresh_button.setEnabled(False);self.status.setText('Working…')
  self.work=Job(fn);self.work.result.connect(callback);self.work.failed.connect(self.failure);self.work.finished.connect(self.unbusy);self.work.start()
 def unbusy(self):
  self.apply_button.setEnabled(True);self.restore.setEnabled(True);self.refresh_button.setEnabled(True);self.log.setPlainText('\n'.join(self.c.commands[-150:]))
 def failure(self,message):self.status.setText('Could not complete: '+message);self.auto.setChecked(False)
 def refresh(self):self.run_job(self.c.inspect,self.inspected)
 def inspected(self,data):
  self.snapshot=data;self.current.setText('Active plan: '+data['label'].split('(',1)[-1].rstrip(')'));
  if data['state'].get('backup_note'):self.log.appendPlainText(data['state']['backup_note'])
  self.actual.setPlainText('\n'.join(f'{k}: AC {v[0]} / battery {v[1]}' for k,v in data['values'].items())+'\n'+'\n'.join(data['errors'].values()));self.status.setText('Active settings read. Select a mode to preview changes.')
 def apply(self,automatic=False,name=None):
  if not automatic:self.auto.setChecked(False)
  n=name or NAMES[self.slider.value()];v=dict(PROFILES[n]) if automatic else self.values();limit=None if automatic or not self.gpu_enabled.isChecked() else self.gpu_limit.value()
  def action():
   result=self.c.apply(n,v,limit)
   return result,self.c.inspect()
  self.run_job(action,self.applied)
 def applied(self,result):
  text,data=result;self.inspected(data);self.status.setText(text);self.last_switch=time.monotonic()
 def restore_all(self):
  self.auto.setChecked(False)
  self.run_job(lambda:(self.c.restore(),self.c.inspect()),self.applied)
 def poll(self):
  self.metric_labels[0].setText(f'{psutil.cpu_percent():.0f}%');
  if self.sensor and self.sensor.isRunning():return
  self.sensor=Job(lambda:(gpu(),[p.info['name'] or '' for p in psutil.process_iter(['name'])]));self.sensor.result.connect(self.sampled);self.sensor.failed.connect(lambda e:self.live.setText('Sensor read unavailable'));self.sensor.start()
 def sampled(self,data):
  gs,processes=data;first=not self.gpus;self.gpus=gs;g=gs[0] if gs else {};watts=g.get('watts');self.live.setText(g.get('name','GPU sensor unavailable'))
  if first and g and all(g.get(k) is not None for k in ['min','default']):
   self.gpu_limit.setRange(round(g['min']),round(g['default']));self.gpu_limit.setValue(round(g['limit']));self.gpu_support.setText(('Standard session: GPU changes may require administrator permission. ' if not __import__('ctypes').windll.shell32.IsUserAnAdmin() else 'Elevated session; driver support still required. ')+f"Driver range {g['min']:.0f}–{g['max']:.0f} W. V1 ceiling capped at factory default {g['default']:.0f} W. A ceiling is not idle consumption.")
  elif not g:self.gpu_enabled.setChecked(False);self.gpu_enabled.setEnabled(False);self.gpu_support.setText('No supported NVIDIA readings found.')
  self.audit.add(watts,session_id=self.session_id,mode=self.c.state.get('current_mode','External/original'),cpu_percent=psutil.cpu_percent(),gpu_utilization=g.get('utilization'),gpu_temperature=g.get('temperature'),gpu_limit=g.get('limit'))
  avg,peak,wh=self.audit.stats();self.metric_labels[1].setText(f'{watts:.1f} W' if watts is not None else 'Unavailable');self.metric_labels[2].setText(f"{g['temperature']:.0f} °C" if g.get('temperature') is not None else 'Unavailable');self.metric_labels[3].setText(f'{wh:.3f} Wh')
  vals=[r['gpu_watts'] for r in self.audit.rows[-120:] if r['gpu_watts'] is not None];self.trace.values=vals;self.trace.update()
  self.audit_summary.setText(f'{len(self.audit.rows)} samples · Average {avg:.1f} W · Peak {peak:.1f} W · {wh:.3f} GPU Wh' if avg is not None else 'No supported wattage readings.');self.cost_label.setText(f'GPU session cost: ${wh/1000*self.cost.value():.5f}')
  rows=[('CPU utilization',self.metric_labels[0].text(),'Windows / psutil','Activity; not power'),('GPU board power',self.metric_labels[1].text(),'NVIDIA driver','GPU only'),('GPU power ceiling',str(g.get('limit','Unavailable'))+' W','NVIDIA driver','Maximum policy'),('GPU utilization',str(g.get('utilization','Unavailable'))+'%','NVIDIA driver','Activity'),('CPU package power','Unavailable','No sensor provider connected','Not estimated'),('Whole-PC / PSU input','Unavailable','External meter / supported PSU required','Not GPU + CPU sum')]
  self.sensor_table.setRowCount(len(rows))
  for i,row in enumerate(rows):
   for j,v in enumerate(row):self.sensor_table.setItem(i,j,W.QTableWidgetItem(v))
  found=[]
  for r in range(self.rules.rowCount()):
   item=self.rules.item(r,0)
   if item and item.text().strip().lower() in {p.lower() for p in processes}:found.append(self.rules.cellWidget(r,1).currentText())
  target=max(found,key=NAMES.index) if found else 'Everyday';self.suggestion.setText('Task suggestion: '+target+' · running processes only');now=time.monotonic()
  if target!=self.stable:self.stable=target;self.stable_since=now
  if self.auto.isChecked():
   self.auto_status.setText('Detected '+target+'; waiting for stability / cooldown.')
   if now-self.stable_since>=30 and now-self.last_switch>=60 and self.c.state.get('current_mode')!=target and not (self.work and self.work.isRunning()):self.apply(True,target)
  else:self.auto_status.setText('Automatic switching is off.')
  logpath=self.c.home/'audit-session.csv'
  new=not logpath.exists()
  with logpath.open('a',newline='',encoding='utf-8') as f:
   writer=csv.DictWriter(f,fieldnames=self.audit.rows[-1])
   if new:writer.writeheader()
   writer.writerow(self.audit.rows[-1])
 def export_audit(self):
  path,_=W.QFileDialog.getSaveFileName(self,'Export GPU audit',str(BASE/'power-audit.csv'),'CSV (*.csv)')
  if path:
   try:self.audit.export(path);self.status.setText('Exported '+path)
   except Exception as e:self.failure(str(e))
 def export_scripts(self):
  folder=W.QFileDialog.getExistingDirectory(self,'Choose script destination',str(BASE))
  if not folder:return
  python=str(Path(sys.executable).with_name('python.exe'));entry=str(BASE/'app.py')
  for name,args in [(n,['--apply',n]) for n in NAMES]+[('Restore',['--restore']),('Inspect',['--inspect'])]:
   content="& '"+python.replace("'","''")+"' '"+entry.replace("'","''")+"' "+' '.join(args)+'\nif ($LASTEXITCODE -ne 0) { throw "Power Desk failed; inspect the command output." }\n'
   (Path(folder)/(name+'.ps1')).write_text(content)
  self.status.setText('Exported mode, restore and inspect PowerShell scripts.')
 def open_hwmonitor(self):
  candidates=[Path(r'C:\Program Files\CPUID\HWMonitor\HWMonitor.exe'),Path(r'C:\Program Files\CPUID\HWMonitor\HWMonitor_x64.exe')]
  for p in candidates:
   if p.exists():os.startfile(str(p));return
  self.status.setText('HWMonitor executable not found at the known installation path.')
 def closeEvent(self,event):
  if self.work and self.work.isRunning():self.status.setText('Wait for the current power operation to finish before closing.');event.ignore();return
  self.timer.stop()
  if self.sensor and self.sensor.isRunning():
   self.closing=True;self.sensor.finished.connect(self.close);self.status.setText('Finishing sensor read…');event.ignore();return
  event.accept()

def cli():
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--apply',choices=NAMES);parser.add_argument('--restore',action='store_true');parser.add_argument('--inspect',action='store_true');parser.add_argument('--audit-seconds',type=int);parser.add_argument('--csv',default='power-audit.csv');args=parser.parse_args()
 if args.apply or args.restore or args.inspect:
  c=Controller()
  if args.apply:print(c.apply(args.apply,PROFILES[args.apply]))
  elif args.restore:print(c.restore())
  else:print(json.dumps(c.inspect(),indent=2))
  return True
 if args.audit_seconds is not None:
  if not 1<=args.audit_seconds<=86400:parser.error('Audit duration must be 1–86400 seconds.')
  a=EnergyAudit();end=time.monotonic()+args.audit_seconds
  while time.monotonic()<end:
   gs=gpu();a.add(gs[0].get('watts') if gs else None);time.sleep(min(4,max(0,end-time.monotonic())))
  a.export(args.csv);print('Saved GPU-only audit to '+args.csv);return True
 return False
if __name__=='__main__':
 try:
  if not cli():
   app=W.QApplication(sys.argv);app.setStyle('Fusion');window=Window();window.show();sys.exit(app.exec_())
 except Exception as e:
  if sys.stdout:print(str(e),file=sys.stderr)
  Path(os.environ.get('LOCALAPPDATA','.')).joinpath('PowerDesk').mkdir(exist_ok=True)
  Path(os.environ.get('LOCALAPPDATA','.')).joinpath('PowerDesk/startup-error.log').write_text(str(e));sys.exit(1)
