from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
from a_config import SLIPPAGE_PCT, PRECISION
from c_log import ErrorHandler, TZ_LOCATION
import math
from decimal import Decimal, getcontext
import time


getcontext().prec = 28  # точность Decimal

def fix_price_scale(price: float, cur_price: float) -> float:
    """
    Универсальная поправка масштаба: ищем ближайшую степень 10,
    которая приближает цену к рыночной.
    """
    if not price or not cur_price or price <= 0 or cur_price <= 0:
        return price

    price_d = Decimal(price)
    cur_price_d = Decimal(cur_price)
    ratio = cur_price_d / price_d

    # Вычисляем оптимальную степень 10
    multiplier = Decimal(10) ** Decimal(round(math.log10(float(ratio))))

    # Слишком малая цена — увеличиваем
    if multiplier >= 10:
        return float(price_d * multiplier)
    # Слишком большая цена — уменьшаем
    elif multiplier <= Decimal("0.1"):
        return float(price_d * multiplier)
    return float(price_d)

def format_duration(ms: int) -> str:
    """
    Конвертирует миллисекундную разницу в формат "Xh Ym" или "Xm" или "Xs".
    :param ms: длительность в миллисекундах
    """
    if ms is None:
        return ""
    
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0 and minutes > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0 and seconds > 0:
        return f"{minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m"
    else:
        return f"{seconds}s"
    
def apply_slippage(price: float, slippage_pct: float, pos_side: str) -> float:
    """
    Корректирует цену закрытия с учётом проскальзывания.
    
    price: float - цена закрытия/текущая
    slippage_pct: float - проскальзывание в процентах (например 0.1 для 0.1%)
    pos_side: 'LONG' или 'SHORT'
    """
    if not (price and slippage_pct and pos_side):
        return price
    sign = 1 if pos_side.upper() == "LONG" else -1
    return price * (1 - sign * slippage_pct / 100)

def milliseconds_to_datetime(milliseconds):
    if milliseconds is None:
        return "N/A"
    try:
        ms = int(milliseconds)   # <-- приведение к int
        if milliseconds < 0: return "N/A"
    except (ValueError, TypeError):
        return "N/A"

    if ms > 1e10:  # похоже на миллисекунды
        seconds = ms / 1000
    else:
        seconds = ms

    dt = datetime.fromtimestamp(seconds, TZ_LOCATION)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def to_human_digit(value):
    if value is None:
        return "N/A"
    getcontext().prec = PRECISION
    dec_value = Decimal(str(value)).normalize()
    if dec_value == dec_value.to_integral():
        return format(dec_value, 'f')
    else:
        return format(dec_value, 'f').rstrip('0').rstrip('.')  


class Utils:
    def __init__(
            self,
            info_handler: ErrorHandler,
        ):    
        info_handler.wrap_foreign_methods(self)
        self.info_handler = info_handler   

    @staticmethod
    def parse_precision(data: List[Dict[str, Any]], symbol: str) -> Optional[Dict[str, Any]]:
        for info in data:
            if info.get("instId") == symbol:
                # print(f"spec: {info}")
                def count_precision(value_str: str) -> int:
                    return len(value_str.split(".")[1]) if "." in value_str else 0

                ctVal_str = str(info.get("ctVal", "1"))
                lot_sz_str = str(info.get("lotSz", "1"))
                tick_sz_str = str(info.get("tickSz", "1"))

                # пробуем взять плечо
                max_leverage = (
                    info.get("lever") or
                    info.get("maxLeverage") or
                    info.get("leverUp")  # иногда в разных режимах так называется
                )

                return {
                    "ctVal": float(ctVal_str),
                    "lotSz": float(lot_sz_str),
                    "contract_precision": count_precision(lot_sz_str),
                    "price_precision": count_precision(tick_sz_str),
                    "max_leverage": int(max_leverage) if max_leverage else None
                }
        return None

    def contract_calc(
        self,
        margin_size: float,
        entry_price: float,
        leverage: float,
        ctVal: float,
        lotSz: float,
        contract_precision: int,
        volume_rate: float = 100,
        debug_label: str = None
    ) -> Optional[float]:
        if any(not isinstance(x, (int, float)) for x in [margin_size, entry_price, leverage, lotSz]):
            self.info_handler.debug_error_notes(f"{debug_label}: Invalid input parameters in contract_calc", is_print=True)
            return None

        try:
            deal_amount = margin_size * volume_rate / 100
            base_qty = (deal_amount * leverage) / entry_price
            raw_contracts = base_qty / ctVal
            rounded_steps = round(raw_contracts / lotSz) * lotSz
            contracts = round(rounded_steps, contract_precision)
            return contracts
        except Exception as e:
            self.info_handler.debug_error_notes(f"{debug_label}: Error in contract_calc: {e}", is_print=True)
            return None

    async def pnl_report(
            self,
            symbol: str,
            pos_side: str,
            pos_data: dict,
            get_current_price: Callable,
            format_message=Callable,
            chat_id=str
        ):
        label = f"{symbol}_{pos_side}"
        cur_price = await get_current_price(symbol)
        if cur_price is None:
            print(f"[REPORT][ERROR][{label}]: cur_price is None")
            return

        # sign = 1 для LONG, -1 для SHORT
        sign = {"LONG": 1, "SHORT": -1}.get(pos_side.upper())
        if sign is None:
            print(f"[REPORT][ERROR][{label}]:sign is None")
            return  

        entry_price = pos_data.get("entry_price")        
        if not entry_price:
            print(f"[REPORT][ERROR][{label}]:not entry_price or invest_usd")
            return

        # Корректируем цену с учётом проскальзывания
        cur_price_with_slippage = apply_slippage(
            price=cur_price,
            slippage_pct=SLIPPAGE_PCT,
            pos_side=pos_side
        )

        # % PnL
        pnl_pct = (cur_price_with_slippage - entry_price) / entry_price * 100 * sign

        # $ PnL
        qty = pos_data.get("vol_assets")  # кол-во монет в позиции
        pnl_usdt = qty * (cur_price_with_slippage - entry_price) * sign
        # ///

        time_in_deal = None
        cur_time = int(time.time() * 1000)
        if pos_data.get("c_time"):
            time_in_deal = cur_time - pos_data.get("c_time")

        leverage = pos_data.get("leverage", 1)

        body = {
            "symbol": symbol,
            "pos_side": pos_side,
            "pnl_pct": pnl_pct * leverage,
            "pnl_usdt": pnl_usdt,
            "cur_time": cur_time,
            "time_in_deal": format_duration(time_in_deal)
        }

        format_message(
            chat_id=chat_id,
            marker="report",
            body=body,
            is_print=True
        )