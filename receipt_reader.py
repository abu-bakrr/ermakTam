import os
import json
import io
from PIL import Image
from google import genai
from google.genai import types

def parse_receipt_gemini(image_bytes_list: list) -> dict:
    """Отправляет все части чека в Gemini одним запросом и возвращает структурированный словарь."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY не установлен в .env")
        
    client = genai.Client(api_key=api_key)
    images = [Image.open(io.BytesIO(b)) for b in image_bytes_list]
    
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

    Верни СТРОГО JSON, без лишнего текста:
    {
      "receipt_date": "ДД.ММ.ГГГГ или пустая строка",
      "supplier": "Название магазина",
      "items": [
        {
          "nomenclature": "Точное название товара с чека",
          "price": "Только цифры — цена за единицу, или итоговая сумма если единичная цена не указана",
          "quantity": "Только число — количество из чека, или 1 если количество не указано"
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
                contents=images + [prompt],
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

