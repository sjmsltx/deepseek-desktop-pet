# -*- coding: utf-8 -*-
"""v6.53 新增：流式取消（/stop 能在流内部生效）回归测试

覆盖 desktop_pet v6.53 的 P0 修复：
  deepseek_client.stream_chat_completions(should_cancel=...) —— 逐块检查取消回调，
  命中即 return（关连接），不再把剩余内容吐完。
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deepseek_client as dc  # noqa: E402


def _sse(lines):
    """构造一个假的 SSE 响应对象（可迭代 + 支持 with）"""
    class _Resp:
        def __iter__(self):
            for ln in lines:
                yield ln

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp()


def _patch_urlopen(monkey_lines, monkeypatch=None):
    """把 deepseek_client 里用到的 urllib.request.urlopen 换成假的

    v6.64：优先用 pytest 的 monkeypatch（用例结束自动恢复）。
    之前是直接赋值 `dc.urllib.request.urlopen = _fake` 且**从未恢复** ——
    会污染后续所有用例（本人排查本地 TTS 用例时被这个坑扰很久：
    后续用例的 urlopen 拿到的是这里伪造的 SSE 流，导致本地服务调用莫名失败）。
    """
    def _fake(req, timeout=300):
        return _sse(monkey_lines)
    if monkeypatch is not None:
        monkeypatch.setattr(dc.urllib.request, 'urlopen', _fake)
    else:
        dc.urllib.request.urlopen = _fake


def _chunks(n):
    out = []
    for i in range(n):
        out.append(('data: {"choices":[{"delta":{"content":"块%d"}}]}\n' % i).encode())
    out.append(b'data: [DONE]\n')
    return out


def test_cancel_stops_early(monkeypatch):
    """取消回调返回 True 后，应立即停止产出（远少于总块数）"""
    _patch_urlopen(_chunks(200), monkeypatch)
    state = {'calls': 0}

    def should_cancel():
        state['calls'] += 1
        return state['calls'] > 3        # 读到第 3 块后请求取消

    got = []
    for evt, val in dc.stream_chat_completions('fake-key', b'{}', should_cancel=should_cancel):
        got.append((evt, val))

    # 允许少量块（回调在下一块才被检查），但绝不该把 200 块读完，也不该产出 'done'
    assert len(got) < 10, '取消未生效：产出 %d 个事件' % len(got)
    assert all(e != 'done' for e, _ in got), '取消后不应产出 done'
    assert state['calls'] <= 6, '取消检查频率异常：%d 次' % state['calls']


def test_without_cancel_completes(monkeypatch):
    """不传 should_cancel 时行为不变：正常收满并产出 done"""
    _patch_urlopen(_chunks(5), monkeypatch)
    got = []
    for evt, val in dc.stream_chat_completions('fake-key', b'{}'):
        got.append((evt, val))

    contents = [v for e, v in got if e == 'content']
    done = [v for e, v in got if e == 'done']
    assert len(contents) == 5, '内容块数不对：%d' % len(contents)
    assert done and '块4' in done[0]['content'], 'done 未携带完整内容'


def test_no_source_regression():
    """源码级护栏：token 上限只走模型档案（不再写 config.json）"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, 'desktop_pet.py'), encoding='utf-8-sig').read()
    assert "_save_cfg_value('max_tokens'" not in src, '仍有写 config.json 的 token 路径'
    assert "should_cancel=lambda" in src, '流式未接入取消回调'
    assert "min(4096, int(getattr(self, 'max_tokens'" in src, '兜底上限仍被写死'


if __name__ == '__main__':
    test_cancel_stops_early()
    test_without_cancel_completes()
    test_no_source_regression()
    print('✅ stream cancel 3 项断言通过')
