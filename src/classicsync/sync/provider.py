from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProviderContext:
    device: object
    partnership_directory: Path
    settings: dict = field(default_factory=dict)
    log: object = None

    def message(self, text):
        if self.log:
            self.log(text)


class Store:
    object_type = None

    def list_items(self):
        raise NotImplementedError

    def read_item(self, item_id, device_id):
        raise NotImplementedError

    def write_item(self, item_id, device_id, device_object):
        raise NotImplementedError

    def delete_item(self, item_id, device_id):
        raise NotImplementedError

    def find_match(self, device_id, device_object, unmatched_item_ids):
        return None

    def same_content(self, item_id, device_id, device_object):
        return False

    def device_updated(self, item_id, device_id, device_object):
        pass

    def describe(self, item_id):
        return item_id

    def describe_device(self, device_id, device_object):
        return None

    def describe_conflict(self, item_id, device_id, device_object):
        return [self.describe(item_id)], [self.describe_device(device_id, device_object) or device_id]

    def close(self):
        pass


class Provider:
    name = ""
    display_name = ""
    object_types = ()
    settings_schema = ()

    def __init__(self, context):
        self.context = context

    def open_store(self, object_type):
        raise NotImplementedError

    def close(self):
        pass
