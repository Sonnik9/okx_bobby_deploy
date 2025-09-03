from a_config import *
from b_context import BotContext
from c_log import ErrorHandler, log_time
from typing import *
import re
from typing import Optional, Tuple, Set
from aiogram import Dispatcher, types


# Базовый словарь: пара символов (латиница, кириллица)
CHAR_PAIRS = {
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "y": "у", "x": "х",
    "A": "А", "B": "В", "E": "Е", "K": "К", "M": "М", "H": "Н", "O": "О",
    "P": "Р", "C": "С", "T": "Т", "X": "Х",
}

LATIN_TO_CYR = CHAR_PAIRS
CYR_TO_LATIN = {v: k for k, v in CHAR_PAIRS.items()}


class TgParser:
    def __init__(self, info_handler: ErrorHandler):    
        info_handler.wrap_foreign_methods(self)
        self.info_handler = info_handler

    @staticmethod
    def cyr_to_latin_f(text: str) -> str:
        """Нормализует строку для корректного сравнения тегов."""
        if not text:
            return ""
        return "".join(CYR_TO_LATIN.get(ch, ch) for ch in text)

    @staticmethod
    def latin_to_cyr_f(s: str) -> str:
        """Приводим похожие латинские буквы к кириллическим,
        убираем шум и заменяем запятые на точки."""
        if not s:
            return ""
        s = "".join(LATIN_TO_CYR.get(ch, ch) for ch in s)
        s = s.lower().replace(",", ".")
        return s

    @staticmethod
    def clean_number(num_str: str) -> Optional[float]:
        """
        Преобразует строку с любыми разделителями в float.
        Берёт последнюю точку как разделитель дробной части.
        """
        cleaned = re.sub(r"[^\d.]", "", num_str)
        if "." in cleaned:
            last_dot = cleaned.rfind(".")
            int_part = re.sub(r"[^\d]", "", cleaned[:last_dot])
            frac_part = re.sub(r"[^\d]", "", cleaned[last_dot + 1 :])
            normalized = f"{int_part}.{frac_part}" if frac_part else int_part
        else:
            normalized = re.sub(r"[^\d]", "", cleaned)

        try:
            return float(normalized)
        except ValueError:
            return None

    def parse_tg_message(self, message: str) -> Tuple[dict, bool]:
        text = self.latin_to_cyr_f(message.strip())
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        result = {
            "symbol": "",
            "pos_side": None,
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
            "leverage": None,
        }

        # символ (ищем по $)
        if lines:
            m_symbol = re.search(r"\$([а-яa-z0-9]+)", lines[0], re.IGNORECASE)
            if m_symbol:
                result["symbol"] = (
                    m_symbol.group(1).upper().replace("USDT", "-USDT-SWAP")
                )

        # позиция: лонг/шорт
        for line in lines:
            if "лонг" in line:
                result["pos_side"] = "LONG"
            elif "шорт" in line:
                result["pos_side"] = "SHORT"

        patterns = {
            "entry_price": r"вход\s*[-–—:]?\s*([\d\s.]+)",
            "stop_loss": r"стоп\s*[-–—:]?\s*([\d\s.]+)",
            "take_profit": r"тейк\s*[-–—:]?\s*([\d\s.]+)",
            "leverage": r"плечо\s*[-–—:]?\s*[хx]?\s*(\d+)"
        }

        for key, pattern in patterns.items():
            m = re.search(pattern, text)
            if m:
                if key == "leverage":
                    try:
                        result[key] = int(m.group(1))
                    except ValueError:
                        pass
                else:
                    result[key] = self.clean_number(m.group(1))

        all_present = all(v for v in result.values())
        result["symbol"] = self.cyr_to_latin_f(result["symbol"]).upper().replace("USDT", "-USDT-SWAP")
        return result, all_present


class TgBotWatcherAiogram(TgParser):
    """
    Отслеживает сообщения из канала через aiogram хендлеры.
    """

    def __init__(self, dp: Dispatcher, channel_id: int, context: BotContext, info_handler: ErrorHandler):
        super().__init__(info_handler)
        self.dp = dp
        self.channel_id = channel_id
        self.message_cache = context.message_cache
        self.stop_bot = context.stop_bot
        self._seen_messages: Set[int] = set()

    def register_handler(self, tag: str, max_cache: int = 20):
        """
        Регистрирует хендлер для прослушивания канала и фильтрации по тегу.
        """

        @self.dp.channel_post()
        async def channel_post_handler(message: types.Message):
            # print("Получено сообщение:", message.chat.id, message.text)
            try:
                # # # Проверяем ID канала
                # if message.chat.id != self.channel_id:
                #     return

                # Проверяем, есть ли текст
                if not message.text:
                    print(f"Нет сообщений для парсигна либо права доступа ограничены. (Возможно апи ограничения). {log_time()}")
                    return

                # Проверяем тег
                if tag.lower() not in message.text.lower():
                    return

                ts_ms = int(message.date.timestamp() * 1000)

                # Уникальность
                if ts_ms in self._seen_messages:
                    return

                self._seen_messages.add(ts_ms)
                self.message_cache.append((message.text, ts_ms))

                # Обрезаем кэш
                if len(self.message_cache) > max_cache:
                    self.message_cache = self.message_cache[-max_cache:]
                    self._seen_messages.clear()

                # print(f"[WATCHER] Новое сообщение с тегом {tag}: {message.text}")

            except Exception as e:
                self.info_handler.debug_error_notes(f"[watch_channel error] {e}", is_print=True)