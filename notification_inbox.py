"""Read the normal user's notification companion status without writing its queue."""
from datetime import datetime
import json

from outlook_watcher import is_running, utcnow


def notification_status(directory):
    result = {'state': 'not_started', 'running': False, 'stale': False,
              'last_success_at': None, 'detail': '', 'captured': 0,
              'teams_seen': 0, 'outlook_seen': 0, 'outlook_enabled': False}
    path = directory / 'notifications-status.json'
    try:
        if path.stat().st_size > 65536:
            raise ValueError('Oversized status')
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError('Invalid status')
        result.update({key: data[key] for key in result if key in data})
        result['running'] = is_running(directory, 'notifications.lock')
        age = (utcnow() - datetime.fromisoformat(data['updated_at'])).total_seconds()
        result['stale'] = result['running'] and (age > 30 or age < -60)
        if not result['running']:
            result['state'] = 'stopped'
    except FileNotFoundError:
        pass
    except PermissionError:
        result.update(state='error', detail='Atlas needs read access to the notification status and lock files.')
    except (ValueError, TypeError, KeyError, OSError):
        result.update(state='error', detail='The notification listener status is unavailable. Reopen the listener.')
    return result


def source_columns(connection):
    """Old queues remain readable before either collector runs its migration."""
    columns = {row[1] for row in connection.execute('PRAGMA table_info(messages)')}
    source = ','.join(name if name in columns else f"'{default}' AS {name}"
                      for name, default in (('channel', 'outlook'), ('content_kind', 'mail'), ('app_name', '')))
    excerpt = "CASE WHEN content_kind='notification' THEN substr(body,1,180) ELSE '' END" if 'content_kind' in columns else "''"
    return source + ',' + excerpt + ' AS preview'
