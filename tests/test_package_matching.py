import gzip
import io
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from backend.deploy import package_matching
from backend.inbox.inbox_analysis import analyse

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = [
    {'folder': 'Microsoft_PowerBI_Desktop_2.130', 'display_name': 'Microsoft_PowerBI_Desktop_2.130'},
    {'folder': 'Adobe_Reader_DC_24', 'display_name': 'Adobe_Reader_DC_24'},
    {'folder': 'VSCode_1.95', 'display_name': 'VSCode_1.95'},
    {'folder': 'Notepad++_8.6', 'display_name': 'Notepad++'},
    {'folder': '7-Zip', 'display_name': '7-Zip'},
    {'folder': 'Microsoft_Teams', 'display_name': 'Microsoft Teams'},
]


def suggest(body, packages=CATALOGUE):
    return [(p['folder'], p['reason'], p['matched']) for p in analyse('Request', body, packages=packages)['packages']]


class WingetAliases(unittest.TestCase):
    """Uses the shipped resources/winget_aliases.json.gz."""

    def test_aliases_from_the_windows_package_index(self):
        self.assertEqual(suggest('please install powerbi')[0][:2], ('Microsoft_PowerBI_Desktop_2.130', 'alias'))
        self.assertEqual(suggest('can I have Acrobat Reader')[0][:2], ('Adobe_Reader_DC_24', 'alias'))
        self.assertEqual(suggest('I need Visual Studio Code installed')[0], ('VSCode_1.95', 'alias', 'visual studio code'))
        self.assertEqual(suggest('please install 7zip')[0][:2], ('7-Zip', 'alias'))

    def test_close_spellings_compare_whole_words(self):
        self.assertEqual(suggest('please install acrobat reder')[0], ('Adobe_Reader_DC_24', 'spelling', 'acrobat reder'))
        self.assertEqual(suggest('can you install notpad++')[0][:2], ('Notepad++_8.6', 'spelling'))
        self.assertEqual(suggest('please install steams'), [], '"teams" must not match inside another word')

    def test_common_words_are_not_product_mentions(self):
        self.assertEqual(analyse('Help', 'my code does not compile', packages=CATALOGUE)['packages'], [])

    def test_without_rapidfuzz_exact_aliases_still_work(self):
        package_matching._phrases.cache_clear()
        with patch.object(package_matching, 'process', None), patch.object(package_matching, 'fuzz', None):
            self.assertEqual(suggest('please install powerbi')[0][:2], ('Microsoft_PowerBI_Desktop_2.130', 'alias'))
            self.assertEqual(suggest('please install acrobat reder'), [])
        package_matching._phrases.cache_clear()

    def test_shipped_alias_file_is_compact_and_attributed(self):
        path = ROOT / 'resources' / 'winget_aliases.json.gz'
        self.assertLess(path.stat().st_size, 600_000)
        document = json.loads(gzip.decompress(path.read_bytes()))
        self.assertEqual(document['licence'], 'MIT')
        self.assertIn('winget-pkgs', document['source'])
        self.assertGreater(len(document['packages']), 1000)


class BuildTool(unittest.TestCase):
    def test_builds_from_a_source_package(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import build_winget_aliases as tool
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'index.db'
            c = sqlite3.connect(db)
            c.executescript('''CREATE TABLE ids(rowid INTEGER PRIMARY KEY, id TEXT); CREATE TABLE names(rowid INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE monikers(rowid INTEGER PRIMARY KEY, moniker TEXT);
                CREATE TABLE manifest(rowid INTEGER PRIMARY KEY, id INT, name INT, moniker INT);
                INSERT INTO ids VALUES(1,'Example.Tool'); INSERT INTO names VALUES(1,'Example Tool'),(2,'Example  Tool (64-bit)');
                INSERT INTO monikers VALUES(1,'extool'),(2,''); INSERT INTO manifest VALUES(1,1,1,1),(2,1,2,2);''')
            c.commit(); c.close()
            msix = Path(tmp) / 'source.msix'
            with zipfile.ZipFile(msix, 'w') as z:
                z.write(db, 'Public/index.db')
            self.assertEqual(tool.build(tool.read_index(str(msix))), [['Example.Tool', ['Example Tool', 'Example Tool (64-bit)'], ['extool']]])


if __name__ == '__main__':
    unittest.main()
