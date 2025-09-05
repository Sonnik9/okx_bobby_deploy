import aiohttp
import asyncio
import hmac
import hashlib
import base64
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from urllib.parse import urlencode
from b_context import BotContext
from c_log import ErrorHandler


class OkxFuturesClient:
    """
    Async OKX v5 REST client (suitable for FUTURES / SWAP usage).
    NOTE: pass api_passphrase exactly as created in OKX API management.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
        context: BotContext,
        info_handler: ErrorHandler,
        base_url: str = "https://www.okx.com",
        recv_window: int = 5000,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.base_url = base_url.rstrip("/")
        self.recv_window = recv_window
   
        info_handler.wrap_foreign_methods(self)
        self.info_handler = info_handler
        self.stop_bot = context.stop_bot
        self.stop_bot_iteration = context.stop_bot_iteration

    # # --- helpers ---
    def _utc_iso(self) -> str:
        # milliseconds precision, Z
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _sign(self, timestamp: str, method: str, request_path: str, body: str) -> str:
        """
        OKX signature: Base64( HMAC-SHA256( secret, timestamp + method + requestPath + body ) )
        See OKX docs for details.
        """
        prehash = f"{timestamp}{method.upper()}{request_path}{body}"
        digest = hmac.new(self.api_secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    async def _request(
        self,
        session: Optional[aiohttp.ClientSession],
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        private: bool = False,
        spec_marker: str = None
    ) -> Dict[str, Any]:

        method_up = method.upper()
        query = ""
        if method_up == "GET" and params:
            query = "?" + urlencode(params, doseq=True)
        request_path = path + query
        body_str = "" if method_up == "GET" else json.dumps(data or {}, separators=(",", ":"), ensure_ascii=False)
        url = self.base_url + request_path

        headers = {"Content-Type": "application/json"}
        if private:
            ts = self._utc_iso()
            signature = self._sign(ts, method_up, request_path, body_str)
            headers.update({
                "OK-ACCESS-KEY": self.api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": ts,
                "OK-ACCESS-PASSPHRASE": self.api_passphrase,
            })

        async def send_request(sess: aiohttp.ClientSession):
            if method_up == "GET":
                return await sess.get(url, headers=headers)
            elif method_up == "POST":
                return await sess.post(url, headers=headers, data=body_str.encode("utf-8"))
            else:
                self.info_handler.debug_error_notes(f"Unsupported HTTP method: {method}", is_print=True)
                return {}
            
        attempt_counter = 0

        use_session = None
        while not self.stop_bot and not self.stop_bot_iteration:
            attempt_counter += 1
            try:
                if session and not session.closed:
                    use_session = session
                    is_temp = False
                else:
                    use_session = aiohttp.ClientSession()
                    is_temp = True

                if is_temp:
                    async with use_session:
                        resp = await send_request(use_session)
                else:
                    resp = await send_request(use_session)

                text = await resp.text()
                try:
                    j = json.loads(text)
                except Exception:
                    self.info_handler.debug_error_notes(f"Non-JSON response: {resp.status} {text}", is_print=True)
                    j = {}

                if resp.status >= 400:
                    self.info_handler.debug_error_notes(f"HTTP {resp.status}: {j}", is_print=True)

                code = j.get("code")
                if code is not None and str(code) != "0":
                    self.info_handler.debug_info_notes(f"OKX DEBUG code {code}: {j.get('msg')} | full: {j}", is_print=True)

                return j

            except asyncio.CancelledError:
                return
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                # if spec_marker != "non_session" or attempt_counter > 1:
                #     self.info_handler.debug_error_notes(f"[Request error] {e}. Attempt== {attempt_counter}. Retry in 1s", is_print=True)
                await asyncio.sleep(1)
            except Exception as e:
                # if spec_marker != "non_session" or attempt_counter > 1:
                #     self.info_handler.debug_error_notes(f"[Unexpected error] {e}. Attempt== {attempt_counter}. Retry in 1s", is_print=True)
                await asyncio.sleep(1)

    # --- Public endpoints ---
    async def get_instruments(
        self,
        session: aiohttp.ClientSession,
        uly: Optional[str] = None,
        instType: str = "SWAP",        
        instId: Optional[str] = None,
        instFamily: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        GET /api/v5/public/instruments
        instType: SPOT, MARGIN, SWAP, FUTURES, OPTION
        Returns list of instrument metadata (tickSz, lotSz, maxSize, etc).
        Use this to determine rounding / lot step (lotSz) and price tick (tickSz).
        """
        params = {"instType": instType}
        if uly:
            params["uly"] = uly
        if instId:
            params["instId"] = instId
        if instFamily:
            params["instFamily"] = instFamily

        r = await self._request(session, "GET", "/api/v5/public/instruments", params=params, private=False)
        if r is None:
            return        
        return r.get("data", [])
    
    async def get_current_price(
        self,
        instId: str
    ) -> Optional[float]:
        """
        GET /api/v5/market/ticker
        Возвращает текущую цену инструмента instId.
        Если цена не найдена — возвращает None.
        """
        params = {"instId": instId}
        # async with aiohttp.ClientSession() as session:
        r = await self._request(None, "GET", "/api/v5/market/ticker", params=params, private=False, spec_marker="non_session")
        if r is None:
            return  
        data = r.get("data", [])
        if not data:
            return None
        try:
            last_price_str = data[0].get("last")
            return float(last_price_str) if last_price_str is not None else None
        except (ValueError, IndexError, KeyError):
            return None

    async def get_all_current_prices(self, session: aiohttp.ClientSession) -> Dict[str, float]:
        """
        GET /api/v5/market/tickers
        Возвращает словарь {instId: last_price} для всех инструментов.
        """
        params = {"instType": "SWAP"}
        # async with aiohttp.ClientSession() as session:
        r = await self._request(session, "GET", "/api/v5/market/tickers", params=params, private=False)
        if r is None:
            return  
        data = r.get("data", [])
        prices = {}
        for item in data:
            try:
                inst_id = item.get("instId")
                last_price_str = item.get("last")
                if inst_id and last_price_str is not None:
                    prices[inst_id] = float(last_price_str)
            except ValueError:
                continue
        return prices

    # --- Private trading endpoints ---
    async def set_position_mode(
        self,
        session: aiohttp.ClientSession,
        pos_mode: str = "long_short_mode"  # "net" — моно
    ) -> Dict[str, Any]:
        """
        POST /api/v5/account/set-position-mode
        pos_mode:
            "long_short" -> Hedge Mode (раздельные позиции LONG/SHORT)
            "net"        -> One-way Mode (моно)
        """
        pos_mode = pos_mode.lower()
        if pos_mode not in ("long_short_mode", "net"):
            print("pos_mode must be 'long_short' or 'net'")
            return

        body = {"posMode": pos_mode}
        return await self._request(
            session,
            "POST",
            "/api/v5/account/set-position-mode",
            data=body,
            private=True
        )

    async def fetch_positions(
        self, 
        session, 
        instId: Optional[str] = None, 
        instType: str = "SWAP",
        posId: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        GET /api/v5/account/positions
        Получает текущие позиции или информацию о конкретной позиции по posId.
        
        Args:
            session: aiohttp.ClientSession
            instId: (опционально) идентификатор инструмента
            instType: тип инструмента, по умолчанию SWAP
            posId: (опционально) ID позиции для запроса закрытой позиции
        
        Returns:
            Список словарей с данными по позициям
        """
        params = {"instType": instType}
        if instId:
            params["instId"] = instId
        if posId:
            params["posId"] = posId  # <-- добавляем возможность запроса по posId

        r = await self._request(
            session, 
            "GET", 
            "/api/v5/account/positions", 
            params=params, 
            private=True
        )
        if r is None:
            return  
        return r.get("data", [])

    async def set_leverage(
        self,
        session: aiohttp.ClientSession,
        instId: str | None = None,
        lever: int | float | str = None,
        mgnMode: str | None = None,
        posSide: str | None = None,
        ccy: str | None = None
    ) -> dict:
        """
        POST /api/v5/account/set-leverage
        - instId: instrument id (optional depending on the scope)
        - lever: leverage (string or number)
        - mgnMode: 'isolated' / 'cross'
        - posSide: 'long'/'short' (for hedge mode)
        - ccy: currency (e.g., 'USDT')
        """
        if lever is None:
            print("lever must be provided")
            return

        # Приводим типы в нужный формат
        body: dict[str, str] = {
            "lever": str(lever)  # OKX принимает плечо в виде строки
        }

        if instId is not None:
            body["instId"] = str(instId)
        if mgnMode is not None:
            body["mgnMode"] = str(mgnMode).lower()
        if posSide is not None:
            body["posSide"] = str(posSide).lower()
        if ccy is not None:
            body["ccy"] = str(ccy)

        r = await self._request(
            session,
            "POST",
            "/api/v5/account/set-leverage",
            data=body,
            private=True
        )
        if r is None:
            return  
        return r.get("data", [])

    async def place_order(
        self,
        session: aiohttp.ClientSession,
        instId: str,
        sz: float | int | str,
        side: str,
        tdMode: str,
        posSide: str,
        reduceOnly: bool,
        tp_trigger_px: Optional[float | int | str] = None,
        tp_ord_px: Optional[float | int | str] = "-1",
        sl_trigger_px: Optional[float | int | str] = None,
        sl_ord_px: Optional[float | int | str] = "-1",
        tpTriggerPxType: str = "last",
        slTriggerPxType: str = "last",
        ordType: str = "limit",          # "limit" или "market"
        px: Optional[float | int | str] = None,  # цена (только для limit)
        client_ord_id: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Размещает ордер с автоматическим Take Profit и Stop Loss.
        - Для limit ордера: ordType="limit", px обязателен
        - Для market ордера: ordType="market", px не используется
        """

        body: Dict[str, Any] = {
            "instId": str(instId),
            "tdMode": tdMode.lower(),
            "side": side.lower(),
            "ordType": ordType.lower(),
            "sz": str(sz),
            "posSide": posSide.lower(),
            "reduceOnly": "true" if reduceOnly else "false",
        }

        # === цена для limit ===
        if ordType.lower() == "limit":
            if px is None:
                raise ValueError("px (цена) обязательна для limit-ордера")
            body["px"] = str(px)

        # === TP / SL ===
        if tp_trigger_px is not None:
            body["tpTriggerPx"] = str(tp_trigger_px)
            body["tpOrdPx"] = str(tp_ord_px) if tp_ord_px is not None else "-1"
            body["tpTriggerPxType"] = tpTriggerPxType

        if sl_trigger_px is not None:
            body["slTriggerPx"] = str(sl_trigger_px)
            body["slOrdPx"] = str(sl_ord_px) if sl_ord_px is not None else "-1"
            body["slTriggerPxType"] = slTriggerPxType

        if client_ord_id:
            body["clOrdId"] = str(client_ord_id)
        if tag:
            body["tag"] = str(tag)

        # === DEBUG REQUEST ===
        self.info_handler.debug_info_notes(
            f"[DEBUG: place_order request body] {body}", is_print=True
        )

        r = await self._request(
            session,
            "POST",
            "/api/v5/trade/order",
            data=body,
            private=True
        )

        if r is None:
            return 

        return r.get("data", [])

    async def cancel_order(
            self,
            session: aiohttp.ClientSession,
            instId: str,
            ordId: Optional[str] = None,
            clOrdId: Optional[str] = None
        ) -> Dict[str, Any]:
        """
        Cancel a normal order: POST /api/v5/trade/cancel-order
        Provide either ordId or clOrdId (and instId).
        """
        body: Dict[str, Any] = {"instId": instId}
        if ordId:
            body["ordId"] = ordId
        if clOrdId:
            body["clOrdId"] = clOrdId

        r = await self._request(session, "POST", "/api/v5/trade/cancel-order", data=body, private=True)
        if r is None:
            return  
        return r.get("data", [])    
    
    # /////
    async def get_historical_orders_report(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> Dict[str, Any]:
        """
        Получить историю позиций (positions-history) из OKX.
        """
        params: Dict[str, Any] = {}
        if symbol:
            params["instId"] = symbol  # OKX формат: BTC-USDT-SWAP
        if start_time:
            params["after"] = str(start_time)
        if end_time:
            params["before"] = str(end_time)

        return await self._request(
            session=session,
            method="GET",
            path="/api/v5/account/positions-history",
            params=params,
            private=True
        )
    async def get_realized_pnl(
        self,
        symbol: str,
        start_time: Optional[int],
        end_time: Optional[int],
        direction: Optional[int] = None  # 1=LONG, 2=SHORT
    ) -> dict:
        """
        Считает реализованный PnL за период по символу (OKX).
        Возвращает словарь:
            {"pnl_usdt": float, "pnl_pct": float}
        """
        try:
            rows = await self.get_futures_statement(symbol=symbol)
            # print(f"rows: {rows}")
            if not rows:
                return {"pnl_usdt": 0.0, "pnl_pct": 0.0}
        except Exception as e:
            self.info_handler.debug_error_notes(
                f"[get_realized_pnl][OKX] error fetching data: {e}", is_print=True
            )
            return {"pnl_usdt": 0.0, "pnl_pct": 0.0}

        pnl_usdt = 0.0
        pnl_pct = 0.0

        for row in rows:
            try:
                ts = int(row.get("uTime", 0))  # время обновления
                if start_time and ts < start_time:
                    continue

                # фильтр по направлению
                pos_side = row.get("posSide", "").upper()  # "LONG"/"SHORT"
                if direction != pos_side:
                    continue

                # PnL в долларах
                # pnl_usdt += float(row.get("realizedPnl", 0.0))
                pnl_usdt += (
                    float(row.get("realizedPnl", 0.0)) +
                    float(row.get("fee", 0.0)) +
                    float(row.get("fundingFee", 0.0))
                )
                # PnL в %
                pnl_pct += (float(row.get("pnlRatio", 0.0))) * 100

            except Exception:
                continue

        return {
            "pnl_usdt": round(pnl_usdt, 4),
            "pnl_pct": round(pnl_pct, 4),
        }

    async def get_futures_statement(
        self,
        symbol: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        resp = await self.get_historical_orders_report(symbol=symbol, session=session)
        if resp and resp.get("code") == "0":
            return resp.get("data", [])
        return []



class ApiResponseValidator:
    @staticmethod
    def normalize_response(resp):
        """
        Приводит resp к dict, если он list — берёт первый элемент.
        Если resp пустой или не содержит dict — возвращает пустой словарь.
        """
        if isinstance(resp, dict):
            return resp
        elif isinstance(resp, list) and resp and isinstance(resp[0], dict):
            return resp[0]
        return {}

    @staticmethod
    def get_code(resp):
        """
        Получает код ответа API ('0', '1', и т.д.)
        Работает и если resp — уже data из r.get("data", [])
        """
        if isinstance(resp, dict):
            return str(resp.get("code", ""))
        return None

    @staticmethod
    def get_data_list(resp):
        """
        Возвращает список data. Если resp уже список — возвращает его как есть.
        Если dict — возвращает resp.get("data", [])
        """
        if isinstance(resp, list):
            return resp
        elif isinstance(resp, dict):
            data = resp.get("data", [])
            return data if isinstance(data, list) else []
        return []
