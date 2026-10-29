"""Conservative, typed identities shared by imports and directory queries."""
import json
import re
from collections import defaultdict

MATCHING_VERSION = '3'
EMPTY_IDENTITIES = frozenset(('', 'none', 'unknown', 'n/a', 'no user', 'no brid', '0',
                              '(empty)', 'empty', 'null', 'unassigned', 'not assigned', '-', 'na', 'not supplied'))


def key(value):
    return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()


def identifier(value):
    return key(value).rsplit('\\', 1)[-1]


def login_keys(value):
    """G-number aliases do not merge separate exported G and X identities."""
    normalized = key(value); account = identifier(value)
    aliases = {normalized, account} - EMPTY_IDENTITIES
    if re.fullmatch(r'g[0-9]+', account):
        windows = 'x' + account[1:]; aliases.add(windows)
        if '\\' in normalized:
            aliases.add(normalized.rsplit('\\', 1)[0] + '\\' + windows)
    return aliases


class IdentityIndex(defaultdict):
    def __init__(self, accounts_only=False):
        super().__init__(set)
        self.accounts_only = accounts_only
        self.accounts = defaultdict(set)
        self.bare = defaultdict(set)
        self.domains = defaultdict(set)
        self.identities = defaultdict(set)
        self.emails = defaultdict(set)
        self.employees = defaultdict(set)
        self.names = defaultdict(set)

    def account(self, uid, value):
        text = key(value)
        if text in EMPTY_IDENTITIES:
            return
        if '@' in text:
            if not self.accounts_only: self.identity(uid, text, 'email')
            self.accounts[text].add(uid)
            if '\\' not in text: self.bare[text].add(uid)
            return
        domain, sep, _ = text.rpartition('\\')
        if sep and domain:
            self.domains[uid].add(domain)
        for alias in login_keys(text):
            if not self.accounts_only: self[alias].add(uid)
            if '\\' in alias:
                self.accounts[alias].add(uid)
            else:
                self.bare[alias].add(uid)

    def identity(self, uid, value, kind=None):
        text = key(value)
        if text not in EMPTY_IDENTITIES:
            self.identities[text].add(uid); self[text].add(uid)
            if kind == 'email': self.emails[text].add(uid)
            if kind == 'employee': self.employees[text].add(uid)


def build_index(c, *, canonical=False, include_names=True, accounts_only=False):
    index = IdentityIndex(accounts_only=accounts_only)
    columns = {r[1] for r in c.execute('pragma table_info(users)')}
    numeric_column = 'id' if 'id' in columns else 'rowid'
    canonical_column = 'canonical_key' if 'canonical_key' in columns else numeric_column
    by_id = {}; primary_domains = {}
    for row in c.execute('select '+numeric_column+',' + canonical_column + ',user_id,email,employee_number,full_name from users'):
        numeric, stable, login, email, employee, name = row
        uid = stable if canonical else numeric; by_id[numeric] = uid
        index.account(uid, login)
        if key(login) not in EMPTY_IDENTITIES:
            primary_domains[uid] = {key(login).rsplit('\\',1)[0]} if '\\' in key(login) else set()
        if not accounts_only:
            index.identity(uid, stable if 'canonical_key' in columns else '')
            index.identity(uid, email, 'email')
            index.identity(uid, employee, 'employee')
        if include_names and not accounts_only and key(name) not in EMPTY_IDENTITIES:
            index.names[key(name)].add(uid)
    if c.execute("select 1 from sqlite_master where type='table' and name='user_aliases'").fetchone():
        alias_columns = {r[1] for r in c.execute('pragma table_info(user_aliases)')}
        value_column = 'alias_value' if 'alias_value' in alias_columns else 'alias_norm'
        for numeric, typ, value in c.execute('select user_id_ref,alias_type,' + value_column + " from user_aliases where alias_type not in ('matching_account','matching_identity','matching_email','matching_employee')"):
            uid = by_id.get(numeric)
            if uid is None: continue
            if typ in ('user_id', 'login', 'windows_login', 'account'):
                index.account(uid, value)
            elif not accounts_only and typ in ('email', 'employee_number', 'employee_id', 'brid', 'canonical_key', 'upn', 'user_principal_name'):
                index.identity(uid, value, 'email' if typ in ('email','upn','user_principal_name') else 'employee' if typ in ('employee_number','employee_id','brid') else None)
            elif typ == 'name' and include_names and not accounts_only and key(value) not in EMPTY_IDENTITIES:
                index.names[key(value)].add(uid)
    index.domains.update(primary_domains)
    return index


def account_candidates(index, value):
    text = key(value)
    if text in EMPTY_IDENTITIES:
        return set()
    if '@' in text:
        return set(index.accounts.get(text, ()))
    domain, separator, account = text.rpartition('\\')
    if not separator:
        return set(index.bare.get(text, ()))
    exact = index.accounts.get(text)
    if exact:
        return set(exact)
    return {uid for uid in index.bare.get(account, ())
            if not index.domains.get(uid) or domain in index.domains[uid]}


def candidates(index, value, *, allow_names=True):
    text = key(value)
    if text in EMPTY_IDENTITIES: return set()
    if not isinstance(index, IdentityIndex):
        return set(index.get(text, ()))
    ids = account_candidates(index, text)
    if '\\' not in text: ids |= set(index.identities.get(text, ()))
    if ids or not allow_names or '\\' in text or '@' in text:
        return ids
    return set(index.names.get(text, ()))


def refresh_account_aliases(c, index):
    """Persist derived accounts for indexed reads; raw export aliases stay intact."""
    columns = {r[1] for r in c.execute('pragma table_info(user_aliases)')}
    if not {'alias_value', 'alias_norm', 'alias_type', 'user_id_ref'} <= columns:
        return
    c.execute("delete from user_aliases where alias_type in ('matching_account','matching_identity','matching_email','matching_employee')")
    # Repeating every primary identity at global scale adds millions of rows.
    # Keep only additional derived or casefold-normalized aliases; existing
    # typed raw aliases and indexed primary columns already cover the others.
    specifications = (
        ('matching_account', (index.accounts,index.bare), 'u.user_id_norm=?', 1,
         "'user_id','login','windows_login','account'"),
        ('matching_identity', (index.identities,), '(u.canonical_key=? or u.email_norm=? or lower(u.employee_number)=?)', 3,
         "'email','upn','user_principal_name','employee_number','employee_id','brid','canonical_key'"),
        ('matching_email', (index.emails,), 'u.email_norm=?', 1, "'email','upn','user_principal_name'"),
        ('matching_employee', (index.employees,), 'lower(u.employee_number)=?', 1, "'employee_number','employee_id','brid'"),
    )
    for typ,sources,condition,parameter_count,raw_types in specifications:
        sql = """insert or ignore into user_aliases(user_id_ref,alias_type,alias_value,alias_norm)
                 select ?,?,?,? where not exists(select 1 from users u where u.id=? and """+condition+""" )
                 and not exists(select 1 from user_aliases a where a.user_id_ref=? and a.alias_norm=?
                                and a.alias_type in ("""+raw_types+'))'
        c.executemany(sql, ((uid,typ,alias,alias,uid,*((alias,)*parameter_count),uid,alias)
                           for source in sources for alias,ids in source.items() for uid in ids))
    if c.execute("select 1 from sqlite_master where type='table' and name='metadata'").fetchone():
        c.execute('insert or replace into metadata(key,value) values(?,?)', ('matching_accounts_version', MATCHING_VERSION))


def rebuild_links(c, *, preserve_manual=False):
    index = build_index(c)
    refresh_account_aliases(c, index)
    if preserve_manual:
        # Unknown/manual provenance is retained rather than guessed.
        c.execute("""delete from assignments where
          (relationship_type='assigned_to' and source_value=(select assigned_to from machines where id=machine_id)) or
          (relationship_type='last_logon_user' and source_value=(select last_logon_user from machines where id=machine_id))""")
    else:
        c.execute('delete from assignments')
    protected = {tuple(row) for row in c.execute('select machine_id,relationship_type from assignments')} if preserve_manual else set()
    result = {'linked': 0, 'ambiguous': 0, 'unmatched': 0,
              'fields': {kind: {'linked': 0, 'ambiguous': 0, 'unmatched': 0, 'identifier_matches': 0, 'name_matches': 0} for kind in ('assigned_to', 'last_logon_user')},
              'examples': []}
    for mid, assigned, logged in c.execute('select id,assigned_to,last_logon_user from machines'):
        for kind, value in [('assigned_to', assigned), ('last_logon_user', logged)]:
            if key(value) in EMPTY_IDENTITIES or (mid, kind) in protected: continue
            authoritative = candidates(index, value, allow_names=False)
            # Historical exports also record a display name in last-logon.
            # Unique exact names stay inventory evidence; a qualified account
            # or email can never fall through to a name, nor can ambiguity.
            ids = authoritative or candidates(index, value)
            status = 'linked' if len(ids) == 1 else 'ambiguous' if ids else 'unmatched'
            if status == 'linked':
                result['fields'][kind]['identifier_matches' if authoritative else 'name_matches'] += 1
                c.execute('insert or ignore into assignments(user_id_ref,machine_id,relationship_type,source_value) values(?,?,?,?)',
                          (next(iter(ids)), mid, kind, value))
            elif len(result['examples']) < 20:
                result['examples'].append({'machine_id': mid, 'field': kind, 'value': value,
                                           'status': status, 'matches': sorted(ids)[:20]})
            result[status] += 1; result['fields'][kind][status] += 1
    if c.execute("select 1 from sqlite_master where type='table' and name='metadata'").fetchone():
        c.execute('insert or replace into metadata(key,value) values(?,?)', ('matching_diagnostics', json.dumps(result)))
    return {name: result[name] for name in ('linked', 'ambiguous', 'unmatched')}
