import logging

from typing import Mapping, Any, Optional, Union, List

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

def save_captcha_image(session: Session, img_src: str, file_path: str = "captcha_downloaded.png") -> bool:
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

    logger.info(CYAN + f"Try to get image from: {img_full_url}" + RESET)

    captcha_value = None

    try:
        # 發送 GET 請求。設置 timeout 以防連線無限期等待
        # response = session.get(img_full_url, stream=True, timeout=10)
        response = session.get(img_full_url, headers=http_headers)

        # 檢查 HTTP 狀態碼 (例如 200 OK, 404 Not Found 等)
        response.raise_for_status() # 如果狀態碼不是 200，會拋出 HTTPError

        print("-------------- OK --------------")
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
        print(YELLOW + f"Get captcha value '{captcha_value}'" + RESET)


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

    print(RED)

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
        print(f"\n{RED}{BOLD}======= 🚨 提交錯誤訊息：======= {RESET}")
        
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
            print(f"{RED}🚫 {error}{RESET}")
            
        print(f"{RED}{BOLD}==================================={RESET}\n")
        return True
    else:
        booking_OK = booking_OK + 1
        print(YELLOW + "✅ HTML 內容中未發現 'feedbackPanelERROR'，可能已成功進入下一步。" + RESET)
        return False

def get_booking_data(passcode: str):

    booking_data = {}
    booking_data['types_of_trip'] = 0
    booking_data['class_type'] = 0
    booking_data['seat_prefer'] = 0
    booking_data['search_by'] = 'radio31'           # 最好不要hard-code
    booking_data['start_station'] = 2
    booking_data['dest_station'] = 3
    booking_data['outbound_date'] = '2025/11/14'
    booking_data['inbound_date'] = '2025/11/14'
    booking_data['outbound_time'] = '1201A'         # 最好不要hard-code
    booking_data['outbound_train_id'] = ""
    booking_data['inbound_time'] = ''
    booking_data['inbound_train_id'] = ""
    booking_data['adult_ticket_num'] = '1F'
    booking_data['child_ticket_num'] = '0H'
    booking_data['disabled_ticket_num'] = '0W'
    booking_data['elder_ticket_num'] = '0E'
    booking_data['college_ticket_num'] = '0P'
    booking_data['type_num'] = f"{booking_data['adult_ticket_num']},{booking_data['child_ticket_num']},{booking_data['disabled_ticket_num']},{booking_data['elder_ticket_num']},{booking_data['college_ticket_num']}"

    form_data = {
        "BookingS1Form:hf:0": "",
        "tripCon:typesoftrip": booking_data['types_of_trip'],
        "trainCon:trainRadioGroup": booking_data['class_type'],
        "seatCon:seatRadioGroup": booking_data['seat_prefer'],
        "bookingMethod": booking_data['search_by'],
        "selectStartStation": booking_data['start_station'],
        "selectDestinationStation": booking_data['dest_station'],
        "toTimeInputField": booking_data['outbound_date'],
        "backTimeInputField": booking_data['inbound_date'],
        "toTimeTable": booking_data['outbound_time'],
        "toTrainIDInputField": booking_data['outbound_train_id'],
        "backTimeTable": booking_data['inbound_time'],
        "backTrainIDInputField": booking_data['inbound_train_id'],
        "ticketPanel:rows:0:ticketAmount": booking_data['adult_ticket_num'],
        "ticketPanel:rows:1:ticketAmount": booking_data['child_ticket_num'],
        "ticketPanel:rows:2:ticketAmount": booking_data['disabled_ticket_num'],
        "ticketPanel:rows:3:ticketAmount": booking_data['elder_ticket_num'],
        "ticketPanel:rows:4:ticketAmount": booking_data['college_ticket_num'],
        "ticketTypeNum": booking_data['type_num'],
        "homeCaptcha:securityCode": passcode,
    }

    return form_data

# ----------------------------------------------------------------------------
# Submit Booking Form
# ----------------------------------------------------------------------------

def thsr_submit_booking_form(session: Session, page: str, url_path: str, passcode: str) -> str:
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

    form_data = get_booking_data(passcode)

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
                filename = "booking_response.html"
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


def select_train_and_submit_XXX(page: str, search_by: str, target_list: list) -> str:
    """
    根據時間或車次列表自動選擇台灣高鐵訂票頁面上的車次，並嘗試點擊「確認車次」按鈕。

    Args:
        page: HTML 檔案內容 (字串)。
        search_by: 查詢方式，'時間' (優先選擇出發時間最接近或等於 target_list 內時間的車次) 
                   或 '車次' (優先選擇 target_list 內車次號碼的車次)。
        target_list: 優先的時間列表 (格式: 'HH:MM') 或車次號碼列表 (格式: 'XXX' 或 'XXXX')。

    Returns:
        如果成功找到並選中車次，返回 'Train selected and form submitted successfully.'。
        如果未找到符合條件的車次，返回 'No matching train found.'。
        如果 'search_by' 參數不正確，返回 'Invalid search_by parameter. Must be "時間" or "車次".'。
    """
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

    # 儲存最終選擇的車次 input 標籤
    selected_train_input = None

    if search_by == '車次':
        # 按照 target_list 中的車次號碼優先級選擇
        for target_code in target_list:
            for train_label in train_options:
                train_input = train_label.find('input', {'name': 'TrainQueryDataViewPanel:TrainGroup'})
                
                # 取得車次號碼
                # query_code = train_input.get('QueryCode')
                query_code = train_input.get('querycode')
                
                if query_code == target_code:
                    selected_train_input = train_input
                    break
            if selected_train_input:
                break
                
    elif search_by == '時間':
        # 尋找最接近 target_list 中優先時間的出發時間
        
        # 將 target_list 中的時間轉換為分鐘數，方便比較
        target_minutes_list = []
        for time_str in target_list:
            try:
                h, m = map(int, time_str.split(':'))
                target_minutes_list.append(h * 60 + m)
            except ValueError:
                print(f"Warning: Invalid time format in target_list: {time_str}")
                
        if not target_minutes_list:
             return 'No valid time format found in target_list.'
             
        # 暫時儲存每個車次及其與目標時間的差距
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
                
                # 計算與每個目標時間的差距（越小越好，優先選擇目標時間在前的）
                min_diff = float('inf')
                best_target_index = float('inf')
                
                for index, target_minutes in enumerate(target_minutes_list):
                    diff = departure_minutes - target_minutes
                    
                    if diff >= 0 and diff < min_diff:
                        min_diff = diff
                        best_target_index = index
                        
                    elif diff < 0 and departure_minutes > target_minutes:
                        # 如果是前一天的時間 (例如 00:07 vs 23:59)，這裏暫時忽略跨日情況的複雜性，
                        # 簡單的假設我們只選當天的，如果需要跨日邏輯會更複雜。
                        pass

                if min_diff != float('inf'):
                    # 儲存車次 input、與目標時間的差距、以及在 target_list 中的優先級
                    train_candidates.append({
                        'input': train_input, 
                        'diff': min_diff, 
                        'target_index': best_target_index,
                        'departure_minutes': departure_minutes
                    })
            except ValueError:
                # 忽略格式不正確的車次時間
                continue

        if train_candidates:
            # 排序邏輯：
            # 1. 優先級最高的 target_list (target_index 越小越好)
            # 2. 差距越小越好 (diff 越小越好)
            # 3. 如果差距和目標優先級都一樣，則選出發時間較早的 (departure_minutes 越小越好)
            train_candidates.sort(key=lambda x: (x['target_index'], x['diff'], x['departure_minutes']))
            
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
                    
        # 2. 模擬點擊 '確認車次' 按鈕 (這個函式只是準備資料和提示下一步，實際的網路請求需要您在外部處理)
        
        # 取得選中車次的關鍵資訊來模擬表單提交
        selected_code = selected_train_input.get('querycode')
        selected_departure = selected_train_input.get('querydeparture')
        
        # 建立提交表單所需的資料 (簡化，實際可能需要更多 hidden 欄位)
        form_data = {
            'BookingS2Form:hf:0': '',
            'SubmitButton': '確認車次'
            # 實際提交時還需要選中的 radio button 的 value，這裡假設為 train_input.get('value')
            # 這裡我們只模擬選擇，實際提交的 HTTP Request/Data 需要外部 library (如 requests) 處理
        }
        
        print(f"Selected Train: Code={selected_code}, Departure={selected_departure}")
        print(f"Next step: Submit form to {form_action} with data including the selected train.")
        
        # 返回成功訊息
        return 'Train selected and form submitted successfully.'
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
                filename = "booking_1st_page.html"
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

def thsr_run_booking_flow():

    session = session_init()
    page = thsr_load_booking_page(session)

    if not page:
        logger.error("Unable to load the ticket booking page; process terminated.")
        return

    run = True

    n = 0

    # while (run):
    if (1):

        # sleep_range(1, 2)

        booking_form = parse_booking_form_element_id(session, page)

        # captcha_passcode_url, captcha_reload_url = get_captcha_src(page) # page.decode('utf-8')

        if (booking_form == None):
            logger.error("ERROR: booking page is something wrong")
            return

        captcha_passcode_url    = booking_form['captcha_image_url']
        captcha_reload_url      = booking_form['captcha_reload_url']
        booking_form_submit_url = booking_form['booking_submit_url']         

        # captcha_passcode_url    = BASE_URL + booking_form['captcha_image_url']
        # captcha_reload_url      = BASE_URL + booking_form['captcha_reload_url']
        # booking_form_submit_url = BASE_URL + booking_form['booking_submit_url']         

        sleep_range(0, 1)

        if (captcha_passcode_url):
            logger.info("--- Download Captcha Image ---")
            passcode = save_captcha_image(session, captcha_passcode_url)            
        else:
            pass  # TBD

        if (passcode):
            logger.info(YELLOW + f"passcode = {passcode}" + RESET)
            sleep_range(2, 3)
            page = thsr_submit_booking_form(session, page, booking_form_submit_url, passcode)
        else:
            logger.info(YELLOW + "passcode is empty" + RESET)

        is_error_found = check_and_print_errors(page)

        # if (is_error_found and captcha_passcode_url):
        #     logger.info("<<< Download Captcha Image >>>")
        #     passcode = save_captcha_image(session, captcha_passcode_url)            
        # else:
        #     pass  # TBD

        run = is_error_found

        if (is_error_found == False):
            if (SAVE_BOOKING_PAGE):
                filename = "booking_2nd_page.html"
                with open(filename, "w", encoding="utf-8") as file:
                    # file.write(response.text)
                    file.write(page)
                logger.info(f"HTML content saved to {filename}")
            
            # translate booking data here

            if (0):
                print("--- Search by Train Code ---")
                target_codes = ['9999', '1537', '803'] # 9999 不存在
                result_code = select_train_and_submit(page, '車次', target_codes)
                print(f"Result: {result_code}\n")
            else:
                print("--- Search by Time (Nearest after target) ---")
                target_times = ['15:44', '13:46', '06:21']
                submission_info = select_train_and_submit(page, '時間', target_times)
                # submission_info = select_train_and_get_submission_data(page_content, '車次', target_list_code)
                # print(f"Result: {result_time}\n")

            if 'error' in submission_info:
                print(f"Submission failed: {submission_info['error']}")
            else:
                submission_url = submission_info['url']
                submission_data = submission_info['data']
                
                print("\n--- Next Step: POST Request ---")
                print(f"POST URL: {submission_url}")
                print(f"POST Data: {submission_data}")
                
                # 實際的 POST 請求 (你需要執行這部分程式碼)
                try:                    
                    response = session.post(BASE_URL + submission_url, headers=http_headers, data=submission_data, allow_redirects=True, timeout=http_timeout)
                    print("POST Request sent successfully.")
                    # 處理下一頁的內容 post_response.text

                    if (SAVE_BOOKING_PAGE):
                        filename = "booking_3rd_page.html"
                        with open(filename, "w", encoding="utf-8") as file:
                            file.write(response.text)
                            # file.write(page)
                        logger.info(f"HTML content saved to {filename}")


                except requests.exceptions.RequestException as e:
                    print(f"An error occurred during POST request: {e}")
                    print(submission_info)


            return True




        # run = False

        # return is_error_found

        n = n + 1

        if (n > 2):
            run = False


        # booking_form = parse_booking_form_element_id(session, page)

        # sleep_range(2, 3)

        # logger.info("--- Reload Captcha Image ---")

        # if (captcha_reload_url):
        #     # reload captcha image by clicking 'regenerate' button
        #     if not reload_captcha_image(session, captcha_reload_url):
        #         logger.error("Failed to reload captcha image")
        #         return
        # else:
        #     pass  # TBD

    return False



# ----------------------------------------------------------------------------
# Entry Function for THSR Booking System
# ----------------------------------------------------------------------------

logger = logging.getLogger(__name__)

def main():
    # logging.basicConfig(filename='myapp.log', level=logging.INFO)

    # 定義輸出格式
    # FORMAT = '[%(asctime)s][%(filename)s][%(levelname)s]: %(message)s'
    FORMAT = '[%(asctime)s][%(levelname)s][%(funcName)s]: %(message)s'
    # Logging初始設定 + 上定義輸出格式
    logging.basicConfig(level=logging.INFO, format=FORMAT)

    logger.info('Started')

    max_run = 5

    n = 0

    t0 = time.perf_counter()


    while (n < max_run):
        v = thsr_run_booking_flow()
        n = n + 1
        if (v == True):
            break

    t1 = int(round((time.perf_counter() - t0) * 1000.0))  # ms, integer
    t2 = t1 / n

    print(f"all run time = {t1}ms")
    print(f"avg run time = {t2}ms")
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
