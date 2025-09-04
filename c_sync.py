import aiohttp
import asyncio
from typing import Callable, Dict, List, Set
from b_context import BotContext
from c_log import ErrorHandler
from API.OKX.okx import OkxFuturesClient


class PositionCleaner():
    def __init__(
        self,
        context: BotContext,
        info_handler: ErrorHandler,
        set_pos_defaults: Callable,
        pnl_report: Callable,
        okx_client: OkxFuturesClient,
        format_message: Callable,
        chat_id: str
    ):
        self.context = context
        info_handler.wrap_foreign_methods(self)
        self.info_handler = info_handler 
        self.set_pos_defaults = set_pos_defaults
        self.okx_client = okx_client
        self.pnl_report = pnl_report
        self.format_message = format_message
        self.chat_id = chat_id

    def reset_position_vars(
            self,
            symbol: str,
            pos_side: str                  
        ):
        self.set_pos_defaults(
            symbol=symbol,
            pos_side=pos_side,
            instruments_data=None,
            reset_flag=True
        )

    async def reset_if_needed(
            self,
            pos_data: dict,
            symbol: str,
            pos_side: str
        ):
        if bool(pos_data.get("in_position", False)):
            await self.pnl_report(
                symbol=symbol,
                pos_side=pos_side,
                pos_data=pos_data,
                get_current_price=self.okx_client.get_current_price,
                format_message=self.format_message,
                chat_id=self.chat_id
            )                    
            self.reset_position_vars(symbol, pos_side)
            

class Synchronizer(PositionCleaner):
    def __init__(
        self,
        context: BotContext,
        info_handler: ErrorHandler,
        set_pos_defaults: Callable,
        pnl_report: Callable,
        okx_client: OkxFuturesClient,
        format_message: Callable,
        positions_update_frequency: float,
        chat_id: str
    ):
        super().__init__(context, info_handler, set_pos_defaults, pnl_report, okx_client, format_message, chat_id)       
        info_handler.wrap_foreign_methods(self)
  
        self.positions_update_frequency = positions_update_frequency
        self._first_update_done = False

    @staticmethod
    def unpack_position_info(position: dict) -> dict:
        """
        Распаковывает позицию OKX SWAP/FUTURES из формата API OKX.
        Возвращает словарь с:
        - symbol (str): 'instId'
        - pos_side (str): 'LONG' или 'SHORT' (в зависимости от posSide)
        - contracts (float): количество контрактов (pos), абсолютное значение
        - entry_price (float): средняя цена позиции (avgPx)
        Если данных нет, возвращает значения по умолчанию.
        """
        if not isinstance(position, dict):
            return {
                "c_time": None,
                "symbol": "N/A",
                "pos_side": "N/A",
                "contracts": 0.0,
                "entry_price": None,
                "trade_id": None,
                # "margin": None,
                "notional_usd": None,
                "leverage": None
            }

        symbol = position.get("instId", "N/A").upper()
        pos_side = position.get("posSide", "N/A").upper()
        trade_id = position.get("tradeId", "N/A")
        # margin = abs(float(position.get("margin", 0.0)))
        notional_usd = abs(float(position.get("notionalUsd", 0.0)))
        contracts = abs(float(position.get("pos", 0.0)))  # абсолютное значение контрактов
        entry_price = float(position.get("avgPx", 0.0))
        leverage = abs(int(position.get("lever", 1)))
        c_time = int(position.get("cTime", None))

        return {
            "symbol": symbol,
            "pos_side": pos_side,
            "contracts": contracts,
            "entry_price": entry_price,
            "trade_id": trade_id,
            # "margin": margin,
            "notional_usd": notional_usd,
            "leverage": leverage,
            "c_time": c_time
        }    

    def update_active_position(
            self,
            symbol: str,
            symbol_data: dict,
            pos_side: str,
            info: dict,
        ):
        ctVal_str = symbol_data["spec"]["ctVal"]
        try:
            ctVal = float(ctVal_str)
        except (ValueError, TypeError):
            ctVal = 1.0  # запасной вариант

        entry_price = info.get("entry_price")
        contracts = info.get("contracts")
        trade_id = info.get("trade_id")
        leverage = info.get("leverage")
        vol_usdt = info.get("notional_usd")

        pos_data = symbol_data[pos_side]
        margin_vol = pos_data.get("margin_vol")
        vol_assets = contracts * ctVal

        # cur_time = int(time.time() * 1000)
        cur_time = info.get("c_time")

        if not pos_data.get("in_position"):      
            body = {
                "symbol": symbol,
                "pos_side": pos_side,
                "cur_time": cur_time,
                "margin_vol": round(margin_vol, 2),
                "vol_usdt": round(vol_usdt, 2),
                "vol_assets": vol_assets,
            }

            self.format_message(
                chat_id=self.chat_id,
                marker="market_order_filled",
                body=body,
                is_print=True
            )

        pos_data.update({
            "c_time": cur_time,
            "trade_id": trade_id,
            "entry_price": entry_price,
            "in_position": True,
            "margin_vol": margin_vol,
            "vol_usdt": vol_usdt,
            "vol_assets": vol_assets,
            "leverage": leverage
        })

    async def update_positions(
        self,  
        target_symbols: Set[str],
        positions: List[Dict],
    ) -> None:
        """
        Обновляет данные о позициях для указанной стратегии и символов.
        """
        try:
            # --- Словарь актуальных позиций по символу+стороне ---
            active_positions = {}
            for position in positions:
                if not position:
                    continue
                inst_id = position.get("instId", "").upper()
                if inst_id in target_symbols:
                    info = self.unpack_position_info(position)
                    if isinstance(info, dict):
                        active_positions[(info["symbol"], info["pos_side"])] = info

            # --- Сначала сброс: пройтись по локальным данным и убрать те позиции, которых нет в active_positions ---
            for symbol in target_symbols:
                symbol_data = self.context.position_vars.get(symbol, {})
                for pos_side in ("LONG", "SHORT"):
                    pos_data = symbol_data.get(pos_side, {})
                    if not pos_data:
                        continue
                    if (symbol, pos_side) not in active_positions:
                        # на бирже нет позиции → сбрасываем локальную
                        await self.reset_if_needed(
                            pos_data=pos_data,
                            symbol=symbol,
                            pos_side=pos_side
                        )

            # --- Теперь обновление / установка активных позиций ---
            for (symbol, pos_side), info in active_positions.items():
                contracts = info.get("contracts", 0.0)
                symbol_data = self.context.position_vars.get(symbol, {})
                pos_data = symbol_data.get(pos_side, {})
                if not pos_data:
                    continue

                if isinstance(contracts, (float, int)) and contracts > 0:
                    self.update_active_position(
                        symbol=symbol,
                        symbol_data=symbol_data,
                        pos_side=pos_side,
                        info=info
                    )
                else:
                    await self.reset_if_needed(
                        pos_data=pos_data,
                        symbol=symbol,
                        pos_side=pos_side
                    )

        except KeyError as e:
            self.info_handler.debug_error_notes(
                f"[KeyError]: {e}"
            )
        except Exception as e:
            self.info_handler.debug_error_notes(
                f"[Unexpected Error]: {e}"
            )

        finally:
            if not self._first_update_done:
                self._first_update_done = True
                self.info_handler.debug_info_notes("[update_positions] First update done, flag set")

    async def refresh_positions_state(
        self
    ) -> None:
        """
        Обновляет состояние позиций для всех стратегий пользователя.
        """
        try:
            symbols_set = set(self.context.position_vars.keys())
            if not symbols_set:
                # print("not symbols_set")
                return
            
            if not self.context.session or self.context.session.closed:
                return
            
            positions = (await self.okx_client.fetch_positions(session=self.context.session) or {})

            if positions is None:
                self.info_handler.debug_error_notes(
                    f"No 'data' field in positions response."
                )
                return

            await self.update_positions(
                symbols_set,
                positions
            )
        
        except aiohttp.ClientError as e:
            self.info_handler.debug_error_notes(
                f"[HTTP Error] Failed to fetch positions: {e}."
            )
        except Exception as e:
            self.info_handler.debug_error_notes(
                f"[Unexpected Error] Failed to refresh positions: {e}."
            )
            
    async def refresh_positions_task(self) -> None:
        while not self.context.stop_bot and not self.context.stop_bot_iteration:
            await self.refresh_positions_state()
            await asyncio.sleep(self.positions_update_frequency)