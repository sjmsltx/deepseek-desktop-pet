# -*- coding: utf-8 -*-
"""
pet_minigames.py — 桌宠小游戏（v6.30 Phase2）

注册式游戏框架：新增游戏 = 实现 QDialog 子类 + 注册一行到 GAMES。
游戏结果通过 on_result(win) 回调给主程序 → 触发好感度事件（胜 +3/+6XP，参与 +1/+2XP）。
"""
import random

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QLineEdit, QMessageBox, QWidget)
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPainter, QPen, QColor, QBrush


class BaseGame(QDialog):
    """游戏基类：结果通过 on_result(win: bool) 回调"""

    def __init__(self, title: str, on_result, parent=None):
        super().__init__(parent)
        self.on_result = on_result
        self.setWindowTitle(title)
        self.setFixedWidth(340)
        self.setStyleSheet(
            "QDialog { background:#1e2430; }"
            "QLabel { color:#dce3f0; font-size:14px; }"
            "QPushButton { background:#2a3a55; color:#dce3f0; border:none;"
            " border-radius:6px; padding:8px 16px; font-size:14px; }"
            "QPushButton:hover { background:#35507a; }"
            "QLineEdit { background:#141b2c; color:#dce3f0; border:1px solid #3a4a66;"
            " border-radius:6px; padding:6px; font-size:14px; }"
        )

    def _finish(self, win: bool, msg: str):
        QMessageBox.information(self, '结果', msg)
        self.on_result(win)
        self.close()


# ---------- 石头剪刀布 ----------
class RockPaperScissors(BaseGame):
    CHOICES = {'✊ 石头': 'rock', '✋ 剪刀': 'scissors', '🖐 布': 'paper'}
    RULES = {('rock', 'scissors'): True, ('scissors', 'paper'): True, ('paper', 'rock'): True}

    def __init__(self, on_result, parent=None):
        super().__init__('✊ 石头剪刀布', on_result, parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('出拳吧！', alignment=Qt.AlignCenter))
        row = QHBoxLayout()
        for label, key in self.CHOICES.items():
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, k=key: self._play(k))
            row.addWidget(btn)
        lay.addLayout(row)

    def _play(self, choice: str):
        ai = random.choice(list(self.CHOICES.values()))
        ai_label = [k for k, v in self.CHOICES.items() if v == ai][0]
        if choice == ai:
            self._finish(False, f'平局！桌宠出了 {ai_label}')
        elif self.RULES.get((choice, ai)):
            self._finish(True, f'你赢了！桌宠出了 {ai_label}，好感度 +3')
        else:
            self._finish(False, f'你输了…桌宠出了 {ai_label}')


# ---------- 猜数字 ----------
class GuessNumber(BaseGame):
    def __init__(self, on_result, parent=None):
        super().__init__('🔢 猜数字', on_result, parent)
        self.target = random.randint(1, 100)
        self.tries = 0
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('1~100 之间猜一个数字（桌宠心里想好了）', alignment=Qt.AlignCenter))
        self.lb_hint = QLabel('猜吧，会提示大了/小了', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb_hint)
        row = QHBoxLayout()
        self.ed = QLineEdit()
        self.ed.setPlaceholderText('输入数字')
        btn = QPushButton('猜')
        btn.clicked.connect(self._guess)
        self.ed.returnPressed.connect(self._guess)
        row.addWidget(self.ed)
        row.addWidget(btn)
        lay.addLayout(row)

    def _guess(self):
        try:
            n = int(self.ed.text().strip())
        except ValueError:
            self.lb_hint.setText('要输入数字哦')
            return
        self.tries += 1
        if n < self.target:
            self.lb_hint.setText(f'{n} 太小了，再大点')
        elif n > self.target:
            self.lb_hint.setText(f'{n} 太大了，再小点')
        else:
            self._finish(True, f'猜中了！就是 {n}，用了 {self.tries} 次，好感度 +3')


# ---------- 五子棋（简化 AI：连子评估 + 简单防守） ----------
class Gomoku(BaseGame):
    SIZE = 11          # 11x11（比 15 小，AI 更快）
    CELL = 26
    MARGIN = 30

    def __init__(self, on_result, parent=None):
        super().__init__('⚫ 五子棋', on_result, parent)
        self.board = [[0] * self.SIZE for _ in range(self.SIZE)]  # 0空 1人 2AI
        self.turn = 1
        self.over = False
        self._board_widget = _BoardWidget(self)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('你执黑先手，连成五子获胜', alignment=Qt.AlignCenter))
        lay.addWidget(self._board_widget)
        btn = QPushButton('认输')
        btn.clicked.connect(lambda: self._finish(False, '认输了…下次一定赢回来！'))
        lay.addWidget(btn)
        self._board_widget.clicked.connect(self._human_move)

    def _human_move(self, x, y):
        if self.over or self.turn != 1 or self.board[y][x] != 0:
            return
        self.board[y][x] = 1
        if self._check_win(1):
            self.over = True
            self._finish(True, '你赢了！连成五子，好感度 +3')
            return
        if self._is_full():
            self.over = True
            self._finish(False, '平局！棋盘下满了')
            return
        self.turn = 2
        self._ai_move()

    def _ai_move(self):
        x, y = self._best_move()
        self.board[y][x] = 2
        if self._check_win(2):
            self.over = True
            self._finish(False, '桌宠赢了！下次再挑战吧（参与 +1）')
            return
        if self._is_full():
            self.over = True
            self._finish(False, '平局！')
            return
        self.turn = 1
        self._board_widget.update()

    # ---- AI：对每个空位按「进攻 + 防守」评分 ----
    def _score_pos(self, x, y):
        return self._line_score(x, y, 1) + self._line_score(x, y, 2) * 0.9

    def _line_score(self, x, y, player):
        total = 0
        for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            count = 1
            blocked = 0
            for sgn in (1, -1):
                cx, cy = x + dx * sgn, y + dy * sgn
                while 0 <= cx < self.SIZE and 0 <= cy < self.SIZE:
                    v = self.board[cy][cx]
                    if v == player:
                        count += 1
                    elif v == 0:
                        blocked += 1
                        break
                    else:
                        blocked += 2
                        break
                    cx += dx * sgn
                    cy += dy * sgn
            total += {5: 100000, 4: 5000, 3: 500, 2: 60, 1: 5}.get(count, 0) // (1 if blocked < 2 else 2)
        return total

    def _best_move(self):
        best = None
        best_score = -1
        for y in range(self.SIZE):
            for x in range(self.SIZE):
                if self.board[y][x] == 0:
                    s = self._score_pos(x, y)
                    if s > best_score:
                        best_score = s
                        best = (x, y)
        return best or (self.SIZE // 2, self.SIZE // 2)

    def _check_win(self, player):
        for y in range(self.SIZE):
            for x in range(self.SIZE):
                if self.board[y][x] != player:
                    continue
                for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
                    cnt = 1
                    cx, cy = x + dx, y + dy
                    while 0 <= cx < self.SIZE and 0 <= cy < self.SIZE and self.board[cy][cx] == player:
                        cnt += 1
                        cx += dx
                        cy += dy
                    if cnt >= 5:
                        return True
        return False

    def _is_full(self):
        return all(self.board[y][x] != 0 for y in range(self.SIZE) for x in range(self.SIZE))


class _BoardWidget(QWidget):
    clicked = __import__('PySide6.QtCore', fromlist=['Signal']).Signal(int, int)

    def __init__(self, game, parent=None):
        super().__init__(parent)
        self.game = game
        self.setFixedSize(game.CELL * (game.SIZE - 1) + game.MARGIN * 2,
                          game.CELL * (game.SIZE - 1) + game.MARGIN * 2)

    def paintEvent(self, event):
        g = self.game
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#141b2c'))
        pen = QPen(QColor('#3a4a66'))
        p.setPen(pen)
        for i in range(g.SIZE):
            p.drawLine(g.MARGIN, g.MARGIN + i * g.CELL, g.MARGIN + (g.SIZE - 1) * g.CELL, g.MARGIN + i * g.CELL)
            p.drawLine(g.MARGIN + i * g.CELL, g.MARGIN, g.MARGIN + i * g.CELL, g.MARGIN + (g.SIZE - 1) * g.CELL)
        for y in range(g.SIZE):
            for x in range(g.SIZE):
                v = g.board[y][x]
                if v:
                    color = QColor('#111111') if v == 1 else QColor('#e0527a')
                    p.setBrush(QBrush(color))
                    p.setPen(Qt.NoPen)
                    p.drawEllipse(QPoint(g.MARGIN + x * g.CELL, g.MARGIN + y * g.CELL), 9, 9)

    def mousePressEvent(self, event):
        g = self.game
        x = round((event.position().x() - g.MARGIN) / g.CELL)
        y = round((event.position().y() - g.MARGIN) / g.CELL)
        if 0 <= x < g.SIZE and 0 <= y < g.SIZE:
            self.clicked.emit(x, y)


# ---------- 游戏注册表 ----------
GAMES = {
    '✊ 石头剪刀布': RockPaperScissors,
    '🔢 猜数字': GuessNumber,
    '⚫ 五子棋': Gomoku,
}


class GameWindow(QDialog):
    """小游戏选择窗口"""

    def __init__(self, on_result, parent=None):
        super().__init__(parent)
        self.on_result = on_result
        self.setWindowTitle('🎮 小游戏')
        self.setFixedWidth(260)
        self.setStyleSheet(
            "QDialog { background:#1e2430; }"
            "QLabel { color:#dce3f0; font-size:13px; }"
            "QPushButton { background:#2a3a55; color:#dce3f0; border:none;"
            " border-radius:6px; padding:10px; font-size:14px; }"
            "QPushButton:hover { background:#35507a; }"
        )
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('和桌宠玩一局？赢了好感度 +3', alignment=Qt.AlignCenter))
        for name, cls in GAMES.items():
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, c=cls: self._open(c))
            lay.addWidget(btn)

    def _open(self, cls):
        self.hide()
        g = cls(self.on_result, self.parent())
        g.exec()
        self.close()
