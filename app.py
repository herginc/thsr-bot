# =======================================================
# app.py (Flask Web Server) - 支援任務隊列、背景執行緒與取消
# =======================================================

# Must for Render environment
import os
# gevent monkey patching can interfere with debuggers.
# We only enable it in production (Render) or when explicitly requested.
if os.environ.get('DEPLOY_ENV') == 'Render' or os.environ.get('GEVENT_SUPPORT') == 'True':
    import gevent.monkey
    gevent.monkey.patch_all()

# import sys
import re
import json
import time
import hashlib
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from argparse import ArgumentParser

from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, request, abort, render_template, jsonify, redirect, session

import simu_booking
import thsr_booking
from config import *
from tdx_api import get_thsr_timetable_od_by_name
from stmp_sms import send_email, send_LINE_message

# ----------------------------------------------------------------------------
# 訂票頻率排程模組
# ----------------------------------------------------------------------------
from booking_schedule import BookingScheduler, parse_departure_dt

# ----------------------------------------------------------------------------
# 訂票模式切換
# True  → 使用 simu_booking.py      (模擬版本，用於開發/測試)
# False → 使用 thsr_booking.py      (真實版本，連接高鐵官網)
# ----------------------------------------------------------------------------
# USE_MOCK_BOOKING = True         ＃開發/測試階段，使用模擬版本 (不連接高鐵官網)
# USE_MOCK_BOOKING = False        ＃真正部署時，使用真實版本 (連接高鐵官網)

USE_MOCK_BOOKING = True

#
# SEND_BOOKING_INFO 變數控制是否在訂票成功後發送 Email 和 LINE 通知。
#
SEND_BOOKING_INFO = True

# 在模擬訂票模式下，為了避免誤發通知，強制將 SEND_BOOKING_INFO 設為 False。
if (USE_MOCK_BOOKING == True):
    SEND_BOOKING_INFO = False


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

PASSENGER_FILE    = os.path.join(JSON_DIR, "passenger.json")
TASKS_FILE        = os.path.join(JSON_DIR, "tasks.json")
HISTORY_FILE      = os.path.join(JSON_DIR, "history.json")
ADMIN_FILE        = os.path.join(JSON_DIR, "admin.json")
TIMETABLE_FILE    = os.path.join(JSON_DIR, "timetable_cache.json")  # TDX 班次查詢快取

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
last_cache_cleanup_date: Optional[datetime.date] = None

# 載入上次的任務，並將所有 'running' 或 'cancelling' 狀態重設為 'failed'
booking_tasks: List[Dict[str, Any]] = load_json(TASKS_FILE) 

for task in booking_tasks:
    # [scott@2026-03-14] status = 'pending' case 也要考慮進去
    # task內容有變, 理論上應該要再回存檔案, 但因下面只要有save_json(TASKS_FILE)就會更新到此異動
    if (task['status'] == 'running') or (task['status'] == 'pending') or (task['status'] == 'cancelling'):
        retry_count = task.get('retry_count', 0)
        if retry_count > 0:
            task['message'] = f'伺服器重啟，任務失敗或已中斷（已重試 {retry_count} 次）。'
        else:
            task['message'] = '伺服器重啟，任務失敗或已中斷。'
        task['status'] = 'booking_failed'
        task['update_time'] = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')

# current_cancel_event: Optional[threading.Event] = None

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

# ----------------------------------------------------------------------------
# 全域 BookingScheduler 實例（啟動時載入 booking_schedule.yaml）
# ----------------------------------------------------------------------------
booking_scheduler = BookingScheduler()


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
# Sensitive data 遮罩
#
# 有管理者權限（session["is_admin"] == True）的 client：
#   - id          → 顯示真實值
#   - personal_id → 保留前4碼+最後1碼，中間 "*"（例：G120*****2）
#   - phone_num   → 顯示真實值
#   - email       → 顯示真實值
#
# 無管理者權限的 client：
#   - id / personal_id / phone_num / email → 全部以等長 "*" 取代
# ----------------------------------------------------------------------------

def _mask_all(value: str) -> str:
    return "*" * len(value) if value else ""

def _mask_personal_id(pid: str) -> str:
    if not pid:
        return ""
    if len(pid) <= 5:
        return "*" * len(pid)
    return pid[:4] + "*" * (len(pid) - 5) + pid[-1]

def apply_passenger_mask(passengers: list, is_admin: bool) -> list:
    """
    id 為非 sensitive，所有 session 皆顯示真實值。
    Sensitive 欄位（personal_id / phone_num / email）：
      - is_admin=True  → personal_id 部分遮罩，其餘顯示真實值
      - is_admin=False → 全部以等長 '*' 取代
    """
    result = []
    for p in passengers:
        base = {
            **p,
            "display_id": p.get("id", ""),   # id 非 sensitive，永遠顯示真實值
        }
        if is_admin:
            base.update({
                "display_personal_id": _mask_personal_id(p.get("personal_id", "")),
                "display_phone_num":   p.get("phone_num", ""),
                "display_email":       p.get("email", ""),
            })
        else:
            base.update({
                "display_personal_id": _mask_all(p.get("personal_id", "")),
                "display_phone_num":   _mask_all(p.get("phone_num", "")),
                "display_email":       _mask_all(p.get("email", "")),
            })
        result.append(base)
    return result


# ----------------------------------------------------------------------------
# ID 生成器：取得當前毫秒級時間戳後面8碼
# 例如：1731159842567.89 -> 1731159842568 -> 59842568
# ----------------------------------------------------------------------------
def get_new_passenger_id():
    full_timestamp = int(time.time() * 1000)
    short_id = full_timestamp % 100000000
    return str(short_id).zfill(8)


# ----------------------------------------------------------------------------
# load_history 函式新增過期紀錄清理邏輯
# ----------------------------------------------------------------------------
def load_history():
    """
    載入歷史紀錄 (history.json)，並清理超過 365 天的紀錄。
    同時格式化所有 history.html 所需的欄位。此函式僅用於讀取和格式化，不修改檔案。
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
                    h['result_text'] = {'booking_success': '成功', 'booking_failed': '失敗', 'task_cancelled': '取消', 'task_aborted': '放棄'}.get(h.get('result', ''), '未知')
                    
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
                
        # This function only filters for display. It does not persist the cleanup to the file.
        # If persistent cleanup is desired, it should be implemented in a separate function.

        return retained_history


# ----------------------------------------------------------------------------
# load_tasks 函式新增任務清理邏輯
# ----------------------------------------------------------------------------
def load_tasks():
    """
    載入並清理已完成且過期的任務：
    - 成功 (success)：1 天 (24 小時) 後從列表移除。
    - 失敗/取消/異常 (failed, cancelled, aborted, unknown)：120 分鐘後從列表移除。
    移除前會確保任務已歸檔至 history.json。
    """
    global booking_tasks
    with data_lock:
        now_cst = datetime.now(CST_TIMEZONE)
        # 仍在進行中的狀態，不進行清理
        ACTIVE_STATUSES = ['pending', 'running', 'cancelling']
        
        retained_tasks = []
        expired_count = 0
        history_list = None
        history_updated = False
        
        for task in booking_tasks:
            status = task.get('status')
            
            # 若為進行中任務，直接保留
            if status in ACTIVE_STATUSES:
                retained_tasks.append(task)
                continue
            
            finish_time_str = task.get('finish_time')
            if not finish_time_str:
                retained_tasks.append(task)
                continue
                
            try:
                finish_dt = datetime.strptime(finish_time_str, '%Y/%m/%d %H:%M:%S').replace(tzinfo=CST_TIMEZONE)
                
                is_expired = False
                if status == 'booking_success':
                    # 成功任務：1 天後移除
                    if (now_cst - finish_dt) >= timedelta(days=1):
                        is_expired = True
                else:
                    # 失敗、取消或其他異常任務：120 分鐘後移除
                    if (now_cst - finish_dt) >= timedelta(minutes=120):
                        is_expired = True
                
                if is_expired:
                    # 清理前確保已歸檔到歷史紀錄
                    if history_list is None:
                        history_list = load_json(HISTORY_FILE) or []
                    
                    if not any(h.get('task_id') == task['task_id'] for h in history_list):
                        history_entry = task.copy()
                        history_entry['result'] = status
                        history_list.append(history_entry)
                        history_updated = True
                        logger.info(f"任務 {task['task_id']} 在清理前已自動補歸檔至歷史紀錄。")
                    
                    expired_count += 1
                else:
                    retained_tasks.append(task)
            except Exception as e:
                logger.warning(f"處理任務 {task.get('task_id')} 清理時發生錯誤: {e}")
                retained_tasks.append(task)

        if history_updated:
            save_json(HISTORY_FILE, history_list)
                
        if expired_count > 0:
            booking_tasks = retained_tasks
            save_json(TASKS_FILE, booking_tasks)
            logger.info(f"已從活動列表中清理 {expired_count} 筆過期任務。")
            
        return list(booking_tasks)


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
        
        # 考慮活躍任務與歷史紀錄，找出今天已使用的最大序號
        max_nn = -1

        # 1. 檢查活躍任務 (booking_tasks)
        if booking_tasks:
            last_active_id = booking_tasks[-1]['task_id']
            if last_active_id.startswith(today_str):
                max_nn = max(max_nn, int(last_active_id.split('-')[1]))

        # 2. 檢查歷史紀錄 (history.json)，只看最後一筆
        history_list = load_json(HISTORY_FILE)
        if history_list:
            last_history_id = history_list[-1]['task_id']
            if last_history_id.startswith(today_str):
                try:
                    max_nn = max(max_nn, int(last_history_id.split('-')[1]))
                except (ValueError, IndexError):
                    pass # 格式不符則忽略

        # 今天的序號從 max_nn + 1 開始 (若今天尚無任務則 max_nn 為 -1，nn 為 0)
        nn = max_nn + 1
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

    with data_lock:
        task = get_task_by_id(task_id)
        if task is None:
            return

        # [第 N 次重試] 前綴由前端依 retry_count 欄位自行渲染，後端不再塞入 message

        task['status'] = new_status
        task['message'] = message
        task['update_time'] = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')

        FINAL_STATUSES = ['booking_success', 'booking_failed', 'task_cancelled', 'task_aborted', 'unknown_result']
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
            else:
                history_list.append(history_entry)
                save_json(HISTORY_FILE, history_list) 
                print(f"Task {task_id} completed ({new_status}). Archived to history.json immediately.")
            
        save_json(TASKS_FILE, booking_tasks)



# -----------------------------------------------------------------------------
# 查詢某'日期/班次'高鐵是否有大學生優惠票
# [注意]: 班次一定要四碼, "508" 不行, 一定要 "0508" 才可以
# [注意]: 班次若為三碼，程式要自動補 '0'。
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# SearchType	    "S"                 S=單程搜尋, R=來回搜尋
# Lang	            "TW"                固定為 TW
# StartStation	    "XinZhu"            THSR 官網使用的英文站名
# EndStation	    "TaiPei"            THSR 官網使用的英文站名
# OutWardSearchDate "2026/04/13"        出發日期，格式 YYYY/MM/DD
# OutWardSearchTime	"08:30"             出發時間：若日期為今天，則為當下時間的下一個半小時 (例如現在是 16:45，則設為 16:00)。若日期為明天之後，則固定為早上5點，確保可查詢到當天所有車次的優惠資訊。
# ReturnSearchDate  "2026/04/08"        回程日期。單程搜尋時，則為查詢當天日期。
# ReturnSearchTime  "16:30"             回程時間。單程搜尋時，則為查詢當下時間的下一個半小時 (例如現在是 16:45，則設為 16:00)。
# DiscountType      "e1b4c4d9-98d7-4c8c-9834-e1d2528750f1,68d9fc7b-7330-44c2-962a-74bc47d2ee8a"     # 此為大學生優惠及早鳥優惠的 GUID
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
        "User-Agent": USER_AGENT
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

    except requests.exceptions.Timeout:
        logger.warning(
            f"[check_discounts_for_list] 優惠查詢逾時"
            f"（{StartStation}→{EndStation} {target_date}），略過優惠資訊"
        )
    except requests.exceptions.ConnectionError as e:
        logger.warning(
            f"[check_discounts_for_list] 優惠查詢連線失敗"
            f"（{StartStation}→{EndStation}）：{e}，略過優惠資訊"
        )
    except Exception as e:
        logger.error(f"執行錯誤: {e}", exc_info=True)

    logger.debug(f"<<< 查詢結果: {results}")
    return results


# ----------------------------------------------------------------------------
# 高鐵訂票成功後，發送 Email 及 LINE 通知
# 整合自 thsr_v3_3.py: send_thsr_booking_information / example_send_thsr_booking_information
# ----------------------------------------------------------------------------

STATION_EN_MAP = {
    '南港': 'NanGang', '台北': 'TPE', '板橋': 'BanQiao', '桃園': 'TaoYuan',
    '新竹': 'HSU',     '苗栗': 'MiaoLi', '台中': 'TaiChung', '彰化': 'ZhangHua',
    '雲林': 'YunLin',  '嘉義': 'JiaYi', '台南': 'TaiNan',   '左營': 'ZuoYing',
}

def _station_en(stn: str) -> str:
    return STATION_EN_MAP.get(stn, stn)

def send_thsr_booking_information(task_data: dict, result_msg: str):
    """
    訂票成功後，根據 task_data（來自 booking_tasks）及 result_msg 組裝通知訊息，
    並透過 Email 及 LINE 發送。

    task_data 預期包含：
        name, personal_id, phone_num, email, identity,
        start_station, end_station, travel_date, train_no,
        train_time, dep_time (radio33 模式的精確出發時間)
    result_msg 預期包含：
        '訂位代號: XXXXXXXX' (由 thsr_booking_flow 回傳)
        '座位: XXX' (由 thsr_booking_flow 回傳)
        '票價: XXX' (由 thsr_booking_flow 回傳)
        '付款期限: XXX' (由 thsr_booking_flow 回傳)
        '高鐵車次: XXX' (由 thsr_booking_flow 回傳)
        '高鐵座位: XXX' (由 thsr_booking_flow 回傳)
        '到達時間: XXX' (由 thsr_booking_flow 回傳)
        '出發時間: XXX' (由 thsr_booking_flow 回傳)
        '身份字號: XXX' (由 thsr_booking_flow 回傳)
        '訂位日期: XXX' (由 thsr_booking_flow 回傳)
        '付款金額: XXX' (由 thsr_booking_flow 回傳)
        '訂位時間: XXX' (由 thsr_booking_flow 回傳)
    """
    try:
        # --- 從 task_data 取得基本資訊 ---
        name          = task_data.get('name', 'Unknown')
        personal_id   = task_data.get('personal_id', '')
        email_addr    = task_data.get('email', '')
        phone_num     = task_data.get('phone_num', '')
        identity      = task_data.get('identity', 'adult')
        departure_stn = task_data.get('start_station', '')
        arrival_stn   = task_data.get('end_station', '')
        travel_date   = task_data.get('travel_date', '')   # 'YYYY/MM/DD'
        train_no      = task_data.get('train_no', '')

        # 出發時間：dep_time（radio33 TDX 精確時間）優先，fallback train_time
        dep_time  = (task_data.get('dep_time')   or '').strip()
        train_time = (task_data.get('train_time') or '').strip()
        dep_time_display = dep_time or train_time or 'N/A'

        # 到達時間：從 timetable_cache.json 查詢（用 travel_date + 起訖站 + train_no）
        arr_time_display = 'N/A'
        try:
            raw_date   = travel_date.replace('/', '-')  # cache key 用 YYYY-MM-DD
            cache_key  = f"{raw_date}|{departure_stn}|{arrival_stn}"
            cache      = load_json(TIMETABLE_FILE) or {}
            trains_for_day = cache.get(cache_key, [])
            for t in trains_for_day:
                if t.get('train_no') == train_no:
                    arr_time_display = t.get('arr_time', 'N/A')
                    break
        except Exception as e:
            logger.warning(f"[send_thsr] 查詢到達時間失敗: {e}")

        # --- 從 result_msg 解析訂位代號（唯一可靠來源）---
        def _parse(pattern, default='N/A'):
            m = re.search(pattern, result_msg)
            return m.group(1).strip() if m else default

        pnr_code         = _parse(r'訂位代號[：:]\s*(\S+)')
        seat_label       = _parse(r'座位[：:]\s*(\S+)')
        total_price      = _parse(r'票價[：:]\s*(TWD\s*\S+|[0-9]+\s*元|\S+)')
        payment_deadline = _parse(r'付款期限[：:]\s*(.+?)(?:\n|$)')

        # 身份證遮罩 (前4碼 + * + 末1碼)
        if personal_id and len(personal_id) > 5:
            masked_pid = personal_id[:4] + '*' * (len(personal_id) - 5) + personal_id[-1]
        else:
            masked_pid = '*' * len(personal_id)

        # 判斷是否學生票
        is_student = identity in ('university', 'student', '大學生', 'college')

        # 日期格式化 (取 MM/DD)
        try:
            dt = datetime.strptime(travel_date.replace('-', '/'), '%Y/%m/%d')
            departure_date_short = dt.strftime('%m/%d')
        except Exception:
            departure_date_short = travel_date

        # 訂位時間
        booking_date = datetime.now(CST_TIMEZONE).strftime('%m/%d %I:%M%p').lower()

        # 付款期限 (英文簡版)
        if payment_deadline == '發車前30分' or payment_deadline == 'N/A':
            payment_deadline_e = departure_date_short
        else:
            payment_deadline_e = payment_deadline[-5:] if len(payment_deadline) >= 5 else payment_deadline

        # 座位標籤英文化 (例: '4車2A' → '4-2A')
        seat_label_e = seat_label.replace('車', '-')

        # --- 組裝中文訊息 (Email body / LINE) ---
        price_display = '學生票價' if is_student else total_price

        msg = (
            f'訂位日期: {booking_date}\n'
            f'訂位代號: {pnr_code}\n'
            f'高鐵車次: {train_no}\n'
            f'乘車日期: {departure_date_short}\n'
            f'出發時間: {departure_stn} {dep_time_display}\n'
            f'到達時間: {arrival_stn} {arr_time_display}\n'
            f'高鐵座位: {seat_label}\n'
            f'身份字號: {masked_pid}\n'
            f'付款金額: {price_display}\n'
            f'付款期限: {payment_deadline}'
        )

        # --- 組裝英文 SMS 訊息 ---
        dep_en = _station_en(departure_stn)
        arr_en = _station_en(arrival_stn)
        price_e = 'Student' if is_student else total_price

        sms_body = (
            f'\nReservation: {pnr_code}\n'
            f'Date: {departure_date_short}, {dep_en} {dep_time_display} - {arr_en} {arr_time_display}\n'
            f'Seat: {seat_label_e}\n'
            f'ID No: {masked_pid}\n'
            f'Price: {price_e} (Due: {payment_deadline_e})'
        )

        # --- 發送 Email ---
        email_ctx = {
            'sender_email'    : NOTIFY_SENDER_EMAIL,
            'sender_password' : NOTIFY_SENDER_PASSWORD,
            'recipient_email' : email_addr,
            'email_subject'   : '"高鐵訂票成功"',
            'email_body'      : msg,
        }
        send_email(email_ctx)

        # --- 發送 LINE ---
        send_LINE_message(msg)

        logger.info(f"[通知] 訂票成功通知已發送 → {name} ({email_addr}), 訂位代號: {pnr_code}")

    except Exception as e:
        logger.error(f"[通知] 發送訂票通知失敗: {e}", exc_info=True)


# ----------------------------------------------------------------------------
# Worker Function for booking.py (Req 0, 1, 4, 5)
# ----------------------------------------------------------------------------
def run_booking_worker():
    global current_running_task_id
    global current_cancel_event

    # 下一輪迴圈開始前，需要在鎖外等待的秒數（由 BookingScheduler 決定）
    # 設計原則：delay sleep 必須在 with data_lock 區塊之外執行，避免長時間持鎖阻塞 Flask 請求
    _pending_retry_delay: int = 0

    while True:

        # ── 執行上一輪排定的 delay（在鎖外 sleep，不阻塞 Flask 請求）──
        if _pending_retry_delay > 0:
            logger.info(f"[Scheduler] 等待 {_pending_retry_delay}s 後進行下一次訂票...")
            time.sleep(_pending_retry_delay)
            _pending_retry_delay = 0

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
                    retry_count = task_to_run.get('retry_count', 0)
                    if retry_count > 0:
                        start_msg = f'開始第 {retry_count} 次重試訂票流程...'
                    else:
                        start_msg = '開始執行訂票流程...'
                    update_task_status(task_to_run['task_id'], 'running', start_msg)

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
                #   True  → simu_booking.thsr_run_booking_flow_simulation (模擬版本)
                #   False → thsr_booking.thsr_run_booking_flow            (真實版本)
                booking_fn = (
                    simu_booking.thsr_run_booking_flow_simulation
                    if USE_MOCK_BOOKING
                    else thsr_booking.thsr_run_booking_flow
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
                    
                    # --- START: booking_failed 重試邏輯 ---
                    if final_status == 'booking_failed':
                        retry_mode = current_task.get('retry_mode', 'stop')
                        retry_count = current_task.get('retry_count', 0)
                        retry_deadline_str = current_task.get('retry_deadline')

                        # 計算 retry_deadline（僅首次失敗時設定）
                        RETRY_MODE_MINUTES = {
                            '30m': 30, '1h': 60, '2h': 120, '4h': 240, '8h': 480
                        }
                        if retry_mode in RETRY_MODE_MINUTES and retry_deadline_str is None:
                            minutes = RETRY_MODE_MINUTES[retry_mode]
                            deadline = datetime.now(CST_TIMEZONE) + timedelta(minutes=minutes)
                            retry_deadline_str = deadline.strftime('%Y/%m/%d %H:%M:%S')
                            current_task['retry_deadline'] = retry_deadline_str

                        # 判斷是否應重試
                        should_retry = False
                        if retry_mode == 'forever':
                            should_retry = True
                        elif retry_mode in RETRY_MODE_MINUTES and retry_deadline_str:
                            try:
                                deadline_dt = datetime.strptime(retry_deadline_str, '%Y/%m/%d %H:%M:%S').replace(tzinfo=CST_TIMEZONE)
                                if datetime.now(CST_TIMEZONE) < deadline_dt:
                                    should_retry = True
                            except Exception:
                                pass

                        if should_retry:
                            # ── [Scheduler] 停止門檻檢查：出發前 N 分鐘內不再重試 ──
                            departure_dt = parse_departure_dt(current_task.get('data', {}))
                            if departure_dt and booking_scheduler.should_stop(departure_dt):
                                stop_mins = booking_scheduler._cfg.get('stop_before_departure_minutes', 5)
                                result_msg = (
                                    f'距出發時間不足 {stop_mins} 分鐘，停止搶票。'
                                    f'（已重試 {retry_count} 次）'
                                )
                                logger.info(
                                    f"[Scheduler] 任務 {current_running_task_id} "
                                    f"距出發時間太近，不再重試，標記為失敗。"
                                )
                                # 不 continue，讓後面的 update_task_status 標記為 failed
                            else:
                                # ── 正常重試流程 ──
                                retry_count += 1
                                current_task['retry_count'] = retry_count
                                current_task['last_fail_reason'] = result_msg   # 單獨保存上次失敗原因
                                current_task['status'] = 'pending'
                                current_task['message'] = f'準備第 {retry_count} 次重試...'
                                current_task['update_time'] = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')
                                save_json(TASKS_FILE, booking_tasks)
                                logger.info(f"任務 {current_running_task_id} 訂票失敗，將進行第 {retry_count} 次重試 (retry_mode={retry_mode})")

                                # ── [Scheduler] 計算下一輪的等待秒數（在鎖外執行）──
                                _pending_retry_delay = (
                                    booking_scheduler.get_delay_seconds(departure_dt)
                                    if departure_dt else 60
                                )
                                if _pending_retry_delay > 0:
                                    logger.info(
                                        f"[Scheduler] 下次重試將等待 {_pending_retry_delay}s "
                                        f"（{booking_scheduler.describe(departure_dt)}）"
                                    )

                                current_running_task_id = None
                                current_cancel_event = None
                                continue  # 直接進入下一輪 worker 迴圈
                        else:
                            # 不重試，標記為最終失敗
                            if retry_count > 0:
                                result_msg = f'訂票失敗（已重試 {retry_count} 次）。{result_msg}'
                    # --- END: booking_failed 重試邏輯 ---

                    # 如果成功，將結果寫入 history.json (略過)
                    # 確保將訂位代號存入 task 物件
                    if final_status == 'booking_success' and '訂位代號:' in result_msg:
                        # 從結果訊息中解析出訂位代號並儲存
                        match = re.search(r'訂位代號: (\w+)', result_msg)
                        if match:
                            booking_code = match.group(1)
                            current_task['booking_code'] = booking_code # <--- **新增這行**
                    
                        if (SEND_BOOKING_INFO == True):
                            # 發送 Email / LINE 訂票成功通知
                            threading.Thread(
                                target=send_thsr_booking_information,
                                args=(task_to_run['data'], result_msg),
                                daemon=True
                            ).start()
                    
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

        # --- START: 欄位正規化 (前端傳入值 → thsr_booking.py 所需格式) ---

        # 5a. travel_date: 統一轉為 'YYYY/MM/DD' (相容 'YYYY-MM-DD' 或已是 'YYYY/MM/DD')
        raw_date = data.get('travel_date', '')
        data['travel_date'] = raw_date.replace('-', '/')

        # 5b. identity: 中文票種 → thsr_booking.py IDENTITY_TO_TICKET_ROW key
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
        #     對應 thsr_booking.py trainCon:trainRadioGroup: 0=標準, 1=商務, 2=自由座
        SEAT_CLASS_ZH_TO_INT = {
            '標準車廂': 0,
            '商務車廂': 1,
            '自由座':   2,
        }
        raw_seat_class = data.pop('seat_class', '')
        data['class_type'] = SEAT_CLASS_ZH_TO_INT.get(raw_seat_class, 0)

        # 5d. seat_option: 中文座位喜好 → seat_prefer 整數
        #     對應 thsr_booking.py seatCon:seatRadioGroup: 0=無, 1=靠窗, 2=走道
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

        # dep_time：前端從 TDX /api/get_trains 回傳的精確出發時間（HH:MM）
        # radio33 模式下由前端帶入，供 BookingScheduler 計算 delay / stop 使用
        # 若前端未帶（舊版相容），維持空字串，parse_departure_dt 會 fallback
        dep_time = str(data.get('dep_time', '') or '').strip()
        if dep_time:
            # 正規化為 HH:MM（防禦前端帶來格式不一致）
            if not re.match(r'^\d{1,2}:\d{2}$', dep_time):
                dep_time = ''
            data['dep_time'] = dep_time
        else:
            data['dep_time'] = ''

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

        # --- START: 檢查是否已過期或即將到期 ---
        departure_dt = parse_departure_dt(data)
        if departure_dt and booking_scheduler.should_stop(departure_dt):
            stop_mins = booking_scheduler._cfg.get('stop_before_departure_minutes', 5)
            return jsonify({
                "status": "error", 
                "message": f"該班次已過期或距離出發時間不足 {stop_mins} 分鐘，無法受理訂票。"
            }), 400
        # --- END: 檢查是否已過期或即將到期 ---

        task_id = get_new_task_id()

        current_time_cst = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')

        # retry_mode 由前端傳入，預設為 'stop'（不重試）
        retry_mode = data.pop('retry_mode', 'stop') or 'stop'

        new_task = {
            'task_id': task_id,
            'status': 'pending',
            'submit_time': current_time_cst,
            'update_time': current_time_cst,
            'message': '等待執行...',
            'retry_mode': retry_mode,   # 'stop' | 'forever' | '30m' | '1h' | '2h' | '4h' | '8h'
            'retry_count': 0,           # 累計重試次數
            'retry_deadline': None,     # ISO 字串，到期時間 (None = 無限或不重試)
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
@app.route("/api/get_tasks_status", methods=["GET"])
def get_booking_status():

    print(CYAN + f"[/api/get_tasks_status] {datetime.now().strftime('%H:%M:%S')} ........." + RESET)

    # 每次前端請求狀態時，同時執行任務清理邏輯，並取得過濾後的列表
    tasks = load_tasks()

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
            'passenger_name':   data.get('name', '?'),
            'retry_count':      task.get('retry_count', 0),
            'retry_mode':       task.get('retry_mode', 'stop'),
            'retry_deadline':   task.get('retry_deadline'),
            'last_fail_reason': task.get('last_fail_reason', ''),   # ← 上次失敗原因
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
# 路由新增: 手動清理已完成任務
# ----------------------------------------------------------------------------
@app.route("/api/clear_completed_tasks", methods=["POST"])
def clear_completed_tasks():
    """
    手動清除 tasks.json 中所有非執行中（成功、失敗、取消、放棄等）的任務。
    """
    global booking_tasks
    with data_lock:
        ACTIVE_STATUSES = ['pending', 'running', 'cancelling']
        retained_tasks = []
        removed_count = 0
        history_list = None
        history_updated = False

        for task in booking_tasks:
            status = task.get('status')
            if status in ACTIVE_STATUSES:
                retained_tasks.append(task)
            else:
                # 確保在移除前已歸檔至歷史紀錄
                if history_list is None:
                    history_list = load_json(HISTORY_FILE) or []
                
                if not any(h.get('task_id') == task['task_id'] for h in history_list):
                    history_entry = task.copy()
                    history_entry['result'] = status
                    history_list.append(history_entry)
                    history_updated = True
                    logger.info(f"任務 {task['task_id']} 在手動清理前已自動補歸檔。")
                
                removed_count += 1

        if history_updated:
            save_json(HISTORY_FILE, history_list)

        if removed_count > 0:
            booking_tasks = retained_tasks
            save_json(TASKS_FILE, booking_tasks)
            logger.info(f"手動清理：已從任務列表中移除 {removed_count} 筆已完成/終止的任務。")

        return jsonify({
            "status": "success", 
            "message": f"已成功清理 {removed_count} 筆已完成任務。",
            "removed_count": removed_count
        }), 200

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
    return render_template("index.html",
                           passengers=passengers,
                           is_admin=session.get('is_admin', False),
                           password_set=admin_password_is_set())


# app.py: 修正 passenger_page 函式，強制姓名唯一性

@app.route("/passenger.html", methods=["GET", "POST"])
def passenger_page():
    # 讀取現有乘客列表，無論是 GET 或 POST 請求，都會在鎖定區間外先讀取
    # 這裡先讀取，如果 POST 失敗，可以直接返回這個列表
    passengers = load_json(PASSENGER_FILE)

    # 共用：根據 session 套用遮罩，傳入模板
    def _render(plist, **kwargs):
        is_admin = session.get('is_admin', False)
        masked = apply_passenger_mask(plist, is_admin)
        return render_template("passenger.html",
                               passengers=masked,
                               is_admin=is_admin,
                               **kwargs)

    if request.method == "POST":
        data = request.form
        name = data.get("name")
        
        # 1. 檢查 'name' 是否為空
        if not name or name.strip() == "":
            return _render(passengers, error="姓名不能為空。")
            
        # 2. 檢查 'name' 是否重複 (必須在寫入前完成)
        # 使用 data_lock 確保在讀取和寫入乘客檔案時的執行緒安全
        with data_lock:
            
            # 重新載入一次，以確保在檢查時拿到的是最新的數據（避免其他執行緒剛好新增了資料）
            passengers = load_json(PASSENGER_FILE)
            
            # 檢查是否存在相同姓名
            existing_names = [p.get("name") for p in passengers if p.get("name") is not None]
            
            if name in existing_names:
                return _render(passengers, error=f"錯誤：乘客姓名 '{name}' 已經存在，請使用獨特的名稱。")
                
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
            return _render(passengers, success=True)
    
    # GET 請求：顯示乘客列表
    return _render(passengers)

# ----------------------------------------------------------------------
# 注意：若您的 passenger.html 中沒有處理 error 參數，需要微幅修改 passenger.html
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------------
# 管理者密碼相關 helper
# ----------------------------------------------------------------------------
def _hash_password(password: str) -> str:
    """以 SHA-256 雜湊密碼後回傳 hex string。"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def admin_password_is_set() -> bool:
    """檢查 admin.json 是否已存有密碼雜湊。"""
    cfg = load_json(ADMIN_FILE)
    return isinstance(cfg, dict) and bool(cfg.get('password_hash'))

def verify_admin_password(password: str) -> bool:
    """驗證輸入密碼是否與已儲存的雜湊相符。"""
    cfg = load_json(ADMIN_FILE)
    if not isinstance(cfg, dict):
        return False
    return cfg.get('password_hash') == _hash_password(password)

# ----------------------------------------------------------------------------
# API：設定管理者密碼（僅在尚未設定時允許）
# POST /api/admin/set-password  body: { "password": "..." }
# ----------------------------------------------------------------------------
@app.route("/api/admin/set-password", methods=["POST"])
def api_admin_set_password():
    if admin_password_is_set():
        return jsonify({"status": "error", "message": "管理者密碼已設定，無法重新設定。"}), 403

    body = request.get_json(silent=True) or {}
    password = (body.get("password") or "").strip()
    if len(password) < 4:
        return jsonify({"status": "error", "message": "密碼長度至少需要 4 個字元。"}), 400

    with data_lock:
        save_json(ADMIN_FILE, {"password_hash": _hash_password(password)})

    logger.info("管理者密碼已完成初始設定。")
    return jsonify({"status": "success", "message": "管理者密碼設定成功。"}), 200

# ----------------------------------------------------------------------------
# API：取得管理者權限（登入）
# POST /api/admin/login  body: { "password": "..." }
# ----------------------------------------------------------------------------
@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    if not admin_password_is_set():
        return jsonify({"status": "error", "message": "管理者密碼尚未設定。"}), 400

    body = request.get_json(silent=True) or {}
    password = (body.get("password") or "").strip()

    if verify_admin_password(password):
        session['is_admin'] = True
        logger.info("管理者登入成功。")
        return jsonify({"status": "success", "message": "已取得管理者權限。"}), 200
    else:
        session.pop('is_admin', None)
        return jsonify({"status": "error", "message": "密碼錯誤。"}), 401

# ----------------------------------------------------------------------------
# API：放棄管理者權限（登出）
# POST /api/admin/logout
# ----------------------------------------------------------------------------
@app.route("/api/admin/logout", methods=["POST"])
def api_admin_logout():
    session.pop('is_admin', None)
    return jsonify({"status": "success", "message": "已登出管理者權限。"}), 200

# ----------------------------------------------------------------------------
# API：查詢目前管理者狀態
# GET /api/admin/status
# ----------------------------------------------------------------------------
@app.route("/api/admin/status", methods=["GET"])
def api_admin_status():
    return jsonify({
        "password_set": admin_password_is_set(),
        "is_admin":     session.get('is_admin', False),
    }), 200

# ----------------------------------------------------------------------------
# 乘客列表 API（供前端取得管理者權限後重新整理 sensitive data 用）
# GET /api/passenger/list
# ----------------------------------------------------------------------------
@app.route("/api/passenger/list", methods=["GET"])
def api_passenger_list():
    """
    根據目前 session 的管理者權限，回傳遮罩後的乘客列表。
    前端在登入/登出管理者後呼叫此 API 更新頁面資料，
    確保 sensitive data 顯示狀態與 session 一致。
    """
    is_admin = session.get('is_admin', False)
    with data_lock:
        passengers = load_json(PASSENGER_FILE)
    masked = apply_passenger_mask(passengers, is_admin)
    # 只回傳前端顯示所需欄位，原始 sensitive 欄位不輸出
    output = [
        {
            "id":                   p.get("id", ""),
            "name":                 p.get("name", ""),
            "identity":             p.get("identity", ""),
            "display_id":           p.get("display_id", ""),
            "display_personal_id":  p.get("display_personal_id", ""),
            "display_phone_num":    p.get("display_phone_num", ""),
            "display_email":        p.get("display_email", ""),
        }
        for p in masked
    ]
    return jsonify({"status": "success", "is_admin": is_admin, "passengers": output}), 200

# ----------------------------------------------------------------------------
# 刪除乘客 API
# ----------------------------------------------------------------------------
@app.route("/api/passenger/delete/<passenger_id>", methods=["DELETE"])
def delete_passenger(passenger_id):
    """
    刪除指定 ID 的乘客資料。
    Returns JSON: {"status": "success"|"error", "message": "..."}
    """
    with data_lock:
        passengers = load_json(PASSENGER_FILE)
        original_count = len(passengers)
        passengers = [p for p in passengers if str(p.get("id")) != str(passenger_id)]

        if len(passengers) == original_count:
            return jsonify({"status": "error", "message": f"找不到 ID 為 '{passenger_id}' 的乘客。"}), 404

        save_json(PASSENGER_FILE, passengers)

    logger.info(f"乘客 ID={passenger_id} 已刪除。")
    return jsonify({"status": "success", "message": f"乘客 {passenger_id} 已成功刪除。"}), 200


# ----------------------------------------------------------------------------
# 匯出乘客資料 API (Export as JSON)
# ----------------------------------------------------------------------------
@app.route("/api/passenger/export", methods=["GET"])
def export_passengers():
    """
    匯出所有乘客資料為 JSON 檔案下載。（需管理者權限）
    """
    if not session.get('is_admin'):
        return jsonify({"status": "error", "message": "需要管理者權限。"}), 403

    from flask import Response
    passengers = load_json(PASSENGER_FILE)
    json_str = json.dumps(passengers, indent=4, ensure_ascii=False)
    filename = f"passengers_{datetime.now(CST_TIMEZONE).strftime('%Y%m%d_%H%M%S')}.json"
    return Response(
        json_str,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ----------------------------------------------------------------------------
# 匯入乘客資料 API (Import from JSON)
# ----------------------------------------------------------------------------
@app.route("/api/passenger/import", methods=["POST"])
def import_passengers():
    """
    從上傳的 JSON 檔案匯入乘客資料。（需管理者權限）
    - 若姓名已存在則跳過（不覆蓋）。
    - Returns JSON: {"status": "success", "added": N, "skipped": N, "errors": [...]}
    """
    if not session.get('is_admin'):
        return jsonify({"status": "error", "message": "需要管理者權限。"}), 403

    if "file" not in request.files:
        return jsonify({"status": "error", "message": "未提供檔案，請上傳 JSON 檔案。"}), 400

    file = request.files["file"]
    if not file.filename.endswith(".json"):
        return jsonify({"status": "error", "message": "檔案格式錯誤，僅接受 .json 檔案。"}), 400

    try:
        content = file.read().decode("utf-8")
        imported = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return jsonify({"status": "error", "message": f"JSON 解析失敗：{str(e)}"}), 400

    if not isinstance(imported, list):
        return jsonify({"status": "error", "message": "JSON 格式錯誤，需為乘客物件的陣列。"}), 400

    REQUIRED_FIELDS = {"name", "personal_id", "phone_num", "email", "identity"}
    added = 0
    skipped = 0
    errors = []

    with data_lock:
        passengers = load_json(PASSENGER_FILE)
        existing_names = {p.get("name") for p in passengers if p.get("name")}

        for i, p in enumerate(imported):
            if not isinstance(p, dict):
                errors.append(f"第 {i+1} 筆資料格式錯誤（非物件）。")
                continue

            missing = REQUIRED_FIELDS - set(p.keys())
            if missing:
                errors.append(f"第 {i+1} 筆資料缺少欄位：{', '.join(missing)}。")
                continue

            name = p.get("name", "").strip()
            if not name:
                errors.append(f"第 {i+1} 筆資料姓名為空，已跳過。")
                skipped += 1
                continue

            if name in existing_names:
                skipped += 1
                continue

            new_passenger = {
                "id": get_new_passenger_id(),
                "name": name,
                "personal_id": p.get("personal_id"),
                "phone_num": p.get("phone_num"),
                "email": p.get("email"),
                "identity": p.get("identity"),
            }
            passengers.append(new_passenger)
            existing_names.add(name)
            added += 1
            # 避免同一毫秒產生重複 ID
            time.sleep(0.002)

        if added > 0:
            save_json(PASSENGER_FILE, passengers)

    logger.info(f"匯入乘客完成：新增 {added} 筆，跳過 {skipped} 筆，錯誤 {len(errors)} 筆。")
    return jsonify({
        "status": "success",
        "added": added,
        "skipped": skipped,
        "errors": errors,
        "message": f"匯入完成：新增 {added} 筆，跳過 {skipped} 筆。"
    }), 200

@app.route("/history.html")
def history_page():
    # 這裡的邏輯需要與實際的 history.json 格式相符
    # history = load_json(HISTORY_FILE)     # ❌ 直接讀 JSON，無格式化
    history = load_history()                # ✅ 使用 load_history()，包含格式化
    
    # 假設 history.json 中的每個項目已經包含所需的鍵
    # 為了簡化，這裡僅傳遞 history 列表
    return render_template("history.html", history=history if history else [])

# ----------------------------------------------------------------------------
# 清理過期的時刻表快取（以天為單位）
# ----------------------------------------------------------------------------
def cleanup_timetable_cache():
    """
    檢查並移除 timetable_cache.json 中日期早於今天的資料。
    每天僅會執行一次完整掃描。
    """
    global last_cache_cleanup_date
    today = datetime.now(CST_TIMEZONE).date()

    if last_cache_cleanup_date == today:
        return

    with data_lock:
        cache = load_json(TIMETABLE_FILE)
        if not cache or not isinstance(cache, dict):
            last_cache_cleanup_date = today
            return

        new_cache = {}
        removed_count = 0
        for k, v in cache.items():
            try:
                # key 格式："{date}|{origin}|{destination}"，例如 "2026-03-28|台北|左營"
                date_str = k.split('|')[0]
                cache_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                if cache_date >= today:
                    new_cache[k] = v
                else:
                    removed_count += 1
            except (ValueError, IndexError):
                removed_count += 1

        if removed_count > 0:
            save_json(TIMETABLE_FILE, new_cache)
            logger.info(f"[Cache Cleanup] 已從快取中移除 {removed_count} 筆過期班次資料。")

        last_cache_cleanup_date = today
    
# ----------------------------------------------------------------------------
# 根據日期及起訖站，查詢高鐵班次下拉選單資料。
# TDX_APP_ID, TDX_APP_KEY 由 config.py 提供 (from config import *)
#
# 快取機制（timetable_cache.json）：
#   key 格式："{date}|{origin}|{destination}"  例："2026-03-28|新竹|台北"
#   value：trains 陣列（含 dep_time, arr_time, has_discount ...）
#   優先讀取快取；快取 miss 才呼叫 TDX API，成功後寫入快取。
#   優惠資訊（has_discount）在快取 miss 時一併寫入；快取 hit 時直接返回，不重查。
# ----------------------------------------------------------------------------
@app.route('/api/get_trains', methods=['GET'])
def api_get_trains():
    """
    查詢高鐵班次下拉選單資料（優先讀快取，miss 才呼叫 TDX）。

    Query Parameters:
        origin      (str): 出發站名稱，例如 '台北'
        destination (str): 到達站名稱，例如 '台中'
        date        (str): 乘車日期 YYYY-MM-DD

    Returns (JSON):
        {
            "status": "success",
            "source": "cache" | "tdx",
            "trains": [ { "train_no", "dep_time", "arr_time", "has_discount" }, ... ]
        }
    """
    origin      = request.args.get('origin', '').strip()
    destination = request.args.get('destination', '').strip()
    date        = request.args.get('date', '').strip()

    if not origin or not destination or not date:
        return jsonify({'status': 'error', 'message': '缺少必要參數 origin / destination / date'}), 400

    # 執行每日快取清理
    cleanup_timetable_cache()

    cache_key = f"{date}|{origin}|{destination}"

    # ── 快取讀取 ──
    try:
        cache = load_json(TIMETABLE_FILE) or {}
        if cache_key in cache:
            cached_trains = cache[cache_key]
            logger.info(f'[快取 HIT] ({date} {origin}-{destination}) 共 {len(cached_trains)} 班，直接返回快取資料')
            return jsonify({'status': 'success', 'source': 'cache', 'trains': cached_trains})
    except Exception as e:
        logger.warning(f'[快取讀取失敗] {e}，繼續呼叫 TDX API')

    # ── 快取 MISS → 呼叫 TDX API ──
    try:
        trains = get_thsr_timetable_od_by_name(
            app_id=TDX_APP_ID,
            app_key=TDX_APP_KEY,
            origin_name=origin,
            destination_name=destination,
            train_date=date,
        )

        train_no_list = [t['train_no'] for t in trains]
        logger.info(f'[TDX] ({date} {origin}-{destination}) 高鐵班次共有 {len(train_no_list)} 班: {train_no_list}')

        # 查詢大學生優惠，失敗時回傳空 dict，不影響主流程
        discount_map = check_discounts_for_list(
            StartStation=origin,
            EndStation=destination,
            target_date=date,
            train_no_list=train_no_list,
            discount_type='大學生',
        )

        # 將優惠資訊合併到班次資料中（若有）
        for t in trains:
            has_discount = discount_map.get(t['train_no'], False)
            t['has_discount'] = has_discount

        # ── 寫入快取 ──
        try:
            cache = load_json(TIMETABLE_FILE) or {}
            cache[cache_key] = trains
            save_json(TIMETABLE_FILE, cache)
            logger.info(f'[快取寫入] key={cache_key}，共 {len(trains)} 班')
        except Exception as e:
            logger.warning(f'[快取寫入失敗] {e}')

        return jsonify({'status': 'success', 'source': 'tdx', 'trains': trains})

    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    except Exception as e:
        err_str = str(e)
        logger.error(f'api_get_trains error: {err_str}')

        # 網路層錯誤：給前端友善訊息，不噴原始 urllib3 堆疊
        if 'NameResolutionError' in err_str or 'Failed to resolve' in err_str:
            msg = 'TDX 班次查詢服務暫時無法連線（DNS 解析失敗），請稍後再試。'
        elif 'timed out' in err_str.lower() or 'Timeout' in err_str:
            msg = 'TDX 班次查詢服務回應逾時，請稍後再試。'
        elif 'ConnectionError' in err_str or 'Max retries exceeded' in err_str:
            msg = 'TDX 班次查詢服務連線失敗，請確認網路狀態後再試。'
        else:
            msg = '班次查詢失敗，請稍後再試。'

        return jsonify({'status': 'error', 'message': msg}), 503


@app.route('/api/get_discounts', methods=['POST'])
def api_get_discounts():
    """
    查詢指定班次中，哪些有大學生優惠。
    Response 只回有優惠的車次 list，最小化 upload 流量。

    Request JSON:
        {
            "origin":  "新竹",
            "dest":    "台北",
            "date":    "2026-04-27",
            "trains":  ["0502", "1504", ...]
        }

    Response JSON:
        {
            "status": "success",
            "discount_trains": ["1504", ...]   // 只含有優惠的車次
        }
    """
    body       = request.get_json(force=True, silent=True) or {}
    origin     = body.get('origin', '').strip()
    dest       = body.get('dest', '').strip()
    date       = body.get('date', '').strip()
    train_list = body.get('trains', [])

    if not origin or not dest or not date or not train_list:
        return jsonify({'status': 'error', 'message': '缺少必要參數 origin / dest / date / trains'}), 400

    discount_map = check_discounts_for_list(
        StartStation=origin,
        EndStation=dest,
        target_date=date,
        train_no_list=train_list,
        discount_type='大學生',
    )

    # 只回有優惠的車次，減少 upload 流量
    discount_trains = [no for no in train_list if discount_map.get(no, False)]

    return jsonify({'status': 'success', 'discount_trains': discount_trains})


# [scott@2026-03-26] 移到這裡！確保 Gunicorn 載入時就會啟動 Worker
start_booking_worker_thread()


if __name__ == "__main__":

    # 確保在直接執行 app.py 時啟動 worker
    # [scott@2026-03-14] 是否應該移到最上面, 理由如下:
    #     為了確保 Gunicorn worker 也啟動，請將 start_booking_worker_thread()
    #     放在 app = Flask(__name__) 之後的頂層代碼區塊。
    # start_booking_worker_thread()

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