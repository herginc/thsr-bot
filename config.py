import os

BASE_URL = "https://irs.thsrc.com.tw"
BOOKING_PAGE_URL = "https://irs.thsrc.com.tw/IMINT/?locale=tw"
SUBMIT_FORM_URL = "https://irs.thsrc.com.tw/IMINT/;jsessionid={}?wicket:interface=:0:BookingS1Form::IFormSubmitListener"
CONFIRM_TRAIN_URL = "https://irs.thsrc.com.tw/IMINT/?wicket:interface=:1:BookingS2Form::IFormSubmitListener"
CONFIRM_TICKET_URL = "https://irs.thsrc.com.tw/IMINT/?wicket:interface=:2:BookingS3Form::IFormSubmitListener"

# Booking Form Captcha Information
# XPath:
#   //*[@id="BookingS1Form_homeCaptcha_passCode"]
# HTML element:
#   <img id="BookingS1Form_homeCaptcha_passCode" class="captcha-img"
#   src="/IMINT/?wicket:interface=:2:BookingS1Form:homeCaptcha:passCode::IResourceListener&amp;wicket:antiCache=1761288618573"
#   height="54px">

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/42.0.2311.135 Safari/537.36 Edge/12.246"
ACCEPT_STR = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
ACCEPT_LANGUAGE = "zh-TW,zh;q=0.8,en-US;q=0.5,en;q=0.3"
ACCEPT_ENCODING = "gzip, deflate, br"

ACCEPT_IMG = "image/webp,*/*"


# 重新整理驗證碼:
# var wcall=wicketAjaxGet('/IMINT/?wicket:interface=:0:BookingS1Form:homeCaptcha:reCodeLink::IBehaviorListener&amp;wicket:behaviorId=0', function() { }, function() { });
# 實際的請求 URL 是： GET /IMINT/?wicket:interface=:0:BookingS1Form:homeCaptcha:reCodeLink::IBehaviorListener&wicket:behaviorId=0

# 這是按鈕的 onclick 屬性中指定的部分相對 Ajax URL
AJAX_RELATIVE_URL = '/IMINT/?wicket:interface=:0:BookingS1Form:homeCaptcha:reCodeLink::IBehaviorListener&wicket:behaviorId=0'

# 組合完整的 Ajax URL
AJAX_FULL_URL = BASE_URL + AJAX_RELATIVE_URL



# THSR Booking URL
THSR_BOOKING_HOST = "irs.thsrc.com.tw"

# define http header
http_headers: dict = {
    "Host": THSR_BOOKING_HOST,
    "User-Agent": USER_AGENT,
    "Accept": ACCEPT_STR,
    "Accept-Language": ACCEPT_LANGUAGE,
    "Accept-Encoding": ACCEPT_ENCODING
}

AJAX_ACCEPT_STR = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"

# define http header
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
PROXY_ENABLE = 1

# PROXY = "http://60.249.94.59:3128"
# PROXY = "http://202.29.215.78:8080"   # 101056 ms
# PROXY = "http://165.154.110.152:1080" # 785 ms (HongKong)   (GOOD)
# PROXY = "http://165.154.152.162:1080" # 1634 ms (HongKong)  (GOOD)
# PROXY = "http://182.52.165.147:8080"  # 3780 ms (Thailand)

# 使用 HTTP proxy (port 80) 做為 HTTP/HTTPS 代理
PROXY_SERVER = "http://182.52.165.147:8080"

# Override proxy settings from environment if provided
_env_proxy_enable = os.getenv("PROXY_ENABLE")
if _env_proxy_enable is not None:
    try:
        PROXY_ENABLE = int(_env_proxy_enable)
    except ValueError:
        PROXY_ENABLE = 1 if _env_proxy_enable.lower() in ("1", "true", "yes", "on") else 0

_env_proxy_server = os.getenv("PROXY_SERVER")
if _env_proxy_server:
    PROXY_SERVER = _env_proxy_server

print(f"PROXY_ENABLE = {PROXY_ENABLE}")
print(f"PROXY_SERVER = {PROXY_SERVER}")

# ----------------------------------------------------------------------------
# Advanced Configuration
# ----------------------------------------------------------------------------

SAVE_BOOKING_PAGE = 0


# ----------------------------------------------------------------------------
# ANSI Escape Codes
# ----------------------------------------------------------------------------

# Define ANSI escape codes for colors and reset
# RED = '\033[91m'
# GREEN = '\033[92m'
# YELLOW = '\033[93m'
# RESET = '\033[0m' # Resets color and styling

RED = '\x1b[91m'
GREEN = '\x1b[92m'
YELLOW = '\x1b[93m'
RESET = '\x1b[0m' # Resets color and styling
