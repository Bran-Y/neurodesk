"""Load one private API credential, without exposing it in notebook output."""
import getpass
import os
from pathlib import Path
import stat

KEY_ENV = 'AIGATE_API_KEY'
DEFAULT_PATH = Path(__file__).resolve().parent / '.env'


class CredentialError(ValueError):
    pass


def _valid(key):
    return (isinstance(key, str) and 1 <= len(key) <= 4096 and key.isascii()
            and not any(c.isspace() for c in key) and '\x00' not in key)


def _read_private(path):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    except FileNotFoundError:
        return None
    except OSError:
        raise CredentialError('Cannot read the private .env file; check its path and permissions.') from None
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise CredentialError('.env must be a regular file owned by this user, with mode 600.')
        data = stream.read(65537)
        if len(data) > 65536:
            raise CredentialError('.env is unexpectedly large; no credentials loaded.')
        return data


def load_api_key(path=None):
    """Return a presence flag, never the secret. Existing kernel config wins."""
    current = os.environ.get(KEY_ENV)
    if current:
        if not _valid(current):
            raise CredentialError('Invalid API key in kernel memory.')
        return True
    data = _read_private(Path(path) if path is not None else DEFAULT_PATH)
    if data is None:
        return False
    matches = []
    for line in data.splitlines():
        name, separator, value = line.partition('=')
        if separator and name.strip() == KEY_ENV:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            matches.append(value)
    if len(matches) != 1 or not _valid(matches[0]):
        raise CredentialError('.env needs exactly one valid AIGATE_API_KEY assignment.')
    os.environ[KEY_ENV] = matches[0]
    return True


def save_api_key(key, path=None):
    """Write mode 600; retain unrelated settings; never return the key."""
    if not _valid(key):
        raise CredentialError('Invalid API key; nothing saved.')
    path = Path(path) if path is not None else DEFAULT_PATH
    old = _read_private(path) or ''
    lines = [line for line in old.splitlines() if line.partition('=')[0].strip() != KEY_ENV]
    lines.append(KEY_ENV + '=' + key)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write('\n'.join(lines) + '\n')
    except OSError:
        raise CredentialError('Could not save the private .env file.') from None


if __name__ == '__main__':
    # Run in a real terminal: never accept a secret in command-line arguments.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        secret = getpass.getpass('API key for private .env (hidden): ').strip()
    save_api_key(secret)
    secret = None
    print('Private .env saved (mode 600). No API request sent.')
