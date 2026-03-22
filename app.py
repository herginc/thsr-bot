# =======================================================
# app.py (Flask Web Server) - 支援任務隊列、背景執行緒與取消
# =======================================================

# Must for Render environment
import gevent.monkey
gevent.monkey.patch_all()

import os
# import sys
import re
import json
import time
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from argparse import ArgumentParser

from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, request, abort, render_template, jsonify, redirect

import booking
import proxy
from config import *
from tdx_api import get_thsr_timetable_od_by_name

# ----------------------------------------------------------------------------
# 訂票模式切換
# True  → 使用 booking.thsr_run_booking_flow_with_data (模擬版本，用於開發/測試)
# False → 使用 proxy.thsr_run_booking_flow             (真實版本，連接高鐵官網)
# ----------------------------------------------------------------------------
USE_MOCK_BOOKING = True
# USE_MOCK_BOOKING = False


# ----------------------------------------------------------------------------
# 
# ----------------------------------------------------------------------------

# 'with lock' guideline:
# < 10 行
# 不做 I/O
# 不做 sleep
# 不呼叫未知函式
#
# 盡量使用:
# Thread → Queue → Worker


# ----------------------------------------------------------------------------
# 
# ----------------------------------------------------------------------------

logger = logging.getLogger(__name__)
# 配置 logger 格式
FORMAT = '[%(asctime)s][%(levelname)s][%(funcName)s]: %(message)s'
logging.basicConfig(level=logging.INFO, format=FORMAT)

# ----------------------------------------------------------------------------
# --- Global Configuration ---
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(__file__)
JSON_DIR = os.path.join(BASE_DIR, "json")
os.makedirs(JSON_DIR, exist_ok=True)

PASSENGER_FILE = os.path.join(JSON_DIR, "passenger.json")
TASKS_FILE     = os.path.join(JSON_DIR, "tasks.json")
HISTORY_FILE   = os.path.join(JSON_DIR, "history.json")

# 使用 timedelta 支援 Python 3.8
CST_TIMEZONE = timezone(timedelta(hours=8))

# logger.info(f'TDX config: APP_ID={TDX_APP_ID!r}, APP_KEY={TDX_APP_KEY!r}')

# --- Helper Functions ---

# ----------------------------------------------------------------------------
# load json file
# ----------------------------------------------------------------------------
def load_json(filename):
    if not os.path.exists(filename):
        # 根據檔案類型返回不同的預設值
        if filename == PASSENGER_FILE:
            return []
        elif filename == TASKS_FILE:
            return []
        elif filename == HISTORY_FILE:
            return []
        return None

    with open(filename, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: Failed to decode JSON from {filename}. Returning empty list.")
            return []

# ----------------------------------------------------------------------------
# save json file
# ----------------------------------------------------------------------------
def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ----------------------------------------------------------------------------
# --- 全局狀態 ---
# ----------------------------------------------------------------------------

data_lock = threading.RLock()

# --- 全局狀態新增 ---
booking_thread: Optional[threading.Thread] = None
current_running_task_id: Optional[str] = None
current_cancel_event: Optional[threading.Event] = None

# 載入上次的任務，並將所有 'running' 或 'cancelling' 狀態重設為 'failed'
booking_tasks: List[Dict[str, Any]] = load_json(TASKS_FILE) 

for task in booking_tasks:
    # [scott@2026-03-14] status = 'pending' case 也要考慮進去
    # task內容有變, 理論上應該要再回存檔案, 但因下面只要有save_json(TASKS_FILE)就會更新到此異動
    if (task['status'] == 'running') or (task['status'] == 'pending') or (task['status'] == 'cancelling'):
        task['status'] = 'failed'
        task['message'] = '伺服器重啟，任務失敗或已中斷。'
        task['update_time'] = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')

# current_cancel_event: Optional[threading.Event] = None

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


# ----------------------------------------------------------------------------
# 啟動背景 Worker 執行緒 (兼容 Gunicorn 和 python app.py)
# ----------------------------------------------------------------------------
# 必須在 app 實例化之後調用，並定義為一般函式
def start_booking_worker_thread():
    global booking_thread
    # 這裡不需要加鎖，因為只在啟動時執行一次
    if booking_thread is None or not booking_thread.is_alive():
        print(f"[{datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')}] 啟動背景訂票 worker 執行緒...")
        booking_thread = threading.Thread(target=run_booking_worker, daemon=True)
        booking_thread.start()

# ----------------------------------------------------------------------------
# ID 生成器：取得當前毫秒級時間戳後面8碼
# 例如：1731159842567.89 -> 1731159842568 -> 59842568
# ----------------------------------------------------------------------------
def get_new_passenger_id():

    # 1. 取得毫秒級時間戳並轉換為整數
    full_timestamp = int(time.time() * 1000)
    
    # 2. 只取後面 8 碼 (對 100,000,000 取模)
    # 例如：1731159842568 % 100000000 = 59842568 (共 8 位)
    short_id = full_timestamp % 100000000
    
    # 3. 轉換為字串並用 '0' 補齊至 8 碼，確保長度一致
    # 例如：如果 ID 是 9842568，則會補齊為 09842568
    return str(short_id).zfill(8)

# ----------------------------------------------------------------------------
# 從TASKS_FILE載入任務, 格式化訂票資訊以符合訂票任務狀態表格格式, 並整理過期的任務.
# 將已過期任務拿掉後, 再回存到TASKS_FILE, 並 return 這些任務 ('未完成'及'已完成但
# 未過期' 任務)
# Note: 剛執行完任務還不會從TASKS_FILE中移除
#
# << 怪奇, 目前沒人呼叫此function>>
#
# ----------------------------------------------------------------------------
def load_tasks_DO_NOT_RUN():
    """
    載入任務列表，並清除tasks.json中過期的已完成任務。
    同時將訂票資訊格式化為 '左營 - 台南 (11-19 23:45)'
    """
    global booking_tasks

    with data_lock:

        # # 從檔案載入任務
        # tasks = load_json(TASKS_FILE) # [cite: 141]
        
        # # 依照建立時間 (timestamp) 降冪排序，確保最新提交的在最上面
        # # 如果任務物件中有 'created_at' 或 'timestamp' 欄位：
        # tasks.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        # # 或者簡單地將列表反轉（如果新任務是 append 在最後面）
        # # tasks.reverse() 
        
        # booking_tasks = tasks
        
        booking_tasks = load_json(TASKS_FILE) # 由以上代碼取代
        
        FINAL_STATUSES = ['success', 'failed', 'cancelled', 'aborted']
        retained_tasks = []
        now_cst = datetime.now(CST_TIMEZONE)
        
        expired_count = 0
        
        for task in booking_tasks:
            task_status = task.get('status')
            
            # --- START: 格式化訂票資訊 (修正 #1: index.html 路線格式) ---
            data = task.get('data', {})
            start_station = data.get('start_station', '?')
            end_station = data.get('end_station', '?')
            travel_date = data.get('travel_date', '????/??/??')
            train_time = data.get('train_time', '??:??')
            
            formatted_date = travel_date
            try:
                # 嘗試解析常見格式: 'YYYY-MM-DD' 或 'YYYY/MM/DD'
                date_formats = ['%Y-%m-%d', '%Y/%m/%d']
                date_obj = None
                for fmt in date_formats:
                    try:
                        date_obj = datetime.strptime(travel_date, fmt)
                        break
                    except ValueError:
                        continue
                
                if date_obj:
                    # 格式化日期為 'MM-DD'
                    formatted_date = date_obj.strftime('%m-%d')
                    
            except Exception:
                # 確保在任何錯誤情況下都有值
                pass 
                
            # 建立新的格式：'左營 - 台南 (11-19 23:45)'
            # [scott@2026-03-08] 動態產生'formatted_route'欄位, TASKS_FILE 不需特別存此欄位.
            task['formatted_route'] = f"{start_station} - {end_station} ({formatted_date} {train_time})"
            # --- END: 格式化訂票資訊 ---
            
            if task_status not in FINAL_STATUSES:
                # 任務正在進行中 (pending 或 running)，直接保留
                retained_tasks.append(task)
                continue

            # [scott@2026-03-08] 以下code都是在處理已完成任務 (FINAL_STATUSES)

            # --- 處理已完成任務的過期邏輯 (保持不變) ---
            finish_time_str = task.get('finish_time')
            # ... (省略過期檢查的 if/else 邏輯) ...
            
            # [scott@2026-03-08] 'finish_time_str'沒有值的已完成任務, 也要放進 retained_tasks (??), 有可能發生嗎?
            if not finish_time_str:
                retained_tasks.append(task)
                print(f"***** 'finish_time_str'沒有值的已完成任務, 也要放進 retained_tasks --> 真的發生了 *****")
                continue
                
            try:
                finish_datetime = datetime.strptime(finish_time_str, '%Y/%m/%d %H:%M:%S').replace(tzinfo=CST_TIMEZONE)
                is_expired = False

                if task_status == 'success':    # 成功 2 天後移除
                    cutoff_date = (now_cst - timedelta(days=2)).date()
                    if finish_datetime.date() <= cutoff_date:
                        is_expired = True
                        
                else:   # 失敗/取消 60 分鐘後移除
                    cutoff_datetime = now_cst - timedelta(minutes=60)
                    if finish_datetime < cutoff_datetime:
                        is_expired = True
                        
            except Exception:
                retained_tasks.append(task)
                continue
                
            
            if is_expired:
                expired_count += 1
            else:
                retained_tasks.append(task)


        # 執行清理操作 (儲存更新後的 tasks.json)
        if expired_count > 0:
            print(f"Cleaned up {expired_count} expired completed tasks from tasks.json (index.html display).")
            booking_tasks = retained_tasks
            save_json(TASKS_FILE, booking_tasks) 
            
        return retained_tasks


# ----------------------------------------------------------------------------
# app.py: 修正 load_history 函式
# ----------------------------------------------------------------------------
def load_history():
    """
    載入歷史紀錄 (history.json)，並清理超過 365 天的紀錄。
    同時格式化所有 history.html 所需的欄位。
    """
    with data_lock:
        history_list = load_json(HISTORY_FILE)
        
        now_cst = datetime.now(CST_TIMEZONE)
        retention_days = 365 
        cutoff_date = (now_cst - timedelta(days=retention_days)).date()

        retained_history = []
        expired_count = 0
        
        for h in history_list:
            finish_time_str = h.get('finish_time')
            
            try:
                finish_datetime = datetime.strptime(finish_time_str, '%Y/%m/%d %H:%M:%S').replace(tzinfo=CST_TIMEZONE)
                
                # 檢查是否過期
                if finish_datetime.date() < cutoff_date:
                    expired_count += 1
                else:
                    # --- START: 格式化 history.html 所需欄位 (修正 #3) ---
                    data = h.get('data', {})
                    
                    # 1. 訂票結果
                    h['result_text'] = {'success': '成功', 'failed': '失敗', 'task_cancelled': '取消', 'task_aborted': '放棄'}.get(h.get('result', ''), '未知')
                    
                    # 2. 訂票時間 (finish_time)
                    h['formatted_order_date'] = finish_datetime.strftime('%Y/%m/%d %H:%M:%S')
                    
                    # 3. 乘車日期
                    h['formatted_travel_date'] = data.get('travel_date', 'N/A')
                    
                    # 4. 路線資訊
                    h['from_info'] = f"{data.get('start_station', 'N/A')} {data.get('train_time', '')}" # 假設 train_time 為出發時間
                    h['to_info'] = f"{data.get('end_station', 'N/A')}"
                    
                    # 5. 姓名和 ID
                    h['name'] = data.get('name', 'N/A')
                    h['personal_id'] = data.get('personal_id', 'N/A')

                    # 6. 車次
                    h['train_no'] = data.get('train_no', 'N/A')

                    retained_history.append(h)
                    
            except Exception as e:
                print(f"Warning: History item date parsing failed for task {h.get('task_id', 'N/A')}. Error: {e}")
                retained_history.append(h)
                
        
        # ... (省略儲存 logic) ...
        if expired_count > 0:
            print(f"Cleaned up {expired_count} expired history entries (older than {retention_days} days).")
            # 儲存時，只保留原始資料，不保留格式化欄位
            keys_to_keep = list(h.keys()) # 取得所有鍵
            history_to_save = []
            for h_item in retained_history:
                # 避免將格式化欄位寫入檔案
                original_item = {k: v for k, v in h_item.items() if not k.startswith('formatted_') and k not in ['result_text', 'from_info', 'to_info']}
                history_to_save.append(original_item)

            save_json(HISTORY_FILE, history_to_save)
        
        return retained_history


# ----------------------------------------------------------------------------
# task_id format: YYYYMMDD-NN
# YYYYMMDD = datetime.now(CST_TIMEZONE).strftime('%Y%m%d') = 當天日期
# NN = 2位數序號 = 00, 01, 02, 03, ... 依序編號
# new task_id 的 YYYYMMDD 若與上一筆 task_id 的 YYYYMMDD 不同時, 則 NN 為 00 
# new task_id 的 YYYYMMDD 若與上一筆 task_id 的 YYYYMMDD 相同時, 則 new task_id 
# 的 NN 為 上一筆 task_id 的 NN + 1
# ----------------------------------------------------------------------------
def get_new_task_id() -> str:
    with data_lock:
        today_str = datetime.now(CST_TIMEZONE).strftime('%Y%m%d')
        
        # 找出最後一筆 task_id
        last_task_id = booking_tasks[-1]['task_id'] if booking_tasks else None
        
        if last_task_id and last_task_id.startswith(today_str):
            # 與上一筆同一天 → NN + 1
            last_nn = int(last_task_id.split('-')[1])
            nn = last_nn + 1
        else:
            # 不同天（或沒有任何任務）→ NN 從 00 開始
            nn = 0
        
        return f"{today_str}-{nn:02d}"

# ----------------------------------------------------------------------------
# 
# ----------------------------------------------------------------------------
def get_task_by_id(task_id: str) -> Optional[Dict[str, Any]]:
    # 注意：此函式預期在 data_lock 內被呼叫，或僅用於讀取
    for task in booking_tasks:
        if task['task_id'] == task_id:
            return task
    return None

# ----------------------------------------------------------------------------
# 根據task_id更新任務狀態並記錄更新時間。
# 如果任務完成 (success/failed/cancelled/aborted)，則立即將其歸檔到 history.json (完整數據)。
# ----------------------------------------------------------------------------
def update_task_status(task_id: str, new_status: str, message: str):
    global booking_tasks

    logger.info(".........")

    with data_lock:
        task = get_task_by_id(task_id)
        if task is None:
            return

        task['status'] = new_status
        task['message'] = message
        task['update_time'] = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')

        FINAL_STATUSES = ['success', 'failed', 'cancelled', 'aborted']
        if new_status in FINAL_STATUSES:
            # 1. 更新任務完成時間
            task['finish_time'] = task['update_time'] 
            
            # 2. 立即歸檔到 history.json
            history_list = load_json(HISTORY_FILE)

            # *** 修正 #2: 確保 history.json 包含 task 的所有頂層欄位 ***
            # 複製 task 的所有內容作為歷史紀錄的基礎
            history_entry = task.copy()
            
            # 覆寫/確保必要的欄位正確
            history_entry['task_id'] = task['task_id']
            history_entry['result'] = new_status 
            history_entry['code'] = task.get('booking_code', 'N/A')
            history_entry['finish_time'] = task['finish_time']
            
            # 移除前端格式化欄位 (如果存在), HISTORY_FILE 不需存此欄位
            history_entry.pop('formatted_route', None) 

            # *** 檢查是否已存在，避免重複歸檔 ***
            if any(h.get('task_id') == task_id for h in history_list):
                 # 如果已存在，則不重複寫入
                 print(f"Warning: Task {task_id} already exists in history.json. Skipping re-archiving.")
                 return
            
            history_list.append(history_entry)
            save_json(HISTORY_FILE, history_list) 
            
            print(f"Task {task_id} completed ({new_status}). Archived to history.json immediately.")
            
        save_json(TASKS_FILE, booking_tasks)



# -----------------------------------------------------------------------------
# 查詢某'日期/班次'高鐵是否有大學生優惠票
# [注意]: 班次一定要四碼, "508" 不行, 一定要 "0508" 才可以
# [注意]: 班次若為三碼，程式要自動補 '0'。
# -----------------------------------------------------------------------------

import requests
import json

def check_discounts_for_list(StartStation, EndStation, target_date, train_no_list, discount_type):
    """
    批次檢查特定日期、多個車次是否有特定類別的優惠。
    """
    logger.debug(f">>> 開始查詢: {StartStation}→{EndStation} date={target_date} type={discount_type} trains={train_no_list}")

    target_date = target_date.replace('-','/')

    today = datetime.today().strftime('%Y/%m/%d')

    api_url = "https://www.thsrc.com.tw/TimeTable/Search"
    
    # 優惠代碼對照表
    discount_map = {
        "早鳥": "e1b4c4d9-98d7-4c8c-9834-e1d2528750f1",
        "大學生": "68d9fc7b-7330-44c2-962a-74bc47d2ee8a",
        "少年": "d380e2a7-dbbd-471c-93b1-4e08a65438aa"
    }

    target_guid = discount_map.get(discount_type)
    if not target_guid:
        logger.error(f"不支援的優惠類別 '{discount_type}'")
        return {}

    # logger.debug(f"優惠 GUID: {target_guid}")

    # 站名中文 → THSR 官網英文代碼
    STATION_NAME_MAP = {
        '南港': 'NanGang',
        '台北': 'TaiPei',
        '板橋': 'BanQiao',
        '桃園': 'TaoYuan',
        '新竹': 'XinZhu',
        '苗栗': 'MiaoLi',
        '台中': 'TaiChung',
        '彰化': 'ZhangHua',
        '雲林': 'YunLin',
        '嘉義': 'JiaYi',
        '台南': 'TaiNan',
        '左營': 'ZuoYing',
    }

    start_en = STATION_NAME_MAP.get(StartStation, StartStation)
    end_en   = STATION_NAME_MAP.get(EndStation, EndStation)

    logger.debug(f"站名轉換: '{StartStation}'→'{start_en}', '{EndStation}'→'{end_en}'")

    payload = {
        "SearchType": "S",
        "Lang": "TW",
        "StartStation": start_en,
        "EndStation": end_en,
        "OutWardSearchDate": target_date,
        "OutWardSearchTime": "05:00",
        "ReturnSearchDate": today,
        "ReturnSearchTime": "05:00",
        "DiscountType": target_guid
    }

    logger.debug(f"POST payload: {payload}")

    headers = {
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "Referer": "https://www.thsrc.com.tw/ArticleContent/A3B630BB-1066-4352-A1EF-58C7B4E8EF7C",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    }

    results = {}
    try:
        session = requests.Session()
        logger.debug(f"GET https://www.thsrc.com.tw/ (取得 cookie)...")
        r0 = session.get("https://www.thsrc.com.tw/", headers=headers, timeout=10)
        logger.debug(f"GET 狀態碼: {r0.status_code}, cookies: {dict(session.cookies)}")

        logger.debug(f"POST {api_url} ...")
        response = session.post(api_url, data=payload, headers=headers, timeout=10)
        logger.debug(f"POST 狀態碼: {response.status_code}")
        logger.debug(f"回應內容 (前500字): {response.text[:500]}")

        if response.status_code == 200:
            data = response.json()

            # 紀錄完整 JSON 結構的 key，方便確認結構是否如預期
            logger.debug(f"JSON top-level keys: {list(data.keys())}")
            data_block = data.get("data", {})
            logger.debug(f"data block keys: {list(data_block.keys()) if isinstance(data_block, dict) else type(data_block)}")
            dep_table = data_block.get("DepartureTable", {})
            logger.debug(f"DepartureTable keys: {list(dep_table.keys()) if isinstance(dep_table, dict) else type(dep_table)}")
            train_items = dep_table.get("TrainItem", [])
            logger.debug(f"TrainItem 筆數: {len(train_items)}")

            # 取得所有有該優惠的車次編號
            available_trains = [
                t.get("TrainNumber")
                for t in train_items
            ]
            logger.info(f"{discount_type}優惠車次清單: {available_trains}")

            # 比對清單
            for no in train_no_list:
                matched = no in available_trains
                results[no] = matched
                if matched:
                    # logger.debug(f"✔ 車次 {no} 有優惠")
                    pass
                else:
                    # logger.debug(f"車次 {no} 無優惠")
                    pass

        else:
            logger.error(f"API 請求失敗: HTTP {response.status_code}, body: {response.text[:300]}")

    except Exception as e:
        logger.error(f"執行錯誤: {e}", exc_info=True)

    logger.debug(f"<<< 查詢結果: {results}")
    return results


# ----------------------------------------------------------------------------
# Worker Function for booking.py (Req 0, 1, 4, 5)
# ----------------------------------------------------------------------------
def run_booking_worker():
    global current_running_task_id
    global current_cancel_event
    
    while True:
        task_to_run = None
        should_sleep = False # 新增旗標，用於在釋放鎖後再睡眠
        
        # --- 階段 1: 檢查並取出任務 (Locked) ---
        with data_lock:
            if current_running_task_id is not None:   # 已經有任務在跑
                should_sleep = True 
                # !!! 修正: 移除這裡的 time.sleep(1)
                
            else:   # 沒有任務在跑
                pending_tasks = [t for t in booking_tasks if t['status'] == 'pending']
                if not pending_tasks:
                    # 沒有待處理任務
                    should_sleep = True 
                    # !!! 修正: 移除這裡的 time.sleep(1)
                else:   # [scott@2026-03-14] 有無機會改成, support multitask 在跑 (一次可以背景同時訂多張票)  (最底層訂票系統: 根據車次一次訂一張, 時間訂票需轉換成多張車次訂票)
                    # 取得並設置為 'running'
                    task_to_run = pending_tasks[0]
                    current_running_task_id = task_to_run['task_id']
                    current_cancel_event = threading.Event()

                    print(YELLOW)
                    print('-' * 80)
                    print("執行新的訂票任務:")
                    print(task_to_run['data'])
                    print('-' * 80)
                    print(RESET)

                    # 這裡調用 update_task_status 會再次獲取鎖，但由於操作快，不會造成死鎖
                    update_task_status(task_to_run['task_id'], 'running', '開始執行訂票流程...')

        # Lock is released here
        
        if should_sleep:
            # 在鎖定區塊之外睡眠，避免阻塞其他請求
            time.sleep(1)
            continue
            
        # --- 階段 2: 執行任務 (Unlocked) ---
        if task_to_run:
            success = False
            result_msg = ""
            try:
                # 根據 USE_MOCK_BOOKING 旗標選擇訂票實作：
                #   True  → booking.thsr_run_booking_flow_with_data (模擬版本)
                #   False → proxy.thsr_run_booking_flow             (真實版本)
                booking_fn = (
                    booking.thsr_run_booking_flow_with_data
                    if USE_MOCK_BOOKING
                    else proxy.thsr_run_booking_flow
                )

                final_status, result_msg = booking_fn(
                    task_to_run['task_id'], 
                    task_to_run['data'], 
                    current_cancel_event,
                    update_task_status
                )

                # [scott@2026-03-12] final_status 不應該只有 'success' or 'failed', 應該有 '成功', '失敗', '放棄', '取消' or '中斷' & '不明原因'
                # [scott@2026-03-17] final_status: 'booking_success', 'booking_failed', 'task_cancelled', 'task_aborted' or 'unknown_result'

                print(GREEN)
                print('*' * 80)
                print(f"final_status = {final_status}, result_msg = {result_msg}")                
                print('*' * 80)
                print(RESET)

            except Exception as e:
                final_status = 'booking_failed'
                result_msg = f"執行錯誤: {e}"
            
            # 任務完成後更新狀態並清除運行中的標記 (重新鎖定)
            with data_lock:
                current_task = get_task_by_id(current_running_task_id)
                if current_task and (current_task['status'] == 'running' or current_task['status'] == 'cancelling'):
                    
                    if current_task['status'] == 'cancelling':
                        final_status = 'task_cancelled'
                        # if '被使用者取消' not in result_msg:
                        #     result_msg = '使用者中斷任務'
                    
                    # 如果成功，將結果寫入 history.json (略過)
                    # 確保將訂位代號存入 task 物件
                    if final_status == 'booking_success' and '訂位代號:' in result_msg:
                        # 從結果訊息中解析出訂位代號並儲存
                        match = re.search(r'訂位代號: (\w+)', result_msg)
                        if match:
                            booking_code = match.group(1)
                            current_task['booking_code'] = booking_code # <--- **新增這行**
                    
                    update_task_status(current_running_task_id, final_status, result_msg)

                current_running_task_id = None
                current_cancel_event = None
        
        # 如果有任務執行，這裡不需要 sleep，直接開始下一個循環


# app.py: 新增 /api/passenger 路由

# 關於「即使Name是唯一的，為何仍需要 ID」的說明：
# 資料獨立性（decoupling）：內部 ID 通常是系統自動分配的、不可變的數字（例如 1, 2, 3...）。如果未來乘客的姓名因故需要更改（例如：改名），由於系統依靠這個不變的內部 ID 來追蹤該乘客所有的歷史紀錄和任務，您只需要更新乘客資料中的 name 欄位，而無需更新所有歷史訂票紀錄。
# 安全層級分離： 為了遵守「Front-End 不使用 personal_id」的安全原則，我們將使用這個非敏感的內部 ID (id) 作為前端下拉選單與後端 API 溝通的橋樑，而不是使用敏感的姓名或身份證字號。
@app.route('/api/passenger', methods=['GET'])
@app.route('/api/get_passengers', methods=['GET'])
def api_passenger():
    """
    提供 JSON 格式的乘客列表給前端 index.html，僅包含不敏感的 id 和 name。
    """
    # 確保在讀取檔案時使用 data_lock 來保護共享資源
    with data_lock:
        passengers = load_json(PASSENGER_FILE)
        
        # 過濾數據：只傳輸 id (作為 value key) 和 name (作為顯示文本)
        safe_passengers = []
        for p in passengers:
            # 僅在 'id' 和 'name' 欄位都存在時才傳輸
            if p.get('id') is not None and p.get('name') is not None:
                safe_passengers.append({
                    'id': p.get('id'),        # 不敏感的 ID 作為下拉選單的 value
                    'name': p.get('name')     # 姓名作為顯示文本
                })
            
        return jsonify(safe_passengers)


# ============================================================================
# app.py 修正: /api/submit 路由 (確保異常處理)
# ============================================================================
# ----------------------------------------------------------------------------
# 路由修改 (Req 4: 提交訂票)
# ----------------------------------------------------------------------------
@app.route("/api/submit", methods=["POST"])
@app.route("/api/submit_task", methods=["POST"])
def submit_booking():
    # 確保所有邏輯都在 try 區塊內，防止未預期的崩潰
    try:
        data = request.json

        # 檢查 data 是否為 None 或空字典
        if not data:
            print("ERROR: Received empty JSON data.")
            abort(400, "Invalid or empty JSON data")

        # --- START: 新增的安全性查找邏輯 ---
        # 1. 取得前端傳來的非敏感內部 ID，並將其從 data 中移除，避免直接儲存
        passenger_internal_id = data.pop('passenger_internal_id', None)
        
        # 2. 檢查內部 ID 是否存在
        if not passenger_internal_id:
             return jsonify({"status": "error", "message": "錯誤：請選擇一個有效的乘客，缺少內部 ID。"}), 400

        # 3. 查找完整的乘客資料 (包含敏感資訊)
        passenger_info = None
        # 使用 data_lock 保護對乘客檔案的讀取
        with data_lock:
            passengers = load_json(PASSENGER_FILE)
            # 尋找匹配的乘客。由於 ID 可能是數字或字串，使用 str() 進行安全比較
            # 找到第一個匹配的乘客資訊
            for p in passengers:
                if str(p.get('id')) == str(passenger_internal_id):
                    passenger_info = p
                    break
        
        if not passenger_info:
            print(f"ERROR: Cannot find passenger with internal ID: {passenger_internal_id}")
            return jsonify({"status": "error", "message": "乘客資料查找失敗：找不到匹配的乘客內部 ID。"}), 400

        # 4. 將查找到的敏感欄位 (personal_id, phone_num) 和其他重要欄位加入到任務數據中
        # 這些是訂票 Worker (booking.py) 所需的關鍵資料
        data['name'] = passenger_info.get('name') 
        data['personal_id'] = passenger_info.get('personal_id')
        data['phone_num'] = passenger_info.get('phone_num')
        data['email'] = passenger_info.get('email')
        data['identity'] = passenger_info.get('identity')
        # --- END: 新增的安全性查找邏輯 ---

        # --- START: 欄位正規化 (前端傳入值 → proxy.py 所需格式) ---

        # 5a. travel_date: 統一轉為 'YYYY/MM/DD' (相容 'YYYY-MM-DD' 或已是 'YYYY/MM/DD')
        raw_date = data.get('travel_date', '')
        data['travel_date'] = raw_date.replace('-', '/')

        # 5b. identity: 中文票種 → proxy.py IDENTITY_TO_TICKET_ROW key
        IDENTITY_ZH_TO_EN = {
            '一般':   'adult',
            '孩童':   'child',
            '愛心':   'disabled',
            '敬老':   'elder',
            '大學生': 'college',
            '學生':   'college',  # 兼容 passenger.json 中寫法
        }
        raw_identity = data.get('identity', '')
        data['identity'] = IDENTITY_ZH_TO_EN.get(raw_identity, 'adult')

        # 5c. seat_class: 中文車廂種類 → class_type 整數
        #     對應 proxy.py trainCon:trainRadioGroup: 0=標準, 1=商務, 2=自由座
        SEAT_CLASS_ZH_TO_INT = {
            '標準車廂': 0,
            '商務車廂': 1,
            '自由座':   2,
        }
        raw_seat_class = data.pop('seat_class', '')
        data['class_type'] = SEAT_CLASS_ZH_TO_INT.get(raw_seat_class, 0)

        # 5d. seat_option: 中文座位喜好 → seat_prefer 整數
        #     對應 proxy.py seatCon:seatRadioGroup: 0=無, 1=靠窗, 2=走道
        SEAT_OPTION_ZH_TO_INT = {
            '無座位偏好': 0,
            '靠窗優先':   1,
            '走道優先':   2,
        }
        raw_seat_option = data.pop('seat_option', '')
        data['seat_prefer'] = SEAT_OPTION_ZH_TO_INT.get(raw_seat_option, 0)

        # --- END: 欄位正規化 ---

        # --- START: 必填欄位驗證（避免進入 worker 才失敗） ---
        booking_method = str(data.get('bookingMethod', '') or '').strip()
        train_no = str(data.get('train_no', '') or '').strip()
        train_time = str(data.get('train_time', '') or '').strip()

        if booking_method == 'radio33':
            if not train_no:
                return jsonify({
                    "status": "error",
                    "message": "車次模式 (radio33) 需提供 train_no。"
                }), 400
        else:
            if not train_time:
                return jsonify({
                    "status": "error",
                    "message": "時間模式需提供 train_time (格式 HH:MM)。"
                }), 400
            if not re.match(r'^\d{1,2}:\d{2}$', train_time):
                return jsonify({
                    "status": "error",
                    "message": "train_time 格式錯誤，請使用 HH:MM（例如 09:00）。"
                }), 400
        # --- END: 必填欄位驗證 ---

        task_id = get_new_task_id()

        current_time_cst = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')

        new_task = {
            'task_id': task_id,
            'status': 'pending',
            'submit_time': current_time_cst,
            'update_time': current_time_cst,
            'message': '等待執行...',
            'data': data # 此處的 data 已經包含了從後端查找並添加的 personal_id 等敏感資訊
        }

        with data_lock:
            # 假設 booking_tasks 在全域範圍內是可用的
            booking_tasks.append(new_task)
            save_json(TASKS_FILE, booking_tasks)
            
        return jsonify({"status": "success", "message": "訂票任務已加入隊列", "task_id": task_id}), 200

    except Exception as e:
        # 捕獲所有異常，並返回 500 錯誤給前端
        import traceback
        error_trace = traceback.format_exc()
        print(f"Submit error: {e}\n{error_trace}")
        
        # 為了安全起見，不將詳細堆棧追蹤暴露給前端
        return jsonify({"status": "error", "message": f"提交失敗: 伺服器內部錯誤 ({type(e).__name__})，請檢查伺服器日誌。"}), 500


# ----------------------------------------------------------------------------
# 路由新增 (Req 3: 動態查詢狀態)
# ----------------------------------------------------------------------------
@app.route("/api/status", methods=["GET"])
@app.route("/api/get_tasks", methods=["GET"])
@app.route("/api/get_tasks_status", methods=["GET"])
def get_booking_status():
    # with lock裡的動作, 盡量不要太久
    with data_lock:
        tasks = list(booking_tasks) # 後續用tasks來處理, 就不用佔用booking_tasks太多時間

    # 每次前端請求狀態時，同時執行任務清理邏輯
    # tasks = load_tasks()

    status_list = []
    for task in tasks:
        # 確保 task['data'] 中有必要的鍵
        data = task.get('data', {})
        status_list.append({
            'id': task['task_id'],
            'status': task['status'],
            'message': task['message'],
            'submit_time': task['submit_time'],
            'update_time': task['update_time'],
            'train_info': f"從 {data.get('start_station', '?')} 到 {data.get('end_station', '?')} ({data.get('travel_date', '?')} {data.get('train_time', '?')} {data.get('train_no', '')})",
            'passenger_name': data.get('name', '?')
        })
        
    worker_status = 'running' if booking_thread and booking_thread.is_alive() and current_running_task_id else 'idle'
    if worker_status == 'running':
        worker_status += f" (Task ID: {current_running_task_id})"

    # print(YELLOW + f"status_list len = {len(status_list)}" + RESET)
    # print(status_list)

    # 訂票任務狀態 (最新顯示在最上方)
    status_list.reverse()   # [scott@2026-03-14] reverse list order

    return jsonify({
        "status": "success",
        "worker_status": worker_status,
        "tasks": status_list
    }), 200


# ----------------------------------------------------------------------------
# 路由新增 (Req 2: 刪除/取消訂票)
# ----------------------------------------------------------------------------
@app.route("/api/cancel/<string:task_id>", methods=["POST"])
@app.route("/api/cancel_task/<string:task_id>", methods=["POST"])
def cancel_booking(task_id):
    global current_running_task_id
    global current_cancel_event
    
    with data_lock:
        task = get_task_by_id(task_id)
        if not task:
            print(RED + f"找不到任務 ID: {task_id}" + RESET)
            return jsonify({"status": "error", "message": f"找不到任務 ID: {task_id}"}), 404
        
        current_status = task['status']
        
        if current_status == 'pending':
            update_task_status(task_id, 'task_cancelled', '任務已從隊列中取消。')
            return jsonify({"status": "success", "message": f"任務 {task_id} 已從隊列中移除。"}), 200
        
        elif current_status == 'running':
            # 檢查是否為當前正在運行的任務
            if current_running_task_id == task_id and current_cancel_event:
                current_cancel_event.set() # 發送取消信號
                # 將狀態設為 'cancelling'，等待 worker 執行緒響應並將最終狀態設為 'cancelled'
                print(YELLOW + f"已發送取消信號(cancelling)給運行中的任務 {task_id}，正在等待其停止..." + RESET)
                update_task_status(task_id, 'cancelling', '已發送取消信號，正在等待 booking 停止運行...')
                return jsonify({"status": "success", "message": f"已發送取消信號給運行中的任務 {task_id}。"}), 200
            else:
                return jsonify({"status": "error", "message": "任務狀態異常或非當前運行任務，無法取消。"}), 500

        elif current_status == 'cancelling':
            return jsonify({"status": "error", "message": f"任務 {task_id} 正在取消中，請稍候。"}), 400
            
        else:
            return jsonify({"status": "error", "message": f"任務 {task_id} 狀態為 '{current_status}'，無法取消。"}), 400

# ----------------------------------------------------------------------------
# 頁面路由
# ----------------------------------------------------------------------------

@app.route("/")
def index_page():
    # 1. 讀取乘客資料
    # 使用 data_lock 保護讀取操作是更安全的做法，但如果 load_json 內部已處理同步，這裡可省略
    passengers = load_json(PASSENGER_FILE)
    
    # 2. 檢查乘客列表是否為空
    if not passengers:
        # 如果沒有乘客資料，則返回一個重定向響應，強制使用者先進入乘客管理頁面
        # 瀏覽器會收到 302 響應並跳轉到 /passenger.html
        print("INFO: No passenger data found. Redirecting to passenger page.")
        return redirect("/passenger.html")
    
    # 3. 如果有乘客資料，則正常渲染首頁
    # 這裡傳遞 passengers 變數到模板，以確保模板中的任何依賴能正常運作
    return render_template("index.html", passengers=passengers)


# app.py: 修正 passenger_page 函式，強制姓名唯一性

@app.route("/passenger.html", methods=["GET", "POST"])
def passenger_page():
    # 讀取現有乘客列表，無論是 GET 或 POST 請求，都會在鎖定區間外先讀取
    # 這裡先讀取，如果 POST 失敗，可以直接返回這個列表
    passengers = load_json(PASSENGER_FILE) 

    if request.method == "POST":
        data = request.form
        name = data.get("name")
        
        # 1. 檢查 'name' 是否為空
        if not name or name.strip() == "":
            return render_template("passenger.html", passengers=passengers, error="姓名不能為空。")
            
        # 2. 檢查 'name' 是否重複 (必須在寫入前完成)
        # 使用 data_lock 確保在讀取和寫入乘客檔案時的執行緒安全
        with data_lock:
            
            # 重新載入一次，以確保在檢查時拿到的是最新的數據（避免其他執行緒剛好新增了資料）
            passengers = load_json(PASSENGER_FILE)
            
            # 檢查是否存在相同姓名
            existing_names = [p.get("name") for p in passengers if p.get("name") is not None]
            
            if name in existing_names:
                # 返回錯誤訊息，將現有乘客列表傳回
                return render_template("passenger.html", passengers=passengers, error=f"錯誤：乘客姓名 '{name}' 已經存在，請使用獨特的名稱。")
                
            # 3. 執行新增操作
            passenger = {
                "id": get_new_passenger_id(),
                "name": name,
                "personal_id": data.get("personal_id"),
                "phone_num": data.get("phone_num"),
                "email": data.get("email"),
                "identity": data.get("identity")
            }
            passengers.append(passenger)
            save_json(PASSENGER_FILE, passengers)
        
            # 4. 新增成功，返回成功訊息
            return render_template("passenger.html", passengers=passengers, success=True)
    
    # GET 請求：顯示乘客列表
    # passengers = load_json(PASSENGER_FILE) # 已經在函式開始處讀取
    return render_template("passenger.html", passengers=passengers)

# ----------------------------------------------------------------------
# 注意：若您的 passenger.html 中沒有處理 error 參數，需要微幅修改 passenger.html
# ----------------------------------------------------------------------

@app.route("/history.html")
def history_page():
    # 這裡的邏輯需要與實際的 history.json 格式相符
    # history = load_json(HISTORY_FILE)     # ❌ 直接讀 JSON，無格式化
    history = load_history()                # ✅ 使用 load_history()，包含格式化
    
    # 假設 history.json 中的每個項目已經包含所需的鍵
    # 為了簡化，這裡僅傳遞 history 列表
    return render_template("history.html", history=history if history else [])
    
# ----------------------------------------------------------------------------
# 根據日期及起訖站，查詢高鐵班次下拉選單資料。
# TDX_APP_ID, TDX_APP_KEY 由 config.py 提供 (from config import *)
# ----------------------------------------------------------------------------
@app.route('/api/get_trains', methods=['GET'])
def api_get_trains():
    """
    查詢高鐵班次下拉選單資料。

    Query Parameters:
        origin      (str): 出發站名稱，例如 '台北'
        destination (str): 到達站名稱，例如 '台中'
        date        (str): 乘車日期 YYYY-MM-DD

    Returns (JSON):
        {
            "status": "success",
            "trains": [
                {
                    "train_no":     "0205",
                    "dep_time":     "07:51",
                    "arr_time":     "08:38",
                    "duration_min": 47,
                    "label":        "0205, 07:51 - 08:38 (47 min)",
                    "train_type":   "直達車"
                },
                ...
            ]
        }
    """
    origin      = request.args.get('origin', '').strip()
    destination = request.args.get('destination', '').strip()
    date        = request.args.get('date', '').strip()

    if not origin or not destination or not date:
        return jsonify({'status': 'error', 'message': '缺少必要參數 origin / destination / date'}), 400

    try:
        trains = get_thsr_timetable_od_by_name(
            app_id=TDX_APP_ID,
            app_key=TDX_APP_KEY,
            origin_name=origin,
            destination_name=destination,
            train_date=date,
        )

        train_no_list = [t['train_no'] for t in trains]
        logger.info(f'({date} {origin}-{destination}) 高鐵班次共有{len(train_no_list)}班: {train_no_list}')

        # 查詢大學生優惠，失敗時回傳空 dict，不影響主流程
        discount_map = check_discounts_for_list(
            StartStation=origin,
            EndStation=destination,
            target_date=date,
            train_no_list=train_no_list,
            discount_type='大學生',
        )
        # logger.info(f'大學生優惠票查詢結果 {discount_map}')
    
        # 有優惠的班次在 label 末尾加 ' *'
        for t in trains:
            has_discount = discount_map.get(t['train_no'], False)
            t['has_discount'] = has_discount
            if has_discount:
                t['label'] = t['label'] + ' *'

        return jsonify({'status': 'success', 'trains': trains})

    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    except Exception as e:
        logger.error(f'api_get_trains error: {e}')
        return jsonify({'status': 'error', 'message': f'查詢失敗: {str(e)}'}), 500


# 將啟動函式保留為一般函式
# def start_booking_worker_thread():
#     global booking_thread
#     # 這裡不需要加鎖，因為只在啟動時執行一次
#     if booking_thread is None or not booking_thread.is_alive():
#         print(f"[{datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')}] 啟動背景訂票 worker 執行緒...")
#         booking_thread = threading.Thread(target=run_booking_worker, daemon=True)
#         booking_thread.start()


if __name__ == "__main__":

    # 確保在直接執行 app.py 時啟動 worker
    # [scott@2026-03-14] 是否應該移到最上面, 理由如下:
    #     為了確保 Gunicorn worker 也啟動，請將 start_booking_worker_thread()
    #     放在 app = Flask(__name__) 之後的頂層代碼區塊。
    start_booking_worker_thread()

    arg_parser = ArgumentParser(
        usage='Usage: python ' + __file__ + ' [--port <port>] [--help]'
    )
    arg_parser.add_argument(
        '-p', '--port', type=int, default=8000, help='Port number of the web server'
    )
    
    args = arg_parser.parse_args()
    port = args.port
    
    # app.run(debug=True) 將在 Windows/Linux Python 直接執行環境下使用
    # gunicorn app:app -b 0.0.0.0:8000 將在 Linux 環境下使用
    # 啟動 app.py
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)

# 備註: 當使用 gunicorn --bind 0.0.0.0:8000 app:app 啟動時:
# 1. gunicorn 會載入 app.py 並取得 app 對象
# 2. if __name__ == "__main__": 區塊不會被執行
# 3. 由於 run_booking_worker 會檢查 current_running_task_id，且在 gunicorn 每個 worker 中會獨立運行，
#    這仍然能滿足 '單一任務處理' 的需求，但為了確保 worker 啟動，
#    最簡單且相容的作法是在 app.py 頂層調用 start_booking_worker_thread()。
#    但為了保持結構清潔，我們將其放在 __main__ 中，並依賴 gunicorn 啟動後的進程獨立性。