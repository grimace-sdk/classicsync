from dataclasses import dataclass, field
from pathlib import Path

from ..rapi.client import (
    HKEY_CLASSES_ROOT, HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, HKEY_USERS, REG_DWORD, REG_MULTI_SZ, REG_SZ, RapiError,
)
from .package import ARM_PROCESSORS, MIPS_PROCESSORS, SH3_PROCESSORS, SH4_PROCESSORS, InstallError

DEFAULT_INSTALL_DIRECTORY = "\\Program Files\\Accessories"
INSTALL_INF_NAME = "Install.inf"
APPS_KEY = "SOFTWARE\\Apps"
SHARED_KEY = "SOFTWARE\\Apps\\Shared"
UNLOAD_DIRECTORY = "\\Windows"
UNLOAD_EXTENSION = ".unload"
UNLOAD_PROGRAM = "\\Windows\\Unload.exe"
HOME_KEY = "~"
INSTALL_PATH_MACRO = "%P"

ROOT_KEYS = {
    "HKEY_LOCAL_MACHINE": (HKEY_LOCAL_MACHINE, "l"),
    "HKEY_CURRENT_USER": (HKEY_CURRENT_USER, "c"),
    "HKEY_USERS": (HKEY_USERS, "u"),
    "HKEY_CLASSES_ROOT": (HKEY_CLASSES_ROOT, "r"),
}

ARGUMENT_COUNTS = {
    "copy": (3, 3),
    "copyshared": (3, 3),
    "mkdir": (1, 1),
    "rm": (1, None),
    "createshortcut": (4, 4),
    "regkeycreate": (3, 3),
    "regvaluedelete": (3, 3),
    "regstring": (5, 5),
    "regstringmulti": (5, 5),
    "regint": (5, 5),
    "remoteexec": (1, 2),
    "execonunload": (1, 1),
    "appendtounload": (1, 1),
    "prependtounload": (1, 1),
    "exit": (0, None),
}

PROCESSOR_SUFFIXES = (
    (MIPS_PROCESSORS, ("mips", "mip")),
    (SH3_PROCESSORS, ("sh3",)),
    (SH4_PROCESSORS, ("sh4",)),
    (ARM_PROCESSORS, ("arm", "strongarm", "sa1100")),
)

ESCAPES = {'"': '"', "0": "\0", "\\": "\\", "n": "\n"}


@dataclass
class LoadCommand:
    name: str
    arguments: list
    line_number: int

    @property
    def key(self):
        return self.name.lower()


@dataclass
class LoadResult:
    app_name: str
    install_directory: str
    unload_path: str = ""
    errors: list = field(default_factory=list)

    @property
    def succeeded(self):
        return not self.errors


def tokenize_load_line(line):
    tokens = []
    position = 0
    length = len(line)
    while position < length:
        while position < length and line[position].isspace():
            position += 1
        if position >= length or line.startswith("//", position):
            break
        token = []
        if line[position] == '"':
            position += 1
            while position < length and line[position] != '"':
                character = line[position]
                if character == "\\" and position + 1 < length and line[position + 1] in ESCAPES:
                    position += 1
                    character = ESCAPES[line[position]]
                token.append(character)
                position += 1
            position += 1
        else:
            while position < length and not line[position].isspace():
                token.append(line[position])
                position += 1
        tokens.append("".join(token))
    return tokens


def parse_load_script(text):
    commands = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        tokens = tokenize_load_line(line)
        if tokens:
            commands.append(LoadCommand(tokens[0], tokens[1:], line_number))
    return commands


def read_install_inf(directory):
    values = {}
    path = find_case_insensitive(Path(directory), INSTALL_INF_NAME)
    if path is None:
        return values
    for line in path.read_bytes().decode("cp1252", errors="replace").splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key.strip().lower() in ("appname", "apptitle", "installdir"):
            values[key.strip().lower()] = value.strip()
    return values


def find_case_insensitive(directory, name):
    try:
        for entry in directory.iterdir():
            if entry.name.lower() == name.lower() and entry.is_file():
                return entry
    except OSError:
        pass
    return None


def processor_suffixes(processor_type):
    for family, suffixes in PROCESSOR_SUFFIXES:
        if processor_type in family:
            return suffixes
    return ("mips",)


def join_device_path(directory, name):
    if not name:
        return directory
    return directory.rstrip("\\") + "\\" + name


def strip_trailing_separators(path):
    stripped = path.rstrip("\\")
    return stripped or "\\"


class UnloadScript:
    def __init__(self):
        self.lines = []

    def prepend(self, record):
        self.lines.insert(0, record)

    def append(self, record):
        self.lines.append(record)

    def text(self):
        return "".join(line + "\n" for line in self.lines + [""])

    def encode(self):
        return self.text().encode("utf-16-le")


class LoadScriptInstaller:
    def __init__(self, client, script_path, destination=None, processor_type=4000, log=None):
        self.client = client
        self.script_path = Path(script_path)
        self.source_directory = self.script_path.parent
        self.processor_type = processor_type
        self.log = log or (lambda message: None)
        install_inf = read_install_inf(self.source_directory)
        self.app_name = install_inf.get("appname") or self.script_path.stem
        self.install_directory = strip_trailing_separators(destination or install_inf.get("installdir") or DEFAULT_INSTALL_DIRECTORY)
        if INSTALL_PATH_MACRO in self.install_directory.upper():
            raise InstallError("the install directory cannot contain %P")
        self.home_key = f"{APPS_KEY}\\{self.app_name}"
        self.unload = UnloadScript()
        self.created_directories = 0

    @property
    def unload_path(self):
        return join_device_path(UNLOAD_DIRECTORY, self.app_name + UNLOAD_EXTENSION)

    async def run(self):
        try:
            text = self.script_path.read_bytes().decode("cp1252", errors="replace")
        except OSError as error:
            raise InstallError(f"Can't open load script {self.script_path}") from error
        result = LoadResult(self.app_name, self.install_directory, self.unload_path)
        self.created_directories = await self.make_directories(self.install_directory)
        await self.register_application()
        for command in parse_load_script(text):
            if command.key == "exit":
                break
            try:
                await self.execute(command)
            except (RapiError, InstallError, OSError, ValueError) as error:
                message = f"{self.script_path.name} line {command.line_number}: {command.name}: {error}"
                self.log(message)
                result.errors.append(message)
        await self.client.write_file_contents(self.unload_path, self.unload.encode())
        self.log(f"unload script {self.unload_path}")
        return result

    async def execute(self, command):
        if command.key not in ARGUMENT_COUNTS:
            raise InstallError("Syntax error in statement.")
        minimum, maximum = ARGUMENT_COUNTS[command.key]
        count = len(command.arguments)
        if count < minimum:
            raise InstallError("Insufficient arguments.")
        if maximum is not None and count > maximum:
            raise InstallError("Too many arguments.")
        arguments = [self.expand(argument) for argument in command.arguments]
        handler = getattr(self, f"command_{command.key}")
        await handler(*arguments)

    def expand(self, value):
        if INSTALL_PATH_MACRO not in value.upper():
            return value
        expanded = []
        position = 0
        while position < len(value):
            if value[position] == "%" and value[position + 1:position + 2].upper() == "P":
                expanded.append(self.install_directory)
                position += 2
            else:
                expanded.append(value[position])
                position += 1
        return "".join(expanded)

    def device_directory(self, directory):
        if directory.startswith("\\"):
            return strip_trailing_separators(directory)
        if directory in (".", ""):
            return self.install_directory
        return join_device_path(self.install_directory, directory.rstrip("\\"))

    def source_file(self, source_directory, name):
        folder = Path(source_directory)
        if not folder.is_absolute():
            folder = self.source_directory if source_directory in (".", "") else self.source_directory / source_directory.replace("\\", "/")
        stem = name.rsplit(".", 1)[0] if "." in name else name
        candidates = [f"{name}.{suffix}" for suffix in processor_suffixes(self.processor_type)]
        candidates += [f"{stem}.{suffix}" for suffix in processor_suffixes(self.processor_type)]
        candidates.append(name)
        for candidate in candidates:
            found = find_case_insensitive(folder, candidate)
            if found:
                return found
        raise InstallError(f"missing {name} in {folder}")

    async def exists(self, path):
        try:
            return await self.client.get_file_attributes(path)
        except RapiError:
            return None

    async def make_directories(self, path):
        created = 0
        parts = [part for part in path.split("\\") if part]
        partial = ""
        for part in parts:
            partial = f"{partial}\\{part}"
            if await self.exists(partial) is None:
                await self.client.create_directory(partial)
                created += 1
        return created

    async def register_application(self):
        handle, _ = await self.client.reg_create_key(HKEY_LOCAL_MACHINE, self.home_key)
        try:
            await self.client.reg_set_value(handle, "InstlDir", REG_SZ, self.install_directory)
            await self.client.reg_set_value(handle, "InstlDirCnt", REG_DWORD, self.created_directories)
            await self.client.reg_set_value(handle, "Instl", REG_DWORD, 1)
        finally:
            await self.client.reg_close_key(handle)

    async def copy(self, source_directory, destination_directory, name, shared):
        local = self.source_file(source_directory, name)
        folder = self.device_directory(destination_directory)
        await self.make_directories(folder)
        remote = join_device_path(folder, name)
        await self.client.write_file_contents(remote, local.read_bytes())
        self.unload.prepend(f"{'1' if shared else '0'}\n {folder}\n {name}")
        if shared:
            await self.increment_shared_count(remote)
        self.log(f"copied {remote}")

    async def increment_shared_count(self, remote):
        handle, _ = await self.client.reg_create_key(HKEY_LOCAL_MACHINE, SHARED_KEY)
        try:
            try:
                _, count = await self.client.reg_query_value(handle, remote)
            except RapiError:
                count = 0
            await self.client.reg_set_value(handle, remote, REG_DWORD, (count if isinstance(count, int) else 0) + 1)
        finally:
            await self.client.reg_close_key(handle)

    async def command_copy(self, source_directory, destination_directory, name):
        await self.copy(source_directory, destination_directory, name, shared=False)

    async def command_copyshared(self, source_directory, destination_directory, name):
        await self.copy(source_directory, destination_directory, name, shared=True)

    async def command_mkdir(self, directory):
        folder = self.device_directory(directory)
        await self.make_directories(folder)
        self.unload.prepend(f" {folder}")
        self.unload.prepend("2")
        self.log(f"folder {folder}")

    async def command_rm(self, *paths):
        for path in paths:
            target = self.device_directory(path)
            await self.client.delete_file(target)
            self.log(f"deleted {target}")

    async def command_createshortcut(self, directory, link_name, target_directory, target):
        folder = self.device_directory(directory)
        link = join_device_path(folder, link_name)
        if target == '""':
            path = self.device_directory(target_directory)
        else:
            path = join_device_path(self.device_directory(target_directory), target)
        if '"' in path:
            content = f'"{path}'
        elif " " in path:
            content = f'"{path}"'
        else:
            content = path
        await self.make_directories(folder)
        await self.client.write_file_contents(link, f"{len(content)}#{content}".encode("cp1252"))
        self.unload.prepend(f"0\n {folder}\n {link_name}")
        self.log(f"shortcut {link} -> {content}")

    def registry_key(self, root, subkey):
        if root == HOME_KEY or subkey == HOME_KEY or subkey.startswith(HOME_KEY + "\\"):
            relative = subkey[1:] if subkey.startswith(HOME_KEY) else subkey
            relative = relative.lstrip("\\")
            path = join_device_path(self.home_key, relative) if relative else self.home_key
            if root == HOME_KEY:
                return HKEY_LOCAL_MACHINE, "l", path, True
            root_key, letter = self.root_key(root)
            return root_key, letter, path, True
        root_key, letter = self.root_key(root)
        return root_key, letter, subkey.strip("\\"), False

    def root_key(self, root):
        try:
            return ROOT_KEYS[root.upper()]
        except KeyError:
            raise InstallError(f"unknown registry root {root}") from None

    def records_uninstall(self, uninstall_flag, home):
        try:
            flagged = int(uninstall_flag) != 0
        except ValueError:
            flagged = False
        return flagged or not home

    async def set_value(self, root, subkey, uninstall_flag, name, value_type, value):
        root_key, letter, path, home = self.registry_key(root, subkey)
        value_name = "" if name.lower() == "default" else name
        if self.records_uninstall(uninstall_flag, home):
            self.unload.prepend(f"3\n {letter} {path} {value_name}")
        handle, _ = await self.client.reg_create_key(root_key, path)
        try:
            await self.client.reg_set_value(handle, value_name, value_type, value)
        finally:
            await self.client.reg_close_key(handle)
        self.log(f"registry {path}\\{name}")

    async def command_regkeycreate(self, root, subkey, uninstall_flag):
        root_key, letter, path, home = self.registry_key(root, subkey)
        if self.records_uninstall(uninstall_flag, home):
            self.unload.append(f"4\n {letter} {path}")
        handle, _ = await self.client.reg_create_key(root_key, path)
        await self.client.reg_close_key(handle)
        self.log(f"registry {path}")

    async def command_regvaluedelete(self, root, subkey, name):
        root_key, _, path, _ = self.registry_key(root, subkey)
        handle = await self.client.reg_open_key(root_key, path)
        try:
            await self.client.reg_delete_value(handle, "" if name.lower() == "default" else name)
        finally:
            await self.client.reg_close_key(handle)
        self.log(f"deleted registry value {path}\\{name}")

    async def command_regstring(self, root, subkey, uninstall_flag, name, value):
        await self.set_value(root, subkey, uninstall_flag, name, REG_SZ, value.split("\0", 1)[0])

    async def command_regstringmulti(self, root, subkey, uninstall_flag, name, value):
        await self.set_value(root, subkey, uninstall_flag, name, REG_MULTI_SZ, value.split("\0"))

    async def command_regint(self, root, subkey, uninstall_flag, name, value):
        await self.set_value(root, subkey, uninstall_flag, name, REG_DWORD, parse_integer(value) & 0xFFFFFFFF)

    async def command_remoteexec(self, program, arguments=None):
        path = program if program.startswith("\\") else join_device_path(self.install_directory, program)
        await self.client.create_process(path, arguments or None)
        self.log(f"started {path}")

    async def command_execonunload(self, program):
        self.unload.append("5")
        self.unload.append(f" {program}")
        self.log(f"{program} will run on removal")

    async def command_appendtounload(self, record):
        self.unload.append(record)

    async def command_prependtounload(self, record):
        self.unload.prepend(record)


def parse_integer(text):
    text = text.strip()
    try:
        return int(text, 0)
    except ValueError:
        digits = ""
        for character in text.lstrip("+-"):
            if not character.isdigit():
                break
            digits += character
        value = int(digits or "0")
        return -value if text.startswith("-") else value


def parse_unload_script(data):
    text = data.decode("utf-16-le", errors="replace") if isinstance(data, (bytes, bytearray)) else data
    records = []
    for line in text.split("\n"):
        if not line:
            continue
        if line.startswith(" ") and records:
            records[-1][1].append(line[1:])
        else:
            records.append((line, []))
    return records

