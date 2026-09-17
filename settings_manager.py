import json
import os
import logging
import config

SETTINGS_FILE = "settings.json"

_settings = {
    "admins": [],
    "org_cards": {},
    "shops": {}
}

def load_settings():
    global _settings
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                _settings = json.load(f)
            logging.info("Settings loaded from settings.json")
        except Exception as e:
            logging.error(f"Error loading settings.json: {e}")
            _initialize_defaults()
    else:
        _initialize_defaults()

def _initialize_defaults():
    global _settings
    _settings["admins"] = config.ADMIN_IDS.copy()
    _settings["org_cards"] = config.ORG_CARDS.copy()
    _settings["shops"] = config.SHOP_TO_ORG.copy()
    save_settings()
    logging.info("Initialized default settings from config.py")

def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(_settings, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Error saving settings.json: {e}")

def get_admins() -> list[int]:
    return _settings.get("admins", [])

def add_admin(user_id: int):
    admins = get_admins()
    if user_id not in admins:
        admins.append(user_id)
        _settings["admins"] = admins
        save_settings()

def remove_admin(user_id: int):
    admins = get_admins()
    if user_id in admins:
        admins.remove(user_id)
        _settings["admins"] = admins
        save_settings()

def get_org_cards(org_name: str) -> list[str]:
    return _settings.get("org_cards", {}).get(org_name, [])

def add_org_card(org_name: str, card: str):
    cards = _settings.get("org_cards", {})
    if org_name not in cards:
        cards[org_name] = []
    if card not in cards[org_name]:
        cards[org_name].append(card)
    _settings["org_cards"] = cards
    save_settings()

def remove_org_card(org_name: str, card: str):
    cards = _settings.get("org_cards", {})
    if org_name in cards and card in cards[org_name]:
        cards[org_name].remove(card)
        _settings["org_cards"] = cards
        save_settings()

def get_shops() -> dict:
    return _settings.get("shops", {})

def add_shop(shop_name: str, org_name: str):
    shops = _settings.get("shops", {})
    shops[shop_name] = org_name
    _settings["shops"] = shops
    save_settings()

def remove_shop(shop_name: str):
    shops = _settings.get("shops", {})
    if shop_name in shops:
        del shops[shop_name]
        _settings["shops"] = shops
        save_settings()

# Ensure settings are loaded when module is imported
load_settings()
