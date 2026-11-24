class ConversionError(ValueError):
    pass


class Report:
    def __init__(self):
        self.warnings = []

    def lost(self, message):
        if message not in self.warnings:
            self.warnings.append(message)
