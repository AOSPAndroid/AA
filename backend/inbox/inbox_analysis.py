"""Rule-based reading of an incoming support message. Suggestions only.

Recognises software requests (install, uninstall, repair) and common issue
categories in English and French, matches package names from the catalogue,
finds inventory machine names written in the text and ranks Knowledge Base
documents. Nothing here contacts a machine or starts an action; the Live Inbox
offers buttons that use the normal Atlas tools and confirmations.
"""
import re
import unicodedata

# Quoted history below these lines belongs to earlier messages in the thread.
REPLY_MARKERS = re.compile(
    r'^\s*(?:-{2,}\s*original message\s*-{2,}|from:\s|de\s?:\s|sent:\s|envoy[eé]\s?:\s|on .{4,80} wrote:|le .{4,80} a [eé]crit\s?:|_{8,})',
    re.I | re.M)

# Phrases are matched as whole words after accents and punctuation are removed.
ACTIONS = (
    ('Uninstall', ('uninstall', 'remove the application', 'remove the app', 'remove the software', 'desinstaller',
                   'desinstallation', 'supprimer le logiciel', 'supprimer l application')),
    ('Repair', ('reinstall', 're install', 'repair', 'reinstaller', 'reinstallation', 'reparer', 'reparation')),
    ('Install', ('install', 'installed', 'installing', 'installation', 'installer', 'need access to the application',
                 'can i have', 'could i have', 'can i get', 'could i get', 'request software', 'software request',
                 'new software', 'download', 'telecharger', 'logiciel', 'besoin de l application', 'besoin du logiciel',
                 'pourriez vous installer', 'pouvez vous installer', 'mettre en place')),
)

# Tools are Live Inbox actions: health, performance, reboot, user-groups, machine-groups.
CATEGORIES = (
    ('slow', 'Slow or freezing PC', ('slow', 'very slow', 'freezing', 'freezes', 'frozen', 'hangs', 'hanging', 'lag',
                                     'lagging', 'not responding', 'takes forever', 'high cpu', 'lent', 'lente',
                                     'lenteur', 'lenteurs', 'fige', 'bloque', 'rame', 'ne repond pas'),
     ('performance', 'health', 'reboot')),
    ('crash', 'Application error or crash', ('crash', 'crashes', 'crashed', 'crashing', 'error', 'error message',
                                             'not working', 'doesnt work', 'does not work', 'wont open', 'will not open',
                                             'cannot open', 'cant open', 'stopped working', 'plante', 'erreur',
                                             'ne fonctionne pas', 'ne marche pas', 'ne s ouvre pas'),
     ('health', 'reboot')),
    ('outlook', 'Outlook or email', ('outlook', 'mailbox', 'shared mailbox', 'email not', 'emails not', 'cannot send',
                                     'cannot receive', 'calendar', 'boite mail', 'messagerie', 'boite aux lettres'),
     ('user-groups', 'health')),
    ('teams', 'Teams', ('teams', 'microsoft teams', 'teams call', 'teams meeting'), ('health', 'reboot')),
    ('network', 'Network, VPN or Wi-Fi', ('vpn', 'network', 'wifi', 'wi fi', 'internet', 'no connection',
                                         'cannot connect', 'cant connect', 'disconnected', 'reseau', 'connexion',
                                         'pas de connexion', 'citrix'),
     ('health', 'machine-groups')),
    ('printer', 'Printing', ('print', 'printer', 'printing', 'cannot print', 'imprimante', 'imprimer', 'impression'),
     ('health', 'user-groups')),
    ('account', 'Password, MFA or locked account', ('password', 'locked out', 'account locked', 'locked account',
                                                    'lockout', 'mfa', 'authenticator', 'reset my password',
                                                    'mot de passe', 'compte bloque', 'compte verrouille', 'verrouille'),
     ('user-groups',)),
    ('access', 'Access or permissions', ('access denied', 'permission', 'permissions', 'no access', 'need access',
                                         'request access', 'shared drive', 'shared folder', 'sharepoint', 'acces',
                                         'droits', 'dossier partage', 'lecteur reseau'),
     ('user-groups', 'machine-groups')),
    ('disk', 'Disk space', ('disk full', 'disk space', 'storage full', 'low disk', 'no space', 'out of space',
                            'espace disque', 'disque plein'),
     ('health',)),
    ('hardware', 'Screen, dock or peripherals', ('screen', 'monitor', 'second screen', 'display', 'dock',
                                                 'docking station', 'keyboard', 'mouse', 'headset', 'webcam', 'camera',
                                                 'ecran', 'clavier', 'souris', 'casque'),
     ('health', 'reboot')),
)

# Words that describe packaging rather than the product.
GENERIC = {'x64', 'x86', 'amd64', 'win', 'win64', 'win32', 'windows', 'en', 'us', 'fr', 'gb', 'uk', 'setup',
           'install', 'installer', 'client', 'app', 'apps', 'application', 'edition', 'version', 'latest', 'msi',
           'exe', 'package', 'pkg', 'bit', 'desktop', 'the', 'for', 'and', 'with', 'plugin', 'addin', 'add', 'in', 'tool', 'tools'}
VENDORS = {'microsoft', 'ms', 'adobe', 'google', 'oracle', 'ibm', 'citrix', 'cisco', 'mozilla', 'apple', 'sap',
           'autodesk', 'jetbrains', 'vmware', 'inc', 'ltd'}
# Candidates only: every name is checked against inventory before it is shown.
HOSTNAME = re.compile(r'(?<![A-Za-z0-9_-])([A-Za-z][A-Za-z0-9-]{4,29})(?![A-Za-z0-9_-])')


def plain(value):
    """Lower-case words separated by single spaces, without accents or punctuation."""
    text = unicodedata.normalize('NFKD', str(value or '').casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return ' '.join(re.sub(r"[^a-z0-9]+", ' ', text.replace("'", '')).split())


def latest_text(subject, body):
    """Subject and the newest part of the body, without quoted earlier messages."""
    body = str(body or '')[:20000]
    marker = REPLY_MARKERS.search(body)
    if marker and marker.start() > 0:
        body = body[:marker.start()]
    return f'{subject or ""}\n{body}'


def contains(words, phrase):
    return f' {phrase} ' in f' {words} '


def package_tokens(*names):
    tokens = []
    for name in names:
        for token in plain(re.sub(r'([a-z])([A-Z])', r'\1 \2', str(name or ''))).split():
            if token in GENERIC or re.fullmatch(r'v?\d+[a-z]?', token) or token in tokens:
                continue
            tokens.append(token)
    return tokens


def score_package(words, package):
    tokens = package_tokens(package.get('display_name'), package.get('folder'))
    if not tokens:
        return 0.0
    weight = lambda t: 0.25 if t in VENDORS else 0.5 if len(t) <= 2 else 1.0
    present = [t for t in tokens if contains(words, t)]
    # At least one distinctive product word must appear; vendors and short tokens alone are not enough.
    if not any(t not in VENDORS and len(t) >= 3 for t in present):
        return 0.0
    return sum(map(weight, present)) / sum(map(weight, tokens))


def match_packages(words, packages, limit=5):
    from backend.deploy.package_matching import alias_matches
    packages = list(packages)
    extra = alias_matches(words, packages) if packages else {}
    scored = []
    for package in packages:
        score, reason, matched = score_package(words, package), 'name', ''
        alias_score, alias_reason, alias_text = extra.get(package['folder'], (0, '', ''))
        if alias_score > score:
            score, reason, matched = alias_score, alias_reason, alias_text
        if score >= 0.4:
            scored.append((score, len(package_tokens(package.get('display_name'))), package, reason, matched))
    scored.sort(key=lambda row: (-row[0], -row[1], str(row[2].get('display_name') or row[2].get('folder')).casefold()))
    return [{'folder': p['folder'], 'display_name': p.get('display_name') or p['folder'], 'score': round(s, 2),
             'reason': reason, 'matched': matched} for s, _, p, reason, matched in scored[:limit]]


def hostname_candidates(text):
    seen = []
    for match in HOSTNAME.finditer(str(text or '')):
        value = match.group(1).casefold()
        # Names need a digit, or a numeric-looking last part that OCR read as letters ("LAPTOP-OOOl").
        numeric = any(c.isdigit() for c in value) or re.search(r'-[0-9oil]{2,}$', value)
        if numeric and 6 <= len(value) <= 30 and value not in seen:
            seen.append(value)
    return seen[:30]


def rank_documents(words, documents, terms, limit=3, categories=()):
    results = []
    for document in documents:
        title, notes = plain(document.get('title')), plain(document.get('notes'))
        score = sum(3 for term in terms if contains(title, term)) + sum(1 for term in terms if contains(notes, term))
        # An article written for this kind of issue ranks first.
        score += 5 * len(set(document.get('categories') or ()) & set(categories))
        if score:
            results.append((score, document))
    results.sort(key=lambda row: (-row[0], str(row[1].get('title', '')).casefold()))
    return [{'id': d['id'], 'title': d.get('title') or 'Untitled document'} for _, d in results[:limit]]


FILLER = {'please', 'pls', 'the', 'a', 'an', 'on', 'onto', 'my', 'me', 'for', 'to', 'it', 'this', 'that', 'new',
          'latest', 'version', 'of', 'software', 'application', 'app', 'program', 'tool', 'le', 'la', 'les', 'l', 'de',
          'du', 'des', 'un', 'une', 'sur', 'mon', 'ma', 'pour', 'svp', 'stp', 'merci', 'thanks', 'thank', 'you', 'hi',
          'hello', 'bonjour', 'could', 'can', 'would', 'you', 'kindly', 'also', 'and', 'et', 'logiciel'}


REQUEST_WORDS = {word for _, phrases in ACTIONS for phrase in phrases for word in phrase.split()}


def search_hint(words, phrases):
    """A few words after the request verb, e.g. "install foo bar please" -> "foo bar"."""
    tokens = words.split()
    for phrase in phrases:
        size = len(phrase.split())
        for i in range(len(tokens) - size + 1):
            if tokens[i:i + size] == phrase.split():
                hint = []
                for token in tokens[i + size:i + size + 10]:
                    if token in FILLER or token in REQUEST_WORDS:
                        if hint:
                            break
                        continue
                    hint.append(token)
                    if len(hint) == 3:
                        break
                if hint:
                    return ' '.join(hint)
    return ''


def analyse(subject, body, *, packages=(), documents=(), find_machines=lambda names: [], linked=()):
    text = latest_text(subject, body)
    found = list(find_machines(hostname_candidates(text)))
    # Machine names and email addresses are not product names: "EXAMPLE-DESKTOP-02" or
    # "alex@example.test" must not suggest "Example App".
    for machine in found:
        for written in {str(machine.get('name', '')), str(machine.get('written_as') or '')} - {''}:
            text = re.sub(re.escape(written), ' ', text, flags=re.I)
    text = re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', ' ', text)
    words = plain(text)
    action = next((name for name, phrases in ACTIONS if any(contains(words, p) for p in phrases)), None)
    categories = []
    for key, label, phrases, tools in CATEGORIES:
        hits = [p for p in phrases if contains(words, p)]
        if hits:
            categories.append({'id': key, 'label': label, 'matched': hits[:5], 'tools': list(tools)})
    categories.sort(key=lambda c: -len(c['matched']))
    suggestions = match_packages(words, packages)
    if not action:
        # Without a request verb, only a near-complete product name is worth offering (as a repair).
        suggestions = [p for p in suggestions if p['score'] >= (0.75 if categories else 0.99)]
        if suggestions and categories:
            action = 'Repair'
    if action and not suggestions and not categories and action != 'Install':
        action = None
    kind = 'software' if action and (suggestions or not categories) else 'issue' if categories else 'other'
    if kind != 'software':
        action = None
    tools = []
    for category in categories:
        tools += [t for t in category['tools'] if t not in tools]
    linked_names = {str(n).casefold() for n in linked if n}
    mentioned = []
    for machine in found:
        mentioned.append({**machine, 'linked': str(machine.get('name', '')).casefold() in linked_names})
    terms = [t for c in categories for t in c['matched']] + [t for p in suggestions[:2] for t in package_tokens(p['display_name'])]
    hint = search_hint(words, dict(ACTIONS)[action]) if kind == 'software' and not suggestions else ''
    return {'kind': kind, 'action': action, 'packages': suggestions, 'search': hint, 'categories': categories, 'tools': tools,
            'machines': mentioned, 'knowledge': rank_documents(words, documents, list(dict.fromkeys(terms)),
                                                      categories=[c['id'] for c in categories])}
