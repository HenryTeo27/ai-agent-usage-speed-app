"""Preview the real UI with synthetic multi-account data."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import meter

def rows(values):
    return [dict(model=model, normal=normal, fast=fast, ratio=ratio,
                 normal_n='120', fast_n='160')
            for model, normal, fast, ratio in values]
def sample_data():
    normal=rows([('gpt-6.1-sol','34.8','56.7','1.63×'),
                 ('gpt-6-astra','25.1','31.4','1.25×')])
    api=rows([('gpt-6.1-terra','48.2','·','·')])
    return {
        'limits': {'primary': {'usedPercent':18}, 'secondary': {'usedPercent':32}},
        'usage': meter.combined_usage([
            {'source':'chat','short':'GPT','month_tokens':120000000,'total_tokens':2000000000,'month_cost':130,'total_cost':2100},
            {'source':'api','short':'API','month_tokens':8453620,'total_tokens':41750980,'month_cost':12.86,'total_cost':84.32}], '2026-10'),
        'delta_sources':[{'source':'chat','short':'GPT','delta':1800000},
                         {'source':'api','short':'API','delta':42650}],
        'speed': {'sources':[{'source':'chat','short':'GPT','1':normal,'14':normal},
                             {'source':'api','short':'API','1':api,'14':api}]},
        'status':'Updated 10:42'
    }


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(meter,'CONFIG',Path(tmp)/'settings.json'), patch.object(meter,'SNAPSHOT',Path(tmp)/'snapshot.json'), patch.object(meter.App,'setup_tray'), patch.object(meter.App,'schedule'), patch.object(meter.App,'schedule_app_update_check'):
            meter.save(meter.CONFIG,{'interval':0,'reserve':0,'appearance':'system'})
            meter.save(meter.SNAPSHOT,sample_data())
            app=meter.App()
            app.root.title('Codex Meter Preview')
            app.root.protocol('WM_DELETE_WINDOW',app.root.destroy)
            app.root.mainloop()
