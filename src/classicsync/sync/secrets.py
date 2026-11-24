import logging

log = logging.getLogger("classicsync.sync")

KEYRING_SERVICE = "classicsync"
KEYRING_FIELD = "keyring"


def keyring_backend():
    try:
        import keyring
        from keyring.backends import fail
    except Exception:
        return None
    try:
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
    except Exception:
        return None
    return keyring


def keyring_available():
    return keyring_backend() is not None


def account_name(provider_name, scope, key):
    return f"{provider_name}/{scope}/{key}"


def is_stored_secret(value):
    return isinstance(value, dict) and KEYRING_FIELD in value


def store_secret(provider_name, scope, key, value):
    backend = keyring_backend()
    account = account_name(provider_name, scope, key)
    if backend is None:
        return value
    try:
        backend.set_password(KEYRING_SERVICE, account, value)
    except Exception as error:
        log.warning("could not save %s in the keyring: %s", account, error)
        return value
    return {KEYRING_FIELD: account}


def forget_secret(provider_name, scope, key):
    backend = keyring_backend()
    if backend is None:
        return
    try:
        backend.delete_password(KEYRING_SERVICE, account_name(provider_name, scope, key))
    except Exception:
        pass


def resolve_secret(value):
    if not is_stored_secret(value):
        return value
    backend = keyring_backend()
    if backend is None:
        return ""
    try:
        return backend.get_password(KEYRING_SERVICE, value[KEYRING_FIELD]) or ""
    except Exception as error:
        log.warning("could not read %s from the keyring: %s", value[KEYRING_FIELD], error)
        return ""
