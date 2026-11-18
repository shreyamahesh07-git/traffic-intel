import os
import sys
import webbrowser
import threading
import time

# Ensure project root is in path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from backend.config import SUMO_HOME, SUMO_BIN
from backend.server import app, sim_manager
import uvicorn

def open_browser():
    time.sleep(1.5)
    print("\n[TRAFFIC INTEL] Opening dashboard in your default browser at http://127.0.0.1:8000 ...")
    webbrowser.open("http://127.0.0.1:8000")

def main():
    print("=" * 65)
    print("      TRAFFIC INTEL — AI ADAPTIVE TRAFFIC MANAGEMENT SYSTEM")
    print("=" * 65)
    print(f"SUMO HOME: {SUMO_HOME}")
    print(f"SUMO BIN : {SUMO_BIN}")
    print("Starting simulation engine and web telemetry server on port 8000...")
    print("Access URL: http://127.0.0.1:8000")
    print("Press CTRL+C in this terminal window to stop the server.")
    print("=" * 65)

    # Automatically start simulation loop
    sim_manager.start_simulation()

    # Launch browser after slight delay
    threading.Thread(target=open_browser, daemon=True).start()

    # Start Uvicorn ASGI server
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

if __name__ == "__main__":
    main()

