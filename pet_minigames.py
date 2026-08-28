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


# ---------- 2048 ----------
class Game2048(BaseGame):
    """2048：方向键移动合并，目标是 2048"""

    def __init__(self, on_result, parent=None):
        super().__init__('🔢 2048', on_result, parent)
        self.setFixedSize(340, 380)
        self.board = [[0] * 4 for _ in range(4)]
        self.score = 0
        self._spawn()
        self._spawn()
        lay = QVBoxLayout(self)
        self.lb = QLabel('方向键移动，合并数字，到 2048 胜利', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb)
        self.lb_board = QLabel('', alignment=Qt.AlignCenter)
        self.lb_board.setStyleSheet('font-family:Consolas,monospace; font-size:18px;')
        lay.addWidget(self.lb_board)
        self._render()
        self.setFocusPolicy(Qt.StrongFocus)

    def _spawn(self):
        empty = [(x, y) for y in range(4) for x in range(4) if self.board[y][x] == 0]
        if empty:
            x, y = random.choice(empty)
            self.board[y][x] = 2 if random.random() < 0.9 else 4

    def _render(self):
        colors = {0: '#141b2c', 2: '#2a3a55', 4: '#35507a', 8: '#3f6ca8',
                  16: '#4a8ac2', 32: '#5aa7d6', 64: '#e0527a', 128: '#e8739a',
                  256: '#f09ab5', 512: '#f5b8cc', 1024: '#ffd700', 2048: '#ff8c00'}
        html = ['<table cellspacing="4" align="center">']
        for y in range(4):
            html.append('<tr>')
            for x in range(4):
                v = self.board[y][x]
                c = colors.get(v, '#e0527a')
                txt = str(v) if v else ''
                html.append(f'<td width="64" height="64" style="background:{c};border-radius:8px;'
                            f'color:{"#fff" if v >= 8 else "#dce3f0"};font-weight:bold;text-align:center;">'
                            f'{txt}</td>')
            html.append('</tr>')
        html.append('</table>')
        self.lb_board.setText(''.join(html))

    def _move(self, dx, dy):
        moved = False
        if dy == 0:
            order_x = range(4) if dx > 0 else range(3, -1, -1)
            for y in range(4):
                line = [self.board[y][x] for x in order_x]
                nl = self._merge(line)
                for i, x in enumerate(order_x):
                    if self.board[y][x] != nl[i]:
                        moved = True
                    self.board[y][x] = nl[i]
        else:
            order_y = range(4) if dy > 0 else range(3, -1, -1)
            for x in range(4):
                line = [self.board[y][x] for y in order_y]
                nl = self._merge(line)
                for i, y in enumerate(order_y):
                    if self.board[y][x] != nl[i]:
                        moved = True
                    self.board[y][x] = nl[i]
        if moved:
            self._spawn()
            self._render()
            if max(max(r) for r in self.board) >= 2048:
                self._finish(True, f'2048 达成！得分 {self.score}，好感度 +3')
            elif not any(0 in r for r in self.board):
                self._finish(False, f'棋盘满了，得分 {self.score}（参与 +1）')

    def _merge(self, line):
        non_zero = [v for v in line if v]
        merged = []
        i = 0
        while i < len(non_zero):
            if i + 1 < len(non_zero) and non_zero[i] == non_zero[i + 1]:
                merged.append(non_zero[i] * 2)
                self.score += non_zero[i] * 2
                i += 2
            else:
                merged.append(non_zero[i])
                i += 1
        return merged + [0] * (4 - len(merged))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Left:
            self._move(-1, 0)
        elif event.key() == Qt.Key_Right:
            self._move(1, 0)
        elif event.key() == Qt.Key_Up:
            self._move(0, -1)
        elif event.key() == Qt.Key_Down:
            self._move(0, 1)
        else:
            super().keyPressEvent(event)


# ---------- 扫雷 ----------
class Minesweeper(BaseGame):
    """扫雷：9x9，10 雷，左键翻开，右键标雷"""

    def __init__(self, on_result, parent=None):
        super().__init__('💣 扫雷', on_result, parent)
        self.W = 9
        self.H = 9
        self.MINES = 10
        self.grid = [[0] * self.W for _ in range(self.H)]  # 0-8 数字, 9=雷
        self.revealed = [[False] * self.W for _ in range(self.H)]
        self.flagged = [[False] * self.W for _ in range(self.H)]
        self.started = False
        self.over = False
        self._widget = _MineWidget(self)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('左键翻开 · 右键标雷 · 避开 10 颗雷', alignment=Qt.AlignCenter))
        lay.addWidget(self._widget)
        self._widget.clicked.connect(self._on_click)

    def _plant(self, ex, ey):
        import random as rnd
        cells = [(x, y) for y in range(self.H) for x in range(self.W) if (x, y) != (ex, ey)]
        for _ in range(self.MINES):
            x, y = rnd.choice(cells)
            cells.remove((x, y))
            self.grid[y][x] = 9
        for y in range(self.H):
            for x in range(self.W):
                if self.grid[y][x] != 9:
                    self.grid[y][x] = sum(
                        1 for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                        if 0 <= x + dx < self.W and 0 <= y + dy < self.H and self.grid[y + dy][x + dx] == 9)

    def _on_click(self, x, y, right):
        if self.over:
            return
        if not self.started:
            self.started = True
            self._plant(x, y)
        if right:
            self.flagged[y][x] = not self.flagged[y][x]
            self._widget.update()
            return
        if self.flagged[y][x] or self.revealed[y][x]:
            return
        if self.grid[y][x] == 9:
            self.over = True
            self._reveal_all()
            self._finish(False, '踩雷了！下次小心（参与 +1）')
            return
        self._flood(x, y)
        self._widget.update()
        if all(self.revealed[y][x] or self.grid[y][x] == 9 for y in range(self.H) for x in range(self.W)):
            self.over = True
            self._finish(True, '全部排完了！好感度 +3')

    def _flood(self, x, y):
        if not (0 <= x < self.W and 0 <= y < self.H) or self.revealed[y][x] or self.grid[y][x] == 9:
            return
        self.revealed[y][x] = True
        if self.grid[y][x] == 0:
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    self._flood(x + dx, y + dy)

    def _reveal_all(self):
        for y in range(self.H):
            for x in range(self.W):
                self.revealed[y][x] = True


class _MineWidget(QWidget):
    clicked = __import__('PySide6.QtCore', fromlist=['Signal']).Signal(int, int, bool)

    def __init__(self, game, parent=None):
        super().__init__(parent)
        self.game = game
        cell = 32
        self.setFixedSize(cell * game.W, cell * game.H)

    def paintEvent(self, event):
        g = self.game
        p = QPainter(self)
        cell = 32
        for y in range(g.H):
            for x in range(g.W):
                rect = QRect(x * cell, y * cell, cell - 1, cell - 1)
                if g.revealed[y][x]:
                    p.fillRect(rect, QColor('#182136'))
                    v = g.grid[y][x]
                    if v == 9:
                        p.setPen(QColor('#ff8a8a'))
                        p.drawText(rect, Qt.AlignCenter, '💣')
                    elif v:
                        colors = {1: '#9fd0ff', 2: '#6ecb7a', 3: '#ff8a8a', 4: '#e0527a', 5: '#c9a0ff'}
                        p.setPen(QColor(colors.get(v, '#dce3f0')))
                        p.drawText(rect, Qt.AlignCenter, str(v))
                else:
                    p.fillRect(rect, QColor('#2a3a55'))
                    if g.flagged[y][x]:
                        p.setPen(QColor('#ffd700'))
                        p.drawText(rect, Qt.AlignCenter, '🚩')

    def mousePressEvent(self, event):
        g = self.game
        cell = 32
        x = int(event.position().x() // cell)
        y = int(event.position().y() // cell)
        if 0 <= x < g.W and 0 <= y < g.H:
            self.clicked.emit(x, y, event.button().name == 'RightButton')


# ---------- 游戏注册表 ----------
GAMES = {
    '✊ 石头剪刀布': RockPaperScissors,
    '🔢 猜数字': GuessNumber,
    '⚫ 五子棋': Gomoku,
    '🔢 2048': Game2048,
    '💣 扫雷': Minesweeper,
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
