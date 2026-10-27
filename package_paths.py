"""Resolve the synced SharePoint package folder without storing a user's profile."""
import os
from pathlib import Path

PACKAGE_FOLDER = 'EPP_PACKAGE_REPO_BetaPackages - BetaPackages'
PLAN_FOLDER = ('PA-IT_shared', '02_Current_plan')  # The assistants' desk plan, for the live floor plan
BUSINESS_ONEDRIVE = 'OneDrive - Barclays Bank PLC'


def _registered_onedrive_roots(other_profiles=False):
    if os.name != 'nt':
        return []
    import winreg
    profiles = [(winreg.HKEY_CURRENT_USER, '')]
    if other_profiles:
        profiles = []
        try:
            with winreg.OpenKey(winreg.HKEY_USERS, '') as users:
                for index in range(winreg.QueryInfoKey(users)[0]):
                    sid = winreg.EnumKey(users, index)
                    if sid.startswith('S-1-5-21-') and not sid.endswith('_Classes'):
                        profiles.append((winreg.HKEY_USERS, sid + '\\'))
        except OSError:
            return []
    roots = []
    for hive, prefix in profiles:
        try:
            with winreg.OpenKey(hive, prefix + r'Software\Microsoft\OneDrive\Accounts') as accounts:
                for index in range(winreg.QueryInfoKey(accounts)[0]):
                    name = winreg.EnumKey(accounts, index)
                    if not name.startswith('Business'):
                        continue
                    try:
                        with winreg.OpenKey(accounts, name) as account:
                            folder, _ = winreg.QueryValueEx(account, 'UserFolder')
                            if isinstance(folder, str) and folder.strip():
                                roots.append(Path(folder))
                    except OSError:
                        continue
        except OSError:
            continue
    return roots


def _candidates(roots, parts=(PACKAGE_FOLDER,)):
    seen = set()
    for root in roots:
        for path in (root.joinpath('Shortcuts', *parts), root.joinpath(*parts)):
            key = os.path.normcase(str(path))
            if key not in seen:
                seen.add(key)
                yield path


def _accessible(path):
    try:
        return path.is_dir()
    except OSError:
        return False


def business_folder(*parts):
    """A SharePoint folder synced into business OneDrive, in Shortcuts or directly in it."""
    commercial = os.environ.get('OneDriveCommercial', '').strip()
    roots = ([Path(commercial)] if commercial else [])
    roots += _registered_onedrive_roots()
    roots.append(Path.home() / BUSINESS_ONEDRIVE)
    candidates = list(_candidates(roots, parts))
    for path in candidates:
        if _accessible(path):
            return path
    # Run-as-admin can use a different profile from the signed-in OneDrive user.
    # Only use a loaded profile's exact folder if it is unambiguous.
    shared = [path for path in _candidates(_registered_onedrive_roots(True), parts)
              if _accessible(path)]
    if len(shared) == 1:
        return shared[0]
    return candidates[0]


def default_package_repository():
    return business_folder(PACKAGE_FOLDER)


def default_plan_folder():
    return business_folder(*PLAN_FOLDER)


def package_repository(config, root):
    value = os.environ.get('WMI_PACKAGE_REPO', '').strip()
    value = value or str(config.get('package_repository') or '').strip()
    if not value:
        return default_package_repository()
    path = Path(os.path.expandvars(value)).expanduser()
    return path if path.is_absolute() else root / path
