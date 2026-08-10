import os
import json
import io
from PIL import Image
from google import genai
from google.genai import types

def parse_receipt_gemini(image_bytes: bytes) -> dict:
    """Отправляет чек в Gemini 2.0 Flash и возвращает структурированный словарь."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY не установлен в .env")
        
    client = genai.Client(api_key=api_key)
    image = Image.open(io.BytesIO(image_bytes))
    
    prompt = """
    Ты опытный бухгалтер. Твоя задача — распознать товары с фотографии чека или накладной.

    В чеке для каждого товара обычно есть 3 числа: КОЛИЧЕСТВО, ЦЕНА за единицу, СУММА (итого за этот товар).
    Связь всегда одна: СУММА = ЦЕНА × КОЛИЧЕСТВО.

    ЛОГИКА РАСПОЗНАВАНИЯ ДЛЯ КАЖДОГО ТОВАРА:
    - Если в чеке есть ЦЕНА и КОЛИЧЕСТВО → используй их. Сумму не трогай.
    - Если в чеке есть СУММА и КОЛИЧЕСТВО, но НЕТ цены за единицу → вычисли цену: ЦЕНА = СУММА / КОЛИЧЕСТВО. Округли до 2 знаков.
    - Если в чеке есть только СУММА (количество = 1) → ЦЕНА = СУММА, КОЛИЧЕСТВО = 1.
    - Никогда не путай ЦЕНУ (за 1 шт) и СУММУ (итого). Это разные числа!

    ПРАВИЛА ФИЛЬТРАЦИИ ЧЕКА:
    1. Игнорируй: адреса, телефоны, ИНН, НДС, рекламные тексты, QR-коды, благодарности.
    2. Не включай строки скидок (chegirma, скидка, discount) как товар.
    3. Строки "ИТОГО", "JAMI", "ИТОГО К ОПЛАТЕ" — это НЕ товар, игнорируй.
    4. Дата — приведи к формату ДД.ММ.ГГГГ.
    5. Поставщик — пиши БРЕНД (Korzinka, Makro), а не юр. лицо. Если бренда нет — юр. лицо.
    6. Цифры только числами, без "сум", "UZS", пробелов. Например: "45000" или "750.50".

    Верни СТРОГО JSON, без лишнего текста:
    {
      "receipt_date": "ДД.ММ.ГГГГ или пустая строка",
      "supplier": "Название магазина",
      "items": [
        {
          "nomenclature": "Точное название товара",
          "price": "Цена за единицу (вычисли если не указана)",
          "quantity": "Количество из чека"
        }
      ]
    }
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
    seen = set()
    
    for r in results:
        if not receipt_date and r.get("receipt_date"):
            receipt_date = r["receipt_date"]
        if not supplier and r.get("supplier"):
            supplier = r["supplier"]
        
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
        "items": all_items
    }
