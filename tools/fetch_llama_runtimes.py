"""Download the reviewed Windows archives and verify pinned upstream SHA-256 digests."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import shutil
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def fetch(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    metadata=json.loads((ROOT/'resources/llama-runtimes.json').read_text())
    for kind,asset in metadata['archives'].items():
        package=destination/(kind+'.zip')
        if not package.is_file() or hashlib.sha256(package.read_bytes()).hexdigest()!=asset['sha256']:
            temporary=package.with_suffix('.part')
            digest=hashlib.sha256()
            try:
                with urllib.request.urlopen(asset['url'],timeout=60) as response,temporary.open('wb') as out:
                    while block:=response.read(1024*1024):out.write(block);digest.update(block)
                if temporary.stat().st_size!=asset['size'] or digest.hexdigest()!=asset['sha256']:
                    raise ValueError('Runtime archive verification failed: '+kind)
                temporary.replace(package)
            finally:temporary.unlink(missing_ok=True)
        folder=destination/('llama-'+kind)
        if folder.exists():shutil.rmtree(folder)
        with zipfile.ZipFile(package) as archive:
            for info in archive.infolist():
                path=PurePosixPath(info.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in info.filename or ':' in info.filename:
                    raise ValueError('Unsafe upstream archive path')
            archive.extractall(folder)
        print('Verified',kind,asset['sha256'],flush=True)
    (destination/'RUNTIME-SOURCES.json').write_text(json.dumps(metadata,sort_keys=True,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    fetch(parser.parse_args().output)
