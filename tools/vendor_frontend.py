"""Copy pinned third-party browser files from node_modules into frontend/assets.

Atlas serves everything locally (no CDN). File names carry the version, and each library's
licence is copied beside it. Run after `npm ci` when a pinned version in package.json changes.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'frontend' / 'assets'
FILES = {
    '@xterm/xterm': [('lib/xterm.js', 'xterm-{v}.js'), ('css/xterm.css', 'xterm-{v}.css'), ('LICENSE', 'xterm-LICENSE.txt')],
    '@xterm/addon-fit': [('lib/addon-fit.js', 'xterm-addon-fit-{v}.js')],
    '@xterm/addon-search': [('lib/addon-search.js', 'xterm-addon-search-{v}.js')],
    'marked': [('lib/marked.umd.js', 'marked-{v}.js'), ('LICENSE', 'marked-LICENSE.txt')],
    'dompurify': [('dist/purify.min.js', 'dompurify-{v}.js'), ('LICENSE', 'dompurify-LICENSE.txt')],
    'mermaid': [('dist/mermaid.min.js', 'mermaid-{v}.js'), ('LICENSE', 'mermaid-LICENSE.txt')],
}


def main():
    for package, files in FILES.items():
        folder = ROOT / 'node_modules' / package
        version = json.loads((folder / 'package.json').read_text(encoding='utf-8'))['version']
        for source, target in files:
            # Remove older copies of the same file so only the pinned version is served.
            for old in ASSETS.glob(target.replace('{v}', '*')):
                old.unlink()
            data = (folder / source).read_bytes()
            # Source maps are not shipped; drop the trailing reference so browsers do not request them.
            # Bytes are otherwise copied unchanged (minified code can contain unusual line separators).
            data = re.sub(rb'\n//# sourceMappingURL=[^\n]*\s*$', b'\n', data)
            (ASSETS / target.format(v=version)).write_bytes(data)
            print(package, version, '->', target.format(v=version))


if __name__ == '__main__':
    main()
