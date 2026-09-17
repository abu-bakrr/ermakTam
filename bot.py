import asyncio
import logging
import json
import os
import io
import uuid
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import settings_manager
import excel_writer
import receipt_reader

import cloudinary
import cloudinary.uploader

cloudinary.config(
  cloud_name = 'dxjyi9id6',
  api_key = '827649586873527',
  api_secret = 'v6008TVAV21lRyZZvNFYFi4JqBI'
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

USERS_FILE = "users.json"
users_db = {}
PHOTOS_DIR = "photos"

if not os.path.exists(PHOTOS_DIR):
    os.makedirs(PHOTOS_DIR)

def load_users():
    global users_db
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                users_db = {int(k): v for k, v in data.items()}
            except Exception as e:
                logging.error(f"Error loading users: {e}")
                users_db = {}
    else:
        users_db = {}

def save_users():
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users_db, f, ensure_ascii=False, indent=4)

load_users()

class Form(StatesGroup):
    lang = State()
    performer = State()
    confirm_performer = State()

    waiting_receipt = State()
    confirm_receipt = State()
    waiting_qr = State()

    edit_receipt_menu = State()
    wait_edit_value = State()
    wait_direct_grand_total = State()

    shop = State()
    payment = State()
    supplier = State()

    loop_price = State()
    loop_qty = State()
    loop_nom = State()
    loop_add_more = State()

    receipt_tmc = State()
    receipt_note = State()

    confirm = State()

    # Admin Panel States
    admin_menu = State()
    admin_manage_admins = State()
    admin_wait_add_admin = State()
    admin_manage_orgs = State()
    admin_manage_cards = State()
    admin_wait_add_card = State()
    
    admin_manage_shops = State()
    admin_wait_add_shop_name = State()
    admin_wait_add_shop_org = State()

def get_msg(user_id: int, key: str) -> str:
    lang = users_db.get(user_id, {}).get("lang", "ru")
    return config.MESSAGES.get(lang, config.MESSAGES["ru"]).get(key, key)

def get_main_menu_kb(user_id: int) -> ReplyKeyboardMarkup:
    new_btn = get_msg(user_id, "new_record_btn")
    receipt_btn = get_msg(user_id, "receipt_btn")
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=new_btn), KeyboardButton(text=receipt_btn)]],
        resize_keyboard=True
    )

def make_keyboard(user_id: int, items: list[str], add_cancel: bool = True) -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text=items[i]), KeyboardButton(text=items[i+1])] if i+1 < len(items) else [KeyboardButton(text=items[i])] for i in range(0, len(items), 2)]
    if add_cancel:
        buttons.append([KeyboardButton(text=get_msg(user_id, "cancel_btn"))])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_cancel_kb(user_id: int, add_next: bool = False) -> ReplyKeyboardMarkup:
    kb_row = []
    if add_next:
        kb_row.append(KeyboardButton(text=get_msg(user_id, "next_btn")))
    kb_row.append(KeyboardButton(text=get_msg(user_id, "cancel_btn")))
    return ReplyKeyboardMarkup(keyboard=[kb_row], resize_keyboard=True)

@dp.message(F.text.in_([config.MESSAGES["ru"]["cancel_btn"], config.MESSAGES["uz"]["cancel_btn"], "/cancel"]))
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state in [Form.lang.state, Form.performer.state, Form.confirm_performer.state]:
        await message.answer(get_msg(message.from_user.id, "reg_required"))
        return
    await state.clear()
    user_id = message.from_user.id
    if user_id in users_db and "performer" in users_db[user_id]:
        await message.answer(get_msg(user_id, "cancelled"), reply_markup=get_main_menu_kb(user_id))
    else:
        await message.answer(get_msg(user_id, "cancelled"), reply_markup=ReplyKeyboardRemove())

@dp.message(Command("lang"))
async def lang_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Русский"), KeyboardButton(text="O'zbekcha")]],
        resize_keyboard=True
    )
    await message.answer(get_msg(message.from_user.id, "choose_lang_menu"), reply_markup=kb)
    await state.set_state(Form.lang)

@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users_db or "lang" not in users_db[user_id] or "performer" not in users_db[user_id]:
        await lang_cmd(message, state)
    else:
        await message.answer(get_msg(user_id, "main_menu"), reply_markup=get_main_menu_kb(user_id))
        await state.clear()

@dp.message(Command("file"))
async def cmd_file(message: types.Message):
    user_id = message.from_user.id
    lang = users_db.get(user_id, {}).get("lang", "ru")
    if user_id not in settings_manager.get_admins():
        msg = "У вас нет прав для скачивания файла." if lang == "ru" else "Faylni yuklab olish uchun ruxsatingiz yo'q."
        await message.answer(msg)
        return
        
    files = excel_writer.get_all_files()
    if not files:
        msg = "Нет доступных файлов." if lang == "ru" else "Mavjud fayllar yo'q."
        await message.answer(msg)
        return
        
    if len(files) == 1:
        
        filename = files[0]
        file = FSInputFile(filename)
        await message.answer_document(file, caption=f"Файл: {os.path.basename(filename)}")
    else:
        
        buttons = []
        for filename in files:
            basename = os.path.basename(filename)
            buttons.append([InlineKeyboardButton(text=basename, callback_data=f"dl_file_{basename}")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg = "Выберите файл для скачивания:" if lang == "ru" else "Yuklab olish uchun faylni tanlang:"
        await message.answer(msg, reply_markup=kb)

@dp.callback_query(F.data.startswith("dl_file_"))
async def callback_dl_file(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = users_db.get(user_id, {}).get("lang", "ru")
    
    if user_id not in settings_manager.get_admins():
        await callback.answer("У вас нет прав.", show_alert=True)
        return
        
    basename = callback.data.replace("dl_file_", "")
    filename = os.path.join(excel_writer.DATA_DIR, basename)
    
    if os.path.exists(filename):
        file = FSInputFile(filename)
        await callback.message.answer_document(file, caption=f"Файл: {basename}")
        await callback.answer()
    else:
        msg = "Файл не найден." if lang == "ru" else "Fayl topilmadi."
        await callback.answer(msg, show_alert=True)

@dp.message(F.text.in_([config.MESSAGES["ru"]["new_record_btn"], config.MESSAGES["uz"]["new_record_btn"], "/new"]))
async def new_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users_db or "performer" not in users_db[user_id]:
        await lang_cmd(message, state)
        return
    
    await state.update_data(
        is_ai_mode=False,
        items_list=[],
        ai_items=[],
        ai_receipt_date="",
        ai_supplier="",
        photo_path=""
    )
    shops = list(settings_manager.get_shops().keys())
    await message.answer(get_msg(user_id, "choose_shop"), reply_markup=make_keyboard(user_id, shops))
    await state.set_state(Form.shop)

@dp.message(F.text.in_([config.MESSAGES["ru"]["receipt_btn"], config.MESSAGES["uz"]["receipt_btn"]]))
async def receipt_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users_db or "performer" not in users_db[user_id]:
        await lang_cmd(message, state)
        return
    await state.update_data(receipt_photos=[])
    cancel_btn = get_msg(user_id, "cancel_btn")
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=cancel_btn)]],
        resize_keyboard=True
    )
    await message.answer(get_msg(user_id, "send_qr_prompt"), reply_markup=kb)
    await state.set_state(Form.waiting_qr)

@dp.message(Form.waiting_receipt, F.photo)
async def process_receipt_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    file_bytes = io.BytesIO()
    await bot.download_file(file_info.file_path, file_bytes)
    img_data = file_bytes.getvalue()

    data = await state.get_data()
    photos = data.get("receipt_photos", [])
    photos.append(img_data)
    await state.update_data(receipt_photos=photos)

    n = len(photos)
    done_btn = get_msg(user_id, "done_btn")
    cancel_btn = get_msg(user_id, "cancel_btn")
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=done_btn)], [KeyboardButton(text=cancel_btn)]],
        resize_keyboard=True
    )
    await message.answer(get_msg(user_id, "photo_accepted").format(n=n), reply_markup=kb)

@dp.message(Form.waiting_receipt, F.text.in_([
    config.MESSAGES["ru"]["done_btn"],
    config.MESSAGES["uz"]["done_btn"]
]))
async def process_receipt_done(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    photos = data.get("receipt_photos", [])

    if not photos:
        await message.answer(get_msg(user_id, "only_photo"))
        return

    n = len(photos)
    wait_msg = await message.answer(
        get_msg(user_id, "reading_receipt_multi").format(n=n)
    )

    try:
        loop = asyncio.get_event_loop()

        # 1. Scan QR codes for soliq link
        soliq_link = await loop.run_in_executor(None, receipt_reader.find_soliq_link, photos)
        original_photo_path = ",".join(photos) if photos else ""
        ai_results = []
        
        if soliq_link:
            await wait_msg.edit_text(get_msg(user_id, "qr_found").format(link=soliq_link))
            # Try API first
            api_parsed = await loop.run_in_executor(None, receipt_reader.parse_receipt_soliq_api, soliq_link)
            if api_parsed and api_parsed.get("items"):
                ai_results = [api_parsed]
        else:
            # No soliq QR found - fallback to Gemini
            pass


        # Fallback to Gemini if API failed
        if not ai_results:
            accumulated_items = []
            for p in photos:
                try:
                    r = await loop.run_in_executor(None, receipt_reader.parse_receipt_gemini, p, accumulated_items)
                    if isinstance(r, dict):
                        ai_results.append(r)
                        if "items" in r:
                            accumulated_items.extend(r["items"])
                except Exception as e:
                    logging.warning(f"AI parse error for one photo: {e}")

        if not ai_results:
            raise Exception("All AI parsing failed")

        raw_parsed = receipt_reader.merge_receipts(ai_results)
        parsed = await loop.run_in_executor(None, receipt_reader.clean_receipt_with_ai, raw_parsed)
        items = parsed.get("items", [])

        await state.update_data(
            ai_items=items,
            is_ai_mode=True,
            ai_supplier=parsed.get("supplier", ""),
            ai_grand_total=parsed.get("grand_total", ""),
            ai_receipt_date=parsed.get("receipt_date", ""),
            photo_path="",
            items_list=[]
        )

        await wait_msg.delete()

        lines = [get_msg(user_id, "ai_recognized")]
        if parsed.get('receipt_date'):
            lines.append(get_msg(user_id, "ai_date").format(val=parsed['receipt_date']))
        else:
            lines.append(get_msg(user_id, "ai_date_not_found"))
        lines.append(get_msg(user_id, "ai_supplier").format(val=parsed.get('supplier') or '—'))
        lines.append("")
        if items:
            lines.append(get_msg(user_id, "ai_items_header").format(val=len(items)))
            grand_total = 0
            for i, item in enumerate(items, 1):
                nom = item.get("nomenclature", "—")
                price = item.get("price", "—")
                qty = item.get("quantity", "—")
                try:
                    p = float(str(price).replace(",", ".").replace(" ", ""))
                    q = float(str(qty).replace(",", ".").replace(" ", ""))
                    item_total = p * q
                    grand_total += item_total
                    total_str = f"{item_total:,.0f}".replace(",", " ")
                except:
                    total_str = "?"
                lines.append(f"  {i}. <b>{nom}</b>")
                lines.append(get_msg(user_id, "ai_item_calc").format(price=price, qty=qty, total=total_str))
            if parsed.get('grand_total'):
                lines.append(f"\n💰 <b>Сумма:</b> {parsed['grand_total']}")
            elif grand_total > 0:
                grand_total_str = f"{grand_total:,.0f}".replace(",", " ")
                lines.append(f"\n💰 <b>Сумма (расчет):</b> {grand_total_str}")
        else:
            lines.append(get_msg(user_id, "ai_no_items"))

        await message.answer("\n".join(lines), parse_mode="HTML")

        # Go straight to shop selection — no confirmation needed
        await message.answer(
            get_msg(user_id, "ai_yes_success"),
            reply_markup=make_keyboard(user_id, list(settings_manager.get_shops().keys()))
        )
        await state.set_state(Form.shop)

    except Exception as e:
        logging.error(f"OCR error: {e}")
        await wait_msg.delete()
        await state.update_data(is_ai_mode=False, items_list=[], ai_items=[])
        await message.answer(
            get_msg(user_id, "ai_fail"),
            reply_markup=make_keyboard(user_id, list(settings_manager.get_shops().keys()))
        )
        await state.set_state(Form.shop)


@dp.message(Form.confirm_receipt)
async def process_confirm_receipt(message: types.Message, state: FSMContext):
    """Kept for legacy fallback, but no longer used in main flow."""
    user_id = message.from_user.id
    await state.update_data(is_ai_mode=True)
    await message.answer(
        get_msg(user_id, "ai_yes_success"),
        reply_markup=make_keyboard(user_id, list(settings_manager.get_shops().keys()))
    )
    await state.set_state(Form.shop)


@dp.message(Form.waiting_receipt)
async def receipt_no_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await message.answer(get_msg(user_id, "only_photo"))

@dp.message(Form.waiting_qr)
async def process_qr(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    # If user cancels
    if message.text in [config.MESSAGES["ru"]["cancel_btn"], config.MESSAGES["uz"]["cancel_btn"], "/cancel"]:
        return await cancel_handler(message, state)

    wait_msg = await message.answer(get_msg(user_id, "reading_receipt").format(n=1))

    try:
        loop = asyncio.get_event_loop()
        soliq_link = None

        if message.photo:
            photo = message.photo[-1]
            file_info = await bot.get_file(photo.file_id)
            file_bytes = io.BytesIO()
            await bot.download_file(file_info.file_path, file_bytes)
            img_data = file_bytes.getvalue()
            soliq_link = await loop.run_in_executor(None, receipt_reader.find_soliq_link, [img_data])
        elif message.text and "soliq" in message.text.lower():
            soliq_link = message.text

        if soliq_link:
            await wait_msg.edit_text(get_msg(user_id, "qr_found").format(link=soliq_link))
            
            parsed = await loop.run_in_executor(None, receipt_reader.parse_receipt_soliq_api, soliq_link)
            if parsed and parsed.get("items"):
                items = parsed.get("items", [])
                await state.update_data(
                    ai_items=items,
                    is_ai_mode=True,
                    ai_supplier=parsed.get("supplier", ""),
                    ai_grand_total=parsed.get("grand_total", ""),
                    ai_receipt_date=parsed.get("receipt_date", ""),
                    photo_path="", 
                    soliq_link=soliq_link,
                    items_list=[]
                )

                await wait_msg.delete()

                lines = [get_msg(user_id, "ai_recognized")]
                if parsed.get('receipt_date'):
                    lines.append(get_msg(user_id, "ai_date").format(val=parsed['receipt_date']))
                else:
                    lines.append(get_msg(user_id, "ai_date_not_found"))
                lines.append(get_msg(user_id, "ai_supplier").format(val=parsed.get('supplier') or '—'))
                lines.append("")
                if items:
                    lines.append(get_msg(user_id, "ai_items_header").format(val=len(items)))
                    grand_total = 0
                    for i, item in enumerate(items, 1):
                        nom = item.get("nomenclature", "—")
                        price = item.get("price", "—")
                        qty = item.get("quantity", "—")
                        try:
                            p = float(str(price).replace(",", ".").replace(" ", ""))
                            q = float(str(qty).replace(",", ".").replace(" ", ""))
                            item_total = p * q
                            grand_total += item_total
                            total_str = f"{item_total:,.0f}".replace(",", " ")
                        except:
                            total_str = "?"
                        lines.append(f"  {i}. <b>{nom}</b>")
                        lines.append(get_msg(user_id, "ai_item_calc").format(price=price, qty=qty, total=total_str))
                    if parsed.get('grand_total'):
                        lines.append(f"\n💰 <b>Сумма:</b> {parsed['grand_total']}")
                    elif grand_total > 0:
                        grand_total_str = f"{grand_total:,.0f}".replace(",", " ")
                        lines.append(f"\n💰 <b>Сумма (расчет):</b> {grand_total_str}")
                else:
                    lines.append(get_msg(user_id, "ai_no_items"))

                await message.answer("\n".join(lines), parse_mode="HTML")

                # Go straight to shop selection — no confirmation needed
                await message.answer(
                    get_msg(user_id, "ai_yes_success"),
                    reply_markup=make_keyboard(user_id, list(settings_manager.get_shops().keys()))
                )
                await state.set_state(Form.shop)
                return


        # If we reach here, API failed or no QR link found.
        # Fallback to asking for full receipt photo
        await wait_msg.delete()
        lang = users_db.get(user_id, {}).get("lang", "ru")
        fallback_msg = "API Soliq не ответил или ссылка неверна. Пожалуйста, отправьте полное фото чека для распознавания (или нажмите Готово):" if lang == "ru" else "API Soliq javob bermadi yoki havola noto'g'ri. Iltimos, chekni rasmini yuboring (yoki Tayyor bosing):"
        
        done_btn = get_msg(user_id, "done_btn")
        cancel_btn = get_msg(user_id, "cancel_btn")
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=done_btn)], [KeyboardButton(text=cancel_btn)]],
            resize_keyboard=True
        )
        await message.answer(fallback_msg, reply_markup=kb)
        await state.update_data(receipt_photos=[])
        await state.set_state(Form.waiting_receipt)

    except Exception as e:
        logging.error(f"QR OCR error: {e}")
        await wait_msg.delete()
        
        lang = users_db.get(user_id, {}).get("lang", "ru")
        fallback_msg = "Ошибка при обработке QR. Пожалуйста, отправьте полное фото чека для распознавания:" if lang == "ru" else "QR kodni ishlashda xatolik. Iltimos, chekni to'liq rasmini yuboring:"
        
        done_btn = get_msg(user_id, "done_btn")
        cancel_btn = get_msg(user_id, "cancel_btn")
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=done_btn)], [KeyboardButton(text=cancel_btn)]],
            resize_keyboard=True
        )
        await message.answer(fallback_msg, reply_markup=kb)
        await state.update_data(receipt_photos=[])
        await state.set_state(Form.waiting_receipt)

@dp.message(Form.lang)
async def process_lang(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text == "Русский":
        lang = "ru"
    elif message.text == "O'zbekcha":
        lang = "uz"
    else:
        await message.answer(get_msg(user_id, "choose_lang_menu"))
        return

    if user_id not in users_db:
        users_db[user_id] = {}
    users_db[user_id]["lang"] = lang
    save_users()

    await message.answer(get_msg(user_id, "enter_performer"), reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.performer)

@dp.message(Form.performer)
async def process_performer(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.update_data(proposed_performer=message.text.strip())
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=get_msg(user_id, "yes")), KeyboardButton(text=get_msg(user_id, "no"))]],
        resize_keyboard=True
    )
    await message.answer(
        get_msg(user_id, "confirm_performer").format(performer=message.text.strip()),
        reply_markup=kb
    )
    await state.set_state(Form.confirm_performer)

@dp.message(Form.confirm_performer)
async def process_confirm_performer(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text == get_msg(user_id, "yes"):
        data = await state.get_data()
        users_db[user_id]["performer"] = data.get("proposed_performer", "")
        save_users()
        await message.answer(get_msg(user_id, "performer_saved"))
        await message.answer(get_msg(user_id, "main_menu"), reply_markup=get_main_menu_kb(user_id))
        await state.clear()
    elif message.text == get_msg(user_id, "no"):
        await message.answer(get_msg(user_id, "enter_performer"), reply_markup=ReplyKeyboardRemove())
        await state.set_state(Form.performer)
    else:
        await message.answer(get_msg(user_id, "press_yes_no"))

@dp.message(Form.shop)
async def process_shop(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text not in settings_manager.get_shops():
        await message.answer(get_msg(user_id, "invalid_shop"))
        return
        
    shop = message.text
    org = settings_manager.get_shops()[shop]
    await state.update_data(shop=shop, org=org)
    
    cards = settings_manager.get_org_cards(org)
    
    cash_btn = get_msg(user_id, "cash_btn")
    buttons = cards + [cash_btn]
    
    await message.answer(get_msg(user_id, "choose_payment"), reply_markup=make_keyboard(user_id, buttons))
    await state.set_state(Form.payment)

@dp.message(Form.payment)
async def process_payment(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    cash_btn = get_msg(user_id, "cash_btn")
    if message.text == cash_btn:
        await state.update_data(payment_type="НАЛ", card_number="")
    else:
        await state.update_data(payment_type="БЕЗНАЛ", card_number=message.text)
    
    data = await state.get_data()
    is_ai_mode = data.get("is_ai_mode", False)
    
    if is_ai_mode:
        
        await state.update_data(supplier=data.get("ai_supplier", ""))
        await start_item_loop(message, state)
    else:
        
        hint = get_msg(user_id, "ai_hint").format(val=data.get("ai_supplier", "")) if data.get("ai_supplier") else ""
        await message.answer(get_msg(user_id, "enter_supplier") + hint, reply_markup=get_cancel_kb(user_id))
        await state.set_state(Form.supplier)

@dp.message(Form.supplier)
async def process_supplier(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.update_data(supplier=message.text)
    await start_item_loop(message, state)

async def start_item_loop(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    is_ai_mode = data.get("is_ai_mode", False)
    ai_items = data.get("ai_items", [])
    items_list = data.get("items_list", [])
    
    if is_ai_mode:
        if not ai_items:
            
            await message.answer(get_msg(user_id, "enter_tmc"), reply_markup=get_cancel_kb(user_id))
            await state.set_state(Form.receipt_tmc)
            return
            
        current_ai_item = ai_items.pop(0)
        items_list.append(current_ai_item)
        await state.update_data(ai_items=ai_items, items_list=items_list)
        
        nom = current_ai_item.get("nomenclature", "?")
        await message.answer(f"✅ <b>{nom}</b> — добавлен", parse_mode="HTML")
        
        await start_item_loop(message, state)
    else:
        
        await state.update_data(current_item={})
        await message.answer(get_msg(user_id, "current_item_manual"), parse_mode="HTML")
        await message.answer(get_msg(user_id, "enter_price"), reply_markup=get_cancel_kb(user_id))
        await state.set_state(Form.loop_price)

@dp.message(Form.loop_price)
async def process_loop_price(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        float(message.text.replace(",", ".").replace(" ", ""))
    except ValueError:
        await message.answer(get_msg(user_id, "invalid_number"), reply_markup=get_cancel_kb(user_id))
        return
        
    data = await state.get_data()
    current_item = data.get("current_item", {})
    current_item["price"] = message.text.replace(",", ".").replace(" ", "")
    await state.update_data(current_item=current_item)
    
    await message.answer(get_msg(user_id, "enter_qty"), reply_markup=get_cancel_kb(user_id))
    await state.set_state(Form.loop_qty)

@dp.message(Form.loop_qty)
async def process_loop_qty(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        float(message.text.replace(",", "."))
    except ValueError:
        await message.answer(get_msg(user_id, "invalid_number"), reply_markup=get_cancel_kb(user_id))
        return
        
    data = await state.get_data()
    current_item = data.get("current_item", {})
    current_item["quantity"] = message.text.replace(",", ".")
    await state.update_data(current_item=current_item)
    
    await message.answer(get_msg(user_id, "enter_nom"), reply_markup=get_cancel_kb(user_id))
    await state.set_state(Form.loop_nom)

@dp.message(Form.loop_nom)
async def process_loop_nom(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    current_item = data.get("current_item", {})
    current_item["nomenclature"] = message.text
    
    items_list = data.get("items_list", [])
    items_list.append(current_item)
    await state.update_data(current_item={}, items_list=items_list)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=get_msg(user_id, "yes")), KeyboardButton(text=get_msg(user_id, "no"))]
        ],
        resize_keyboard=True
    )
    await message.answer(get_msg(user_id, "add_more_prompt"), reply_markup=kb)
    await state.set_state(Form.loop_add_more)

@dp.message(Form.loop_add_more)
async def process_loop_add_more(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text == get_msg(user_id, "yes"):
        await start_item_loop(message, state)
    elif message.text == get_msg(user_id, "no"):
        
        await message.answer(get_msg(user_id, "enter_tmc"), reply_markup=get_cancel_kb(user_id))
        await state.set_state(Form.receipt_tmc)
    else:
        await message.answer(get_msg(user_id, "press_yes_no"))

@dp.message(Form.receipt_tmc)
async def process_receipt_tmc(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.update_data(tmc_group=message.text)
    await message.answer(get_msg(user_id, "enter_note"), reply_markup=get_cancel_kb(user_id, add_next=True))
    await state.set_state(Form.receipt_note)

@dp.message(Form.receipt_note)
async def process_receipt_note(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text == get_msg(user_id, "next_btn"):
        await state.update_data(note="")
    else:
        await state.update_data(note=message.text)
    await finish_and_confirm(message, state)

async def finish_and_confirm(message: types.Message, state: FSMContext):
    """Directly saves the record without asking for confirmation."""
    user_id = message.from_user.id
    data = await state.get_data()
    items = data.get("items_list", [])
    
    if not items:
        await message.answer(get_msg(user_id, "error"), reply_markup=get_main_menu_kb(user_id))
        await state.clear()
        return

    performer = users_db.get(user_id, {}).get("performer", "Неизвестно")
    shop = data.get("shop", "")
    org = settings_manager.get_shops().get(shop, "")
    payment = data.get('payment_type', '')
    if data.get('card_number'):
        payment += f" ({data.get('card_number')})"

    # Show summary before saving
    lines = [get_msg(user_id, "final_check_header")]
    lines.append(get_msg(user_id, "final_shop").format(val=shop))
    lines.append(get_msg(user_id, "final_payment").format(val=payment))
    lines.append(get_msg(user_id, "final_supplier").format(val=data.get('supplier')))
    lines.append(get_msg(user_id, "final_items_header").format(val=len(items)))
    
    grand_total = 0
    for i, item in enumerate(items, 1):
        try:
            p_str = str(item.get("price", "0")).replace(",", ".").replace(" ", "")
            q_str = str(item.get("quantity", "0")).replace(",", ".").replace(" ", "")
            price_val = float(p_str) if p_str else 0
            qty_val = float(q_str) if q_str else 0
            total = price_val * qty_val
            grand_total += total
        except:
            total = 0
        lines.append(get_msg(user_id, "final_item_line").format(
            i=i, nom=item.get('nomenclature'), qty=item.get('quantity'),
            price=item.get('price'), total=f"{total:,.0f}".replace(",", " ")
        ))
    
    ai_grand_total = data.get("ai_grand_total")
    if data.get("is_ai_mode") and ai_grand_total:
        lines.append(get_msg(user_id, "final_total").format(val=f"{ai_grand_total}"))
    else:
        lines.append(get_msg(user_id, "final_total").format(val=f"{grand_total:,.0f}".replace(",", " ")))

    await message.answer("\n".join(lines), parse_mode="HTML")

    # Save directly
    record_data = {
        "shop": shop,
        "organization": org,
        "performer": performer,
        "payment_type": data.get("payment_type", ""),
        "card_number": data.get("card_number", ""),
        "supplier": data.get("supplier", ""),
        "receipt_date": data.get("ai_receipt_date", ""),
        "items": items,
        "photo_path": data.get("photo_path", ""),
        "tmc_group": data.get("tmc_group", ""),
        "note": data.get("note", "")
    }
    try:
        excel_writer.add_record(record_data)
        await message.answer(get_msg(user_id, "success"), reply_markup=get_main_menu_kb(user_id))
    except Exception as e:
        logging.error(f"Error saving to excel: {e}")
        await message.answer(get_msg(user_id, "error") + f"\n{e}", reply_markup=get_main_menu_kb(user_id))
    
    await state.clear()


@dp.message(Form.confirm)
async def process_confirm(message: types.Message, state: FSMContext):
    """Direct save — no longer prompts for confirmation."""
    user_id = message.from_user.id
    data = await state.get_data()
    
    performer = users_db.get(user_id, {}).get("performer", "Неизвестно")
    shop = data.get("shop", "")
    org = settings_manager.get_shops().get(shop, "")
    
    record_data = {
        "shop": shop,
        "organization": org,
        "performer": performer,
        "payment_type": data.get("payment_type", ""),
        "card_number": data.get("card_number", ""),
        "supplier": data.get("supplier", ""),
        "receipt_date": data.get("ai_receipt_date", ""),
        "items": data.get("items_list", []),
        "photo_path": data.get("photo_path", ""),
        "tmc_group": data.get("tmc_group", ""),
        "note": data.get("note", "")
    }
    
    try:
        excel_writer.add_record(record_data)
        await message.answer(get_msg(user_id, "success"), reply_markup=get_main_menu_kb(user_id))
    except Exception as e:
        logging.error(f"Error saving to excel: {e}")
        await message.answer(get_msg(user_id, "error") + f"\n{e}", reply_markup=get_main_menu_kb(user_id))
    
    await state.clear()



@dp.message(Form.wait_direct_grand_total)
async def process_direct_grand_total(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text == get_msg(user_id, "edit_full_manual_btn"):
        await state.update_data(is_ai_mode=False, ai_items=[])
        await message.answer(
            get_msg(user_id, "ai_no_manual"),
            reply_markup=make_keyboard(user_id, list(settings_manager.get_shops().keys()))
        )
        await state.set_state(Form.shop)
        return
        
    # User entered a new sum
    await state.update_data(ai_grand_total=message.text, is_ai_mode=True)
    await message.answer(
        get_msg(user_id, "edit_saved"),
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer(
        get_msg(user_id, "ai_yes_success"),
        reply_markup=make_keyboard(user_id, list(settings_manager.get_shops().keys()))
    )
    await state.set_state(Form.shop)

# === ADMIN PANEL HANDLERS ===

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in settings_manager.get_admins():
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Управление Админами", callback_data="admin_manage_admins")],
        [InlineKeyboardButton(text="Управление Картами", callback_data="admin_manage_orgs")],
        [InlineKeyboardButton(text="Управление Цехами", callback_data="admin_manage_shops")]
    ])
    await message.answer("Панель администратора:", reply_markup=kb)
    await state.set_state(Form.admin_menu)

@dp.callback_query(F.data == "admin_manage_admins")
async def cb_manage_admins(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in settings_manager.get_admins():
        await callback.answer("Нет прав.", show_alert=True)
        return
    
    admins = settings_manager.get_admins()
    text = f"Текущие администраторы ({len(admins)}):\n" + "\n".join(map(str, admins))
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить админа", callback_data="admin_add_admin")],
        [InlineKeyboardButton(text="Удалить админа", callback_data="admin_remove_admin")],
        [InlineKeyboardButton(text="Назад", callback_data="admin_back_to_main")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(Form.admin_manage_admins)
    await callback.answer()

@dp.callback_query(F.data == "admin_add_admin")
async def cb_add_admin(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Отправьте Telegram ID нового администратора (только цифры):")
    await state.set_state(Form.admin_wait_add_admin)
    await callback.answer()

@dp.message(Form.admin_wait_add_admin)
async def process_add_admin(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in settings_manager.get_admins():
        return
    if not message.text.isdigit():
        await message.answer("Пожалуйста, отправьте корректный числовой ID.")
        return
    new_admin_id = int(message.text)
    settings_manager.add_admin(new_admin_id)
    await message.answer(f"Администратор {new_admin_id} добавлен.")
    
    # Return to menu
    await admin_cmd(message, state)

@dp.callback_query(F.data == "admin_remove_admin")
async def cb_remove_admin(callback: types.CallbackQuery, state: FSMContext):
    admins = settings_manager.get_admins()
    buttons = []
    for adm in admins:
        buttons.append([InlineKeyboardButton(text=f"Удалить {adm}", callback_data=f"admin_deladm_{adm}")])
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="admin_manage_admins")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("Выберите администратора для удаления:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_deladm_"))
async def cb_do_remove_admin(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in settings_manager.get_admins():
        return
    
    del_id = int(callback.data.split("_")[-1])
    if del_id == user_id:
        await callback.answer("Вы не можете удалить самого себя!", show_alert=True)
        return
        
    settings_manager.remove_admin(del_id)
    await callback.answer(f"Админ {del_id} удален.", show_alert=True)
    await cb_manage_admins(callback, state)

@dp.callback_query(F.data == "admin_back_to_main")
async def cb_admin_back_main(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await admin_cmd(callback.message, state)
    await callback.answer()

# === MANAGE ORG CARDS ===
@dp.callback_query(F.data == "admin_manage_orgs")
async def cb_manage_orgs(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in settings_manager.get_admins():
        return
        
    orgs = list(set(settings_manager.get_shops().values()))
    buttons = []
    for org in orgs:
        buttons.append([InlineKeyboardButton(text=org, callback_data=f"admin_org_{org}")])
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="admin_back_to_main")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("Выберите организацию:", reply_markup=kb)
    await state.set_state(Form.admin_manage_orgs)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_org_"))
async def cb_org_selected(callback: types.CallbackQuery, state: FSMContext):
    org = callback.data.replace("admin_org_", "")
    cards = settings_manager.get_org_cards(org)
    
    await state.update_data(admin_selected_org=org)
    
    text = f"Организация: {org}\nТекущие карты:\n"
    if not cards:
        text += "Нет привязанных карт."
    else:
        text += "\n".join(cards)
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить карту", callback_data="admin_add_card")],
        [InlineKeyboardButton(text="Удалить карту", callback_data="admin_remove_card")],
        [InlineKeyboardButton(text="Назад", callback_data="admin_manage_orgs")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(Form.admin_manage_cards)
    await callback.answer()

@dp.callback_query(F.data == "admin_add_card")
async def cb_add_card(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Отправьте номер новой карты в чат:")
    await state.set_state(Form.admin_wait_add_card)
    await callback.answer()

@dp.message(Form.admin_wait_add_card)
async def process_add_card(message: types.Message, state: FSMContext):
    data = await state.get_data()
    org = data.get("admin_selected_org")
    if not org:
        await admin_cmd(message, state)
        return
        
    card = message.text.strip()
    settings_manager.add_org_card(org, card)
    await message.answer(f"Карта {card} добавлена для {org}.")
    await admin_cmd(message, state)

@dp.callback_query(F.data == "admin_remove_card")
async def cb_remove_card(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    org = data.get("admin_selected_org")
    if not org:
        await callback.answer("Ошибка организации.", show_alert=True)
        return
        
    cards = settings_manager.get_org_cards(org)
    buttons = []
    for i, card in enumerate(cards):
        # Callback data max length is 64 chars, so we use index
        buttons.append([InlineKeyboardButton(text=f"Удалить {card}", callback_data=f"admin_delcard_{i}")])
    buttons.append([InlineKeyboardButton(text="Назад", callback_data=f"admin_org_{org}")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("Выберите карту для удаления:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_delcard_"))
async def cb_do_remove_card(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    org = data.get("admin_selected_org")
    if not org:
        return
        
    idx = int(callback.data.split("_")[-1])
    cards = settings_manager.get_org_cards(org)
    
    if 0 <= idx < len(cards):
        card = cards[idx]
        settings_manager.remove_org_card(org, card)
        await callback.answer(f"Карта удалена.", show_alert=True)
    
    # Refresh cards view
    callback.data = f"admin_org_{org}"
    await cb_org_selected(callback, state)

# === END ADMIN PANEL ===

# === MANAGE SHOPS ===
@dp.callback_query(F.data == "admin_manage_shops")
async def cb_manage_shops(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.fromuser.id if hasattr(callback, "from_user") else callback.from_user.id
    if user_id not in settings_manager.get_admins():
        return
        
    shops = settings_manager.get_shops()
    text = "Текущие цехи:\n\n"
    for shop, org in shops.items():
        text += f"🏭 <b>{shop}</b> -> 🏢 {org}\n"
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить цех", callback_data="admin_add_shop")],
        [InlineKeyboardButton(text="Удалить цех", callback_data="admin_remove_shop")],
        [InlineKeyboardButton(text="Назад", callback_data="admin_back_to_main")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(Form.admin_manage_shops)
    await callback.answer()

@dp.callback_query(F.data == "admin_add_shop")
async def cb_add_shop(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Отправьте название нового цеха (например: Писта 2):")
    await state.set_state(Form.admin_wait_add_shop_name)
    await callback.answer()

@dp.message(Form.admin_wait_add_shop_name)
async def process_add_shop_name(message: types.Message, state: FSMContext):
    shop_name = message.text.strip()
    await state.update_data(admin_new_shop_name=shop_name)
    
    orgs = list(set(settings_manager.get_shops().values()))
    text = f"Цех: <b>{shop_name}</b>\n\nТеперь введите название организации для этого цеха, или выберите из существующих:"
    
    buttons = []
    for org in orgs:
        buttons.append([KeyboardButton(text=org)])
    
    if buttons:
        kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, parse_mode="HTML")
        
    await state.set_state(Form.admin_wait_add_shop_org)

@dp.message(Form.admin_wait_add_shop_org)
async def process_add_shop_org(message: types.Message, state: FSMContext):
    org_name = message.text.strip()
    data = await state.get_data()
    shop_name = data.get("admin_new_shop_name")
    
    if not shop_name:
        await admin_cmd(message, state)
        return
        
    settings_manager.add_shop(shop_name, org_name)
    
    await message.answer(f"Цех <b>{shop_name}</b> успешно привязан к организации <b>{org_name}</b>.", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await admin_cmd(message, state)

@dp.callback_query(F.data == "admin_remove_shop")
async def cb_remove_shop(callback: types.CallbackQuery, state: FSMContext):
    shops = settings_manager.get_shops()
    buttons = []
    for i, shop in enumerate(shops.keys()):
        # Callback data max length is 64 chars
        buttons.append([InlineKeyboardButton(text=f"Удалить {shop}", callback_data=f"admin_delshop_{i}")])
        
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="admin_manage_shops")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("Выберите цех для удаления:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_delshop_"))
async def cb_do_remove_shop(callback: types.CallbackQuery, state: FSMContext):
    idx = int(callback.data.split("_")[-1])
    shops = list(settings_manager.get_shops().keys())
    
    if 0 <= idx < len(shops):
        shop = shops[idx]
        settings_manager.remove_shop(shop)
        await callback.answer(f"Цех удален.", show_alert=True)
    
    # Refresh shop view
    await cb_manage_shops(callback, state)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
