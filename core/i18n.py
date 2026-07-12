import os
import json
import config

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES_DIR = os.path.join(BASE_DIR, "locales")
LANG = "el" if config.RESPONSE_LANGUAGE.lower() == "greek" else "en"
_translations = {}

def load_locale(lang: str):
    global _translations
    path = os.path.join(LOCALES_DIR, f"{lang}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            _translations = json.load(f)

# Load default language at startup
load_locale(LANG)

def t(key: str, **kwargs) -> str:
    """
    Translates a key from the loaded locale.
    Supports nested keys with dot notation (e.g., 'weather.code_0')
    and format arguments (e.g., t('weather.error', error='timeout')).
    """
    parts = key.split('.')
    val = _translations
    try:
        for p in parts:
            val = val[p]
        if isinstance(val, str):
            if kwargs:
                val = val.format(**kwargs)
            if '{' in val:
                val = val.replace('{user_name}', config.USER_NAME)
                val = val.replace('{partner_name}', getattr(config, 'PARTNER_NAME', 'Partner'))
                val = val.replace('{kid1_name}', getattr(config, 'KID1_NAME', 'Kid1'))
                val = val.replace('{kid2_name}', getattr(config, 'KID2_NAME', 'Kid2'))
            return val
        elif isinstance(val, list):
            return val
    except KeyError:
        return f"[{key}]"
    return str(val)


def load_prompt(filename: str) -> str:
    path = os.path.join(BASE_DIR, 'prompts', filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f_prompt:
            return f_prompt.read()
    return f'[PROMPT NOT FOUND: {filename}]'
