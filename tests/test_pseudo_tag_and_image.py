# -*- coding: utf-8 -*-
"""伪标签不泄漏 + 图片复制/另存（2026-10-27，Owner 实报）

## 两个问题

1. 「偶尔还是会有一些莫名其妙的这种代码会漏在聊天里面」
   —— 模型偶尔不调 say_bubble 工具，把 `<say_bubble>…</say_bubble>` **直接写进正文**。
   实测 `chat_memory_flash.json` 里 6 条 assistant 回复尾部各有一个（开/闭标签各 13 处）。

2. 「我之前其实想的是把它整成一个粘贴板，也就是说我点了之后它是存在我的粘贴板里面的，
   当然它也可以存成图片，不过名字应该叫做另存为图片吧」
   —— 图片按钮原先只有「存文件」一条路，且名字叫「存为图片」。
"""
import os
import sys
import tempfile

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def _pb():
    import pet_bubble as pb
    return pb


# ---------------- ① 伪标签剥离 ----------------

@pytest.mark.parametrize('raw,expect', [
    ('正文A<say_bubble>一句话</say_bubble>', '正文A'),
    ('正文B</say_bubble>', '正文B'),                      # Owner 截图里那种孤立闭合
    ('正文C<say_bubble>', '正文C'),                       # 孤立开标签（最终文本路径直接删）
    ('正文D<SAY_BUBBLE>x</SAY_BUBBLE>', '正文D'),         # 大小写
    ('正文E<say_bubble>\n两行\n</say_bubble>', '正文E'),  # 标签内含换行
])
def test_emotion_tag_strips_say_bubble(raw, expect):
    """最终文本路径必须把伪标签彻底剥掉"""
    pb = _pb()
    cleaned, _emo = pb.strip_emotion_tag(raw)
    assert 'say_bubble' not in cleaned.lower(), '伪标签漏进正文：%r' % cleaned
    assert cleaned.startswith(expect)


def test_normal_text_untouched():
    """不含标签的正常文本不能被改（尤其不能吃掉结尾空格/字符）"""
    pb = _pb()
    for txt in ('只是普通正文', '我说了 say_bubble 这个工具名', '正文结尾有空格 '):
        cleaned, _ = pb.strip_emotion_tag(txt)
        assert cleaned == txt, '正常文本被改动：%r → %r' % (txt, cleaned)


def test_streaming_holds_unclosed_tag():
    """★ 流式：开标签未闭合时，里面的字**不许**当正文显示

    第一版我删掉孤立开标签，实测输出 '这是一段正文。气泡里的话～</say_bubble>'
    —— 气泡文本冒充了正文。现在改为整段扣住等闭合标签。
    """
    pb = _pb()
    shown = ''
    buf = ''
    full = '这是一段正文。<say_bubble>气泡里的话～</say_bubble>'
    for k in range(0, len(full), 3):          # 每 3 字一块，模拟真实 chunk
        cleaned, pending, _ = pb.strip_emotion_tags(buf + full[k:k + 3])
        buf = pending
        shown += cleaned
    assert 'say_bubble' not in shown, '流式显示里还有标签：%r' % shown
    assert '<' not in shown, '流式显示里还有尖括号：%r' % shown
    assert shown == '这是一段正文。', '正文/气泡内容串了：%r' % shown
    assert buf == '', '收尾仍有残留缓冲：%r' % buf


def test_stream_end_unclosed_keeps_inner_text():
    """★ Owner 2026-10-27 裁定：流结束仍不闭合 → 剥标签、**保留里面的字**当正文

    取舍理由（我给的、Owner 采纳）：宁可多显示一句，也不静默吞字。
    反面方案是整段丢弃，那会让「模型写到一半断了」变成用户什么都看不到。
    """
    pb = _pb()
    cleaned, pending, _ = pb.strip_emotion_tags('正文<say_bubble>半句话')
    assert cleaned == '正文'
    assert pending == '<say_bubble>半句话', '未闭合段应被扣住等闭合'
    final = cleaned + pb.strip_say_bubble(pending)      # 收尾 flush 的动作
    assert final == '正文半句话', '收尾后应保留里面的字：%r' % final
    assert 'say_bubble' not in final and '<' not in final


def test_stream_end_truncated_tag_not_leaked():
    """★ 实测抓到的漏：流在 `<say_bub` 处断掉，收尾会把残片原样显示出来

    第一版 `strip_say_bubble` 只删带 `>` 的完整标签 ⇒ `'正文<say_bub'` 原样留下；
    补丁 1d 加了残片切割，但**函数开头的快速返回**又把残片挡在门外
    （`'say_bubble' not in s.lower()` —— 残片天然不含完整标签名）⇒ 补丁 1e 放宽门槛。
    """
    pb = _pb()
    for frag in ('正文<say_bub', '正文<say', '正文<s', '正文<say_bubble', '正文<say_bubble x'):
        got = pb.strip_say_bubble(frag)
        assert got == '正文', '残片漏出来了：%r → %r' % (frag, got)


def test_lone_trailing_angle_kept():
    """⚠ 已知取舍：孤立的尾部 '<' 保留不删

    理由：`'正文<'` 与「数学文本 a < b」在字符串层面无法区分，删掉会吃掉合法内容。
    代价：流恰好在 '<' 之后断开时，界面上会多一个 '<'（1 个字符，比删错正文划算）。
    """
    pb = _pb()
    assert pb.strip_say_bubble('正文<') == '正文<'
    assert pb.strip_say_bubble('正常文本 < 尖括号') == '正常文本 < 尖括号'
    assert pb.strip_say_bubble('正常文本<3') == '正常文本<3'


def test_extract_say_bubbles_returns_content():
    """取出的气泡内容必须非空（我第一版正则漏了捕获组 ⇒ 恒返回 []，被 this 抓过）"""
    pb = _pb()
    got = pb.extract_say_bubbles('正文<say_bubble>记住我哦～</say_bubble>')
    assert got == ['记住我哦～'], '取不到内容：%r' % got
    assert pb.extract_say_bubbles('没有标签') == []


def test_trim_only_in_final_path():
    """最终路径清尾部空行；流式路径不许 trim（否则会粘词）"""
    pb = _pb()
    final, _ = pb.strip_emotion_tag('正文\n\n<say_bubble>x</say_bubble>')
    assert final == '正文', '最终文本尾部还有空行：%r' % final
    stream, _pend, _ = pb.strip_emotion_tags('正文 ')
    assert stream == '正文 ', '流式路径把尾空格吃了（下一块会粘词）：%r' % stream


# ---------------- ② 图片：复制到剪贴板 / 另存为 ----------------

def _pet():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._notify = lambda *a, **k: None
    p.said = []
    p.say_plain = lambda t, **kw: p.said.append(t)
    p.show()
    for _ in range(6):
        app.processEvents()
    return p, app


def _first_bubble(p):
    lay = p.chat_history_layout
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if w is not None:
            return w
    return None


def test_copy_bubble_image_puts_image_on_clipboard():
    """★ Owner 的主要诉求：点图片 = 进剪贴板"""
    from PySide6.QtWidgets import QApplication
    p, app = _pet()
    try:
        p._append_chat('桌宠', '测试复制的消息')
        for _ in range(6):
            app.processEvents()
        b = _first_bubble(p)
        assert b is not None
        assert p._copy_bubble_image(b) is True
        img = QApplication.clipboard().image()
        assert not img.isNull(), '剪贴板里没有图像'
        assert img.width() > 50 and img.height() > 10, '图像尺寸异常 %dx%d' % (img.width(), img.height())
        assert any('剪贴板' in s for s in p.said), '没有给出复制成功提示'
    finally:
        p.close()


def test_render_pixmap_shared_by_copy_and_save():
    """复制与另存共用同一渲染（避免两处各写一遍合成逻辑）"""
    p, app = _pet()
    try:
        p._append_chat('桌宠', '共用渲染测试')
        for _ in range(6):
            app.processEvents()
        b = _first_bubble(p)
        pix = p._render_bubble_pixmap(b)
        assert pix is not None and pix.width() > 50
        tmp = os.path.join(tempfile.gettempdir(), '_bubble_shared.png')
        if os.path.exists(tmp):
            os.remove(tmp)
        assert pix.save(tmp) and os.path.getsize(tmp) > 100
        os.remove(tmp)
    finally:
        p.close()


def test_three_action_buttons_in_both_paths():
    """两条真正会生成按钮的路径都要有 3 个：

        ① AI 回复：_new_bubble + _attach_bubble_actions
        ② 历史回放：_new_bubble_at_top

        ⚠ _append_chat（用户消息 / 系统提示）本来就不加按钮 —— 不是本次漏掉，
          所以不拿它当断言对象（我第一版就是这么写错的）。
    """
    p, app = _pet()
    try:
        # ① AI 回复路径
        b, content = p._new_bubble('桌宠', '10-27 23:00', is_user=False, text='按钮测试')
        content.addWidget(p._bubble_text_label('按钮测试', is_user=False))
        p._attach_bubble_actions(b, '按钮测试')
        for _ in range(6):
            app.processEvents()
        btns = getattr(b, '_action_btns', [])
        assert [x.text() for x in btns] == ['⧉', '🖼', '💾'], '回复气泡按钮不对：%r' % [x.text() for x in btns]
        assert any('剪贴板' in x.toolTip() for x in btns), '缺「复制图片」语义'
        assert any('另存为' in x.toolTip() for x in btns), '缺「另存为」语义'

        # ② 历史回放路径
        hb, _hc = p._new_bubble_at_top('桌宠', '10-27 23:00', is_user=False, text='历史消息')
        for _ in range(6):
            app.processEvents()
        hbtns = getattr(hb, '_action_btns', [])
        assert [x.text() for x in hbtns] == ['⧉', '🖼', '💾'], \
            '历史气泡按钮不对：%r' % [x.text() for x in hbtns]
    finally:
        p.close()


def test_old_label_removed():
    """"存为图片" 这个旧名字必须全部换成 "另存为图片"（否则两个动作都叫"存"，分不清）"""
    import io as _io
    src = _io.open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert "'存为图片'" not in src, '还有旧文案「存为图片」'
    assert '另存为图片' in src
