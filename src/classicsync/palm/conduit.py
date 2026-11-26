from dataclasses import dataclass, field

PRIORITY_FIRST = 0
PRIORITY_DEFAULT = 2
PRIORITY_LAST = 4


@dataclass
class ConduitContext:
    client: object
    partnership: object
    user: object
    folder: object
    log: object = print
    dry_run: bool = False
    claimed: set = field(default_factory=set)


class Conduit:
    name = ""
    display_name = ""
    creators = ()
    databases = ()
    priority = PRIORITY_DEFAULT

    def claims(self, database):
        return database.creator in self.creators or database.name in self.databases


class RecordConduit(Conduit):
    object_type = None
    database = ""

    def __init__(self):
        if self.database and not self.databases:
            self.databases = (self.database,)

    def parse(self, data):
        raise NotImplementedError

    def build(self, record):
        raise NotImplementedError

    def to_desktop(self, record, category, secret):
        raise NotImplementedError

    def from_desktop(self, device_object, base):
        raise NotImplementedError

    def source(self, client):
        from .source import PalmDatabaseSource
        return PalmDatabaseSource(client, self)


class FreeformConduit(Conduit):
    async def run(self, context):
        raise NotImplementedError
