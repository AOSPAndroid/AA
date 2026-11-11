"""Build a Windows release from an explicit, reviewed runtime manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def build(llama_dir, output):
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    files=json.loads((ROOT/'resources/runtime-manifest.json').read_text())['files']
    if len(files)!=len(set(files)):
        raise ValueError('Duplicate runtime manifest entries')
    hashes={}
    for name in files:
        path=ROOT/name
        if path.is_symlink() or not path.is_file() or '..' in Path(name).parts or Path(name).is_absolute():
            raise ValueError('Invalid runtime manifest entry: '+name)
        if any(p in ('data','logs','tests','node_modules','.git','drawio') for p in Path(name).parts) or Path(name).name in ('config.json','.env','firecrawl.key') or name.endswith('.gguf'):
            raise ValueError('Forbidden runtime manifest entry: '+name)
        hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    output=Path(output)
    candidate=output.with_suffix('.building')
    try:
        with zipfile.ZipFile(candidate,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(files):
                data=(ROOT/name).read_bytes()
                if name.endswith('.bat'):data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
                hashes[name]=hashlib.sha256(data).hexdigest()
                archive.writestr('AA/'+name,data)
            for kind in ('cpu','vulkan'):
                folder=Path(llama_dir)/('llama-'+kind)
                if not any(folder.rglob('llama-server.exe')):
                    raise ValueError('Missing llama.cpp '+kind+' Windows build')
                for path in sorted(folder.rglob('*')):
                    if path.is_symlink():raise ValueError('Runtime contains a symbolic link')
                    if path.is_file():
                        name='axis/'+path.relative_to(llama_dir).as_posix()
                        data=path.read_bytes();hashes[name]=hashlib.sha256(data).hexdigest()
                        archive.writestr('AA/'+name,data)
            provenance=Path(llama_dir)/'RUNTIME-SOURCES.json'
            metadata={'BUNDLE-COMMIT.txt':(commit+'\n').encode(),'axis/LLAMA-CPP-VERSION.txt':b'llama.cpp b11815\n'}
            if provenance.is_file():metadata['axis/LLAMA-RUNTIME-SOURCES.json']=provenance.read_bytes()
            for name,data in metadata.items():
                archive.writestr('AA/'+name,data);hashes[name]=hashlib.sha256(data).hexdigest()
            archive.writestr('AA/BUNDLE-MANIFEST.json',json.dumps({'source_commit':commit,'files':hashes},sort_keys=True,indent=2)+'\n')
        with zipfile.ZipFile(candidate) as archive:
            if archive.testzip() is not None:raise ValueError('Archive failed integrity check')
            for name in ('Start AA.bat','Stop AA.bat','backend/factory.py','backend/axis_api.py','office_atlas.db'):
                if not archive.read('AA/'+name):raise ValueError('Required runtime file missing: '+name)
        candidate.replace(output)
    finally:candidate.unlink(missing_ok=True)
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n')
    print('Verified',output.name,output.stat().st_size,'bytes from',commit)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--llama-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'aa-windows.zip')
    args=parser.parse_args();build(args.llama_dir,args.output)


if __name__=='__main__':main()
