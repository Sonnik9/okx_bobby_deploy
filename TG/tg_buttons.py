import asyncio
import copy
from typing import *
from a_config import *
from b_context import BotContext
from c_log import ErrorHandler
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def validate_user_config(user_cfg: dict) -> bool:
    """
    Проверяет корректность конфигурации пользователя.
    """
    config = user_cfg.setdefault("config", {})
    fin = config.setdefault("fin_settings", {})

    # === OKX ===
    okx = config.get("OKX", {})
    if not okx.get("api_key") or not okx.get("api_secret") or not okx.get("api_passphrase"):
        return False

    # === FIN SETTINGS ===
    if fin.get("margin_size") is None:
        return False
    if fin.get("margin_mode") is None:
        return False
    if fin.get("leverage") == 0:
        return False
    if fin.get("market_order") is None:
        return False
    if fin.get("order_timeout") is None:
        return False

    return True


def format_config(cfg: dict, indent: int = 0) -> str:
    lines = []
    pad = "  " * indent
    for k, v in cfg.items():
        if isinstance(v, dict):
            lines.append(f"{pad}• {k}:")
            lines.append(format_config(v, indent + 1))
        else:
            lines.append(f"{pad}• {k}: {v}")
    return "\n".join(lines)


class TelegramUserInterface:
    def __init__(self, bot: Bot, dp: Dispatcher, context: BotContext, info_handler: ErrorHandler):
        self.bot = bot
        self.dp = dp
        self.context = context
        self.info_handler = info_handler
        self._polling_task: asyncio.Task | None = None
        self._stop_flag = False
        self.bot_iteration_lock = asyncio.Lock()

        # ===== Главное меню =====
        self.main_menu = types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="🛠 Настройки"), types.KeyboardButton(text="📊 Статус")],
                [types.KeyboardButton(text="▶️ Старт"), types.KeyboardButton(text="⏹ Стоп")]
            ],
            resize_keyboard=True,
            input_field_placeholder="Выберите действие…"
        )

        # ===== Регистрация хендлеров =====
        self.dp.message.register(self.start_handler, Command("start"))
        self.dp.message.register(self.settings_cmd, self._text_contains(["настройки"]))
        self.dp.message.register(self.status_cmd, self._text_contains(["статус"]))
        self.dp.message.register(self.start_cmd, self._text_contains(["старт"]))
        self.dp.message.register(self.stop_cmd, self._text_contains(["стоп"]))
        self.dp.message.register(self.text_message_handler, self._awaiting_input)

        # ===== Inline Callbacks =====
        self.dp.callback_query.register(self.settings_handler, F.data == "SETTINGS")
        self.dp.callback_query.register(self.okx_settings_handler, F.data == "SET_OKX")
        self.dp.callback_query.register(self.api_key_input, F.data == "SET_API_KEY")
        self.dp.callback_query.register(self.secret_key_input, F.data == "SET_SECRET_KEY")
        self.dp.callback_query.register(self.pass_phr_input, F.data == "SET_API_PASSPHRASE")
        self.dp.callback_query.register(self.fin_settings_handler, F.data == "SET_FIN")
        self.dp.callback_query.register(self.margin_size_input, F.data == "SET_MARGIN")
        self.dp.callback_query.register(self.leverage_input, F.data == "SET_LEVERAGE")
        self.dp.callback_query.register(self.margin_mode_input, F.data == "SET_MARGIN_MODE")
        self.dp.callback_query.register(self.market_order_input, F.data == "SET_MARKET_ORDER")
        self.dp.callback_query.register(self.order_timeout_input, F.data == "SET_ORDER_TIMEOUT")

        self.dp.callback_query.register(self.start_button, F.data == "START")
        self.dp.callback_query.register(self.stop_button, F.data == "STOP")

    # ===== Вспомогательные =====
    def _text_contains(self, keys: list[str]):
        def _f(message: types.Message) -> bool:
            if not message.text:
                return False
            txt = message.text.strip().lower()
            return any(k in txt for k in keys)
        return _f

    def _awaiting_input(self, message: types.Message) -> bool:
        chat_id = message.chat.id
        cfg = self.context.users_configs.get(chat_id)
        return bool(cfg and cfg.get("_await_field"))

    def ensure_user_config(self, user_id: int):
        if user_id not in self.context.users_configs:
            self.context.users_configs[user_id] = copy.deepcopy(INIT_USER_CONFIG)
            self.context.queues_msg[user_id] = []

    # ===== Keyboards =====
    def _settings_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔑 OKX", callback_data="SET_OKX")],
            [InlineKeyboardButton(text="💰 FIN SETTINGS", callback_data="SET_FIN")]
        ])

    def _okx_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="API Key", callback_data="SET_API_KEY")],
            [InlineKeyboardButton(text="Secret Key", callback_data="SET_SECRET_KEY")],
            [InlineKeyboardButton(text="PassPhrase", callback_data="SET_API_PASSPHRASE")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="SETTINGS")]
        ])

    def _fin_keyboard(self) -> InlineKeyboardMarkup:
        kb = [
            [InlineKeyboardButton(text="Margin Size", callback_data="SET_MARGIN")],
            [InlineKeyboardButton(text="Margin Mode", callback_data="SET_MARGIN_MODE")],
            [InlineKeyboardButton(text="Leverage", callback_data="SET_LEVERAGE")],
            [InlineKeyboardButton(text="Market Order", callback_data="SET_MARKET_ORDER")],
            [InlineKeyboardButton(text="Order Timeout", callback_data="SET_ORDER_TIMEOUT")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="SETTINGS")]
        ]
        return InlineKeyboardMarkup(inline_keyboard=kb)

    # ===== START / STATUS / STOP =====
    async def start_handler(self, message: types.Message):
        chat_id = message.chat.id
        self.ensure_user_config(chat_id)
        await message.answer("Добро пожаловать! Главное меню снизу 👇", reply_markup=self.main_menu)

    async def settings_cmd(self, message: types.Message):
        chat_id = message.chat.id
        self.ensure_user_config(chat_id)
        await message.answer("Выберите раздел настроек:", reply_markup=self._settings_keyboard())

    async def status_cmd(self, message: types.Message):
        chat_id = message.chat.id
        self.ensure_user_config(chat_id)
        cfg = self.context.users_configs[chat_id]

        status = "В работе" if getattr(self.context, "start_bot_iteration", False) else "Не активен"
        pretty_cfg = format_config(cfg.get("config", {}))

        await message.answer(
            f"📊 Текущий статус: {status}\n\n⚙ Настройки:\n{pretty_cfg}",
            reply_markup=self.main_menu
        )

    async def start_cmd(self, message: types.Message):
        chat_id = message.chat.id
        self.ensure_user_config(chat_id)

        async with self.bot_iteration_lock:
            if self.context.start_bot_iteration or any(
                pos.get("in_position", False)
                for symbol_data in self.context.position_vars.values()
                for side, pos in symbol_data.items()
                if side != "spec"
            ):
                await message.answer("Торговля уже запущена или есть открытые позиции.", reply_markup=self.main_menu)
                return

            cfg = self.context.users_configs[chat_id]
            if validate_user_config(cfg):
                self.context.start_bot_iteration = True
                self.context.stop_bot_iteration = False
                await message.answer("✅ Торговля запущена", reply_markup=self.main_menu)
            else:
                await message.answer("❗ Сначала настройте конфиг полностью", reply_markup=self.main_menu)

    async def stop_cmd(self, message: types.Message):
        chat_id = message.chat.id
        self.ensure_user_config(chat_id)

        async with self.bot_iteration_lock:
            if any(
                pos.get("in_position", False)
                for symbol_data in self.context.position_vars.values()
                for side, pos in symbol_data.items()
                if side != "spec"
            ):
                await message.answer("Сперва закройте все позиции.", reply_markup=self.main_menu)
                return

            if self.context.start_bot_iteration:
                self.context.start_bot_iteration = False
                self.context.stop_bot_iteration = True
                # self.context.users_configs = {}
                await message.answer("⛔ Торговля остановлена", reply_markup=self.main_menu)
            else:
                await message.answer("Данная опция недоступна, поскольку торговля еще не начата.", reply_markup=self.main_menu)

    # ===== HANDLERS ==========
    async def settings_handler(self, callback: types.CallbackQuery):
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)
        await callback.answer()
        await callback.message.edit_text("Выберите раздел настроек:", reply_markup=self._settings_keyboard())

    async def okx_settings_handler(self, callback: types.CallbackQuery):
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)
        await callback.answer()
        await callback.message.edit_text("Настройки OKX:", reply_markup=self._okx_keyboard())

    async def fin_settings_handler(self, callback: types.CallbackQuery):
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)
        await callback.answer()
        await callback.message.edit_text("FIN SETTINGS:", reply_markup=self._fin_keyboard())

    # ===== Обработка текстового ввода =====
    async def text_message_handler(self, message: types.Message):
        chat_id = message.chat.id
        self.ensure_user_config(chat_id)
        cfg = self.context.users_configs.get(chat_id)
        if not cfg or not cfg.get("_await_field"):
            return

        field_info = cfg["_await_field"]
        section, field = field_info["section"], field_info["field"]
        raw = (message.text or "").strip()
        fs = cfg["config"].setdefault(section, {})

        try:
            if section == "fin_settings":
                if field == "leverage":
                    try:
                        val = int(raw)
                        if val == 0:
                            fs[field] = None
                        else:
                            fs[field] = val
                    except:
                        await message.answer("❗ Leverage должен быть числом.")
                        return 

                elif field == "margin_size":
                    try:
                        fs[field] = float(raw.replace(",", "."))
                    except:
                        await message.answer("❗ Margin Size должен быть числом.")
                        return 

                elif field == "margin_mode":
                    if raw not in {"1", "2"}:
                        await message.answer("❗ Введите 1 (ISOLATED) или 2 (CROSSED)")
                        return
                    fs[field] = int(raw)

                elif field == "market_order":
                    if raw == "1":
                        fs[field] = False
                    elif raw == "2":
                        fs[field] = True
                    else:
                        await message.answer("❗ Введите 1 (лимитный) или 2 (по маркету)")
                        return

                elif field == "order_timeout":
                    try:
                        fs[field] = int(raw)
                    except:
                        await message.answer("❗ Order Timeout должен быть числом.")
                        return 

            elif section == "OKX":
                if field in {"api_key", "api_secret", "api_passphrase"}:
                    if not raw:
                        await message.answer("❗ Значение не может быть пустым")
                        return
                    fs[field] = raw

        except Exception as e:
            await message.answer(f"Ошибка: {e}")
            return

        cfg["_await_field"] = None
        await message.answer(f"✅ Значение для {field} сохранено!", reply_markup=self.main_menu)

        if validate_user_config(cfg):
            await message.answer("✅ Конфиг полностью заполнен! Торговлю можно запускать.", reply_markup=self.main_menu)

    # ========= INPUT PROMPTS =========
    async def api_key_input(self, callback: types.CallbackQuery):
        await callback.answer()
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)
        self.context.users_configs[user_id]["_await_field"] = {"section": "OKX", "field": "api_key"}
        await callback.message.answer("Введите API Key:")

    async def secret_key_input(self, callback: types.CallbackQuery):
        await callback.answer()
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)
        self.context.users_configs[user_id]["_await_field"] = {"section": "OKX", "field": "api_secret"}
        await callback.message.answer("Введите Secret Key:")

    async def pass_phr_input(self, callback: types.CallbackQuery):
        await callback.answer()
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)
        self.context.users_configs[user_id]["_await_field"] = {"section": "OKX", "field": "api_passphrase"}
        await callback.message.answer("Введите PassPhrase:")

    async def margin_size_input(self, callback: types.CallbackQuery):
        await callback.answer()
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)
        self.context.users_configs[user_id]["_await_field"] = {"section": "fin_settings", "field": "margin_size"}
        await callback.message.answer("Введите Margin Size (число):")

    async def margin_mode_input(self, callback: types.CallbackQuery):
        await callback.answer()
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)
        self.context.users_configs[user_id]["_await_field"] = {"section": "fin_settings", "field": "margin_mode"}
        await callback.message.answer("Введите Margin Mode (1 -- ISOLATED, 2 -- CROSSED):")

    async def leverage_input(self, callback: types.CallbackQuery):
        await callback.answer()
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)
        self.context.users_configs[user_id]["_await_field"] = {"section": "fin_settings", "field": "leverage"}
        await callback.message.answer("Введите Leverage (целое число). Отключить -- 0:")

    async def market_order_input(self, callback: types.CallbackQuery):
        await callback.answer()
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)
        self.context.users_configs[user_id]["_await_field"] = {"section": "fin_settings", "field": "market_order"}
        await callback.message.answer("Введите тип ордера (1 -- лимитный, 2 -- по маркету):")

    async def order_timeout_input(self, callback: types.CallbackQuery):
        await callback.answer()
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)
        self.context.users_configs[user_id]["_await_field"] = {"section": "fin_settings", "field": "order_timeout"}
        await callback.message.answer("Введите таймаут лимитного ордера (секунды):")

    # ===== START/STOP кнопки inline =====
    async def start_button(self, callback: types.CallbackQuery):
        await callback.answer()
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)

        cfg = self.context.users_configs[user_id]
        if validate_user_config(cfg):
            self.context.start_bot_iteration = True
            await callback.message.answer("✅ Торговля запущена", reply_markup=self.main_menu)
        else:
            await callback.message.answer("❗ Сначала настройте конфиг полностью", reply_markup=self.main_menu)

    async def stop_button(self, callback: types.CallbackQuery):
        if any(
            pos.get("in_position", False)
            for symbol_data in self.context.position_vars.values()
            for side, pos in symbol_data.items()
            if side != "spec"
        ):
            await callback.message.answer("Сперва закройте все позиции.", reply_markup=self.main_menu)
            return
        user_id = callback.from_user.id
        self.ensure_user_config(user_id)

        if self.context.start_bot_iteration:
            self.context.start_bot_iteration = False
            self.context.stop_bot_iteration = True
            await callback.message.answer("⛔ Торговля остановлена", reply_markup=self.main_menu)
        else:
            await callback.message.answer("Это действие невозможно, так как торговля ещё не начата.", reply_markup=self.main_menu)

    # ===== Run / Stop =====
    async def run(self):
        self._polling_task = asyncio.create_task(
            self.dp.start_polling(self.bot, stop_signal=lambda: self._stop_flag)
        )
        await asyncio.sleep(0.1)

    async def stop(self):
        pass