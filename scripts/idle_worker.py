"""Hold a withdrawn app with fake data for a non-interactive idle measurement."""
import json
import os
from pathlib import Path
import sys
import time

meter=sys.modules['_codex_meter_runtime']
meter.App.show=lambda app:None
meter.App.setup_tray=lambda app:None  # Do not add an icon to the user's tray.
meter.App.publish_ready=lambda app:None
meter.app_updater.installed_root=lambda *args:Path(args[3])
meter.save(meter.CONFIG,{'interval':2,'reserve':0,'appearance':'system'})
row={'model':'gpt-example','normal':'20.0','fast':'30.0','ratio':'1.50×','normal_n':'8','fast_n':'9'}
meter.save(meter.SNAPSHOT,{'usage':{'month_tokens':123,'total_tokens':456,'month_cost':1,'total_cost':2},
                           'limits':{'primary':{'usedPercent':20}},
                           'speed':{'1':[dict(row,model='one-'+str(i)) for i in range(3)],
                                    '14':[dict(row,model='two-'+str(i)) for i in range(4)]},
                           'last_refresh_at':time.time(),
                           'app_update_check':{'checked_at':time.time(),'retry':False}})
app=meter.App();assert app.root.state()=='withdrawn'
app.root.after(18000,app.root.quit)
Path(os.environ['CODEX_METER_IDLE_READY']).write_text('ready')
try: app.run()
finally: app.root.destroy()
print(json.dumps({'passed':True}))
