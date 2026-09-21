# -*- coding: utf-8 -*-
"""3.0 适配层与面板的回归测试（P0）。

护栏重点：
  · 只读、不读凭据文件、失败必须降级而**不抛异常**
  · 令牌地址解析要能吃下日志格式，且格式变了要返回 None 而不是乱猜
  · 服务不在时 probe() 要给出可读原因，而不是崩
测试纪律（项目约定）：一律用 monkeypatch.setattr 做替身，禁止裸赋值模块属性。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dsh_adapter as ad  # noqa: E402
import dsh_panel as panel  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_discovery(monkeypatch, tmp_path):
    """所有测试都不去发现真实环境（否则会读到本机正在跑的 DSH，导致断言不确定）。"""
    monkeypatch.setattr(ad, "resolve_root", lambda: str(tmp_path / "no-real-root"))
    monkeypatch.setattr(ad, "resolve_port", lambda: ad.DEFAULT_PORT)
    monkeypatch.setattr(ad, "_DISCOVERY_CACHE", {"ts": 0.0, "data": None})


# ---------- 令牌地址解析 ----------

def test_read_token_url_parses_log(tmp_path, monkeypatch):
    log = tmp_path / "dsh-web.log"
    log.write_text("booting...\ndsh web: http://127.0.0.1:3080/?token=TESTTOKEN123\n",
                   encoding="utf-8")
    monkeypatch.setattr(ad, "LOG_CANDIDATES", [str(log)])
    assert ad.read_token_url() == "http://127.0.0.1:3080/?token=TESTTOKEN123"


def test_read_token_url_takes_last_line(tmp_path, monkeypatch):
    log = tmp_path / "dsh-web.log"
    log.write_text("dsh web: http://127.0.0.1:3080/?token=OLD\n"
                   "dsh web: http://127.0.0.1:3080/?token=NEW\n", encoding="utf-8")
    monkeypatch.setattr(ad, "LOG_CANDIDATES", [str(log)])
    assert ad.read_token_url().endswith("token=NEW")


def test_read_token_url_returns_none_when_format_changed(tmp_path, monkeypatch):
    """格式变了要如实返回 None（让调用方降级），不能瞎编地址。"""
    log = tmp_path / "dsh-web.log"
    log.write_text("dsh web started, token hidden for security\n", encoding="utf-8")
    monkeypatch.setattr(ad, "LOG_CANDIDATES", [str(log)])
    assert ad.read_token_url() is None


def test_read_token_url_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(ad, "LOG_CANDIDATES", [str(tmp_path / "nope.log")])
    assert ad.read_token_url() is None


# ---------- 配置只读镜像 ----------

def test_read_settings_missing_file_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(ad, "DSH_HOME", str(tmp_path / "no-such-home"))
    assert ad.read_settings() == {}


def test_read_settings_fallback_parse(monkeypatch, tmp_path):
    home = tmp_path / ".dsh"
    home.mkdir()
    (home / "settings.yaml").write_text("ui-onboarding: done\nport: 3080\n", encoding="utf-8")
    monkeypatch.setattr(ad, "DSH_HOME", str(home))
    data = ad.read_settings()
    assert isinstance(data, dict) and data  # 有没有 yaml 库都要能返回内容


def test_never_reads_credentials(monkeypatch, tmp_path):
    """凭据文件永不被读取：即使只有它存在，也必须返回空。"""
    home = tmp_path / ".dsh"
    home.mkdir()
    (home / ".credentials.yaml").write_text("secret: sk-should-never-be-read\n", encoding="utf-8")
    monkeypatch.setattr(ad, "DSH_HOME", str(home))
    assert ad.read_settings() == {}


# ---------- 探测与降级 ----------

def test_probe_not_serving_degrades(monkeypatch):
    monkeypatch.setattr(ad, "is_serving", lambda *a, **k: False)
    monkeypatch.setattr(ad, "read_version", lambda *a, **k: "0.1.5-rc.2")
    info = ad.probe()
    assert info["serving"] is False
    assert info["url"] is None
    assert "未运行" in info["reason"]


def test_probe_serving_but_no_url(monkeypatch):
    monkeypatch.setattr(ad, "is_serving", lambda *a, **k: True)
    monkeypatch.setattr(ad, "read_token_url", lambda *a, **k: None)
    monkeypatch.setattr(ad, "read_version", lambda *a, **k: None)
    info = ad.probe()
    assert info["serving"] is True and info["url"] is None
    assert "令牌" in info["reason"]


def test_probe_full_success(monkeypatch):
    monkeypatch.setattr(ad, "is_serving", lambda *a, **k: True)
    monkeypatch.setattr(ad, "read_token_url", lambda *a, **k: "http://127.0.0.1:3080/?token=X")
    monkeypatch.setattr(ad, "http_status", lambda *a, **k: (200, 1234, ""))
    monkeypatch.setattr(ad, "read_settings", lambda *a, **k: {"ui-onboarding": "done"})
    monkeypatch.setattr(ad, "read_version", lambda *a, **k: "0.1.5-rc.2")
    info = ad.probe()
    assert info["status"] == 200 and info["settings_ok"] is True
    assert info["version"] == "0.1.5-rc.2" and info["reason"] == ""


# ---------- 面板：只做宿主，失败要给可读原因 ----------

def test_panel_reports_when_launcher_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(panel.ad, "is_serving", lambda *a, **k: False)
    monkeypatch.setattr(panel, "LAUNCHER", str(tmp_path / "no-launcher.ps1"))
    ok, msg = panel.open_panel()
    assert ok is False and "找不到启动器" in msg


def test_panel_reports_when_url_unavailable(monkeypatch):
    monkeypatch.setattr(panel.ad, "is_serving", lambda *a, **k: True)
    monkeypatch.setattr(panel.ad, "read_token_url", lambda *a, **k: None)
    ok, msg = panel.open_panel()
    assert ok is False and "令牌" in msg


def test_panel_opens_with_edge_app_mode(monkeypatch, tmp_path):
    """可用路径：找到 Edge 就用 --app 打开，且参数里必须是那个带令牌地址。"""
    fake_edge = tmp_path / "msedge.exe"
    fake_edge.write_text("", encoding="utf-8")
    calls = []

    monkeypatch.setattr(panel.ad, "is_serving", lambda *a, **k: True)
    monkeypatch.setattr(panel.ad, "read_token_url",
                        lambda *a, **k: "http://127.0.0.1:3080/?token=T")
    monkeypatch.setattr(panel.ad, "http_status", lambda *a, **k: (200, 10, ""))
    monkeypatch.setattr(panel, "BROWSERS", [("Edge", [str(fake_edge)])])
    monkeypatch.setattr(panel, "_spawn", lambda args: (calls.append(args), True)[1])

    ok, msg = panel.open_panel()
    assert ok is True and "Edge" in msg
    assert calls and calls[0][0] == str(fake_edge)
    assert any(str(a).startswith("--app=") for a in calls[0])


# ---------- 端口/位置自动发现（“别人的 DSH 自定义了端口”怎么整）----------

def test_discovery_user_config_wins(monkeypatch, tmp_path):
    cfg = tmp_path / "dsh_config.json"
    cfg.write_text('{"root": "D:\\\\custom\\\\dsh", "port": 4444}', encoding="utf-8")
    monkeypatch.setattr(ad, "USER_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(ad, "_running_dsh_processes", lambda *a, **k: [])
    d = ad.discover(force=True)
    assert d["port"] == 4444 and d["root"] == "D:\\custom\\dsh"
    assert "用户配置" in d["port_source"] and "用户配置" in d["root_source"]


def test_discovery_reads_running_process_port(monkeypatch):
    """没配置、没环境变量时，从运行中进程的 --port 真发现出来。"""
    monkeypatch.setattr(ad, "USER_CONFIG_PATH", "no-such-config.json")
    monkeypatch.delenv("DSH_PORT", raising=False)
    monkeypatch.delenv("DSH_ROOT", raising=False)
    monkeypatch.setattr(ad, "_running_dsh_processes", lambda *a, **k: [
        {"pid": 111, "cmdline": "node bin.js web --port 3900", "root": "E:\\somewhere\\dsh", "port": 3900}
    ])
    d = ad.discover(force=True)
    assert d["port"] == 3900 and d["root"] == "E:\\somewhere\\dsh"
    assert "运行中进程" in d["port_source"]


def test_discovery_env_overrides_process(monkeypatch):
    monkeypatch.setattr(ad, "USER_CONFIG_PATH", "no-such-config.json")
    monkeypatch.setenv("DSH_PORT", "4100")
    monkeypatch.setenv("DSH_ROOT", "F:\\env\\dsh")
    monkeypatch.setattr(ad, "_running_dsh_processes", lambda *a, **k: [
        {"pid": 1, "cmdline": "x", "root": "E:\\other", "port": 3900}
    ])
    d = ad.discover(force=True)
    assert d["port"] == 4100 and d["root"] == "F:\\env\\dsh"
    assert "环境变量" in d["port_source"]


def test_discovery_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(ad, "USER_CONFIG_PATH", "no-such-config.json")
    monkeypatch.delenv("DSH_PORT", raising=False)
    monkeypatch.delenv("DSH_ROOT", raising=False)
    monkeypatch.setattr(ad, "_running_dsh_processes", lambda *a, **k: [])
    monkeypatch.setattr(ad, "_port_from_logs", lambda: None)
    d = ad.discover(force=True)
    assert d["port"] == 3080 and "默认值" in d["port_source"]


def test_discovery_uses_log_port_when_process_unknown(monkeypatch):
    """进程命令行看不到端口（例如 npx 启动），退一步从启动日志里的 URL 反推。"""
    monkeypatch.setattr(ad, "USER_CONFIG_PATH", "no-such-config.json")
    monkeypatch.delenv("DSH_PORT", raising=False)
    monkeypatch.setattr(ad, "_running_dsh_processes", lambda *a, **k: [])
    monkeypatch.setattr(ad, "_port_from_logs", lambda: 3210)
    d = ad.discover(force=True)
    assert d["port"] == 3210 and "日志" in d["port_source"]
