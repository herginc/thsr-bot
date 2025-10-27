import logging

from typing import Mapping, Any, Optional

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

# Initialize ddddocr
# ocr = ddddocr.DdddOcr(show_ad=False)
ocr = ddddocr.DdddOcr()

def sleep_range(a, b):
    sec = random.uniform(a, b)
    sleep(sec)

# ----------------- 模擬點擊按鈕的程式碼 -----------------

def click_regenerate_captcha_button(session: Session) -> bool:
    """
    通過發送 Wicket Ajax 請求，模擬點擊「重新產生驗證碼」按鈕。

    Args:
        session: 包含當前會話狀態 (Cookies) 的 requests.Session 物件。

    Returns:
        如果請求成功則返回 True，否則返回 False。
    """
    print(f"1. 正在模擬點擊 (Ajax GET): {AJAX_FULL_URL}")

    try:
        # 發送 GET 請求到 Ajax URL
        # Wicket Ajax 請求通常是一個 GET 請求
        response = session.get(
            AJAX_FULL_URL,
            headers=http_headers,
            timeout=15
        )

        # 檢查 HTTP 狀態碼
        response.raise_for_status()

        # 成功的 Wicket Ajax 響應通常是 XML 格式，並帶有 200 狀態碼
        print("2. 請求成功，伺服器響應狀態碼: 200 OK")

        # Wicket 的響應內容 (response.text) 包含了指示瀏覽器更新 DOM 的 XML
        # 如果需要，您可以解析這個 XML 檢查驗證碼圖片的 src 是否有更新
        # print("Wicket Ajax Response Preview (XML):", response.text[:200] + "...")

        return True

    except requests.exceptions.RequestException as e:
        print(f"請求失敗: {e}")
        return False


def get_captcha_value(image_bytes):
    captcha_value = ocr.classification(image_bytes)
    print(RED + f"Get captcha value '{captcha_value}'" + RESET)

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

    logger.debug(f"Try ing get image from: {img_full_url}")

    try:
        # 發送 GET 請求。設置 timeout 以防連線無限期等待
        # response = session.get(img_full_url, stream=True, timeout=10)
        response = session.get(img_full_url, headers=http_headers)

        # 檢查 HTTP 狀態碼 (例如 200 OK, 404 Not Found 等)
        response.raise_for_status() # 如果狀態碼不是 200，會拋出 HTTPError

        if (0):
            image = Image.open(io.BytesIO(response.content))
            image.show()

        if (1):
            # 以二進制寫入模式 ('wb') 開啟檔案
            with open(file_path, 'wb') as f:
                # 寫入圖片的二進制內容
                f.write(response.content)

        logger.info(f"Image downloaded successfully ({file_path})")

        captcha_image_bytes = response.content

        get_captcha_value(captcha_image_bytes)

        return True

    except requests.exceptions.HTTPError as e:
        print(f"下載圖片失敗，HTTP 錯誤碼: {e.response.status_code} ({e})")
        return False
    except requests.exceptions.RequestException as e:
        print(f"下載圖片失敗，連線或請求錯誤: {e}")
        return False
    except IOError as e:
        print(f"儲存檔案失敗，IO 錯誤: {e}")
        return False

# def parse_security_img_url(html: bytes) -> str:
#     page = BeautifulSoup(html, features="html.parser")
#     element = page.find(**BOOKING_PAGE["security_code_img"])
#     return HTTPConfig.BASE_URL + element["src"]


def get_captcha_src(response_content: str) -> Optional[str]:
    """
    從 HTML 內容中，根據特定的 ID 找到 img 元素的 src 屬性值。

    Args:
        response_content: 包含目標 img 元素的 HTML 字串。

    Returns:
        如果找到 img 元素，則返回其 src 屬性值 (str)；
        如果找不到，則返回 None。
    """

    # 使用 Beautiful Soup 解析 HTML 內容
    # 'html.parser' 是一個常用的解析器
    soup = BeautifulSoup(response_content, 'html.parser')

    # 目標 img 元素的 ID
    target_id = 'BookingS1Form_homeCaptcha_passCode'

    # 1. 找到具有特定 id 的 img 元素
    # 這是根據 ID 查找元素的最常用且最有效的方法之一
    # img_tag = soup.find('img', id=target_id)
    img_tag = soup.find(id=target_id)

    # 2. 檢查是否找到元素，並取得 src 屬性的值
    if img_tag:
        # 使用 .get() 方法來安全地取得屬性值。
        # 如果屬性存在，則返回其值；如果不存在，則返回 None，避免 KeyError。
        img_url = img_tag.get('src')
        logger.info(f"img_src={img_url}")
        return img_url
    else:
        # 如果找不到元素，則返回 None
        logger.error("無法找到驗證碼圖片元素")
        return None


def thsr_load_booking_page(session: Session):

    page = None

    try:
        # Measure time just for the request (ms, integer)
        t0 = time.perf_counter()
        response = session.get(BOOKING_PAGE_URL, headers=http_headers, allow_redirects=True, timeout=15)
        elapsed_ms = int(round((time.perf_counter() - t0) * 1000.0))  # ms, integer

        # Check if the request was successful
        if response.status_code == 200:
            page = response.content
            logger.info(f"{YELLOW}Get booking page from {BOOKING_PAGE_URL}{RESET}")
            if (SAVE_BOOKING_PAGE):
                filename = "output_10.html"
                with open(filename, "w", encoding="utf-8") as file:
                    file.write(response.text)
                logger.info(f"HTML content saved to {filename}")
        else:
            logger.info(f"Failed to retrieve content. Status code: {response.status_code}")

        logger.info(f"resp.status_code = {response.status_code}")
        # logger.info(f"request elapsed = {elapsed_ms} ms")

    except requests.exceptions.ProxyError as e:
        elapsed_ms = int(round((time.perf_counter() - t0) * 1000.0)) if 't0' in locals() else None
        # 在 logging.error() 加上 exc_info 參數，就可以紀錄 Exception。
        logging.error(f"Proxy error: {e}", exc_info=True)
    except requests.exceptions.SSLError as e:
        elapsed_ms = int(round((time.perf_counter() - t0) * 1000.0)) if 't0' in locals() else None
        # 在 logging.error() 加上 exc_info 參數，就可以紀錄 Exception。
        logging.error(f"SSL error: {e}", exc_info=True)
    except requests.exceptions.RequestException as e:
        elapsed_ms = int(round((time.perf_counter() - t0) * 1000.0)) if 't0' in locals() else None
        # 在 logging.error() 加上 exc_info 參數，就可以紀錄 Exception。
        logging.error(f"An error occurred: {e}", exc_info=True)

    if elapsed_ms is not None:
        logger.info(f"request elapsed = {elapsed_ms} ms")

    return page

def session_init():
    max_retries = 3

    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=max_retries))
    session.mount("http://", HTTPAdapter(max_retries=max_retries))

    if (PROXY_ENABLE):
        # (2025-10-23, 02:00) 62046 ms, 47633 ms, 19438 ms, 47847 ms, 34457 ms
        # (2025-10-24, 09:00) 19665 ms, 50486 ms
        # PROXY = DISABLED
        # PROXY = "http://60.249.94.59:3128"
        # PROXY = "http://202.29.215.78:8080"   # 101056 ms
        # PROXY = "http://165.154.110.152:1080" # 785 ms (HongKong)   (GOOD)
        # PROXY = "http://165.154.152.162:1080" # 1634 ms (HongKong)  (GOOD)
        # PROXY = "http://182.52.165.147:8080"  # 3780 ms (Thailand)

        # 使用 HTTP proxy (port 80) 做為 HTTP/HTTPS 代理
        PROXY = "http://182.52.165.147:8080"
        session.proxies.update({
            "http": PROXY,
            "https": PROXY,
        })
        # 避免 requests 使用環境變數中的代理設定（視需求可保留或移除）
        session.trust_env = False
        logger.info("*** proxy server enbled ***")

    return session


def thsr_regenerate_captcha_flow(session: requests.Session, booking_page_html: bytes):
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
    img_src = get_captcha_src(booking_page_html.decode('utf-8'))

    if img_src:
        # 步驟 3: 下載並識別新的驗證碼圖片
        # 由於 Ajax 成功，使用相同的 img_src 去下載，會取得新的圖片內容。
        logger.info("取得新的驗證碼圖片並識別...")
        save_captcha_image(session, img_src, file_path="new_captcha.png")
    else:
        logger.error("無法取得驗證碼圖片 src，流程終止。")

def thsr_run_booking_flow():

    session = session_init()
    page = thsr_load_booking_page(session)

    if not page:
        logger.error("無法加載訂票頁面，流程終止。")
        return

    sleep_range(1, 2)
    img_src = get_captcha_src(page) # page.decode('utf-8')

    if (img_src):
        logger.info("--- 第一次獲取驗證碼 ---")
        save_captcha_image(session, img_src)

    # 流程 B: 模擬點擊重新產生並識別
    thsr_regenerate_captcha_flow(session, page) # 傳入 session 和第一次加載的 HTML

    if (0):
        success = click_regenerate_captcha_button(session)

        if success:
            print("✅ 成功模擬重新產生驗證碼。")
            print("📢 下一步：您應該重新獲取**新的**驗證碼圖片的 `src` 值，並下載識別。")
        else:
            print("❌ 模擬失敗，請檢查網路連線或請求參數。")



logger = logging.getLogger(__name__)

def main():
    # logging.basicConfig(filename='myapp.log', level=logging.INFO)

    # 定義輸出格式
    # FORMAT = '[%(asctime)s][%(filename)s][%(levelname)s]: %(message)s'
    FORMAT = '[%(asctime)s][%(levelname)s][%(funcName)s]: %(message)s'
    # Logging初始設定 + 上定義輸出格式
    logging.basicConfig(level=logging.DEBUG, format=FORMAT)

    logger.info('Started')

    print(RED + "This text is red." + RESET)
    print(GREEN + "This text is green." + RESET)
    print(YELLOW + "This text is yellow." + RESET)
    print(RED + "Bold red text" + RESET) # Example with bold (bold code is 1;91m for red)

    thsr_run_booking_flow()

    logger.info('Finished')


if __name__ == '__main__':
    main()
