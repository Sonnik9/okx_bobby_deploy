from typing import List, Optional, Callable
from b_context import BotContext
from c_log import ErrorHandler


class PositionVarsSetup:
    def __init__(self, context: BotContext, info_handler: ErrorHandler, parse_precision: Callable):   
        self.context = context
        info_handler.wrap_foreign_methods(self)
        self.info_handler = info_handler
        self.parse_precision = parse_precision
    
    @staticmethod
    def pos_vars_root_template():
        """Базовый шаблон переменных позиции"""
        return {  
            "leverage": None,
            "margin_vol": None,
            "vol_usdt": None,   
            "vol_assets": None,
            "entry_price": None,  
            "pending_open": False,    
            "in_position": False, 
            "order_id": None,
            "c_time": None
        }
            
    def set_pos_defaults(
            self,
            symbol: str,
            pos_side: str,
            instruments_data: List = None,
            reset_flag: bool = False
        ):
        """Безопасная инициализация структуры данных контроля позиций."""

        # Убедимся, что pos_side существует в данных символа
        if symbol not in self.context.position_vars:
            self.context.position_vars[symbol] = {}
        specs = None
        if instruments_data and "spec" not in self.context.position_vars[symbol]:
            try:
                specs: Optional[dict] = self.parse_precision(
                    data=instruments_data,
                    symbol=symbol
                )
                if not specs or not all(v is not None for v in specs.values()):                    
                    print(f"Нет нужных инструментов для монеты {symbol}. Возможно токен недоступен для торговли.")
                    return False
                
            except Exception as e:
                print(f"⚠️ [ERROR] при получении инструментов для {symbol}: {e}")
                return False            
            
            self.context.position_vars[symbol]["spec"] = specs
        if pos_side not in self.context.position_vars[symbol] or reset_flag:
            self.context.position_vars[symbol][pos_side] = self.pos_vars_root_template()

        return True