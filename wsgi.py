import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ui.server import wsgi_app, CockpitHandler

# Vercel WSGI entrypoint
app = wsgi_app
application = wsgi_app

class handler(CockpitHandler):
    pass
