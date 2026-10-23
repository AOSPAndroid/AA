"""Manual, read-only AD queries using the Atlas host's Windows identity."""
import json
import base64
import re
import secrets
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

class Lookup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['user', 'computer']
    identity: str = Field(min_length=1, max_length=128)
    server: str = Field(default='', max_length=128)

class Browse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['children', 'search', 'members', 'details'] = 'children'
    kind: Literal['all', 'user', 'computer', 'group', 'ou'] = 'all'
    base: str = Field(default='', max_length=2048)
    query: str = Field(default='', max_length=128)
    server: str = Field(default='', max_length=128)
    limit: int = Field(default=200, ge=1, le=5000)

def browse(body, powershell):
    if body.server and not re.fullmatch(r'(?![-.])(?!.*\.\.)[A-Za-z0-9_.-]{1,128}', body.server):
        raise HTTPException(400, 'Enter a domain or domain-controller hostname')
    if any(ord(c) < 32 for c in body.base + body.query):
        raise HTTPException(400, 'Control characters are not allowed')
    if body.operation in ('members', 'details') and not body.base:
        raise HTTPException(400, 'Select an AD object first')
    encoded = base64.b64encode(body.model_dump_json().encode('utf-8')).decode('ascii')
    script = "$request=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "')) | ConvertFrom-Json;" + (Path(__file__).parent/'scripts/ad_browser.ps1').read_text(encoding='utf-8')
    try:
        output = powershell(script, timeout=35)
        if len(output) > 5000000:
            raise ValueError('Response too large. Narrow the search or choose an OU.')
        result = json.loads(output)
        if isinstance(result, dict) and result.get('error'):
            raise ValueError(result['error'])
        if not isinstance(result, dict) or not isinstance(result.get('items'), list):
            raise ValueError('Unexpected directory response')
        return result
    except subprocess.TimeoutExpired:
        raise HTTPException(504, 'Directory browse timed out. Choose a smaller OU or narrow the search.')
    except Exception as error:
        raise HTTPException(502, 'AD browser: ' + readable_error(error)) from error

def script_for(body):
    identity, server = body.identity.strip(), body.server.strip()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@$\\-]{0,127}', identity):
        raise HTTPException(400, 'Enter an exact account, DOMAIN\\account, UPN, or computer name')
    if '\\' in identity:
        parts = identity.split('\\')
        if len(parts) != 2 or not all(parts):
            raise HTTPException(400, 'Invalid domain account')
        domain, identity = parts
        server = server or domain
    if body.kind == 'user':
        # Report IDs B/G/X + digits map to the bank's X domain account.
        match = re.fullmatch(r'[BGXbgx]([0-9]+)(@[^@]+)?', identity)
        if match:
            identity = 'X' + match[1] + (match[2] or '')
    if server and not re.fullmatch(r'(?![-.])(?!.*\.\.)[A-Za-z0-9_.-]{1,128}', server):
        raise HTTPException(400, 'Enter a domain or domain-controller hostname')
    # Validated values are additionally quoted as PowerShell literals.
    quote = lambda s: "'" + s.replace("'", "''") + "'"
    return '$kind=' + quote(body.kind) + ';$identity=' + quote(identity) + ';$server=' + quote(server) + ';' + (Path(__file__).parent/'scripts/active_directory.ps1').read_text(encoding='utf-8')

def readable_error(error):
    text = str(error)
    if '<Objs' in text:
        try:
            root = ET.fromstring(text[text.index('<Objs'):text.rindex('</Objs>') + 7])
            text = ' '.join(n.text or '' for n in root.iter() if n.tag.endswith('}S') and n.get('S') == 'Error')
        except (ValueError, ET.ParseError):
            return 'PowerShell could not complete the lookup. Check RSAT, domain connectivity and Domain / controller.'
    text = re.sub(r'_x([0-9a-fA-F]{4})_', lambda m: chr(int(m[1], 16)), text)
    text = re.split(r'\r?\n\s*(?:At line:|\+|CategoryInfo)', text)[0]
    return ' '.join(text.split())[:900]

def lookup(body, powershell):
    script = script_for(body)
    try:
        output = powershell(script, timeout=35)
        if len(output) > 1000000:
            raise ValueError('AD response exceeds the display limit')
        result = json.loads(output)
        if isinstance(result, dict) and isinstance(result.get('error'), str):
            raise ValueError(result['error'])
        if not isinstance(result, dict) or not isinstance(result.get('details'), dict) or not isinstance(result.get('groups'), list):
            raise ValueError('Unexpected directory response')
        return result
    except subprocess.TimeoutExpired:
        raise HTTPException(504, 'AD lookup timed out. Check domain connectivity and the selected server.')
    except Exception as error:
        raise HTTPException(502, 'AD lookup failed: ' + readable_error(error)) from error

def register(app, powershell):
    @app.post('/api/active-directory/browse')
    def browse_query(body: Browse, request: Request):
        from atlas_api import TOKEN
        if not secrets.compare_digest(request.headers.get('x-atlas-token', ''), TOKEN):
            raise HTTPException(403, 'Refresh Atlas before browsing Active Directory')
        return browse(body, powershell)

    @app.post('/api/active-directory/lookup')
    def query(body: Lookup, request: Request):
        from atlas_api import TOKEN
        if not secrets.compare_digest(request.headers.get('x-atlas-token', ''), TOKEN):
            raise HTTPException(403, 'Refresh Atlas before querying Active Directory')
        return lookup(body, powershell)
