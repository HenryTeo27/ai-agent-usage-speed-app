"""Discover Codex homes and environment credentials without persisting secrets."""
import json
import os
from pathlib import Path


def persisted_environment(name):
    if os.name != 'nt':
        return []
    import winreg
    values = []
    locations = ((winreg.HKEY_CURRENT_USER, 'Environment'),
                 (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'))
    for root, key in locations:
        try:
            with winreg.OpenKey(root, key) as handle:
                value, _ = winreg.QueryValueEx(handle, name)
                if isinstance(value, str) and value.strip():
                    values.append(value)
        except OSError:
            pass
    return values


def codex_homes():
    root = Path.home()
    candidates = [root / '.codex']
    for value in [os.environ.get('CODEX_HOME', ''), *persisted_environment('CODEX_HOME')]:
        if value:
            candidates.append(Path(os.path.expandvars(value)).expanduser())
    for value in [os.environ.get('CODEX_METER_EXTRA_HOMES', ''), *persisted_environment('CODEX_METER_EXTRA_HOMES')]:
        candidates.extend(Path(os.path.expandvars(part)).expanduser()
                          for part in value.split(os.pathsep) if part.strip())
    try:
        candidates.extend(sorted(root.glob('.codex*')))
    except OSError:
        pass
    result, seen = [], set()
    for candidate in candidates:
        try:
            path = candidate.resolve()
            key = os.path.normcase(str(path))
            if key in seen or not path.is_dir():
                continue
            if not any((path / name).exists() for name in ('auth.json', 'config.toml', 'sessions', 'archived_sessions')):
                continue
            seen.add(key)
            result.append(path)
        except OSError:
            continue
    return result


def source_id(home):
    return str(home)


def source_label(home):
    return home.name if home.parent == Path.home() else str(home)


def read_auth_mode(home):
    try:
        with (home / 'auth.json').open(encoding='utf-8') as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            return None
        if data.get('auth_mode') == 'apikey' or data.get('OPENAI_API_KEY'):
            return 'apiKey'
        if data.get('auth_mode') in ('chatgpt', 'chatgptAuthTokens') or data.get('tokens'):
            return 'chatgpt'
    except (OSError, ValueError):
        pass
    return None


def account_names(homes):
    """Short, deterministic names shared by Settings, deltas and speed rows."""
    names, counts = {}, {}
    for home in homes:
        mode = read_auth_mode(home)
        base = {'chatgpt': 'GPT', 'apiKey': 'API'}.get(mode, 'Codex')
        counts[base] = counts.get(base, 0) + 1
        names[source_id(home)] = base + (str(counts[base]) if counts[base] > 1 else '')
    return names
