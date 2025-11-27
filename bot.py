#!/usr/bin/env python3
"""
Rebar.uz  –  Telegram bot  (webhook, inline-keyboard, design = site style)
Author:  you
"""
import os
import asyncio
import logging
from typing import Dict, List

import httpx
from bs4 import BeautifulSoup

from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO
)
logger = logging.getLogger("rebar_bot")

# ---------- CONFIG ----------
TOKEN = os.environ["TOKEN"]
WEBHOOK_URL = f"https://{os.environ['REPL_SLUG']}.{os.environ['REPL_OWNER']}.repl.co/telegram"
SOURCE_URL = "https://rebar.uz"
MENU_URL = f"{SOURCE_URL}/menu"
# colours & emoji  =  site style
GREEN = "#27ae60"  # buttons
BLACK = "#1e1e1e"  # background
# -----------------------------

# ---------- DATA LAYER ----------
class RebarAPI:
    """Parses site once at start() and keeps data in RAM."""

    def __init__(self) -> None:
        self.categories: Dict[str, List[Dict[str, str]]] = {}  # title -> [ {name, price, img}, ..]
        self.contacts: Dict[str, str] = {}

    async def start(self) -> None:
        logger.info("Parsing %s ..", SOURCE_URL)
        async with httpx.AsyncClient(timeout=15) as client:
            # ---- main page  (contacts) ----
            r_main = await client.get(SOURCE_URL)
            r_main.raise_for_status()
            soup = BeautifulSoup(r_main.text, "lxml")

            # phone & address
            self.contacts["phone"] = (
                soup.select_one("a[href^='tel:']").get("href").replace("tel:", "")
            )
            self.contacts["address"] = soup.select_one(".footer__addr").get_text(
                strip=True
            )
            self.contacts["instagram"] = soup.select_one(
                "a[href*='instagram']"
            ).get("href")

            # ---- menu page ----
            r_menu = await client.get(MENU_URL)
            r_menu.raise_for_status()
            soup = BeautifulSoup(r_menu.text, "lxml")

            current_category = ""
            for card in soup.select(".menu-card"):
                # category title
                cat = card.select_one(".menu-card__title")
                if cat:
                    current_category = cat.get_text(strip=True)
                    self.categories[current_category] = []
                # items
                for item in card.select(".menu-item"):
                    name = item.select_one(".menu-item__name").get_text(strip=True)
                    price = item.select_one(".menu-item__price").get_text(strip=True)
                    img_tag = item.select_one("img")
                    img = SOURCE_URL + img_tag.get("src") if img_tag else ""
                    self.categories[current_category].append(
                        {"name": name, "price": price, "img": img}
                    )
        logger.info("Loaded %s categories", len(self.categories))


# singleton
API = RebarAPI()
# --------------------------------

# ---------- BOT LOGIC ----------
async def start_command(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/start – главное меню."""
    kb = [
        [InlineKeyboardButton("🍽 Меню", callback_data="main_menu")],
        [InlineKeyboardButton("📞 Контакты", callback_data="contacts")],
        [
            InlineKeyboardButton(
                "🌐 Сайт", web_app=WebAppInfo(url=SOURCE_URL)
            )
        ],
    ]
    await update.message.reply_text(
        "Добро пожаловать в *Rebar.uz* 🥩",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown",
    )


async def show_categories(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать список категорий."""
    query = update.callback_query
    await query.answer()

    kb = [
        [InlineKeyboardButton(f"▫️ {cat}", callback_data=f"cat_{idx}")]
        for idx, cat in enumerate(API.categories)
    ]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="start")])
    await query.edit_message_text(
        "Выберите категорию:", reply_markup=InlineKeyboardMarkup(kb)
    )


async def show_items(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать блюда выбранной категории."""
    query = update.callback_query
    await query.answer()

    cat_idx = int(query.data.split("_")[1])
    category = list(API.categories)[cat_idx]
    items = API.categories[category]

    text = f"*{category}*\n" + "\n".join(
        f"• {it['name']} – {it['price']}" for it in items
    )
    kb = [[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]
    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
    )


async def show_contacts(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        f"*Rebar – стейк-хаус*\n"
        f"📍 {API.contacts['address']}\n"
        f"📞 [Позвонить](tel:{API.contacts['phone']})\n"
        f"📸 [Instagram]({API.contacts['instagram']})"
    )
    kb = [[InlineKeyboardButton("⬅️ Назад", callback_data="start")]]
    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
    )


# ---------- DISPATCH ----------
bot_app = Application.builder().token(TOKEN).build()

bot_app.add_handler(CommandHandler("start", start_command))
bot_app.add_handler(CallbackQueryHandler(show_categories, pattern="^main_menu$"))
bot_app.add_handler(CallbackQueryHandler(show_items, pattern="^cat_"))
bot_app.add_handler(CallbackQueryHandler(show_contacts, pattern="^contacts$"))
bot_app.add_handler(
    CallbackQueryHandler(start_command, pattern="^start$")
)  # вернуть /start

# ---------- FLASK WEBHOOK ----------
flask_app = Flask(__name__)


@flask_app.route("/")
def index():
    return "Rebar.uz bot is running"


@flask_app.post("/telegram")
def webhook():
    """Принять update от Telegram."""
    asyncio.run(
        bot_app.update_queue.put(
            Update.de_json(request.get_json(force=True), bot_app.bot)
        )
    )
    return "ok"


# ---------- START ----------
async def main() -> None:
    await API.start()  # спарсим сайт
    # поставить webhook
    await bot_app.bot.setWebhook(WEBHOOK_URL)
    logger.info("Webhook set to %s", WEBHOOK_URL)
    # запустить flask
    flask_app.run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    asyncio.run(main())
