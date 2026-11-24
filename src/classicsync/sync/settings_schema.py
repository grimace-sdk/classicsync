from dataclasses import dataclass, fields

from ..i18n import _
from ..paths import plugins_directory
from .secrets import forget_secret, is_stored_secret, resolve_secret, store_secret
from .state import read_json, write_json_atomically

SETTING_TYPES = ("string", "path", "bool", "int", "choice", "list")
TRUE_WORDS = ("1", "true", "yes", "on")
FALSE_WORDS = ("0", "false", "no", "off")
LIST_SEPARATOR = ";"
GLOBAL_SETTINGS_FILE = "settings.json"
PARTNERSHIP_OPTION_KEYS = ("file_folders", "file_depth")

SOURCE_DEFAULT = "default"
SOURCE_GLOBAL = "global"
SOURCE_DEVICE = "device"


class SettingError(ValueError):
    pass


@dataclass(frozen=True)
class Setting:
    key: str
    label: str = ""
    type: str = "string"
    default: object = None
    choices: tuple = ()
    help: str = ""
    minimum: int = None
    maximum: int = None
    per_device: bool = False
    secret: bool = False

    def __post_init__(self):
        if not self.key or not isinstance(self.key, str):
            raise SettingError(_("a setting needs a key"))
        if self.type not in SETTING_TYPES:
            raise SettingError(_("setting {key} has unknown type {type!r}; use one of {types}").format(
                key=self.key, type=self.type, types=", ".join(SETTING_TYPES)))
        object.__setattr__(self, "choices", tuple(tuple(choice) if isinstance(choice, list) else choice for choice in self.choices))
        if self.type == "choice" and not self.choices:
            raise SettingError(_("choice setting {key} has no choices").format(key=self.key))
        if not self.label:
            object.__setattr__(self, "label", self.key)

    @classmethod
    def from_value(cls, value):
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            known = {field.name for field in fields(cls)}
            unknown = sorted(set(value) - known)
            if unknown:
                raise SettingError(_("setting {key} has unknown fields: {fields}").format(
                    key=value.get("key", "?"), fields=", ".join(unknown)))
            return cls(**value)
        raise SettingError(_("a settings schema entry must be a Setting or a dict, not {value!r}").format(value=value))

    def choice_values(self):
        return [choice[0] if isinstance(choice, tuple) else choice for choice in self.choices]

    def choice_labels(self):
        return [str(choice[1]) if isinstance(choice, tuple) else str(choice) for choice in self.choices]

    def choice_label(self, value):
        values = self.choice_values()
        return self.choice_labels()[values.index(value)] if value in values else str(value)

    def check_range(self, number):
        if self.minimum is not None and number < self.minimum:
            raise SettingError(_("{key} must be at least {minimum}").format(key=self.key, minimum=self.minimum))
        if self.maximum is not None and number > self.maximum:
            raise SettingError(_("{key} must be at most {maximum}").format(key=self.key, maximum=self.maximum))
        return number

    def parse(self, text):
        text = text.strip()
        if self.type in ("string", "path"):
            return text
        if self.type == "bool":
            if text.lower() in TRUE_WORDS:
                return True
            if text.lower() in FALSE_WORDS:
                return False
            raise SettingError(_("{key} must be yes or no, not {value!r}").format(key=self.key, value=text))
        if self.type == "int":
            try:
                return self.check_range(int(text))
            except ValueError:
                raise SettingError(_("{key} must be a whole number, not {value!r}").format(key=self.key, value=text)) from None
        if self.type == "list":
            return [part.strip() for part in text.split(LIST_SEPARATOR) if part.strip()]
        for value, label in zip(self.choice_values(), self.choice_labels()):
            if text == str(value) or text.lower() == label.lower():
                return value
        raise SettingError(_("{key} must be one of {choices}, not {value!r}").format(
            key=self.key, choices=", ".join(str(value) for value in self.choice_values()), value=text))

    def coerce(self, value):
        if self.secret and is_stored_secret(value):
            return value
        if self.type == "bool" and isinstance(value, bool):
            return value
        if self.type == "int" and isinstance(value, int) and not isinstance(value, bool):
            return self.check_range(value)
        if self.type == "list" and isinstance(value, (list, tuple)):
            return [str(item) for item in value]
        if self.type == "choice" and value in self.choice_values():
            return value
        if isinstance(value, str):
            return self.parse(value)
        raise SettingError(_("{key} cannot be {value!r}").format(key=self.key, value=value))

    def format(self, value):
        if value is None:
            return ""
        if self.secret:
            if is_stored_secret(value):
                return _("(saved in the keyring)")
            return _("(saved)") if value else ""
        if self.type == "bool":
            return _("yes") if value else _("no")
        if self.type == "list":
            return LIST_SEPARATOR.join(str(item) for item in value)
        if self.type == "choice":
            return self.choice_label(value)
        return str(value)


def provider_schema(provider_class):
    return [Setting.from_value(entry) for entry in getattr(provider_class, "settings_schema", None) or ()]


def schema_defaults(schema):
    return {setting.key: setting.default for setting in schema if setting.default is not None}


def parse_assignment(text):
    key, separator, value = text.partition("=")
    if not separator or not key.strip():
        raise SettingError(_("expected KEY=VALUE, not {text!r}").format(text=text))
    return key.strip(), value


def parse_assignments(schema, assignments):
    by_key = {setting.key: setting for setting in schema}
    parsed = {}
    for text in assignments:
        key, value = parse_assignment(text)
        setting = by_key.get(key)
        if setting is None and by_key:
            raise SettingError(_("unknown setting {key}; known settings: {keys}").format(key=key, keys=", ".join(by_key)))
        if not value.strip():
            parsed[key] = None
        else:
            parsed[key] = setting.parse(value) if setting else value
    return parsed


def global_settings_path(plugin_directory=None):
    return (plugin_directory or plugins_directory()) / GLOBAL_SETTINGS_FILE


def load_global_settings(provider_name, plugin_directory=None):
    stored = read_json(global_settings_path(plugin_directory), {})
    values = stored.get(provider_name) if isinstance(stored, dict) else None
    return dict(values) if isinstance(values, dict) else {}


def save_global_settings(provider_name, values, plugin_directory=None):
    path = global_settings_path(plugin_directory)
    stored = read_json(path, {})
    if not isinstance(stored, dict):
        stored = {}
    if values:
        stored[provider_name] = values
    else:
        stored.pop(provider_name, None)
    write_json_atomically(path, stored)


def apply_changes(values, changes):
    updated = dict(values)
    for key, value in changes.items():
        if value is None:
            updated.pop(key, None)
        else:
            updated[key] = value
    return updated


def partnership_values(options):
    return {"file_folders": list(options.file_folders), "file_depth": options.file_depth, **options.provider_settings}


def effective_settings(provider_class, options, plugin_directory=None):
    try:
        defaults = schema_defaults(provider_schema(provider_class))
    except SettingError:
        defaults = {}
    values = {**defaults, **load_global_settings(provider_class.name, plugin_directory), **partnership_values(options)}
    return {key: resolve_secret(value) for key, value in values.items()}


def protect_secrets(schema, changes, provider_name, scope):
    protected = dict(changes)
    for setting in schema:
        if not setting.secret or setting.key not in changes:
            continue
        if changes[setting.key] is None:
            forget_secret(provider_name, scope, setting.key)
        else:
            protected[setting.key] = store_secret(provider_name, scope, setting.key, changes[setting.key])
    return protected


def setting_sources(schema, global_values, options=None):
    device_values = {}
    if options is not None:
        device_values = dict(options.provider_settings)
        default_options = type(options)()
        device_values.update({key: getattr(options, key) for key in PARTNERSHIP_OPTION_KEYS
                              if getattr(options, key) != getattr(default_options, key)})
    rows = []
    for setting in schema:
        if setting.key in device_values:
            rows.append((setting, device_values[setting.key], SOURCE_DEVICE))
        elif setting.key in global_values:
            rows.append((setting, global_values[setting.key], SOURCE_GLOBAL))
        else:
            rows.append((setting, setting.default, SOURCE_DEFAULT))
    return rows


def apply_to_options(options, changes):
    for key, value in changes.items():
        if key in PARTNERSHIP_OPTION_KEYS:
            default = type(options)()
            setattr(options, key, getattr(default, key) if value is None else value)
        elif value is None:
            options.provider_settings.pop(key, None)
        else:
            options.provider_settings[key] = value
    return options
