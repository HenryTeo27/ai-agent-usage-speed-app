import queue
import weakref
import contextlib, io, webbrowser
import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta, timezone
from types import SimpleNamespace
import sys, os, json, subprocess, threading, tempfile, re, time, shutil
from pathlib import Path
from datetime import datetime
ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT / 'build_vendor'))

DATA = Path(os.environ['LOCALAPPDATA']) / 'CodexMeter'
CONFIG = DATA / 'settings.json'
SNAPSHOT = DATA / 'snapshot.json'
SPEED = Path.home() / '.codex/bin/codex-speed/codex_speed.py'
VENDOR = SPEED.parent / 'vendor'
UPSTREAM = 'https://gist.githubusercontent.com/pszemraj/f8fe69ff5002c3bd0825edfd02001635/raw/codex_speed.py'
CREATE = 0x08000000 if os.name == 'nt' else 0
PYTHON = str(Path(sys.executable).with_name('python.exe')) if Path(sys.executable).name.lower() == 'pythonw.exe' else sys.executable
VERSION = '1.0.6'
DEFAULT = {'interval': 6, 'reserve': 600000000}
CACHED_SPEED = DATA / 'tools' / 'codex_speed.py'

ACTIVE_PROCESSES = set()
PROCESS_LOCK = threading.Lock()
STOP_EVENT = threading.Event()


def load_gui():
    """Workers and second-instance launchers do not load the desktop libraries."""
    global tk, ttk, messagebox, pystray, Image, ImageTk
    if 'tk' in globals(): return
    if os.name == 'nt':
        import ctypes
        try: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError): pass
    import tkinter as tk
    from tkinter import ttk, messagebox
    import pystray
    from PIL import Image, ImageTk


def load_icon(size):
    # Decode only the small ICO frame, not the full-resolution PNG.
    with Image.open(ROOT/'assets/codex-transparent.ico') as icon:
        return icon.ico.getimage((size,size)).convert('RGBA')


def terminate_process(process):
    if process.poll() is not None: return
    if os.name == 'nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,
                       creationflags=CREATE,timeout=10)
    else: process.kill()


def cancel_scans():
    STOP_EVENT.set()
    with PROCESS_LOCK: processes=list(ACTIVE_PROCESSES)
    for process in processes:
        try: terminate_process(process)
        except (OSError,subprocess.TimeoutExpired): pass


def read(path, fallback):
    try: return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError): return fallback

def save(path,data):
    """Replace one durable snapshot; interrupted writes never truncate the old one."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    content=json.dumps(data,ensure_ascii=False,allow_nan=False)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                                         prefix='.'+path.stem+'-',suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name)
            stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def load_snapshot():
    data=read(SNAPSHOT,{})
    return data if isinstance(data,dict) else {}


def apply_usage_result(data,value,previous,observed_at):
    """One adjacent pair only; the reserve adjustment never enters this calculation."""
    before=previous['total_tokens'] if previous is not None else None
    after=value['total_tokens']
    previous_at=data.get('updated_at',{}).get('usage')
    data['usage']=dict(value)
    data['delta']=after-before if before is not None else None
    data['delta_comparison']={'previous_tokens':before,'current_tokens':after,
                              'previous_at':previous_at,'current_at':observed_at}
    data.setdefault('updated_at',{})['usage']=observed_at


def delta_tooltip(data):
    pair=data.get('delta_comparison',{})
    before=pair.get('previous_tokens');after=pair.get('current_tokens')
    if before is None or after is None: return 'Since Last Refresh'
    return f'Since Last Refresh\nPrevious total: {before:,}\nCurrent total: {after:,}\nDifference: {after-before:+,} tokens'


def run(args, timeout=180, env=None):
    with PROCESS_LOCK:
        if STOP_EVENT.is_set(): raise RuntimeError('Refresh cancelled')
        process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                 text=True,encoding='utf-8',errors='replace',env=env,
                                 creationflags=CREATE)
        ACTIVE_PROCESSES.add(process)
    try:
        try: stdout,stderr=process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate_process(process)
            process.communicate(timeout=10)
            raise RuntimeError(f'Scan timed out after {timeout}s')
        if process.returncode: raise RuntimeError((stderr or stdout or 'Command failed')[-500:])
        return stdout
    finally:
        with PROCESS_LOCK: ACTIVE_PROCESSES.discard(process)

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
    with tempfile.TemporaryDirectory(prefix='codex-meter-speed-') as tmp:
        value=worker_call('--speed-all',[],Path(tmp)/'result.json',145)
        return value[0],value[1]


def scan_speed():
    import urllib.request, ast
    note=''
    with tempfile.TemporaryDirectory(prefix='codex-meter-') as tmp:
        folder=Path(tmp); candidate=folder/'codex_speed.py'
        try:
            with urllib.request.urlopen(UPSTREAM, timeout=12) as response: content=response.read(2_000_000)
            source=content.decode('utf-8')
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
            return speed_batch(script)
        try: output=scan(candidate)
        except Exception:
            fallback=CACHED_SPEED if CACHED_SPEED.exists() else SPEED
            if candidate == fallback or not fallback.exists(): raise
            output=scan(fallback); note='Speed update incompatible; using last available copy'
        else:
            if candidate != CACHED_SPEED and candidate != SPEED:
                CACHED_SPEED.parent.mkdir(parents=True,exist_ok=True)
                if not CACHED_SPEED.exists() or CACHED_SPEED.read_bytes()!=candidate.read_bytes():
                    shutil.copyfile(candidate,CACHED_SPEED)
        return output,note

def speed_batch(script):
    spec=importlib.util.spec_from_file_location('_codex_meter_speed',script)
    engine=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=engine
    spec.loader.exec_module(engine)
    # Only JSON decoding changes; parsing and statistics remain upstream code.
    import orjson
    engine.json=SimpleNamespace(loads=orjson.loads,dumps=json.dumps,JSONDecodeError=orjson.JSONDecodeError)
    now=datetime.now(timezone.utc)
    home=Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex')
    original_find=engine.find_rollouts
    def recent_rollouts(home,*args,**kwargs):
        result=[]
        for path in original_find(home):
            try:
                if path.stat().st_mtime >= (now-timedelta(days=14)).timestamp(): result.append(path)
            except OSError: result.append(path)
        return result
    engine.find_rollouts=recent_rollouts
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        samples,totals=engine.load_samples(home,None,1)
    if totals.get('unreadable_files'): raise RuntimeError(f"Cannot read {totals['unreadable_files']} Codex log files")
    tz=datetime.now().astimezone().tzinfo or timezone.utc
    output={}
    for days in (1,14):
        cutoff=now-timedelta(days=days)
        selected=[sample for sample in samples if datetime.fromisoformat(sample.completed_at)>=cutoff and sample.output_tokens>=100]
        if not selected:
            output[str(days)]=[]
            continue
        buffer=io.StringIO()
        from rich.console import Console
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            engine.print_report(engine.build_report(selected,totals,100,tz),selected,tz,granularity='summary',console=Console(file=buffer,width=140,highlight=False))
        output[str(days)]=parse_speed(buffer.getvalue())
    return output


def ratio_color(value):
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", value)
    if not match: return '#8a8c8f'
    number = float(match.group())
    return '#9b3038' if number < 1 else '#947019' if number < 1.5 else '#185c40'


def remaining_percent(used):
    return max(0, min(100, 100 - float(used)))


class Tooltip:
    instances=weakref.WeakSet()
    """A small, event-driven tooltip; no polling or permanent window."""
    def __init__(self, widget, text):
        self.widget, self.text, self.popup, self.timer = widget, text, None, None
        self.instances.add(self)
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
        self.popup.title('Codex Meter tooltip')
        self.popup.transient(self.widget.winfo_toplevel())
        self.popup.overrideredirect(True)
        self.popup.attributes('-topmost', True)
        tk.Label(self.popup, text=self.text() if callable(self.text) else self.text, bg='#202224', fg='#ffffff',
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
        load_gui()
        self.dirty=False
        self.settings={**DEFAULT, **read(CONFIG,{})}; self.data=load_snapshot(); self.busy=False; self.closed=False; self.job=None; self.results=queue.Queue()
        if self.data.get('status','').startswith('Updated '):
            self.data['status']=re.sub(r'\s*·\s*\d+(?:\.\d+)?s(?=\s*·|$)','',self.data['status'])
        self.root=tk.Tk(); self.root.withdraw(); self.root.title('Codex Meter'); self.root.geometry('480x650'); self.root.minsize(440,610); self.root.configure(bg='#ffffff')
        self.root.iconbitmap(str(ROOT/'assets/codex-transparent.ico'))
        self.root.protocol('WM_DELETE_WINDOW',self.hide)
        self.root.bind('<Map>',self.on_map)
        self.root.bind('<Configure>',self.update_window_shape)
        self.build(); self.draw()
        self.root.update_idletasks();self.configure_window()
        self.setup_tray();self.schedule()
        self.publish_ready()
        if '--start-hidden' not in sys.argv: self.show()
        # A recent snapshot can be shown immediately without another full scan.
        age = time.time() - self.data.get('last_refresh_at', SNAPSHOT.stat().st_mtime if SNAPSHOT.exists() else 0)
        if not self.data or (self.settings['interval'] and age >= self.settings['interval']*3600): self.root.after_idle(self.refresh)
    def configure_window(self):
        """Use native styles, without installing Python callbacks in the window procedure."""
        if os.name!='nt': return
        import ctypes
        from ctypes import wintypes
        user=ctypes.windll.user32
        self.set_native_icons()
        hwnd=user.GetParent(self.root.winfo_id())
        if not hwnd: return
        if getattr(self,'window_handle',None)!=hwnd and hasattr(self,'_native_rounding'):
            del self._native_rounding
        self.window_handle=hwnd
        get_style=user.GetWindowLongPtrW
        get_style.argtypes=[wintypes.HWND,ctypes.c_int];get_style.restype=ctypes.c_ssize_t
        set_style=user.SetWindowLongPtrW
        set_style.argtypes=[wintypes.HWND,ctypes.c_int,ctypes.c_ssize_t];set_style.restype=ctypes.c_ssize_t
        style=get_style(hwnd,-16)
        # Keep native minimize/maximize behavior; no caption or resize-frame inset.
        if style & 0x00c40000:
            set_style(hwnd,-16,style & ~0x00c40000)
            user.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
            user.SetWindowPos(hwnd,None,0,0,0,0,0x27)
        self.update_window_shape()

    def update_window_shape(self,event=None):
        if os.name!='nt' or not hasattr(self,'window_handle'): return
        if event is not None and event.widget is not self.root: return
        import ctypes
        from ctypes import wintypes
        user=ctypes.windll.user32
        if not hasattr(self,'_native_rounding'):
            corner=ctypes.c_int(2)  # DWMWCP_ROUND; retain compositor antialiasing/shadow.
            dwm=ctypes.windll.dwmapi
            dwm.DwmSetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
            self._native_rounding=dwm.DwmSetWindowAttribute(self.window_handle,33,ctypes.byref(corner),ctypes.sizeof(corner))==0
            class Margins(ctypes.Structure):
                _fields_=[('left',ctypes.c_int),('right',ctypes.c_int),('top',ctypes.c_int),('bottom',ctypes.c_int)]
            margin=Margins(1,1,1,1)
            dwm.DwmExtendFrameIntoClientArea.argtypes=[wintypes.HWND,ctypes.POINTER(Margins)]
            dwm.DwmExtendFrameIntoClientArea(self.window_handle,ctypes.byref(margin))
        if self._native_rounding: return
        # Windows 10 fallback; update only when the window changes size.
        user.SetWindowRgn.argtypes=[wintypes.HWND,wintypes.HRGN,wintypes.BOOL]
        if self.root.state()=='zoomed': user.SetWindowRgn(self.window_handle,None,True);return
        gdi=ctypes.windll.gdi32
        gdi.CreateRoundRectRgn.argtypes=[ctypes.c_int]*6;gdi.CreateRoundRectRgn.restype=wintypes.HRGN
        radius=round(16*(user.GetDpiForWindow(self.window_handle) or 96)/96)
        region=gdi.CreateRoundRectRgn(0,0,self.root.winfo_width()+1,self.root.winfo_height()+1,radius,radius)
        if not user.SetWindowRgn(self.window_handle,region,True):
            gdi.DeleteObject.argtypes=[wintypes.HANDLE];gdi.DeleteObject(region)

    def drag_window(self,event):
        if os.name=='nt':
            import ctypes
            user=ctypes.windll.user32
            user.ReleaseCapture()
            user.SendMessageW(self.window_handle,0xA1,2,0)

    def toggle_maximize(self):
        self.root.state('normal' if self.root.state()=='zoomed' else 'zoomed')

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
        previous=getattr(self,'native_icons',[])
        if getattr(self,'native_icon_dpi',None)==dpi and len(previous)==2:
            icons=previous
        else:
            icons=[]
            for kind,metric in ((0,49),(1,11)):
                size=user.GetSystemMetricsForDpi(metric,dpi)
                icons.append(user.LoadImageW(None,str(ROOT/'assets/codex-transparent.ico'),1,size,size,0x10))
        for kind,icon in enumerate(icons):
            if icon: user.SendMessageW(hwnd,0x80,kind,icon)
        if icons is not previous:
            user.DestroyIcon.argtypes=[wintypes.HANDLE]
            for icon in previous:
                if icon: user.DestroyIcon(icon)
        self.native_icons=icons;self.native_icon_dpi=dpi

    def build(self):
        bg='#ffffff'; self.bg=bg
        head=tk.Frame(self.root,bg=bg); head.pack(fill='x',padx=0,pady=(0,10))
        controls=tk.Frame(head,bg=bg);controls.pack(side='right',anchor='n')
        for kind,cmd,tip in [('close',self.hide,'Hide to tray'),('maximize',self.toggle_maximize,'Maximize / restore'),('minimize',self.root.iconify,'Minimize')]:
            self.window_button(controls,kind,cmd,tip).pack(side='right')
        brand=tk.Frame(head,bg=bg);brand.pack(side='left',padx=20,pady=(12,0))
        self.logo=ImageTk.PhotoImage(load_icon(32).resize((28,28),Image.Resampling.LANCZOS),master=self.root)
        logo=tk.Label(brand,image=self.logo,bg=bg);logo.pack(side='left')
        name=tk.Label(brand,text='Codex',font=('Segoe UI',11),fg='#222426',bg=bg);name.pack(side='left',padx=9)
        for widget in (head,brand,logo,name):
            widget.bind('<ButtonPress-1>',self.drag_window)
            widget.bind('<Double-Button-1>',lambda event:self.toggle_maximize())
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
        self.status_tooltip=Tooltip(self.status,lambda:self.status_detail if self.status_detail else 'Latest refresh result')
        self.status_detail=self.data.get('details','')
    def window_button(self,parent,kind,command,tip):
        scale=max(1,float(self.root.tk.call('tk','scaling'))/(96/72))
        width,height=round(38*scale),round(33*scale)
        button=tk.Canvas(parent,width=width,height=height,bg=self.bg,bd=0,highlightthickness=0,cursor='arrow',takefocus=True)
        glyph={'close':'\ue8bb','minimize':'\ue921','maximize':'\ue922'}[kind]
        button.create_text(width/2,height/2,text=glyph,font=('Segoe MDL2 Assets',9),fill='#42474b',anchor='center',tags='icon')
        def hover(active):
            button.config(bg=('#c42b1c' if kind=='close' else '#e9ecee') if active else self.bg)
            button.itemconfigure('icon',fill='#ffffff' if active and kind=='close' else '#42474b')
        button.bind('<Enter>',lambda event:hover(True))
        button.bind('<Leave>',lambda event:hover(False))
        button.bind('<ButtonRelease-1>',lambda event:command() if 0<=event.x<width and 0<=event.y<height else None)
        button.bind('<Return>',lambda event:command());button.bind('<space>',lambda event:command())
        Tooltip(button,tip)
        return button

    def label(self,parent,text,size=10,color='#777b80',font='Segoe UI',bold=False,**kw):
        return tk.Label(parent,text=text,bg=self.bg,fg=color,font=(font,size,'bold' if bold else 'normal'),**kw)
    def draw(self):
        for x in self.body.winfo_children(): x.destroy()
        limits=self.data.get('limits',{})
        windows=[x for x in (limits.get('primary'),limits.get('secondary')) if x and x.get('usedPercent') is not None]
        for index,window in enumerate(windows or [None]):
            line=tk.Frame(self.body,bg=self.bg); line.pack(fill='x',pady=(0,10))
            text=f"{remaining_percent(window['usedPercent']):g}% remaining" if window else 'Usage unavailable'
            self.label(line,text,15,'#222426',anchor='w').pack(side='left')
            if index==0:
                for symbol,command,tip in [('⚙',self.settings_dialog,'Settings'),('↻',self.refresh,'Refresh')]:
                    button=tk.Button(line,text=symbol,command=command,font=('Segoe UI Symbol',14),relief='flat',bd=0,bg=self.bg,fg='#72797d',activebackground='#f2f4f3',cursor='hand2',padx=5,takefocus=False)
                    button.pack(side='right',padx=2);Tooltip(button,tip)
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
        delta.pack(fill='x',pady=(7,10)); Tooltip(delta,delta_tooltip(self.data) if d is not None else 'Available after the next successful refresh')
        tk.Frame(self.body,bg='#e9eaec',height=1).pack(fill='x')
        self.label(self.body,'Speed',11,'#292d30',anchor='w').pack(fill='x',pady=(9,5))
        speed=self.data.get('speed',{})
        for days in ('1','14'):
            period=tk.Frame(self.body,bg=self.bg);period.pack(fill='x',pady=(6,7))
            tk.Label(period,text='14 days' if days=='14' else '1 day',font=('Segoe UI Semibold',10),fg='#41564b',bg='#f0f4f1',padx=8,pady=2).pack(side='left')
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
        if not self.busy: self.status.config(text=self.data.get('status','Ready'))
        self.status_detail=self.data.get('details','')
    def build_sources(self,parent):
        footer=tk.Frame(parent,bg=self.bg); footer.pack(fill='x',pady=(14,18))
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
            ('Rich · speed tool formatting','https://github.com/Textualize/rich'),
            ('joblib · speed tool runtime','https://github.com/joblib/joblib'),
            ('orjson · fast JSON decoding','https://github.com/ijl/orjson'),
            ('Source code · Codex Meter '+VERSION,'https://github.com/HenryTeo27/ai-agent-usage-speed-app')]:
            link=self.label(footer,title,8,'#73777b',anchor='w',cursor='hand2')
            link.pack(fill='x',pady=2); link.bind('<Button-1>',lambda event,address=url:webbrowser.open(address))
    def settings_dialog(self):
        if getattr(self,'settings_window',None) is not None and self.settings_window.winfo_exists():
            self.settings_window.lift();return
        win=tk.Toplevel(self.root); win.title('Settings'); win.configure(bg=self.bg); win.resizable(False,False); win.transient(self.root)
        self.settings_window=win; win.grab_set()
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
        sources=tk.Frame(box,bg=self.bg);sources.grid(row=4,column=0,columnspan=2,sticky='ew')
        self.build_sources(sources)
    def schedule(self):
        if self.job: self.root.after_cancel(self.job); self.job=None
        if self.settings['interval']: self.job=self.root.after(self.settings['interval']*3600000,self.scheduled)
    def scheduled(self): self.job=None; self.refresh()
    def refresh(self):
        if self.busy: return
        self.usage_baseline=dict(self.data['usage']) if 'usage' in self.data else None
        self.busy=True; self.refresh_started=time.monotonic(); self.pending={'usage','limits','speed'}
        self.refresh_errors=[]; self.refresh_notes=[]; self.refresh_timings={}
        self.status.config(text='Refreshing…')
        threading.Thread(target=self.collect,daemon=True).start()
        self.root.after(500,self.check_results)
    def collect(self):
        def scan(name,fn):
            started=time.monotonic()
            try: return name,fn(),None,time.monotonic()-started
            except Exception as exc: return name,None,str(exc).replace('\n',' ')[:180],time.monotonic()-started
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(scan,name,fn) for name,fn in [('usage',get_usage),('limits',get_limits),('speed',get_speed)]]
            for future in as_completed(futures): self.results.put(future.result())
    def check_results(self):
        if self.closed: return
        while True:
            try: name,value,error,elapsed=self.results.get_nowait()
            except queue.Empty: break
            self.pending.discard(name); self.refresh_timings[name]=round(elapsed,2)
            if error: self.refresh_errors.append(name+': '+error)
            else:
                if name=='speed': value,note=value; self.refresh_notes.extend([note] if note else [])
                if name=='usage':
                    apply_usage_result(self.data,value,self.usage_baseline,time.time())
                self.data[name]=value
                self.data.setdefault('updated_at',{})[name]=time.time()
                self.data['status']=name.capitalize()+' updated '+datetime.now().strftime('%H:%M')
                try: save(SNAPSHOT,self.data)
                except OSError as exc: self.refresh_errors.append('save: '+str(exc)[:120])
                # Display each source immediately instead of waiting for the slowest one.
                self.render_results()
            if not self.pending:
                self.finish()
                return
        waiting=', '.join(sorted(self.pending))
        if self.root.state()!='withdrawn':
            text=f'Refreshing {waiting} · {time.monotonic()-self.refresh_started:.0f}s'
            if self.status.cget('text')!=text: self.status.config(text=text)
        self.root.after(1000 if self.root.state()=='withdrawn' else 500,self.check_results)
    def finish(self):
        if self.closed: return
        updated='Updated '+datetime.now().strftime('%H:%M')
        details=self.refresh_errors+self.refresh_notes
        self.data['status']=(updated+(' · tool fallback' if self.refresh_notes else '')) if not self.refresh_errors else 'Partial refresh · '+', '.join(error.split(':')[0] for error in self.refresh_errors)+' failed'
        self.data['details']='\n'.join(details)
        self.data['refresh_seconds']=self.refresh_timings
        self.data['app_version']=VERSION
        if not self.refresh_errors: self.data['last_refresh_at']=time.time()
        try: save(SNAPSHOT,self.data)
        except Exception as exc: self.data['status']='Could not save latest result'; self.data['details']=str(exc)
        finally:
            self.busy=False; self.schedule()
        self.status.config(text=self.data.get('status','Ready'))
        self.render_results()
    def publish_ready(self):
        if os.name=='nt' and hasattr(self,'window_handle'):
            import ctypes
            from ctypes import wintypes
            user=ctypes.windll.user32
            user.SetPropW.argtypes=[wintypes.HWND,wintypes.LPCWSTR,wintypes.HANDLE]
            user.SetPropW(self.window_handle,'CodexMeter.Ready',1)

    def on_map(self,event):
        if event.widget is self.root:
            # Tk can recreate the native wrapper on restore; never keep its old HWND.
            self.configure_window()
            if self.dirty: self.draw();self.dirty=False
            self.publish_ready()
    def render_results(self):
        if self.root.state()=='withdrawn': self.dirty=True
        else: self.draw()
    def setup_tray(self):
        im=load_icon(32)
        self.tray=pystray.Icon('Codex Meter',im,'Codex Meter',pystray.Menu(pystray.MenuItem('Open',lambda:self.root.after(0,self.show),default=True),pystray.MenuItem('Refresh',lambda:self.root.after(0,self.refresh)),pystray.MenuItem('Quit',lambda:self.root.after(0,self.quit))))
        self.tray.run_detached()
    def hide(self):
        for tooltip in list(Tooltip.instances):
            try:
                if tooltip.widget.winfo_toplevel() is self.root: tooltip.hide()
            except tk.TclError: pass
        if getattr(self,'settings_window',None) is not None and self.settings_window.winfo_exists(): self.settings_window.destroy()
        self.root.withdraw()
    def show(self):
        if self.dirty: self.draw(); self.dirty=False
        self.root.deiconify(); self.root.lift(); self.root.focus_force()
    def quit(self):
        self.closed=True
        cancel_scans()
        self.tray.stop(); self.root.destroy()
    def run(self): self.root.mainloop()

def worker_main():
    import runpy
    args=sys.argv[1:]
    output_index=args.index('--worker-output')
    output=Path(args[output_index+1]); del args[output_index:output_index+2]
    buffer=io.StringIO()
    try:
        if args[0]=='--limits': value=limits_worker()
        elif args[0]=='--diagnose':
            value={}
            def measure(name,fn):
                started=time.monotonic()
                try:
                    result=fn()
                    if name=='speed': result={'rows':{k:len(rows) for k,rows in result[0].items()},'note':result[1]}
                    return name,{'ok':True,'seconds':round(time.monotonic()-started,2),'result':result}
                except Exception as exc: return name,{'ok':False,'seconds':round(time.monotonic()-started,2),'error':str(exc)}
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures=[pool.submit(measure,name,fn) for name,fn in [('usage',get_usage),('limits',get_limits),('speed',get_speed)]]
                for future in as_completed(futures):
                    name,result=future.result(); value[name]=result
        elif args[0]=='--speed-all': value=scan_speed()
        elif args[0]=='--speed-batch': value=speed_batch(args[1])
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


def find_ready_window():
    import ctypes
    from ctypes import wintypes
    user=ctypes.windll.user32
    user.GetPropW.argtypes=[wintypes.HWND,wintypes.LPCWSTR];user.GetPropW.restype=wintypes.HANDLE
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    found=[]
    @callback
    def inspect_window(hwnd,unused):
        if user.GetPropW(hwnd,'CodexMeter.Ready'):
            found.append(hwnd);return False
        return True
    user.EnumWindows.argtypes=[callback,wintypes.LPARAM]
    user.EnumWindows(inspect_window,0)
    return found[0] if found else None


def start_single_instance():
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);user=ctypes.windll.user32
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    user.FindWindowW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR];user.FindWindowW.restype=wintypes.HWND
    user.GetPropW.argtypes=[wintypes.HWND,wintypes.LPCWSTR];user.GetPropW.restype=wintypes.HANDLE
    user.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int];user.SetForegroundWindow.argtypes=[wintypes.HWND]
    handle=kernel.CreateMutexW(None,False,'Local\\CodexMeterSingleInstance')
    existed=ctypes.get_last_error()==183
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    try:
        if existed:
            # Never expose a partially built window during rapid double-click launches.
            for attempt in range(160):
                hwnd=find_ready_window()
                if hwnd:
                    user.ShowWindow(hwnd,9)
                    for restored in range(20):
                        current=find_ready_window()
                        if current:
                            user.SetForegroundWindow(current);break
                        time.sleep(0.025)
                    break
                time.sleep(0.05)
        else:
            App().run()
    finally: kernel.CloseHandle(handle)


if __name__=='__main__':
    if '--worker-output' in sys.argv: worker_main()
    else: start_single_instance()
