import pytest

from veriquill.claims.documents import UnsupportedDocument, load_document


def test_plain_text_keeps_line_numbers(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text("Experience\nLed the auth redesign\nSkills\n", encoding="utf-8")

    document = load_document(path)

    assert document.name == "resume.txt"
    assert document.lines[1] == "Led the auth redesign"
    assert document.line_number_of("Led the auth redesign") == 2


def test_blank_lines_are_preserved_so_line_numbers_stay_accurate(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text("A\n\n\nB\n", encoding="utf-8")

    document = load_document(path)

    assert document.line_number_of("B") == 4


def test_docx_is_read_as_paragraphs(tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "resume.docx"
    written = docx.Document()
    written.add_paragraph("Experience")
    written.add_paragraph("Built a RAG pipeline")
    written.save(path)

    document = load_document(path)

    assert "Built a RAG pipeline" in document.lines


def test_unknown_extension_is_refused(tmp_path):
    path = tmp_path / "resume.rtf"
    path.write_text("x", encoding="utf-8")

    with pytest.raises(UnsupportedDocument, match="rtf"):
        load_document(path)


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_document(tmp_path / "nope.txt")
