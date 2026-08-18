import os
import json
import io
import platform

# Configure zbar library path for pyzbar on macOS
if platform.system() == "Darwin":
    os.environ["DYLD_LIBRARY_PATH"] = "/opt/homebrew/lib:" + os.environ.get("DYLD_LIBRARY_PATH", "")

from PIL import Image, ImageEnhance, ImageOps
from google import genai
from google.genai import types
from pyzbar.pyzbar import decode

def scan_qr_codes(image_bytes: bytes) -> list[str]:
    """Сканирует QR-коды на изображении с применением улучшений для повышения шанса распознавания."""
    try:
        original_image = Image.open(io.BytesIO(image_bytes))
        
        # Создаем список вариаций картинки для pyzbar (он часто капризен)
        variations = [original_image]
        
        # 1. ЧБ вариант
        gray = original_image.convert('L')
        variations.append(gray)
        
        # 2. Повышенный контраст
        enhancer = ImageEnhance.Contrast(gray)
        variations.append(enhancer.enhance(1.5))
        variations.append(enhancer.enhance(2.0))
        variations.append(enhancer.enhance(3.0))
        
        # 3. Бинаризация (черно-белый порог)
        binary = gray.point(lambda p: 255 if p > 128 else 0, mode='1')
        variations.append(binary)
        
        all_links = set()
        for img_var in variations:
            decoded_objects = decode(img_var)
            for obj in decoded_objects:
                data = obj.data.decode('utf-8', errors='ignore')
                if data.startswith('http') or data.startswith('https'):
                    all_links.add(data)
                    
        return list(all_links)
    except Exception as e:
        print(f"[WARNING] QR scan error: {e}")
        return []


def find_soliq_link(image_bytes_list: list[bytes]) -> str | None:
    """Ищет ссылку, начинающуюся с soliq, в списке изображений."""
    for img_bytes in image_bytes_list:
        links = scan_qr_codes(img_bytes)
        for link in links:
            if link.startswith('soliq') or 'soliq' in link.lower():
                return link
    return None


def parse_receipt_gemini(image_bytes: bytes, previously_found_items: list = None) -> dict:
    """Отправляет чек в Gemini и возвращает структурированный словарь."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY не установлен в .env")
        
    client = genai.Client(api_key=api_key)
    image = Image.open(io.BytesIO(image_bytes))
    
    if previously_found_items is None:
        previously_found_items = []
    
    prompt = """
    Ты опытный бухгалтер. Твоя задача — распознать данные с фотографии чека или накладной.

    ПРАВИЛА РАСПОЗНАВАНИЯ:
    1. Игнорируй всё лишнее: адрес магазина, телефоны, ИНН, НДС, рекламные тексты, QR-коды, благодарности за покупку.
    2. Не добавляй строки скидок (chegirma, скидка, discount) как отдельный товар.
    3. Если товар продан в количестве > 1, НЕ умножай цену — верни цену за единицу ИЛИ итоговую сумму за этот товар как есть на чеке.
    4. Строки "ИТОГО", "JAMI", "ИТОГО К ОПЛАТЕ" — это НЕ товар, игнорируй их.
    5. Дата на чеке может быть в разных форматах — приведи её к формату ДД.ММ.ГГГГ.
    6. Для поставщика: используй БРЕНД (Korzinka, Makro, Havas), а не юр. лицо (MCHJ, ООО). Если бренда нет — пиши юр. лицо.
    7. В поле price пиши ТОЛЬКО цифры, без пробелов, без "сум", без "UZS". Пример: "45000" или "45000.50".
    8. Обязательно найди окончательную сумму чека (ИТОГО / JAMI). Будь очень внимателен к копейкам (точкам и нулям в конце), пиши сумму точно как на чеке.

    Верни СТРОГО JSON, без лишнего текста:
    {
      "receipt_date": "ДД.ММ.ГГГГ или пустая строка",
      "supplier": "Название магазина",
      "grand_total": "Окончательная сумма чека (только цифры, например '150000' или '150000.50')",
      "items": [
        {
          "nomenclature": "Точное название товара с чека",
          "price": "Только цифры — цена за единицу, или итоговая сумма если единичная цена не указана",
          "quantity": "Только число — количество из чека, или 1 если количество не указано"
        }
      ]
    }
    """
    
    if previously_found_items:
        items_str = json.dumps(previously_found_items, ensure_ascii=False, indent=2)
        prompt += f"""
    
    ВНИМАНИЕ! Следующие товары УЖЕ БЫЛИ НАЙДЕНЫ на предыдущих частях этого же чека. 
    Если ты видишь их на этом фото, НЕ ДОБАВЛЯЙ их в свой ответ (пропусти их). 
    Список уже найденных товаров:
    {items_str}
    """
    
    MODELS = [
        'gemini-3.5-flash-lite',
        'gemini-3.1-flash-lite',
        'gemini-3.0-flash',
        'gemini-2.5-flash',
        'gemini-2.5-flash-lite',
    ]
    
    last_error = None
    
    for model_name in MODELS:
        try:
            print(f"Пробуем модель: {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=[image, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            )
            
            data = json.loads(response.text)
            
            return {
                "receipt_date": str(data.get("receipt_date", "")),
                "supplier": str(data.get("supplier", "")),
                "grand_total": str(data.get("grand_total", "")),
                "items": data.get("items", [])
            }
            
        except Exception as e:
            print(f"[WARNING] Ошибка с моделью {model_name}: {e}. Пробуем следующую...")
            last_error = e
            continue  

    raise Exception(f"Все модели выдали ошибку. Последняя ошибка: {last_error}")

def merge_receipts(results: list) -> dict:
    all_items = []
    receipt_date = ""
    supplier = ""
    grand_total = ""
    seen = set()
    
    for r in results:
        if not receipt_date and r.get("receipt_date"):
            receipt_date = r["receipt_date"]
        if not supplier and r.get("supplier"):
            supplier = r["supplier"]
        if not grand_total and r.get("grand_total"):
            grand_total = r["grand_total"]
        
        for item in r.get("items", []):
            key = (
                str(item.get("nomenclature", "")).strip().lower(),
                str(item.get("price", "")).strip(),
                str(item.get("quantity", "")).strip()
            )
            if key not in seen:
                seen.add(key)
                all_items.append(item)
    
    return {
        "receipt_date": receipt_date,
        "supplier": supplier,
        "grand_total": grand_total,
        "items": all_items
    }

def clean_receipt_with_ai(merged_receipt_data: dict) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return merged_receipt_data
        
    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    Ниже представлен JSON-объект, полученный путем склеивания распознанных товаров с нескольких фотографий одного длинного чека.
    Возможно, некоторые товары задублировались из-за пересечения фотографий. 
    Также возможно, что один и тот же товар был пробит на двух языках (например, русский и узбекский), и поэтому попал в список дважды.

    Твоя задача — очистить список товаров от дубликатов.
    Если два товара имеют одинаковую цену и количество, и их названия означают одно и то же (или очень похожи):
    - Оставь только ОДИН вариант товара в списке.
    - В названии товара (`nomenclature`) выбери только ОДИН язык (предпочтительно русский, если есть). НЕ пиши оба названия через слеш (например, НЕ пиши "Нон / Хлеб", напиши просто "Хлеб").

    Данные чека:
    {json.dumps(merged_receipt_data, ensure_ascii=False, indent=2)}

    Верни очищенный СТРОГО JSON в таком же формате:
    {{
      "receipt_date": "...",
      "supplier": "...",
      "grand_total": "...",
      "items": [ ... ]
    }}
    """
    
    try:
        print("Пробуем финальную очистку дубликатов...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        data = json.loads(response.text)
        return {
            "receipt_date": str(data.get("receipt_date", "")),
            "supplier": str(data.get("supplier", "")),
            "grand_total": str(data.get("grand_total", "")),
            "items": data.get("items", [])
        }
    except Exception as e:
        print(f"[WARNING] Ошибка финальной очистки: {e}")
        return merged_receipt_data
