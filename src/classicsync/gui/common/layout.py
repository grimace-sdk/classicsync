import wx

DROP_DOWN_CLASSES = (wx.ComboBox, wx.Choice)
LABELLED_CLASSES = (wx.Button, wx.CheckBox, wx.RadioButton)
MINIMUM_FONT_SCALE = 0.8
FONT_STEP = 0.5
BUTTON_MARGIN = 6
ELLIPSIS = "..."
WRAP_MARGIN = 2


def dialog_rect(parent, x, y, width, height):
    position = parent.ConvertDialogToPixels(wx.Point(x, y))
    size = parent.ConvertDialogToPixels(wx.Size(width, height))
    return position, size


def place(parent, control_class, x, y, width, height, *args, **kwargs):
    position, size = dialog_rect(parent, x, y, width, height)
    identifier = kwargs.pop("id", wx.ID_ANY)
    if control_class in DROP_DOWN_CLASSES:
        size = wx.Size(size.width, -1)
    control = control_class(parent, identifier, *args, pos=position, size=size, **kwargs)
    if control_class is wx.StaticText and height > 10:
        fit_wrapped_text(control, size)
    elif control_class in LABELLED_CLASSES:
        fit_label(control, size.width)
    return control


def smaller_font_sizes(control):
    original_size = control.GetFont().GetFractionalPointSize()
    size = original_size - FONT_STEP
    while size >= original_size * MINIMUM_FONT_SCALE:
        yield size
        size -= FONT_STEP


def set_font_size(control, point_size):
    font = control.GetFont()
    font.SetFractionalPointSize(point_size)
    control.SetFont(font)


def line_height(control):
    return control.GetTextExtent("Ag").height


def wrapped_lines(control, text, width):
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if line and control.GetTextExtent(candidate).width > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


def wrap_width(control, size):
    return size.width - control.ConvertDialogToPixels(wx.Size(WRAP_MARGIN, 0)).width


def fits(control, text, size):
    return len(wrapped_lines(control, text, wrap_width(control, size))) * line_height(control) <= size.height


def fit_wrapped_text(control, size):
    label = control.GetLabel()
    for point_size in smaller_font_sizes(control):
        if fits(control, label, size):
            break
        set_font_size(control, point_size)
    if fits(control, label, size):
        control.SetLabel("\n".join(wrapped_lines(control, label, wrap_width(control, size))))
    else:
        control.SetLabel(ellipsized(control, label, size))
    control.SetSize(size)


def ellipsized(control, text, size):
    lines = wrapped_lines(control, text, wrap_width(control, size))
    kept = lines[:max(1, size.height // line_height(control))]
    dc = wx.ClientDC(control)
    dc.SetFont(control.GetFont())
    kept[-1] = wx.Control.Ellipsize(kept[-1] + ELLIPSIS, dc, wx.ELLIPSIZE_END, wrap_width(control, size))
    return "\n".join(kept)


def label_width(control):
    text_width = control.GetTextExtent(wx.StripMenuCodes(control.GetLabel())).width
    if isinstance(control, wx.Button):
        return text_width + 2 * control.ConvertDialogToPixels(wx.Size(BUTTON_MARGIN, 0)).width
    return control.GetBestSize().width


def fit_label(control, width):
    if not control.GetLabel():
        return
    for point_size in smaller_font_sizes(control):
        if label_width(control) <= width:
            break
        set_font_size(control, point_size)


def dialog_size(parent, width, height):
    return parent.ConvertDialogToPixels(wx.Size(width, height))


def bold(control, scale=1.0):
    font = control.GetFont()
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    if scale != 1.0:
        font.SetFractionalPointSize(font.GetFractionalPointSize() * scale)
    control.SetFont(font)
    return control
