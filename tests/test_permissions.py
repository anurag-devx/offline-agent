from offline_agent.engine.config import AgentConfig, load_agent
from offline_agent.engine.permissions import Policy
from offline_agent.engine.paths import TEMPLATES_DIR


def test_full_format_round_trip():
    # Regression: the loader once mistook this format for the legacy one (both had "internet").
    p = Policy.from_dict({"files": {"read": "allow", "move": "ask", "folders": ["~/Downloads"]},
                          "internet": {"read": "off"}})
    assert p.mode("files.read") == "allow" and p.mode("files.move") == "ask"
    cfg = AgentConfig(permissions=p)
    assert AgentConfig.from_dict(cfg.to_dict()).to_dict() == cfg.to_dict()


def test_legacy_format_still_loads():
    p = Policy.from_dict({"files_read": "allow", "internet": "ask"}, legacy_domains=["x.com"])
    assert p.mode("files.read") == "allow"
    assert p.mode("internet.read") == "ask" and p.internet.domains == ["x.com"]


def test_yaml_booleans_mean_off_and_allow():
    p = Policy.from_dict({"files": {"read": True, "delete": False}})
    assert p.mode("files.read") == "allow" and p.mode("files.delete") == "off"


def test_every_template_loads():
    names = [load_agent(p).name for p in sorted(TEMPLATES_DIR.glob("*.yaml"))]
    assert len(names) >= 8 and all(names)
