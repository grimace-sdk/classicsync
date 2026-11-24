import faulthandler
import json
import os
import sys
from pathlib import Path

import wx

faulthandler.enable()
home = Path(os.environ["CLASSICSYNC_HOME"])
home.mkdir(parents=True, exist_ok=True)
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""), "rapi_proxy": "127.0.0.1:19998",
                                                "frontend": os.environ.get("CLASSICSYNC_FRONTEND", "auto")}))

from classicsync.gui.app import Application

application = Application(False)
wx.CallLater(int(os.environ.get("CLASSICSYNC_IDLE_SECONDS", "45")) * 1000, application.quit)
application.MainLoop()
print("exited cleanly", flush=True)
