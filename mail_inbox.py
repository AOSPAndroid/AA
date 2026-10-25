"""Local Admin inbox reads and directory joins. Never registered on the LAN viewer."""
from contextlib import contextmanager
from datetime import datetime
import os
from pathlib import Path
import re
import sqlite3

from fastapi import HTTPException, Query
from directory_lookup import exact_users, linked_machines
from outlook_watcher import default_directory, status, utcnow
from notification_inbox import notification_status, source_columns


def mail_directory():
    import companion_server
    if companion_server.companion and companion_server.companion.mail_active():
        return companion_server.companion.inbox
    from inbox_control import InboxIntegration, IntegrationError
    try:
        configured = InboxIntegration().config()
        if configured:
            return Path(configured['directory']).resolve()
    except IntegrationError as error:
        raise HTTPException(503, str(error)) from error
    return Path(os.environ.get('ATLAS_MAIL_DIR') or default_directory()).expanduser().resolve()


@contextmanager
def queue_reader(directory):
    path = directory / 'inbox.sqlite3'
    connection = None
    try:
        if not path.is_file():
            yield None
            return
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        yield connection
    except sqlite3.Error as error:
        raise HTTPException(503, 'The local mail queue is unavailable. Check the configured folder and read access for the Atlas Windows account, then retry.') from error
    except PermissionError as error:
        raise HTTPException(503, 'The Atlas Windows account needs read access to the configured mail folder.') from error
    finally:
        if connection is not None:
            connection.close()


def watcher_status(directory):
    import companion_server
    if companion_server.companion and companion_server.companion.mail_active() and directory == companion_server.companion.inbox:
        return companion_server.companion.mail_status()
    try:
        current = status(directory)
    except PermissionError as error:
        raise HTTPException(503, 'The Atlas Windows account needs read access to the mail watcher status and lock files.') from error
    # A process can still hold its lock while Outlook is displaying a prompt.
    try:
        age = (utcnow() - datetime.fromisoformat(current['updated_at'])).total_seconds()
        stale = age > max(60, int(current.get('interval', 5)) * 3)
    except (KeyError, ValueError, TypeError):
        stale = bool(current['running'])
    return {**{key: current.get(key) for key in
               ('state', 'running', 'last_success_at', 'updated_at', 'detail', 'config')},
            'stale': stale, 'interval': current.get('interval', 5)}


def person(row):
    data = dict(row)
    return {key: data.get(key, '') for key in
            ('id', 'canonical_key', 'name', 'full_name', 'user_name', 'email', 'department', 'location', 'job_role')}


def match_sender(connection, message, chosen=None):
    address = message['sender_address'].strip()
    rows = exact_users(connection, address, field='email') if '@' in address else []
    basis = 'email'
    if not rows:
        basis = 'name'
        rows = exact_users(connection, message['sender_name'], field='name')
    people = [person(row) for row in rows]
    kind = basis if len(people) == 1 else 'ambiguous' if people else 'unmatched'
    selected = people[0] if len(people) == 1 else None
    if chosen is not None:
        selected = next((user for user in people if user['id'] == chosen), None)
        if selected is None:
            raise HTTPException(409, 'This person is no longer a candidate for the sender. Refresh the message.')
    return {'kind': kind, 'basis': basis if people else None, 'user': selected,
            'candidates': people, 'chosen': chosen is not None}


# Characters that text recognition (and hurried typing) confuse in hostnames: O/0, I/l/1, S/5, B/8, Z/2.
LOOKALIKE = str.maketrans({'o': '0', 'i': '1', 'l': '1', 's': '5', 'b': '8', 'z': '2'})


def lookalike_key(value):
    return str(value or '').casefold().translate(LOOKALIKE)


def mentioned_machines(connection, names):
    if not names:
        return []
    columns = 'name,name_norm,device_kind,model_id,operational_status,windows_remote_supported'
    rows = [dict(row) for row in connection.execute(
        f'SELECT {columns} FROM legacy_machines WHERE name_norm IN (%s) ORDER BY name' % ','.join('?' * len(names)), names)]
    found = {row['name_norm'] for row in rows}
    # Names with no exact match are retried with look-alike characters made equal, so a misread
    # "GBRPWMK2O88I521" still finds GBRPWMK20881521. Only machines in inventory are returned.
    missing = {lookalike_key(name): name for name in names if name not in found}
    if missing:
        connection.create_function('atlas_lookalike', 1, lookalike_key, deterministic=True)
        lengths = sorted({len(name) for name in missing.values()})
        for row in connection.execute(
                f'SELECT {columns} FROM legacy_machines WHERE length(name_norm) IN (%s) AND atlas_lookalike(name_norm) IN (%s) '
                'ORDER BY name LIMIT 20' % (','.join('?' * len(lengths)), ','.join('?' * len(missing))),
                (*lengths, *missing)):
            if row['name_norm'] not in found:
                found.add(row['name_norm'])
                rows.append({**dict(row), 'written_as': missing[lookalike_key(row['name_norm'])].upper()})
    return [{key: value for key, value in row.items() if key != 'name_norm'} for row in rows]


# People named in a message, as people write them: "Marie Dupont", "DUPONT Marie", "Dupont, Marie",
# "Marie Dupont's laptop", "Bonjour Marie Dupont". Every two- and three-word window of capitalised
# words is tried in both orders, so only names that exist in the directory come back.
NAME_WORD = r"[A-ZÀ-Þ][A-Za-zÀ-ÿ'’-]*[A-Za-zÀ-ÿ]"
NAME_RUN = re.compile(rf"{NAME_WORD}(?:(?:[ \t]+|,[ \t]*){NAME_WORD})+")
PEOPLE = 8


def name_candidates(text, limit=400):
    """{directory name_norm: name as written}."""
    found = {}
    for run in NAME_RUN.finditer(text):
        words = [re.sub(r"['’]s$", '', word) for word in re.split(r'[ \t]+|,[ \t]*', run.group(0)) if word]
        for size in (3, 2):
            for start in range(len(words) - size + 1):
                window = words[start:start + size]
                written = ' '.join(window)
                variants = [window] if size == 3 else [window, window[::-1]]
                for variant in variants:
                    found.setdefault(' '.join(variant).lower(), written)
                if size == 2:
                    found.setdefault(f'{window[1]}, {window[0]}'.lower(), written)
        if len(found) >= limit:
            break
    return found


def operator_accounts():
    """The Windows accounts running Atlas (x01426046_dsk is x01426046's admin account)."""
    accounts = set()
    for value in (os.environ.get('USERNAME'), os.environ.get('USER')):
        value = str(value or '').rsplit('\\', 1)[-1].casefold()
        if value:
            accounts |= {value, re.sub(r'[_-](dsk|adm|admin|a)$', '', value)}
    return accounts


def people_desks(connection, people):
    try:
        from desk_directory import people_desks as desks
        return desks(connection, people)
    except (sqlite3.Error, KeyError, ValueError):
        return {}


def mentioned_people(connection, text, exclude=()):
    """People the message names (full name, email address or account ID), in the order they are
    written, with their linked machines. The sender and the Atlas operator are left out. A name
    shared by several people is returned once with its candidates."""
    from clipboard_history import ACCOUNT, EMAIL
    exclude, operators = set(exclude), operator_accounts()
    keep = lambda row: row['id'] not in exclude and str(row['user_name'] or '').casefold() not in operators
    entries = {}

    def add(rows, basis, written):
        # A name that is also the sender's or the operator's (a signature, "Hi <operator>") means them.
        if not rows or not all(keep(row) for row in rows):
            return
        position = text.find(written)
        if len(rows) == 1:
            key, entry = ('user', rows[0]['id']), {**person(rows[0]), 'written': written, 'basis': basis}
        else:
            key, entry = ('name', written.casefold()), {'ambiguous': True, 'written': written, 'basis': basis,
                                                      'candidates': [person(row) for row in rows[:5]]}
        # Listed in the order of their first mention, however they were written.
        if key not in entries or 0 <= position < entries[key][0] or entries[key][0] < 0:
            entries[key] = (position, entry)

    for address in dict.fromkeys(EMAIL.findall(text)):
        add(exact_users(connection, address, field='email'), 'email', address)
    for account in dict.fromkeys(ACCOUNT.findall(text)):
        add(exact_users(connection, account), 'account', account)
    names = name_candidates(text)
    rows = []
    keys = list(names)
    for start in range(0, len(keys), 400):
        chunk = keys[start:start + 400]
        rows += connection.execute(f"SELECT * FROM legacy_users WHERE name_norm IN ({','.join('?' * len(chunk))})", chunk).fetchall()
    by_name = {}
    for row in rows:
        by_name.setdefault(row['name_norm'], []).append(row)
    for key, matches in by_name.items():
        add(matches, 'name', names[key])
    people = [entry for _, entry in sorted(entries.values(), key=lambda item: (item[0] < 0, item[0]))][:PEOPLE]
    for entry in people:
        if not entry.get('ambiguous'):
            entry['machines'] = linked_machines(connection, entry['id'])[:6]
    return people


def safely(load, label, warnings):
    # The request can still be read when the package share or knowledge store is unavailable.
    try:
        return list(load())
    except Exception as error:
        warnings.append(f'{label} unavailable: {error}')
        return []


def register(app, directory_connection, get_directory=mail_directory, packages=lambda: [], documents=lambda: []):
    @app.get('/api/inbox/arrivals')
    def arrivals(after_id: int = Query(0, ge=0)):
        # Atlas desktop alerts need counts only, never sender names or bodies.
        with queue_reader(get_directory()) as queue:
            if queue is None:
                return {'newest_id': 0, 'count': 0}
            newest = queue.execute('SELECT coalesce(max(id),0) FROM messages').fetchone()[0]
            count = queue.execute('SELECT count(*) FROM messages WHERE id>?', (after_id,)).fetchone()[0]
            return {'newest_id': newest, 'count': count}

    @app.get('/api/inbox/messages')
    def messages(after_id: int = Query(0, ge=0), before_id: int = Query(0, ge=0),
                 limit: int = Query(50, ge=1, le=100)):
        if after_id and before_id:
            raise HTTPException(400, 'Use either newer or older pagination, not both.')
        directory = get_directory()
        with queue_reader(directory) as queue:
            rows, total, newest = [], 0, 0
            if queue is not None:
                total, newest = queue.execute('SELECT count(*),coalesce(max(id),0) FROM messages').fetchone()
                where = 'WHERE id>?' if after_id else 'WHERE id<?' if before_id else ''
                parameters = [after_id or before_id] if where else []
                order = 'ASC' if after_id else 'DESC'
                rows = queue.execute('SELECT id,received_at,imported_at,sender_name,sender_address,subject,'
                                     + source_columns(queue) + ' '
                                     f'FROM messages {where} ORDER BY id {order} LIMIT ?',
                                     (*parameters, limit + 1)).fetchall()
        more = len(rows) > limit
        items = [dict(row) for row in rows[:limit]]
        if items:
            try:
                with directory_connection() as connection:
                    for item in items:
                        item['match'] = match_sender(connection, item)
            except sqlite3.Error as error:
                raise HTTPException(503, 'Atlas directory lookup is unavailable. Retry after the database is ready.') from error
        return {'items': items, 'total': total, 'newest_id': newest, 'has_more': more,
                'next_before': items[-1]['id'] if items and not after_id else None,
                'next_after': items[-1]['id'] if items and after_id else newest,
                'watcher': watcher_status(directory), 'notifications': notification_status(directory)}

    @app.get('/api/inbox/messages/{message_id}')
    def message(message_id: int, user_id: int | None = Query(None, ge=1)):
        with queue_reader(get_directory()) as queue:
            row = queue.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone() if queue else None
        if row is None:
            raise HTTPException(404, 'Message not found in the local inbox.')
        item = dict(row)
        for key, default in (('channel', 'outlook'), ('content_kind', 'mail'), ('app_name', '')):
            item.setdefault(key, default)
        # Outlook entry/store IDs are private implementation details, not browser links.
        for key in ('source', 'entry_id', 'conversation_id'):
            item.pop(key, None)
        from inbox_analysis import analyse
        warnings = []
        catalogue, knowledge = safely(packages, 'Package catalogue', warnings), safely(documents, 'Knowledge Base', warnings)
        try:
            with directory_connection() as connection:
                match = match_sender(connection, item, user_id)
                machines = linked_machines(connection, match['user']['id']) if match['user'] else []
                analysis = analyse(item.get('subject'), item.get('body'), packages=catalogue, documents=knowledge,
                                   find_machines=lambda names: mentioned_machines(connection, names),
                                   linked=[m.get('name') for m in machines])
                from inbox_analysis import latest_text
                sender = [match['user']['id']] if match['user'] else []
                analysis['people'] = mentioned_people(connection, latest_text(item.get('subject'), item.get('body')), sender)
                # Where the sender and the people named sit, from the floor plan.
                known = [user for user in [match['user'], *analysis['people']] if user and not user.get('ambiguous')]
                desks = people_desks(connection, known)
                for user in known:
                    user['desks'] = desks.get(user['canonical_key'], [])
        except sqlite3.Error as error:
            raise HTTPException(503, 'Atlas directory lookup is unavailable. Retry after the database is ready.') from error
        return {'message': item, 'match': match, 'machines': machines, 'analysis': {**analysis, 'warnings': warnings}}

    # AA's Axis chat reads the same list and detail the Live Inbox page shows (backend/axis_sources.py).
    app.state.inbox_messages, app.state.inbox_message = messages, message

    @app.get('/api/inbox/person/{user_id}')
    def person_detail(user_id: int):
        """A person's directory record, linked machines and desk for the Live Inbox request tools."""
        try:
            with directory_connection() as connection:
                row = connection.execute('SELECT * FROM legacy_users WHERE id=?', (user_id,)).fetchone()
                if row is None:
                    raise HTTPException(404, 'This person is no longer in the Atlas directory.')
                user = dict(row)
                return {'user': user, 'machines': linked_machines(connection, user_id),
                        'desks': people_desks(connection, [person(row)]).get(user['canonical_key'], [])}
        except sqlite3.Error as error:
            raise HTTPException(503, 'Atlas directory lookup is unavailable. Retry after the database is ready.') from error
