"""AA-only discovery of this workspace's local Admin server."""
import json
from pathlib import Path
from runtime_paths import paths
from axis.launch_atlas import AtlasLaunchError, _get_json


def active_port(root, identity, required=False):
    root=Path(root).resolve()
    try:
        record=json.loads((paths(root).root/'server.json').read_text())
        port=record['port']
        if type(port) is not int or not 1024<=port<=65535:
            raise ValueError('Invalid Admin port')
        health=_get_json(port,'/api/health')
    except (OSError,ValueError,KeyError,TypeError):
        if not required:
            return None
        raise AtlasLaunchError('Cannot verify AA startup. Check the runtime logs.') from None
    if (health.get('application')!='Office Atlas' or health.get('mode')!='admin'
            or health.get('instance_id')!=record.get('instance_id') or not record.get('instance_id')
            or Path(record.get('root','')).resolve()!=root or Path(health.get('instance_root','')).resolve()!=root):
        raise AtlasLaunchError('The server does not belong to this AA folder. Use its Stop AA.bat.')
    if str(health.get('identity','')).casefold()!=identity.casefold():
        raise AtlasLaunchError('AA is running under another Windows account. Use its existing launcher to stop it.')
    return port
