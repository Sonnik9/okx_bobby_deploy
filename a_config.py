# --- CORE ---
TEG_ANCHOR: str = "#soft" # --------------------------  # имя тега целевого сообщения

# --- SECRETS CONFIG ---                 
# TG_BOT_TOKEN: str = "8232845447:AAEIdSZ0IeNxlTBTQ7I7G_QeAn4tOFgTE6Q"
# TG_GROUP_ID: str = "-1002653345160" # id группы откуда парсить сигнал
TG_BOT_TOKEN: str = "8304645115:AAE5HKrTclLDoRmE5W60vLRurbEH_fm-qyU" # -- токен бота (test)
TG_GROUP_ID: str = "-1003053085303" # -- id группы откуда парсить сигнал (test)

# -- UTILS ---
# BLACK_SYMBOLS: set = {"BTC-USDT-SWAP"} # -------------# символы-исключения (не используем в торговле)
BLACK_SYMBOLS: dict = {}
TIME_ZONE: str = "UTC"
SLIPPAGE_PCT: float = 0.09 # % -- поправка для расчетов PnL. Откл -- None | 0.0
PRECISION: int = 28 # -- точность округления для малых чисел
PING_URL = "https://www.okx.com/api/v5/public/time"
PING_INTERVAL: float = 10 # sec

# --- SYSTEM ---
TG_UPDATE_FREQUENCY: float = 1 # sec ---- частота запросов к тг при парсинге
POSITIONS_UPDATE_FREQUENCY: float = 1 # sec --- частота обновления данных позиции
MAIN_CYCLE_FREQUENCY: float = 1 # sec  ---- частота главного цикла
SIGNAL_PROCESSING_LIMIT: int = 10 # --------- ограничивает количество одновременной обработки сигналов
PING_UPDATE_INTERVAL: int = 10 # sec --- через сколько обновляем сессию

# --- STYLES ---
HEAD_WIDTH: int = 35
HEAD_LINE_TYPE: str = "" #  либо "_"
EMO_SUCCESS:str = "🟢"
EMO_LOSE: str = "🔴"
EMO_ZERO: str = "⚪"
EMO_ORDER_FILLED: str = "🤞"


# ------- BUTTON TEMPLATES ------

INIT_USER_CONFIG = {
    "config": {
        "OKX": {
            # "api_key": "1ad6a657-79f0-46ca-ac96-ab134919f175",
            # "api_secret": "2242CBDD7836791C69CED4BD135CC873",
            # "api_passphrase": "Dimonhochetpivo123?"
            "api_key": "4e7f66f3-2fe5-4211-94b0-77b8980c0bb4",
            "api_secret": "FD81F64CC6924294C886B37FD9FC4ED4",
            "api_passphrase": "hereiame33!ABc"
        },
        "fin_settings": {
            "margin_size": None,
            "margin_mode": 2, # CROSSED            
            "leverage": None,
            "market_order": None, # 1 -- лимитками, 2 -- по маркету.
            "order_timeout": 60,           
        }
    },
    "_await_field": None
}