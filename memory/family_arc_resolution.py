from core.i18n import t
import re


def _normalize_candidate_entities(candidate: dict) -> set[str]:
    entities = candidate.get("entities") or candidate.get("subject_entities") or []
    if isinstance(entities, str):
        entities = [entities]
    out = set()
    for item in entities:
        value = str(item or "").strip().lower()
        if value:
            out.add(value)
    return out


def _normalize_candidate_topic(candidate: dict) -> str:
    return str(candidate.get("topic") or "").strip().lower()


def _normalize_candidate_relation(candidate: dict) -> str:
    return str(candidate.get("relation_type") or "").strip().lower()


def _normalize_candidate_state_markers(candidate: dict) -> set[str]:
    markers = candidate.get("state_markers") or []
    if isinstance(markers, str):
        markers = [markers]
    return {
        str(x or "").strip().lower()
        for x in markers
        if str(x or "").strip()
    }


def _extract_candidate_date_key(candidate: dict) -> str:
    for key in ("date", "date_key", "event_date", "memory_date"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value

    fact = str(candidate.get("fact") or "")
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", fact)
    if m:
        return m.group(1)

    return ""


def _candidate_arc_signature(candidate: dict) -> dict:
    return {
        "category": str(candidate.get("category") or "").strip().lower(),
        "entities": _normalize_candidate_entities(candidate),
        "topic": _normalize_candidate_topic(candidate),
        "relation_type": _normalize_candidate_relation(candidate),
        "state_markers": _normalize_candidate_state_markers(candidate),
        "date_key": _extract_candidate_date_key(candidate),
    }


def _has_meaningful_entity_overlap(a: dict, b: dict) -> bool:
    a_entities = _candidate_arc_signature(a)["entities"]
    b_entities = _candidate_arc_signature(b)["entities"]
    if not a_entities or not b_entities:
        return False
    return bool(a_entities & b_entities)


def _topics_are_close(a: dict, b: dict) -> bool:
    a_topic = _candidate_arc_signature(a)["topic"]
    b_topic = _candidate_arc_signature(b)["topic"]
    if not a_topic or not b_topic:
        return False
    if a_topic == b_topic:
        return True
    if a_topic in b_topic or b_topic in a_topic:
        return True
    return False


def _same_family_arc(a: dict, b: dict) -> bool:
    a_sig = _candidate_arc_signature(a)
    b_sig = _candidate_arc_signature(b)

    if a_sig["category"] != "family" or b_sig["category"] != "family":
        return False

    if not _has_meaningful_entity_overlap(a, b):
        return False

    if not _topics_are_close(a, b):
        return False

    a_date = a_sig["date_key"]
    b_date = b_sig["date_key"]
    if a_date and b_date and a_date != b_date:
        return False

    return True


def _candidate_adds_new_stage(existing_candidate: dict, new_candidate: dict) -> bool:
    old_rel = _normalize_candidate_relation(existing_candidate)
    new_rel = _normalize_candidate_relation(new_candidate)

    old_markers = _normalize_candidate_state_markers(existing_candidate)
    new_markers = _normalize_candidate_state_markers(new_candidate)

    if new_rel != old_rel and new_rel in {"follow_up", "state_update", "confirmed"}:
        return True

    if new_markers - old_markers:
        important_markers = {
            "confirmed", "returned", "cancelled", "scheduled",
            "tired", "better", "sick", "home", "away"
        }
        if (new_markers - old_markers) & important_markers:
            return True

    new_fact = str(new_candidate.get("fact") or "").lower()
    stage_keywords = (
        t("prompts.ext_str_537"), t("prompts.ext_str_298"), t("prompts.ext_str_263"), t("prompts.ext_str_268"), t("prompts.ext_str_698"),
        t("prompts.ext_str_589"), t("prompts.ext_str_397"), t("prompts.ext_str_650"), t("prompts.ext_str_666"), t("prompts.ext_str_194"),
        "returned", "return", "home", "tired", "left", "until", "camp"
    )
    if any(k in new_fact for k in stage_keywords):
        old_fact = str(existing_candidate.get("fact") or "").lower()
        if not all(k in old_fact for k in stage_keywords if k in new_fact):
            return True

    return False


def _fact_information_score(candidate: dict) -> int:
    fact = str(candidate.get("fact") or "")
    relation_type = _normalize_candidate_relation(candidate)
    markers = _normalize_candidate_state_markers(candidate)
    entities = _normalize_candidate_entities(candidate)

    score = 0
    score += len(fact)
    score += len(entities) * 20
    score += len(markers) * 15

    if relation_type == "confirmed":
        score += 40
    elif relation_type == "state_update":
        score += 30
    elif relation_type == "follow_up":
        score += 25
    elif relation_type == "temporary_state":
        score += 20

    if re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", fact):
        score += 20

    if any(token in fact.lower() for token in (t("prompts.ext_str_537"), t("prompts.ext_str_745"), t("prompts.ext_str_754"), t("prompts.ext_str_575"), t("prompts.ext_str_737"), t("prompts.ext_str_666"), "for ", "days", "home", "tired", "until")):
        score += 20

    return score


def _pick_richer_candidate(existing_candidate: dict, new_candidate: dict) -> dict:
    old_score = _fact_information_score(existing_candidate)
    new_score = _fact_information_score(new_candidate)
    return new_candidate if new_score > old_score else existing_candidate


def _facts_are_near_exact(a: dict, b: dict) -> bool:
    a_fact = str(a.get("fact") or "").strip().lower()
    b_fact = str(b.get("fact") or "").strip().lower()

    if not a_fact or not b_fact:
        return False

    if a_fact == b_fact:
        return True

    shorter, longer = sorted((a_fact, b_fact), key=len)

    enrich_indicators = (
        " for ", " days", " day", " hours", " until", " because ",
        t("prompts.ext_str_629"), t("prompts.ext_str_450"), t("prompts.ext_str_611"), t("prompts.ext_str_719"), t("prompts.ext_str_566"), t("prompts.ext_str_393"),
        "returned", "home", "tired", t("prompts.ext_str_405"), t("prompts.ext_str_419"), t("prompts.ext_str_336")
    )
    if shorter and shorter in longer:
        extra = longer.replace(shorter, "", 1)
        if any(token in extra for token in enrich_indicators):
            return False
        if len(shorter) / max(len(longer), 1) >= 0.8:
            return True

    return False


def _decide_family_arc_resolution(existing_candidate: dict, new_candidate: dict) -> str:
    if not _same_family_arc(existing_candidate, new_candidate):
        return "add_new_memory"

    if _facts_are_near_exact(existing_candidate, new_candidate):
        return "skip_exact_duplicate"

    if _candidate_adds_new_stage(existing_candidate, new_candidate):
        return "add_new_memory"

    richer = _pick_richer_candidate(existing_candidate, new_candidate)
    if richer is new_candidate:
        return "merge_enrich_existing"

    return "skip_exact_duplicate"

