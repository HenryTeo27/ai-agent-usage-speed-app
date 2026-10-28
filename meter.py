import queue
import contextlib, io, runpy, webbrowser
import sys, os, json, subprocess, threading, tempfile, urllib.request, ast, re, time, shutil
from pathlib import Path
from datetime import datetime
# Opt in before creating a Tk window so Windows does not bitmap-scale the UI.
if os.name == 'nt':
    import ctypes
    try: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError): pass
import tkinter as tk
from tkinter import ttk, messagebox

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / 'vendor'))
import pystray
from PIL import Image, ImageTk

DATA = Path(os.environ['LOCALAPPDATA']) / 'CodexMeter'
CONFIG = DATA / 'settings.json'
SNAPSHOT = DATA / 'snapshot.json'
SPEED = Path.home() / '.codex/bin/codex-speed/codex_speed.py'
VENDOR = SPEED.parent / 'vendor'
UPSTREAM = 'https://gist.githubusercontent.com/pszemraj/f8fe69ff5002c3bd0825edfd02001635/raw/codex_speed.py'
CREATE = 0x08000000 if os.name == 'nt' else 0
PYTHON = str(Path(sys.executable).with_name('python.exe')) if Path(sys.executable).name.lower() == 'pythonw.exe' else sys.executable
VERSION = '1.0.0'
DEFAULT = {'interval': 6, 'reserve': 600000000}
CACHED_SPEED = DATA / 'tools' / 'codex_speed.py'

def read(path, fallback):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): return fallback

def save(path, data):
    DATA.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)

def run(args, timeout=180, env=None):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', errors='replace', env=env,
                               creationflags=CREATE)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # npx and joblib spawn children; terminate the complete command tree.
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, creationflags=CREATE, timeout=10)
        else: process.kill()
        process.communicate(timeout=10)
        raise RuntimeError(f'Scan timed out after {timeout}s')
    if process.returncode: raise RuntimeError((stderr or stdout or 'Command failed')[-500:])
    return stdout

def limits_worker():
    p = subprocess.Popen([find_codex(), 'app-server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', creationflags=CREATE)
    try:
        for msg in [{'id':1,'method':'initialize','params':{'clientInfo':{'name':'codex-meter','version':'1.0'}}}, {'method':'initialized'}, {'id':2,'method':'account/rateLimits/read'}]:
            p.stdin.write(json.dumps(msg)+'\n'); p.stdin.flush()
        for line in p.stdout:
            data=json.loads(line)
            if data.get('id') == 2:
                if 'error' in data: raise RuntimeError(str(data['error']))
                return data['result']['rateLimits']
        raise RuntimeError('No rate limit response')
    finally: p.terminate()

def find_codex():
    override=os.environ.get('CODEX_APP_RUNTIME_CLI_PATH')
    if override and Path(override).is_file(): return override
    executable=shutil.which('codex.exe') or shutil.which('codex')
    if executable: return executable
    folder=Path(os.environ.get('LOCALAPPDATA',''))/'OpenAI/Codex/bin'
    choices=list(folder.glob('*/codex.exe'))
    if choices: return str(max(choices,key=lambda path:path.stat().st_mtime))
    raise RuntimeError('Install Codex and sign in, then reopen Codex Meter')


def worker_call(mode, args, output, timeout, env=None):
    command=[sys.executable] if getattr(sys,'frozen',False) else [PYTHON,str(ROOT/'meter.py')]
    run(command+[mode,'--worker-output',str(output)]+args, timeout=timeout, env=env)
    result=read(output,{})
    if not result.get('ok'): raise RuntimeError(result.get('error','Worker returned no result'))
    return result['value']


def get_limits():
    with tempfile.TemporaryDirectory(prefix='codex-meter-limits-') as tmp:
        return worker_call('--limits',[],Path(tmp)/'result.json',35)

def get_usage():
    npx = shutil.which('npx.cmd') or shutil.which('npx')
    if not npx: raise RuntimeError('Node.js / npx not found')
    data = json.loads(run([npx, '--yes', 'ccusage@latest', 'codex', 'monthly', '--json'], timeout=180))
    month = datetime.now().strftime('%Y-%m')
    rows = data['monthly']; total = data['totals']
    current = next((x for x in rows if x['month'] == month), {'totalTokens':0,'costUSD':0})
    return {'month':month, 'month_tokens':current['totalTokens'], 'month_cost':current['costUSD'], 'total_tokens':total['totalTokens'], 'total_cost':total['costUSD']}

def parse_speed(raw):
    lines=raw.splitlines()
    try: start=next(i for i,x in enumerate(lines) if x.strip() == 'Selected history')
    except StopIteration:
        if 'No samples' in raw or 'no samples' in raw: return []
        raise ValueError('Selected history table not found')
    result=[]
    for line in lines[start+2:]:
        line=line.strip()
        if not line: break
        parts=line.split()
        if len(parts) < 6: raise ValueError('Unexpected speed table row')
        result.append({'model':parts[0], 'normal':parts[1], 'fast':parts[2], 'ratio':parts[3], 'normal_n':parts[4], 'fast_n':parts[5]})
    return result

def get_speed():
    env=os.environ.copy(); env['PYTHONPATH']=os.pathsep.join([str(ROOT/'vendor'),str(ROOT/'build_vendor'),str(VENDOR)]); env['PYTHONIOENCODING']='utf-8'; env['COLUMNS']='140'; env['NO_COLOR']='1'
    note=''
    with tempfile.TemporaryDirectory(prefix='codex-meter-') as tmp:
        folder=Path(tmp); candidate=folder/'codex_speed.py'
        try:
            with urllib.request.urlopen(UPSTREAM, timeout=12) as response: content=response.read(2_000_000)
            source=content.decode('utf-8'); ast.parse(source)
            if 'Selected history' not in source or 'samples.csv.gz' not in source: raise ValueError('Unexpected upstream script')
            # Upstream currently assumes Linux /etc/localtime. Apply the same
            # Windows timezone fallback as the user's installed script.
            tree=ast.parse(source)
            zone_fn=next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'system_zone'), None)
            if zone_fn:
                lines=source.splitlines(keepends=True)
                replacement='def system_zone():\n    return datetime.now().astimezone().tzinfo or timezone.utc\n'
                lines[zone_fn.lineno-1:zone_fn.end_lineno]=[replacement]
                source=''.join(lines)
            candidate.write_text(source, encoding='utf-8')
        except Exception:
            candidate=CACHED_SPEED if CACHED_SPEED.exists() else SPEED
            if not candidate.exists(): raise RuntimeError('First speed scan needs internet to download codex-speed')
            note='Speed update unavailable; using last available copy'
        def scan(script):
            output={}
            for days in (14,1):
                raw=worker_call('--speed-worker',[str(script),'--days',str(days),'--granularity','summary','--min-output','100','--workers','1','--out',str(folder/'out'),'--cache-dir',str(folder/'cache')],folder/'result.json',120,env)
                output[str(days)]=parse_speed(raw)
            return output
        try: output=scan(candidate)
        except Exception:
            fallback=CACHED_SPEED if CACHED_SPEED.exists() else SPEED
            if candidate == fallback or not fallback.exists(): raise
            output=scan(fallback); note='Speed update incompatible; using last available copy'
        else:
            if candidate != CACHED_SPEED and candidate != SPEED:
                CACHED_SPEED.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(candidate,CACHED_SPEED)
        return output,note

def ratio_color(value):
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", value)
    if not match: return '#8a8c8f'
    number = float(match.group())
    return '#9b3038' if number < 1 else '#947019' if number < 1.5 else '#185c40'


def remaining_percent(used):
    return max(0, min(100, 100 - float(used)))


class Tooltip:
    """A small, event-driven tooltip; no polling or permanent window."""
    def __init__(self, widget, text):
        self.widget, self.text, self.popup, self.timer = widget, text, None, None
        widget.bind('<Enter>', self.enter, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')
        widget.bind('<Destroy>', self.hide, add='+')
    def enter(self, event):
        self.timer = self.widget.after(350, self.show)
    def show(self):
        self.timer = None
        if not self.widget.winfo_exists(): return
        self.popup = tk.Toplevel(self.widget)
        self.popup.overrideredirect(True)
        self.popup.attributes('-topmost', True)
        tk.Label(self.popup, text=self.text, bg='#202224', fg='#ffffff',
                 font=('Segoe UI', 9), padx=11, pady=8, justify='left').pack()
        self.popup.update_idletasks()
        x = min(self.widget.winfo_pointerx()+12, self.popup.winfo_screenwidth()-self.popup.winfo_reqwidth()-12)
        y = min(self.widget.winfo_pointery()+18, self.popup.winfo_screenheight()-self.popup.winfo_reqheight()-12)
        self.popup.geometry(f'+{max(0,x)}+{max(0,y)}')
    def hide(self, event=None):
        if self.timer:
            self.widget.after_cancel(self.timer); self.timer = None
        if self.popup:
            self.popup.destroy(); self.popup = None


class App:
    def __init__(self):
        self.settings={**DEFAULT, **read(CONFIG,{})}; self.data=read(SNAPSHOT,{}); self.busy=False; self.closed=False; self.job=None; self.results=queue.Queue()
        self.root=tk.Tk(); self.root.title('Codex Meter'); self.root.geometry('480x650'); self.root.minsize(440,610); self.root.configure(bg='#ffffff')
        self.root.iconbitmap(str(ROOT/'assets/codex-transparent.ico'))
        self.root.after_idle(self.set_native_icons)
        self.root.protocol('WM_DELETE_WINDOW',self.hide)
        self.build(); self.draw(); self.setup_tray(); self.schedule()
        # A recent snapshot can be shown immediately without another full scan.
        age = time.time() - self.data.get('last_refresh_at', SNAPSHOT.stat().st_mtime if SNAPSHOT.exists() else 0)
        if not self.data or (self.settings['interval'] and age >= self.settings['interval']*3600): self.refresh()
    def set_native_icons(self):
        """Load icons at the screen's actual pixel sizes, avoiding 16px upscaling."""
        if os.name != 'nt': return
        import ctypes
        from ctypes import wintypes
        user = ctypes.windll.user32
        user.GetParent.argtypes = [wintypes.HWND]
        user.GetParent.restype = wintypes.HWND
        user.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user.LoadImageW.restype = wintypes.HANDLE
        user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.SendMessageW.restype = wintypes.LPARAM
        hwnd = user.GetParent(self.root.winfo_id())
        user.GetDpiForWindow.argtypes = [wintypes.HWND]
        dpi = user.GetDpiForWindow(hwnd) or 96
        self.native_icons = []
        for kind, metric in ((0, 49), (1, 11)):
            size = user.GetSystemMetricsForDpi(metric, dpi)
            icon = user.LoadImageW(None, str(ROOT/'assets/codex-transparent.ico'), 1, size, size, 0x10)
            if icon:
                self.native_icons.append(icon)
                user.SendMessageW(hwnd, 0x80, kind, icon)

    def build(self):
        bg='#ffffff'; self.bg=bg
        head=tk.Frame(self.root,bg=bg); head.pack(fill='x',padx=20,pady=(8,8))
        self.logo=ImageTk.PhotoImage(Image.open(ROOT/'assets/codex-transparent.png').resize((28,28),Image.Resampling.LANCZOS))
        tk.Label(head,image=self.logo,bg=bg).pack(side='left')
        tk.Label(head,text='Codex',font=('Segoe UI',11),fg='#222426',bg=bg).pack(side='left',padx=9)
        for text,cmd,tip in [('⚙',self.settings_dialog,'Settings'),('↻',self.refresh,'Refresh')]:
            button=tk.Button(head,text=text,command=cmd,font=('Segoe UI Symbol',13),relief='flat',bd=0,bg=bg,fg='#62666b',activebackground='#f2f3f4',cursor='hand2',padx=5)
            button.pack(side='right',padx=2); Tooltip(button,tip)
        holder=tk.Frame(self.root,bg=bg); holder.pack(fill='both',expand=True,padx=20)
        self.canvas=tk.Canvas(holder,bg=bg,highlightthickness=0,bd=0)
        self.canvas.pack(side='left',fill='both',expand=True)
        self.body=tk.Frame(self.canvas,bg=bg); self.body_window=self.canvas.create_window((0,0),window=self.body,anchor='nw')
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.body_window,width=e.width))
        def adjust(e):
            self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        self.body.bind('<Configure>',adjust)
        self.root.bind_all('<MouseWheel>',lambda e:self.canvas.yview_scroll(int(-e.delta/120),'units'))
        self.status=tk.Label(self.root,text='',font=('Segoe UI',8),fg='#8a8c8f',bg=bg,anchor='w'); self.status.pack(fill='x',padx=20,pady=(5,10))
    def label(self,parent,text,size=10,color='#777b80',font='Segoe UI',bold=False,**kw):
        return tk.Label(parent,text=text,bg=self.bg,fg=color,font=(font,size,'bold' if bold else 'normal'),**kw)
    def draw(self):
        for x in self.body.winfo_children(): x.destroy()
        limits=self.data.get('limits',{})
        windows=[x for x in (limits.get('primary'),limits.get('secondary')) if x and x.get('usedPercent') is not None]
        for window in windows:
            line=tk.Frame(self.body,bg=self.bg); line.pack(fill='x',pady=(0,10))
            self.label(line,f"{remaining_percent(window['usedPercent']):g}% remaining",15,'#222426',anchor='w').pack(side='left')
        if not windows: self.label(self.body,'Usage unavailable',12,anchor='w').pack(fill='x',pady=(0,10))
        u=self.data.get('usage',{}); cols=tk.Frame(self.body,bg=self.bg); cols.pack(fill='x')
        for index,(title,key,cost) in enumerate([('This month','month_tokens','month_cost'),('All time','total_tokens','total_cost')]):
            cols.columnconfigure(index,weight=1,uniform='totals')
            f=tk.Frame(cols,bg=self.bg); f.grid(row=0,column=index,sticky='ew')
            self.label(f,title,9,anchor='w').pack(fill='x')
            n=u.get(key); n=(n+self.settings['reserve']) if n is not None and key=='total_tokens' else n
            self.label(f,f'{n:,}' if n is not None else '—',12,'#292d30',font='Consolas',anchor='w').pack(fill='x',pady=(3,1))
            c=u.get(cost); price=self.label(f,f'${c:,.2f}' if c is not None else '—',10,'#73777b',anchor='w'); price.pack(fill='x')
            Tooltip(price,'Estimated API-equivalent cost (USD)')
        d=self.data.get('delta')
        delta=self.label(self.body,f'{d:+,} tokens' if d is not None else '—',9,'#185c40',anchor='w')
        delta.pack(fill='x',pady=(7,10)); Tooltip(delta,'Since Last Refresh' if d is not None else 'Available after the next successful refresh')
        tk.Frame(self.body,bg='#e9eaec',height=1).pack(fill='x')
        self.label(self.body,'Speed',11,'#292d30',anchor='w').pack(fill='x',pady=(9,5))
        speed=self.data.get('speed',{})
        for days in ('1','14'):
            self.label(self.body,'14 days' if days=='14' else '1 day',9,'#777b80',anchor='w').pack(fill='x',pady=(2,3))
            grid=tk.Frame(self.body,bg=self.bg); grid.pack(fill='x',pady=(0,6))
            for i,v in enumerate(['Model','Normal','Fast','Ratio']):
                self.label(grid,v,8,'#989b9e',anchor='w' if i==0 else 'e').grid(row=0,column=i,sticky='ew',pady=(0,2))
                grid.columnconfigure(i,weight=4 if i==0 else 1)
            rows=speed.get(days,[])
            for idx,row in enumerate(rows,1):
                values=[row['model'],row['normal'].strip('()~*†'),row['fast'].strip('()~*†'),row['ratio'].strip('()~*†')]
                for col,val in enumerate(values):
                    label=self.label(grid,val,9,ratio_color(row['ratio']) if col==3 else '#353a3e',font='Consolas',anchor='w' if col==0 else 'e')
                    label.grid(row=idx,column=col,sticky='ew',pady=1)
                    if col in (1,2):
                        mode='normal' if col==1 else 'fast'; count=row[mode+'_n']
                        Tooltip(label,f"{val} effective tokens/s\nApproximately {count} timed responses" if val not in ('·','—') else 'No timed responses')
                    elif col==3:
                        Tooltip(label,'Fast ÷ Normal'+ ('\nLimited sample size' if '(' in row['ratio'] else ''))
            if not rows: self.label(grid,'No available samples',9,anchor='w').grid(row=1,column=0,columnspan=4,sticky='w')
        footer=tk.Frame(self.body,bg=self.bg); footer.pack(fill='x',pady=(14,18))
        tk.Frame(footer,bg='#e9eaec',height=1).pack(fill='x',pady=(0,12))
        self.label(footer,'Sources & components',9,anchor='w').pack(fill='x')
        self.label(footer,'Checks latest tools on refresh; falls back when unavailable.',8,anchor='w',wraplength=390,justify='left').pack(fill='x',pady=(4,8))
        for title,url in [
            ('codex-speed · speed calculations','https://gist.github.com/pszemraj/f8fe69ff5002c3bd0825edfd02001635'),
            ('ccusage / Codex · tokens & cost','https://github.com/ccusage/ccusage'),
            ('OpenAI Codex · account limits & local logs','https://github.com/openai/codex'),
            ('Python / Tk · desktop interface','https://www.python.org/'),
            ('pystray · tray icon','https://github.com/moses-palmer/pystray'),
            ('Pillow · icons','https://python-pillow.org/'),
            ('Rich / joblib · speed tool runtime','https://github.com/Textualize/rich'),
            ('Source code · Codex Meter '+VERSION,'https://github.com/HenryTeo27/ai-agent-usage-speed-app')]:
            link=self.label(footer,title,8,'#73777b',anchor='w',cursor='hand2')
            link.pack(fill='x',pady=2); link.bind('<Button-1>',lambda event,address=url:webbrowser.open(address))
        if not self.busy: self.status.config(text=self.data.get('status','Ready'))
    def settings_dialog(self):
        win=tk.Toplevel(self.root); win.title('Settings'); win.configure(bg=self.bg); win.resizable(False,False); win.transient(self.root)
        win.geometry(f'+{max(0, self.root.winfo_rootx()+20)}+{max(0, self.root.winfo_rooty()+50)}')
        box=tk.Frame(win,bg=self.bg); box.pack(padx=24,pady=22)
        self.label(box,'Refresh interval',10,anchor='w').grid(row=0,column=0,sticky='w',pady=6)
        v=tk.StringVar(value='Manual' if not self.settings['interval'] else f"{self.settings['interval']} hours")
        ttk.Combobox(box,textvariable=v,values=['Manual','2 hours','4 hours','6 hours','8 hours','12 hours'],state='readonly',width=18).grid(row=0,column=1,padx=(20,0))
        self.label(box,'Reserve adjustment (tokens)',10,anchor='w').grid(row=1,column=0,sticky='w',pady=6)
        r=tk.StringVar(value=str(self.settings['reserve'])); ttk.Entry(box,textvariable=r,width=21).grid(row=1,column=1,padx=(20,0))
        self.label(box,'Added to all-time tokens. Existing reserve records may overlap.',9,anchor='w').grid(row=2,column=0,columnspan=2,sticky='w',pady=8)
        def apply():
            try:
                num=int(r.get().replace(',',''))
                if num<0: raise ValueError()
            except ValueError: messagebox.showerror('Settings','Enter a non-negative whole number.',parent=win); return
            self.settings={'interval':0 if v.get()=='Manual' else int(v.get().split()[0]),'reserve':num}; save(CONFIG,self.settings); self.schedule(); self.draw(); win.destroy()
        ttk.Button(box,text='Save',command=apply).grid(row=3,column=1,sticky='e',pady=(10,0))
    def schedule(self):
        if self.job: self.root.after_cancel(self.job); self.job=None
        if self.settings['interval']: self.job=self.root.after(self.settings['interval']*3600000,self.scheduled)
    def scheduled(self): self.job=None; self.refresh()
    def refresh(self):
        if self.busy: return
        self.busy=True
        self.status.config(text='Reading usage…')
        threading.Thread(target=self.collect,daemon=True).start()
        self.root.after(100,self.check_results)
    def collect(self):
        fresh={}; errors=[]
        try:
            for name,fn in [('usage',get_usage),('limits',get_limits),('speed',get_speed)]:
                self.results.put(('stage',{'usage':'Reading usage…','limits':'Reading limits…','speed':'Measuring speed…'}[name]))
                try:
                    result=fn()
                    if name=='speed': fresh[name],note=result; errors.extend([note] if note else [])
                    else: fresh[name]=result
                except Exception as e: errors.append(name+': '+str(e).replace('\n',' ')[:120])
        finally:
            # Only the UI thread touches Tk, even when a source fails.
            self.results.put(('done',(fresh,errors)))
    def check_results(self):
        if self.closed: return
        while True:
            try: kind,value=self.results.get_nowait()
            except queue.Empty: break
            if kind=='stage': self.status.config(text=value)
            else:
                self.finish(*value)
                return
        self.root.after(100,self.check_results)
    def finish(self,fresh,errors):
        if self.closed: return
        try:
            old=self.data.get('usage'); new=fresh.get('usage')
            if new: self.data['delta']=new['total_tokens']-old['total_tokens'] if old else None
            self.data.update(fresh)
            self.data['status']=(' · '.join(errors) if errors else 'Updated '+datetime.now().strftime('%H:%M'))
            if fresh: self.data['last_refresh_at']=time.time()
            save(SNAPSHOT,self.data)
        except Exception as e:
            self.data['status']='Refresh failed: '+str(e)[:120]
        finally:
            self.busy=False
            self.status.config(text=self.data.get('status','Refresh finished'))
            self.schedule()
        self.draw()
    def setup_tray(self):
        im=Image.open(ROOT/'assets/codex-transparent.png').convert('RGBA')
        self.tray=pystray.Icon('Codex Meter',im,'Codex Meter',pystray.Menu(pystray.MenuItem('Open',lambda:self.root.after(0,self.show),default=True),pystray.MenuItem('Refresh',lambda:self.root.after(0,self.refresh)),pystray.MenuItem('Quit',lambda:self.root.after(0,self.quit))))
        self.tray.run_detached()
    def hide(self): self.root.withdraw()
    def show(self): self.root.deiconify(); self.root.lift(); self.root.focus_force()
    def quit(self): self.closed=True; self.tray.stop(); self.root.destroy()
    def run(self): self.root.mainloop()

def worker_main():
    args=sys.argv[1:]
    output_index=args.index('--worker-output')
    output=Path(args[output_index+1]); del args[output_index:output_index+2]
    buffer=io.StringIO()
    try:
        if args[0]=='--limits': value=limits_worker()
        else:
            script=args[1]; sys.argv=[script]+args[2:]
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                try: runpy.run_path(script,run_name='__main__')
                except SystemExit as exc:
                    if exc.code not in (0,None): raise RuntimeError(buffer.getvalue()[-500:])
            value=buffer.getvalue()
        result={'ok':True,'value':value}
    except Exception as exc: result={'ok':False,'error':str(exc)}
    output.write_text(json.dumps(result),encoding='utf-8')


def start_single_instance():
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.windll.kernel32; user=ctypes.windll.user32
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    user.FindWindowW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR]
    user.FindWindowW.restype=wintypes.HWND
    user.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
    user.SetForegroundWindow.argtypes=[wintypes.HWND]
    handle=kernel.CreateMutexW(None,False,'Local\\CodexMeterSingleInstance')
    existed=kernel.GetLastError()==183
    if not handle: raise ctypes.WinError()
    try:
        if existed:
            # A rapid second launch may arrive before the first window exists.
            for attempt in range(40):
                hwnd=user.FindWindowW(None,'Codex Meter')
                if hwnd:
                    user.ShowWindow(hwnd,9)
                    user.SetForegroundWindow(hwnd)
                    break
                time.sleep(0.1)
        else:
            App().run()
    finally:
        kernel.CloseHandle(handle)


if __name__=='__main__':
    if '--worker-output' in sys.argv: worker_main()
    else: start_single_instance()
