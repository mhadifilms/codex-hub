"""Private user configuration for Codex Hub; no credential reads."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

AUTH_ENV = ('OPENAI_API_KEY', 'CODEX_ACCESS_TOKEN', 'CODEX_API_KEY',
            'OPENAI_IDENTITY_TOKEN_FILE', 'OPENAI_IDENTITY_FEDERATION_RULE_ID')

def default_root():
    if os.environ.get('CODEX_HUB_ROOT'):
        return Path(os.environ['CODEX_HUB_ROOT']).expanduser().resolve()
    legacy = Path.home() / '.codex-subs'
    if legacy.is_dir():
        return legacy.resolve()
    return (Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'codex-hub').resolve()

ROOT = default_root()
VERSION = (Path(__file__).resolve().parent / 'VERSION' if (Path(__file__).resolve().parent / 'VERSION').is_file()
           else Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip()
ID_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}$')

def validate(data):
    if data.get('schemaVersion') != 1:
        raise ValueError('Unsupported config version; expected schemaVersion 1.')
    if type(data.get('scrollLines', 1)) is not int or not 1 <= data.get('scrollLines', 1) <= 20:
        raise ValueError('scrollLines must be an integer from 1 to 20.')
    if 'codexBinary' in data and (not isinstance(data['codexBinary'], str) or not data['codexBinary'].strip()):
        raise ValueError('codexBinary must be an executable path or command name.')
    accounts = data.get('accounts')
    if not isinstance(accounts, dict) or not accounts:
        raise ValueError('Configure at least one account.')
    for ident, account in accounts.items():
        if not ID_PATTERN.fullmatch(ident) or ident in ('all', 'main', 'attach', 'tui', 'setup', 'reload', 'doctor', 'list', 'new', 'resume', 'cli', 'accounts', 'settings', 'usage', 'config', 'sidebar', 'welcome', 'picker', 'manage', 'chat', 'account-login'):
            raise ValueError('Account IDs must be unique command-safe names (letters, numbers, _ or -).')
        if not isinstance(account, dict) or not isinstance(account.get('label'), str) or not account['label'].strip():
            raise ValueError('Each account needs a label.')
        if not isinstance(account.get('home'), str) or not account['home']:
            raise ValueError('Each account needs a Codex home path.')
        account['home'] = str(Path(account['home']).expanduser().resolve())
        if account.get('session') and not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', account['session']):
            raise ValueError('Invalid tmux session name.')
    if data.get('defaultAccount') not in accounts:
        raise ValueError('defaultAccount must name a configured account.')
    return data


def initial(root):
    # Discover old isolated homes by file presence only; never read credentials.
    legacy = {}
    if root.is_dir():
        for directory in sorted(root.iterdir()):
            if directory.is_dir() and ID_PATTERN.fullmatch(directory.name) and (
                (directory / 'config.toml').is_file() or any(directory.glob('state_*.sqlite'))):
                legacy[directory.name] = {'label': 'Account ' + directory.name, 'home': str(directory),
                                          'description': 'Local workspace', 'session': 'codex-sub-' + directory.name}
    accounts = legacy or {'default': {'label': 'Default', 'description': 'Local workspace',
                                      'home': str(Path.home() / '.codex')}}
    return {'schemaVersion': 1, 'defaultAccount': next(iter(accounts)), 'accounts': accounts}


def load(root=ROOT):
    path = root / 'config.json'
    try:
        with path.open() as source:
            return validate(json.load(source))
    except FileNotFoundError:
        return validate(initial(root))
    except json.JSONDecodeError as error:
        raise ValueError(f'Invalid JSON in {path}: {error.msg}') from error


def save(data, root=ROOT):
    validate(data)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=root, delete=False) as output:
        temporary = Path(output.name)
        json.dump(data, output, indent=2)
        output.write('\n')
    temporary.chmod(0o600)
    temporary.replace(root / 'config.json')


@contextmanager
def locked(root=ROOT):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / 'config.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def initialize(root=ROOT):
    with locked(root):
        data = load(root)
        if not (root / 'config.json').exists():
            save(data, root)
        if not (root / 'tmux.conf').exists():
            library = Path(__file__).resolve().parent
            bundled = library / 'tmux.conf'
            if not bundled.exists():
                bundled = library.parent / 'tmux.conf'
            shutil.copyfile(bundled, root / 'tmux.conf')
            (root / 'tmux.conf').chmod(0o600)
    return data


def home(ident, root=ROOT):
    accounts = load(root)['accounts']
    if ident not in accounts:
        raise ValueError(f'Unknown account: {ident}. Run codex-hub accounts list.')
    return Path(accounts[ident]['home'])


def environment(ident, root=ROOT):
    env = os.environ.copy()
    for key in AUTH_ENV:
        env.pop(key, None)
    env['CODEX_HOME'] = str(home(ident, root))
    env['CODEX_HUB_ROOT'] = str(root)
    return env


def session(ident, root=ROOT):
    return load(root)['accounts'][ident].get('session', 'codex-hub-' + ident)


def executable(root=ROOT):
    selected = os.environ.get('CODEX_HUB_CODEX') or load(root).get('codexBinary') or 'codex'
    path = shutil.which(str(Path(selected).expanduser()))
    if not path:
        raise ValueError(f'Codex executable unavailable: {selected}. Set codexBinary in the hub config.')
    return path


def preferences(root=ROOT, **values):
    with locked(root):
        data = load(root)
        data.update(values)
        save(data, root)
    return data


def add(ident, label=None, codex_home=None, description='', root=ROOT):
    with locked(root):
        data = load(root)
        if ident in data['accounts']:
            raise ValueError('That account ID already exists.')
        path = Path(codex_home).expanduser().resolve() if codex_home else root / 'accounts' / ident
        data['accounts'][ident] = {'label': label or ident, 'home': str(path), 'description': description}
        validate(data)
        # Managed account homes use file storage for independent browser logins.
        if not codex_home:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            config = path / 'config.toml'
            if not config.exists():
                with config.open('x') as stream:
                    stream.write('cli_auth_credentials_store = "file"\n')
                config.chmod(0o600)
        save(data, root)
    return data


def update(ident, label=None, description=None, default=False, root=ROOT):
    with locked(root):
        data = load(root)
        if ident not in data['accounts']:
            raise ValueError('Unknown account.')
        if label is not None:
            data['accounts'][ident]['label'] = label.strip()
        if description is not None:
            data['accounts'][ident]['description'] = description.strip()
        if default:
            data['defaultAccount'] = ident
        save(data, root)
    return data


def remove(ident, root=ROOT):
    with locked(root):
        data = load(root)
        if ident not in data['accounts']:
            raise ValueError('Unknown account.')
        if len(data['accounts']) == 1:
            raise ValueError('Keep at least one account configured.')
        del data['accounts'][ident]
        if data['defaultAccount'] == ident:
            data['defaultAccount'] = next(iter(data['accounts']))
        save(data, root)
    # Homes, credentials, and chat history are deliberately retained on disk.
    return data
