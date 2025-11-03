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

# Initialize ddddocr
ocr = ddddocr.DdddOcr(show_ad=False)
# ocr = ddddocr.DdddOcr()

def sleep_range(a, b):
    sec = random.uniform(a, b)
    sleep(sec)

# ----------------- 模擬點擊按鈕的程式碼 -----------------

def reload_captcha_image(session: Session, url_path: str) -> bool:
    """
    通過發送 Wicket Ajax 請求，模擬點擊「重新產生驗證碼」按鈕。

    Args:
        session: 包含當前會話狀態 (Cookies) 的 requests.Session 物件。

    Returns:
        如果請求成功則返回 True，否則返回 False。
    """

    # captcha_recode_link = AJAX_FULL_URL
    captcha_recode_link = BASE_URL + url_path

    logger.debug(f"正在模擬點擊 (Ajax GET): {captcha_recode_link}")

    try:
        # 發送 GET 請求到 Ajax URL
        # Wicket Ajax 請求通常是一個 GET 請求
        response = session.get(
            captcha_recode_link,
            headers=http_headers,
            # headers=ajax_http_headers,
            timeout=15
        )

        # 檢查 HTTP 狀態碼
        response.raise_for_status()

        # 成功的 Wicket Ajax 響應通常是 XML 格式，並帶有 200 狀態碼
        logger.debug("Session request successful: 200 OK")

        # cookies = response.json().get('cookies')
        # logger.info(CYAN + f"cookies = {cookies}" + RESET)


        # Wicket 的響應內容 (response.text) 包含了指示瀏覽器更新 DOM 的 XML
        # 如果需要，您可以解析這個 XML 檢查驗證碼圖片的 src 是否有更新
        # print("Wicket Ajax Response Preview (XML):", response.text[:200] + "...")

        return True

    except requests.exceptions.RequestException as e:
        print(f"請求失敗: {e}")
        return False


def get_captcha_value(image_bytes):
    captcha_value = ocr.classification(image_bytes)
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

    # 使用 global 變數 BASE_URL 與相對路徑組合，形成完整的 URL
    img_full_url = BASE_URL + img_src

    if not img_src:
        print("錯誤: 圖片相對路徑 (img_src) 不可為空。")
        return False

    logger.info(f"Try to get image from: {img_full_url}")

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

    booking_form['captcha_image_url']  = inject_jsessionid_to_url(session, booking_form['captcha_image_url'])
    booking_form['captcha_reload_url'] = inject_jsessionid_to_url(session, booking_form['captcha_reload_url'])
    booking_form['booking_submit_url'] = inject_jsessionid_to_url(session, booking_form['booking_submit_url'])

    print(CYAN)

    print(f"captcha_image_url  = {booking_form['captcha_image_url']}")
    print(f"captcha_reload_url = {booking_form['captcha_reload_url']}")
    print(f"booking_submit_url = {booking_form['booking_submit_url']}")

    print(RESET)


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
        # print("✅ HTML 內容中未發現 'feedbackPanelERROR'，可能已成功進入下一步。")
        return False


def thsr_submit_booking_form(session: Session, url_path: str, passcode: str) -> bytes:
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


    types_of_trip = 0
    class_type = 0
    seat_prefer = 0
    search_by = 'radio31'
    start_station = 2
    dest_station = 3
    outbound_date = '2025/11/04'
    inbound_date = '2025/11/04'
    outbound_time = '1201A'
    outbound_train_id = ""
    inbound_time = ''
    inbound_train_id = ""
    adult_ticket_num = '1F'
    child_ticket_num = '0H'
    disabled_ticket_num = '0W'
    elder_ticket_num = '0E'
    college_ticket_num = '0P'
    type_num = f"{adult_ticket_num},{child_ticket_num},{disabled_ticket_num},{elder_ticket_num},{college_ticket_num}"


    form_data = {
        "BookingS1Form:hf:0": "",
        "tripCon:typesoftrip": types_of_trip,
        "trainCon:trainRadioGroup": class_type,
        "seatCon:seatRadioGroup": seat_prefer,
        "bookingMethod": search_by,
        "selectStartStation": start_station,
        "selectDestinationStation": dest_station,
        "toTimeInputField": outbound_date,
        "backTimeInputField": inbound_date,
        "toTimeTable": outbound_time,
        "toTrainIDInputField": outbound_train_id,
        "backTimeTable": inbound_time,
        "backTrainIDInputField": inbound_train_id,
        "ticketPanel:rows:0:ticketAmount": adult_ticket_num,
        "ticketPanel:rows:1:ticketAmount": child_ticket_num,
        "ticketPanel:rows:2:ticketAmount": disabled_ticket_num,
        "ticketPanel:rows:3:ticketAmount": elder_ticket_num,
        "ticketPanel:rows:4:ticketAmount": college_ticket_num,
        "ticketTypeNum": type_num,
        "homeCaptcha:securityCode": passcode,
    }

    try:
        # Measure time just for the request (ms, integer)
        t0 = time.perf_counter()
        response = session.post(submit_url, headers=http_headers, data=form_data, allow_redirects=True, timeout=http_timeout)
        elapsed_ms = int(round((time.perf_counter() - t0) * 1000.0))  # ms, integer

        # Check if the request was successful
        if response.status_code == 200:
            page = response.content   # response.text
            logger.info(CYAN + f"Get booking response from {submit_url}" + RESET)

            # cookies = response.json().get('cookies')
            # logger.info(CYAN + f"cookies = {cookies}" + RESET)


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


def thsr_load_booking_page(session: Session) -> bytes:

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
                filename = "booking_page.html"
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
# Regenerate Captcha Function
# ----------------------------------------------------------------------------

def XXX_thsr_regenerate_captcha_flow(session: requests.Session, booking_page_html: bytes):
    """
    完整的重新產生並識別驗證碼流程。
    1. 模擬點擊「重新產生」按鈕 (Ajax)。
    2. 重新解析 HTML 以取得新的驗證碼圖片 src。
    3. 下載並識別新的驗證碼圖片。
    """
    logger.info("--- 開始執行重新產生驗證碼流程 ---")

    # 步驟 1: 模擬點擊「重新產生」按鈕
    if not click_regenerate_captcha_button(session):
        logger.error("重新產生驗證碼失敗，流程終止。")
        return

    # 步驟 2: 重新獲取並識別新的驗證碼

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
    captcha_passcode_url, captcha_reCode_url = get_captcha_src(booking_page_html.decode('utf-8'))

    if captcha_passcode_url:
        # 步驟 3: 下載並識別新的驗證碼圖片
        # 由於 Ajax 成功，使用相同的 img_src 去下載，會取得新的圖片內容。
        logger.info("取得新的驗證碼圖片並識別...")
        save_captcha_image(session, captcha_passcode_url, file_path="new_captcha.png")
    else:
        logger.error("無法取得驗證碼圖片 src，流程終止。")


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

    if (run):

        sleep_range(1, 2)

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

        sleep_range(1, 2)

        if (captcha_passcode_url):
            logger.info("--- Download Captcha Image ---")
            passcode = save_captcha_image(session, captcha_passcode_url)            
        else:
            pass  # TBD

        sleep_range(1, 2)

        if (passcode):
            logger.info(YELLOW + f"passcode = {passcode}" + RESET)
            page = thsr_submit_booking_form(session, booking_form_submit_url, passcode)
        else:
            logger.info(YELLOW + "passcode is empty" + RESET)


        is_error_found = check_and_print_errors(page)

        run = False

        return is_error_found

        sleep_range(2, 3)

        logger.info("--- Reload Captcha Image ---")

        if (captcha_reload_url):
            # reload captcha image by clicking 'regenerate' button
            if not reload_captcha_image(session, captcha_reload_url):
                logger.error("Failed to reload captcha image")
                return
        else:
            pass  # TBD

        n = n + 1



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

    max_run = 10

    n = 0

    t0 = time.perf_counter()


    while (n < max_run):
        thsr_run_booking_flow()
        n = n + 1

    t1 = int(round((time.perf_counter() - t0) * 1000.0))  # ms, integer
    t2 = t1 / n

    print(f"all run time = {t1}ms")
    print(f"avg run time = {t2}ms")

    logger.info('Finished')


# ----------------------------------------------------------------------------
# Execute the main function only when the script is run directly from shell.
# For example: ~$ Python myapp.py
# Note: If this file is not being imported as a module
# Note: The __name__ variable is set to '__main__' when the file is executed.
# ----------------------------------------------------------------------------

if __name__ == '__main__':
    main()
