"""Build the Windows archive from tracked source and downloaded llama.cpp builds."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--llama-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'aa-windows.zip')
    args = parser.parse_args()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    excluded = ('.github/', 'tests/', 'axis/tests/', 'tools/', 'frontend/react/')
    with zipfile.ZipFile(args.output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in tracked:
            if not name or name.startswith(excluded) or name in ('AGENTS.md', '.gitignore', '.gitattributes', 'package-lock.json'):
                continue
            data = (ROOT / name).read_bytes()
            if name.endswith('.bat'):
                data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            archive.writestr('AA/' + name, data)
        for kind in ('cpu', 'vulkan'):
            folder = args.llama_dir / ('llama-' + kind)
            if not any(folder.rglob('llama-server.exe')):
                raise SystemExit('Missing llama.cpp ' + kind + ' Windows build')
            for path in folder.rglob('*'):
                if path.is_file():
                    archive.write(path, 'AA/axis/' + path.relative_to(args.llama_dir).as_posix())
        archive.writestr('AA/BUNDLE-COMMIT.txt', commit + '\n')
        archive.writestr('AA/axis/LLAMA-CPP-VERSION.txt', 'llama.cpp b11815\n')
    with zipfile.ZipFile(args.output) as archive:
        assert archive.testzip() is None
        required = ('Start AA.bat', 'Stop AA.bat', 'aa_launcher.py', 'backend/axis_api.py',
                    'backend/axis_operations.py', 'backend/axis_sources.py', 'frontend/assets/axis-chat.js',
                    'atlas/official-index.html', 'axis/agent.py', 'axis/aa_client.py', 'axis/start.py', 'axis/join_model.py', 'axis/Join Model.bat',
                    'axis/models.json', 'axis/skill_library.py', 'axis/skills/pc-health/SKILL.md',
                    'axis/skills/package-deployment/SKILL.md', 'office_atlas.db')
        for name in required:
            assert archive.read('AA/' + name), name
        assert not any(name.endswith('.gguf') or Path(name).name in ('firecrawl.key', '.env', 'config.json') for name in archive.namelist())
        assert archive.read('AA/BUNDLE-COMMIT.txt').decode().strip() == commit
    checksum = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(args.output.suffix + '.sha256').write_text(checksum + '  ' + args.output.name + '\n')
    print('Verified', args.output.name, args.output.stat().st_size, 'bytes from', commit)


if __name__ == '__main__':
    main()
