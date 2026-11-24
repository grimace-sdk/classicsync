from dataclasses import dataclass, field
from pathlib import Path

from ..rapi.client import HKEY_LOCAL_MACHINE, RapiError
from .appmgr import read_appmgr_ini, select_component_package
from .load_script import APPS_KEY, UNLOAD_PROGRAM, LoadScriptInstaller
from .package import DeviceProfile, InstallError, compatibility_problem, read_cab_package
from .records import DesktopAppRecords

APPMGR_DIRECTORY = "\\Windows\\AppMgr"
APPMGR_INSTALL_DIRECTORY = "\\Windows\\AppMgr\\Install"
WCELOAD_PROGRAM = "Wceload.exe"
WCELOAD_PATH = "\\Windows\\Wceload.exe"
STARTUP_FOLDER = "\\Windows\\StartUp"
WCELOAD_SHORTCUT = "Wceload.lnk"
NO_ASK_DESTINATION = "/noaskdest"
HPC1_REFUSAL = "Application Manager cannot install applications on a Handheld PC 1.0 device."
INVALID_FILE_NAME_CHARACTERS = '\\/:*?"<>|'


@dataclass
class InstallOutcome:
    name: str
    message: str
    device_path: str = ""
    errors: list = field(default_factory=list)

    @property
    def succeeded(self):
        return not self.errors


@dataclass
class InstalledApp:
    name: str
    install_directory: str = ""
    installed: bool = True


async def read_device_profile(client, platform=""):
    version = await client.get_version()
    system = await client.get_system_info()
    return DeviceProfile(version.major, version.minor, version.build, system.processor_type, platform)


async def path_exists(client, path):
    try:
        await client.get_file_attributes(path)
        return True
    except RapiError:
        return False


async def ensure_directory(client, path):
    if not await path_exists(client, path):
        await client.create_directory(path)


def device_cab_name(package):
    name = "".join("_" if character in INVALID_FILE_NAME_CHARACTERS else character for character in package.file_name)
    return name if name.lower().endswith(".cab") else f"{name}.CAB"


def refuse_hpc1(profile):
    if profile.os_major < 2:
        raise InstallError(HPC1_REFUSAL)


async def ensure_wceload_shortcut(client):
    shortcut = f"{STARTUP_FOLDER}\\{WCELOAD_SHORTCUT}"
    if await path_exists(client, shortcut):
        return False
    await ensure_directory(client, STARTUP_FOLDER)
    await client.create_shortcut(shortcut, WCELOAD_PATH)
    return True


async def copy_cab(client, package, progress=None):
    await ensure_directory(client, APPMGR_DIRECTORY)
    await ensure_directory(client, APPMGR_INSTALL_DIRECTORY)
    device_path = f"{APPMGR_INSTALL_DIRECTORY}\\{device_cab_name(package)}"
    reporter = (lambda written: progress(written, package.size)) if progress else None
    await client.write_file_contents(device_path, package.data, progress=reporter)
    return device_path


async def run_wceload(client, default_folder=True):
    return await client.create_process(WCELOAD_PROGRAM, NO_ASK_DESTINATION if default_folder else None)


async def install_cabs(client, packages, profile=None, default_folder=True, progress=None):
    profile = profile or await read_device_profile(client)
    refuse_hpc1(profile)
    for package in packages:
        problem = compatibility_problem(package, profile)
        if problem:
            raise InstallError(problem)
    outcomes = []
    for package in packages:
        device_path = await copy_cab(client, package, progress)
        name = package.uninstall_name or package.file_name
        outcomes.append(InstallOutcome(name, f"{name}: copied to {device_path}", device_path))
    try:
        await ensure_wceload_shortcut(client)
    except RapiError as error:
        outcomes[-1].errors.append(f"could not create {STARTUP_FOLDER}\\{WCELOAD_SHORTCUT}: {error}")
    await run_wceload(client, default_folder)
    outcomes[-1].message += f", {WCELOAD_PROGRAM} started"
    return outcomes


async def install_cab(client, package, profile=None, default_folder=True, progress=None):
    return (await install_cabs(client, [package], profile, default_folder, progress))[0]


async def install_components(client, components, profile=None, default_folder=True, progress=None):
    profile = profile or await read_device_profile(client)
    refuse_hpc1(profile)
    packages = [select_component_package(component, profile) for component in components]
    outcomes = await install_cabs(client, packages, profile, default_folder, progress)
    for outcome, component in zip(outcomes, components):
        outcome.name = component.name
    return outcomes


async def install_load(client, script_path, destination=None, profile=None, log=None):
    profile = profile or await read_device_profile(client)
    installer = LoadScriptInstaller(client, script_path, destination, profile.processor_type, log)
    result = await installer.run()
    message = f"{result.app_name}: installed into {result.install_directory}, unload script {result.unload_path}"
    return InstallOutcome(result.app_name, message, result.install_directory, result.errors)


async def install_file(client, path, destination=None, default_folder=True, progress=None, log=None, records=None):
    path = Path(path)
    suffix = path.suffix.lower()
    profile = await read_device_profile(client)
    if suffix == ".load":
        return [await install_load(client, path, destination, profile, log)]
    if suffix == ".cab":
        return [await install_cab(client, read_cab_package(path), profile, default_folder, progress)]
    if suffix == ".ini":
        components = read_appmgr_ini(path)
        records = records if records is not None else DesktopAppRecords()
        for component in components:
            records.add_component(component)
        return await install_components(client, components, profile, default_folder, progress)
    raise InstallError(f"{path.name}: expected a .cab, .ini or .load file")


async def list_installed_apps(client, include_uninstalled=False):
    try:
        apps_key = await client.reg_open_key(HKEY_LOCAL_MACHINE, APPS_KEY)
    except RapiError:
        return []
    names = []
    try:
        index = 0
        while (name := await client.reg_enum_key(apps_key, index)) is not None:
            names.append(name)
            index += 1
    finally:
        await client.reg_close_key(apps_key)
    apps = []
    for name in names:
        app = await read_installed_app(client, name)
        if app and (app.installed or include_uninstalled):
            apps.append(app)
    return sorted(apps, key=lambda app: app.name.lower())


async def read_installed_app(client, name):
    try:
        handle = await client.reg_open_key(HKEY_LOCAL_MACHINE, f"{APPS_KEY}\\{name}")
    except RapiError:
        return None
    try:
        values = {}
        for value_name in ("Instl", "InstlDir"):
            try:
                values[value_name] = (await client.reg_query_value(handle, value_name))[1]
            except RapiError:
                pass
    finally:
        await client.reg_close_key(handle)
    if "Instl" not in values:
        return None
    return InstalledApp(name, values.get("InstlDir", "") if isinstance(values.get("InstlDir"), str) else "", values["Instl"] == 1)


async def uninstall_app(client, name):
    return await client.create_process(UNLOAD_PROGRAM, name)
