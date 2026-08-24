"""Protocol Converter — FastAPI 启动入口"""
import uvicorn
import webbrowser
import threading
import time
import logging
from app import app, VERSION, _check_update_sync

logger = logging.getLogger("update")

def open_browser():
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:8027")

def check_update_on_startup():
    """启动时后台静默检测新版本，只记日志不打扰用户"""
    time.sleep(3)
    try:
        result = _check_update_sync()
        if result.get("error"):
            logger.info(f"[update] {result['error']}")
        elif result.get("available"):
            logger.info(f"[update] 发现新版本 {result['latest']}（当前 {VERSION}）")
        else:
            logger.info(f"[update] 已是最新版本 {VERSION}")
    except Exception as e:
        logger.info(f"[update] 检测异常: {e}")

if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    threading.Thread(target=check_update_on_startup, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8027, reload=False)
