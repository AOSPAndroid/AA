"""Recognise software names in free text: catalogue names, winget aliases and close spellings.

Each catalogue package is linked to the same product in the offline winget index
(resources/winget_aliases.json.gz), which adds its other names and short alias, e.g.
"Microsoft_PowerBI_Desktop_2.130" gains "powerbi". Text is then matched against those phrases
exactly, or with RapidFuzz for close spellings ("acrobat reder"). Whole words are compared, so
"teams" never matches inside "steams". Without RapidFuzz installed, exact aliases still work.
"""
import gzip
import json
import re
import threading
from functools import lru_cache
from pathlib import Path

try:
    from rapidfuzz import fuzz, process
except ImportError:  # optional: close-spelling matching is skipped
    fuzz = process = None

ALIASES = Path(__file__).resolve().parents[2] / 'resources' / 'winget_aliases.json.gz'
VERSION = re.compile(r'^(?:v?\d+[a-z]?(?:\.\d+)*|\d+bit|x\d+|arm\d*)$')
NOISE = {'x64', 'x86', 'amd64', 'arm64', 'bit', 'setup', 'installer', 'install', 'msi', 'exe', 'package', 'pkg',
         'en', 'us', 'gb', 'uk', 'fr', 'de', 'version', 'latest', 'edition', 'the', 'for', 'and', 'with'}
# Monikers that are ordinary words are too ambiguous to count as a product mention on their own.
COMMON = {'code', 'mail', 'notes', 'note', 'office', 'word', 'paint', 'camera', 'photos', 'photo', 'chat', 'music',
          'video', 'player', 'browser', 'editor', 'viewer', 'reader', 'client', 'app', 'apps', 'tools', 'tool',
          'terminal', 'desktop', 'cloud', 'drive', 'sync', 'remote', 'access', 'connect', 'monitor', 'manager',
          'studio', 'search', 'files', 'file', 'shell', 'git', 'go', 'r', 'one', 'teams'}
_lock = threading.Lock()


def plain(value):
    from backend.inbox.inbox_analysis import plain as plain_text
    return plain_text(value)


def core(name):
    """Product words of a name: no versions, architectures or bracketed notes."""
    text = re.sub(r'\(.*?\)|\[.*?\]', ' ', str(name or ''))
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text.replace('_', ' ').replace('.', ' '))
    tokens = plain(text).split()
    # A leading number is part of the name ("7-Zip"), not a version.
    return ' '.join(t for i, t in enumerate(tokens) if t not in NOISE and (i == 0 or not VERSION.match(t)))


@lru_cache(maxsize=1)
def winget():
    try:
        document = json.loads(gzip.decompress(ALIASES.read_bytes()))
    except (OSError, ValueError):
        return {}
    index = {}
    for package_id, names, monikers in document.get('packages', []):
        phrases = {core(n) for n in names} | {plain(m.replace('-', ' ')) for m in monikers} | {plain(m) for m in monikers}
        tail = core(' '.join(package_id.split('.')[1:]))
        phrases |= {tail} if len(tail.split()) > 1 else set()
        phrases = {p for p in phrases if p}
        # Display names and monikers both identify the product ("vscode" -> Visual Studio Code).
        for key in {core(n) for n in names} | {plain(m) for m in monikers}:
            index.setdefault(key, set()).update(phrases)
    return {key: sorted(value) for key, value in index.items() if key}


def _link(cores, index):
    """Catalogue core name -> winget phrases, by exact core name or a very close spelling."""
    keys = list(index)
    linked = {}
    for name in cores:
        if name in index:
            linked[name] = index[name]
        elif process and len(name) >= 5:
            best = process.extractOne(name, keys, scorer=fuzz.token_sort_ratio, score_cutoff=92)
            if best:
                linked[name] = index[best[0]]
                continue
            # "adobe reader dc" is "adobe acrobat reader dc" with one word left out. Two words at least,
            # so a single word such as "office" never links to every product containing it.
            words = set(name.split())
            if len(words) < 2:
                continue
            close = [key for key, score, _ in process.extract(name, keys, scorer=fuzz.token_set_ratio, score_cutoff=100, limit=25)
                     if words <= set(key.split()) and len(set(key.split()) - words) <= 1]
            if close:
                linked[name] = index[min(close, key=lambda key: (len(key), key))]
    return linked


@lru_cache(maxsize=4)
def _phrases(catalogue):
    index = winget()
    cores = {folder: (core(display), core(folder)) for folder, display in catalogue}
    linked = _link({c for pair in cores.values() for c in pair if c}, index)
    result = {}
    for folder, display in catalogue:
        own = [c for c in cores[folder] if c]
        aliases = {a for c in own for a in linked.get(c, [])} - set(own)
        result[folder] = (own, sorted(a for a in aliases if len(a) >= 4 and a not in COMMON))
    return result


def catalogue_phrases(packages):
    """{folder: (own name phrases, alias phrases)} for a catalogue; cached per catalogue."""
    key = tuple(sorted((str(p['folder']), str(p.get('display_name') or p['folder'])) for p in packages))
    with _lock:
        return _phrases(key)


def grams(words, limit=4000):
    """Word n-grams of the text (1-4 words) plus joined forms, so "power bi" also reads as "powerbi"."""
    tokens = words.split()[:limit]
    found = {k: set() for k in range(1, 5)}
    for k in range(1, 5):
        for i in range(len(tokens) - k + 1):
            window = tokens[i:i + k]
            found[k].add(' '.join(window))
            if k > 1:
                found[1].add(''.join(window))
    return found


def alias_matches(words, packages):
    """{folder: (score, reason, matched text)} from aliases and close spellings."""
    phrases = catalogue_phrases(packages)
    text = grams(words)
    results = {}
    for folder, (own, aliases) in phrases.items():
        for alias in aliases:
            if alias in text[min(len(alias.split()), 4)]:
                results[folder] = max(results.get(folder, (0, '', '')), (1.0, 'alias', alias))
    if process:
        # Close spellings: whole-word windows of the same length, long phrases only. Bounded text keeps it fast.
        text = grams(words, limit=1500)
        for folder, (own, aliases) in phrases.items():
            for phrase in own + aliases:
                if len(phrase) < 6 or phrase in COMMON:
                    continue
                candidates = text[min(len(phrase.split()), 4)]
                if not candidates:
                    continue
                best = process.extractOne(phrase, candidates, scorer=fuzz.ratio, score_cutoff=88)
                if best and best[0] != phrase:
                    score = round(0.9 * best[1] / 100, 2)
                    results[folder] = max(results.get(folder, (0, '', '')), (score, 'spelling', best[0]))
    return results


def prewarm():
    """Load the winget index in the background so the first message opens without a pause."""
    threading.Thread(target=winget, name='atlas-winget-aliases', daemon=True).start()
