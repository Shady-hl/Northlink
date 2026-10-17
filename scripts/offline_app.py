"""Launch Streamlit while blocking outbound Python socket connections and DNS.

This is a software-level smoke-test mode, not a claim that laptop Wi-Fi is off.
Usage: .venv/bin/python scripts/offline_app.py --server.port 8513
"""
import ipaddress
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def local(host):
    if host in ("localhost", "", None):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def audit(event, args):
    if event == "socket.getaddrinfo" and not local(args[0]):
        raise OSError("Offline test: external name lookup blocked")
    if event == "socket.connect":
        address = args[1]
        if isinstance(address, tuple) and not local(address[0]):
            raise OSError("Offline test: external connection blocked")


sys.addaudithook(audit)
sys.argv = ["streamlit", "run", str(ROOT / "app.py"), *sys.argv[1:]]
runpy.run_module("streamlit", run_name="__main__")
