import asyncio
from aiogram import Bot
import asyncio, random
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramRetryAfter,
    TelegramForbiddenError,
    TelegramNetworkError
)
from a_config import *
from b_context import BotContext
from c_log import ErrorHandler
from c_utils import milliseconds_to_datetime, to_human_digit
from typing import *
import random
import traceback


# === Утилита для форматирования сообщений ===
class MessageFormatter:
    def __init__(self, context: BotContext, info_handler: ErrorHandler):
        self.context = context
        self.info_handler = info_handler

    # // utils method:
    def format_message(
        self,
        chat_id: str,
        marker: str,
        body: dict,
        is_print: bool = True
    ) -> None:
        """
        Универсальный логгер с маркером категории и телом сообщения.
        :param marker: тип сообщения (signal, limit_order_sent, limit_order_failed,
                    market_order_filled, market_order_failed, report)
        :param body: основной контент (dict/list/str)
        :param is_print: вывод в консоль
        """

        msg = ""

        try:
            head = f"{HEAD_LINE_TYPE}" * HEAD_WIDTH

            symbol = body.get("symbol")
            if symbol:
                symbol = symbol.replace("-USDT-SWAP", "")

            pos_side = body.get("pos_side")
            cur_time = milliseconds_to_datetime(body.get("cur_time"))
            reason = body.get("reason")
            
            # --- Формирование сообщений по маркеру ---
            if marker == "signal":
                leverage = body.get("leverage")
                entry_price = to_human_digit(body.get("entry_price"))
                tp = to_human_digit(body.get("tp"))
                sl = to_human_digit(body.get("sl"))

                msg = (
                    f"{head}\n"
                    f"SIGNAL RECEIVED [{symbol}]\n\n"
                    f"[{cur_time}]\n\n"
                    f"{pos_side}\n"
                    f"LEVERAGE - {leverage}\n"
                    f"ENTRY - {entry_price}\n"
                    f"TP - {tp}\n"
                    f"SL - {sl}\n"
                )

            elif marker in {"limit_order_sent", "market_order_sent"}:
                msg = (
                    f"{head}\n\n"
                    f"[{symbol}] MARKET ORDER SENT\n"
                    f"{pos_side}\n"
                    f"[{cur_time}]\n"
                )

            elif marker == "limit_order_failed":
                msg = (
                    f"{head}\n\n"                                  
                    f"{EMO_LOSE} MARKET ORDER FAILED\n"
                    f"[{cur_time}]\n"
                    f"[{symbol}] | {pos_side}\n"
                    f"REASON - {reason}\n"
                )

            elif marker == "market_order_filled":
                vol_usdt = body.get("vol_usdt")
                margin_vol = body.get("margin_vol")
                vol_assets = to_human_digit(body.get("vol_assets"))
                msg = (
                    f"{head}\n\n"                    
                    f"{EMO_ORDER_FILLED} MARKET ORDER FILLED\n"
                    f"[{cur_time}]\n"
                    f"[{symbol}] | {pos_side}\n" 
                    f"VOL_USDT - {vol_usdt}\n"
                    f"MARGIN_VOL - {margin_vol}\n"
                    f"VOL_ASSETS - {vol_assets}\n"
                )

            elif marker == "market_order_failed":
                msg = (
                    f"{head}\n\n"                                  
                    f"{EMO_LOSE} MARKET ORDER FAILED\n"
                    f"[{cur_time}]\n"
                    f"[{symbol}] | {pos_side}\n"    
                    f"REASON - {reason}\n"
                )

            elif marker == "report":
                pnl_pct = body.get("pnl_pct")
                pnl_usdt = body.get("pnl_usdt")
                time_in_deal = body.get("time_in_deal", "N/A")

                # --- Формируем эмодзи и форматируем pnl ---
                emo = "N/A"
                pnl_usdt_str = "N/A"
                if pnl_usdt is not None:
                    if pnl_pct is not None:                    
                        if pnl_pct > 0:
                            emo = f"{EMO_SUCCESS} SUCCESS"
                            pnl_usdt_str = f"+ {pnl_usdt:.2f}"
                        elif pnl_pct < 0:
                            emo = f"{EMO_LOSE} LOSE"
                            pnl_usdt_str = f"- {abs(pnl_usdt):.2f}"
                        else:
                            emo = f"{EMO_ZERO} 0 P&L"
                            pnl_usdt_str = f"{pnl_usdt:.4f}"
                    else:
                        # Если pnl_usdt = None, только эмодзи
                        if pnl_pct > 0:
                            emo = f"{EMO_SUCCESS} SUCCESS"
                        elif pnl_pct < 0:
                            emo = f"{EMO_LOSE} LOSE"
                        else:
                            emo = f"{EMO_ZERO} 0 P&L"

                msg = (
                    f"{head}\n\n"
                    f"[{symbol}] | {pos_side} | {emo}\n"
                    f"PNL {pnl_pct:.2f}% | PNL {pnl_usdt_str} USDT\n"
                    f"CLOSING TIME - [{cur_time}]\n"                    
                    f"TIME IN DEAL - {time_in_deal}\n"
                )

            else:
                print(f"Неизвестный тип сообщения в format_message. Marker: {marker}")

            self.context.queues_msg[chat_id].append(msg)
            if is_print:
                print(msg)

        except Exception as e:
            err_msg = f"[ERROR] preform_message: {e}\n"
            err_msg += traceback.format_exc()
            self.info_handler.debug_error_notes(err_msg, is_print=True)


# === Основной TelegramNotifier ===
class TelegramNotifier(MessageFormatter):
    def __init__(self, bot: Bot, context: BotContext, info_handler: ErrorHandler):
        super().__init__(context, info_handler)
        self.bot = bot

    async def send_report_batches(self, chat_id: int, batch_size: int = 1):
        queue = self.context.queues_msg[chat_id]
        while queue:
            batch = queue[:batch_size]
            text_block = "\n\n".join(batch)
            await self._send_message(chat_id, text_block)
            del queue[:len(batch)]
            await asyncio.sleep(0.25)

    async def _send_message(self, chat_id: int, text: str):
        while not self.context.stop_bot and not self.context.stop_bot_iteration:
            try:
                msg = await self.bot.send_message(chat_id, text, parse_mode="HTML")
                return msg
            except TelegramNetworkError as e:
                wait = random.uniform(1, 3)
                self.info_handler.debug_error_notes(
                    f"[TG SEND][{chat_id}] Network error: {e}. Retrying in {wait:.1f}s", is_print=True
                )
                await asyncio.sleep(wait)
            except TelegramRetryAfter as e:
                wait = int(getattr(e, "retry_after", 5))
                self.info_handler.debug_error_notes(
                    f"[TG SEND][{chat_id}] Rate limit. Waiting {wait}s", is_print=True
                )
                await asyncio.sleep(wait)
            except TelegramForbiddenError:
                self.info_handler.debug_error_notes(
                    f"[TG SEND][{chat_id}] Bot is blocked by user. Stopping sending.", is_print=True
                )
                return None
            except TelegramAPIError as e:
                self.info_handler.debug_error_notes(
                    f"[TG SEND][{chat_id}] API error: {e}. Exit loop.", is_print=True
                )
                return None
            except Exception as e:
                self.info_handler.debug_error_notes(
                    f"[TG SEND][{chat_id}] Unexpected error: {e}. Exit loop.", is_print=True
                )
                return None