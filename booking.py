# booking.py (Modified to support Standalone execution)

import logging
from typing import Mapping, Any, Optional, Union, List, Dict, Tuple # 確保 Tuple 導入
import threading
from time import sleep
import requests
import os
from requests.sessions import Session
from requests.adapters import HTTPAdapter
# from requests.models import Response
import time
from config import *
from bs4 import BeautifulSoup
from PIL import Image
import io
import ddddocr
import random
import re

# ----------------------------------------------------------------------------
# Global Variables (保持不變)
# ----------------------------------------------------------------------------
booking_OK = 0
booking_NG = 0

# Initialize ddddocr
ocr = ddddocr.DdddOcr(show_ad=False)

# ----------------------------------------------------------------------------
# Common Functions (保持不變)
# ----------------------------------------------------------------------------

def sleep_range(a, b):
    sec = random.uniform(a, b)
    sleep(sec)

# ----------------------------------------------------------------------------
# Session Initialization (保持不變)
# ----------------------------------------------------------------------------

def session_init():
    # ... (與原 proxy.py 中的 session_init 內容相同) ...
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=session_max_retries))
    session.mount("http://", HTTPAdapter(max_retries=session_max_retries))

    if (PROXY_ENABLE):
        # Configure proxy settings
        PROXY = PROXY_SERVER
        session.proxies.update({
            "http": PROXY,
            "https": PROXY,
        })
    # ... (省略 session headers 設定) ...
    return session

# ----------------------------------------------------------------------------
# Entry Function for THSR Booking System (保持不變)
# ----------------------------------------------------------------------------

logger = logging.getLogger(__name__)
# 配置 logger 格式
FORMAT = '[%(asctime)s][%(levelname)s][%(funcName)s]: %(message)s'
logging.basicConfig(level=logging.INFO, format=FORMAT)


def thsr_run_booking_flow_with_data(
    task_id: str, 
    task_data: Dict[str, Any], 
    cancel_event: threading.Event,
    status_updater: callable
) -> Tuple[bool, str]:
    """
    執行高鐵訂票流程。 (與 app.py 協同工作時使用)
    """
    
    global booking_OK
    global booking_NG
    
    logger.info(f"Task {task_id} received. Passenger: {task_data.get('name', 'N/A')} | Route: {task_data.get('start_station', '?')} to {task_data.get('end_station', '?')}")
    status_updater(task_id, 'running', '開始初始化 Session...')
    
    t0 = time.perf_counter()
    booking_success = False
    result_message = ""
    
    # --- 模擬總時間設定 ---
    # 總時間目標: 60s ~ 120s
    total_steps = 10 
    # 每個步驟平均時間: (60s + 120s) / 2 / 10 = 9 秒
    # 設置每個步驟延遲 5s 到 15s 之間
    MIN_STEP_DELAY = 2.0
    MAX_STEP_DELAY = 8.0

    # --- 實際的 thsr 訂票流程 ---
    try:
        if cancel_event.is_set():
            raise Exception("任務開始前已被取消。")

        # 1. 初始化 Session
        session = session_init()
        if not session:
            raise Exception("Session 初始化失敗。")
        status_updater(task_id, 'running', 'Session 初始化成功。準備開始訂票步驟...')
        
        # 2. 模擬多個步驟，並檢查取消信號
        for step in range(1, total_steps + 1):
            
            if cancel_event.is_set():
                raise Exception("任務運行中被使用者取消。")

            # 在這裡模擬長時間延遲
            step_delay = random.uniform(MIN_STEP_DELAY, MAX_STEP_DELAY)
            sleep_range(step_delay, step_delay) # 確保延遲落在設定區間

            # sleep_range(0.3, 0.8) # 模擬網路延遲

            # --- 模擬步驟進度與結果 ---
            if step == 1: 
                result_message = f"從 {task_data.get('start_station')} 到 {task_data.get('end_station')}，讀取訂票頁面..."
            elif step == 3: 
                result_message = "提交表單數據並選擇車次中..."
            elif step == 5: 
                result_message = "處理驗證碼並提交訂票表單..."
            elif step == 7: 
                result_message = "等待系統回應訂位代號..."
            elif step == total_steps:
                if random.random() > 0.3: # 模擬 70% 成功率
                    booking_success = True
                    code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ123456789', k=6)) 
                    result_message = f"訂票成功！訂位代號: {code}"
                else:
                    result_message = "訂票失敗。列車滿座或系統錯誤。"
            else:
                result_message = f"模擬網路請求及資料處理..."

            status_updater(task_id, 'running', f"步驟 {step}/{total_steps}: (延遲 {step_delay:.2f}s) {result_message}")
            
            if booking_success:
                break
        
        # 3. 處理結果
        if booking_success:
            booking_OK += 1
            final_msg = result_message
            return True, final_msg
        else:
            booking_NG += 1
            return False, result_message


    except Exception as e:
        if "被使用者取消" in str(e):
            result_message = str(e)
            return False, result_message
            
        booking_NG += 1
        result_message = f"訂票流程中斷: {e}"
        logger.error(f"Task {task_id} execution failed: {e}")
        return False, result_message
    
    finally:
        t1 = time.perf_counter() - t0
        # 輸出處理時間 (單位: 秒)
        logger.info(f"Task {task_id} finished. Total run time = {t1:.2f}s. Success: {booking_success}")


# ----------------------------------------------------------------------------
# Main Function for Standalone Execution (新增此區塊)
# ----------------------------------------------------------------------------

# 模擬 status_updater 的函式
def cli_status_updater(task_id, status, message):
    # 在命令行模式下，我們只需要印出狀態
    print(f"[STATUS UPDATE] Task {task_id} - {status.upper()}: {message}")

def main():
    logger.info('Standalone mode started.')
    
    # 模擬從 app.py 傳入的任務資料 (請根據需要修改這些預設值)
    mock_task_data = {
        'start_station': '台北',
        'end_station': '左營',
        'travel_date': '2025/12/31',
        'train_time': '12:00',
        'name': 'Standalone User',
        'personal_id': 'A123456789',
        # ... 其他訂票所需數據
    }
    
    # 模擬 app.py 的參數
    task_id = "STANDALONE-001"
    cancel_event = threading.Event() # 模擬取消事件
    
    t0 = time.perf_counter()
    max_run = 3 # 運行最大次數
    n = 0
    
    while n < max_run:
        n += 1
        print(f"\n--- Running Booking Flow, Run {n}/{max_run} ---")
        
        # 呼叫核心訂票流程
        success, result_msg = thsr_run_booking_flow_with_data(
            task_id=f"{task_id}-{n}", # 每次運行給予不同 ID
            task_data=mock_task_data,
            cancel_event=cancel_event,
            status_updater=cli_status_updater
        )
        
        if success:
            print(f"\n{GREEN}✅ Booking succeeded!{RESET} Message: {result_msg}")
            break
        else:
            print(f"\n{RED}❌ Booking failed.{RESET} Message: {result_msg}")
            # 如果失敗，休息一段時間再重試
            if n < max_run:
                sleep_range(2, 4)
    
    t1 = int(round((time.perf_counter() - t0) * 1000.0))
    print(f"\n==========================================")
    print(f"Total time = {t1}ms, Runs = {n}")
    print(f"Booking OK   = {booking_OK}")
    print(f"Booking NG   = {booking_NG}")
    print(f"==========================================")
    logger.info('Standalone mode finished.')


if __name__ == "__main__":
    main()