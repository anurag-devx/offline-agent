import pytest

from offline_agent.engine.context import ToolContext, set_context
from offline_agent.engine.toolkits import files
from tests.conftest import config


def ctx_for(downloads, **files_policy):
    cfg = config(permissions={"files": {"folders": [str(downloads)], "read": "allow", "create": "allow",
                                        "move": "allow", **files_policy}})
    ctx = ToolContext(cfg, {"granted_folders": [], "granted_domains": [], "changes": 0})
    set_context(ctx)
    return ctx


def test_outside_scope_is_refused(downloads):
    ctx_for(downloads)
    with pytest.raises(PermissionError):
        files.resolve(str(downloads.parent / "Pictures" / "x.jpg"))


def test_protected_folder_always_refused(downloads):
    ctx_for(downloads)
    with pytest.raises(PermissionError, match="protected"):
        files.resolve("~/.ssh/id_rsa")


def test_move_files_top_level_only_and_never_overwrites(downloads):
    ctx = ctx_for(downloads)
    (downloads / "all_pdf").mkdir()
    (downloads / "all_pdf" / "a.pdf").write_text("old")
    out = files.move_files(str(downloads), str(downloads / "all_pdf"), extensions=".pdf")
    assert out.startswith("OK moved 2/2")
    assert sorted(p.name for p in (downloads / "all_pdf").iterdir()) == ["a.pdf", "a_1.pdf", "b.pdf"]
    assert (downloads / "sub" / "deep.pdf").exists()  # subfolders untouched
    assert [e["op"] for e in ctx.events].count("move") == 2  # every change recorded


def test_change_limit(downloads):
    ctx_for(downloads, max_changes=1)
    out = files.move_files(str(downloads), str(downloads / "x"), extensions=".pdf")
    assert "NOT MOVED" in out


def test_file_type_filter(downloads):
    ctx_for(downloads, file_types=[".jpg"])
    with pytest.raises(PermissionError, match="file types"):
        files.read_file(str(downloads / "notes.docx"))


def test_list_folder_is_compact(downloads):
    ctx_for(downloads)
    out = files.list_folder(str(downloads), extensions=".pdf")
    assert out.splitlines()[0].startswith("OK ~/Downloads filter .pdf · 2 files")
