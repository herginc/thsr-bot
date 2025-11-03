import os

# ----------------------------------------------------------------------------
# Define URLs
# ----------------------------------------------------------------------------

# THSR Booking Host URL
THSR_BOOKING_HOST  = "irs.thsrc.com.tw"

BASE_URL                   = "https://irs.thsrc.com.tw"
BOOKING_PAGE_URL           = "https://irs.thsrc.com.tw/IMINT/?locale=tw"           # or "https://irs.thsrc.com.tw/IMINT" ??
BOOKING_MAIN_PAGE_URL      = BOOKING_PAGE_URL

# 無痕模式 Incognito mode
# BOOKING_SUBMIT_FORM_URL    = "https://irs.thsrc.com.tw/IMINT/?wicket:interface=:0:BookingS1Form::IFormSubmitListener"

# BOOKING_SUBMIT_FORM_URL    = "https://irs.thsrc.com.tw/IMINT/;jsessionid={}?wicket:interface=:0:BookingS1Form::IFormSubmitListener"
# BOOKING_CONFIRM_TRAIN_URL  = "https://irs.thsrc.com.tw/IMINT/?wicket:interface=:1:BookingS2Form::IFormSubmitListener"
# BOOKING_CONFIRM_TICKET_URL = "https://irs.thsrc.com.tw/IMINT/?wicket:interface=:2:BookingS3Form::IFormSubmitListener"




# Booking Form Captcha Information
# XPath:
#   //*[@id="BookingS1Form_homeCaptcha_passCode"]
# HTML element:
#   <img id="BookingS1Form_homeCaptcha_passCode" class="captcha-img"
#   src="/IMINT/?wicket:interface=:2:BookingS1Form:homeCaptcha:passCode::IResourceListener&amp;wicket:antiCache=1761288618573"
#   height="54px">


BOOKING_FORM_CAPTCHA_PASSCODE_IMG_ID = "BookingS1Form_homeCaptcha_passCode"
BOOKING_FORM_CAPTCHA_RELOAD_BTN_ID   = "BookingS1Form_homeCaptcha_reCodeLink"
BOOKING_FORM_SUBMIT_BTN_ID           = "BookingS1Form"

# Notice: The number after 'Interface' will change, it is not fixed at '0'
# 
# <button id="BookingS1Form_homeCaptcha_reCodeLink" type="button" class="btn-reload" onclick="var wcall=wicketAjaxGet('/IMINT/?wicket:interface=:2:BookingS1Form:homeCaptcha:reCodeLink::IBehaviorListener&amp;wicket:behaviorId=0', function() { }, function() { });return !wcall;">
# <button id="BookingS1Form_homeCaptcha_reCodeLink" type="button" class="btn-reload" onclick="var wcall=wicketAjaxGet('/IMINT/?wicket:interface=:5:BookingS1Form:homeCaptcha:reCodeLink::IBehaviorListener&amp;wicket:behaviorId=0', function() { }, function() { });return !wcall;">

# 重新整理驗證碼:
# var wcall=wicketAjaxGet('/IMINT/?wicket:interface=:0:BookingS1Form:homeCaptcha:reCodeLink::IBehaviorListener&amp;wicket:behaviorId=0', function() { }, function() { });
# 實際的請求 URL 是： GET /IMINT/?wicket:interface=:0:BookingS1Form:homeCaptcha:reCodeLink::IBehaviorListener&wicket:behaviorId=0

# 在 Wicket 機制中，模擬點擊 Ajax 按鈕後，
# 驗證碼圖片的 src 值會被更新，但 HTML 內容本身**不會**改變。
#
# 因此，我們只需要重新解析原始 HTML 來取得新的 src。
# (如果網站是傳統的 POST 請求刷新整個頁面，則需要重新 get 頁面)

# 這裡我們使用傳入的 booking_page_html (第一次加載的頁面內容)
# 進行解析以獲得最新的 src。

# 注意: 實際的 Wicket 流程中，圖片的 src 中的 `wicket:antiCache` 參數會被更新。
# 雖然 HTML 內容未變，但瀏覽器在執行 Wicket Ajax 響應的 JavaScript 後，
# 會被告知要重新載入 `id='BookingS1Form_homeCaptcha_passCode'` 元素的圖片。

# 雖然實際圖片 src 參數已被更新，但**第一次載入的 HTML 內容**中的 src 依然是舊的。
# 因此，我們需要**重新訪問頁面**或**直接構造圖片 URL**。

# 簡單起見，我們假設點擊後，頁面上的 **src 參數已更新** (或我們能構造出新的 src)。
# 在 Wicket 應用中，最保險的做法是**重新發送 GET 請求給整個頁面**，然後再解析。
# 但為了演示，我們直接重用 `get_captcha_src` 函式來獲取 **當前頁面上的 src**。

# --- 為了簡化，我們假設 Ajax 請求成功後，舊的 src 依然可用，但圖片內容已更新 ---
# 這是 Wicket 的特殊情況，我們重用第一次獲得的 src 結構，只是內容會變。
# 實際應用中，如果 src 變了，需要重新 parse HTML (即重新 load booking page)。

# 重新解析 HTML 取得 **舊的 src** (因為它包含相對路徑結構)
# 讓 `save_captcha_image` 函式去下載**最新的圖片內容**


# 這是按鈕的 onclick 屬性中指定的部分相對 Ajax URL
# 有無 ';jsessionid=hiGlHNU_Ks_3xUq88hqWnixKRYGEdMIc-RNXfeJo.omcirsap5' 這段似乎不受影響 (???)
# AJAX_RELATIVE_URL = '/IMINT/?wicket:interface=:0:BookingS1Form:homeCaptcha:reCodeLink::IBehaviorListener&wicket:behaviorId=0'
# AJAX_RELATIVE_URL = '/IMINT/;jsessionid=hiGlHNU_Ks_3xUq88hqWnixKRYGEdMIc-RNXfeJo.omcirsap5?wicket:interface=:0:BookingS1Form:homeCaptcha:reCodeLink::IBehaviorListener&wicket:behaviorId=0'

# 組合完整的 Ajax URL
# AJAX_FULL_URL = BASE_URL + AJAX_RELATIVE_URL


# ----------------------------------------------------------------------------
# Define HTTP Header
# ----------------------------------------------------------------------------

session_max_retries = 3

http_timeout = 15

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/42.0.2311.135 Safari/537.36 Edge/12.246"
ACCEPT_STR = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
ACCEPT_LANGUAGE = "zh-TW,zh;q=0.8,en-US;q=0.5,en;q=0.3"
ACCEPT_ENCODING = "gzip, deflate, br"

ACCEPT_IMG = "image/webp,*/*"

http_headers: dict = {
    "Host": THSR_BOOKING_HOST,
    "User-Agent": USER_AGENT,
    "Accept": ACCEPT_STR,
    "Accept-Language": ACCEPT_LANGUAGE,
    "Accept-Encoding": ACCEPT_ENCODING
}

AJAX_ACCEPT_STR = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"

ajax_http_headers: dict = {
    "Host": THSR_BOOKING_HOST,
    "User-Agent": USER_AGENT,
    "Accept": AJAX_ACCEPT_STR,
    "Accept-Language": ACCEPT_LANGUAGE,
    "Accept-Encoding": ACCEPT_ENCODING,
    'Referer': BOOKING_PAGE_URL,
}

#    'X-Requested-With': 'XMLHttpRequest',


# ----------------------------------------------------------------------------
# Proxy Server Configuration
# ----------------------------------------------------------------------------

# Enable or disable proxy server
PROXY_ENABLE = 0

# PROXY = "http://60.249.94.59:3128"
# PROXY = "http://202.29.215.78:8080"   # 101056 ms
# PROXY = "http://165.154.110.152:1080" # 785 ms (HongKong)   (GOOD)
# PROXY = "http://165.154.152.162:1080" # 1634 ms (HongKong)  (GOOD)
# PROXY = "http://182.52.165.147:8080"  # 3780 ms (Thailand)

# 使用 HTTP proxy (port 80) 做為 HTTP/HTTPS 代理
PROXY_SERVER = "http://182.52.165.147:8080"

# Override proxy settings from environment if provided
# _env_proxy_enable = os.getenv("PROXY_ENABLE")
_env_proxy_enable = os.environ.get("PROXY_ENABLE")
if _env_proxy_enable is not None:
    try:
        PROXY_ENABLE = int(_env_proxy_enable)
    except ValueError:
        PROXY_ENABLE = 1 if _env_proxy_enable.lower() in ("1", "true", "yes", "on") else 0

# _env_proxy_server = os.getenv("PROXY_SERVER")
_env_proxy_server = os.environ.get("PROXY_SERVER")
if _env_proxy_server:
    PROXY_SERVER = _env_proxy_server

print(f"PROXY_ENABLE = {PROXY_ENABLE}")
print(f"PROXY_SERVER = {PROXY_SERVER}")


# ----------------------------------------------------------------------------
# Advanced Configuration
# ----------------------------------------------------------------------------

SAVE_BOOKING_PAGE = 1


# ----------------------------------------------------------------------------
# ANSI Escape Codes
# ----------------------------------------------------------------------------

# Define ANSI escape codes for colors and reset

BOLD    = '\033[1m'

RED     = '\x1b[91m'
GREEN   = '\x1b[92m'
YELLOW  = '\x1b[93m'
BLUE    = '\x1b[94m'
MAGENTA = '\x1b[95m'
CYAN    = '\x1b[96m'
WHITE   = '\x1b[97m'
RESET   = '\x1b[0m'     # Resets color and styling

# if sys.platform == "win32":
if os.name == 'nt':
    import colorama
    colorama.init()

print(RED       + "Hello, color text ..." + RESET)
print(GREEN     + "Hello, color text ..." + RESET)
print(YELLOW    + "Hello, color text ..." + RESET)
print(BLUE      + "Hello, color text ..." + RESET)
print(MAGENTA   + "Hello, color text ..." + RESET)
print(CYAN      + "Hello, color text ..." + RESET)
print(WHITE     + "Hello, color text ..." + RESET)
