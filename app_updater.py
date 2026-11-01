"""Quiet, verified application updates for the per-user Windows installation."""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

REPO='HenryTeo27/codex-meter'
LEGACY_REPO='HenryTeo27/ai-agent-usage-speed-app'
API=f'https://api.github.com/repos/{REPO}/releases/latest'
ARCHIVE='Codex-Meter-Windows-x64.zip'
HOSTS={'api.github.com','github.com','release-assets.githubusercontent.com',
       'objects.githubusercontent.com','github-releases.githubusercontent.com'}
MAX_DOWNLOAD=200*1024*1024
MAX_EXTRACTED=600*1024*1024
MAX_FILES=20000
CREATE_NO_WINDOW=0x08000000 if os.name=='nt' else 0


def version_tuple(value):
    match=re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)',str(value))
    if not match: raise ValueError('Invalid release version')
    return tuple(map(int,match.groups()))


def installed_root(source_file,executable,frozen,data_dir):
    """Never update a development checkout or an extracted, portable bundle."""
    if os.name!='nt' or not os.environ.get('LOCALAPPDATA'): return None
    local=Path(os.environ['LOCALAPPDATA']).resolve()
    if Path(data_dir).resolve()!=(local/'CodexMeter').resolve(): return None
    expected=(local/'Programs'/'CodexMeter').resolve()
    actual=(Path(executable).parent if frozen else Path(source_file).parent).resolve()
    return expected if actual==expected else None


def configure_logon_resume(source_file,executable,frozen,data_dir,enabled):
    """One pending update may resume at sign-in; this is not general autostart."""
    if installed_root(source_file,executable,frozen,data_dir) is None: return
    import winreg
    key_path=r'Software\Microsoft\Windows\CurrentVersion\RunOnce'
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,key_path,0,winreg.KEY_SET_VALUE) as key:
            if enabled:
                command=[str(executable)]
                if not frozen: command.append(str(source_file))
                winreg.SetValueEx(key,'CodexMeterPendingUpdate',0,winreg.REG_SZ,
                                 subprocess.list2cmdline(command+['--start-hidden']))
            else:
                try: winreg.DeleteValue(key,'CodexMeterPendingUpdate')
                except FileNotFoundError: pass
    except OSError: pass  # Next app launch still resumes from the saved archive.


def check_url(url):
    from urllib.parse import urlsplit
    parsed=urlsplit(url)
    if (parsed.scheme!='https' or parsed.hostname not in HOSTS or parsed.username or parsed.password
            or parsed.port not in (None,443)):
        raise ValueError('Untrusted update URL')
    return url


def open_url(url,timeout=20):
    import urllib.request
    class SafeRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            return super().redirect_request(req,fp,code,msg,headers,check_url(newurl))
    request=urllib.request.Request(check_url(url),headers={'User-Agent':'Codex-Meter-Updater',
        'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    return urllib.request.build_opener(SafeRedirect()).open(request,timeout=timeout)


def release_candidate(metadata,current_version):
    if metadata.get('draft') or metadata.get('prerelease'): return None
    tag=metadata.get('tag_name','')
    if version_tuple(tag)<=version_tuple(current_version): return None
    matches=[item for item in metadata.get('assets',[]) if item.get('name')==ARCHIVE]
    if len(matches)!=1: raise ValueError('Release archive is missing or ambiguous')
    asset=matches[0];digest=asset.get('digest','')
    if not isinstance(digest,str) or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}',digest):
        raise ValueError('Release archive has no SHA-256 digest')
    size=asset.get('size')
    if type(size) is not int or not 0<size<=MAX_DOWNLOAD: raise ValueError('Invalid release archive size')
    allowed={f'https://github.com/{repo}/releases/download/{tag}/{ARCHIVE}' for repo in (REPO,LEGACY_REPO)}
    url=asset.get('browser_download_url')
    if url not in allowed: raise ValueError('Unexpected release archive URL')
    return {'version':tag.removeprefix('v'),'url':url,'sha256':digest[7:].lower(),'size':size}


def latest_release(current_version):
    with open_url(API) as response: raw=response.read(1024*1024+1)
    if len(raw)>1024*1024: raise ValueError('Release metadata is too large')
    return release_candidate(json.loads(raw),current_version)


def remove_stage(stage,updates):
    stage=Path(stage).resolve();updates=Path(updates).resolve()
    if stage.parent!=updates or not re.fullmatch(r'update-[0-9a-f]{32}',stage.name):
        raise ValueError('Unexpected update staging directory')
    if stage.exists(): shutil.rmtree(stage)
    manifest=updates/'ready-update.json'
    try:
        if Path(json.loads(manifest.read_text(encoding='utf-8-sig'))['stage']).resolve()==stage:
            manifest.unlink(missing_ok=True)
    except (OSError,ValueError,KeyError,TypeError): pass


def clean_stale_stages(updates,now=None):
    updates=Path(updates)
    if not updates.is_dir(): return
    cutoff=(time.time() if now is None else now)-2*24*3600
    try: active=Path(json.loads((updates/'ready-update.json').read_text(encoding='utf-8-sig'))['stage']).resolve()
    except (OSError,ValueError,KeyError,TypeError): active=None
    for stage in updates.iterdir():
        if re.fullmatch(r'update-[0-9a-f]{32}',stage.name) and stage.is_dir():
            try:
                if stage.resolve()!=active and stage.stat().st_mtime<cutoff: remove_stage(stage,updates)
            except (OSError,ValueError): pass


def previous_failure(data_dir,current_version):
    path=Path(data_dir)/'updates'/'last-failure.json'
    try:
        value=json.loads(path.read_text(encoding='utf-8-sig'))
        checked=value['checked_at']
        if (type(checked) not in (int,float) or not 0<checked<=time.time()
                or version_tuple(value['version'])<=version_tuple(current_version)):
            return None
        return {'checked_at':checked,'version':value['version']}
    except (OSError,ValueError,KeyError,TypeError): return None


def remember_ready(candidate,stage,data_dir):
    import tempfile
    updates=Path(data_dir)/'updates';path=updates/'ready-update.json'
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=updates,delete=False,suffix='.tmp') as stream:
            temporary=Path(stream.name)
            json.dump({'candidate':candidate,'stage':str(Path(stage).resolve())},stream)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def ready_update(data_dir,current_version):
    updates=(Path(data_dir)/'updates').resolve();path=updates/'ready-update.json'
    try:
        value=json.loads(path.read_text(encoding='utf-8-sig'));candidate=value['candidate']
        stage=Path(value['stage']).resolve()
        if (stage.parent!=updates or not re.fullmatch(r'update-[0-9a-f]{32}',stage.name)
                or version_tuple(candidate['version'])<=version_tuple(current_version)
                or not (stage/ARCHIVE).is_file()):
            path.unlink(missing_ok=True);return None
        # Reuse the same strict metadata rules before trusting a persisted candidate.
        release_candidate({'tag_name':'v'+candidate['version'],'assets':[{'name':ARCHIVE,
            'size':candidate['size'],'digest':'sha256:'+candidate['sha256'],
            'browser_download_url':candidate['url']}]},current_version)
        return candidate,stage
    except (OSError,ValueError,KeyError,TypeError): return None


def resume_ready(data_dir,current_version,health_check,cancelled=lambda:False):
    import hashlib
    ready=ready_update(data_dir,current_version)
    if ready is None: return None
    candidate,stage=ready
    try:
        digest=hashlib.sha256();size=0
        with (stage/ARCHIVE).open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):
                if cancelled(): raise RuntimeError('Update cancelled')
                size+=len(chunk);digest.update(chunk)
        if size!=candidate['size'] or digest.hexdigest()!=candidate['sha256']:
            raise ValueError('Saved update checksum does not match')
        payload=stage/'CodexMeter'
        # This exact child is inside the already validated staging directory.
        if payload.exists():
            if payload.is_symlink() or payload.resolve().parent!=stage: raise ValueError('Unsafe saved payload')
            shutil.rmtree(payload)
        target=extract_bundle(stage/ARCHIVE,stage)
        health_check(target/'CodexMeter.exe',candidate['version'],stage)
        return candidate,stage
    except Exception:
        (Path(data_dir)/'updates'/'ready-update.json').unlink(missing_ok=True)
        remove_stage(stage,Path(data_dir)/'updates')
        raise


def extract_bundle(archive,stage):
    """Extract only the program bundle, rejecting unsafe Windows paths and links."""
    import stat,zipfile
    target=Path(stage)/'CodexMeter';seen=set();total=0;count=0
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            name=info.filename
            if not name.startswith('CodexMeter/'): continue
            parts=name.split('/')
            if parts[-1]=='': parts.pop()
            if len(parts)==1 and info.is_dir(): continue
            if (len(parts)<2 or any(not part or part in ('.','..') or '\\' in part or ':' in part
                                    or part.endswith((' ','.')) for part in parts)):
                raise ValueError('Unsafe path in update archive')
            for part in parts:
                if re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?',part):
                    raise ValueError('Reserved path in update archive')
            if stat.S_ISLNK(info.external_attr>>16): raise ValueError('Link in update archive')
            key='/'.join(parts).casefold()
            if key in seen: raise ValueError('Duplicate path in update archive')
            seen.add(key);count+=1;total+=info.file_size
            if count>MAX_FILES or total>MAX_EXTRACTED: raise ValueError('Update archive is too large')
            destination=target.joinpath(*parts[1:])
            if info.is_dir(): destination.mkdir(parents=True,exist_ok=True)
            else:
                destination.parent.mkdir(parents=True,exist_ok=True)
                with bundle.open(info) as source,destination.open('xb') as output:
                    shutil.copyfileobj(source,output,length=1024*1024)
    if not (target/'CodexMeter.exe').is_file() or not (target/'_internal').is_dir():
        raise ValueError('Update archive does not contain a complete app')
    return target


def download_and_stage(candidate,data_dir,health_check,cancelled=lambda:False):
    """Download, hash and validate before allowing any installed file to change."""
    import hashlib,uuid
    updates=Path(data_dir)/'updates';updates.mkdir(parents=True,exist_ok=True)
    clean_stale_stages(updates)
    stage=updates/('update-'+uuid.uuid4().hex);stage.mkdir()
    try:
        archive=stage/ARCHIVE;digest=hashlib.sha256();size=0;started=time.monotonic()
        with open_url(candidate['url'],timeout=30) as response,archive.open('xb') as output:
            while True:
                if cancelled(): raise RuntimeError('Update cancelled')
                if time.monotonic()-started>600: raise RuntimeError('Update download timed out')
                chunk=response.read(1024*1024)
                if not chunk: break
                size+=len(chunk)
                if size>candidate['size'] or size>MAX_DOWNLOAD: raise ValueError('Update download is too large')
                digest.update(chunk);output.write(chunk)
        if size!=candidate['size'] or digest.hexdigest()!=candidate['sha256']:
            raise ValueError('Update checksum does not match the release')
        if cancelled(): raise RuntimeError('Update cancelled')
        target=extract_bundle(archive,stage)
        if cancelled(): raise RuntimeError('Update cancelled')
        health_check(target/'CodexMeter.exe',candidate['version'],stage)
        remember_ready(candidate,stage,data_dir)
        return stage
    except Exception:
        try: remove_stage(stage,updates)
        except OSError: pass
        raise


def start_installer(stage,target,data_dir,helper,version,relaunch):
    stage=Path(stage).resolve();updates=(Path(data_dir)/'updates').resolve()
    if stage.parent!=updates or not re.fullmatch(r'update-[0-9a-f]{32}',stage.name):
        raise ValueError('Unexpected update staging directory')
    if not (stage/'CodexMeter'/'CodexMeter.exe').is_file(): raise ValueError('Update is incomplete')
    version_tuple(version)
    script=stage/'apply-update.ps1';shutil.copyfile(helper,script)
    powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    subprocess.Popen([str(powershell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                      '-File',str(script),'-ParentPid',str(os.getpid()),'-Target',str(target),
                      '-Stage',str(stage),'-Version',version,'-Relaunch',str(int(relaunch))],
                     cwd=str(updates),
                     stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                     creationflags=CREATE_NO_WINDOW)
