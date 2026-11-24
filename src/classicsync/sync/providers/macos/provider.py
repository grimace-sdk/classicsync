import hashlib
import threading
from datetime import datetime, timedelta, timezone

import Contacts
import EventKit
import Foundation

from ....i18n import N_, _
from ...objects import CALENDAR, CONTACTS, TASKS
from ...provider import Provider, ProviderError
from ...settings_schema import Setting
from ..native_pim import (
    EventFields, TaskFields, changed_fields, changed_values, contact_fields_from_text, contact_text, empty_contact_fields,
    event_fields_from_text, event_text, normalized_contact_fields, normalized_event, normalized_task, task_fields_from_text,
    task_text, without_recurring_times,
)
from ..pim_store import RemotePimStore
from .mapping import (
    ContactSlots, apply_contact_changes, apply_event_changes, apply_reminder_changes, contact_slots, event_fields, item_stamp,
    reminder_fields,
)

ACCESS_TIMEOUT_SECONDS = 120
FETCH_TIMEOUT_SECONDS = 60
MAXIMUM_PREDICATE_DAYS = 1400
AUTHORIZED_STATUSES = (3,)
DENIED_STATUSES = (1, 2)
CONTACT_KEYS = [
    "identifier", "givenName", "familyName", "middleName", "namePrefix", "nameSuffix", "organizationName", "departmentName",
    "jobTitle", "phoneNumbers", "emailAddresses", "postalAddresses", "urlAddresses", "birthday", "dates", "contactRelations",
]
NOTE_KEY = "note"


def wait_for_completion(start, timeout, message):
    finished = threading.Event()
    results = []

    def completed(*values):
        results.append(values)
        finished.set()

    start(completed)
    deadline = datetime.now() + timedelta(seconds=timeout)
    run_loop = Foundation.NSRunLoop.currentRunLoop()
    while not finished.is_set() and datetime.now() < deadline:
        run_loop.runUntilDate_(Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.1))
    if not results:
        raise ProviderError(message)
    return results[0]


def nsdate(moment):
    return Foundation.NSDate.dateWithTimeIntervalSince1970_(moment.timestamp())


class NativeFactory:
    def __init__(self, event_store=None):
        self.event_store = event_store

    def labeled(self, label, value):
        return Contacts.CNLabeledValue.labeledValueWithLabel_value_(label, value)

    def phone(self, text):
        return Contacts.CNPhoneNumber.phoneNumberWithStringValue_(text)

    def postal_address(self, parts):
        address = Contacts.CNMutablePostalAddress.alloc().init()
        address.setStreet_(parts["street"])
        address.setCity_(parts["city"])
        address.setState_(parts["state"])
        address.setPostalCode_(parts["postal_code"])
        address.setCountry_(parts["country"])
        return address

    def relation(self, name):
        return Contacts.CNContactRelation.contactRelationWithName_(name)

    def date_components(self, day):
        components = Foundation.NSDateComponents.alloc().init()
        components.setYear_(day.year)
        components.setMonth_(day.month)
        components.setDay_(day.day)
        return components

    def date(self, moment):
        return nsdate(moment)

    def alarm(self, minutes):
        return EventKit.EKAlarm.alarmWithRelativeOffset_(-60.0 * minutes)


def request_contacts_access(store):
    status = Contacts.CNContactStore.authorizationStatusForEntityType_(Contacts.CNEntityTypeContacts)
    if status in AUTHORIZED_STATUSES:
        return
    if status in DENIED_STATUSES:
        raise ProviderError(_("ClassicSync may not use Contacts; allow it in System Settings, Privacy & Security, Contacts."))
    granted, error = wait_for_completion(
        lambda done: store.requestAccessForEntityType_completionHandler_(Contacts.CNEntityTypeContacts, done),
        ACCESS_TIMEOUT_SECONDS, _("No answer to the request to use Contacts."))
    if not granted:
        raise ProviderError(_("ClassicSync may not use Contacts; allow it in System Settings, Privacy & Security, Contacts."))


def request_event_access(store, entity_type):
    status = EventKit.EKEventStore.authorizationStatusForEntityType_(entity_type)
    name = _("Calendars") if entity_type == EventKit.EKEntityTypeEvent else _("Reminders")
    denied = _("ClassicSync may not use {name}; allow it in System Settings, Privacy & Security, {name}.").format(name=name)
    if status in AUTHORIZED_STATUSES:
        return
    if status in DENIED_STATUSES:
        raise ProviderError(denied)
    if entity_type == EventKit.EKEntityTypeEvent and hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        start = store.requestFullAccessToEventsWithCompletion_
    elif entity_type == EventKit.EKEntityTypeReminder and hasattr(store, "requestFullAccessToRemindersWithCompletion_"):
        start = store.requestFullAccessToRemindersWithCompletion_
    else:
        def start(done):
            store.requestAccessToEntityType_completion_(entity_type, done)
    granted, error = wait_for_completion(start, ACCESS_TIMEOUT_SECONDS,
                                         _("No answer to the request to use {name}.").format(name=name))
    if not granted:
        raise ProviderError(denied)


def text_hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class ContactsStore(RemotePimStore):
    vcard_version = "4.0"

    def __init__(self, object_type, cache_directory, os_major, group_name):
        super().__init__(object_type, cache_directory, os_major)
        self.store = Contacts.CNContactStore.alloc().init()
        request_contacts_access(self.store)
        self.factory = NativeFactory()
        self.group = self.find_group(group_name) if group_name else None
        self.notes_available = True
        self.contacts = {}

    def find_group(self, group_name):
        groups, error = self.store.groupsMatchingPredicate_error_(None, None)
        for group in groups or []:
            if group.name() == group_name:
                return group
        group = Contacts.CNMutableGroup.alloc().init()
        group.setName_(group_name)
        request = Contacts.CNSaveRequest.alloc().init()
        request.addGroup_toContainerWithIdentifier_(group, None)
        self.execute(request)
        return group

    def execute(self, request):
        ok, error = self.store.executeSaveRequest_error_(request, None)
        if not ok:
            raise ProviderError(_("Contacts could not save: {error}").format(error=error))

    def fetch_all(self, keys):
        request = Contacts.CNContactFetchRequest.alloc().initWithKeysToFetch_(keys)
        request.setUnifyResults_(False)
        if self.group is not None:
            request.setPredicate_(Contacts.CNContact.predicateForContactsInGroupWithIdentifier_(self.group.identifier()))
        found = []
        ok, error = self.store.enumerateContactsWithFetchRequest_error_usingBlock_(
            request, None, lambda contact, stop: found.append(contact))
        if not ok:
            raise ProviderError(_("Contacts could not be read: {error}").format(error=error))
        return found

    def list_remote(self):
        try:
            found = self.fetch_all(CONTACT_KEYS + [NOTE_KEY]) if self.notes_available else self.fetch_all(CONTACT_KEYS)
        except ProviderError:
            if not self.notes_available:
                raise
            self.notes_available = False
            found = self.fetch_all(CONTACT_KEYS)
        self.contacts = {contact.identifier(): contact for contact in found}
        self.texts = {item_id: self.contact_text(contact) for item_id, contact in self.contacts.items()}
        return {item_id: text_hash(text) for item_id, text in self.texts.items()}

    def contact_text(self, contact):
        return contact_text(contact_slots(contact, self.notes_available).values, contact.identifier())

    def fetch_text(self, item_id):
        return self.contact_text(self.contacts[item_id])

    def put_text(self, item_id, text, uid):
        request = Contacts.CNSaveRequest.alloc().init()
        if item_id:
            contact = self.contacts[item_id].mutableCopy()
            slots = contact_slots(contact, self.notes_available)
            before = normalized_contact_fields(slots.values)
        else:
            contact = Contacts.CNMutableContact.alloc().init()
            slots = ContactSlots(notes_available=self.notes_available)
            before = empty_contact_fields()
        apply_contact_changes(contact, slots, changed_values(before, contact_fields_from_text(text)), self.factory)
        if item_id:
            request.updateContact_(contact)
        else:
            request.addContact_toContainerWithIdentifier_(contact, None)
            if self.group is not None:
                request.addMember_toGroup_(contact, self.group)
        self.execute(request)
        self.contacts[contact.identifier()] = contact
        written = self.contact_text(contact)
        self.texts[contact.identifier()] = written
        return contact.identifier(), text_hash(written)

    def delete_remote(self, item_id):
        request = Contacts.CNSaveRequest.alloc().init()
        request.deleteContact_(self.contacts[item_id].mutableCopy())
        self.execute(request)
        self.contacts.pop(item_id, None)


def find_calendar(store, entity_type, calendar_name):
    if not calendar_name:
        calendar = (store.defaultCalendarForNewEvents() if entity_type == EventKit.EKEntityTypeEvent
                    else store.defaultCalendarForNewReminders())
        if calendar is None:
            raise ProviderError(_("There is no default calendar or list."))
        return calendar
    for calendar in store.calendarsForEntityType_(entity_type) or []:
        if calendar.title() == calendar_name:
            return calendar
    raise ProviderError(_("There is no calendar or list called {name}.").format(name=calendar_name))


class EventKitStore(RemotePimStore):
    vcard_version = "4.0"
    entity_type = None

    def __init__(self, object_type, cache_directory, os_major, calendar_name):
        super().__init__(object_type, cache_directory, os_major)
        self.store = EventKit.EKEventStore.alloc().init()
        request_event_access(self.store, self.entity_type)
        self.calendar = find_calendar(self.store, self.entity_type, calendar_name)
        self.factory = NativeFactory(self.store)
        self.items = {}

    def native_text(self, item):
        raise NotImplementedError

    def native_items(self):
        raise NotImplementedError

    def list_remote(self):
        self.items = {}
        for item in self.native_items():
            self.items.setdefault(item.calendarItemIdentifier(), item)
        self.texts = {item_id: self.native_text(item) for item_id, item in self.items.items()}
        return {item_id: item_stamp(self.items[item_id], text) for item_id, text in self.texts.items()}

    def item(self, item_id):
        if item_id not in self.items:
            found = self.store.calendarItemWithIdentifier_(item_id)
            if found is None:
                raise ProviderError(_("Calendar item {item} no longer exists.").format(item=item_id))
            self.items[item_id] = found
        return self.items[item_id]

    def fetch_text(self, item_id):
        return self.native_text(self.item(item_id))

    def finish_put(self, item):
        item_id = item.calendarItemIdentifier()
        self.items[item_id] = item
        text = self.native_text(item)
        self.texts[item_id] = text
        return item_id, item_stamp(item, text)


class CalendarStore(EventKitStore):
    entity_type = EventKit.EKEntityTypeEvent

    def __init__(self, object_type, cache_directory, os_major, calendar_name, past_days, future_days):
        self.past_days = past_days
        self.future_days = future_days
        super().__init__(object_type, cache_directory, os_major, calendar_name)

    def native_text(self, event):
        return event_text(event_fields(event), event.calendarItemExternalIdentifier() or event.calendarItemIdentifier())

    def native_items(self):
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=self.past_days)
        end = now + timedelta(days=self.future_days)
        found = []
        while start < end:
            chunk_end = min(end, start + timedelta(days=MAXIMUM_PREDICATE_DAYS))
            predicate = self.store.predicateForEventsWithStartDate_endDate_calendars_(nsdate(start), nsdate(chunk_end),
                                                                                     [self.calendar])
            found.extend(sorted(self.store.eventsMatchingPredicate_(predicate) or [],
                                key=lambda event: event.startDate().timeIntervalSince1970()))
            start = chunk_end
        return found

    def save(self, event, span):
        ok, error = self.store.saveEvent_span_commit_error_(event, span, True, None)
        if not ok:
            raise ProviderError(_("Calendar could not save {title}: {error}").format(title=event.title(), error=error))

    def put_text(self, item_id, text, uid):
        incoming = event_fields_from_text(text)
        if item_id:
            event = self.item(item_id)
            before = normalized_event(event_fields(event))
            changes = changed_fields(before, incoming, ignored=("recurring",))
            if event.hasRecurrenceRules():
                changes = without_recurring_times(changes)
        else:
            event = EventKit.EKEvent.eventWithEventStore_(self.store)
            event.setCalendar_(self.calendar)
            changes = changed_fields(EventFields(), incoming, ignored=("recurring",))
        apply_event_changes(event, incoming, changes, self.factory)
        self.save(event, EventKit.EKSpanFutureEvents if event.hasRecurrenceRules() else EventKit.EKSpanThisEvent)
        return self.finish_put(event)

    def delete_remote(self, item_id):
        event = self.item(item_id)
        span = EventKit.EKSpanFutureEvents if event.hasRecurrenceRules() else EventKit.EKSpanThisEvent
        ok, error = self.store.removeEvent_span_commit_error_(event, span, True, None)
        if not ok:
            raise ProviderError(_("Calendar could not delete {title}: {error}").format(title=event.title(), error=error))
        self.items.pop(item_id, None)


class RemindersStore(EventKitStore):
    entity_type = EventKit.EKEntityTypeReminder

    def native_text(self, reminder):
        return task_text(reminder_fields(reminder), reminder.calendarItemExternalIdentifier() or reminder.calendarItemIdentifier())

    def native_items(self):
        predicate = self.store.predicateForRemindersInCalendars_([self.calendar])
        (reminders,) = wait_for_completion(lambda done: self.store.fetchRemindersMatchingPredicate_completion_(predicate, done),
                                           FETCH_TIMEOUT_SECONDS, _("Reminders did not answer."))
        return list(reminders or [])

    def put_text(self, item_id, text, uid):
        incoming = task_fields_from_text(text)
        if item_id:
            reminder = self.item(item_id)
            before = normalized_task(reminder_fields(reminder))
        else:
            reminder = EventKit.EKReminder.reminderWithEventStore_(self.store)
            reminder.setCalendar_(self.calendar)
            before = TaskFields()
        apply_reminder_changes(reminder, incoming, changed_fields(before, incoming), self.factory)
        ok, error = self.store.saveReminder_commit_error_(reminder, True, None)
        if not ok:
            raise ProviderError(_("Reminders could not save {title}: {error}").format(title=reminder.title(), error=error))
        return self.finish_put(reminder)

    def delete_remote(self, item_id):
        ok, error = self.store.removeReminder_commit_error_(self.item(item_id), True, None)
        if not ok:
            raise ProviderError(_("Reminders could not delete an item: {error}").format(error=error))
        self.items.pop(item_id, None)


class MacProvider(Provider):
    name = "macos"
    display_name = N_("macOS Contacts, Calendar and Reminders")
    object_types = (CONTACTS, CALENDAR, TASKS)
    settings_schema = (
        Setting("macos_contacts_group", N_("Contacts group"), "string", "",
                help=N_("Only synchronize contacts in this group; new contacts from the device are added to it. "
                        "Empty: all contacts.")),
        Setting("macos_calendar", N_("Calendar"), "string", "",
                help=N_("Calendar for appointments. Empty: the default calendar for new events.")),
        Setting("macos_reminders_list", N_("Reminders list"), "string", "",
                help=N_("Reminders list for tasks. Empty: the default list.")),
        Setting("macos_past_days", N_("Past appointments (days)"), "int", 30, minimum=0,
                help=N_("Appointments that ended more than this many days ago are not synchronized.")),
        Setting("macos_future_days", N_("Future appointments (days)"), "int", 365, minimum=0,
                help=N_("Appointments starting more than this many days ahead are not synchronized.")),
    )

    def open_store(self, object_type):
        settings = self.context.settings
        cache = self.context.partnership_directory / "macos"
        os_major = self.context.device.os_major
        if object_type.key == CONTACTS.key:
            return ContactsStore(object_type, cache, os_major, settings.get("macos_contacts_group") or "")
        if object_type.key == CALENDAR.key:
            return CalendarStore(object_type, cache, os_major, settings.get("macos_calendar") or "",
                                 settings.get("macos_past_days", 30), settings.get("macos_future_days", 365))
        if object_type.key == TASKS.key:
            return RemindersStore(object_type, cache, os_major, settings.get("macos_reminders_list") or "")
        raise ValueError(f"macos provider does not handle {object_type.key}")


PROVIDERS = [MacProvider]
