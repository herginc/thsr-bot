# =======================================================
# app.py (Flask Web Server) - 已更新，支援任務隊列、背景執行緒與取消
# =======================================================

# Must for Render environment
import gevent.monkey
gevent.monkey.patch_all()

import os
import sys
import json
import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from argparse import ArgumentParser

from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, request, abort, render_template, jsonify, redirect

import booking
import re

# --- 檔案名稱配置 ---
PASSENGER_FILE  = 'passenger.json'
TASKS_FILE      = 'tasks.json'
HISTORY_FILE    = 'history.json'

# --- Helper Functions ---
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

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_new_passenger_id():
    # 假設的 ID 生成器
    return int(time.time() * 1000)


def load_tasks():
    """
    載入任務列表，並清除tasks.json中過期的已完成任務。
    同時將訂票資訊格式化為 '左營 - 台南 (11-19 23:45)'
    """
    global booking_tasks
    
    with data_lock:
        booking_tasks = load_json(TASKS_FILE)
        
        FINAL_STATUSES = ['success', 'failed', 'cancelled']
        retained_tasks = []
        now_cst = datetime.now(CST_TIMEZONE)
        
        expired_count = 0
        
        for task in booking_tasks:
            task_status = task.get('status')
            
            # --- START: 格式化訂票資訊 (修正 #1: index.html 路線格式) ---
            data = task.get('data', {})
            start_station = data.get('start_station', '?')
            end_station = data.get('end_station', '?')
            travel_date = data.get('travel_date', '????-??-??')
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
            task['formatted_route'] = f"{start_station} - {end_station} ({formatted_date} {train_time})"
            # --- END: 格式化訂票資訊 ---

            
            if task_status not in FINAL_STATUSES:
                # 任務正在進行中 (pending 或 running)，直接保留
                retained_tasks.append(task)
                continue
            
            # --- 處理已完成任務的過期邏輯 (保持不變) ---
            finish_time_str = task.get('finish_time')
            # ... (省略過期檢查的 if/else 邏輯) ...
            
            if not finish_time_str:
                retained_tasks.append(task)
                continue
                
            try:
                finish_datetime = datetime.strptime(finish_time_str, '%Y/%m/%d %H:%M:%S').replace(tzinfo=CST_TIMEZONE)
                is_expired = False
                
                if task_status == 'success':
                    cutoff_date = (now_cst - timedelta(days=2)).date()
                    if finish_datetime.date() < cutoff_date:
                        is_expired = True
                        
                else: 
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


def load_tasks_old():
    """
    載入任務列表，並清除和歸檔過期的已完成任務。
    - 成功訂單: 保留 2 天
    - 失敗/取消訂單: 保留 60 分鐘 (1 小時)
    """    
    global booking_tasks
    
    with data_lock:
        booking_tasks = load_json(TASKS_FILE)
        
        FINAL_STATUSES = ['success', 'failed', 'cancelled']
        retained_tasks = []
        archived_tasks = []
        now_cst = datetime.now(CST_TIMEZONE)
        
        expired_count = 0
        
        for task in booking_tasks:
            task_status = task.get('status')
            
            if task_status not in FINAL_STATUSES:
                # 任務正在進行中 (pending 或 running)，直接保留
                retained_tasks.append(task)
                continue
            
            # --- 處理已完成任務的過期邏輯 ---
            finish_time_str = task.get('finish_time')
            if not finish_time_str:
                # 如果沒有完成時間，表示資料有問題，為安全起見保留
                retained_tasks.append(task)
                continue
                
            try:
                finish_datetime = datetime.strptime(finish_time_str, '%Y/%m/%d %H:%M:%S').replace(tzinfo=CST_TIMEZONE)
                is_expired = False
                
                if task_status == 'success':
                    # 成功訂單：保留 2 天 (即在 3 天前的 00:00:00 之後的訂單)
                    cutoff_date = (now_cst - timedelta(days=2)).date()
                    if finish_datetime.date() < cutoff_date:
                        is_expired = True
                        
                else: # failed 或 cancelled
                    # 失敗或取消訂單：保留 60 分鐘
                    cutoff_datetime = now_cst - timedelta(minutes=60)
                    if finish_datetime < cutoff_datetime:
                        is_expired = True
                        
            except Exception as e:
                # 日期解析錯誤，保留任務
                print(f"Warning: Failed to parse finish_time for task {task.get('task_id', 'N/A')}: {e}")
                retained_tasks.append(task)
                continue
                
            
            if is_expired:
                # 任務過期：準備歸檔
                expired_count += 1
                archived_tasks.append(task)
            else:
                # 任務未過期：保留在 tasks 列表中以供 /api/status 顯示
                retained_tasks.append(task)


        # 3. 執行歸檔操作
        if expired_count > 0:
            print(f"Archiving {expired_count} expired completed tasks from tasks.json.")
            
            # A. 更新 tasks.json (只保留未過期的)
            booking_tasks = retained_tasks
            save_json(TASKS_FILE, booking_tasks) 

            # B. 寫入 history.json (歸檔過期任務)
            history_list = load_json(HISTORY_FILE)
            for task in archived_tasks:
                # 轉換為 history 格式
                history_entry = {
                    'task_id': task['task_id'],
                    'result': task['status'],
                    'code': task.get('booking_code', 'N/A'),
                    'submit_time': task['submit_time'],
                    'finish_time': task['finish_time'],
                    'message': task['message'],
                    'data': task['data'], 
                    'name': task['data'].get('name', 'N/A'),
                    'personal_id': task['data'].get('personal_id', 'N/A'),
                    'train_no': task['data'].get('train_no', 'N/A'),
                    'travel_date': task['data'].get('travel_date', 'N/A'),
                    'start_station': task['data'].get('start_station', 'N/A'),
                    'end_station': task['data'].get('end_station', 'N/A'),
                }
                history_list.append(history_entry)
            
            save_json(HISTORY_FILE, history_list) 
            
        # 4. 返回給 /api/status 的數據 (僅包含未過期的所有任務)
        return retained_tasks


# app.py: 修正 load_history 函式

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
                    h['result_text'] = {'success': '成功', 'failed': '失敗', 'cancelled': '已取消'}.get(h.get('result', ''), '未知')
                    
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


# 修正 load_history 函式 (確保與 load_tasks 分工)

def load_history_old2():
    """
    載入歷史紀錄 (history.json)，並清理超過 365 天的紀錄。
    用於 history.html 頁面的長期查詢。
    """
    
    # 確保鎖定共享資源
    with data_lock:
        history_list = load_json(HISTORY_FILE)
        
        now_cst = datetime.now(CST_TIMEZONE)
        
        # 設置保留天數為 365 天 (一年)
        retention_days = 365 
        
        # 計算截止日期：今天日期往前推 365 天的 00:00:00
        cutoff_date = (now_cst - timedelta(days=retention_days)).date()

        retained_history = []
        expired_count = 0
        
        for h in history_list:
            finish_time_str = h.get('finish_time')
            
            try:
                # 解析任務完成時間
                finish_datetime = datetime.strptime(finish_time_str, '%Y/%m/%d %H:%M:%S').replace(tzinfo=CST_TIMEZONE)
                
                # 檢查：如果完成日期早於截止日期，則視為過期
                if finish_datetime.date() < cutoff_date:
                    expired_count += 1
                else:
                    # --- 格式化數據供 history.html 顯示 ---
                    
                    # 格式化完成時間
                    h['formatted_finish_time'] = finish_datetime.strftime('%Y/%m/%d %H:%M:%S')
                    
                    # 格式化出發/到達資訊
                    h['from_info'] = f"{h.get('start_station', 'N/A')}"
                    h['to_info'] = f"{h.get('end_station', 'N/A')}"
                    
                    # 格式化其他欄位
                    h['formatted_travel_date'] = h['data'].get('travel_date', 'N/A')
                    h['result'] = {'success': '成功', 'failed': '失敗', 'cancelled': '已取消'}.get(h['result'], h['result'])
                    
                    retained_history.append(h)
                    
            except Exception as e:
                # 如果日期解析失敗 (例如 finish_time 欄位缺失或格式錯誤)，則保留紀錄
                print(f"Warning: Failed to parse history date for task {h.get('task_id', 'N/A')}. Retaining. Error: {e}")
                retained_history.append(h)
                
        
        # 如果有紀錄被刪除，則將清理後的列表寫回 history.json
        if expired_count > 0:
            print(f"Cleaned up {expired_count} expired history entries (older than {retention_days} days).")
            # 準備寫入檔案的列表 (移除格式化欄位以減小檔案大小)
            history_to_save = [{k: v for k, v in h.items() if not k.startswith('formatted_') and k not in ['from_info', 'to_info']} for h in retained_history]
            save_json(HISTORY_FILE, history_to_save)
        
        # 返回要顯示在 history.html 上的列表
        return retained_history


def load_history_old():
    """
    載入歷史紀錄並刪除超過 2 天的紀錄。
    """
    # 確保鎖定
    with data_lock:
        history_list = load_json(HISTORY_FILE)
        
        # 1. 設置截止時間 (Current Date - 2 Days)
        # 這裡我們使用任務完成時間 (finish_time) 來判斷是否過期
        
        # 今天 00:00:00 的時間戳
        now_cst = datetime.now(CST_TIMEZONE)
        
        # 過期截止日期的 00:00:00
        # 如果要保留 2 天，則截止時間是 3 天前的 00:00:00
        # 範例: 今天是 10/3 23:00，截止日期是 10/1 00:00:00。10/1 的訂單將被刪除。
        # 為了保留完整 2 天，我們設定截止時間為 (今天日期 - 2 天)
        
        retention_days = 2
        cutoff_date = (now_cst - timedelta(days=retention_days)).date() # 只需要日期部分

        # 2. 過濾並移除過期紀錄
        retained_history = []
        expired_count = 0
        
        for h in history_list:
            finish_time_str = h.get('finish_time') # 使用 'finish_time' 判斷
            
            try:
                # 解析完成時間的日期
                # 格式應為 '%Y/%m/%d %H:%M:%S'
                finish_datetime = datetime.strptime(finish_time_str, '%Y/%m/%d %H:%M:%S').replace(tzinfo=CST_TIMEZONE)
                
                # 檢查是否過期 (如果 finish_datetime 的日期早於 cutoff_date，則視為過期)
                if finish_datetime.date() < cutoff_date:
                    expired_count += 1
                else:
                    # 格式化顯示所需欄位
                    h['formatted_finish_time'] = finish_datetime.strftime('%Y/%m/%d %H:%M:%S')
                    h['from_info'] = f"{h.get('start_station', 'N/A')} {h['data'].get('start_time', '')}"
                    h['to_info'] = f"{h.get('end_station', 'N/A')} {h['data'].get('end_time', '')}"
                    h['formatted_travel_date'] = h['data'].get('travel_date', 'N/A')
                    h['result'] = {'success': '成功', 'failed': '失敗', 'cancelled': '已取消'}.get(h['result'], h['result'])
                    retained_history.append(h)
                    
            except Exception as e:
                # 處理日期解析錯誤的歷史紀錄 (保留)
                print(f"Warning: Failed to parse history date for task {h.get('task_id', 'N/A')}: {e}")
                retained_history.append(h)
                
        
        # 3. 如果有紀錄被刪除，則儲存新的 history.json
        if expired_count > 0:
            print(f"Cleaned up {expired_count} expired history entries (older than {retention_days} days).")
            # 只保留歷史紀錄的核心數據，刪除格式化欄位以減小檔案大小
            history_to_save = [{k: v for k, v in h.items() if not k.startswith('formatted_') and k not in ['from_info', 'to_info']} for h in retained_history]
            save_json(HISTORY_FILE, history_to_save)
        
        # 返回要顯示在 history.html 上的列表
        return retained_history


# --- 核心配置與全局狀態 ---
# 使用 timedelta 支援 Python 3.8
CST_TIMEZONE = timezone(timedelta(hours=8))

data_lock = threading.RLock()

# --- 全局狀態新增 ---
booking_thread: Optional[threading.Thread] = None
current_running_task_id: Optional[str] = None
# 載入上次的任務，並將所有 'running' 狀態重設為 'failed' 或 'pending'
booking_tasks: List[Dict[str, Any]] = load_json(TASKS_FILE) 
for task in booking_tasks:
    if task['status'] == 'running' or task['status'] == 'cancelling':
        task['status'] = 'failed'
        task['message'] = '伺服器重啟，任務失敗或已中斷。'
        task['update_time'] = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')

next_task_id = len(booking_tasks) + 1 
current_cancel_event: Optional[threading.Event] = None
# --- 核心配置與全局狀態 (保持不變) ---

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ----------------------------------------------------------------------------
# 啟動背景 Worker 執行緒 (兼容 Gunicorn 和 python app.py)
# ----------------------------------------------------------------------------
# 必須在 app 實例化之後調用，並定義為一般函式
def start_booking_worker_thread():
    global booking_thread
    with data_lock:
        if booking_thread is None or not booking_thread.is_alive():
            print(f"[{datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')}] 啟動背景訂票 worker 執行緒...")
            booking_thread = threading.Thread(target=run_booking_worker, daemon=True)
            booking_thread.start()

def get_new_task_id() -> str:
    global next_task_id
    with data_lock:
        task_id = str(next_task_id)
        next_task_id += 1
        # 使用時間戳 + id 確保唯一性
        return datetime.now(CST_TIMEZONE).strftime('%Y%m%d%H%M%S') + '-' + task_id

def get_task_by_id(task_id: str) -> Optional[Dict[str, Any]]:
    # 注意：此函式預期在 data_lock 內被呼叫，或僅用於讀取
    for task in booking_tasks:
        if task['task_id'] == task_id:
            return task
    return None


# app.py: 修正 update_task_status 函式 (確保 history.json 數據最完整)

def update_task_status(task_id: str, new_status: str, message: str):
    """
    更新任務狀態並記錄更新時間。
    如果任務完成 (success/failed/cancelled)，則立即將其歸檔到 history.json (完整數據)。
    """
    global booking_tasks
    
    with data_lock:
        task = get_task_by_id(task_id)
        if task is None:
            return

        task['status'] = new_status
        task['message'] = message
        task['update_time'] = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')

        FINAL_STATUSES = ['success', 'failed', 'cancelled']
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
            
            # 移除前端格式化欄位 (如果存在)
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


def update_task_status_old3(task_id: str, new_status: str, message: str):
    """
    更新任務狀態並記錄更新時間。
    如果任務完成 (success/failed/cancelled)，則立即將其歸檔到 history.json。
    """
    global booking_tasks
    
    with data_lock:
        task = get_task_by_id(task_id)
        if task is None:
            # 任務已經被清理或不存在
            return

        task['status'] = new_status
        task['message'] = message
        task['update_time'] = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')

        FINAL_STATUSES = ['success', 'failed', 'cancelled']
        if new_status in FINAL_STATUSES:
            # 1. 更新任務完成時間
            task['finish_time'] = task['update_time'] 
            
            # 2. 立即歸檔到 history.json (修正歷史紀錄不顯示的問題)
            history_list = load_json(HISTORY_FILE)
            history_entry = {
                'task_id': task['task_id'],
                'result': new_status, 
                'code': task.get('booking_code', 'N/A'), 
                'submit_time': task['submit_time'],
                'finish_time': task['finish_time'], 
                'message': task['message'],
                'data': task['data'], 
                'name': task['data'].get('name', 'N/A'),
                'personal_id': task['data'].get('personal_id', 'N/A'),
                'train_no': task['data'].get('train_no', 'N/A'), 
                'travel_date': task['data'].get('travel_date', 'N/A'),
                'start_station': task['data'].get('start_station', 'N/A'),
                'end_station': task['data'].get('end_station', 'N/A'),
            }
            history_list.append(history_entry)
            save_json(HISTORY_FILE, history_list) 
            
            print(f"Task {task_id} completed ({new_status}). Archived to history.json immediately.")
            
        # 3. 儲存更新後的 tasks.json (讓 load_tasks 處理 index.html 的短期保留)
        save_json(TASKS_FILE, booking_tasks)


def update_task_status_old2(task_id: str, new_status: str, message: str):
    """
    更新任務狀態並記錄更新時間。
    任務完成後 (success/failed/cancelled)，不會立即移除，留待 load_tasks 處理。
    """
    global booking_tasks
    
    with data_lock:
        task = get_task_by_id(task_id)
        if task is None:
            # 任務已經被清理或不存在
            return

        task['status'] = new_status
        task['message'] = message
        task['update_time'] = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')

        FINAL_STATUSES = ['success', 'failed', 'cancelled']
        if new_status in FINAL_STATUSES:
            # 這是任務完成的實際時間
            task['finish_time'] = task['update_time'] 
            
            # 如果成功，且 booking_code 尚未設定，則嘗試解析並設定
            if new_status == 'success' and 'booking_code' in task and '訂位代號:' in message:
                 # 這裡假設 run_booking_worker 已經將 booking_code 寫入 task
                 pass

            print(f"Task {task_id} completed ({new_status}). Sticking in tasks list for now.")

        # 儲存更新後的 tasks.json (無論狀態是否改變)
        save_json(TASKS_FILE, booking_tasks)


def update_task_status_old(task_id: str, new_status: str, message: str):
    """
    更新任務狀態並記錄更新時間。
    如果任務完成 (success/failed/cancelled)，則將其從 task 列表移至 history。
    """
    global booking_tasks
    
    # 確保鎖定 (data_lock 在 app.py 頂部已定義為 threading.RLock())
    with data_lock:
        
        # 1. 更新 tasks 列表
        task = get_task_by_id(task_id)
        if task is None:
            print(f"Warning: Task {task_id} not found for status update.")
            return

        task['status'] = new_status
        task['message'] = message
        task['update_time'] = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')

        # 2. 如果任務已完成，則將其移至 history
        FINAL_STATUSES = ['success', 'failed', 'cancelled']
        if new_status in FINAL_STATUSES:
            
            # 從 booking_tasks 移除
            booking_tasks = [t for t in booking_tasks if t['task_id'] != task_id]
            save_json(TASKS_FILE, booking_tasks) # 儲存更新後的 tasks.json

            # 寫入 history 列表
            history_list = load_json(HISTORY_FILE)
            
            # 確保歷史紀錄包含所有必要欄位（特別是訂票結果 result 和完成時間）
            # 這裡我們使用 'submit_time' 作為完成時間的日期基礎，但最好是新增一個 'finish_time'
            
            # 準備 history 格式
            history_entry = {
                # 歷史記錄所需的基礎欄位
                'task_id': task['task_id'],
                'result': new_status, # success, failed, cancelled
                'code': task.get('booking_code', 'N/A'), # 如果成功，這裡應該有訂位代號
                'submit_time': task['submit_time'],
                'finish_time': task['update_time'], # 任務完成的實際時間
                'message': task['message'],
                
                # 訂票資訊 (從 task['data'] 中取出)
                'data': task['data'], 
                'name': task['data'].get('name', 'N/A'),
                'personal_id': task['data'].get('personal_id', 'N/A'),
                'train_no': task['data'].get('train_no', 'N/A'), # 如果訂票成功，這裡可能需要更新
                'travel_date': task['data'].get('travel_date', 'N/A'),
                'start_station': task['data'].get('start_station', 'N/A'),
                'end_station': task['data'].get('end_station', 'N/A'),
            }
            
            history_list.append(history_entry)
            save_json(HISTORY_FILE, history_list) # 儲存更新後的 history.json
            
            print(f"Task {task_id} completed ({new_status}). Moved to history.")


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
            if current_running_task_id is not None:
                # 已經有任務在跑
                should_sleep = True 
                # !!! 修正: 移除這裡的 time.sleep(1)
                
            else:
                pending_tasks = [t for t in booking_tasks if t['status'] == 'pending']
                if not pending_tasks:
                    # 沒有待處理任務
                    should_sleep = True 
                    # !!! 修正: 移除這裡的 time.sleep(1)
                else:
                    # 取得並設置為 'running'
                    task_to_run = pending_tasks[0]
                    current_running_task_id = task_to_run['task_id']
                    current_cancel_event = threading.Event()
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
                # 執行訂票流程 (在鎖之外執行)
                success, result_msg = booking.thsr_run_booking_flow_with_data( 
                    task_to_run['task_id'], 
                    task_to_run['data'], 
                    current_cancel_event,
                    update_task_status
                )
                final_status = 'success' if success else 'failed'
                
            except Exception as e:
                final_status = 'failed'
                result_msg = f"執行錯誤: {e}"
            
            # 任務完成後更新狀態並清除運行中的標記 (重新鎖定)
            with data_lock:
                current_task = get_task_by_id(current_running_task_id)
                if current_task and (current_task['status'] == 'running' or current_task['status'] == 'cancelling'):
                    
                    if current_task['status'] == 'cancelling':
                        final_status = 'cancelled'
                        if '被使用者取消' not in result_msg:
                            result_msg = '任務被使用者強制取消。'
                    
                    # 如果成功，將結果寫入 history.json (略過)
                    # 確保將訂位代號存入 task 物件
                    if final_status == 'success' and '訂位代號:' in result_msg:
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

@app.route('/api/passenger', methods=['GET'])
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
                    'id': p.get('id'),         # 不敏感的 ID 作為下拉選單的 value
                    'name': p.get('name')     # 姓名作為顯示文本
                })
            
        return jsonify(safe_passengers)


# ============================================================================
# app.py 修正: /api/submit 路由 (確保異常處理)
# ============================================================================
@app.route("/api/submit", methods=["POST"])
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
# 路由修改 (Req 4: 提交訂票)
# ----------------------------------------------------------------------------
@app.route("/api/submit_NG", methods=["POST"])
def submit_booking_NG():

    try:
        data = request.json
        if not data:
            abort(400, "Invalid JSON data")

        task_id = get_new_task_id()
        current_time_cst = datetime.now(CST_TIMEZONE).strftime('%Y/%m/%d %H:%M:%S')

        new_task = {
            'task_id': task_id,
            'status': 'pending',
            'submit_time': current_time_cst,
            'update_time': current_time_cst,
            'message': '等待執行...',
            'data': data
        }

        with data_lock:
            booking_tasks.append(new_task)
            save_json(TASKS_FILE, booking_tasks)
            
        return jsonify({"status": "success", "message": "訂票任務已加入隊列", "task_id": task_id}), 200

    except Exception as e:
        # logger.error(f"Submit error: {e}")
        return jsonify({"status": "error", "message": f"提交失敗: {e}"}), 500

# ----------------------------------------------------------------------------
# 路由新增 (Req 3: 動態查詢狀態)
# ----------------------------------------------------------------------------
@app.route("/api/status", methods=["GET"])
def get_booking_status():
    with data_lock:
        tasks = list(booking_tasks) 
        
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
            'train_info': f"從 {data.get('start_station', '?')} 到 {data.get('end_station', '?')} ({data.get('travel_date', '?')} {data.get('train_time', '?')})",
            'passenger_name': data.get('name', '?')
        })
        
    worker_status = 'running' if booking_thread and booking_thread.is_alive() and current_running_task_id else 'idle'
    if worker_status == 'running':
        worker_status += f" (Task ID: {current_running_task_id})"
        
    return jsonify({
        "status": "success",
        "worker_status": worker_status,
        "tasks": status_list
    }), 200

# ----------------------------------------------------------------------------
# 路由新增 (Req 2: 刪除/取消訂票)
# ----------------------------------------------------------------------------
@app.route("/api/cancel/<string:task_id>", methods=["POST"])
def cancel_booking(task_id):
    global current_running_task_id
    global current_cancel_event
    
    with data_lock:
        task = get_task_by_id(task_id)
        if not task:
            return jsonify({"status": "error", "message": f"找不到任務 ID: {task_id}"}), 404
        
        current_status = task['status']
        
        if current_status == 'pending':
            update_task_status(task_id, 'cancelled', '任務已從隊列中取消。')
            return jsonify({"status": "success", "message": f"任務 {task_id} 已從隊列中移除。"}), 200
        
        elif current_status == 'running':
            # 檢查是否為當前正在運行的任務
            if current_running_task_id == task_id and current_cancel_event:
                current_cancel_event.set() # 發送取消信號
                # 將狀態設為 'cancelling'，等待 worker 執行緒響應並將最終狀態設為 'cancelled'
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


# @app.route("/")
# def index_page():
#     # 確保 passengers 數據能正確傳遞
#     passengers = load_json(PASSENGER_FILE)
#     if not passengers:
#         # 添加一個預設選項
#         passengers = [{"id": "", "name": "請先新增乘客個人資料"}] 
        
#     return render_template("index.html", passengers=passengers)


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


# @app.route("/passenger.html", methods=["GET", "POST"])
# def passenger_page():
#     if request.method == "POST":
#         data = request.form
#         passenger = {
#             "id": get_new_passenger_id(),
#             "name": data.get("name"),
#             "personal_id": data.get("personal_id"),
#             "phone_num": data.get("phone_num"),
#             "email": data.get("email"),
#             "identity": data.get("identity")
#         }
#         passengers = load_json(PASSENGER_FILE)
#         passengers.append(passenger)
#         save_json(PASSENGER_FILE, passengers)
#         # 新增成功後重定向或返回 passenger.html
#         passengers = load_json(PASSENGER_FILE) # 重新載入以顯示最新的列表
#         return render_template("passenger.html", passengers=passengers, success=True)
        
#     passengers = load_json(PASSENGER_FILE)
#     return render_template("passenger.html", passengers=passengers)


@app.route("/history.html")
def history_page():
    # 這裡的邏輯需要與實際的 history.json 格式相符
    history = load_json(HISTORY_FILE)
    
    # 假設 history.json 中的每個項目已經包含所需的鍵
    # 為了簡化，這裡僅傳遞 history 列表
    return render_template("history.html", history=history if history else [])


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

# 為了確保 Gunicorn worker 也啟動，請將 start_booking_worker_thread()
# 放在 app = Flask(__name__) 之後的頂層代碼區塊。