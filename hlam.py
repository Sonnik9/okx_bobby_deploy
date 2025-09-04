         
    # @staticmethod
    # def parse_precision(data: List[Dict[str, Any]], symbol: str) -> Optional[Dict[str, Any]]:
    #     for info in data:
    #         if info.get("instId") == symbol:
    #             def count_precision(value_str: str) -> int:
    #                 return len(value_str.split(".")[1]) if "." in value_str else 0

    #             ctVal_str = str(info.get("ctVal", "1"))
    #             lot_sz_str = str(info.get("lotSz", "1"))
    #             tick_sz_str = str(info.get("tickSz", "1"))

    #             return {
    #                 "ctVal": float(ctVal_str),
    #                 "lotSz": float(lot_sz_str),
    #                 "contract_precision": count_precision(lot_sz_str),
    #                 "price_precision": count_precision(tick_sz_str)
    #             }
    #     return None




# spec: {'alias': '', 'auctionEndTime': '', 'baseCcy': '', 'category': '1', 'contTdSwTime': '', 'ctMult': '1', 'ctType': 'linear', 'ctVal': '1', 'ctValCcy': 'JTO', 'expTime': '', 'futureSettlement': False, 'instFamily': 'JTO-USDT', 'instId': 'JTO-USDT-SWAP', 'instIdCode': 143865, 'instType': 'SWAP', 'lever': '50', 'listTime': '1704696900623', 'lotSz': '1', 'maxIcebergSz': '100000000.0000000000000000', 'maxLmtAmt': '20000000', 'maxLmtSz': '100000000', 'maxMktAmt': '', 'maxMktSz': '50000', 'maxStopSz': '50000', 'maxTriggerSz': '100000000.0000000000000000', 'maxTwapSz': '100000000.0000000000000000', 'minSz': '1', 'openType': '', 'optType': '', 'preMktSwTime': '', 'quoteCcy': '', 'ruleType': 'normal', 'settleCcy': 'USDT', 'state': 'live', 'stk': '', 'tickSz': '0.001', 'tradeQuoteCcyList': [], 'uly': 'JTO-USDT'}



        # # --- Основной цикл итерации ---
        # while not self.context.stop_bot_iteration and not self.context.stop_bot:
        #     try:
        #         signal_tasks_val = self.context.message_cache[-SIGNAL_PROCESSING_LIMIT:] if self.context.message_cache else None
        #         if not signal_tasks_val:
        #             # print("[DEBUG] No signal tasks available")
        #             await asyncio.sleep(MAIN_CYCLE_FREQUENCY)
        #             continue

        #         for signal_item in signal_tasks_val:
        #             if not signal_item:
        #                 continue

        #             message, last_timestamp = signal_item
        #             if not (message and last_timestamp):
        #                 print("[DEBUG] Invalid signal item, skipping")
        #                 continue

        #             hash_message = hash(message)
        #             msg_key = f"{last_timestamp}_{hash_message}"
        #             if msg_key in self.context.tg_timing_cache:
        #                 continue
        #             self.context.tg_timing_cache.add(msg_key)

        #             parsed_msg, all_present = self.tg_watcher.parse_tg_message(message)
        #             if not all_present:
        #                 print(f"[DEBUG] Parse error: {parsed_msg}")
        #                 continue

        #             symbol = parsed_msg.get("symbol")
        #             pos_side = parsed_msg.get("pos_side")
        #             debug_label = f"{symbol}_{pos_side}"

        #             if symbol in BLACK_SYMBOLS:
        #                 continue

        #             # === Проверка на таймаут ===
        #             diff_sec = time.time() - (last_timestamp / 1000)
        #             # print(f"[DEBUG]{debug_label} diff sec: {diff_sec:.2f}")
                    
        #             for num, (chat_id, user_cfg) in enumerate(self.context.users_configs.items(), start=1):
        #                 if num > 1:
        #                     continue
        #                 if diff_sec < user_cfg.get("fin_settings", {}).get("order_timeout", 60):
        #                     # Создаём lock для каждой позиции, если ещё нет
        #                     lock_key = f"{symbol}_{pos_side}"
        #                     if lock_key not in self.context.symbol_locks:
        #                         self.context.symbol_locks[lock_key] = asyncio.Lock()

        #                     # Асинхронно блокируем обработку сигналов на эту позицию
        #                     async with self.context.symbol_locks[lock_key]:                                    
        #                         asyncio.create_task(self.handle_signal(
        #                             chat_id=chat_id,
        #                             parsed_msg=parsed_msg,
        #                             context_vars=context_vars,                            
        #                             symbol=symbol,
        #                             pos_side=pos_side,
        #                             last_timestamp=last_timestamp,
        #                             msg_key=msg_key
        #                         ))
