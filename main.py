"""Protocol Converter — FastAPI 启动入口"""
import uvicorn
import webbrowser
import threading
import time
from app import app

def open_browser():
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:8027")

if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8027, reload=False)
