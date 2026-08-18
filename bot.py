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
    if user_id not in config.ADMIN_IDS:
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
    
    if user_id not in config.ADMIN_IDS:
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
    shops = list(config.SHOP_TO_ORG.keys())
    await message.answer(get_msg(user_id, "choose_shop"), reply_markup=make_keyboard(user_id, shops))
    await state.set_state(Form.shop)

@dp.message(F.text.in_([config.MESSAGES["ru"]["receipt_btn"], config.MESSAGES["uz"]["receipt_btn"]]))
async def receipt_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users_db or "performer" not in users_db[user_id]:
        await lang_cmd(message, state)
        return
    await state.update_data(receipt_photos=[])
    done_btn = get_msg(user_id, "done_btn")
    cancel_btn = get_msg(user_id, "cancel_btn")
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=done_btn)], [KeyboardButton(text=cancel_btn)]],
        resize_keyboard=True
    )
    await message.answer(get_msg(user_id, "send_receipt_prompt"), reply_markup=kb)
    await state.set_state(Form.waiting_receipt)

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

        if soliq_link:
            await wait_msg.edit_text(get_msg(user_id, "qr_found").format(link=soliq_link))
            photo_path = soliq_link
        else:
            # No soliq QR found - ask user to send QR photo
            await wait_msg.delete()
            await state.update_data(receipt_photos=photos)
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=get_msg(user_id, "cancel_btn"))]],
                resize_keyboard=True
            )
            await message.answer(get_msg(user_id, "qr_not_found"), reply_markup=kb)
            await state.set_state(Form.waiting_qr)
            return

        def upload_to_cloudinary(img_data):
            try:
                res = cloudinary.uploader.upload(img_data, resource_type="image")
                return res.get("secure_url", "")
            except Exception as e:
                logging.warning(f"Cloudinary upload failed: {e}")
                return ""

        cloud_tasks = [
            loop.run_in_executor(None, upload_to_cloudinary, p)
            for p in photos
        ]

        ai_results = []
        accumulated_items = []

        for p in photos:
            try:
                # Pass accumulated_items to the parser
                r = await loop.run_in_executor(None, receipt_reader.parse_receipt_gemini, p, accumulated_items)
                if isinstance(r, dict):
                    ai_results.append(r)
                    if "items" in r:
                        accumulated_items.extend(r["items"])
            except Exception as e:
                logging.warning(f"AI parse error for one photo: {e}")

        cloudinary_urls = await asyncio.gather(*cloud_tasks)
        cloudinary_url = ",".join(url for url in cloudinary_urls if url)

        if not ai_results:
            raise Exception("All AI parsing failed")

        raw_parsed = receipt_reader.merge_receipts(ai_results)

        # Final AI cleanup
        parsed = await loop.run_in_executor(None, receipt_reader.clean_receipt_with_ai, raw_parsed)
        items = parsed.get("items", [])

        await state.update_data(
            ai_items=items,
            ai_supplier=parsed.get("supplier", ""),
            ai_receipt_date=parsed.get("receipt_date", ""),
            photo_path=photo_path,  # Use soliq link as photo_path
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

            if grand_total > 0:
                grand_total_str = f"{grand_total:,.0f}".replace(",", " ")
                lines.append(f"\n💰 <b>Общая сумма чека:</b> {grand_total_str}")
        else:
            lines.append(get_msg(user_id, "ai_no_items"))

        await message.answer("\n".join(lines), parse_mode="HTML")

        if items:
            kb = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text=get_msg(user_id, "yes")), KeyboardButton(text=get_msg(user_id, "no"))],
                    [KeyboardButton(text=get_msg(user_id, "cancel_btn"))]
                ],
                resize_keyboard=True
            )
            await message.answer(get_msg(user_id, "ai_confirm_prompt"), reply_markup=kb)
            await state.set_state(Form.confirm_receipt)
        else:
            await state.update_data(is_ai_mode=False)
            await message.answer(
                get_msg(user_id, "ai_partial_fail"),
                reply_markup=make_keyboard(user_id, list(config.SHOP_TO_ORG.keys()))
            )
            await state.set_state(Form.shop)

    except Exception as e:
        logging.error(f"OCR error: {e}")
        await wait_msg.delete()
        await state.update_data(is_ai_mode=False, items_list=[], ai_items=[])
        await message.answer(
            get_msg(user_id, "ai_fail"),
            reply_markup=make_keyboard(user_id, list(config.SHOP_TO_ORG.keys()))
        )
        await state.set_state(Form.shop)

@dp.message(Form.confirm_receipt)
async def process_confirm_receipt(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text == get_msg(user_id, "yes"):
        await state.update_data(is_ai_mode=True)
        await message.answer(
            get_msg(user_id, "ai_yes_success"),
            reply_markup=make_keyboard(user_id, list(config.SHOP_TO_ORG.keys()))
        )
        await state.set_state(Form.shop)
    elif message.text == get_msg(user_id, "no"):
        await show_edit_menu(message, state, user_id)
    else:
        await message.answer(get_msg(user_id, "press_yes_no"))

@dp.message(Form.waiting_receipt)
async def receipt_no_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await message.answer(get_msg(user_id, "only_photo"))

@dp.message(Form.waiting_qr, F.photo)
async def process_qr_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    file_bytes = io.BytesIO()
    await bot.download_file(file_info.file_path, file_bytes)
    img_data = file_bytes.getvalue()

    wait_msg = await message.answer(get_msg(user_id, "reading_receipt").format(n=1))

    try:
        loop = asyncio.get_event_loop()

        # Scan QR code on the new photo
        soliq_link = await loop.run_in_executor(None, receipt_reader.find_soliq_link, [img_data])

        await wait_msg.delete()

        if soliq_link:
            data = await state.get_data()
            photos = data.get("receipt_photos", [])

            await message.answer(get_msg(user_id, "qr_found").format(link=soliq_link))

            # Now process the receipt photos with the soliq link
            wait_msg2 = await message.answer(
                get_msg(user_id, "reading_receipt_multi").format(n=len(photos))
            )

            def upload_to_cloudinary(img_data):
                try:
                    res = cloudinary.uploader.upload(img_data, resource_type="image")
                    return res.get("secure_url", "")
                except Exception as e:
                    logging.warning(f"Cloudinary upload failed: {e}")
                    return ""

            cloud_tasks = [
                loop.run_in_executor(None, upload_to_cloudinary, p)
                for p in photos
            ]

            ai_results = []
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

            cloudinary_urls = await asyncio.gather(*cloud_tasks)
            cloudinary_url = ",".join(url for url in cloudinary_urls if url)

            if not ai_results:
                raise Exception("All AI parsing failed")

            raw_parsed = receipt_reader.merge_receipts(ai_results)
            parsed = await loop.run_in_executor(None, receipt_reader.clean_receipt_with_ai, raw_parsed)
            items = parsed.get("items", [])

            await state.update_data(
                ai_items=items,
                ai_supplier=parsed.get("supplier", ""),
                ai_receipt_date=parsed.get("receipt_date", ""),
                photo_path=soliq_link,  # Use soliq link as photo_path
                items_list=[]
            )

            await wait_msg2.delete()

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

                if grand_total > 0:
                    grand_total_str = f"{grand_total:,.0f}".replace(",", " ")
                    lines.append(f"\n💰 <b>Общая сумма чека:</b> {grand_total_str}")
            else:
                lines.append(get_msg(user_id, "ai_no_items"))

            await message.answer("\n".join(lines), parse_mode="HTML")

            if items:
                kb = ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text=get_msg(user_id, "yes")), KeyboardButton(text=get_msg(user_id, "no"))],
                        [KeyboardButton(text=get_msg(user_id, "cancel_btn"))]
                    ],
                    resize_keyboard=True
                )
                await message.answer(get_msg(user_id, "ai_confirm_prompt"), reply_markup=kb)
                await state.set_state(Form.confirm_receipt)
            else:
                await state.update_data(is_ai_mode=False)
                await message.answer(
                    get_msg(user_id, "ai_partial_fail"),
                    reply_markup=make_keyboard(user_id, list(config.SHOP_TO_ORG.keys()))
                )
                await state.set_state(Form.shop)
        else:
            # Still no QR found - ask again
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=get_msg(user_id, "cancel_btn"))]],
                resize_keyboard=True
            )
            await message.answer(get_msg(user_id, "qr_not_found"), reply_markup=kb)

    except Exception as e:
        logging.error(f"QR OCR error: {e}")
        await wait_msg.delete()
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=get_msg(user_id, "cancel_btn"))]],
            resize_keyboard=True
        )
        await message.answer(get_msg(user_id, "qr_not_found"), reply_markup=kb)

@dp.message(Form.waiting_qr)
async def qr_no_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await message.answer(get_msg(user_id, "only_photo"))

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
    if message.text not in config.SHOP_TO_ORG:
        await message.answer(get_msg(user_id, "invalid_shop"))
        return
        
    shop = message.text
    org = config.SHOP_TO_ORG[shop]
    await state.update_data(shop=shop, org=org)
    
    cards = config.ORG_CARDS.get(org, [])
    
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
    user_id = message.from_user.id
    data = await state.get_data()
    items = data.get("items_list", [])
    
    if not items:
        await message.answer(get_msg(user_id, "error"), reply_markup=get_main_menu_kb(user_id))
        await state.clear()
        return

    payment = data.get('payment_type', '')
    if data.get('card_number'):
        payment += f" ({data.get('card_number')})"

    lines = [get_msg(user_id, "final_check_header")]
    lines.append(get_msg(user_id, "final_shop").format(val=data.get('shop')))
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
            i=i, 
            nom=item.get('nomenclature'), 
            qty=item.get('quantity'), 
            price=item.get('price'), 
            total=f"{total:,.0f}".replace(",", " ")
        ))
        
    note_val = data.get('note', '') or '—'
    lines.append(get_msg(user_id, "final_receipt_tmc_note").format(
        tmc=data.get('tmc_group', '—'), 
        note=note_val
    ))
        
    lines.append(get_msg(user_id, "final_total").format(val=f"{grand_total:,.0f}".replace(",", " ")))
    lines.append(get_msg(user_id, "final_ask"))

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=get_msg(user_id, "yes")), KeyboardButton(text=get_msg(user_id, "no"))],
            [KeyboardButton(text=get_msg(user_id, "cancel_btn"))]
        ],
        resize_keyboard=True
    )
    await message.answer("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    await state.set_state(Form.confirm)

@dp.message(Form.confirm)
async def process_confirm(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text == get_msg(user_id, "yes"):
        data = await state.get_data()
        
        performer = users_db.get(user_id, {}).get("performer", "Неизвестно")
        shop = data.get("shop", "")
        org = config.SHOP_TO_ORG.get(shop, "")
        
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
        
    elif message.text == get_msg(user_id, "no"):
        await message.answer(get_msg(user_id, "cancelled"), reply_markup=get_main_menu_kb(user_id))
        await state.clear()
    else:
        await message.answer(get_msg(user_id, "press_yes_no"))


async def show_edit_menu(message_or_callback, state: FSMContext, user_id: int):
    data = await state.get_data()
    items = data.get("ai_items", [])
    
    if not items:
        # If AI found absolutely nothing, just go to manual mode
        await state.update_data(is_ai_mode=False, ai_items=[])
        if isinstance(message_or_callback, types.Message):
            await message_or_callback.answer(
                get_msg(user_id, "ai_no_manual"),
                reply_markup=make_keyboard(user_id, list(config.SHOP_TO_ORG.keys()))
            )
        else:
            await message_or_callback.message.answer(
                get_msg(user_id, "ai_no_manual"),
                reply_markup=make_keyboard(user_id, list(config.SHOP_TO_ORG.keys()))
            )
        await state.set_state(Form.shop)
        return

    buttons = []
    # Button to edit supplier
    buttons.append([InlineKeyboardButton(text=get_msg(user_id, "edit_supplier_btn"), callback_data="edit_receipt_supplier")])
    
    # Buttons for each item
    for i, item in enumerate(items):
        nom = item.get("nomenclature", f"Товар {i+1}")
        btn_text = get_msg(user_id, "edit_item_btn").format(nom=nom)
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"edit_receipt_item_{i}")])
        
    # Done button
    buttons.append([InlineKeyboardButton(text=get_msg(user_id, "edit_done_btn"), callback_data="edit_receipt_done")])
    
    # Full manual button
    buttons.append([InlineKeyboardButton(text=get_msg(user_id, "edit_full_manual_btn"), callback_data="edit_receipt_manual")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    text = get_msg(user_id, "edit_menu_title")
    if isinstance(message_or_callback, types.Message):
        # We also want to remove the regular keyboard
        await message_or_callback.answer(get_msg(user_id, "edit_saved"), reply_markup=ReplyKeyboardRemove())
        await message_or_callback.answer(text, reply_markup=kb)
    else:
        await message_or_callback.message.edit_text(text, reply_markup=kb)
        
    await state.set_state(Form.edit_receipt_menu)

@dp.callback_query(Form.edit_receipt_menu, F.data.startswith("edit_receipt_"))
async def process_edit_receipt_callback(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    action = callback.data.replace("edit_receipt_", "")
    
    if action == "done":
        await state.update_data(is_ai_mode=True)
        await callback.message.delete()
        await callback.message.answer(
            get_msg(user_id, "ai_yes_success"),
            reply_markup=make_keyboard(user_id, list(config.SHOP_TO_ORG.keys()))
        )
        await state.set_state(Form.shop)
        
    elif action == "manual":
        await state.update_data(is_ai_mode=False, ai_items=[])
        await callback.message.delete()
        await callback.message.answer(
            get_msg(user_id, "ai_no_manual"),
            reply_markup=make_keyboard(user_id, list(config.SHOP_TO_ORG.keys()))
        )
        await state.set_state(Form.shop)
        
    elif action == "supplier":
        await state.update_data(edit_target="supplier")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=get_msg(user_id, "edit_back_btn"), callback_data="edit_back")]])
        await callback.message.edit_text(get_msg(user_id, "enter_new_supplier"), reply_markup=kb)
        await state.set_state(Form.wait_edit_value)
        
    elif action.startswith("item_"):
        idx = int(action.split("_")[1])
        data = await state.get_data()
        items = data.get("ai_items", [])
        if idx >= len(items):
            await callback.answer("Error")
            return
            
        item = items[idx]
        nom = item.get("nomenclature", "")
        
        buttons = [
            [InlineKeyboardButton(text=get_msg(user_id, "edit_name_btn"), callback_data=f"edit_field_{idx}_name")],
            [InlineKeyboardButton(text=get_msg(user_id, "edit_price_btn"), callback_data=f"edit_field_{idx}_price")],
            [InlineKeyboardButton(text=get_msg(user_id, "edit_qty_btn"), callback_data=f"edit_field_{idx}_qty")],
            [InlineKeyboardButton(text=get_msg(user_id, "edit_back_btn"), callback_data="edit_back")]
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(get_msg(user_id, "edit_item_title").format(nom=nom), reply_markup=kb)

@dp.callback_query(Form.edit_receipt_menu, F.data == "edit_back")
async def process_edit_back_menu(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await show_edit_menu(callback, state, user_id)

@dp.callback_query(Form.edit_receipt_menu, F.data.startswith("edit_field_"))
async def process_edit_field_callback(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    parts = callback.data.split("_")
    idx = int(parts[2])
    field = parts[3]
    
    await state.update_data(edit_target=f"item_{idx}_{field}")
    
    prompts = {
        "name": get_msg(user_id, "enter_new_name"),
        "price": get_msg(user_id, "enter_new_price"),
        "qty": get_msg(user_id, "enter_new_qty")
    }
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=get_msg(user_id, "edit_back_btn"), callback_data="edit_back")]])
    await callback.message.edit_text(prompts[field], reply_markup=kb)
    await state.set_state(Form.wait_edit_value)

@dp.callback_query(Form.wait_edit_value, F.data == "edit_back")
async def process_edit_back(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await show_edit_menu(callback, state, user_id)

@dp.message(Form.wait_edit_value)
async def process_edit_value_msg(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    target = data.get("edit_target")
    
    if target == "supplier":
        await state.update_data(ai_supplier=message.text)
    elif target and target.startswith("item_"):
        parts = target.split("_")
        idx = int(parts[1])
        field = parts[2]
        
        items = data.get("ai_items", [])
        if idx < len(items):
            if field == "name":
                items[idx]["nomenclature"] = message.text
            elif field == "price":
                items[idx]["price"] = message.text
            elif field == "qty":
                items[idx]["quantity"] = message.text
            await state.update_data(ai_items=items)
            
    # Go back to menu
    await message.delete()  # optionally delete user's message
    # To properly go back, we resend the menu
    await show_edit_menu(message, state, user_id)


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
