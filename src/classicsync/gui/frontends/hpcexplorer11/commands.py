from ....i18n import N_, _

ID_UP = 210
ID_UNDO = 211
ID_CUT = 212
ID_COPY = 213
ID_PASTE = 214
ID_DELETE = 215
ID_TOOLBAR = 216
ID_STATUS_BAR = 217
ID_OPEN = 218
ID_RENAME = 219
ID_HELP_TOPICS = 226
ID_SYNCHRONIZE_NOW = 245
ID_SYNCHRONIZE_SELECTION = 247
ID_CLOSE = 248
ID_PROPERTIES = 249
ID_LARGE_ICONS = 250
ID_SMALL_ICONS = 251
ID_LIST = 252
ID_DETAILS = 253
ID_REFRESH = 254
ID_ABOUT = 255
ID_PRINT = 257
ID_NEW_FOLDER = 260
ID_CREATE_SHORTCUT = 261
ID_COMMUNICATIONS = 262
ID_PASTE_SHORTCUT = 263
ID_SELECT_ALL = 264
ID_INVERT_SELECTION = 266
ID_ARRANGE_BY_NAME = 267
ID_ARRANGE_BY_TYPE = 268
ID_ARRANGE_BY_SIZE = 269
ID_ARRANGE_BY_DATE = 270
ID_AUTO_ARRANGE = 271
ID_OPTIONS = 273
ID_BACKUP_RESTORE = 274
ID_SYNCHRONIZATION_MANAGER = 281
ID_FILE_CONVERSION = 282
ID_BACK_UP_NOW = 285
ID_ADDRESS = 286
ID_NEXT_PANE = 289
ID_PREVIOUS_PANE = 290
ID_CONTEXT_MENU = 295
ID_CANCEL_MODE = 296
ID_FOLDERS = 302
ID_FREE_STUFF = 304
ID_PRODUCT_NEWS = 305
ID_DEVELOPER_FORUM = 306
ID_FAQ = 307
ID_ONLINE_SUPPORT = 308
ID_WINDOWS_CE_HOME = 309
ID_SEND_FEEDBACK = 310
ID_BEST_OF_THE_WEB = 311
ID_SEARCH_THE_WEB = 312
ID_WEB_TUTORIAL = 313
ID_MICROSOFT_HOME = 314

VIEW_COMMANDS = {ID_LARGE_ICONS: "large", ID_SMALL_ICONS: "small", ID_LIST: "list", ID_DETAILS: "details"}
ARRANGE_COMMANDS = {ID_ARRANGE_BY_NAME: 0, ID_ARRANGE_BY_SIZE: 1, ID_ARRANGE_BY_TYPE: 2, ID_ARRANGE_BY_DATE: 3}
WEB_COMMANDS = [ID_FREE_STUFF, ID_PRODUCT_NEWS, ID_DEVELOPER_FORUM, ID_FAQ, ID_ONLINE_SUPPORT, ID_WINDOWS_CE_HOME,
                ID_SEND_FEEDBACK, ID_BEST_OF_THE_WEB, ID_SEARCH_THE_WEB, ID_WEB_TUTORIAL, ID_MICROSOFT_HOME]

UNAVAILABLE = {ID_UNDO, ID_PRINT, ID_SYNCHRONIZE_SELECTION, ID_FILE_CONVERSION, ID_HELP_TOPICS, ID_AUTO_ARRANGE, *WEB_COMMANDS}

TOOLTIPS = {
    ID_UP: N_("Up One Level  (Bksp)"),
    ID_UNDO: N_("Undo  (Ctrl+Z)"),
    ID_CUT: N_("Cut  (Ctrl+X)"),
    ID_COPY: N_("Copy  (Ctrl+C)"),
    ID_PASTE: N_("Paste  (Ctrl+V)"),
    ID_DELETE: N_("Delete  (Del)"),
    ID_SYNCHRONIZE_NOW: N_("Synchronize Now"),
    ID_SYNCHRONIZE_SELECTION: N_("Synchronize Selection"),
    ID_PROPERTIES: N_("Properties"),
    ID_LARGE_ICONS: N_("Large Icons"),
    ID_SMALL_ICONS: N_("Small Icons"),
    ID_LIST: N_("List"),
    ID_DETAILS: N_("Details"),
    ID_NEW_FOLDER: N_("New Folder"),
    ID_BACK_UP_NOW: N_("Back Up Now"),
    ID_ADDRESS: N_("Go to a different folder"),
    ID_FOLDERS: N_("Show/Hide Folder List"),
}

HELP = {
    ID_UP: N_("Goes to the folder one level up."),
    ID_UNDO: N_("Undoes the last Rename, Copy, or Move."),
    ID_CUT: N_("Removes the selected items and copies them to the Clipboard."),
    ID_COPY: N_("Copies selected items to the Clipboard. Use Paste to put them in a new location."),
    ID_PASTE: N_("Inserts the items you have copied or cut into the selected location."),
    ID_DELETE: N_("Deletes the selected items."),
    ID_TOOLBAR: N_("Shows or hides the toolbar."),
    ID_STATUS_BAR: N_("Shows or hides the status bar."),
    ID_OPEN: N_("Opens the selected folder."),
    ID_RENAME: N_("Renames the selected item."),
    ID_HELP_TOPICS: N_("Opens Help for H/PC Explorer."),
    ID_SYNCHRONIZE_NOW: N_("Synchronizes all the registered databases."),
    ID_SYNCHRONIZE_SELECTION: N_("Synchronizes the selected items."),
    ID_CLOSE: N_("Closes the window."),
    ID_PROPERTIES: N_("Displays properties of the selected items."),
    ID_LARGE_ICONS: N_("Displays items by using large icons."),
    ID_SMALL_ICONS: N_("Displays items by using small icons."),
    ID_LIST: N_("Displays items in a list."),
    ID_DETAILS: N_("Displays information about each item in the window."),
    ID_REFRESH: N_("Refreshes item information."),
    ID_ABOUT: N_("Displays program information, version number, and copyright."),
    ID_PRINT: N_("Converts and prints the selected item."),
    ID_NEW_FOLDER: N_("Creates a new, empty folder."),
    ID_CREATE_SHORTCUT: N_("Creates shortcuts to the selected items."),
    ID_COMMUNICATIONS: N_("Opens communications properties."),
    ID_PASTE_SHORTCUT: N_("Creates shortcuts to the items you have copied or cut into the selected location."),
    ID_SELECT_ALL: N_("Selects all items in the window."),
    ID_INVERT_SELECTION: N_("Reverses which items are selected and which are not."),
    ID_ARRANGE_BY_NAME: N_("Sorts items alphabetically by name."),
    ID_ARRANGE_BY_TYPE: N_("Sorts items by type."),
    ID_ARRANGE_BY_SIZE: N_("Sorts items by size, from smallest to largest."),
    ID_ARRANGE_BY_DATE: N_("Sorts items by date, from oldest to most recent."),
    ID_AUTO_ARRANGE: N_("Arranges the icons automatically."),
    ID_OPTIONS: N_("Changes the display options for the window."),
    ID_BACKUP_RESTORE: N_("Opens backup and restore properties."),
    ID_SYNCHRONIZATION_MANAGER: N_("Opens Synchronization Manager."),
    ID_FILE_CONVERSION: N_("Opens File Converter properties."),
    ID_BACK_UP_NOW: N_("Backs up all H/PC files, data, and settings."),
    ID_FOLDERS: N_("Shows or hides the Folder List."),
    ID_FREE_STUFF: N_("Opens the Handheld PC free stuff page."),
    ID_PRODUCT_NEWS: N_("Opens the Handheld PC product news page."),
    ID_DEVELOPER_FORUM: N_("Opens the Windows CE developers home page."),
    ID_FAQ: N_("Opens the Windows CE FAQ page."),
    ID_ONLINE_SUPPORT: N_("Opens the Windows CE online support page."),
    ID_WINDOWS_CE_HOME: N_("Opens the Windows CE home page."),
    ID_SEND_FEEDBACK: N_("Opens the Windows CE feedback page."),
    ID_BEST_OF_THE_WEB: N_("Opens the Best of the Web page."),
    ID_SEARCH_THE_WEB: N_("Opens the search page."),
    ID_WEB_TUTORIAL: N_("Opens the Web Tutorial page."),
    ID_MICROSOFT_HOME: N_("Opens the Microsoft home page."),
}


def tooltip(identifier):
    return _(TOOLTIPS[identifier])


def help_text(identifier):
    return _(HELP[identifier]) if identifier in HELP else ""
