import asyncio
import aiohttp
from typing import Optional

class BotContext:
    def __init__(self):
        """ Инициализируем глобальные структуры"""
        # //
        self.message_cache: list = []  # основной кеш сообщений
        self.tg_timing_cache: set = set()
        self.stop_bot = False
        self.start_bot_iteration = False
        self.stop_bot_iteration = False
        # //
        self.users_configs: dict = {}
        self.instruments_data: dict = None
        self.prices: dict = None
        self.queues_msg: dict = {}
        self.position_vars: dict = {}
        self.report_list: list = []
        self.session: Optional[aiohttp.ClientSession] = None
        self.symbol_locks: dict = {}