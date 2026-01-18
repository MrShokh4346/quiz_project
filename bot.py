import asyncio
import json
import random
import logging
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, PollAnswer, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import os
from aiohttp import web
from aiogram import types
from dotenv import load_dotenv

load_dotenv()
# ===================== CONFIG =====================
BOT_TOKEN=os.getenv("BOT_TOKEN")
QUESTIONS_FILE = "telegram_quiz.json"
WEBHOOK_URL=os.getenv("WEBHOOK_URL")

# =================================================

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Savollarni yuklash (faqat 2–10 ta variantli)
try:
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)["questions"]

    QUESTIONS = []
    for q in raw:
        try:
            text = q["question"].strip()
            options = [opt.strip() for opt in q["options"]]
            correct = q["solution"] - 1
            if 2 <= len(options) <= 10 and 0 <= correct < len(options):
                QUESTIONS.append((text, options, correct))
        except:
            continue

    print(f"To‘g‘ri savollar yuklandi: {len(QUESTIONS)}")
except Exception as e:
    print("XATO:", e)
    QUESTIONS = []

if not QUESTIONS:
    print("Bot ishlamaydi — savollar yo‘q!")
    exit()

TOTAL = len(QUESTIONS)

class States(StatesGroup):
    choosing_count = State()
    choosing_range = State()
    playing = State()

user_data = {}

def get_count_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="30 ta", callback_data="count_30")],
        [InlineKeyboardButton(text="50 ta", callback_data="count_50")],
        [InlineKeyboardButton(text="100 ta", callback_data="count_100")],
        [InlineKeyboardButton(text="150 ta", callback_data="count_150")],
        [InlineKeyboardButton(text="200 ta", callback_data="count_200")],
        [InlineKeyboardButton(text="Barchasi", callback_data="count_all")],
    ])

def get_range_keyboard(count: str):
    count = TOTAL if count == "all" else int(count)
    buttons = []
    for start in range(1, TOTAL + 1, count):
        end = min(start + count - 1, TOTAL)
        text = f"{start}–{end}"
        if end == TOTAL:
            text += " (oxirgi)"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"range_{start}_{end}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Har savol uchun tugmalar
def get_quiz_keyboard(user_range: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        # [InlineKeyboardButton(text=f"Diapazon: {user_range}", callback_data="show_range")],
        [InlineKeyboardButton(text="Testni to‘xtatish", callback_data="stop_quiz")]
    ])

@router.message(CommandStart())
@router.message(F.text == "Savollar")
async def start(message: Message, state: FSMContext):
    await state.clear()

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
                [#KeyboardButton(text="Start"), 
                KeyboardButton(text="Savollar")]
                # [KeyboardButton(text="❌ Close")]
            ],
            resize_keyboard=True
        )
    await message.answer("Start", reply_markup=keyboard)

    await message.answer(
        f"<b>Test Bot</b>\n\n"
        f"Jami savollar: <b>{TOTAL}</b>\n\n"
        f"Nechta savol ishlaysiz?",
        reply_markup=get_count_keyboard()
        # reply_markup=keyboard
    )
    await state.set_state(States.choosing_count)

@router.callback_query(F.data.startswith("count_"))
async def choose_count(call: CallbackQuery, state: FSMContext):
    count = call.data.split("_")[1]
    await call.message.edit_text(
        f"Tanlandi: <b>{'Barcha' if count=='all' else count + ' ta'}</b>\n\n"
        f"Diapazonni tanlang:",
        reply_markup=get_range_keyboard(count)
    )
    await state.set_state(States.choosing_range)
    await state.update_data(count=count if count != "all" else TOTAL)
    await call.answer()

@router.callback_query(F.data.startswith("range_"))
async def choose_range(call: CallbackQuery, state: FSMContext):
    _, start, end = call.data.split("_")
    start, end = int(start), int(end)

    indices = [i for i in range(start-1, end) if i < len(QUESTIONS)]
    if not indices:
        await call.answer("Bu diapazonda savol yo‘q!", show_alert=True)
        return

    random.shuffle(indices)
    selected = [QUESTIONS[i] for i in indices]

    user_id = call.from_user.id
    user_range = f"{start}–{end}"

    user_data[user_id] = {
        "score": 0,
        "current": 0,
        "total": len(selected),
        "questions": selected,
        "answered": False,
        "timer_task": None,
        "range": user_range
    }

    await state.set_state(States.playing)
    await call.message.edit_text(
        f"<b>Test boshlandi!</b>\n\n"
        f"Diapazon: <b>{user_range}</b>\n"
        f"Savollar: <b>{len(selected)}</b> ta\n\n"
        f"Har bir savolga 30 soniya!",
        reply_markup=None
    )
    await asyncio.sleep(1.5)
    await send_question(user_id)
    await call.answer()

async def send_question(user_id: int):
    data = user_data[user_id]
    if data["current"] >= data["total"]:
        await show_results(user_id)
        return

    q_text, options, correct = data["questions"][data["current"]]
    data["answered"] = False
    data["timer_task"] = asyncio.create_task(timer_expired(user_id))

    await bot.send_poll(
        chat_id=user_id,
        question=f"{data['range']} • {data['current']+1}/{data['total']}\n\n{q_text}",
        options=options,
        type="quiz",
        correct_option_id=correct + 1,
        is_anonymous=False,
        open_period=30,
        explanation="Vaqt tugadi!",
        reply_markup=get_quiz_keyboard(data["range"])  # YANGI TUGMALAR
    )



# async def send_question(user_id: int):
#     data = user_data[user_id]
#     if data["current"] >= data["total"]:
#         await show_results(user_id)
#         return

#     q_text, options, correct = data["questions"][data["current"]]

#     # Shuffle options
#     opt_with_index = list(enumerate(options))
#     random.shuffle(opt_with_index)

#     options = [o for _, o in opt_with_index]
#     correct = next(idx for idx, (old_idx, _) in enumerate(opt_with_index) if old_idx == correct)

#     data["answered"] = False
#     data["timer_task"] = asyncio.create_task(timer_expired(user_id))

#     await bot.send_poll(
#         chat_id=user_id,
#         question=f"{data['range']} • {data['current']+1}/{data['total']}\n\n{q_text}",
#         options=options,
#         type="quiz",
#         correct_option_id=correct, #+ 1,
#         is_anonymous=False,
#         open_period=30,
#         explanation="Vaqt tugadi!",
#         reply_markup=get_quiz_keyboard(data["range"])
#     )



async def timer_expired(user_id: int):
    await asyncio.sleep(30)
    if user_id not in user_data or user_data[user_id]["answered"]:
        return
    user_data[user_id]["current"] += 1
    await bot.send_message(user_id, "Vaqt tugadi! Keyingi savol...")
    await asyncio.sleep(1.5)
    await send_question(user_id)

@router.poll_answer()
async def handle_answer(poll_answer: PollAnswer):
    user_id = poll_answer.user.id
    if user_id not in user_data:
        return
    data = user_data[user_id]
    if data["answered"]:
        return

    selected = poll_answer.option_ids[0]
    correct = data["questions"][data["current"]][2]
    if selected == correct:
        data["score"] += 1

    data["answered"] = True
    if data["timer_task"]:
        data["timer_task"].cancel()

    data["current"] += 1
    await asyncio.sleep(2)
    await send_question(user_id)

# YANGI TUGMALAR UCHUN
# @router.message(F.text == "Savollar")
@router.callback_query(F.data == "show_range")
async def show_range(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id in user_data:
        await call.answer(f"Joriy diapazon: {user_data[user_id]['range']}", show_alert=True)
    else:
        await call.answer("Test boshlanmagan")

@router.callback_query(F.data == "stop_quiz")
async def stop_quiz(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id in user_data:
        # Timer bekor qilish
        if user_data[user_id]["timer_task"]:
            user_data[user_id]["timer_task"].cancel()
        await call.message.edit_reply_markup(reply_markup=None)
        # await call.answer("Test to‘xtatildi!", show_alert=True)
        await show_results(user_id)
    else:
        await call.answer("Test topilmadi")

async def show_results(user_id: int):
    if user_id not in user_data:
        return
    data = user_data[user_id]
    score = data["score"]
    percent = score / data["total"] * 100 if data["total"] else 0

    text = f"<b>Test yakunlandi!</b>\n\n"
    text += f"Diapazon: <b>{data['range']}</b>\n"
    text += f"Natija: <b>{score}/{data['total']}</b> ({percent:.1f}%)\n\n"

    if percent >= 90:
        text += "Ajoyib!"
    elif percent >= 70:
        text += "Juda yaxshi!"
    elif percent >= 50:
        text += "Yaxshi"
    else:
        text += "Yana mashq qiling!"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Yana boshlash", callback_data="restart")
    ]])

    await bot.send_message(user_id, text, reply_markup=kb)
    del user_data[user_id]

@router.callback_query(F.data == "restart")
async def restart(call: CallbackQuery, state: FSMContext):
    await call.message.delete()
    await start(call.message, state)

async def main():
    print(f"Bot ishga tushdi! Mavjud savollar: {len(QUESTIONS)}")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

async def handle(request):
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)  # <-- correct for Aiogram 3.3+
    return web.Response(text="OK")

app = web.Application()
app.router.add_post(f"/{BOT_TOKEN}", handle)

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL + "/" + BOT_TOKEN)

app.on_startup.append(on_startup)

if __name__ == "__main__":
    if WEBHOOK_URL:
        web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
    else:
        import asyncio
        asyncio.run(main())