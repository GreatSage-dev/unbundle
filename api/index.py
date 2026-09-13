import sys
from pathlib import Path

# Add repo root to sys.path so 'src' imports resolve cleanly
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ui.server import wsgi_app, CockpitHandler

# Vercel WSGI entrypoint
app = wsgi_app
application = wsgi_app

# Vercel BaseHTTPRequestHandler entrypoint
class handler(CockpitHandler):
    pass
