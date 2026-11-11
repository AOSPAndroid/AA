"""Export or restore a stopped AA workspace, including consistent SQLite snapshots."""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import zipfile

from runtime_paths import paths

EPHEMERAL={'server.json','viewer-server.json','model-process.json','share-addresses.txt'}


def stopped(root):
    for name in EPHEMERAL-{'share-addresses.txt'}:
        if any(root.rglob(name)):
            raise ValueError('Stop AA before exporting or migrating. Process ownership records are still present.')


def export(root, output, database=None):
    root,output=Path(root).resolve(),Path(output).resolve()
    stopped(root)
    if output.exists() or root in output.parents:
        raise ValueError('Choose a new export file outside the runtime folder.')
    with tempfile.TemporaryDirectory(prefix='aa-export-') as tmp:
        candidate=Path(tmp)/'workspace.zip'
        with zipfile.ZipFile(candidate,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('AA-WORKSPACE.json',json.dumps({'format':1,'description':'Stopped AA runtime workspace'}))
            sources={p.relative_to(root).as_posix():p for p in root.rglob('*')}
            if database is not None:sources['office_atlas.db']=Path(database).resolve()
            for relative,item in sorted(sources.items()):
                rel=Path(relative)
                if item.is_symlink():
                    raise ValueError('Workspace exports cannot contain symbolic links.')
                if not item.is_file() or item.name in EPHEMERAL or any(p in ('locks','logs','__pycache__') for p in rel.parts) or item.name.endswith(('-wal','-shm','-journal')):
                    continue
                source=item
                if item.suffix in ('.db','.sqlite3','.sqlite'):
                    source=Path(tmp)/'snapshot.db'
                    a=sqlite3.connect(item.as_uri()+'?mode=ro',uri=True)
                    b=sqlite3.connect(source)
                    try:a.backup(b)
                    finally:a.close();b.close()
                archive.write(source,rel.as_posix())
                if source!=item:source.unlink()
        output.parent.mkdir(parents=True,exist_ok=True)
        # Do not overwrite another export created concurrently.
        with output.open('xb') as dest, candidate.open('rb') as source:shutil.copyfileobj(source,dest)


def restore(source, destination):
    destination=Path(destination).resolve()
    if destination.exists():
        raise ValueError('Restore into a new folder; an existing workspace is never overwritten.')
    with zipfile.ZipFile(source) as archive:
        if json.loads(archive.read('AA-WORKSPACE.json')).get('format')!=1:
            raise ValueError('Unsupported workspace export.')
        entries=archive.infolist()
        if len(entries)>50000 or sum(x.file_size for x in entries)>20*1024**3:
            raise ValueError('Workspace archive is too large.')
        names=set()
        for info in entries:
            # ZipInfo normalizes backslashes on Windows and truncates NULs.
            # Validate the original member name before using its normalized path.
            raw=info.orig_filename
            name=PurePosixPath(raw)
            if (name.is_absolute() or '..' in name.parts or '\\' in raw or ':' in raw or '\x00' in raw
                    or not name.parts or raw.casefold() in names or ((info.external_attr>>16)&0o170000)==0o120000
                    or name.name in EPHEMERAL):
                raise ValueError('Unsafe or duplicate workspace entry.')
            names.add(raw.casefold())
        destination.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.aa-restore-',dir=destination.parent) as tmp:
            staging=Path(tmp)/'workspace';staging.mkdir()
            for info in entries:
                if info.filename=='AA-WORKSPACE.json' or info.is_dir():continue
                target=staging/info.filename;target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(info) as src,target.open('xb') as out:shutil.copyfileobj(src,out)
            staging.rename(destination)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='action',required=True)
    backup=commands.add_parser('export');backup.add_argument('output',type=Path)
    load=commands.add_parser('import');load.add_argument('archive',type=Path);load.add_argument('--dest',type=Path,required=True)
    args=parser.parse_args()
    if args.action=='export':export(paths().root,args.output,paths().database)
    else:restore(args.archive,args.dest)


if __name__=='__main__':main()
