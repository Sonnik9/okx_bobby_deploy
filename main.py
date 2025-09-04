import asyncio
import time
import aiohttp
from pprint import pprint
from typing import *
from a_config import *
from b_context import BotContext
from b_constructor import PositionVarsSetup
from b_network import NetworkManager
from TG.tg_parser import TgBotWatcherAiogram
from TG.tg_notifier import TelegramNotifier
from TG.tg_buttons import TelegramUserInterface
from API.OKX.okx import OkxFuturesClient, ApiResponseValidator
from aiogram import Bot, Dispatcher

from c_sync import Synchronizer
from c_log import ErrorHandler, log_time
from c_utils import Utils, fix_price_scale, to_human_digit
import traceback
import os

def force_exit(*args):
    print("💥 Принудительное завершение процесса")
    os._exit(1)  # немедленно убивает процесс


class Core:
    def __init__(self):
        self.context = BotContext()
        self.info_handler = ErrorHandler()
        self.bot = Bot(token=TG_BOT_TOKEN)
        self.dp = Dispatcher()
        self.tg_watcher = None
        self.notifier = None
        self.tg_interface = None  # позже инициализируем
        self.positions_task = None
        self.instruments_data = {}

    async def _start_user_context(self, chat_id: int):
        """Инициализация юзер-контекста (сессии, клиентов, стримов и контролов)"""

        user_context = self.context.users_configs[chat_id]
        okx_cfg        = user_context.get("config", {}).get("OKX", {})
        api_key        = okx_cfg.get("api_key")
        api_secret     = okx_cfg.get("api_secret")
        api_passphrase = okx_cfg.get("api_passphrase")

        print("♻️ Пересоздаём user_context сессию")

        # --- Чистим старый connector ---
        if hasattr(self, "connector") and self.connector:
            await self.connector.shutdown_session()
            self.connector = None

        # --- Создаём новый connector ---
        self.connector = NetworkManager(
            context=self.context,
            info_handler=self.info_handler,
        )

        # --- OKX client ---
        self.okx_client = OkxFuturesClient(
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=api_passphrase,
            context=self.context,
            info_handler=self.info_handler
        )

        # --- Вспомогалки ---
        self.utils = Utils(info_handler=self.info_handler)

        self.pos_setup = PositionVarsSetup(
            context=self.context,
            info_handler=self.info_handler,
            parse_precision=self.utils.parse_precision
        )

        self.sync = Synchronizer(
            context=self.context,
            info_handler=self.info_handler,
            set_pos_defaults=self.pos_setup.set_pos_defaults,
            pnl_report=self.utils.pnl_report,
            okx_client=self.okx_client,
            format_message=self.notifier.format_message,
            positions_update_frequency=POSITIONS_UPDATE_FREQUENCY,
            chat_id=chat_id
        )

        # --- Заворачиваем внешние методы в обработчик ошибок ---
        self.info_handler.wrap_foreign_methods(self)

    async def cancel_existing_order(self, session: aiohttp.ClientSession, symbol: str, pos_data: dict) -> None:
        """
        Отменяет текущий алгоритмический ордер, если он существует (order_id).
        После попытки отмены сбрасывает pos_data['order_id'] в None.
        """
        order_id = pos_data.get("order_id", 1)

        try:
            cancel_resp = await self.okx_client.cancel_order(
                session=session,
                instId=symbol,
                ordId=order_id
            )
            self.info_handler.debug_info_notes(
                f"[INFO] Order {order_id} cancelled for {symbol}: {cancel_resp}", is_print=True
            )
        except Exception as e:
            self.info_handler.debug_error_notes(
                f"[ERROR] Failed to cancel order {order_id} for {symbol}: {e}", is_print=True
            )
        finally:
            pos_data["order_id"] = None            
        
    async def complete_until_cancel(
        self,
        session: aiohttp.ClientSession,
        chat_id: str,
        fin_settings: dict,
        symbol: str,
        pos_side: str,
        pos_data: dict,
        last_timestamp: int,
        msg_key: str
    ):
        """
        Ожидает открытия позиции до ORDER_TIMEOUT.
        Если позиция не открыта за это время, логирует таймаут и отменяет ордер.
        """   
        try:     
            self.info_handler.debug_info_notes(f"Запуск ожидания позиции для {symbol}", is_print=True)
            
            # start_time = time.time()
            start_time = last_timestamp / 1000
            while ((time.time() - start_time) < fin_settings.get("order_timeout")) \
                and (not self.context.stop_bot) and not self.context.stop_bot_iteration:
                if pos_data.get("in_position"):
                    break
                await asyncio.sleep(0.1)

            if not pos_data.get("in_position"):
                # Таймаут — позиция так и не открылась
                market_order_failed_body = {
                    "symbol": symbol,
                    "pos_side": pos_side,
                    "reason": "TIME-OUT",
                    "cur_time": int(time.time() * 1000),
                }
                self.notifier.format_message(
                    chat_id=chat_id,
                    marker="market_order_failed",
                    body=market_order_failed_body,
                    is_print=True
                )

        finally:            
            # Очищаем кеш таймингов телеграм
            self.context.tg_timing_cache.discard(msg_key)
            # Отмена ордера, если существует order_id
            await self.cancel_existing_order(
                session=session,
                symbol=symbol,
                pos_data=pos_data
            )

    async def pre_order_template(
        self,
        session: aiohttp.ClientSession,
        chat_id: str,
        fin_settings: dict,
        symbol: str,
        pos_side: str,
        leverage: int,
        symbol_data: dict,
        entry_price:float,
        take_profit: float,
        stop_loss: float,
        debug_label: str,
        market_label: str = "limit"
    ):
        """
        Темплейт под установку плеча, расчёт контрактов и размещение лимитного ордера с TP/SL.
        Имена параметров сохранены без изменений.
        """

        int_margin_mode = fin_settings.get("margin_mode", 1)
        margin_mode = "isolated" if int_margin_mode == 1 else "cross"

        # === 1. Установка плеча ===
        lev_resp = await self.okx_client.set_leverage(
            session=session,
            instId=symbol,
            lever=leverage,
            mgnMode=margin_mode,
            posSide=pos_side
        )
        # print(lev_resp)

        # === 2. Расчёт контрактов ===
        spec = symbol_data.get("spec", {})
        ctVal = spec.get("ctVal")
        lotSz = spec.get("lotSz")
        price_precision = spec.get("price_precision")
        contract_precision = spec.get("contract_precision")

        contracts = self.utils.contract_calc(
            margin_size=fin_settings.get("margin_size"),
            entry_price=float(entry_price),
            leverage=leverage,
            ctVal=ctVal,
            lotSz=lotSz,
            contract_precision=contract_precision,
            debug_label=debug_label
        )

        if not contracts or contracts <= 0:
            failed_reason = f"{debug_label}: Invalid contracts calculated: {contracts}"
            order_failed_body = {
                "symbol": symbol,
                "pos_side": pos_side,
                "reason": failed_reason,
                "cur_time": int(time.time() * 1000),
            }
            self.notifier.format_message(
                chat_id=chat_id,
                marker=f"{market_label}_order_failed",
                body=order_failed_body,
                is_print=True
            )
            return

        # === 3. Размещение лимитного ордера с корректными TP/SL ===
        entry_px = to_human_digit(round(float(entry_price), price_precision))
        tp_px = to_human_digit(round(float(take_profit), price_precision))
        sl_px = to_human_digit(round(float(stop_loss), price_precision))

        print(
            f"[DEBUG price rounding] precision={price_precision} | "
            f"entry: raw={entry_price} -> rounded={entry_px} | "
            f"tp: raw={take_profit} -> rounded={tp_px} | "
            f"sl: raw={stop_loss} -> rounded={sl_px}"
        )

        return entry_px, tp_px, sl_px, contracts

    async def place_order_template(
        self,
        session: aiohttp.ClientSession,
        chat_id: str,
        fin_settings: dict,
        symbol: str,
        leverage: int,
        entry_price: str,
        take_profit: str,
        stop_loss: str,
        pos_side: str,
        symbol_data: dict,
        pos_data: dict,
        market_label: str = "limit"
    ):
            
        debug_label = f"[{symbol}_{pos_side}]"

        # Если уже есть активный order_id — выходим
        if pos_data.get("order_id"):
            return False 

        pre_order_resp = await self.pre_order_template(
            session=session,
            chat_id=chat_id,
            fin_settings=fin_settings,
            symbol=symbol,
            pos_side=pos_side,
            leverage=leverage,
            symbol_data=symbol_data,
            entry_price=entry_price,
            take_profit=take_profit,
            stop_loss=stop_loss,
            debug_label=debug_label,
            market_label=market_label
        )

        if not pre_order_resp or len(pre_order_resp) != 4:
            self.info_handler.debug_info_notes(f"{debug_label} Invalid pre_order_resp")
            return False

        entry_px, tp_px, sl_px, contracts = pre_order_resp

        px = entry_px if market_label == "limit" else None
        side = "buy" if pos_side.upper() == "LONG" else "sell"

        int_margin_mode = fin_settings.get("margin_mode", 1)
        margin_mode = "isolated" if int_margin_mode == 1 else "cross"

        place_order_resp = await self.okx_client.place_order(
            session=session,
            instId=symbol,
            sz=contracts,
            side=side,
            tdMode=margin_mode,
            posSide=pos_side,
            reduceOnly=False,
            ordType=market_label,         # ✅ тип ордера
            px=px,                        # ✅ цена лимитки
            tp_trigger_px=tp_px,
            tp_ord_px="-1",               # маркет на закрытие позиции
            sl_trigger_px=sl_px,
            sl_ord_px="-1",               # маркет на закрытие позиции
            tpTriggerPxType="last",       # срабатывает по последней сделке
            slTriggerPxType="last"
        )

        data_list = ApiResponseValidator.get_data_list(place_order_resp)
        ord_info = data_list[0] if data_list else {}
        ord_id = ord_info.get("ordId")
        ord_ts = ord_info.get("ts")

        # Проверка успешности размещения ордера
        if not ord_id or ord_info.get("sCode") != "0":
            order_failed_body = {
                "symbol": symbol,
                "pos_side": pos_side,
                "reason": ord_info.get("sMsg"),
                "cur_time": int(ord_ts) if ord_ts else int(time.time() * 1000),
            }
            self.notifier.format_message(
                chat_id=chat_id,
                marker=f"{market_label}_order_failed",
                body=order_failed_body,
                is_print=True
            )
            return False

        # === 4. Сохраняем ID и timestamp ===
        try:
            pos_data["order_id"] = int(ord_id)
        except (ValueError, TypeError):
            pos_data["order_id"] = None

        # Логируем успешное размещение лимитного ордера
        order_sent_body = {
            "symbol": symbol,
            "pos_side": pos_side,
            "cur_time": int(ord_ts) if ord_ts else int(time.time() * 1000),
        }
        self.notifier.format_message(
            chat_id=chat_id,
            marker=f"{market_label}_order_sent",
            body=order_sent_body,
            is_print=True
        )

        return True 

    async def complete_signal_task(
        self,
        chat_id: str,
        fin_settings: dict,
        parsed_msg: dict,
        context_vars: dict,
        last_timestamp: int,
        msg_key: str,
    ):
        symbol = parsed_msg["symbol"]
        pos_side = parsed_msg["pos_side"]
        symbol_data = context_vars[symbol]
        pos_data = symbol_data[pos_side]

        leverage = pos_data["leverage"]
        entry_price = parsed_msg["entry_price"]
        take_profit = parsed_msg["take_profit"]
        stop_loss = parsed_msg["stop_loss"]

        market_label = "limit" if not fin_settings.get("market_order") else "market"
        # Выполняем торговый шаблон
        place_order_response: bool = await self.place_order_template(
                session=self.context.session,
                chat_id=chat_id,
                fin_settings=fin_settings,
                symbol=symbol,
                leverage=leverage,
                entry_price=entry_price,
                take_profit=take_profit,
                stop_loss=stop_loss,
                pos_side=pos_side,
                symbol_data=symbol_data,
                pos_data=pos_data,
                market_label=market_label
            )
        
        if market_label == "limit" and place_order_response:
            # Создаём задачу для слежения и отмены
            asyncio.create_task(
                self.complete_until_cancel(
                    session=self.context.session,
                    chat_id=chat_id,
                    fin_settings=fin_settings,
                    symbol=symbol,
                    pos_side=pos_side,
                    pos_data=pos_data,
                    last_timestamp=last_timestamp,
                    msg_key=msg_key
                )
            )

    async def handle_signal(
        self,
        chat_id: str,
        parsed_msg: dict,
        context_vars: dict,        
        symbol: str,
        pos_side: str,
        last_timestamp: str,
        msg_key: str
    ) -> None:
        # Проверка и установка дефолтов
        if not self.pos_setup.set_pos_defaults(symbol, pos_side, self.instruments_data):
            return

        # Ждём первого апдейта позиций
        while not self.sync._first_update_done:
            await asyncio.sleep(0.1)

        pos_data = context_vars.get(symbol, {}).get(pos_side, {})

        # Защита 1: уже в позиции (по данным биржи)
        if pos_data.get("in_position"):
            self.info_handler.debug_info_notes(
                f"[handle_signal] Skip: already in_position {symbol} {pos_side}"
            )
            return

        # Защита 2: уже идёт открытие (pending_open)
        if pos_data.get("pending_open", False):
            self.info_handler.debug_info_notes(
                f"[handle_signal] Skip: pending_open {symbol} {pos_side}"
            )
            return

        # Ставим флаг pending_open
        pos_data["pending_open"] = True

        try:
            # --- Достаём фин настройки ---
            fin_settings = self.context.users_configs[chat_id]["config"]["fin_settings"]

            # Обновляем плечо
            max_leverage = context_vars.get(symbol, {}).get("spec", {}).get("max_leverage", 20)
            leverage = min(
                fin_settings.get("leverage") or parsed_msg.get("leverage"),
                max_leverage
            )
            pos_data["leverage"] = leverage
            pos_data["margin_vol"] = fin_settings.get("margin_size")

            # Форматируем цены
            cur_price = self.context.prices.get(symbol)
            for key in ("entry_price", "take_profit", "stop_loss"):
                parsed_msg[key] = fix_price_scale(parsed_msg.get(key), cur_price)

            # Уведомление
            signal_body = {
                "symbol": symbol,
                "pos_side": pos_side,
                "cur_time": last_timestamp,
                "leverage": leverage,
                "entry_price": parsed_msg["entry_price"],
                "tp": parsed_msg["take_profit"],
                "sl": parsed_msg["stop_loss"],
            }
            self.notifier.format_message(chat_id, "signal", signal_body, is_print=True)

            # Запуск ордера
            await self.complete_signal_task(
                chat_id=chat_id,
                fin_settings=fin_settings,
                parsed_msg=parsed_msg,
                context_vars=context_vars,
                last_timestamp=last_timestamp,
                msg_key=msg_key
            )

        finally:
            # Снимаем pending_open, если update_positions ещё не успел
            if not pos_data.get("in_position"):
                pos_data["pending_open"] = False


    async def _run_iteration(self) -> None:
        """Одна итерация торговли (от старта до стопа)."""
        print("[CORE] Iteration started")

        # --- Перебор пользователей ---
        for num, (chat_id, user_cfg) in enumerate(self.context.users_configs.items(), start=1):
            print(f"[DEBUG] Processing user {num} | chat_id: {chat_id}")
            
            if num > 1:
                self.info_handler.debug_info_notes(
                    f"Бот настроен только для одного пользователя! "
                    f"Для текущего chat_id: {chat_id} опция торговли недоступна. {log_time()}"
                )
                continue

            try:
                # --- Запуск контекста пользователя ---
                print(f"[DEBUG] Starting user context for chat_id: {chat_id}")
                await self._start_user_context(chat_id=chat_id)

                # --- Дебаг OKX настройки ---
                user_config: Dict[str, Any] = self.context.users_configs.get(chat_id, {})
                okx_cfg: Dict[str, Any] = user_config.get("config", {}).get("OKX", {})
                print(f"[DEBUG] OKX config for user {chat_id}: {okx_cfg}")

                required_keys = ["api_key", "api_secret", "api_passphrase"]
                for key in required_keys:
                    if key not in okx_cfg or okx_cfg[key] is None:
                        print(f"[WARNING] OKX {key} not set for user {chat_id}")

            except Exception as e:
                err_msg = f"[ERROR] Failed to start user context for chat_id {chat_id}: {e}"
                self.info_handler.debug_error_notes(err_msg, is_print=True)
                continue

        self.connector.start_ping_loop()

        # --- Получаем инструменты с биржи ---
        try:       
            self.instruments_data = await self.okx_client.get_instruments(session=self.context.session)
            if self.instruments_data:
                print(f"[DEBUG] Instruments fetched: {len(self.instruments_data)} items")
            else:
                self.info_handler.debug_error_notes(f"[ERROR] Failed to fetch instruments: {e}", is_print=True)

        except Exception as e:
            self.info_handler.debug_error_notes(f"[ERROR] Failed to fetch instruments: {e}", is_print=True)

        self.context.prices = await self.okx_client.get_all_current_prices(session=self.context.session)

        # --- Запуск наблюдателей ---
        self.tg_watcher.register_handler(tag=TEG_ANCHOR)
        # /
        context_vars = self.context.position_vars
        asyncio.create_task(self.sync.refresh_positions_task())

        # --- Основной цикл итерации ---
        while not self.context.stop_bot_iteration and not self.context.stop_bot:
            try:
                signal_tasks_val = self.context.message_cache[-SIGNAL_PROCESSING_LIMIT:] if self.context.message_cache else None
                if not signal_tasks_val:
                    # print("[DEBUG] No signal tasks available")
                    await asyncio.sleep(MAIN_CYCLE_FREQUENCY)
                    continue

                for signal_item in signal_tasks_val:
                    if not signal_item:
                        continue

                    message, last_timestamp = signal_item
                    if not (message and last_timestamp):
                        print("[DEBUG] Invalid signal item, skipping")
                        continue

                    hash_message = hash(message)
                    msg_key = f"{last_timestamp}_{hash_message}"
                    if msg_key in self.context.tg_timing_cache:
                        continue
                    self.context.tg_timing_cache.add(msg_key)

                    parsed_msg, all_present = self.tg_watcher.parse_tg_message(message)
                    if not all_present:
                        print(f"[DEBUG] Parse error: {parsed_msg}")
                        continue

                    symbol = parsed_msg.get("symbol")
                    pos_side = parsed_msg.get("pos_side")
                    debug_label = f"{symbol}_{pos_side}"

                    if symbol in BLACK_SYMBOLS:
                        continue

                    # === Проверка на таймаут ===
                    diff_sec = time.time() - (last_timestamp / 1000)
                    # print(f"[DEBUG]{debug_label} diff sec: {diff_sec:.2f}")
                    
                    for num, (chat_id, user_cfg) in enumerate(self.context.users_configs.items(), start=1):
                        if num > 1:
                            continue
                        if diff_sec < user_cfg.get("fin_settings", {}).get("order_timeout", 60):
                            # Создаём lock для каждой позиции, если ещё нет
                            lock_key = f"{symbol}_{pos_side}"
                            if lock_key not in self.context.symbol_locks:
                                self.context.symbol_locks[lock_key] = asyncio.Lock()

                            # Асинхронно блокируем обработку сигналов на эту позицию
                            async with self.context.symbol_locks[lock_key]:                                    
                                asyncio.create_task(self.handle_signal(
                                    chat_id=chat_id,
                                    parsed_msg=parsed_msg,
                                    context_vars=context_vars,                            
                                    symbol=symbol,
                                    pos_side=pos_side,
                                    last_timestamp=last_timestamp,
                                    msg_key=msg_key
                                ))

            except Exception as e:
                err_msg = f"[ERROR] main loop: {e}\n" + traceback.format_exc()
                self.info_handler.debug_error_notes(err_msg, is_print=True)

            finally:
                try:
                    for num, (chat_id, user_cfg) in enumerate(self.context.users_configs.items(), start=1):
                        if num > 1:
                            continue
                        await self.notifier.send_report_batches(chat_id=chat_id, batch_size=1)
                except Exception as e:
                    err_msg = f"[ERROR] main finally block: {e}\n" + traceback.format_exc()
                    self.info_handler.debug_error_notes(err_msg, is_print=True)

                await asyncio.sleep(MAIN_CYCLE_FREQUENCY)


    async def run_forever(self, debug: bool = True):
        """Основной перезапускаемый цикл Core."""
        if debug: print("[CORE] run_forever started")

        # Запуск Telegram UI один раз
        if self.tg_interface is None:
            self.tg_watcher = TgBotWatcherAiogram(
                dp=self.dp,
                channel_id=TG_GROUP_ID,
                context=self.context,
                info_handler=self.info_handler
            )
            self.tg_watcher.register_handler(tag=TEG_ANCHOR)

            self.tg_interface = TelegramUserInterface(
                bot=self.bot,
                dp=self.dp,
                context=self.context,
                info_handler=self.info_handler,
            )

            self.notifier = TelegramNotifier(
                bot=self.bot,
                context=self.context,
                info_handler=self.info_handler
            )

            await self.tg_interface.run()  # polling стартует уже с зарегистрированными хендлерами

        while not self.context.stop_bot:
            if debug: print("[CORE] Новый цикл run_forever, обнуляем флаги итерации")
            self.context.start_bot_iteration = False
            self.context.stop_bot_iteration = False

            # ждём нажатия кнопки START
            if debug: print("[CORE] Ожидание кнопки START...")
            while not self.context.start_bot_iteration and not self.context.stop_bot:
                await asyncio.sleep(0.3)

            if self.context.stop_bot:
                if debug: print("[CORE] Stop флаг поднят, выходим из run_forever")
                break

            # запускаем итерацию торговли
            try:
                if debug: print("[CORE] Запуск торговой итерации (_run_iteration)...")
                await self._run_iteration()
                if debug: print("[CORE] Торговая итерация завершена")
            except Exception as e:
                self.info_handler.debug_error_notes(f"[CORE] Ошибка в итерации: {e}", is_print=True)

            # очищаем ресурсы итерации
            try:
                if debug: print("[CORE] Очистка ресурсов итерации (_shutdown_iteration)...")
                await self._shutdown_iteration(debug=debug)
                if debug: print("[CORE] Очистка ресурсов завершена")
            except Exception as e:
                self.info_handler.debug_error_notes(f"[CORE] Ошибка при shutdown итерации: {e}", is_print=True)

            # если была локальная остановка — ждём нового START
            if self.context.stop_bot_iteration:
                self.info_handler.debug_info_notes("[CORE] Перезапуск по кнопке STOP", is_print=True)
                if debug: print("[CORE] Ожидание следующего START после STOP")
                continue

        if debug: print("[CORE] run_forever finished")

    async def _shutdown_iteration(self, debug: bool = True):
        """Закрывает итерационные ресурсы и обнуляет инстансы."""

        # --- Остановка цикла positions_flow_manager ---
        if self.positions_task:
            self.positions_task.cancel()
            try:
                await self.positions_task
            except asyncio.CancelledError:
                if debug:
                    print("[CORE] positions_flow_manager cancelled")
            self.positions_task = None

        # --- Connector ---
        if getattr(self, "connector", None):
            try:
                await asyncio.wait_for(self.connector.shutdown_session(), timeout=5)
            except Exception as e:
                if debug:
                    print(f"[CORE] connector.shutdown_session() error: {e}")
            finally:
                self.context.session = None
                self.connector = None

        # --- Сброс прочих ссылок ---
        self.okx_client = None
        self.sync = None
        self.utils = None
        self.pos_setup = None

        self.context.position_vars = {}

        if debug:
            print("[CORE] Iteration shutdown complete")

async def main():
    instance = Core()
    try:
        # ставим таймаут на работу, чтобы любой зависший таск не блокировал forever
        await asyncio.wait_for(instance.run_forever(), timeout=None)
    except asyncio.CancelledError:
        print("🚨 CancelledError caught")
    finally:
        print("♻️ Cleaning up iteration")
        instance.context.stop_bot = True
        await instance._shutdown_iteration()

if __name__ == "__main__":
    # жёсткое убийство через Ctrl+C / kill
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("💥 Force exit")
    os._exit(1)