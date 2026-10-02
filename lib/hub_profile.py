"""Share user instructions and skills without sharing login storage."""
import json
from pathlib import Path
import time
try:
    import tomllib
except ImportError:
    import tomli as tomllib
import hub_config

SETTINGS = ('model', 'model_reasoning_effort', 'service_tier', 'approval_policy',
            'approvals_reviewer', 'sandbox_mode', 'tui', 'features', 'projects',
            'shell_environment_policy', 'plugins', 'marketplaces')
FILES = ('AGENTS.md', 'AGENTS.override.md', 'skills', 'rules', 'agents', 'prompts')


def link(source, destination, backup):
    if not source.exists():
        return
    if destination.is_symlink() and destination.resolve() == source.resolve():
        return
    if destination.exists() or destination.is_symlink():
        backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination.rename(backup)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.symlink_to(source.resolve(), target_is_directory=source.is_dir())


def sync(source, root=hub_config.ROOT):
    source = Path(source).expanduser().resolve()
    if not source.is_dir():
        raise ValueError('Choose an existing Codex profile directory.')
    with hub_config.locked(root):
        config = hub_config.load(root)
        config['profileSource'] = str(source)
        config['sharedLibrary'] = True
        backup = Path(root) / 'profile-backups' / (str(time.time_ns()))
        for slot, account in config['accounts'].items():
            home = Path(account['home'])
            if home.resolve() == source:
                continue
            for name in FILES:
                link(source / name, home / name, backup / slot / name)
            link(source / 'plugins/cache', home / 'plugins/cache', backup / slot / 'plugins/cache')
        hub_config.save(config, root)
    return config


def arguments(root=hub_config.ROOT):
    source = hub_config.load(root).get('profileSource')
    if not source:
        return []
    path = Path(source) / 'config.toml'
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text())
    def leaves(value, keys):
        if isinstance(value, dict):
            for key, child in value.items():
                yield from leaves(child, keys + [key])
        else:
            # JSON scalar/array syntax is also TOML syntax for these settings.
            yield '.'.join(json.dumps(key) for key in keys) + '=' + json.dumps(value)
    return [arg for key in SETTINGS if key in data
            for leaf in leaves(data[key], [key]) for arg in ('-c', leaf)]
