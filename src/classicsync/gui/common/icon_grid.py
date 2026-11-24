import time

import wx

GRID_PLATFORMS = ("__WXMAC__", "__WXGTK__", "__WXQT__", "__WXX11__")
VIEW_BITS = wx.LC_ICON | wx.LC_SMALL_ICON | wx.LC_LIST | wx.LC_REPORT

MODE_LARGE = "large"
MODE_SMALL = "small"

LARGE_ICON_SIZE = 32
SMALL_ICON_SIZE = 16
LARGE_CELL_DIALOG_WIDTH = 50
LARGE_ICON_TOP = 4
LARGE_LABEL_GAP = 4
LARGE_LABEL_LINES = 2
SMALL_CELL_MINIMUM_DIALOG_WIDTH = 74
SMALL_CELL_MAXIMUM_DIALOG_WIDTH = 134
SMALL_LABEL_GAP = 3
SMALL_ROW_PADDING = 3
GRID_MARGIN = 4
LABEL_PADDING = 2
SCROLL_UNIT = 8
TYPE_AHEAD_SECONDS = 1.0
TINT_FRACTION = 0.5
BAND_ALPHA = 60
ELLIPSIS = "..."


def grid_supported():
    return wx.Platform in GRID_PLATFORMS


def is_grid_style(style):
    return grid_supported() and bool(style & (wx.LC_ICON | wx.LC_SMALL_ICON))


def blend_bitmap(bitmap, colour, fraction):
    image = bitmap.ConvertToImage()
    mask = (image.GetMaskRed(), image.GetMaskGreen(), image.GetMaskBlue()) if image.HasMask() else None
    data = bytearray(image.GetData())
    target = (colour.Red(), colour.Green(), colour.Blue())
    for offset in range(0, len(data), 3):
        if mask and tuple(data[offset:offset + 3]) == mask:
            continue
        for channel in range(3):
            data[offset + channel] = int(data[offset + channel] * (1 - fraction) + target[channel] * fraction)
    image.SetData(bytes(data))
    return wx.Bitmap(image)


def break_word(dc, word, width):
    pieces = []
    piece = ""
    for character in word:
        if piece and dc.GetTextExtent(piece + character).width > width:
            pieces.append(piece)
            piece = character
        else:
            piece += character
    pieces.append(piece)
    return pieces


def wrap_text(dc, text, width):
    lines = []
    line = ""
    for word in text.split(" "):
        candidate = f"{line} {word}" if line else word
        if dc.GetTextExtent(candidate).width <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        pieces = break_word(dc, word, width) if dc.GetTextExtent(word).width > width else [word]
        lines.extend(pieces[:-1])
        line = pieces[-1]
    lines.append(line)
    return lines


def ellipsize(dc, text, width):
    if dc.GetTextExtent(text).width <= width:
        return text
    return wx.Control.Ellipsize(text, dc, wx.ELLIPSIZE_END, width)


def limit_lines(dc, lines, width, maximum):
    if len(lines) <= maximum:
        return lines
    kept = lines[:maximum]
    remainder = " ".join(lines[maximum - 1:])
    kept[-1] = wx.Control.Ellipsize(remainder + ELLIPSIS, dc, wx.ELLIPSIZE_END, width)
    return kept


class GridListEvent(wx.ListEvent):
    def __init__(self, event_type, identifier, index, label="", cancelled=False):
        super().__init__(event_type, identifier)
        self.SetIndex(index)
        item = wx.ListItem()
        item.SetId(index)
        item.SetText(label)
        self.SetItem(item)
        self.edit_cancelled = cancelled

    def IsEditCancelled(self):
        return self.edit_cancelled


class GridItem:
    def __init__(self, label, image):
        self.label = label
        self.image = image


class IconGridView(wx.ScrolledWindow):
    def __init__(self, parent, mode=MODE_LARGE, single_selection=False, editable=False):
        super().__init__(parent, style=wx.WANTS_CHARS | wx.BORDER_NONE | wx.VSCROLL)
        self.mode = mode
        self.single_selection = single_selection
        self.editable = editable
        self.items = []
        self.selected = set()
        self.focused = -1
        self.anchor = -1
        self.image_lists = {}
        self.bitmap_cache = {}
        self.wrap_cache = {}
        self.layout_pending = False
        self.small_cell_width = None
        self.band_origin = None
        self.band_rect = None
        self.band_initial = set()
        self.band_toggle = False
        self.pending_single_select = -1
        self.type_ahead = ""
        self.type_ahead_time = 0.0
        self.editor = None
        self.editing_index = -1
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetScrollRate(0, SCROLL_UNIT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_left_double_click)
        self.Bind(wx.EVT_RIGHT_DOWN, self._on_right_down)
        self.Bind(wx.EVT_RIGHT_UP, self._on_right_up)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.Bind(wx.EVT_CHAR, self._on_char)
        self.Bind(wx.EVT_SET_FOCUS, self._on_focus_changed)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_focus_changed)
        self.Bind(wx.EVT_SYS_COLOUR_CHANGED, self._on_colours_changed)
        self.Bind(wx.EVT_SCROLLWIN, self._on_scroll)

    def set_mode(self, mode):
        if mode != self.mode:
            self.mode = mode
            self.wrap_cache.clear()
            self._schedule_layout()

    def SetImageList(self, image_list, which):
        self.image_lists[which] = image_list
        self.bitmap_cache.clear()
        self.Refresh()

    def GetItemCount(self):
        return len(self.items)

    def InsertItem(self, index, label, image=-1):
        index = max(0, min(index, len(self.items)))
        self.items.insert(index, GridItem(label, image))
        self.selected = {position + 1 if position >= index else position for position in self.selected}
        if self.focused >= index:
            self.focused += 1
        self._schedule_layout()
        return index

    def SetItem(self, index, column, label, image=-1):
        if column != 0 or not 0 <= index < len(self.items):
            return True
        self.items[index].label = label
        if image != -1:
            self.items[index].image = image
        self._schedule_layout()
        return True

    def GetItemText(self, index, column=0):
        return self.items[index].label if 0 <= index < len(self.items) and column == 0 else ""

    def GetItemImage(self, index):
        return self.items[index].image if 0 <= index < len(self.items) else -1

    def DeleteAllItems(self):
        self._finish_edit(True)
        self.items = []
        self.selected = set()
        self.focused = -1
        self.anchor = -1
        self.wrap_cache.clear()
        self._schedule_layout()
        return True

    def IsSelected(self, index):
        return index in self.selected

    def Select(self, index, on=True):
        if not 0 <= index < len(self.items):
            return
        if on:
            wanted = {index} if self.single_selection else self.selected | {index}
            if self.focused < 0:
                self.focused = index
                self.anchor = index
        else:
            wanted = self.selected - {index}
        self._set_selection(wanted)

    def GetFirstSelected(self):
        return min(self.selected) if self.selected else -1

    def GetNextSelected(self, index):
        following = [position for position in self.selected if position > index]
        return min(following) if following else -1

    def GetSelectedItemCount(self):
        return len(self.selected)

    def GetFocusedItem(self):
        return self.focused

    def Focus(self, index):
        if 0 <= index < len(self.items):
            self.focused = index
            self.EnsureVisible(index)
            self.Refresh()

    def EnsureVisible(self, index):
        if not 0 <= index < len(self.items):
            return
        rect = self._cell_rect(index)
        top = self.GetViewStart()[1] * SCROLL_UNIT
        height = self.GetClientSize().height
        if rect.GetTop() < top:
            self.Scroll(-1, max(0, rect.GetTop() - GRID_MARGIN) // SCROLL_UNIT)
        elif rect.GetBottom() > top + height:
            self.Scroll(-1, (rect.GetBottom() - height + GRID_MARGIN + SCROLL_UNIT) // SCROLL_UNIT)

    def EditLabel(self, index):
        if not 0 <= index < len(self.items):
            return None
        self._finish_edit(False)
        self.EnsureVisible(index)
        self.editing_index = index
        cell = self._cell_rect(index)
        line_height = self._line_height()
        if self.mode == MODE_LARGE:
            label = self._label_rect(index, expanded=False)
            position = wx.Point(cell.GetLeft() + 1, label.GetTop() - 2)
            size = wx.Size(cell.GetWidth() - 2, line_height + 6)
        else:
            left = cell.GetLeft() + SMALL_ICON_SIZE + SMALL_LABEL_GAP
            position = wx.Point(left, cell.GetTop())
            size = wx.Size(cell.GetRight() - left, max(line_height + 6, cell.GetHeight()))
        self.editor = wx.TextCtrl(self, value=self.items[index].label, pos=self.CalcScrolledPosition(position), size=size,
                                  style=wx.TE_PROCESS_ENTER)
        self.editor.SetSelection(-1, -1)
        self.editor.SetFocus()
        self.editor.Bind(wx.EVT_TEXT_ENTER, lambda event: self._finish_edit(False))
        self.editor.Bind(wx.EVT_KEY_DOWN, self._on_editor_key)
        self.editor.Bind(wx.EVT_KILL_FOCUS, self._on_editor_focus_lost)
        return self.editor

    def _on_editor_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._finish_edit(True)
        else:
            event.Skip()

    def _on_editor_focus_lost(self, event):
        event.Skip()
        wx.CallAfter(self._finish_edit, False)

    def _finish_edit(self, cancelled):
        editor = self.editor
        if not editor:
            return
        self.editor = None
        index = self.editing_index
        label = editor.GetValue()
        editor.Hide()
        wx.CallAfter(editor.Destroy)
        if not self:
            return
        event = self._post(wx.wxEVT_LIST_END_LABEL_EDIT, index, label, cancelled)
        if not cancelled and event.IsAllowed() and 0 <= index < len(self.items):
            self.items[index].label = label
            self.wrap_cache.clear()
        self.SetFocus()
        self.Refresh()

    def _post(self, event_type, index, label="", cancelled=False):
        event = GridListEvent(event_type, self.GetId(), index, label, cancelled)
        event.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(event)
        return event

    def _set_selection(self, wanted):
        removed = sorted(self.selected - wanted)
        added = sorted(wanted - self.selected)
        if not removed and not added:
            return
        self.selected = set(wanted)
        self.Refresh()
        for index in removed:
            self._post(wx.wxEVT_LIST_ITEM_DESELECTED, index, self.GetItemText(index))
        for index in added:
            self._post(wx.wxEVT_LIST_ITEM_SELECTED, index, self.GetItemText(index))

    def _activate(self, index):
        if 0 <= index < len(self.items):
            self._post(wx.wxEVT_LIST_ITEM_ACTIVATED, index, self.GetItemText(index))

    def _schedule_layout(self):
        self.small_cell_width = None
        if not self.layout_pending:
            self.layout_pending = True
            wx.CallAfter(self._update_layout)
        self.Refresh()

    def _update_layout(self):
        self.layout_pending = False
        if not self:
            return
        rows = self._row_count()
        height = GRID_MARGIN * 2 + rows * self._cell_size().height
        self.SetVirtualSize(wx.Size(self.GetClientSize().width, height))
        self.Refresh()

    def dialog_width(self, dialog_units):
        return self.ConvertDialogToPixels(wx.Size(dialog_units, 0)).width

    def _line_height(self):
        return self.GetTextExtent("Ag").height

    def _measure_context(self):
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        return dc

    def _cell_size(self):
        line_height = self._line_height()
        if self.mode == MODE_LARGE:
            height = LARGE_ICON_TOP + LARGE_ICON_SIZE + LARGE_LABEL_GAP + LARGE_LABEL_LINES * line_height + LABEL_PADDING * 2 + 4
            return wx.Size(self.dialog_width(LARGE_CELL_DIALOG_WIDTH), height)
        if self.small_cell_width is None:
            dc = self._measure_context()
            widest = max((dc.GetTextExtent(item.label).width for item in self.items), default=0)
            width = SMALL_ICON_SIZE + SMALL_LABEL_GAP + widest + LABEL_PADDING * 2 + 8
            self.small_cell_width = max(self.dialog_width(SMALL_CELL_MINIMUM_DIALOG_WIDTH),
                                        min(self.dialog_width(SMALL_CELL_MAXIMUM_DIALOG_WIDTH), width))
        return wx.Size(self.small_cell_width, max(SMALL_ICON_SIZE, line_height) + SMALL_ROW_PADDING * 2)

    def _column_count(self):
        width = self.GetClientSize().width - GRID_MARGIN * 2
        return max(1, width // self._cell_size().width)

    def _row_count(self):
        columns = self._column_count()
        return (len(self.items) + columns - 1) // columns

    def _cell_rect(self, index):
        size = self._cell_size()
        columns = self._column_count()
        row, column = divmod(index, columns)
        return wx.Rect(GRID_MARGIN + column * size.width, GRID_MARGIN + row * size.height, size.width, size.height)

    def _icon_rect(self, index):
        cell = self._cell_rect(index)
        if self.mode == MODE_LARGE:
            return wx.Rect(cell.GetLeft() + (cell.GetWidth() - LARGE_ICON_SIZE) // 2, cell.GetTop() + LARGE_ICON_TOP,
                           LARGE_ICON_SIZE, LARGE_ICON_SIZE)
        return wx.Rect(cell.GetLeft() + 1, cell.GetTop() + (cell.GetHeight() - SMALL_ICON_SIZE) // 2, SMALL_ICON_SIZE, SMALL_ICON_SIZE)

    def _label_lines(self, dc, index, expanded):
        item = self.items[index]
        width = self._label_width()
        key = (item.label, width, self.mode, expanded)
        if key not in self.wrap_cache:
            if self.mode == MODE_LARGE:
                lines = wrap_text(dc, item.label, width)
                self.wrap_cache[key] = lines if expanded else limit_lines(dc, lines, width, LARGE_LABEL_LINES)
            else:
                self.wrap_cache[key] = [ellipsize(dc, item.label, width)]
        return self.wrap_cache[key]

    def _label_width(self):
        cell = self._cell_size()
        if self.mode == MODE_LARGE:
            return cell.width - LABEL_PADDING * 2 - 4
        return cell.width - SMALL_ICON_SIZE - SMALL_LABEL_GAP - LABEL_PADDING * 2 - 4

    def _label_rect(self, index, expanded, dc=None):
        dc = dc or self._measure_context()
        lines = self._label_lines(dc, index, expanded)
        line_height = self._line_height()
        text_width = max((dc.GetTextExtent(line).width for line in lines), default=0)
        cell = self._cell_rect(index)
        if self.mode == MODE_LARGE:
            width = text_width + LABEL_PADDING * 2
            top = cell.GetTop() + LARGE_ICON_TOP + LARGE_ICON_SIZE + LARGE_LABEL_GAP
            return wx.Rect(cell.GetLeft() + (cell.GetWidth() - width) // 2, top, width, len(lines) * line_height + LABEL_PADDING)
        left = cell.GetLeft() + SMALL_ICON_SIZE + SMALL_LABEL_GAP
        return wx.Rect(left, cell.GetTop() + (cell.GetHeight() - line_height - LABEL_PADDING) // 2, text_width + LABEL_PADDING * 2,
                       line_height + LABEL_PADDING)

    def _hit_rect(self, index, dc=None):
        return self._icon_rect(index).Union(self._label_rect(index, False, dc))

    def HitTest(self, point):
        logical = self.CalcUnscrolledPosition(point)
        if not self.items:
            return -1
        size = self._cell_size()
        column = (logical.x - GRID_MARGIN) // size.width
        row = (logical.y - GRID_MARGIN) // size.height
        if logical.x < GRID_MARGIN or logical.y < GRID_MARGIN or column >= self._column_count():
            return -1
        index = row * self._column_count() + column
        if not 0 <= index < len(self.items):
            return -1
        return index if self._hit_rect(index).Contains(logical) else -1

    def _visible_indices(self):
        size = self._cell_size()
        top = self.GetViewStart()[1] * SCROLL_UNIT
        height = self.GetClientSize().height
        columns = self._column_count()
        first_row = max(0, (top - GRID_MARGIN) // size.height - 1)
        last_row = (top + height - GRID_MARGIN) // size.height + 1
        return range(first_row * columns, min(len(self.items), (last_row + 1) * columns))

    def _bitmap(self, index, tinted):
        image = self.items[index].image
        which = wx.IMAGE_LIST_NORMAL if self.mode == MODE_LARGE else wx.IMAGE_LIST_SMALL
        image_list = self.image_lists.get(which)
        if image_list is None or not 0 <= image < image_list.GetImageCount():
            return None
        key = (which, image, tinted)
        if key not in self.bitmap_cache:
            bitmap = image_list.GetBitmap(image)
            if tinted and bitmap.IsOk():
                bitmap = blend_bitmap(bitmap, wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT), TINT_FRACTION)
            self.bitmap_cache[key] = bitmap
        return self.bitmap_cache[key]

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        self.DoPrepareDC(dc)
        background = self.GetBackgroundColour() if self.UseBgCol() else wx.SystemSettings.GetColour(wx.SYS_COLOUR_LISTBOX)
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        dc.SetFont(self.GetFont())
        focused_expanded = -1
        for index in self._visible_indices():
            if index == self.focused and index in self.selected and self.mode == MODE_LARGE and self.HasFocus():
                focused_expanded = index
                continue
            self._draw_item(dc, index, False)
        if focused_expanded >= 0:
            self._draw_item(dc, focused_expanded, True)
        if self.band_rect:
            self._draw_band(dc)

    def _draw_item(self, dc, index, expanded):
        has_focus = self.HasFocus() or (self.editor is not None)
        selected = index in self.selected
        bitmap = self._bitmap(index, selected and has_focus)
        icon = self._icon_rect(index)
        if bitmap and bitmap.IsOk():
            dc.DrawBitmap(bitmap, icon.GetLeft() + (icon.GetWidth() - bitmap.GetWidth()) // 2,
                          icon.GetTop() + (icon.GetHeight() - bitmap.GetHeight()) // 2, True)
        if index == self.editing_index and self.editor:
            return
        label = self._label_rect(index, expanded, dc)
        lines = self._label_lines(dc, index, expanded)
        if selected:
            if has_focus:
                fill = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
                ink = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT)
            else:
                fill = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE)
                ink = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT)
            dc.SetBrush(wx.Brush(fill))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(label)
        else:
            ink = self.GetForegroundColour() if self.UseForegroundColour() else wx.SystemSettings.GetColour(wx.SYS_COLOUR_LISTBOXTEXT)
        dc.SetTextForeground(ink)
        line_height = self._line_height()
        for number, line in enumerate(lines):
            width = dc.GetTextExtent(line).width
            if self.mode == MODE_LARGE:
                left = label.GetLeft() + (label.GetWidth() - width) // 2
            else:
                left = label.GetLeft() + LABEL_PADDING
            dc.DrawText(line, left, label.GetTop() + LABEL_PADDING // 2 + number * line_height)
        if index == self.focused and has_focus:
            wx.RendererNative.Get().DrawFocusRect(self, dc, label)

    def _draw_band(self, dc):
        colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        context = wx.GraphicsContext.Create(dc)
        if context is None:
            return
        context.SetBrush(wx.Brush(wx.Colour(colour.Red(), colour.Green(), colour.Blue(), BAND_ALPHA)))
        context.SetPen(wx.Pen(colour, 1))
        rect = self.band_rect
        context.DrawRectangle(rect.GetLeft(), rect.GetTop(), rect.GetWidth(), rect.GetHeight())

    def _on_size(self, event):
        self.wrap_cache.clear()
        self._update_layout()
        event.Skip()

    def _on_scroll(self, event):
        self._finish_edit(False)
        event.Skip()

    def _on_focus_changed(self, event):
        self.Refresh()
        event.Skip()

    def _on_colours_changed(self, event):
        self.bitmap_cache.clear()
        self.Refresh()
        event.Skip()

    def _toggle_modifier(self, event):
        return event.CmdDown() or event.ControlDown()

    def _on_left_down(self, event):
        self._finish_edit(False)
        self.SetFocus()
        index = self.HitTest(event.GetPosition())
        self.pending_single_select = -1
        multiple = not self.single_selection
        if index >= 0:
            if multiple and self._toggle_modifier(event):
                self.focused = index
                self.anchor = index
                self._set_selection(self.selected ^ {index})
            elif multiple and event.ShiftDown() and self.anchor >= 0:
                self.focused = index
                low, high = sorted((self.anchor, index))
                self._set_selection(set(range(low, high + 1)))
            elif index in self.selected:
                self.focused = index
                self.anchor = index
                self.pending_single_select = index
                self.Refresh()
            else:
                self.focused = index
                self.anchor = index
                self._set_selection({index})
            return
        self.band_origin = self.CalcUnscrolledPosition(event.GetPosition())
        self.band_toggle = multiple and (self._toggle_modifier(event) or event.ShiftDown())
        if not self.band_toggle:
            self._set_selection(set())
        self.band_initial = set(self.selected)
        if not self.HasCapture():
            self.CaptureMouse()

    def _on_left_up(self, event):
        if self.pending_single_select >= 0:
            self._set_selection({self.pending_single_select})
            self.pending_single_select = -1
        self._end_band()

    def _end_band(self):
        if self.HasCapture():
            self.ReleaseMouse()
        if self.band_rect:
            self.band_rect = None
            self.Refresh()
        self.band_origin = None

    def _on_capture_lost(self, event):
        self.band_origin = None
        self.band_rect = None
        self.Refresh()

    def _on_motion(self, event):
        if self.band_origin is None or not event.LeftIsDown():
            return
        position = event.GetPosition()
        height = self.GetClientSize().height
        if position.y < 0:
            self.Scroll(-1, max(0, self.GetViewStart()[1] - 1))
        elif position.y > height:
            self.Scroll(-1, self.GetViewStart()[1] + 1)
        current = self.CalcUnscrolledPosition(position)
        self.band_rect = wx.Rect(wx.Point(min(self.band_origin.x, current.x), min(self.band_origin.y, current.y)),
                                 wx.Point(max(self.band_origin.x, current.x), max(self.band_origin.y, current.y)))
        if self.single_selection:
            self.Refresh()
            return
        dc = self._measure_context()
        inside = {index for index in range(len(self.items)) if self._hit_rect(index, dc).Intersects(self.band_rect)}
        wanted = self.band_initial ^ inside if self.band_toggle else inside
        if inside and (self.focused not in inside):
            self.focused = min(inside)
            self.anchor = self.focused
        self._set_selection(wanted)
        self.Refresh()

    def _on_left_double_click(self, event):
        index = self.HitTest(event.GetPosition())
        if index >= 0:
            self._activate(index)

    def _on_right_down(self, event):
        self._finish_edit(False)
        self.SetFocus()
        index = self.HitTest(event.GetPosition())
        if index >= 0:
            self.focused = index
            if index not in self.selected:
                self.anchor = index
                self._set_selection({index})
            self.Refresh()
        else:
            self._set_selection(set())

    def _on_right_up(self, event):
        self._show_context_menu(self.ClientToScreen(event.GetPosition()))

    def _show_context_menu(self, position):
        event = wx.ContextMenuEvent(wx.wxEVT_CONTEXT_MENU, self.GetId(), position)
        event.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(event)

    def _move_focus(self, index, event):
        if not self.items:
            return
        index = max(0, min(len(self.items) - 1, index))
        self.focused = index
        if event.ShiftDown() and not self.single_selection and self.anchor >= 0:
            low, high = sorted((self.anchor, index))
            self._set_selection(set(range(low, high + 1)))
        elif self._toggle_modifier(event) and not self.single_selection:
            self.Refresh()
        else:
            self.anchor = index
            self._set_selection({index})
        self.EnsureVisible(index)

    def _page_items(self):
        rows = max(1, self.GetClientSize().height // self._cell_size().height)
        return rows * self._column_count()

    def _on_key_down(self, event):
        key = event.GetKeyCode()
        columns = self._column_count()
        current = self.focused if self.focused >= 0 else -1
        moves = {
            wx.WXK_LEFT: current - 1, wx.WXK_RIGHT: current + 1, wx.WXK_UP: current - columns, wx.WXK_DOWN: current + columns,
            wx.WXK_HOME: 0, wx.WXK_END: len(self.items) - 1,
            wx.WXK_PAGEUP: current - self._page_items(), wx.WXK_PAGEDOWN: current + self._page_items(),
            wx.WXK_NUMPAD_LEFT: current - 1, wx.WXK_NUMPAD_RIGHT: current + 1, wx.WXK_NUMPAD_UP: current - columns,
            wx.WXK_NUMPAD_DOWN: current + columns,
        }
        if event.AltDown():
            event.Skip()
            return
        if key in moves:
            if not self.items:
                return
            target = 0 if current < 0 else moves[key]
            if key in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_NUMPAD_UP, wx.WXK_NUMPAD_DOWN) and not 0 <= target < len(self.items):
                target = current
            self._move_focus(target, event)
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and not event.HasAnyModifiers():
            if self.focused >= 0 and self.focused in self.selected:
                self._activate(self.focused)
        elif key == wx.WXK_SPACE and self._toggle_modifier(event) and self.focused >= 0:
            wanted = self.selected ^ {self.focused} if not self.single_selection else {self.focused}
            self._set_selection(wanted)
        elif key in (wx.WXK_MENU, wx.WXK_WINDOWS_MENU):
            self._show_keyboard_context_menu()
        elif key == wx.WXK_TAB and not event.ControlDown():
            self.Navigate(wx.NavigationKeyEvent.IsBackward if event.ShiftDown() else wx.NavigationKeyEvent.IsForward)
        else:
            event.Skip()

    def _show_keyboard_context_menu(self):
        if self.focused >= 0 and self.focused in self.selected:
            rect = self._icon_rect(self.focused)
            point = self.CalcScrolledPosition(wx.Point(rect.GetLeft() + rect.GetWidth() // 2, rect.GetBottom()))
        else:
            point = wx.Point(GRID_MARGIN, GRID_MARGIN)
        self._show_context_menu(self.ClientToScreen(point))

    def _on_char(self, event):
        character = event.GetUnicodeKey()
        if character == wx.WXK_NONE or character < 32 or event.ControlDown() or event.CmdDown() or event.AltDown() or not self.items:
            event.Skip()
            return
        now = time.monotonic()
        if now - self.type_ahead_time > TYPE_AHEAD_SECONDS:
            self.type_ahead = ""
        self.type_ahead_time = now
        self.type_ahead += chr(character).lower()
        repeated = set(self.type_ahead) == {self.type_ahead[0]}
        prefix = self.type_ahead[0] if repeated else self.type_ahead
        start = self.focused + 1 if repeated else max(self.focused, 0)
        count = len(self.items)
        for offset in range(count):
            index = (start + offset) % count
            if self.items[index].label.lower().startswith(prefix):
                self.focused = index
                self.anchor = index
                self._set_selection({index})
                self.EnsureVisible(index)
                return


class ForwardingFileDrop(wx.FileDropTarget):
    def __init__(self, view):
        super().__init__()
        self.view = view

    def OnDropFiles(self, x, y, filenames):
        target = self.view.file_drop_target
        return bool(target and target.OnDropFiles(x, y, filenames))


class ItemListView(wx.Panel):
    def __init__(self, parent, style=wx.LC_REPORT):
        super().__init__(parent)
        self.view_style = style
        self.file_drop_target = None
        self.list = wx.ListCtrl(self, style=style)
        self.grid = None
        if grid_supported():
            self.grid = IconGridView(self, MODE_SMALL if style & wx.LC_SMALL_ICON else MODE_LARGE,
                                     single_selection=bool(style & wx.LC_SINGLE_SEL), editable=bool(style & wx.LC_EDIT_LABELS))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.list, 1, wx.EXPAND)
        if self.grid:
            sizer.Add(self.grid, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self.active = self.list
        self._show_active(self.grid if is_grid_style(style) else self.list)

    def _show_active(self, view):
        for candidate in (self.list, self.grid):
            if candidate is not None:
                candidate.Show(candidate is view)
        self.active = view
        self.Layout()

    def _transfer_items(self, source, target):
        rows = [(source.GetItemText(index), self._item_image(source, index), source.IsSelected(index))
                for index in range(source.GetItemCount())]
        focused = source.GetFocusedItem()
        target.DeleteAllItems()
        if target is self.list and self.view_style & wx.LC_REPORT and not self.list.GetColumnCount():
            return
        for index, (label, image, selected) in enumerate(rows):
            target.InsertItem(index, label, image)
        for index, (label, image, selected) in enumerate(rows):
            if selected:
                target.Select(index)
        if 0 <= focused < len(rows):
            target.Focus(focused)

    def _item_image(self, source, index):
        if source is self.grid:
            return source.GetItemImage(index)
        return source.GetItem(index).GetImage()

    def GetWindowStyleFlag(self):
        return self.view_style

    def SetWindowStyleFlag(self, style):
        self.view_style = style
        if is_grid_style(style):
            self.grid.set_mode(MODE_SMALL if style & wx.LC_SMALL_ICON else MODE_LARGE)
            self.grid.single_selection = bool(style & wx.LC_SINGLE_SEL)
            self.grid.editable = bool(style & wx.LC_EDIT_LABELS)
            if self.active is not self.grid:
                self._transfer_items(self.list, self.grid)
                self._show_active(self.grid)
            return
        if self.active is not self.list:
            self.list.SetWindowStyleFlag(style)
            self._transfer_items(self.grid, self.list)
            self._show_active(self.list)
        else:
            self.list.SetWindowStyleFlag(style)

    def SetDropTarget(self, target):
        self.file_drop_target = target
        self.list.SetDropTarget(ForwardingFileDrop(self))
        if self.grid:
            self.grid.SetDropTarget(ForwardingFileDrop(self))

    def SetFocus(self):
        self.active.SetFocus()

    def HasFocus(self):
        return self.active.HasFocus()

    def SetImageList(self, image_list, which):
        self.list.SetImageList(image_list, which)
        if self.grid:
            self.grid.SetImageList(image_list, which)

    def InsertColumn(self, *args, **kwargs):
        return self.list.InsertColumn(*args, **kwargs)

    def GetColumnCount(self):
        return self.list.GetColumnCount()

    def InsertItem(self, index, label, image=-1):
        if self.active is self.grid:
            return self.grid.InsertItem(index, label, image)
        return self.list.InsertItem(index, label, image)

    def SetItem(self, index, column, label, image=-1):
        return self.active.SetItem(index, column, label, image)

    def GetItemText(self, index, column=0):
        return self.active.GetItemText(index, column)

    def GetItemCount(self):
        return self.active.GetItemCount()

    def DeleteAllItems(self):
        return self.active.DeleteAllItems()

    def Select(self, index, on=True):
        self.active.Select(index, on)

    def IsSelected(self, index):
        return self.active.IsSelected(index)

    def GetFirstSelected(self):
        return self.active.GetFirstSelected()

    def GetNextSelected(self, index):
        return self.active.GetNextSelected(index)

    def GetSelectedItemCount(self):
        return self.active.GetSelectedItemCount()

    def GetFocusedItem(self):
        return self.active.GetFocusedItem()

    def Focus(self, index):
        self.active.Focus(index)

    def EnsureVisible(self, index):
        self.active.EnsureVisible(index)

    def EditLabel(self, index):
        return self.active.EditLabel(index)
