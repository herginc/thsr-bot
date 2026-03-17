import logging
import threading

from typing import Mapping, Any, Optional, Union, List, Dict, Tuple

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
# --- Global Configuration ---
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(__file__)
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

booking_OK = 0
booking_NG = 0


# Initialize ddddocr
ocr = ddddocr.DdddOcr(show_ad=False)
# ocr = ddddocr.DdddOcr()

# ----------------------------------------------------------------------------
# Common Functions
# ----------------------------------------------------------------------------

def sleep_range(a, b):
    sec = random.uniform(a, b)
    sleep(sec)


# ----------------------------------------------------------------------------
# Session Initialization
# ----------------------------------------------------------------------------

def session_init():

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
        # 避免 requests 使用環境變數中的代理設定（視需求可保留或移除）
        session.trust_env = False
        logger.info(f"{YELLOW}*** proxy server {PROXY_SERVER} enbled ***{RESET}")

    return session


# ----------------------------------------------------------------------------
# Reload captcha image (模擬 click 'regenerate' button)
# ----------------------------------------------------------------------------

def reload_captcha_image(session: Session, url_path: str) -> bool:
    """
    通過發送 Wicket Ajax 請求，模擬點擊「重新產生驗證碼」按鈕。

    Args:
        session: 包含當前會話狀態 (Cookies) 的 requests.Session 物件。

    Returns:
        如果請求成功則返回 True，否則返回 False。
    """

    captcha_recode_link = BASE_URL + url_path

    logger.debug(f"模擬 click 'regenerate' button (Ajax GET): {captcha_recode_link}")

    try:
        # 發送 GET 請求到 Ajax URL, Wicket Ajax 請求通常是一個 GET 請求
        response = session.get(
            captcha_recode_link,
            headers=http_headers,  # ajax_http_headers,
            timeout=15
        )

        # 檢查 HTTP 狀態碼
        response.raise_for_status()

        # 成功的 Wicket Ajax 響應通常是 XML 格式，並帶有 200 狀態碼
        logger.debug("Session request successful: 200 OK")

        # cookies = response.json().get('cookies')
        # logger.info(CYAN + f"cookies = {cookies}" + RESET)

        # scott --> how to parse this response (XML format ??)

        # <?xml version="1.0" encoding="UTF-8"?><ajax-response><component id="BookingS1Form_homeCaptcha_passCode" ><![CDATA[<img id="BookingS1Form_homeCaptcha_passCode" class="captcha-img" src="/IMINT/?wicket:interface=:0:BookingS1Form:homeCaptcha:passCode::IResourceListener&wicket:antiCache=1762263528372" height="54px">]]></component><component id="BookingS1Form_homeCaptcha_soundLink" ><![CDATA[<button id="BookingS1Form_homeCaptcha_soundLink" type="button" class="btn-speak" onclick="window.location.href='/IMINT/?wicket:interface=:0:BookingS1Form:homeCaptcha:soundLink::ILinkListener';">
        # <span title="語音播放" class="material-icons" wicket:message="title=bookingS3PlayAudio">volume_up</span>
        # </button>]]></component></ajax-response>

        # Wicket 的響應內容 (response.text) 包含了指示瀏覽器更新 DOM 的 XML
        # 如果需要，您可以解析這個 XML 檢查驗證碼圖片的 src 是否有更新
        # print("Wicket Ajax Response Preview (XML):", response.text[:200] + "...")

        return True

    except requests.exceptions.RequestException as e:
        print(f"請求失敗: {e}")
        return False


def get_captcha_value(image_bytes):
    # captcha_value = ocr.classification(image_bytes) # run this API about 0.5s
    captcha_value = '1234'
    print(YELLOW + f"Get captcha value '{captcha_value}'" + RESET)
    return captcha_value

def save_and_parse_captcha_image(session: Session, img_src: str, file_path: str = None) -> bool:
    if file_path is None:
        file_path = os.path.join(OUTPUT_DIR, "captcha_downloaded.png")
    """
    結合 BASE_URL 和 img_src (相對路徑)，從網址下載圖片並儲存到本地檔案。

    Args:
        img_src: 圖片的相對 URL (例如: '/IMINT/...')。
        file_path: 圖片要儲存的本地路徑和檔案名稱。預設值為 'captcha_downloaded.png'。

    Returns:
        如果下載成功則返回 True，否則返回 False。
    """

    if not img_src:
        print("錯誤: 圖片相對路徑 (img_src) 不可為空。")
        return False

    # 使用 global 變數 BASE_URL 與相對路徑組合，形成完整的 URL
    img_full_url = BASE_URL + img_src

    # logger.info(CYAN + f"Try to get image from: {img_full_url}" + RESET)

    captcha_value = None

    try:
        # 發送 GET 請求。設置 timeout 以防連線無限期等待
        # response = session.get(img_full_url, stream=True, timeout=10)
        response = session.get(img_full_url, headers=http_headers)

        # 檢查 HTTP 狀態碼 (例如 200 OK, 404 Not Found 等)
        response.raise_for_status() # 如果狀態碼不是 200，會拋出 HTTPError

        # print("-------------- OK --------------")
        logger.info(f"Downloaded captcha image successfully")

        # cookies = response.json().get('cookies')
        # logger.info(CYAN + f"cookies = {cookies}" + RESET)


        captcha_image_bytes = response.content

        # XXXX captcha_value = get_captcha_value(captcha_image_bytes)

        if (0):  # only OK for GUI OS
            image = Image.open(io.BytesIO(response.content))
            image.show()

        if (1):#captcha_value):
            # 以二進制寫入模式 ('wb') 開啟檔案
            with open(file_path, 'wb') as f:
                # 寫入圖片的二進制內容
                f.write(response.content)
            logger.info(f"Save image successfully ({file_path})")
        else:
            print(response.content)

        captcha_value = ocr.classification(captcha_image_bytes)
        # print(response.content)
        # captcha_value = '1234'
        # print(YELLOW + f"Get captcha value '{captcha_value}'" + RESET)


    except requests.exceptions.HTTPError as e:
        print(f"下載圖片失敗，HTTP 錯誤碼: {e.response.status_code} ({e})")
        # return None
    except requests.exceptions.RequestException as e:
        print(f"下載圖片失敗，連線或請求錯誤: {e}")
        # return None
    except IOError as e:
        print(f"儲存檔案失敗，IO 錯誤: {e}")
        # return None

    return captcha_value


def parse_booking_form_element_id(session: Session, page: str):

    booking_form = {}

    booking_form['captcha_image_url']  = None
    booking_form['captcha_reload_url'] = None
    booking_form['booking_submit_url'] = None


    # 使用 Beautiful Soup 解析 HTML 內容
    # 'html.parser' 是一個常用的解析器
    soup = BeautifulSoup(page, 'html.parser')

    # configure target id
    target_id = BOOKING_FORM_CAPTCHA_PASSCODE_IMG_ID

    # find element id
    element = soup.find(id=target_id)    # or soup.find('img', id=target_id)

    # if the element is found, extract the attribute value.
    if element:
        # 如果屬性存在，則返回其值；如果不存在，則返回 None，避免 KeyError。
        booking_form['captcha_image_url'] = element.get('src')    # 使用 .get() 方法來安全地取得屬性值。
        # logger.debug(f"img_src={img_url}")
        # return img_url
    else:
        # 如果找不到元素，則返回 None
        logger.error(f"Unable to find element id {target_id}")
        return None


    """""

    # 正則表達式模式
    # 模式解釋:
    # 1. 'jsessionid=' : 匹配起始標記
    # 2. '(.+?)'   : 這是捕獲組 (Capture Group)，匹配一個或多個 (非貪婪模式)
    #                 任何字元 (除了換行符)。
    #                 非貪婪模式 (.+?) 確保它只匹配到下一個條件。
    # 3. '\?'      : 匹配問號 '?' (必須使用反斜線跳脫，因為 '?' 在 RegEx 中有特殊含義)
    regex_pattern = r"jsessionid=(.+?)\?"

    # 執行匹配
    match = re.search(regex_pattern, booking_form['captcha_image_url'])

    if match:
        # match.group(1) 包含捕獲組 (.+?) 匹配到的內容
        extracted_substring = match.group(1)
        
        print(MAGENTA + f"✅ 成功提取的子字串：{extracted_substring}" + RESET)
    else:
        print("❌ 找不到匹配的子字串。")
    
    """""

    # configure target id
    target_id = BOOKING_FORM_CAPTCHA_RELOAD_BTN_ID

    # find element id
    element = soup.find(id=target_id)

    # if the element is found, extract the attribute value.
    if element:
        # 如果屬性存在，則返回其值；如果不存在，則返回 None，避免 KeyError。
        onclick_value = element.get('onclick')

        # 使用正則表達式 (RegEx) 提取 wicketAjaxGet 函式中的第一個引號內容
        # 模式: 尋找 'wicketAjaxGet(' 後面第一個單引號 (') 裡面的內容
        match = re.search(r"wicketAjaxGet\('([^']+)'", onclick_value)
        
        if match:
            # match.group(1) 包含括號內匹配到的內容
            extracted_url = match.group(1)
            # 由於原始 HTML 可能將 '&' 編碼為 '&amp;'，為了實際使用，通常需要解碼
            # BeautifulSoup 默認會處理部分實體，但手動確保一下更好
            booking_form['captcha_reload_url'] = extracted_url.replace('&amp;', '&')
    else:
        # 如果找不到元素，則返回 None
        logger.error(f"Unable to find element id {target_id}")
        return None

    # configure target id
    target_id = BOOKING_FORM_SUBMIT_BTN_ID

    # find element id
    element = soup.find(id=target_id)    # or soup.find('img', id=target_id)

    # if the element is found, extract the attribute value.
    if element:
        # 如果屬性存在，則返回其值；如果不存在，則返回 None，避免 KeyError。
        booking_form['booking_submit_url'] = element.get('action')    # 使用 .get() 方法來安全地取得屬性值。
        logger.debug(CYAN + f"submit_btn_url={booking_form['booking_submit_url']}" + RESET)
    else:
        # 如果找不到元素，則返回 None
        logger.error(f"Unable to find element id {target_id}")
        return None

    print(GREEN)

    print(f"captcha_image_url  = {booking_form['captcha_image_url']}")
    print(f"captcha_reload_url = {booking_form['captcha_reload_url']}")
    print(f"booking_submit_url = {booking_form['booking_submit_url']}")

    print(RESET)

    # booking_form['captcha_image_url']  = inject_jsessionid_to_url(session, booking_form['captcha_image_url'])
    # booking_form['captcha_reload_url'] = inject_jsessionid_to_url(session, booking_form['captcha_reload_url'])
    # booking_form['booking_submit_url'] = inject_jsessionid_to_url(session, booking_form['booking_submit_url'])

    # print(CYAN)

    # print(f"captcha_image_url  = {booking_form['captcha_image_url']}")
    # print(f"captcha_reload_url = {booking_form['captcha_reload_url']}")
    # print(f"booking_submit_url = {booking_form['booking_submit_url']}")

    # print(RESET)


    return booking_form

def get_captcha_src(page: str) -> Optional[str]:
    """
    從 HTML 內容中，根據特定的 ID 找到 img 元素的 src 屬性值。

    Args:
        page: 包含目標 img 元素的 HTML 字串。

    Returns:
        如果找到 img 元素，則返回其 src 屬性值 (str)；
        如果找不到，則返回 NONE。
    """

    # 使用 Beautiful Soup 解析 HTML 內容
    # 'html.parser' 是一個常用的解析器
    soup = BeautifulSoup(page, 'html.parser')

    # Find element id
    target_id = BOOKING_FORM_CAPTCHA_PASSCODE_IMG_ID

    # 尋找特定id元素
    img_tag = soup.find(id=target_id)    # or soup.find('img', id=target_id)

    # 檢查是否找到元素，並取得屬性的值
    if img_tag:
        # 如果屬性存在，則返回其值；如果不存在，則返回 None，避免 KeyError。
        img_url = img_tag.get('src')    # 使用 .get() 方法來安全地取得屬性值。
        logger.debug(f"img_src={img_url}")
        # return img_url
    else:
        # 如果找不到元素，則返回 None
        logger.error(f"Unable to find element id {target_id}")
        return None

    target_id = BOOKING_FORM_CAPTCHA_RELOAD_BTN_ID

    # 尋找特定id元素
    btn_tag = soup.find(id=target_id)    # or soup.find('img', id=target_id)

    # 檢查是否找到元素，並取得屬性的值
    if btn_tag:
        # 如果屬性存在，則返回其值；如果不存在，則返回 None，避免 KeyError。
        onclick_value = btn_tag.get('onclick')

        # 使用正則表達式 (RegEx) 提取 wicketAjaxGet 函式中的第一個引號內容
        # 模式: 尋找 'wicketAjaxGet(' 後面第一個單引號 (') 裡面的內容
        match = re.search(r"wicketAjaxGet\('([^']+)'", onclick_value)
        
        if match:
            # match.group(1) 包含括號內匹配到的內容
            extracted_url = match.group(1)
            # 由於原始 HTML 可能將 '&' 編碼為 '&amp;'，為了實際使用，通常需要解碼
            # BeautifulSoup 默認會處理部分實體，但手動確保一下更好
            btn_url = extracted_url.replace('&amp;', '&')
            logger.debug(RED + f"btn_url = {btn_url}" + RESET)

        return img_url, btn_url
    else:
        # 如果找不到元素，則返回 None
        logger.error(f"Unable to find element id {target_id}")
        return img_url, None

def inject_jsessionid_to_url_XXX(session: Session, url_path: str) -> Optional[str]:
    """
    檢查 URL 路徑是否包含 ';jsessionid='。
    如果沒有，則嘗試從 Session Cookies 中獲取 JSESSIONID，
    並將其插入到 '/IMINT/' 與 '?' 之間。
    """
    
    # 1. 檢查字串是否已經包含 ;jsessionid=
    if ';jsessionid=' in url_path:
        return url_path

    # 2. 獲取 JSESSIONID
    try:
        jsessionid = session.cookies['JSESSIONID']
        # 確保 session_str 以分號開頭，以便在路徑中作為參數
        session_str = f";jsessionid={jsessionid}"
    except KeyError:
        return None

    # 3. 定位插入點：查找 '/IMINT/'
    # 這裡我們使用 RegEx 查找 "/IMINT/" 模式
    imint_match = re.search(r'/IMINT/', url_path)
    
    # 4. 定位 URL 中第一個 '?'
    # 注意：如果 URL 中沒有 '?'，我們仍然要能夠處理
    query_start_index = url_path.find('?')

    if imint_match:
        insert_index = imint_match.end() # /IMINT/ 結束的位置
        
        # 情況 A: URL 包含 '?' (常見情況，插入在 ? 前面)
        if query_start_index != -1 and query_start_index > insert_index:
            # 插入點在 /IMINT/ 和 ? 之間
            new_url = (
                url_path[:insert_index] +  # /IMINT/
                session_str +              # ;jsessionid=...
                url_path[insert_index:]    # ?wicket:...
            )
            return new_url
        
        # 情況 B: URL 不包含 '?' (極少見，直接在 /IMINT/ 後面插入)
        elif query_start_index == -1:
            # 直接在 /IMINT/ 後面插入 session ID
            new_url = url_path[:insert_index] + session_str + url_path[insert_index:]
            return new_url
        
        # 情況 C: ? 在 /IMINT/ 之前或格式錯誤
        else:
            return None
    else:
        # 如果 URL 中根本沒有 /IMINT/，則不進行操作
        return None


# ----------------------------------------------------------------------------
# 
# ----------------------------------------------------------------------------

def inject_jsessionid_to_url(session: Session, url_path: str) -> Optional[str]:
    """
    檢查 URL 路徑是否包含 ';jsessionid='。
    如果沒有，則嘗試從 Session Cookies 中獲取 JSESSIONID，
    並將其插入到 '/IMINT/' 與 '?' 之間。

    Args:
        session: 包含 JSESSIONID cookie 的 requests.Session 物件。
        url_path: 需要檢查和修改的 URL 路徑字串 (例如: '/IMINT/?wicket:interface=...').

    Returns:
        返回修正後的 URL 字串；如果找不到 JSESSIONID 或匹配模式，則返回 None。
    """
    
    # 1. 檢查字串是否已經包含 ;jsessionid=
    if ';jsessionid=' in url_path:
        # print("URL 已包含 JSESSIONID，無需修改。")
        return url_path

    # 2. 獲取 JSESSIONID
    try:
        # 從 Session Cookies 中安全地獲取 JSESSIONID
        jsessionid = session.cookies['JSESSIONID']
        session_str = f";jsessionid={jsessionid}"
    except KeyError:
        # print("Session Cookies 中找不到 'JSESSIONID'。")
        return None

    # 3. 定位插入點：使用 RegEx 查找 /IMINT/ 和 ?wicket: 之間的模式
    # 模式: 匹配 '/IMINT/' 後面跟著 (非貪婪模式) 任何字元直到 '?'
    # 但我們只想確認這兩個標記是否存在。
    
    # 查找 '/IMINT/'
    start_match = re.search(r'/IMINT/', url_path)
    
    # 查找第一個 '?' 的位置
    end_match = re.search(r'\?', url_path)

    # 4. 執行插入
    # if start_match and end_match and start_match.end() < end_match.start():
    if start_match and end_match and start_match.end() <= end_match.start():
        # 獲取 '/IMINT/' 結束的位置 (即插入點)
        insert_index = start_match.end()
        
        # 創建新的 URL： [起始部分] + [;jsessionid=...] + [剩餘部分]
        new_url = (
            url_path[:insert_index] + 
            session_str + 
            url_path[insert_index:]
        )
        print(f"成功插入 JSESSIONID: {new_url}")
        return new_url
    else:
        print(f"URL 格式不符合預期的 '/IMINT/...?...' 模式。 {url_path}")
        return None


def check_and_print_errors(html_content: Union[str, bytes]) -> bool:
    """
    檢查 HTML 內容中是否包含 'feedbackPanelERROR' class 的元素。
    如果找到，則印出錯誤內容並返回 True。

    Args:
        html_content: request.post 回傳的 HTML 內容 (str 或 bytes)。

    Returns:
        bool: 如果找到錯誤元素則返回 True，否則返回 False。
    """
    global booking_OK, booking_NG

    # 確保傳入的是字串，BeautifulSoup 建議使用字串解析
    if isinstance(html_content, bytes):
        # 假設內容是 UTF-8 編碼，如果不是，請替換為正確的編碼
        html_content = html_content.decode('utf-8', errors='ignore')

    # 使用 'html.parser' 解析 HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 使用 find_all(class_='...') 查找所有指定 class 的元素
    # 注意：在 Beautiful Soup 中，因為 'class' 是 Python 的保留字，
    # 所以要用 class_ 來指代 HTML 的 class 屬性。
    error_elements = soup.find_all(class_='feedbackPanelERROR')
    
    if error_elements:
        booking_NG = booking_NG + 1
        print(f"\n{RED}{BOLD}======= 提交錯誤訊息：======= {RESET}")
        
        # 為了避免重複印出 (因為 <ul> 和 <span> 都帶有這個 class)，
        # 我們通常只提取最小範圍的元素（即 <span> 或 <li>）的內容。
        
        # 在您提供的結構中，我們查找所有帶有此 class 的 <span> 標籤
        # 以獲得最精確的錯誤文本。
        error_spans = soup.find_all('span', class_='feedbackPanelERROR')
        
        # 使用 set 來儲存並確保錯誤訊息不重複
        unique_errors = set()
        
        for span in error_spans:
            # .get_text(strip=True) 獲取標籤內的文本並移除前後空白
            error_text = span.get_text(strip=True)
            if error_text:
                unique_errors.add(error_text)
                
        for error in sorted(list(unique_errors)):
            print(f"{RED}{error}{RESET}")
            
        print(f"{RED}{BOLD}==================================={RESET}\n")
        return True, unique_errors
    else:
        booking_OK = booking_OK + 1
        print(YELLOW)
        print('-' * 80)
        print("✅ HTML 內容中未發現 'feedbackPanelERROR'，可能已成功進入下一步。")
        print('-' * 80)
        print(RESET)
        return False, None

# ----------------------------------------------------------------------------
# 站名 → selectStartStation / selectDestinationStation value 對照表
# 來源: booking_1st_page.html <select name="selectStartStation"> options
# ----------------------------------------------------------------------------
STATION_NAME_TO_ID: Dict[str, str] = {
    '南港': '1',
    '台北': '2',
    '板橋': '3',
    '桃園': '4',
    '新竹': '5',
    '苗栗': '6',
    '台中': '7',
    '彰化': '8',
    '雲林': '9',
    '嘉義': '10',
    '台南': '11',
    '左營': '12',
}

# ----------------------------------------------------------------------------
# 出發時間 (HH:MM) → toTimeTable / backTimeTable option value 對照表
# 來源: booking_1st_page.html <select name="toTimeTable"> options
# 格式規則:
#   午夜/凌晨 00:00 → 1201A,  00:30 → 1230A
#   上午 05:00~11:30 → HHMMA  (e.g. 500A, 1130A)
#   正午 12:00 → 1200N
#   下午 12:30~23:30 → H(H)MMP  (e.g. 1230P, 100P, 1130P)
# ----------------------------------------------------------------------------
TIME_TO_TIMETABLE: Dict[str, str] = {
    '00:00': '1201A', '00:30': '1230A',
    '05:00': '500A',  '05:30': '530A',
    '06:00': '600A',  '06:30': '630A',
    '07:00': '700A',  '07:30': '730A',
    '08:00': '800A',  '08:30': '830A',
    '09:00': '900A',  '09:30': '930A',
    '10:00': '1000A', '10:30': '1030A',
    '11:00': '1100A', '11:30': '1130A',
    '12:00': '1200N',
    '12:30': '1230P',
    '13:00': '100P',  '13:30': '130P',
    '14:00': '200P',  '14:30': '230P',
    '15:00': '300P',  '15:30': '330P',
    '16:00': '400P',  '16:30': '430P',
    '17:00': '500P',  '17:30': '530P',
    '18:00': '600P',  '18:30': '630P',
    '19:00': '700P',  '19:30': '730P',
    '20:00': '800P',  '20:30': '830P',
    '21:00': '900P',  '21:30': '930P',
    '22:00': '1000P', '22:30': '1030P',
    '23:00': '1100P', '23:30': '1130P',
}

# ----------------------------------------------------------------------------
# 票種 identity → (suffix, row_index)
# 對應 task_data['identity'] 欄位與 HTML ticketPanel rows
# ----------------------------------------------------------------------------
# ticketPanel:rows:0:ticketAmount → 全票    suffix F
# ticketPanel:rows:1:ticketAmount → 孩童票  suffix H
# ticketPanel:rows:2:ticketAmount → 愛心票  suffix W
# ticketPanel:rows:3:ticketAmount → 敬老票  suffix E
# ticketPanel:rows:4:ticketAmount → 大學生票 suffix P
IDENTITY_TO_TICKET_ROW: Dict[str, tuple] = {
    'adult':    ('F', 0),
    'child':    ('H', 1),
    'disabled': ('W', 2),
    'elder':    ('E', 3),
    'college':  ('P', 4),
}

def _resolve_station_id(name: str) -> str:
    """將中文站名轉換為表單 value，找不到時 raise ValueError。"""
    station_id = STATION_NAME_TO_ID.get(name)
    if station_id is None:
        raise ValueError(f"未知的站名: '{name}'。支援站名: {list(STATION_NAME_TO_ID.keys())}")
    return station_id

def _resolve_timetable_value(hhmm: str) -> str:
    """
    將 'HH:MM' 字串轉換為 toTimeTable option value。
    若找不到精確對應，則找最近的半小時時段 (無條件進位至下一個整點或半點)。
    """
    value = TIME_TO_TIMETABLE.get(hhmm)
    if value:
        return value

    # 找不到精確時間 → 找最接近且 >= 輸入時間的選項
    try:
        h, m = map(int, hhmm.split(':'))
        input_minutes = h * 60 + m
    except (ValueError, AttributeError):
        raise ValueError(f"時間格式錯誤: '{hhmm}'，請使用 'HH:MM' 格式 (e.g. '09:00')")

    # 建立 {分鐘數: option_value} 的對照，找最小的 >= input_minutes
    minute_map = {}
    for t, v in TIME_TO_TIMETABLE.items():
        th, tm = map(int, t.split(':'))
        minute_map[th * 60 + tm] = v

    candidates = [(mins, v) for mins, v in minute_map.items() if mins >= input_minutes]
    if candidates:
        best = min(candidates, key=lambda x: x[0])
        logger.warning(f"時間 '{hhmm}' 無精確對應，使用最近的後續時段: '{best[1]}'")
        return best[1]

    # 已超過最後一班 (23:30) → 使用最後一個時段
    last = max(minute_map.items(), key=lambda x: x[0])
    logger.warning(f"時間 '{hhmm}' 超出可選範圍，使用最後時段: '{last[1]}'")
    return last[1]

def _build_ticket_amounts(identity: str, count: int = 1) -> Dict[str, str]:
    """
    根據 identity 和張數，回傳 5 個票種的 form 欄位 dict。
    指定票種設為 count，其餘為 0。
    """
    defaults = {'F': 0, 'H': 0, 'W': 0, 'E': 0, 'P': 0}

    row_info = IDENTITY_TO_TICKET_ROW.get(identity)
    if row_info is None:
        logger.warning(f"未知的 identity '{identity}'，預設使用全票 (adult)。")
        row_info = IDENTITY_TO_TICKET_ROW['adult']

    suffix, _ = row_info
    defaults[suffix] = count

    amounts = {
        'F': f"{defaults['F']}F",
        'H': f"{defaults['H']}H",
        'W': f"{defaults['W']}W",
        'E': f"{defaults['E']}E",
        'P': f"{defaults['P']}P",
    }
    return amounts


def get_booking_data(passcode: str, task_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    根據 task_data 動態產生高鐵訂票表單所需的 form_data。

    task_data 預期欄位:
        start_station   (str) : 出發站中文名，例如 '台北'
        end_station     (str) : 到達站中文名，例如 '左營'
        travel_date     (str) : 出發日期，格式 'YYYY/MM/DD'
        train_time      (str) : 出發時間，格式 'HH:MM'
        identity        (str) : 票種，可選 adult/child/disabled/elder/college (預設 adult)
        ticket_count    (int) : 張數 (預設 1)
        class_type      (int) : 車廂種類，0=標準對號座, 1=商務對號座, 2=自由座 (預設 0)
        seat_prefer     (int) : 座位喜好，0=無, 1=靠窗優先, 2=走道優先 (預設 0)
        train_no        (str) : 指定車次號碼 (若有值則 search_by 切換為 radio33 車次模式)

    回傳:
        Dict[str, Any]: 可直接用於 requests.post(data=...) 的表單資料。
    """

    print(YELLOW)
    print('-' * 70)
    print(task_data)
    print('-' * 70)
    print(RESET)

    # --- 站名 → station ID ---
    start_station_id = _resolve_station_id(task_data.get('start_station', ''))
    end_station_id   = _resolve_station_id(task_data.get('end_station', ''))

    # --- 日期 (直接使用，格式 YYYY/MM/DD) ---
    travel_date = task_data.get('travel_date', '')
    if not travel_date:
        raise ValueError("task_data 缺少 'travel_date' 欄位")

    # --- 搜尋方式 & 時間/車次 ---
    train_no = str(task_data.get('train_no', '') or '').strip()
    train_time = str(task_data.get('train_time', '') or '').strip()

    if train_no:
        # 車次模式（radio33）
        search_by = 'radio33'
        outbound_time = ''  # 不需時間參數
        outbound_train_id = train_no
    else:
        # 時間模式（radio31）
        if not train_time:
            raise ValueError("缺少 train_time（HH:MM）或 train_no（車次號碼），兩者不能同時為空。")
        search_by = 'radio31'
        outbound_time = _resolve_timetable_value(train_time)
        outbound_train_id = ''

    # --- 票種與張數 ---
    identity     = task_data.get('identity', 'adult')
    ticket_count = int(task_data.get('ticket_count', 1))
    amounts      = _build_ticket_amounts(identity, ticket_count)

    # ticketTypeNum: 逗號分隔的 5 種票量字串 (順序: F,H,W,E,P)
    ticket_type_num = f"{amounts['F']},{amounts['H']},{amounts['W']},{amounts['E']},{amounts['P']}"

    # --- 車廂種類 & 座位喜好 ---
    class_type  = int(task_data.get('class_type', 0))   # 0=標準, 1=商務, 2=自由座
    seat_prefer = int(task_data.get('seat_prefer', 0))  # 0=無, 1=靠窗, 2=走道

    logger.info(
        f"get_booking_data: {task_data.get('start_station')}({start_station_id})"
        f" → {task_data.get('end_station')}({end_station_id})"
        f" | {travel_date} {task_data.get('train_time','')} ({outbound_time})"
        f" | identity={identity} count={ticket_count}"
        f" | class={class_type} seat={seat_prefer}"
    )

    form_data = {
        "BookingS1Form:hf:0":               "",
        "tripCon:typesoftrip":              0,          # 0=單程 (去回程不在此系統範圍內)
        "trainCon:trainRadioGroup":         class_type,
        "seatCon:seatRadioGroup":           seat_prefer,
        "bookingMethod":                    search_by,
        "selectStartStation":               start_station_id,
        "selectDestinationStation":         end_station_id,
        "toTimeInputField":                 travel_date,
        "backTimeInputField":               travel_date, # 單程時與去程同日，不影響結果
        "toTimeTable":                      outbound_time,
        "toTrainIDInputField":              outbound_train_id,
        "backTimeTable":                    '',
        "backTrainIDInputField":            '',
        "ticketPanel:rows:0:ticketAmount":  amounts['F'],
        "ticketPanel:rows:1:ticketAmount":  amounts['H'],
        "ticketPanel:rows:2:ticketAmount":  amounts['W'],
        "ticketPanel:rows:3:ticketAmount":  amounts['E'],
        "ticketPanel:rows:4:ticketAmount":  amounts['P'],
        "ticketTypeNum":                    ticket_type_num,
        "homeCaptcha:securityCode":         passcode,
    }

    return form_data

# ----------------------------------------------------------------------------
# Submit Booking Form
# ----------------------------------------------------------------------------

def thsr_submit_booking_form(session: Session, page: str, url_path: str, passcode: str, task_data: Dict[str, Any]) -> str:
    page = None

    submit_url = BASE_URL + url_path

    logger.info(MAGENTA + f"(OLD) submit_url = {submit_url}" + RESET)

    jsessionid = session.cookies["JSESSIONID"]

    print(YELLOW + f'session.cookies["JSESSIONID"] = {jsessionid}' + RESET)

    # SUBMIT_FORM_URL = "https://irs.thsrc.com.tw/IMINT/;jsessionid={}?wicket:interface=:0:BookingS1Form::IFormSubmitListener"
    
    # submit_url = SUBMIT_FORM_URL.format(jsessionid)

    # logger.info(MAGENTA + f"(NEW) submit_url = {submit_url}" + RESET)

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

    form_data = get_booking_data(passcode, task_data)

    try:
        # Measure time just for the request (ms, integer)
        t0 = time.perf_counter()
        response = session.post(submit_url, headers=http_headers, data=form_data, allow_redirects=True, timeout=http_timeout)
        elapsed_ms = int(round((time.perf_counter() - t0) * 1000.0))  # ms, integer

        # Check if the request was successful
        if response.status_code == 200:
            page = response.text  # response.content   # response.text
            logger.info(CYAN + f"Get booking response from {submit_url}" + RESET)

            if (SAVE_BOOKING_PAGE):
                filename = os.path.join(OUTPUT_DIR, "booking_response.html")
                with open(filename, "w", encoding="utf-8") as file:
                    file.write(response.text)
                    # file.write(page)
                logger.info(f"HTML content saved to {filename}")
        else:
            logger.info(f"Failed to retrieve content. Status code: {response.status_code}")

        logger.info(f"resp.status_code = {response.status_code}")
        logger.info(f"request elapsed = {elapsed_ms} ms")

    except requests.exceptions.ProxyError as e:
        logging.error(f"Proxy error: {e}", exc_info=True)
    except requests.exceptions.SSLError as e:
        logging.error(f"SSL error: {e}", exc_info=True)
    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred: {e}", exc_info=True)
        # 在 logging.error() 加上 exc_info 參數，就可以紀錄 Exception。

    return page


# ----------------------------------------------------------------------------
# Select Target Train id (by time or train id)
# ----------------------------------------------------------------------------

# 設定全域變數：時間比對的容許範圍（分鐘）
# 允許範圍：-5 分鐘到 +5 分鐘
TIME_TOLERANCE_MINUTES = 5

def select_train_and_submit(page: str, search_by: str, target_list: list) -> str:
    """
    根據時間（含前後容許範圍）或車次列表自動選擇台灣高鐵訂票頁面上的車次，並模擬點擊「確認車次」按鈕。

    Args:
        page: HTML 檔案內容 (字串)。
        search_by: 查詢方式，'時間' 或 '車次'。
        target_list: 優先的時間列表 (格式: 'HH:MM') 或車次號碼列表 (格式: 'XXX' 或 'XXXX')。

    Returns:
        成功選擇與準備提交，返回 'Train selected and form submitted successfully.'。
        找不到符合條件的車次，返回 'No matching train found.'。
        參數錯誤，返回 'Invalid search_by parameter. Must be "時間" or "車次".'。
    """
    global TIME_TOLERANCE_MINUTES

    if search_by not in ['時間', '車次']:
        return 'Invalid search_by parameter. Must be "時間" or "車次".'

    soup = BeautifulSoup(page, 'html.parser')
    
    # 尋找所有車次選項
    train_options = soup.select('div.result-listing label.result-item')

    # 找到表單的 action URL
    form = soup.find('form', {'id': 'BookingS2Form'})
    if not form:
        return 'Form "BookingS2Form" not found.'
    
    form_action = form.get('action')
    if not form_action:
        return 'Form action URL not found.'

    # 2. 取得隱藏欄位 'BookingS2Form:hf:0' 的值 (這是 Wicket 框架通常需要的)
    hf_input = form.find('input', {'name': 'BookingS2Form:hf:0'})
    hf_value = hf_input.get('value') if hf_input else ''

    # 儲存最終選擇的車次 input 標籤
    selected_train_input = None

    if search_by == '車次':
        # 按照 target_list 中的車次號碼優先級選擇
        for target_code in target_list:
            for train_label in train_options:
                train_input = train_label.find('input', {'name': 'TrainQueryDataViewPanel:TrainGroup'})
                
                # 取得車次號碼
                query_code = train_input.get('querycode')
                
                if query_code == target_code:
                    selected_train_input = train_input
                    break
            if selected_train_input:
                break
                
    elif search_by == '時間':
        
        # 1. 將 target_list 中的時間轉換為分鐘數
        target_minutes_list = []
        for time_str in target_list:
            try:
                h, m = map(int, time_str.split(':'))
                target_minutes_list.append(h * 60 + m)
            except ValueError:
                print(f"Warning: Invalid time format in target_list: {time_str}")
        
        if not target_minutes_list:
             return 'No valid time format found in target_list.'
             
        train_candidates = []
        
        for train_label in train_options:
            train_input = train_label.find('input', {'name': 'TrainQueryDataViewPanel:TrainGroup'})
            
            # 取得出發時間
            query_departure = train_input.get('querydeparture')
            if not query_departure:
                continue

            try:
                dep_h, dep_m = map(int, query_departure.split(':'))
                departure_minutes = dep_h * 60 + dep_m
                
                min_abs_diff = float('inf')
                best_target_index = float('inf')
                
                # 遍歷所有目標時間，找到符合容許範圍且優先級最高的目標
                for index, target_minutes in enumerate(target_minutes_list):
                    # 計算實際出發時間與目標時間的差距
                    diff = departure_minutes - target_minutes
                    abs_diff = abs(diff)
                    
                    # 檢查是否在容許範圍內 (-5 到 +5 分鐘)
                    if abs_diff <= TIME_TOLERANCE_MINUTES:
                        
                        # 如果這是目前找到的、優先級更高的目標時間
                        if index < best_target_index:
                            best_target_index = index
                            min_abs_diff = abs_diff
                            
                        # 如果優先級相同，選擇差距更小的
                        elif index == best_target_index and abs_diff < min_abs_diff:
                            min_abs_diff = abs_diff
                            
                
                if best_target_index != float('inf'):
                    # 儲存車次 input、與目標時間的絕對差距、以及在 target_list 中的優先級
                    train_candidates.append({
                        'input': train_input, 
                        'abs_diff': min_abs_diff, 
                        'target_index': best_target_index,
                        'departure_minutes': departure_minutes
                    })
            except ValueError:
                # 忽略格式不正確的車次時間
                continue

        if train_candidates:
            # 排序邏輯：
            # 1. 優先級最高的 target_list (target_index 越小越好)
            # 2. 絕對時間差距越小越好 (abs_diff 越小越好)
            # 3. 如果前兩者相同，則選出發時間較早的 (departure_minutes 越小越好)
            train_candidates.sort(key=lambda x: (x['target_index'], x['abs_diff'], x['departure_minutes']))
            
            selected_train_input = train_candidates[0]['input']
            
    
    if selected_train_input:
        # 1. 設定選中的車次 input 的 'checked' 屬性為 'true'，並移除其他選項的 'checked'
        for train_label in train_options:
            train_input = train_label.find('input', {'name': 'TrainQueryDataViewPanel:TrainGroup'})
            if train_input == selected_train_input:
                train_input['checked'] = 'true'
            else:
                if 'checked' in train_input.attrs:
                    del train_input['checked']
                    
        # 2. 模擬點擊 '確認車次' 按鈕 (實際的網路請求需要您在外部處理)

        # 4. 取得選中車次的 radio button 資訊
        radio_name = selected_train_input.get('name')
        radio_value = selected_train_input.get('value')

        # selected_radio              = selected_train_input.get('value')
        selected_code               = selected_train_input.get('querycode')
        selected_querydeparturedate = selected_train_input.get('querydeparturedate')
        selected_departure          = selected_train_input.get('querydeparture')
        
        print(f"Selected Train (Tolerance {TIME_TOLERANCE_MINUTES} min): Code={selected_code}, Departure_Date={selected_querydeparturedate}, Departure={selected_departure}")
        print(f"Next step: Submit form to {form_action} with data including the selected train.")

        # select_train_data = {
        #     "BookingS2Form:hf:0": hf_value,
        #     "TrainQueryDataViewPanel:TrainGroup": radio_value,
        #     "SubmitButton": '確認車次'
        # }

        # 5. 構建完整的表單提交數據
        form_data = {
            'BookingS2Form:hf:0': hf_value,               # Wicket 隱藏欄位
            radio_name: radio_value,                      # 選中的車次 radio button
            'SubmitButton': '確認車次'                     # 提交按鈕
        }

        print(form_data)

        # 返回成功訊息
        # return 'Train selected and form submitted successfully.'

        return {
            'url': form_action,
            'data': form_data,
            'train_code': selected_code
        }

    else:
        # 未找到符合條件的車次
        return 'No matching train found.'


# ----------------------------------------------------------------------------
# Load Booking Main Page
# ----------------------------------------------------------------------------

def thsr_load_booking_page(session: Session) -> str:

    page = None

    try:
        # Measure time just for the request (ms, integer)
        t0 = time.perf_counter()
        response = session.get(BOOKING_PAGE_URL, headers=http_headers, allow_redirects=True, timeout=http_timeout)
        elapsed_ms = int(round((time.perf_counter() - t0) * 1000.0))  # ms, integer

        # cookies = response.json().get('cookies')
        # logger.info(CYAN + f"cookies = {cookies}" + RESET)


        # Check if the request was successful
        if response.status_code == 200:
            # page = response.content   # or response.text ??
            page = response.text   # or response.text ??
            logger.info(CYAN + f"Get booking page from {BOOKING_PAGE_URL}" + RESET)
            if (SAVE_BOOKING_PAGE):
                filename = os.path.join(OUTPUT_DIR, "booking_1st_page.html")
                with open(filename, "w", encoding="utf-8") as file:
                    # file.write(response.text)
                    file.write(page)
                logger.info(f"HTML content saved to {filename}")
        else:
            logger.info(f"Failed to retrieve content. Status code: {response.status_code}")

        logger.info(f"resp.status_code = {response.status_code}")
        logger.info(f"request elapsed = {elapsed_ms} ms")

    except requests.exceptions.ProxyError as e:
        logging.error(f"Proxy error: {e}", exc_info=True)
    except requests.exceptions.SSLError as e:
        logging.error(f"SSL error: {e}", exc_info=True)
    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred: {e}", exc_info=True)
        # 在 logging.error() 加上 exc_info 參數，就可以紀錄 Exception。

    # if elapsed_ms is not None:
    #     logger.info(f"request elapsed = {elapsed_ms} ms")

    return page




# ----------------------------------------------------------------------------
# Main THSR Booking System
# ----------------------------------------------------------------------------

def thsr_run_booking_flow(
    task_id: str,
    task_data: Dict[str, Any],
    cancel_event: threading.Event,
    status_updater: callable
) -> Tuple[bool, str]:
    """
    執行高鐵訂票流程 (真實版本)。
    與 booking.thsr_run_booking_flow_with_data 擁有相同的 interface。

    Args:
        task_id:        任務唯一識別碼。
        task_data:      訂票所需資料 (start_station, end_station, travel_date, train_time,
                        name, personal_id, phone_num, email, identity ...)。
        cancel_event:   threading.Event，由外部設定 (set()) 以中止任務。
        status_updater: callable(task_id, status, message)，用於回報進度給呼叫者。

    Returns:
        Tuple[bool, str]: (成功與否, 結果訊息)
    """

    global booking_OK, booking_NG

    logger.info(
        f"Task {task_id} received. "
        f"Passenger: {task_data.get('name', 'N/A')} | "
        f"Route: {task_data.get('start_station', '?')} to {task_data.get('end_station', '?')}"
    )
    status_updater(task_id, 'running', '開始初始化 Session...')

    t0 = time.perf_counter()
    booking_success = False
    result_message = ""

    try:
        # ------------------------------------------------------------------
        # 步驟 0: 取消檢查
        # ------------------------------------------------------------------
        if cancel_event.is_set():
            raise Exception("取消排隊中任務")

        # ------------------------------------------------------------------
        # 步驟 1: 初始化 Session
        # ------------------------------------------------------------------
        session = session_init()
        if not session:
            raise Exception("Session 初始化失敗。")
        status_updater(task_id, 'running', 'Session 初始化成功。載入訂票頁面中...')

        # ------------------------------------------------------------------
        # 步驟 2: 載入訂票首頁
        # ------------------------------------------------------------------
        if cancel_event.is_set():
            raise Exception("放棄排隊中任務")

        page = thsr_load_booking_page(session)
        if not page:
            raise Exception("Unable to load the ticket booking page; process terminated.")
        status_updater(task_id, 'running', '訂票頁面載入成功。解析表單元素中...')

        # ------------------------------------------------------------------
        # 步驟 3: 解析表單元素 ID
        # ------------------------------------------------------------------
        if cancel_event.is_set():
            raise Exception("放棄運行中任務")

        booking_form = parse_booking_form_element_id(session, page)
        if booking_form is None:
            raise Exception("訂票頁面解析失敗，表單結構異常。")

        captcha_passcode_url    = booking_form['captcha_image_url']
        captcha_reload_url      = booking_form['captcha_reload_url']    # noqa: F841
        booking_form_submit_url = booking_form['booking_submit_url']
        status_updater(task_id, 'running', '表單元素解析成功。下載驗證碼圖片中...')

        # ------------------------------------------------------------------
        # 步驟 4: 下載驗證碼並識別
        # ------------------------------------------------------------------
        sleep_range(5, 6)

        if cancel_event.is_set():
            raise Exception("放棄運行中任務")

        passcode = None
        if captcha_passcode_url:
            logger.info("--- Download Captcha Image ---")
            sleep_range(0, 1)
            passcode = save_and_parse_captcha_image(session, captcha_passcode_url)
        
        if not passcode:
            raise Exception("驗證碼取得或識別失敗。")
        
        logger.info(YELLOW + f"passcode = {passcode}" + RESET)
        status_updater(task_id, 'running', f'驗證碼識別成功。提交訂票表單中...')

        # ------------------------------------------------------------------
        # 步驟 5: 提交訂票表單 (第一頁)
        # ------------------------------------------------------------------
        if cancel_event.is_set():
            raise Exception("取消運行中任務")

        sleep_range(2, 3)
        page = thsr_submit_booking_form(session, page, booking_form_submit_url, passcode, task_data)

        is_error_found, errmsg_set = check_and_print_errors(page)

        if is_error_found:
            # 驗證碼錯誤或表單錯誤，本輪失敗 (呼叫端的 while loop 可決定是否重試)
            # result_message = "訂票表單提交失敗：驗證碼錯誤或欄位有誤。"     # [scott@2026-03-15] 直接使用Server回覆的訊息 (無 '欄位有誤')
            # errmsg_str = str(errmsg_set)
            # result_message = errmsg_str    # [scott@2026-03-16] should translate errmsg_list to errmsg_str
            result_message = "".join(errmsg_set)  # 把集合裡的字串合併
            booking_NG += 1
            return "booking_failed", result_message

        status_updater(task_id, 'running', '表單提交成功。選擇車次中...')

        if SAVE_BOOKING_PAGE:
            filename = os.path.join(OUTPUT_DIR, "booking_2nd_page.html")
            with open(filename, "w", encoding="utf-8") as file:
                file.write(page)
            logger.info(f"HTML content saved to {filename}")

        # ------------------------------------------------------------------
        # 步驟 6: 選擇車次並取得提交資料
        # ------------------------------------------------------------------
        if cancel_event.is_set():
            raise Exception("取消運行中任務")

        train_no = str(task_data.get('train_no', '') or '').strip()
        train_time = str(task_data.get('train_time', '') or '').strip()

        if train_no:
            # 依車次號碼選擇
            submission_info = select_train_and_submit(page, '車次', [train_no])
        else:
            # 依時間 (HH:MM) 選擇
            if not train_time:
                raise ValueError("缺少 train_time（HH:MM）或 train_no（車次號碼），無法選擇車次。")
            submission_info = select_train_and_submit(page, '時間', [train_time])

        if not isinstance(submission_info, dict):
            result_message = f"選車失敗：{submission_info}"
            booking_NG += 1
            return False, result_message

        submission_url  = submission_info['url']
        submission_data = submission_info['data']
        status_updater(task_id, 'running', f'車次選擇完成。送出訂位請求中...')

        # ------------------------------------------------------------------
        # 步驟 7: POST 送出訂位
        # ------------------------------------------------------------------
        if cancel_event.is_set():
            raise Exception("取消運行中任務")

        response = session.post(
            BASE_URL + submission_url,
            headers=http_headers,
            data=submission_data,
            allow_redirects=True,
            timeout=http_timeout
        )
        response.raise_for_status()

        if SAVE_BOOKING_PAGE:
            filename = os.path.join(OUTPUT_DIR, "booking_3rd_page.html")
            with open(filename, "w", encoding="utf-8") as file:
                file.write(response.text)
            logger.info(f"HTML content saved to {filename}")

        # ------------------------------------------------------------------
        # 步驟 8: 解析訂位代號
        # ------------------------------------------------------------------
        # 嘗試從回應頁面中解析訂位代號
        booking_code_match = re.search(r'訂位代號[：:]\s*([A-Z0-9]{4,10})', response.text)
        if booking_code_match:
            booking_code = booking_code_match.group(1)
            result_message = f"訂位代號: {booking_code}"
            booking_success = True
            booking_OK += 1
            status_updater(task_id, 'running', f'訂位成功！{result_message}')
        else:
            result_message = "訂位請求已送出，但搶輸訂位" # [scott@2026-03-17] 應該是搶輸訂位, should save webpage for debugging
            # result_message = "訂位請求已送出，但未能解析訂位代號，請至官網確認。" # [scott@2026-03-17] 應該是搶輸訂位
            booking_NG += 1
            status_updater(task_id, 'running', result_message)
            return "booking_failed", result_message

        return "booking_success", result_message

    except Exception as e:
        if "取消" in str(e) or "中斷" in str(e) or "放棄" in str(e):
            result_message = str(e)
            return 'task_aborted', result_message

        booking_NG += 1
        result_message = f"訂票流程中斷: {e}"
        logger.error(f"Task {task_id} execution failed: {e}")
        return 'unknown_result', result_message


    # except Exception as e:
    #     err_str = str(e)

    #     if "取消" in err_str:
    #         result_message = err_str
    #         return False, result_message

    #     booking_NG += 1
    #     result_message = f"訂票流程中斷: {e}"
    #     logger.error(f"Task {task_id} execution failed: {e}")
    #     return False, result_message

    finally:
        t1 = time.perf_counter() - t0
        logger.info(
            f"{YELLOW}Task {task_id} finished. "
            f"Total run time = {t1:.2f}s. "
            f"booking_success: {booking_success}{RESET}"
        )
        print('-' * 80)



# ----------------------------------------------------------------------------
# Entry Function for THSR Booking System
# ----------------------------------------------------------------------------

logger = logging.getLogger(__name__)

def main():
    # logging.basicConfig(filename='myapp.log', level=logging.INFO)
    FORMAT = '[%(asctime)s][%(levelname)s][%(funcName)s]: %(message)s'
    logging.basicConfig(level=logging.INFO, format=FORMAT)

    logger.info('Started')

    # 模擬 task_data (與 app.py 的 submit 格式一致)
    mock_task_data = {
        'start_station': '台北',
        'end_station': '左營',
        'travel_date': '2026/03/31',
        'train_time': '12:00',
        'name': 'Standalone User',
        'personal_id': 'A123456789',
    }

    def cli_status_updater(task_id, status, message):
        print(f"[STATUS UPDATE] Task {task_id} - {status.upper()}: {message}")

    task_id    = "PROXY-STANDALONE-001"
    cancel_event = threading.Event()
    max_run    = 5
    n          = 0

    t0 = time.perf_counter()

    while n < max_run:
        n += 1
        print(f"\n--- Running Booking Flow (proxy), Run {n}/{max_run} ---")

        success, result_msg = thsr_run_booking_flow(
            task_id=f"{task_id}-{n}",
            task_data=mock_task_data,
            cancel_event=cancel_event,
            status_updater=cli_status_updater
        )

        if success:
            print(f"\n{GREEN}✅ Booking succeeded!{RESET} Message: {result_msg}")
            break
        else:
            print(f"\n{RED}❌ Booking failed.{RESET} Message: {result_msg}")

    t1 = int(round((time.perf_counter() - t0) * 1000.0))
    t2 = t1 / n if n else 0

    print(f"all run time = {t1}ms")
    print(f"avg run time = {t2:.1f}ms")
    print(f"booking_OK   = {booking_OK}")
    print(f"booking_NG   = {booking_NG}")

    logger.info('Finished')


# ----------------------------------------------------------------------------
# Execute the main function only when the script is run directly from shell.
# For example: ~$ Python myapp.py
# Note: If this file is not being imported as a module
# Note: The __name__ variable is set to '__main__' when the file is executed.
# ----------------------------------------------------------------------------

if __name__ == '__main__':
    main()
