# -*- coding: utf-8 -*-
"""
model_manager_ui.py — 模型管理对话框（Phase 2）
================================================
入口：右键菜单 → ⚙️ 设置 → 🎯 模型管理…

左侧：档案列表（新增 / 复制 / 删除）
右侧：所选档案的全部字段——显示名、模型 ID、接口地址、副标题、颜色、
      温度、输出上限、思考开关、价格（输入 / 缓存 / 输出，每百万 token 单价）
底部：拉取官方模型列表 / 连通性自检 / 恢复出厂（当前档案）/ 保存 / 关闭

设计要点
--------
- 网络操作（拉列表、探测）放后台线程，结果经 Qt 信号回主线程，界面不卡。
- 保存时把编辑器内容写回 ModelRegistry 并落盘；registry 是唯一来源。
- 「拉取官方模型列表」直接对接 GET /models，「连通性自检」发 max_tokens=1
  的最小请求并把响应里的真实 model 回显出来——这两个动作正是发现
  「官方把模型重命名了」的手段。
"""
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
                               QVBoxLayout)

from deepseek_client import list_models, probe_model
from model_registry import BUILTIN_PROFILES, MAX_OUTPUT_TOKENS, MIN_OUTPUT_TOKENS


class ModelManagerDialog(QDialog):
    """模型档案管理对话框（增删改 + 拉官方列表 + 连通性自检）"""

    net_done = Signal(object)   # 后台网络操作的结果（回主线程处理）
    saved = Signal()            # 档案已落盘（调用方据此热加载）

    def __init__(self, registry, api_key_getter=None, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.api_key_getter = api_key_getter or (lambda: '')
        self._cur = None
        self.setWindowTitle('🎯 模型管理')
        self.resize(900, 620)
        self.net_done.connect(self._on_net_done)
        self._build()
        self._reload_list()

    # ---------- 界面 ----------
    def _build(self):
        root = QHBoxLayout(self)

        # 左：档案列表 + 增删
        left = QVBoxLayout()
        left.addWidget(QLabel('模型档案'))
        self.lst = QListWidget()
        self.lst.setFixedWidth(210)
        self.lst.currentItemChanged.connect(lambda *_: self._on_pick())
        left.addWidget(self.lst)
        row = QHBoxLayout()
        for text, slot in (('新增', self._on_add), ('复制', self._on_dup), ('删除', self._on_del)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        left.addLayout(row)
        self.lbl_src = QLabel('')
        self.lbl_src.setWordWrap(True)
        self.lbl_src.setStyleSheet('color:#7c8486;font-size:11px;')
        left.addWidget(self.lbl_src)
        root.addLayout(left)

        # 右：编辑区
        right = QVBoxLayout()

        gb1 = QGroupBox('身份')
        f1 = QFormLayout(gb1)
        self.ed_name = QLineEdit()
        self.ed_model = QLineEdit()
        self.ed_endpoint = QLineEdit()
        self.ed_sub = QLineEdit()
        self.ed_color = QLineEdit()
        f1.addRow('显示名', self.ed_name)
        f1.addRow('模型 ID', self.ed_model)
        f1.addRow('接口地址', self.ed_endpoint)
        f1.addRow('副标题', self.ed_sub)
        f1.addRow('主题色', self.ed_color)
        right.addWidget(gb1)

        gb2 = QGroupBox('参数')
        f2 = QFormLayout(gb2)
        self.sp_temp = QDoubleSpinBox()
        self.sp_temp.setRange(0.0, 2.0)
        self.sp_temp.setSingleStep(0.1)
        self.sp_temp.setDecimals(2)
        self.sp_tokens = QSpinBox()
        self.sp_tokens.setRange(MIN_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS)
        self.sp_tokens.setSingleStep(1000)
        self.sp_tokens.setGroupSeparatorShown(True)
        self.ck_reason = QCheckBox('开启（推理模型会先输出思考过程）')
        f2.addRow('采样温度', self.sp_temp)
        f2.addRow('输出上限', self.sp_tokens)
        f2.addRow('思考模式', self.ck_reason)
        right.addWidget(gb2)

        gb3 = QGroupBox('价格（每百万 token 单价，用于费用统计）')
        f3 = QFormLayout(gb3)
        self.sp_pin = QDoubleSpinBox()
        self.sp_pcache = QDoubleSpinBox()
        self.sp_pout = QDoubleSpinBox()
        for sp in (self.sp_pin, self.sp_pcache, self.sp_pout):
            sp.setRange(0.0, 9999.0)
            sp.setDecimals(3)
            sp.setSingleStep(0.1)
        f3.addRow('输入', self.sp_pin)
        f3.addRow('缓存命中', self.sp_pcache)
        f3.addRow('输出', self.sp_pout)
        right.addWidget(gb3)

        self.lbl_status = QLabel('')
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet('color:#4d5456;font-size:12px;')
        right.addWidget(self.lbl_status)

        bar = QHBoxLayout()
        self.btn_pull = QPushButton('🔍 拉取官方模型列表')
        self.btn_probe = QPushButton('🩺 连通性自检')
        self.btn_reset = QPushButton('↩ 恢复出厂')
        self.btn_export = QPushButton('📤 导出')
        self.btn_import = QPushButton('📥 导入')
        self.btn_save = QPushButton('💾 保存')
        self.btn_close = QPushButton('关闭')
        self.btn_pull.clicked.connect(self._on_pull)
        self.btn_probe.clicked.connect(self._on_probe)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_import.clicked.connect(self._on_import)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_close.clicked.connect(self.reject)
        for b in (self.btn_pull, self.btn_probe, self.btn_reset, self.btn_export, self.btn_import):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self.btn_save)
        bar.addWidget(self.btn_close)
        right.addLayout(bar)

        root.addLayout(right, 1)

    # ---------- 列表 / 编辑 ----------
    def _reload_list(self, keep=None):
        self.lst.blockSignals(True)
        self.lst.clear()
        for p in self.registry.profiles():
            self.lst.addItem(QListWidgetItem('%s   (%s)' % (p.display_name, p.key)))
        self.lst.blockSignals(False)
        keys = self.registry.keys()
        want = keep or self._cur or (keys[0] if keys else None)
        if want not in keys:
            want = keys[0] if keys else None      # 导入/删除后原选中项可能已不存在
        if want in keys:
            self.lst.setCurrentRow(keys.index(want))
        self.lbl_src.setText('档案来源：models.json（%s）' % self.registry.path)
        self._on_pick()

    def _on_pick(self):
        it = self.lst.currentItem()
        if it is None:
            return
        key = self.registry.keys()[self.lst.currentRow()]
        p = self.registry.get(key)
        if p is None:
            return
        self._cur = key
        self.ed_name.setText(p.display_name)
        self.ed_model.setText(p.model_id)
        self.ed_endpoint.setText(p.endpoint)
        self.ed_sub.setText(p.sub)
        self.ed_color.setText(p.color)
        self.sp_temp.setValue(p.temperature)
        self.sp_tokens.setValue(p.max_tokens)
        self.ck_reason.setChecked(p.reasoning)
        self.sp_pin.setValue(float(p.price.get('input', 0)))
        self.sp_pcache.setValue(float(p.price.get('cache', 0)))
        self.sp_pout.setValue(float(p.price.get('output', 0)))

    def _endpoint(self):
        """探测/拉列表用哪个地址：优先编辑器里的，回退当前档案"""
        return self.ed_endpoint.text().strip() or None

    def _key(self):
        return self.api_key_getter() or ''

    # ---------- 保存 ----------
    def _on_save(self):
        if not self._cur:
            return
        p = self.registry.get(self._cur)
        if p is None:
            return
        name = self.ed_name.text().strip() or self._cur
        mid = self.ed_model.text().strip()
        if not mid:
            QMessageBox.warning(self, '模型管理', '模型 ID 不能为空。')
            return
        self.registry.set_field(self._cur, 'display_name', name)
        self.registry.set_field(self._cur, 'model_id', mid)
        self.registry.set_field(self._cur, 'endpoint', self.ed_endpoint.text().strip() or p.endpoint)
        self.registry.set_field(self._cur, 'sub', self.ed_sub.text().strip())
        self.registry.set_field(self._cur, 'color', self.ed_color.text().strip() or p.color)
        self.registry.set_param(self._cur, 'temperature', self.sp_temp.value())
        self.registry.set_param(self._cur, 'max_tokens', self.sp_tokens.value())
        self.registry.set_param(self._cur, 'reasoning', self.ck_reason.isChecked())
        self.registry.set_price(self._cur, {'input': self.sp_pin.value(),
                                            'cache': self.sp_pcache.value(),
                                            'output': self.sp_pout.value()})
        if not self.registry.save():
            QMessageBox.warning(self, '模型管理', '写入 models.json 失败：%s' % self.registry.last_error)
            return
        self.lbl_status.setText('✓ 已保存到 models.json：%s → %s' % (name, mid))
        self._reload_list(keep=self._cur)
        self.saved.emit()

    # ---------- 增删档案 ----------
    def _on_add(self):
        key, ok = QInputDialog.getText(self, '新增档案', '内部键（英文小写，如 turbo）：')
        key = (key or '').strip()
        if not ok or not key:
            return
        if not self.registry.add_profile(key, display_name=key, copy_from=self._cur):
            QMessageBox.warning(self, '模型管理', '键「%s」已存在或非法。' % key)
            return
        self.registry.save()
        self._reload_list(keep=key)
        self.lbl_status.setText('已新增档案 %s——填好模型 ID 后点保存。' % key)

    def _on_dup(self):
        if not self._cur:
            return
        base = self.registry.get(self._cur)
        key, ok = QInputDialog.getText(self, '复制档案', '新档案的内部键：',
                                       text=self._cur + '_copy')
        key = (key or '').strip()
        if not ok or not key:
            return
        if not self.registry.add_profile(
                key,
                display_name=(base.display_name + ' 副本') if base else key,
                model_id=(base.model_id if base else ''),
                copy_from=self._cur):
            QMessageBox.warning(self, '模型管理', '键「%s」已存在或非法。' % key)
            return
        self.registry.save()
        self._reload_list(keep=key)

    def _on_del(self):
        if not self._cur:
            return
        if len(self.registry) <= 1:
            QMessageBox.information(self, '模型管理', '至少保留一份档案，不能全删。')
            return
        if QMessageBox.question(self, '删除档案', '确定删除「%s」？' % self._cur) != QMessageBox.Yes:
            return
        self.registry.remove_profile(self._cur)
        self.registry.save()
        self._cur = None
        self._reload_list()

    def _on_reset(self):
        """把当前档案恢复为出厂默认（键匹配内置档案时全恢复，否则只清价格）"""
        if not self._cur:
            return
        p = self.registry.get(self._cur)
        builtin = next((b for b in BUILTIN_PROFILES if b['key'] == self._cur), None)
        if builtin is None:
            if QMessageBox.question(self, '恢复出厂',
                                    '该档案不在出厂列表里，只清空价格？') != QMessageBox.Yes:
                return
            p.price = {}
        else:
            if QMessageBox.question(self, '恢复出厂',
                                    '把「%s」恢复为出厂默认？' % self._cur) != QMessageBox.Yes:
                return
            p.display_name = builtin['display_name']
            p.model_id = builtin['model_id']
            p.aliases = list(builtin['aliases'])
            p.endpoint = builtin['endpoint']
            p.temperature = builtin['params']['temperature']
            p.max_tokens = builtin['params']['max_tokens']
            p.reasoning = builtin['params']['reasoning']
            p.price = dict(builtin['price'])
            p.color = builtin['appearance']['color']
            p.sub = builtin['appearance']['sub']
        self.registry.save()
        self._reload_list(keep=self._cur)
        self.lbl_status.setText('已恢复出厂：%s' % self._cur)
        self.saved.emit()

    # ---------- 网络动作（后台线程，不卡界面） ----------
    def _run_bg(self, job, label):
        self.lbl_status.setText(label)
        self.btn_pull.setEnabled(False)
        self.btn_probe.setEnabled(False)

        def work():
            try:
                self.net_done.emit(job())
            except Exception as e:
                self.net_done.emit(('error', str(e)[:160]))
        threading.Thread(target=work, daemon=True).start()

    def _on_pull(self):
        self._run_bg(lambda: ('pull',) + list_models(self._key(), self._endpoint()),
                     '正在拉取官方模型列表…')

    def _on_probe(self):
        mid = self.ed_model.text().strip()
        self._run_bg(lambda: ('probe',) + probe_model(self._key(), mid, self._endpoint()),
                     '正在探测 %s …' % (mid or '(未填模型 ID)'))

    def _on_net_done(self, payload):
        self.btn_pull.setEnabled(True)
        self.btn_probe.setEnabled(True)
        kind = payload[0]
        if kind == 'error':
            self.lbl_status.setText('✗ 出错：%s' % payload[1])
            return
        if kind == 'pull':
            _, ids, err = payload
            if err:
                self.lbl_status.setText('✗ 拉取失败：%s' % err)
                return
            if not ids:
                self.lbl_status.setText('官方没有返回任何模型。')
                return
            pick, ok = QInputDialog.getItem(self, '官方当前可用模型',
                                            '选一个填进「模型 ID」：', ids, 0, False)
            if ok and pick:
                self.ed_model.setText(pick)
                self.lbl_status.setText('已填入官方模型 ID：%s（记得点保存）' % pick)
            else:
                self.lbl_status.setText('官方当前可用：%s' % '、'.join(ids))
            return
        # 连通性探测
        _, ok, real, dt, err = payload
        mid = self.ed_model.text().strip()
        if ok:
            if real and real != mid:
                self.lbl_status.setText(
                    '✓ 通了（%.2f 秒）  响应模型：%s\n注意：请求写的是 %s，官方已把它指向 %s'
                    % (dt, real, mid, real))
            else:
                self.lbl_status.setText('✓ 通了（%.2f 秒）  响应模型：%s' % (dt, real or mid))
        else:
            self.lbl_status.setText('✗ 不通：%s' % err)

    # ---------- 导出 / 导入档案 ----------
    def _on_export(self):
        """把全部档案导出成一个可分享的 JSON（不含密钥）"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, '导出模型档案', 'models-export.json',
                                              'JSON 文件 (*.json)')
        if not path:
            return
        ok, msg = self.registry.export_to(path)
        self.lbl_status.setText(('✓ ' if ok else '✗ ') + msg)

    def _on_import(self):
        """从导出文件导入档案（合并 / 整体替换）"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, '导入模型档案', '', 'JSON 文件 (*.json)')
        if not path:
            return
        ans = QMessageBox.question(self, '导入方式',
                                   '「是」= 合并（同名档案被覆盖，其余保留）\n'
                                   '「否」= 整体替换（现有档案全部丢弃）',
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        mode = 'merge' if ans == QMessageBox.Yes else 'replace'
        ok, msg = self.registry.import_from(path, mode)
        if ok:
            self.registry.save()
            self._cur = None
            self._reload_list()
            self.saved.emit()
        self.lbl_status.setText(('✓ ' if ok else '✗ ') + msg)
