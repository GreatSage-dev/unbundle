import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ui.server import wsgi_app, CockpitHandler, run_server

# Vercel WSGI entrypoints
app = wsgi_app
application = wsgi_app

# Vercel BaseHTTPRequestHandler entrypoint
class handler(CockpitHandler):
    pass

if __name__ == "__main__":
    port_arg = 8765
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port_arg = int(sys.argv[1])
    run_server(port_arg)
