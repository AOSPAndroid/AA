"""Package metadata and a bounded metadata-only filesystem inspection."""
import os,time
from datetime import datetime,timezone
from pathlib import Path

SCHEMA='''create table if not exists package_catalog(
 repository text not null,folder text not null,display_name text not null default '',
 version text not null default '',revision integer not null default 1,updated_at text not null,
 primary key(repository,folder))'''

def inspect_package(root,limit=10000,seconds=4):
 """Does not open installers or modify OneDrive attributes. Never promises offline readiness."""
 root=Path(root).resolve();started=time.monotonic();scripts={k:[] for k in ('Install','Uninstall','Repair')}
 result={'scripts':scripts,'files_checked':0,'recall_files':0,'bytes':0,'complete':True,'errors':[],'checked_at':datetime.now(timezone.utc).isoformat()}
 pending=[root]
 while pending:
  folder=pending.pop()
  try:
   if folder.stat().st_file_attributes & (0x1000|0x400000):
    result['recall_files']+=1;result['complete']=False;continue
  except AttributeError:pass
  except OSError:result['complete']=False;result['errors'].append('Folder attributes unavailable');continue
  try:
   with os.scandir(folder) as entries:
    for entry in entries:
     if result['files_checked']>=limit or time.monotonic()-started>seconds:
      result['complete']=False;pending=[];break
     p=Path(entry.path)
     try:
      if entry.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()):
       result['complete']=False;continue
      if entry.is_dir(follow_symlinks=False):pending.append(p);continue
      stat=entry.stat(follow_symlinks=False);result['files_checked']+=1;result['bytes']+=stat.st_size
      if getattr(stat,'st_file_attributes',0)&(0x1000|0x400000):result['recall_files']+=1
      if p.suffix.lower() in ('.ps1','.vbs'):
       for action,suffix in [('Install',('_i','_install','_installs')),('Uninstall',('_u','_uninstall','_uninstalls')),('Repair',('_r','_repair','_repairs'))]:
        if p.stem.lower().endswith(suffix):scripts[action].append(str(p.relative_to(root)))
     except OSError:result['complete']=False;result['errors'].append('Some file attributes unavailable')
  except OSError:result['complete']=False;result['errors'].append('Some folders could not be read')
 for values in scripts.values():values.sort(key=str.casefold)
 result['errors']=sorted(set(result['errors']))
 result['availability']='Download needed' if result['recall_files'] else 'Check incomplete' if not result['complete'] else 'No recall flags detected' if os.name=='nt' else 'Offline status unverified'
 result['availability_note']='Windows file attributes are a snapshot, not a guarantee of offline installation. External script dependencies are not checked.'
 return result
