import tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from backend import *
class Controls(unittest.TestCase):
 def test_invalid_values_cannot_execute(self):
  for key in SETTINGS:
   values=dict(PROFILES['Quiet']);values[key]=SETTINGS[key][3]+1
   with self.assertRaises(ValueError):validate(values)
  values=dict(PROFILES['Quiet']);values['cpu_min']=90
  with self.assertRaises(ValueError):validate(values)
 def test_energy_integrates_and_excludes_gaps(self):
  a=EnergyAudit()
  with patch('backend.time.monotonic',side_effect=[0,10,40,50]):
   a.add(100);a.add(200);a.add(300);a.add(None)
  self.assertAlmostEqual(a.wh,150*10/3600)
 def test_failed_configuration_does_not_activate(self):
  with tempfile.TemporaryDirectory() as d:
   c=Controller(d);calls=[]
   def fail(args):
    calls.append(args)
    if '/setacvalueindex' in args:raise PowerError('denied')
    return ''
   with patch('backend.active',return_value=(BALANCED,'Balanced')),patch('backend.gpu',return_value=[]),patch.object(c,'run',side_effect=fail),patch('backend.read_setting',return_value=(0,0)):
    with self.assertRaises(PowerError):c.apply('Quiet',PROFILES['Quiet'])
   self.assertFalse(any('/setactive' in row for row in calls))
   self.assertEqual(c.state['original_scheme'],BALANCED)
 def test_no_gpu_write_when_not_selected(self):
  with tempfile.TemporaryDirectory() as d:
   c=Controller(d);calls=[];now=[BALANCED]
   def run(args):
    calls.append(args)
    if '/setactive' in args:now[0]=args[-1]
    return ''
   with patch('backend.active',side_effect=lambda:(now[0],'')),patch('backend.gpu',return_value=[]),patch('backend.read_setting',side_effect=lambda _,k:(PROFILES['Quiet'][k],0)),patch.object(c,'run',side_effect=run):
    c.apply('Quiet',PROFILES['Quiet']);c.restore()
   self.assertEqual(now[0],BALANCED)
   self.assertFalse(any(row[0]=='nvidia-smi' for row in calls))
 def test_gpu_failure_before_activation(self):
  target=dict(uuid='test',min=100,max=400,limit=300)
  with tempfile.TemporaryDirectory() as d:
   c=Controller(d);calls=[]
   def run(args):
    calls.append(args)
    if args[0]=='nvidia-smi':raise PowerError('No permission')
    return ''
   with patch('backend.active',return_value=(BALANCED,'')),patch('backend.gpu',return_value=[target]),patch('backend.read_setting',side_effect=lambda _,k:(PROFILES['Quiet'][k],0)),patch.object(c,'run',side_effect=run):
    with self.assertRaises(PowerError):c.apply('Quiet',PROFILES['Quiet'],200)
   self.assertFalse(any('/setactive' in row for row in calls))
if __name__=='__main__':unittest.main()
