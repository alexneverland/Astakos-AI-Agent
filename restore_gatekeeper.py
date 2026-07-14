import json

def update_system_py():
    with open('tools/system.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. control_routine_notifications
    marker = '    VALID_ACTIONS = {"mute", "unmute", "silence_emotional", "allow_emotional"}'
    if marker in content and 'classify_routine_intent' not in content.split(marker)[0][-300:]:
        inject = """    routine_names = _get_routine_names_for_intent_classification()
    intent_result = classify_routine_intent(source_text, routine_names=routine_names)
    if intent_result.intent == "context_update":
        return t("tools.system.context_update_not_notif")

"""
        content = content.replace(marker, inject + marker)

    # 2. control_routine_condition
    marker2 = '    VALID_ACTIONS = {"add", "remove"}'
    if marker2 in content and 'classify_routine_intent' not in content.split(marker2)[0][-300:]:
        inject2 = """    routine_names = _get_routine_names_for_intent_classification()
    intent_result = classify_routine_intent(source_text, routine_names=routine_names)
    if intent_result.intent == "context_update":
        return t("tools.system.context_update_not_cond")

"""
        content = content.replace(marker2, inject2 + marker2)

    # 3. control_routine_schedule
    marker3 = '    VALID_ACTIONS = {"pause", "resume", "set_window", "clear_window"}'
    if marker3 in content and 'classify_routine_intent' not in content.split(marker3)[0][-300:]:
        inject3 = """    routine_names = _get_routine_names_for_intent_classification()
    intent_result = classify_routine_intent(source_text, routine_names=routine_names)
    if intent_result.intent == "context_update":
        return t("tools.system.context_update_not_sched")

"""
        content = content.replace(marker3, inject3 + marker3)

    # 4. control_routine_cooldown
    marker4 = '    VALID_ACTIONS = {"reset"}'
    if marker4 in content and 'classify_routine_intent' not in content.split(marker4)[0][-300:]:
        inject4 = """    routine_names = _get_routine_names_for_intent_classification()
    intent_result = classify_routine_intent(source_text, routine_names=routine_names)
    if intent_result.intent == "context_update":
        return "ℹ️ This looks like a context/fact update, not a manual routine cooldown override command. Cooldown not reset."

"""
        content = content.replace(marker4, inject4 + marker4)
        
    with open('tools/system.py', 'w', encoding='utf-8') as f:
        f.write(content)

def update_intents():
    # Update EL
    with open('core/intents_el.json', 'r', encoding='utf-8') as f:
        el_data = json.load(f)
        
    el_time_words = el_data['routine_intent']['time_condition_words']
    el_time_additions = ["μονο αν", "μόνο αν", "μονο", "μόνο", "εφοσον", "εφόσον"]
    for word in el_time_additions:
        if word not in el_time_words:
            el_time_words.append(word)

    el_control_words = el_data['routine_intent']['control_verbs']
    el_control_additions = ["παιζουμε", "παίζουμε", "βαλτην", "βάλτην", "βαλτο", "βάλτο"]
    for word in el_control_additions:
        if word not in el_control_words:
            el_control_words.append(word)
            
    with open('core/intents_el.json', 'w', encoding='utf-8') as f:
        json.dump(el_data, f, ensure_ascii=False, indent=2)

    # Update EN
    with open('core/intents_en.json', 'r', encoding='utf-8') as f:
        en_data = json.load(f)
        
    en_time_words = en_data['routine_intent']['time_condition_words']
    en_time_additions = ["only if", "provided that", "as long as"]
    for word in en_time_additions:
        if word not in en_time_words:
            en_time_words.append(word)

    en_control_words = en_data['routine_intent']['control_verbs']
    en_control_additions = ["we play", "we run", "put it", "apply"]
    for word in en_control_additions:
        if word not in en_control_words:
            en_control_words.append(word)
            
    with open('core/intents_en.json', 'w', encoding='utf-8') as f:
        json.dump(en_data, f, ensure_ascii=False, indent=4)

if __name__ == '__main__':
    update_system_py()
    update_intents()
