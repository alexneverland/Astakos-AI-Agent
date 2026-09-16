"""Contracts for separating generated-file markers from visible replies."""

from services.created_file import extract_created_files


def test_extract_created_files_removes_all_markers_and_keeps_up_to_five_paths() -> None:
    result = extract_created_files(
        "Έτοιμα.\n"
        "[CREATED_FILE: C:\\astakos_v2\\outputs\\one.pdf]\n"
        "[CREATED_FILE: C:\\astakos_v2\\outputs\\two.png]"
    )

    assert result.text == "Έτοιμα."
    assert result.paths == (
        "C:\\astakos_v2\\outputs\\one.pdf",
        "C:\\astakos_v2\\outputs\\two.png",
    )
    assert [output.kind for output in result.outputs] == ["file", "file"]


def test_extract_created_files_leaves_ordinary_reply_unchanged() -> None:
    result = extract_created_files("Κανονική απάντηση")

    assert result.text == "Κανονική απάντηση"
    assert result.paths == ()


def test_extract_created_files_includes_generated_photo_marker() -> None:
    result = extract_created_files(
        "Έτοιμη η εικόνα.\n[SEND_PHOTO: C:/astakos_v2/outputs/scene.png]"
    )

    assert result.text == "Έτοιμη η εικόνα."
    assert result.paths == ("C:/astakos_v2/outputs/scene.png",)
    assert result.outputs[0].kind == "photo"


def test_extract_created_files_strips_extra_markers_without_sending_them() -> None:
    markers = "\n".join(f"[CREATED_FILE: C:/outputs/{index}.txt]" for index in range(7))

    result = extract_created_files(f"Έτοιμα\n{markers}")

    assert result.text == "Έτοιμα"
    assert result.paths == tuple(f"C:/outputs/{index}.txt" for index in range(5))
    assert "CREATED_FILE" not in result.text
