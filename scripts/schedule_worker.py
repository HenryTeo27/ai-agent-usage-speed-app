"""Exercise a real, hidden event loop with isolated data and fake scan sources."""
import json
from pathlib import Path
import sys
import time

if '_codex_meter_runtime' in sys.modules:
    meter=sys.modules['_codex_meter_runtime']
else:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import meter
meter.load_gui()
meter.App.show=lambda app:None
meter.App.setup_tray=lambda app:None
meter.App.publish_ready=lambda app:None
meter.tk.Toplevel.deiconify=lambda window:None
meter.tk.Toplevel.grab_set=lambda window:None
old={'month':'2026-10','month_tokens':10,'month_cost':1,'total_tokens':111,'total_cost':2}
meter.save(meter.CONFIG,{'interval':4,'reserve':0,'appearance':'system'})
meter.save(meter.SNAPSHOT,{'usage':old,'limits':{},'speed':{'1':[],'14':[]},'last_refresh_at':time.time()-3*3600})
meter.get_usage=lambda:{**old,'total_tokens':130}
meter.get_limits=lambda:{}
meter.get_speed=lambda:({'1':[],'14':[]},'')
app=meter.App();result={'changed':False,'completed':False,'error':None}
def change():
    try:
        assert not app.busy
        app.settings_dialog();app.settings_vars['interval'].set('2 hours')
        result['changed']=meter.read(meter.CONFIG,{})['interval']==2
    except Exception as exc:
        result['error']=str(exc);app.root.quit()
def check():
    if app.data.get('usage',{}).get('total_tokens')==130 and not app.busy:
        result['completed']=True;app.root.quit()
    else: app.root.after(25,check)
app.root.after(100,change);app.root.after(125,check);app.root.after(8000,app.root.quit)
try:
    app.run()
    assert result['error'] is None,result
    assert result['changed'] and result['completed'],result
    assert app.data['delta']==19 and 'last_refresh_attempt_at' in meter.read(meter.SNAPSHOT,{})
    assert app.root.state()=='withdrawn' and app.settings_window.state()=='withdrawn'
finally: app.root.destroy()
print(json.dumps({'passed':True,'automatic_refresh':'completed','settings_saved':True}))
