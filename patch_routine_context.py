def patch():
    with open('c:/astakos_v2/services/routine_context.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Inject _get_bool_with_fallback and replace the 3 assignments
    target1 = '    ctx.update({\n        "today": today,'
    replacement1 = """    def _get_bool_with_fallback(specific: str, generic: str) -> bool | None:
        val = resolve_context_bool(specific, current)
        if val is not None:
            return val
        return resolve_context_bool(generic, current)

    ctx.update({
        "today": today,"""
    content = content.replace(target1, replacement1)

    target2 = '"alexandros_with_user": resolve_context_bool("alexandros_with_user", current),'
    replacement2 = '"alexandros_with_user": _get_bool_with_fallback("alexandros_with_user", "kid1_with_user"),'
    content = content.replace(target2, replacement2)

    target3 = '"alexandros_with_sofia": resolve_context_bool("alexandros_with_sofia", current),'
    replacement3 = '"alexandros_with_sofia": _get_bool_with_fallback("alexandros_with_sofia", "kid1_with_partner"),'
    content = content.replace(target3, replacement3)

    target4 = '"sofia_with_user": resolve_context_bool("sofia_with_user", current),'
    replacement4 = '"sofia_with_user": _get_bool_with_fallback("sofia_with_user", "partner_with_user"),'
    content = content.replace(target4, replacement4)

    # 2. Fix resolve_alexandros_away_state
    target5 = """    state_data = get_context_state("alexandros_away_from_home")
    if not state_data:
        return False
    expires_at = state_data.get("expires_at")"""

    replacement5 = """    state_data = get_context_state("alexandros_away_from_home")
    if not state_data:
        state_data = get_context_state("kid1_away_from_home")
        if not state_data:
            return False
    expires_at = state_data.get("expires_at")"""
    content = content.replace(target5, replacement5)

    with open('c:/astakos_v2/services/routine_context.py', 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':
    patch()
