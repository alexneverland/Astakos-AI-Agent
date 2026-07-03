from services.routine_intent import classify_routine_intent


def test_manual_command_pause():
    result = classify_routine_intent(
        "Πάγωσε το ποδόσφαιρο του αλέξανδρου μέχρι μία σεπτεμβρίου",
        routine_names=["ποδόσφαιρο Αλέξανδρου", "πάρκο με Αλέξανδρο"],
    )
    assert result.intent == "manual_routine_control"


def test_context_update_offseason():
    result = classify_routine_intent(
        "Είναι καλοκαίρι ο Αλέξανδρος δεν έχει ποδόσφαιρο ξανά τον Σεπτέμβριο",
        routine_names=["ποδόσφαιρο Αλέξανδρου"],
    )
    assert result.intent == "context_update"


def test_context_update_shift():
    result = classify_routine_intent(
        "Από αύριο είμαι πρωινή βάρδια",
        routine_names=["ψώνια στη λαϊκή", "πάρκο με Αλέξανδρο"],
    )
    assert result.intent == "context_update"


def test_manual_condition_edit():
    result = classify_routine_intent(
        "Βάλε στην ρουτίνα ψώνια στη λαϊκή όταν είμαι πρωινή βάρδια να μην ενεργοποιείται",
        routine_names=["ψώνια στη λαϊκή"],
    )
    assert result.intent == "manual_routine_control"


def test_general_chat():
    result = classify_routine_intent(
        "Καλημέρα φίλε τι κάνεις",
        routine_names=[],
    )
    assert result.intent == "general_chat"


def test_context_update_with_routine_mention():
    result = classify_routine_intent(
        "Σήμερα μάλλον δεν θα πάμε πάρκο",
        routine_names=["πάρκο με Αλέξανδρο"],
    )
    assert result.intent == "context_update"


def test_manual_notification_control():
    result = classify_routine_intent(
        "Μη μου στέλνεις για το πάρκο μέχρι να γυρίσουμε σπίτι",
        routine_names=["πάρκο με Αλέξανδρο"],
    )
    assert result.intent == "manual_routine_control"


def test_manual_cooldown_reset_control():
    result = classify_routine_intent(
        "Μηδένισε το cooldown της ρουτίνας καθάρισμα κλουβιού κουνελιού",
        routine_names=["καθάρισμα κλουβιού κουνελιού"],
    )
    assert result.intent == "manual_routine_control"
