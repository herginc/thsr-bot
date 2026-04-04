# =============================================================================
# booking_schedule.py — 訂票頻率排程模組
# =============================================================================
#
# 功能：
#   根據 booking_schedule.yaml 的設定，在每次訂票嘗試前計算應等待的秒數，
#   並判斷是否應停止訂票。
#
# 使用方式（在 app.py 的 run_booking_worker 重試迴圈中）：
#
#   from booking_schedule import BookingScheduler
#
#   scheduler = BookingScheduler()           # 啟動時載入一次即可（或每次重試前 reload）
#
#   # 判斷是否應停止
#   if scheduler.should_stop(train_departure_dt):
#       break  # 距出發時間太近，停止搶票
#
#   # 取得本輪應等待的秒數
#   delay = scheduler.get_delay_seconds(train_departure_dt)
#   if delay > 0:
#       time.sleep(delay)
#
# =============================================================================

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from config import *

try:
    import yaml
except ImportError:
    yaml = None  # 若未安裝 PyYAML，退回預設值模式

logger = logging.getLogger(__name__)

# 台灣時區 CST (UTC+8)
CST_TIMEZONE = timezone(timedelta(hours=8))

# 配置檔路徑（與本模組同目錄）
DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "booking_schedule.yaml")

# -----------------------------------------------------------------------------
# 內建預設值（當 yaml 無法載入時使用）
# -----------------------------------------------------------------------------
_DEFAULT_CONFIG = {
    "stop_before_departure_minutes": 5,
    "night_boost_window": {
        "enabled": True,
        "start_time": "01:30",
        "end_time": "02:30",
        "delay_seconds": 0,
    },
    "departure_near": {
        "near_threshold_minutes": 120,
        "delay_seconds": 0,
    },
    "departure_far": {
        "delay_seconds": 60,
    },
}


# =============================================================================
# BookingScheduler
# =============================================================================

class BookingScheduler:
    """
    根據 booking_schedule.yaml 決定每次訂票嘗試的等待秒數與停止條件。

    優先順序：
      1. stop_before_departure  — 出發前 N 分鐘內 → 停止
      2. night_boost_window     — 凌晨特殊時段    → delay = 0（全速）
      3. departure_near         — 距出發 ≤ 2 小時  → delay = 0（全速）
      4. departure_far          — 其餘情況         → delay = 60 秒
    """

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self._cfg = self._load_config()

    # -------------------------------------------------------------------------
    # 公開 API
    # -------------------------------------------------------------------------

    def reload(self):
        """重新從磁碟讀取配置（熱更新用）。"""
        self._cfg = self._load_config()
        logger.info("[BookingScheduler] 配置已重新載入")

    def should_stop(self, departure_dt: Optional[datetime]) -> bool:
        """
        判斷是否應停止訂票嘗試。

        Args:
            departure_dt: 班次出發的 datetime（需含時區資訊）。
                          為 None 時（解析失敗），保守回傳 False（繼續嘗試）。

        Returns:
            True  → 停止（距出發時間太近）
            False → 繼續嘗試
        """
        if departure_dt is None:
            logger.warning("[BookingScheduler] should_stop: departure_dt 為 None，跳過停止判斷")
            return False

        minutes_left = self._minutes_until_departure(departure_dt)
        stop_threshold = self._cfg.get("stop_before_departure_minutes", 5)

        if minutes_left <= stop_threshold:
            logger.info(
                YELLOW +
                f"[BookingScheduler] 出發時間={departure_dt.strftime('%Y/%m/%d %H:%M')} "
                f"距出發剩餘 {minutes_left:.1f} 分鐘 "
                f"≤ 停止門檻 {stop_threshold} 分鐘 → 停止訂票"
                + RESET
            )
            return True
        return False

    def get_delay_seconds(self, departure_dt: Optional[datetime]) -> int:
        """
        計算本輪訂票前應等待的秒數。

        Args:
            departure_dt: 班次出發的 datetime（需含時區資訊）。
                          為 None 時（解析失敗），回傳遠程預設 delay。

        Returns:
            等待秒數（0 = 不等待，立即嘗試）
        """
        now = datetime.now(CST_TIMEZONE)

        # --- 規則 2: 凌晨高速搶票時段（不依賴 departure_dt）---
        night = self._cfg.get("night_boost_window", {})
        if night.get("enabled", False) and self._in_night_window(now, night):
            delay = int(night.get("delay_seconds", 0))
            logger.info(
                f"[BookingScheduler] 凌晨搶票時段 "
                f"({night['start_time']}–{night['end_time']}) → delay={delay}s"
            )
            return delay

        if departure_dt is None:
            far_cfg = self._cfg.get("departure_far", {})
            delay = int(far_cfg.get("delay_seconds", 60))
            logger.warning(
                f"[BookingScheduler] get_delay_seconds: departure_dt 為 None，"
                f"使用遠程預設 delay={delay}s"
            )
            return delay

        minutes_left = self._minutes_until_departure(departure_dt)

        # --- 規則 3: 距出發 ≤ near_threshold ---
        near_cfg = self._cfg.get("departure_near", {})
        near_threshold = near_cfg.get("near_threshold_minutes", 120)
        if minutes_left <= near_threshold:
            delay = int(near_cfg.get("delay_seconds", 0))
            logger.info(
                f"[BookingScheduler] 出發時間={departure_dt.strftime('%Y/%m/%d %H:%M')} "
                f"距出發 {minutes_left:.1f} 分鐘 "
                f"≤ {near_threshold} 分鐘（近程規則）→ delay={delay}s"
            )
            return delay

        # --- 規則 4: 距出發 > near_threshold（一般規則）---
        far_cfg = self._cfg.get("departure_far", {})
        delay = int(far_cfg.get("delay_seconds", 60))
        logger.info(
            f"[BookingScheduler] 出發時間={departure_dt.strftime('%Y/%m/%d %H:%M')} "
            f"距出發 {minutes_left:.1f} 分鐘 "
            f"> {near_threshold} 分鐘（遠程規則）→ delay={delay}s"
        )
        return delay

    def describe(self, departure_dt: Optional[datetime]) -> str:
        """回傳本輪排程決策的說明文字（供 log / UI 顯示）。"""
        if departure_dt is None:
            far_delay = int(self._cfg.get("departure_far", {}).get("delay_seconds", 60))
            return f"出發時間未知，使用預設間隔 {far_delay} 秒"
        if self.should_stop(departure_dt):
            return "已停止訂票（距出發時間太近）"
        delay = self.get_delay_seconds(departure_dt)
        if delay == 0:
            return "全速搶票（無等待）"
        return f"每次訂票間隔 {delay} 秒"

    # -------------------------------------------------------------------------
    # 內部輔助方法
    # -------------------------------------------------------------------------

    def _load_config(self) -> dict:
        """載入 YAML 配置；失敗時回傳內建預設值。"""
        if yaml is None:
            logger.warning("[BookingScheduler] PyYAML 未安裝，使用內建預設值")
            return _DEFAULT_CONFIG.copy()

        if not os.path.exists(self.config_path):
            logger.warning(
                f"[BookingScheduler] 找不到配置檔 {self.config_path}，使用內建預設值"
            )
            return _DEFAULT_CONFIG.copy()

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            logger.info(f"[BookingScheduler] 配置載入成功：{self.config_path}")
            return cfg or _DEFAULT_CONFIG.copy()
        except Exception as e:
            logger.error(f"[BookingScheduler] 配置載入失敗：{e}，使用內建預設值")
            return _DEFAULT_CONFIG.copy()

    @staticmethod
    def _minutes_until_departure(departure_dt: datetime) -> float:
        """計算距出發時間剩餘分鐘數（可為負數，表示已過站）。"""
        now = datetime.now(CST_TIMEZONE)
        # 確保 departure_dt 有時區資訊
        if departure_dt.tzinfo is None:
            departure_dt = departure_dt.replace(tzinfo=CST_TIMEZONE)
        delta = departure_dt - now
        return delta.total_seconds() / 60.0

    @staticmethod
    def _in_night_window(now: datetime, night_cfg: dict) -> bool:
        """判斷 now 是否在凌晨高速時段內。"""
        try:
            start_h, start_m = map(int, night_cfg["start_time"].split(":"))
            end_h,   end_m   = map(int, night_cfg["end_time"].split(":"))
        except (KeyError, ValueError):
            return False

        start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end   = now.replace(hour=end_h,   minute=end_m,   second=0, microsecond=0)

        # 跨午夜處理（例：23:00–01:00）
        if start <= end:
            return start <= now < end
        else:
            return now >= start or now < end


# =============================================================================
# 便利函式：解析 task_data 中的出發 datetime
# =============================================================================

def parse_departure_dt(task_data: dict) -> Optional[datetime]:
    """
    從 task_data 解析出完整的出發 datetime。

    欄位優先順序（高→低）：
        1. dep_time   — 前端從 TDX 時刻表帶來的精確出發時間（HH:MM），最準確
        2. train_time — 使用者在時間模式下手動選擇的時間（HH:MM）
        3. 以上皆空   — fallback 到 'YYYY/MM/DD 23:59'（保守估計，維持系統可運作）

    task_data 預期包含：
        travel_date : 'YYYY/MM/DD' 或 'YYYY-MM-DD'
        dep_time    : 'HH:MM'（radio33 模式，由前端從 TDX 資料填入，最優先）
        train_time  : 'HH:MM'（時間模式）
        train_no    : '車次號碼'（僅供 log 顯示用）

    Returns:
        datetime（含 CST 時區）；travel_date 無效時回傳 None。
    """
    try:
        raw_date   = task_data.get("travel_date", "").replace("-", "/").strip()
        dep_time   = (task_data.get("dep_time")   or "").strip()
        train_time = (task_data.get("train_time") or "").strip()
        train_no   = (task_data.get("train_no")   or "").strip()

        if not raw_date:
            logger.warning("[parse_departure_dt] travel_date 為空，無法解析出發時間")
            return None

        if dep_time:
            resolved_time = dep_time
            source = f"dep_time（TDX 精確時間，train_no={train_no or 'N/A'}）"
        elif train_time:
            resolved_time = train_time
            source = "train_time（使用者選擇）"
        else:
            resolved_time = "23:59"
            source = "fallback 23:59（dep_time 與 train_time 皆為空）"
            logger.warning(
                f"[parse_departure_dt] dep_time 與 train_time 皆為空"
                f"（train_no={train_no or 'N/A'}），使用 fallback 23:59"
            )

        dt_str = f"{raw_date} {resolved_time}"
        dt = datetime.strptime(dt_str, "%Y/%m/%d %H:%M")
        logger.debug(f"[parse_departure_dt] 出發時間解析：{dt_str}（來源：{source}）")
        return dt.replace(tzinfo=CST_TIMEZONE)

    except Exception as e:
        logger.error(f"[parse_departure_dt] 解析出發時間失敗：{e}，task_data={task_data}")
        return None


# =============================================================================
# 模組自測（python booking_schedule.py）
# =============================================================================

if __name__ == "__main__":
    import time

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s][%(levelname)s]: %(message)s"
    )

    scheduler = BookingScheduler()
    now = datetime.now(CST_TIMEZONE)

    test_cases = [
        ("出發前 3 分鐘（應停止）",      now + timedelta(minutes=3)),
        ("出發前 30 分鐘（近程，delay=0）", now + timedelta(minutes=30)),
        ("出發前 90 分鐘（近程，delay=0）", now + timedelta(minutes=90)),
        ("出發前 3 小時（遠程，delay=60）", now + timedelta(hours=3)),
        ("出發前 6 小時（遠程，delay=60）", now + timedelta(hours=6)),
    ]

    print("\n" + "=" * 60)
    print("BookingScheduler 自測結果")
    print("=" * 60)
    for label, dep_dt in test_cases:
        stop   = scheduler.should_stop(dep_dt)
        delay  = scheduler.get_delay_seconds(dep_dt) if not stop else -1
        result = "🛑 停止" if stop else f"✅ delay={delay}s"
        print(f"  [{label}]  →  {result}")
    print("=" * 60)

    # 凌晨時段模擬（強制注入 01:45 的 now）
    print("\n--- 凌晨時段模擬（now=01:45）---")
    night_now = now.replace(hour=1, minute=45, second=0)
    dep_far   = now + timedelta(hours=5)
    in_window = scheduler._in_night_window(night_now, scheduler._cfg.get("night_boost_window", {}))
    print(f"  凌晨 01:45 在夜間時段內: {in_window}")