"""Explicit service administration through the existing WMI transport."""
import json
import logging
import re
import threading
from pathlib import Path
from weakref import WeakValueDictionary
from fastapi import HTTPException

MANAGE_SCRIPT = (Path(__file__).parent / 'scripts' / 'remote_services.ps1').read_text(encoding='utf-8')
_CONTROL_LOCKS = WeakValueDictionary()
_CONTROL_REGISTRY_LOCK = threading.Lock()
_OUTCOMES = {
    'stop': ('stopped', 'already_stopped', 'pending', 'blocked', 'changed', 'gone', 'failed'),
    'start': ('started', 'already_running', 'pending', 'blocked', 'changed', 'gone', 'failed'),
    'restart': ('restarted', 'pending', 'blocked', 'changed', 'gone', 'failed'),
}
_VERIFIED_STATES = {'stopped': 'Stopped', 'already_stopped': 'Stopped', 'started': 'Running', 'already_running': 'Running', 'restarted': 'Running'}
_STATES = {'Running', 'Stopped', 'Paused', 'Start Pending', 'Stop Pending', 'Continue Pending', 'Pause Pending', 'Unknown'}

SCRIPT = r"""
$ErrorActionPreference='Stop'
$s=Get-WmiObject -ComputerName $pc -Class Win32_Service -Filter "Name='RemoteRegistry'" -ErrorAction Stop
if(!$s){throw 'Remote Registry service was not found'}
$before=$s.State
$mode=$s.StartMode
if($s.StartMode -eq 'Disabled') {
 $code=$s.ChangeStartMode('Manual').ReturnValue
 if($code -ne 0){throw "Could not enable Remote Registry (service code $code). Check remote administrator rights and policy."}
 $s.Get()
}
if($s.State -ne 'Running') {
 $code=$s.StartService().ReturnValue
 if($code -notin @(0,10)){throw "Could not start Remote Registry (service code $code). Check remote administrator rights and policy."}
 for($i=0; $i -lt 20 -and $s.State -ne 'Running'; $i++) {Start-Sleep -Milliseconds 250; $s.Get()}
}
if($s.State -ne 'Running'){throw "Remote Registry has not reached Running (state: $($s.State), startup: $($s.StartMode)). Refresh or check Services on the target."}
@{computer=$pc;service='RemoteRegistry';state=$s.State;start_mode=$s.StartMode;previous_state=$before;previous_start_mode=$mode} | ConvertTo-Json -Compress
"""

def enable_remote_registry(wmi, computer):
    pc=wmi.validate_pc(computer)
    try:
        result=json.loads(wmi.ps('$pc='+wmi.quote(pc)+';'+SCRIPT,timeout=30))
        if (not isinstance(result,dict) or result.get('computer','').upper()!=pc.upper()
                or result.get('service')!='RemoteRegistry' or result.get('state')!='Running'):
            raise ValueError('Remote Registry did not return a verified running state')
        return result
    except Exception as error:
        raise HTTPException(502,f'{pc}: {error}') from error


def _manage(wmi, pc, action, **parameters):
    arguments = ' '.join(f'-{key} {wmi.quote(value)}' for key, value in parameters.items())
    try:
        output = wmi.ps(f'& {{\n{MANAGE_SCRIPT}\n}} -Computer {wmi.quote(pc)} -Action {wmi.quote(action)} {arguments}', timeout=60)
        result = json.loads(output)
        if not isinstance(result, dict) or not result.get('ok'):
            raise ValueError(result.get('error', 'Invalid Windows response') if isinstance(result, dict) else 'Invalid Windows response')
        if result.get('computer', '').upper() != pc.upper():
            raise ValueError('Windows returned a different target')
        return result
    except Exception as error:
        suffix = f' Refresh services before retrying; the {action} outcome may be unknown.' if action in _OUTCOMES else ''
        if action == 'restart':
            suffix += ' The service may be stopped.'
        raise HTTPException(502, f'{pc}: {error}{suffix}') from error


def list_services(wmi, computer):
    pc = wmi.validate_pc(computer)
    result = _manage(wmi, pc, 'list')
    if not isinstance(result.get('items'), list):
        raise HTTPException(502, f'{pc}: Windows returned an invalid service list')
    return result


def _validate_result(result, pc, name, expected, action):
    outcome = result.get('outcome')
    valid = (isinstance(result.get('name'), str) and result['name'].casefold() == name.casefold()
             and outcome in _OUTCOMES[action]
             and (outcome not in _VERIFIED_STATES or result.get('state') == _VERIFIED_STATES[outcome]))
    item = result.get('item')
    if outcome == 'gone':
        valid = valid and item is None and result.get('state') == ''
    else:
        valid = valid and isinstance(item, dict)
        if isinstance(item, dict):
            valid = valid and (
                isinstance(item.get('name'), str) and item['name'].casefold() == name.casefold()
                and isinstance(item.get('identity'), str) and bool(re.fullmatch(r'[a-f0-9]{64}', item['identity']))
                and (outcome == 'changed' or item['identity'] == expected)
                and isinstance(item.get('state'), str) and item['state'] in _STATES and item['state'] == result.get('state')
                and isinstance(item.get('start_mode'), str)
                and isinstance(item.get('display_name'), str)
                and isinstance(item.get('pid'), int) and not isinstance(item['pid'], bool) and item['pid'] >= 0
                and all(isinstance(item.get('can_' + verb), bool) and isinstance(item.get(verb + '_reason'), str)
                        for verb in ('stop', 'start', 'restart')))
    if not valid:
        raise HTTPException(502, f'{pc}: Windows did not verify the service outcome. Refresh services before retrying.')


def _control_service(wmi, request, action):
    pc = wmi.validate_pc(request.computer)
    name, expected = request.name, request.expected_identity
    if (not isinstance(name, str) or not 1 <= len(name) <= 256
            or any(ord(c) < 32 for c in name) or not isinstance(expected, str)
            or not re.fullmatch(r'[a-f0-9]{64}', expected)):
        raise HTTPException(400, 'Refresh services and choose a service from the list')
    operator = wmi.identity()
    key = (pc.casefold(), name.casefold())
    with _CONTROL_REGISTRY_LOCK:
        lock = _CONTROL_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _CONTROL_LOCKS[key] = lock
    if not lock.acquire(blocking=False):
        logging.warning('Service %s conflict target=%s service=%s operator=%s', action, pc, name, operator)
        raise HTTPException(409, f'{pc}: Another action is running for this service. Refresh services before retrying.')
    try:
        result = _manage(wmi, pc, action, Name=name, ExpectedIdentity=expected)
        _validate_result(result, pc, name, expected, action)
        logging.warning('Service %s target=%s service=%s outcome=%s state=%s phase=%s operator=%s', action, pc, name, result['outcome'], result.get('state'), result.get('phase', ''), operator)
        return result
    except Exception:
        logging.exception('Service %s outcome unavailable target=%s service=%s operator=%s', action, pc, name, operator)
        raise
    finally:
        lock.release()


def stop_service(wmi, request):
    return _control_service(wmi, request, 'stop')


def start_service(wmi, request):
    return _control_service(wmi, request, 'start')


def restart_service(wmi, request):
    return _control_service(wmi, request, 'restart')
