"""Exercise quit/reopen with withdrawn windows and an isolated data directory."""
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

if '_codex_meter_runtime' in sys.modules:
    meter=sys.modules['_codex_meter_runtime']
else:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import meter

meter.load_gui()
meter.App.show=lambda app:None
meter.App.setup_tray=lambda app:setattr(app,'tray',SimpleNamespace(stop=lambda:None))
meter.App.refresh=lambda app:None
meter.App.schedule=lambda app:None
meter.App.publish_ready=lambda app:None
meter.tk.Toplevel.deiconify=lambda window:None
meter.tk.Toplevel.grab_set=lambda window:None
app=meter.App()
assert app.root.state()=='withdrawn'
if sys.argv[1]=='write':
    app.data={'usage':{'month_tokens':100,'total_tokens':1000,'month_cost':1,'total_cost':2},
              'speed':{'1':[],'14':[]},'limits':{'primary':{'usedPercent':20}},
              'delta':20,'status':'Updated 10:00','last_refresh_at':time.time()}
    app.settings_dialog()
    app.settings_vars['appearance'].set('Dark')
    app.settings_vars['interval'].set('30 minutes')
    app.settings_vars['reserve'].set('321')
    # Deliberately quit without pressing Save or waiting for the edit debounce.
    app.busy=True
    app.quit()
else:
    assert app.settings=={'appearance':'dark','interval':0.5,'reserve':321},app.settings
    assert app.data['usage']['total_tokens']==1000
    assert app.data['speed']=={'1':[],'14':[]}
    assert app.data['delta']==20
    assert app.dark
    app.sync_theme(False);assert app.dark  # Manual Dark overrides Windows Light.
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    labels=[widget.cget('text') for widget in descendants(app.body) if isinstance(widget,meter.tk.Label)]
    assert '1,321' in labels,labels
    app.settings_dialog()
    labels=[widget.cget('text') for widget in descendants(app.settings_window) if isinstance(widget,meter.tk.Label)]
    assert 'Sources & components' not in labels
    app.settings_vars['appearance'].set('Light')
    app.sync_theme(True);assert not app.dark
    app.settings_vars['appearance'].set('System')
    app.sync_theme(True);assert app.dark
    app.sync_theme(False);assert not app.dark
    assert app.root.state()=='withdrawn' and app.settings_window.state()=='withdrawn'
    app.quit()
print(json.dumps({'stage':sys.argv[1],'passed':True,'storage':str(meter.DATA)}))
