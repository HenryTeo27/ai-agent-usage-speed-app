"""Open the real UI with synthetic data for screenshots; no scans or saved data."""
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import meter

with patch.object(meter.App, 'refresh'), patch.object(meter.App, 'setup_tray'):
    app = meter.App()
app.settings = {'interval': 0, 'reserve': 0}
if app.job:
    app.root.after_cancel(app.job)
    app.job = None

def rows(values):
    return [dict(model=model, normal=normal, fast=fast, ratio=ratio,
                 normal_n='120', fast_n='160')
            for model, normal, fast, ratio in values]
app.data = {
    'limits': {'primary': {'usedPercent': 18, 'windowDurationMins': 300},
               'secondary': {'usedPercent': 32, 'windowDurationMins': 10080},
               'accounts': [
                   {'kind': 'chatgpt', 'email': 'alex@example.com', 'label': '.codex', 'source': 'chat'},
                   {'kind': 'apiKey', 'label': '.codex-api', 'source': 'api'}]},
    'usage': {'month_tokens': 128453620, 'month_cost': 142.86,
              'total_tokens': 2041750980, 'total_cost': 2184.32,
              'sources': [{'source': 'chat', 'month_tokens': 120000000},
                          {'source': 'api', 'month_tokens': 8453620}]},
    'delta': 1842650,
    'speed': {
        '1': rows([('gpt-6.1-sol', '34.8', '56.7', '1.63×'),
                   ('gpt-6-astra', '25.1', '31.4', '1.25×'),
                   ('gpt-6-luna', '72.0', '67.0', '0.93×')]),
        '14': rows([('gpt-6.1-sol', '33.6', '52.1', '1.55×'),
                    ('gpt-6-astra', '24.9', '32.5', '1.31×'),
                    ('gpt-6-luna', '71.4', '68.5', '0.96×')]),
        'sources': [{'source': 'chat', '1': rows([('gpt-6.1-sol', '34.8', '56.7', '1.63×')])},
                    {'source': 'api', '1': rows([('gpt-6-astra', '25.1', '31.4', '1.25×')])}]},
    'status': 'Updated 10:42',
}
app.root.title('Codex Meter Preview')
app.root.geometry('+480+100')
app.root.protocol('WM_DELETE_WINDOW', app.root.destroy)
app.draw()
app.root.mainloop()
