         
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