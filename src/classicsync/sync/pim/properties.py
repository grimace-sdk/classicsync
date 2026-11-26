from ...rapi.cedb import CEVT_BLOB, CEVT_FILETIME, CEVT_I2, CEVT_I4, CEVT_LPWSTR

SUBJECT = (0x0037, CEVT_LPWSTR)
NOTES_TEXT = (0x1000, CEVT_LPWSTR)
NOTES_BLOB = (0x0017, CEVT_BLOB)
NOTES_INK = (0x0016, CEVT_BLOB)
SENSITIVITY = (0x0004, CEVT_I2)
CATEGORIES = (0x4005, CEVT_LPWSTR)
UNIQUE_ID = (0x0067, CEVT_BLOB)
UNKNOWN_0002 = (0x0002, CEVT_I4)
REMINDER_MINUTES = (0x4501, CEVT_I4)
REMINDER_ENABLED = (0x4503, CEVT_I2)
REMINDER_SOUND = (0x4509, CEVT_LPWSTR)
REMINDER_OPTIONS = (0x450A, CEVT_I4)

CONTACT_TEXT_FIELDS = {
    "given_name": 0x3A06,
    "surname": 0x3A11,
    "middle_name": 0x4024,
    "name_prefix": 0x4023,
    "generation": 0x3A05,
    "company": 0x3A16,
    "department": 0x3A18,
    "title": 0x3A17,
    "office_location": 0x3A19,
    "work_phone": 0x3A08,
    "work_phone2": 0x4007,
    "home_phone": 0x3A09,
    "home_phone2": 0x3A2F,
    "mobile_phone": 0x3A1C,
    "car_phone": 0x3A1E,
    "pager": 0x4009,
    "work_fax": 0x3A24,
    "home_fax": 0x3A25,
    "assistant": 0x4002,
    "assistant_phone": 0x4004,
    "spouse": 0x400A,
    "children": 0x4006,
    "web_page": 0x4008,
    "categories": 0x4005,
    "email1": 0x4083,
    "email2": 0x4093,
    "email3": 0x40A3,
    "home_street": 0x4040,
    "home_city": 0x4041,
    "home_state": 0x4042,
    "home_postal_code": 0x4043,
    "home_country": 0x4044,
    "work_street": 0x4045,
    "work_city": 0x4046,
    "work_state": 0x4047,
    "work_postal_code": 0x4048,
    "work_country": 0x4049,
    "other_street": 0x404A,
    "other_city": 0x404B,
    "other_state": 0x404C,
    "other_postal_code": 0x404D,
    "other_country": 0x404E,
    "notes": 0x1000,
}
CONTACT_FILE_AS = 0x4013
CONTACT_DATE_FIELDS = {
    "birthday": 0x4001,
    "anniversary": 0x4003,
}

APPOINTMENT_START = (0x420D, CEVT_FILETIME)
APPOINTMENT_DAY = (0x4212, CEVT_FILETIME)
APPOINTMENT_DURATION = (0x4213, CEVT_I4)
APPOINTMENT_TYPE = (0x4215, CEVT_I4)
APPOINTMENT_RECURRENCE = (0x4223, CEVT_I2)
APPOINTMENT_LOCATION = (0x4208, CEVT_LPWSTR)
APPOINTMENT_BUSY_STATUS = (0x000F, CEVT_I2)

APPOINTMENT_TYPE_ALL_DAY = 1
APPOINTMENT_TYPE_NORMAL = 2

TASK_START = (0x4104, CEVT_FILETIME)
TASK_DUE = (0x4105, CEVT_FILETIME)
TASK_COMPLETED = (0x410F, CEVT_I2)
TASK_COMPLETED_DATE = (0x410F, CEVT_FILETIME)
TASK_IMPORTANCE = (0x0026, CEVT_I4)
TASK_PROJECT = (0x4028, CEVT_LPWSTR)
TASK_UNKNOWN_4126 = (0x4126, CEVT_I2)
TASK_UNKNOWN_0003 = (0x0003, CEVT_I2)

NO_DATE = 915151392000000000

RECURRENCE_RULE = (0x7F01, CEVT_LPWSTR)
RECURRENCE_EXCEPTIONS = (0x7F02, CEVT_LPWSTR)
TASK_PRIORITY = (0x7F03, CEVT_I2)
PRIVATE_IDENTIFIERS = frozenset({RECURRENCE_RULE[0], RECURRENCE_EXCEPTIONS[0], TASK_PRIORITY[0]})

BUSY_STATUS_NAMES = {0: "FREE", 1: "TENTATIVE", 2: "BUSY", 3: "OOF"}
