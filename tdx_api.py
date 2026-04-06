"""
tdx_api.py - TDX 交通資料平台 API 封裝模組
供其他程式呼叫 (e.g. app.py, Flask routes)

使用方式:
    from tdx_api import get_thsr_timetable_od

    trains = get_thsr_timetable_od(
        app_id='your-app-id',
        app_key='your-app-key',
        origin_id='1000',        # 台北
        destination_id='1040',   # 台中
        train_date='2026-03-20',
    )
    for t in trains:
        print(t['train_no'], t['dep_time'], t['arr_time'])

[scott@2026-04-06] 由 front-end client 直接呼叫 OData查詢，不需要先取得 token 再呼叫 API，因為 OData URL 已經包含了 token 參數。如此可節省back-end server的流量負擔，讓前端直接與TDX API溝通。
    支援OData查詢 https://tdx.transportdata.tw/api/basic/v2/Rail/THSR/DailyTimetable/OD/{OriginStationID}/to/{DestinationStationID}/{TrainDate} 
    https://tdx.transportdata.tw/api/basic/v2/Rail/THSR/DailyTimetable/OD/1030/to/1000/2026-04-27

    reference: https://tdx.transportdata.tw/data-service/basic  指定[日期]高鐵所有車次之時刻表資料 v2
    reference: https://tdx.transportdata.tw/api-service/swagger/basic/268fc230-2e04-471b-a728-a726167c1cfc#/THSR/THSRApi_ODDailyTimetable_2126
    reference: https://github.com/LinYenCheng/thsr-app        
"""

import requests
from datetime import datetime
from typing import Dict, List, Optional

# ----------------------------------------------------------------------------
# 高鐵車站名稱 → StationID 對照表
# ----------------------------------------------------------------------------

STATION_ID_MAP: Dict[str, str] = {
    '南港': '0990',
    '台北': '1000',
    '板橋': '1010',
    '桃園': '1020',
    '新竹': '1030',
    '苗栗': '1035',
    '台中': '1040',
    '彰化': '1043',
    '雲林': '1047',
    '嘉義': '1050',
    '台南': '1060',
    '左營': '1070',
}


# ----------------------------------------------------------------------------
# TDX 認證
# ----------------------------------------------------------------------------

def get_access_token(app_id: str, app_key: str) -> str:
    """
    向 TDX 取得 OAuth2 Access Token。

    Args:
        app_id:  TDX Client ID
        app_key: TDX Client Secret

    Returns:
        Access Token 字串

    Raises:
        requests.HTTPError: 認證失敗時
    """
    token_url = (
        'https://tdx.transportdata.tw/auth/realms/TDXConnect'
        '/protocol/openid-connect/token'
    )
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    data = {
        'grant_type':    'client_credentials',
        'client_id':     app_id,
        'client_secret': app_key,
    }
    response = requests.post(token_url, headers=headers, data=data, timeout=10)
    if response.status_code != 200:
        raise RuntimeError(
            f'TDX 認證失敗 (HTTP {response.status_code}): {response.text}\n'
            f'  app_id={app_id!r}  (長度={len(app_id)})\n'
            f'  app_key 長度={len(app_key)}'
        )
    return response.json()['access_token']


# ----------------------------------------------------------------------------
# 高鐵 OD 時刻表 API (原始呼叫)
# ----------------------------------------------------------------------------

def _fetch_thsr_timetable_raw(
    token: str,
    origin_id: str,
    destination_id: str,
    train_date: str,
) -> list:
    """
    呼叫 TDX 高鐵 OD 時刻表 API，回傳原始 JSON list。

    API:  GET /v2/Rail/THSR/DailyTimetable/OD/{origin}/to/{dest}/{date}

    Args:
        token:          Access Token
        origin_id:      起站 StationID (e.g. '1000')
        destination_id: 迄站 StationID (e.g. '1040')
        train_date:     查詢日期 YYYY-MM-DD

    Returns:
        list of train dicts (TDX 原始格式)

    Raises:
        RuntimeError: API 呼叫失敗
    """
    base_url = 'https://tdx.transportdata.tw/api/basic'
    url = (
        f'{base_url}/v2/Rail/THSR/DailyTimetable'
        f'/OD/{origin_id}/to/{destination_id}/{train_date}'
        f'?$format=JSON'
    )
    headers = {
        'authorization':   f'Bearer {token}',
        'Accept-Encoding': 'gzip',
    }
    response = requests.get(url, headers=headers, timeout=15)
    if response.status_code != 200:
        raise RuntimeError(
            f'TDX API 呼叫失敗 (HTTP {response.status_code}): {response.text}'
        )
    data = response.json()
    return data if isinstance(data, list) else []


# ----------------------------------------------------------------------------
# 主要公開函式
# ----------------------------------------------------------------------------

def get_thsr_timetable_od(
    app_id: str,
    app_key: str,
    origin_id: str,
    destination_id: str,
    train_date: str,
) -> List[dict]:
    """
    查詢指定日期、起迄站間的高鐵時刻表，回傳整理後的車次清單。

    Args:
        app_id:           TDX Client ID
        app_key:          TDX Client Secret
        origin_id:        起站 StationID (e.g. '1000')
        destination_id:   迄站 StationID (e.g. '1040')
        train_date:       查詢日期 'YYYY-MM-DD'

    Returns:
        list of dict，每筆格式:
        {
            'train_no':     '0205',        # 車次
            'dep_time':     '07:51',       # 出發時間 HH:MM
            'arr_time':     '08:38',       # 到達時間 HH:MM
        }
        依出發時間升序排列。

    Raises:
        RuntimeError: Token 取得或 API 呼叫失敗
    """
    token = get_access_token(app_id, app_key)
    raw_trains = _fetch_thsr_timetable_raw(token, origin_id, destination_id, train_date)

    result = []
    for train in raw_trains:
        info       = train.get('DailyTrainInfo', {})
        train_no   = info.get('TrainNo', '')
        dep_time   = train.get('OriginStopTime', {}).get('DepartureTime', '')
        arr_time   = train.get('DestinationStopTime', {}).get('ArrivalTime', '')
  
        if not train_no or not dep_time or not arr_time:
            continue

        result.append({
            'train_no':     train_no,
            'dep_time':     dep_time,
            'arr_time':     arr_time,
        })

    # 依出發時間排序
    # result.sort(key=lambda x: x['dep_time'])
    return result


def get_thsr_timetable_od_by_name(
    app_id: str,
    app_key: str,
    origin_name: str,
    destination_name: str,
    train_date: str,
) -> List[dict]:
    """
    同 get_thsr_timetable_od，但使用站名（中文）查詢。

    Args:
        origin_name:      起站名稱 (e.g. '台北')
        destination_name: 迄站名稱 (e.g. '台中')
        其餘同上

    Raises:
        ValueError: 站名不在 STATION_ID_MAP 中
        RuntimeError: API 呼叫失敗
    """
    origin_id = STATION_ID_MAP.get(origin_name)
    dest_id   = STATION_ID_MAP.get(destination_name)

    if origin_id is None:
        raise ValueError(f'未知起站名稱: {origin_name}')
    if dest_id is None:
        raise ValueError(f'未知迄站名稱: {destination_name}')

    return get_thsr_timetable_od(app_id, app_key, origin_id, dest_id, train_date)