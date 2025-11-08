# =======================================================
# app.py (Flask Web Server) - 已更新表格數據格式
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
from typing import Dict, Any, List
# from zoneinfo import ZoneInfo
from argparse import ArgumentParser

from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, request, abort, render_template, jsonify, render_template_string

import threading
from typing import Optional # <--- 必須加上這一行

import proxy

# ... (省略 LINE Bot 相關設定) ...

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# --- 核心配置與全局狀態 (保持不變) ---
MAX_NETWORK_LATENCY = 5
BASE_CLIENT_TIMEOUT = 600 + MAX_NETWORK_LATENCY
# CST_TIMEZONE = ZoneInfo('Asia/Taipei')

data_lock = threading.Lock()


if sys.version_info >= (3, 10):
    print("Python Version >= 3.10")
    current_waiting_event: threading.Event | None = None
    current_response_data: Dict[str, Any] | None = None
else:
    print("Python Version < 3.10")
    current_waiting_event: Optional[threading.Event] = None
    current_response_data: Optional[Dict[str, Any]] = None

TICKET_DIR = "./"
TICKET_REQUEST_FILE = os.path.join(TICKET_DIR, "ticket_booking_requests.json")
TICKET_HISTORY_FILE = os.path.join(TICKET_DIR, "ticket_history.json")

PASSENGER_DIR = "./json"
PASSENGER_FILE = os.path.join(PASSENGER_DIR, "passenger_data.json")

# --- 數據庫操作函式 (保持不變) ---
def load_json(filename):
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_json(filename, data):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- 新增：根據姓名查找身分證字號的輔助函數 ---
def get_passenger_data_by_name(name: str) -> str:
    """從乘客檔案中根據姓名查找身分證字號，若找不到則回傳空字串。"""
    passengers = load_json(PASSENGER_FILE) # PASSENGER_FILE 儲存乘客資料
    for p in passengers:
        # 由於 personal_id 可能是 string，且 name 必須完全匹配
        if p.get("name") == name:
            return p
    return ""
# --- 輔助函數結束 ---

def get_new_id():
    booking_requests = load_json(TICKET_REQUEST_FILE)
    history = load_json(TICKET_HISTORY_FILE)
    max_id = 0
    if booking_requests:
        max_id = max(max_id, max(r.get("id", 0) for r in booking_requests))
    if history:
        max_id = max(max_id, max(h.get("id", 0) for h in history))
    return max_id + 1

def get_new_passenger_id():
    passengers = load_json(PASSENGER_FILE)
    if not passengers:
        return 1
    return max(p["id"] for p in passengers) + 1

# def push_task_to_client(task_data: Dict[str, Any]):
#     global current_waiting_event, current_response_data
#     with data_lock:
#         notifications_sent = 0
#         if current_waiting_event:
#             current_response_data = {"status": "success", "data": task_data.copy()}
#             current_waiting_event.set()
#             notifications_sent = 1
#     print(f"[{time.strftime('%H:%M:%S')}] ✅ PUSHED: New booking task (ID: {task_data.get('id')}). Waking up {notifications_sent} client.")


# ----------------------------------------------------------------------------
# 數據格式化函式 - 將單筆訂票數據格式化為前端表格所需的精簡格式
# ----------------------------------------------------------------------------
def format_ticket_data(ticket: Dict[str, Any]) -> Dict[str, Any]:

    # 訂票日期 (Order Date): 格式 'hh:mm'
    try:
        # 假設 order_date 格式為 "YYYY-MM-DD HH:MM:SS"
        order_dt = datetime.strptime(ticket.get("order_date"), "%Y-%m-%d %H:%M:%S")
        formatted_order_date = order_dt.strftime("%H:%M")
    except Exception:
        formatted_order_date = "N/A"

    # 乘車日期 (Travel Date): 格式 'MM/DD'
    try:
        # 假設 travel_date 格式為 "YYYY-MM-DD"
        travel_dt = datetime.strptime(ticket.get("travel_date"), "%Y-%m-%d")
        formatted_travel_date = travel_dt.strftime("%m/%d")
    except Exception:
        formatted_travel_date = "N/A"

    # 組合時間地點資訊
    from_info = f"{ticket.get('from_station', 'N/A')} {ticket.get('from_time', 'N/A')}"
    to_info = f"{ticket.get('to_station', 'N/A')} {ticket.get('to_time', 'N/A')}"

    # Dict 的內容需含所有前端所需的資料 (如: booking data, personal data, history, ...)
    formatted_ticket = {
        "id": ticket["id"],
        "status": ticket.get("status"),
        "result": ticket.get("status", "N/A"),
        "code": ticket.get("code", "N/A"),                      # ??
        "name": ticket.get("name", "N/A"),
        "personal_id": ticket.get("personal_id", "N/A"),        # 雖然表格不顯示，但保留原始數據
        "phone_num": ticket.get("phone_num", "N/A"),            # 雖然表格不顯示，但保留原始數據
        "email": ticket.get("email", "N/A"),                    # 雖然表格不顯示，但保留原始數據
        "search_by": ticket.get("search_by", "N/A"),
        "train_id": ticket.get("train_id", "N/A"),
        "formatted_order_date": formatted_order_date,           # 表格暫無使用此資料
        "formatted_travel_date": formatted_travel_date,
        "from_info": from_info,
        "to_info": to_info,
        "search_data": "TBD",
    }
    return formatted_ticket


# ===================================================
# --- 路由定義 ---
# ===================================================

# 1. 訂票首頁 (GET)
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        data = request.form

        # 1. 獲取姓名
        name = data.get("name")
        
        # 2. 根據姓名在乘客檔案中查找身分證字號
        p = get_passenger_data_by_name(name)
        personal_id = p.get("personal_id", "")
        phone_num   = p.get("phone_num", "")
        email       = p.get("email", "")
        
        if not name or not personal_id:
            # 處理沒有足夠資料的情況
            print(f"訂票失敗：姓名 '{name}' 找不到對應的身分證字號。")
            # 這裡簡單地跳過訂票，並重導向
            return redirect(url_for("index"))

        ticket = {
            "id": get_new_id(),
            "status": "訂票待處理",
            "order_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "name": name,                       # 表單提交
            "personal_id": personal_id,         # 後端查找
            "phone_num": phone_num,             # 後端查找
            "email": email,                     # 後端查找
            "search_by": search_by,
            "train_id": data.get("train_id"),
            "travel_date": data.get("travel_date"),
            "from_station": data.get("from_station"),
            "from_time": data.get("from_time", ""), # 從 index.html 移除的欄位給預設值
            "to_station": data.get("to_station"),
            "to_time": data.get("to_time", ""), # 從 index.html 移除的欄位給預設值
        }

        booking_requests = load_json(TICKET_REQUEST_FILE)
        booking_requests.append(ticket)
        save_json(TICKET_REQUEST_FILE, booking_requests)
        # 檢查是否需要新增乘客資料 (雖然應該已經存在，但保留檢查)
        add_passenger_if_new(ticket["name"], ticket["personal_id"], ticket["phone_num"], ticket["email"])
        return redirect(url_for("index"))

        # --- POST 處理邏輯結束 ---
            
    elif request.method == "GET":
        booking_requests = load_json(TICKET_REQUEST_FILE)
        passengers = load_json(PASSENGER_FILE) # **載入乘客資料**
        formatted_booking_requests = [format_ticket_data(r) for r in booking_requests]
        
        # 傳遞 booking_requests 和 passengers
        return render_template("index.html", booking_requests=formatted_booking_requests, passengers=passengers)



def parse_search_data(search_data: str):
    
    if (search_data.isdigit()):
        return "train_id", search_data, "TBD"
        
    else:
        return "from_time", "TBD", search_data


# 2. JSON API 訂票提交路由
@app.route("/api/submit_ticket", methods=["POST"])
def api_submit_ticket():
    try:
        data = request.get_json()

        if not data:
            return jsonify({"status": "error", "message": "Missing JSON data in request body."}), 400
        else:
            print(data)

        required_fields = ["name", "travel_date", "from_station", "to_station", "search_data"]

        for field in required_fields:
            if not data.get(field):
                 return jsonify({"status": "error", "message": f"Missing required field: {field}"}), 400

        name = data.get("name")
        pdata = get_passenger_data_by_name(name)        # 根據 name 查找 passenger data
        personal_id = pdata.get("personal_id", "")
        phone_num   = pdata.get("phone_num", "")
        email       = pdata.get("email", "")

        if not personal_id:
             return jsonify({"status": "error", "message": f"Passenger name '{name}' not found or missing personal_id."}), 400
         
        search_by, train_id, from_time = parse_search_data(data['search_data'])

        print(f"search_by = {search_by}")
        print(f"train_id  = {train_id}")
        print(f"from_time = {from_time}")

        ticket = {
            "id": get_new_id(),
            "status": "待處理",
            "order_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "name": name,
            "personal_id": personal_id,         # 後端查找
            "phone_num": phone_num,             # 後端查找
            "email": email,                     # 後端查找
            "search_by": search_by,
            "train_id": train_id,
            "travel_date": data["travel_date"],
            "from_station": data["from_station"],
            "from_time": from_time,
            "to_station": data["to_station"],
            # "code": None
        }

        booking_requests = load_json(TICKET_REQUEST_FILE)
        booking_requests.append(ticket)
        save_json(TICKET_REQUEST_FILE, booking_requests)

        add_passenger_if_new(ticket["name"], ticket["personal_id"], ticket["phone_num"], ticket["email"])        # 再次檢查/新增
        
        print(f"[{time.strftime('%H:%M:%S')}] API SUBMIT: New task ID {ticket['id']} created.")

        return jsonify({
            "status": "success",
            "message": "Booking task submitted successfully.",
            "task_id": ticket["id"]
        }), 201

    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] API SUBMIT UNKNOWN ERROR: {e}")
        return jsonify({"status": "internal_error", "message": str(e)}), 500


# 3. 歷史記錄頁面 (已修改：應用格式化)
@app.route("/history.html")
def history():
    history_data = load_json(TICKET_HISTORY_FILE)

    # 應用格式化函式，將格式化後的數據傳遞給 history.html
    formatted_history = [format_ticket_data(h) for h in history_data]

    return render_template("history.html", history=formatted_history)

# 4. AJAX 短輪詢路由 (已修改：使用格式化數據和新模板)
@app.route("/api/pending_table", methods=["GET"])
def api_pending_table():
    booking_requests = load_json(TICKET_REQUEST_FILE)

    # 應用格式化函式
    formatted_booking_requests = [format_ticket_data(r) for r in booking_requests]

    # 新的模板字串，配合 index.html 的新表頭
    template_str = """
    {% for r in formatted_booking_requests %}
    <tr>
        <td>{{ r.id }}</td>
        <td>{{ r.status }}</td>
        <td>{{ r.name }}</td>
        <td>{{ r.train_id }}</td>
        <td>{{ r.formatted_travel_date }}</td>
        <td>{{ r.from_info }}</td>
        <td>{{ r.to_info }}</td>
    </tr>
    {% else %}
    <tr>
        <td colspan="8">目前沒有待處理的訂票任務。</td>
    </tr>
    {% endfor %}
    """

    rendered_html = render_template_string(template_str, formatted_booking_requests=formatted_booking_requests)
    return rendered_html, 200

# 5. Long Polling 端點 (保持不變)
@app.route('/poll_for_update', methods=['POST'])
def long_poll_endpoint():

    # return "OK", 200

    # ...existing code...
    global current_waiting_event, current_response_data
    client_timeout = BASE_CLIENT_TIMEOUT
    client_timestamp = ""
    try:
        data = request.get_json()
        client_timeout = data.get('client_timeout_s', BASE_CLIENT_TIMEOUT)
        client_timestamp = data.get('timestamp', "")
    except Exception:
        pass

    booking_requests = load_json(TICKET_REQUEST_FILE)
    if booking_requests:
        print(f"[{time.strftime('%H:%M:%S')}] 🚨 WAITING TASKS FOUND: Returning {len(booking_requests)} pending tasks immediately.")
        return jsonify({
            "status": "initial_sync",
            "message": "Found pending tasks in queue.",
            "data": booking_requests.copy()
        }), 200

    new_client_event = threading.Event()
    response_payload = None
    with data_lock:
        if current_waiting_event:
            current_response_data = {"status": "forced_reconnect", "message": "New poll initiated. Please re-poll immediately."}
            current_waiting_event.set()

        current_waiting_event = new_client_event
        current_response_data = None

    is_triggered = new_client_event.wait(timeout=30) # ?? 30 ??

    with data_lock:
        response_payload = current_response_data
        if new_client_event == current_waiting_event:
            current_waiting_event = None
            current_response_data = None

    if response_payload:
        return jsonify(response_payload), 200

    if not is_triggered:
        print(f"[{time.strftime('%H:%M:%S')}] Timeout reached. Sending 'No Update' response.")
        return jsonify({"status": "timeout", "message": "No new events."}), 200

    return jsonify({"status": "internal_error", "message": "Unknown trigger state."}), 500


@app.route("/admin", methods=["GET", "POST"])
def admin():
    return "Under construction", 200

# 6. 任務結果回傳端點 (保持不變)
@app.route('/update_status', methods=['POST'])
def update_status():
    # ... (程式碼保持不變) ...
    try:
        data = request.get_json()
        task_id = data.get('task_id')
        status = data.get('status')
        details = data.get('details', {})

        if not task_id or not status:
            return jsonify({"status": "error", "message": "Missing task_id or status"}), 400

        task_id = int(task_id)

        with data_lock:
            booking_requests = load_json(TICKET_REQUEST_FILE)
            found = False
            for ticket in booking_requests:
                if ticket.get("id") == task_id:
                    ticket["status"] = status
                    ticket["result_details"] = details
                    ticket["completion_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if details.get("code"):
                        ticket["code"] = details["code"]

                    if status in ["booked", "failed"]:
                        booking_requests.remove(ticket)
                        history_data = load_json(TICKET_HISTORY_FILE)
                        history_data.append(ticket)
                        save_json(TICKET_HISTORY_FILE, history_data)

                    found = True
                    break

            save_json(TICKET_REQUEST_FILE, booking_requests)

        if found:
            return jsonify({"status": "success", "message": f"Task {task_id} status updated to {status}."}), 200
        else:
            return jsonify({"status": "not_found", "message": f"Task {task_id} not found."}), 404

    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ STATUS UPDATE UNKNOWN ERROR: {e}")
        return jsonify({"status": "internal_error", "message": str(e)}), 500


def add_passenger_if_new(name, personal_id, phone_num, email):
    passengers = load_json(PASSENGER_FILE)
    for p in passengers:
        if p["name"] == name and p["personal_id"] == personal_id:
            # [scott]: still update phone number & email
            return  # Already exists
    # Add new passenger with default identity
    new_passenger = {
        "id": get_new_passenger_id(),
        "name": name,
        "personal_id": personal_id,
        "phone_num": phone_num,
        "email": email,
        "identity": "一般"
    }
    passengers.append(new_passenger)
    save_json(PASSENGER_FILE, passengers)

# --- 新增路由：在背景執行 proxy.main() ---
proxy_thread = None

@app.route("/proxy", methods=["GET", "POST"])
def proxy_route():
    """
    啟動 proxy.main() 在背景執行。若已在執行中則回傳狀態。
    """
    global proxy_thread
    with data_lock:
        if proxy_thread and proxy_thread.is_alive():
            return jsonify({"status": "running", "message": "Proxy already running."}), 200

        # 建立並啟動背景執行緒
        proxy_thread = threading.Thread(target=proxy.main, daemon=True)
        proxy_thread.start()

    return jsonify({"status": "started", "message": "Proxy started in background."}), 202

@app.route("/passenger.html", methods=["GET", "POST"])
def passenger_page():
    if request.method == "POST":
        data = request.form
        passenger = {
            "id": get_new_passenger_id(),
            "name": data.get("name"),
            "personal_id": data.get("personal_id"),
            "phone_num": data.get("phone_num"),
            "email": data.get("email"),
            "identity": data.get("identity")
        }
        passengers = load_json(PASSENGER_FILE)
        passengers.append(passenger)
        save_json(PASSENGER_FILE, passengers)
        return render_template("passenger.html", passengers=passengers, success=True)
    passengers = load_json(PASSENGER_FILE)
    return render_template("passenger.html", passengers=passengers)

if __name__ == "__main__":

    arg_parser = ArgumentParser(
        usage='Usage: python ' + __file__ + ' [--port <port>] [--help]'
    )
    arg_parser.add_argument('-p', '--port', default=10000, help='port')
    arg_parser.add_argument('-d', '--debug', default=True, help='debug')
    options = arg_parser.parse_args()

    app.run(debug=options.debug, port=options.port, threaded=True)
