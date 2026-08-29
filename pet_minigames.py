# -*- coding: utf-8 -*-
"""
pet_minigames.py — 桌宠小游戏（v6.30 Phase2）

注册式游戏框架：新增游戏 = 实现 QDialog 子类 + 注册一行到 GAMES。
游戏结果通过 on_result(win) 回调给主程序 → 触发好感度事件（胜 +3/+6XP，参与 +1/+2XP）。
"""
import random

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QLineEdit, QMessageBox, QWidget, QGridLayout, QComboBox)
from PySide6.QtCore import Qt, QPoint, QRect, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QBrush


class BaseGame(QDialog):
    """游戏基类：结果通过 on_result(win, score) 回调；支持难度选择"""

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
            "QPushButton:disabled { background:#1c2740; color:#667; }"
            "QComboBox { background:#141b2c; color:#dce3f0; border:1px solid #3a4a66;"
            " border-radius:6px; padding:4px 8px; font-size:13px; }"
            "QLineEdit { background:#141b2c; color:#dce3f0; border:1px solid #3a4a66;"
            " border-radius:6px; padding:6px; font-size:14px; }"
        )
        self._difficulties = {}
        self._combo = None
        self.difficulty = None

    def _add_difficulty(self, lay, difficulties: dict):
        """难度选择：difficulties = {显示名: 值}。少于 2 档自动隐藏下拉。"""
        self._difficulties = difficulties
        if len(difficulties) >= 2:
            row = QHBoxLayout()
            row.addWidget(QLabel('难度'))
            self._combo = QComboBox()
            for name in difficulties:
                self._combo.addItem(name)
            self._combo.currentIndexChanged.connect(lambda _: self._apply_difficulty())
            row.addWidget(self._combo)
            row.addStretch(1)
            lay.insertLayout(0, row)
        self._apply_difficulty()

    def _apply_difficulty(self):
        if self._combo is not None:
            self.difficulty = self._difficulties.get(self._combo.currentText())
        else:
            self.difficulty = next(iter(self._difficulties.values()), None)

    def _finish(self, win: bool, msg: str, score: int = 0):
        QMessageBox.information(self, '结果', msg)
        try:
            self.on_result(win, score)
        except TypeError:
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
            # dx>0 向右滑：从右往左取行合并（大数字靠右）
            order_x = range(3, -1, -1) if dx > 0 else range(4)
            for y in range(4):
                line = [self.board[y][x] for x in order_x]
                nl = self._merge(line)
                for i, x in enumerate(order_x):
                    if self.board[y][x] != nl[i]:
                        moved = True
                    self.board[y][x] = nl[i]
        else:
            # dy>0 向下滑：从下往上取列合并
            order_y = range(3, -1, -1) if dy > 0 else range(4)
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
            self.clicked.emit(x, y, event.button() == Qt.RightButton)


# ---------- 贪吃蛇 ----------
class Snake(BaseGame):
    """贪吃蛇：方向键控制，吃食物变长"""

    SIZE = 20
    CELL = 15

    def __init__(self, on_result, parent=None):
        super().__init__('🐍 贪吃蛇', on_result, parent)
        self.setFixedSize(340, 400)
        self.snake = [(10, 10), (9, 10), (8, 10)]
        self.dir = (1, 0)
        self.score = 0
        self.over = False
        self.food = self._spawn_food()
        self._widget = _SnakeWidget(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)
        self.timer.start(130)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('方向键控制，吃到食物变长', alignment=Qt.AlignCenter))
        lay.addWidget(self._widget)
        self.lb = QLabel('得分 0', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb)
        self.setFocusPolicy(Qt.StrongFocus)

    def _spawn_food(self):
        while True:
            f = (random.randint(0, self.SIZE - 1), random.randint(0, self.SIZE - 1))
            if f not in self.snake:
                return f

    def _step(self):
        if self.over:
            return
        head = (self.snake[0][0] + self.dir[0], self.snake[0][1] + self.dir[1])
        if head in self.snake or not (0 <= head[0] < self.SIZE and 0 <= head[1] < self.SIZE):
            self.over = True
            self.timer.stop()
            self._finish(False, f'撞到了！得分 {self.score}（参与 +1）')
            return
        self.snake.insert(0, head)
        if head == self.food:
            self.score += 1
            self.lb.setText(f'得分 {self.score}')
            self.food = self._spawn_food()
        else:
            self.snake.pop()
        self._widget.update()

    def keyPressEvent(self, e):
        m = {Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1), Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0)}
        d = m.get(e.key())
        if d and (d[0] != -self.dir[0] or d[1] != -self.dir[1]):
            self.dir = d
        else:
            super().keyPressEvent(e)


class _SnakeWidget(QWidget):
    def __init__(self, game, parent=None):
        super().__init__(parent)
        self.game = game
        self.setFixedSize(game.SIZE * game.CELL, game.SIZE * game.CELL)

    def paintEvent(self, event):
        g = self.game
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#141b2c'))
        # 食物
        p.setBrush(QBrush(QColor('#e0527a')))
        p.setPen(Qt.NoPen)
        p.drawEllipse(g.food[0] * g.CELL + 2, g.food[1] * g.CELL + 2, g.CELL - 4, g.CELL - 4)
        # 蛇
        for i, (x, y) in enumerate(g.snake):
            color = QColor('#6ecb7a') if i == 0 else QColor('#3f8f5f')
            p.setBrush(QBrush(color))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(x * g.CELL + 1, y * g.CELL + 1, g.CELL - 2, g.CELL - 2, 3, 3)


# ---------- 记忆翻牌 ----------
class MemoryMatch(BaseGame):
    """记忆翻牌：配对 8 对表情卡片"""

    def __init__(self, on_result, parent=None):
        super().__init__('🃏 记忆翻牌', on_result, parent)
        self.setFixedWidth(300)
        emojis = ['🍎', '🍊', '🍇', '🍓', '🍑', '🥝', '🍉', '🍒'] * 2
        random.shuffle(emojis)
        self.cards = emojis
        self.revealed = [False] * 16
        self.matched = [False] * 16
        self.first = None
        self.tries = 0
        self.buttons = []
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('翻开配对，全部配对获胜', alignment=Qt.AlignCenter))
        grid = QGridLayout()
        for i in range(16):
            btn = QPushButton('❓')
            btn.setFixedSize(56, 56)
            btn.setStyleSheet(
                'QPushButton { background:#2a3a55; color:#dce3f0; border:1px solid #3a4a66;'
                ' border-radius:8px; font-size:20px; }'
                'QPushButton:hover { background:#35507a; }'
                'QPushButton:disabled { background:#1c2740; color:#8aa; }')
            btn.clicked.connect(lambda checked, idx=i: self._flip(idx))
            grid.addWidget(btn, i // 4, i % 4)
            self.buttons.append(btn)
        lay.addLayout(grid)
        self.lb = QLabel('尝试 0 次', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb)

    def _flip(self, idx):
        if self.matched[idx] or self.revealed[idx]:
            return
        self.revealed[idx] = True
        self.buttons[idx].setText(self.cards[idx])
        if self.first is None:
            self.first = idx
            return
        self.tries += 1
        self.lb.setText(f'尝试 {self.tries} 次')
        a, b = self.first, idx
        self.first = None
        if self.cards[a] == self.cards[b]:
            self.matched[a] = self.matched[b] = True
            self.buttons[a].setEnabled(False)
            self.buttons[b].setEnabled(False)
            if all(self.matched):
                self._finish(True, f'全部配对！用了 {self.tries} 次，好感度 +3')
        else:
            QTimer.singleShot(650, lambda: self._unflip(a, b))

    def _unflip(self, a, b):
        if not self.matched[a]:
            self.revealed[a] = False
            self.buttons[a].setText('❓')
        if not self.matched[b]:
            self.revealed[b] = False
            self.buttons[b].setText('❓')


# ---------- 井字棋 ----------
class TicTacToe(BaseGame):
    """井字棋：3×3，三档 AI 难度"""

    def __init__(self, on_result, parent=None):
        super().__init__('⚫ 井字棋', on_result, parent)
        self.setFixedWidth(320)
        self.board = [''] * 9
        self.turn = 'X'  # 玩家 X，AI O
        self.over = False
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('你执 X，连成一线获胜', alignment=Qt.AlignCenter))
        self._add_difficulty(lay, {'简单': 0, '普通': 1, '困难': 2})
        self.lb = QLabel('', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb)
        grid = QGridLayout()
        self.btns = []
        for i in range(9):
            btn = QPushButton('')
            btn.setFixedSize(70, 70)
            btn.setStyleSheet(
                'QPushButton { background:#182136; color:#dce3f0; border:1px solid #3a4a66;'
                ' border-radius:8px; font-size:26px; }'
                'QPushButton:hover { background:#24314a; }')
            btn.clicked.connect(lambda checked, idx=i: self._move(idx))
            grid.addWidget(btn, i // 3, i % 3)
            self.btns.append(btn)
        lay.addLayout(grid)
        self._render()

    def _render(self):
        for i, b in enumerate(self.btns):
            b.setText(self.board[i])
        w = self._winner()
        if w:
            self.lb.setText(f'{"你" if w == "X" else "桌宠"}赢了！')
        elif '' not in self.board:
            self.lb.setText('平局')
        else:
            self.lb.setText('轮到你（X）' if self.turn == 'X' else '桌宠思考中…')

    def _winner(self):
        lines = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
        for a, b, c in lines:
            if self.board[a] and self.board[a] == self.board[b] == self.board[c]:
                return self.board[a]
        return None

    def _move(self, idx):
        if self.over or self.turn != 'X' or self.board[idx]:
            return
        self.board[idx] = 'X'
        if self._check_end():
            return
        self.turn = 'O'
        self._render()
        QTimer.singleShot(300, self._ai_move)

    def _ai_move(self):
        if self.over:
            return
        d = self.difficulty or 1
        idx = None
        if d >= 1:  # 普通/困难：先堵玩家再赢
            idx = self._find_win('O')
            if idx is None and d >= 2:
                idx = self._find_win('X')  # 困难：堵玩家
        if idx is None:
            if d == 0:  # 简单：随机
                empties = [i for i, v in enumerate(self.board) if not v]
                idx = random.choice(empties) if empties else None
            else:
                idx = self._find_win('X')  # 普通：堵玩家
                if idx is None:
                    center = 4
                    if not self.board[center]:
                        idx = center
                    else:
                        empties = [i for i, v in enumerate(self.board) if not v]
                        idx = random.choice(empties) if empties else None
        if idx is not None:
            self.board[idx] = 'O'
            self.turn = 'X'
            self._check_end()
            self._render()

    def _find_win(self, player):
        for i, v in enumerate(self.board):
            if not v:
                self.board[i] = player
                w = self._winner()
                self.board[i] = ''
                if w == player:
                    return i
        return None

    def _check_end(self):
        w = self._winner()
        if w:
            self.over = True
            win = w == 'X'
            self._finish(win, f'你赢了！好感度 +3' if win else f'桌宠赢了！（参与 +1）')
            return True
        if '' not in self.board:
            self.over = True
            self._finish(False, '平局！（参与 +1）')
            return True
        return False


# ---------- Farkle 骰子（天国拯救同款） ----------
class Farkle(BaseGame):
    """Farkle：目标分自选（500~10000），和桌宠轮流掷 6 骰，先到目标分获胜"""

    TARGETS = [('500', 500), ('1000', 1000), ('1500', 1500), ('2000', 2000),
               ('3000', 3000), ('4000', 4000), ('8000', 8000), ('10000', 10000)]

    def __init__(self, on_result, parent=None):
        super().__init__('🎲 Farkle 骰子', on_result, parent)
        self.setFixedWidth(380)
        self.pscore = 0       # 玩家总成绩
        self.escore = 0       # 桌宠总成绩
        self.turn = 'player'  # player / enemy
        self.turn_score = 0   # 当前回合累计
        self.dice = []        # 剩余骰子
        self.pending = []     # 待计分的骰子
        self.kept_dice = []   # 本回合已保留的骰子
        self.over = False
        lay = QVBoxLayout(self)
        row0 = QHBoxLayout()
        row0.addWidget(QLabel('目标分'))
        self.combo_target = QComboBox()
        for label, v in self.TARGETS:
            self.combo_target.addItem(label, v)
        self.combo_target.setCurrentText('4000')
        row0.addWidget(self.combo_target)
        row0.addStretch(1)
        lay.addLayout(row0)
        self._add_difficulty(lay, {'普通': 0, '高手局': 1})
        self.lb_info = QLabel('目标 4000 分，先到者胜！', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb_info)
        self.lb_dice = QLabel('点击「掷骰子」开始', alignment=Qt.AlignCenter)
        self.lb_dice.setStyleSheet('font-size:22px;')
        lay.addWidget(self.lb_dice)
        self.lb_score = QLabel('你: 0 ｜ 桌宠: 0', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb_score)
        self.lb_turn = QLabel('', alignment=Qt.AlignCenter)
        self.lb_turn.setStyleSheet('color:#8aa; font-size:12px;')
        lay.addWidget(self.lb_turn)
        row = QHBoxLayout()
        self.btn_roll = QPushButton('🎲 掷骰子')
        self.btn_roll.clicked.connect(self._roll)
        self.btn_keep = QPushButton('✅ 保留')
        self.btn_keep.clicked.connect(self._keep)
        self.btn_lock = QPushButton('🔒 锁定回合')
        self.btn_lock.clicked.connect(self._lock)
        row.addWidget(self.btn_roll)
        row.addWidget(self.btn_keep)
        row.addWidget(self.btn_lock)
        lay.addLayout(row)
        self._sync_ui()

    # ---------- 计分规则 ----------
    @staticmethod
    def score_dice(dice):
        """返回 (分数, 可计分骰子索引集合)。无计分返回 (0, set())。"""
        from collections import Counter
        n = len(dice)
        if n == 6 and sorted(dice) == [1, 2, 3, 4, 5, 6]:
            return 1500, set(range(6))
        counts = Counter(dice)
        if n == 6 and sorted(counts.values()) == [2, 2, 2]:
            return 1500, set(range(6))
        score = 0
        usable = set()
        for v, c in counts.items():
            if c >= 3:
                base = 1000 if v == 1 else v * 100
                mult = 2 ** (c - 3)
                score += base * mult   # 4个=2x, 5个=4x, 6个=8x（已覆盖全部 c 个骰子）
                for i, d in enumerate(dice):
                    if d == v:
                        usable.add(i)
            else:
                if v == 1:
                    score += 100 * c
                    for i, d in enumerate(dice):
                        if d == 1:
                            usable.add(i)
                elif v == 5:
                    score += 50 * c
                    for i, d in enumerate(dice):
                        if d == 5:
                            usable.add(i)
        return score, usable

    # ---------- 游戏流程 ----------
    def _roll(self):
        if self.over or self.turn != 'player':
            return
        if not self.dice:
            self.dice = [random.randint(1, 6) for _ in range(6)]
            self.kept_dice = []
        else:
            self.dice = [random.randint(1, 6) for _ in range(len(self.dice))]
        self.pending = list(range(len(self.dice)))
        s, _u = self.score_dice(self.dice)
        if s == 0:
            self.turn_score = 0
            self.lb_dice.setText('💥 FARKLE！无计分骰，回合清零')
            QTimer.singleShot(1200, self._end_turn)
            self._sync_ui()
            return
        self._sync_ui()

    def _keep(self):
        if self.over or self.turn != 'player' or not self.dice:
            return
        s, usable = self.score_dice(self.dice)
        if s == 0:
            return
        self.turn_score += s
        self.kept_dice += list(self.dice)
        self.dice = []
        self._sync_ui()

    def _lock(self):
        if self.over or self.turn != 'player' or self.turn_score <= 0:
            return
        self.pscore += self.turn_score
        self.turn_score = 0
        self.dice = []
        if self.pscore >= self.target():
            self.over = True
            self._finish(True, f'你先到 {self.target()} 分！好感度 +3')
            return
        self.turn = 'enemy'
        self._sync_ui()
        QTimer.singleShot(900, self._enemy_turn)

    def _end_turn(self):
        if self.turn == 'player':
            self.turn_score = 0
            self.dice = []
            self.turn = 'enemy'
            self._sync_ui()
            QTimer.singleShot(900, self._enemy_turn)
        else:
            self.turn = 'player'
            self.turn_score = 0
            self.dice = []
            self._sync_ui()

    def _enemy_turn(self):
        if self.over:
            return
        self.turn_score = 0
        self.dice = []
        aggro = self.difficulty or 0
        for _round in range(12):
            self.dice = [random.randint(1, 6) for _ in range(6 if not self.dice else len(self.dice))]
            s, _u = self.score_dice(self.dice)
            if s == 0:
                self.turn_score = 0
                self.dice = []
                break
            self.turn_score += s
            self.dice = []
            # AI 决策：普通保守（≥200 锁定），高手局激进（≥350 锁定 或 剩 1 骰锁定）
            lock_at = 200 if aggro == 0 else 350
            if self.turn_score >= lock_at or len(self.dice) == 0:
                break
        self.escore += self.turn_score
        self.turn_score = 0
        if self.escore >= self.target():
            self.over = True
            self._finish(False, f'桌宠先到 {self.target()} 分…下次一定赢！（参与 +1）')
            return
        self.turn = 'player'
        self._sync_ui()

    def target(self):
        return self.combo_target.currentData() or 4000

    def _sync_ui(self):
        if self.dice:
            s, usable = self.score_dice(self.dice)
            self.lb_dice.setText(' '.join(str(d) for d in self.dice))
            self.lb_turn.setText(f'本轮可计 {s} 分' + ('（点保留）' if self.turn == 'player' else ''))
        else:
            self.lb_dice.setText('🎲')
            self.lb_turn.setText('你的回合' if self.turn == 'player' else '桌宠回合…')
        self.lb_score.setText(f'你: {self.pscore} ｜ 桌宠: {self.escore}（目标 {self.target()}）')
        self.btn_roll.setEnabled(self.turn == 'player' and not self.over)
        self.btn_keep.setEnabled(self.turn == 'player' and bool(self.dice) and not self.over)
        self.btn_lock.setEnabled(self.turn == 'player' and self.turn_score > 0 and not self.over)


# ---------- 打地鼠 ----------
class WhackAMole(BaseGame):
    """打地鼠：30 秒内点中随机冒出的地鼠"""

    def __init__(self, on_result, parent=None):
        super().__init__('🎯 打地鼠', on_result, parent)
        self.setFixedWidth(320)
        self.score = 0
        self.time_left = 30
        self.playing = False
        self._mole = None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('30 秒点地鼠，越快越多分！', alignment=Qt.AlignCenter))
        self._add_difficulty(lay, {'慢': 900, '普通': 600, '快': 350})
        self.lb = QLabel('得分 0 ｜ 剩余 30s', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb)
        grid = QGridLayout()
        self.btns = []
        for i in range(9):
            btn = QPushButton('🕳️')
            btn.setFixedSize(72, 72)
            btn.setStyleSheet(
                'QPushButton { background:#182136; color:#dce3f0; border:1px solid #3a4a66;'
                ' border-radius:10px; font-size:26px; }'
                'QPushButton:hover { background:#24314a; }')
            btn.clicked.connect(lambda checked, idx=i: self._hit(idx))
            grid.addWidget(btn, i // 3, i % 3)
            self.btns.append(btn)
        lay.addLayout(grid)
        self.btn_start = QPushButton('开始')
        self.btn_start.clicked.connect(self._start)
        lay.addWidget(self.btn_start)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._move_timer = QTimer(self)
        self._move_timer.timeout.connect(self._move_mole)

    def _start(self):
        self.score = 0
        self.time_left = 30
        self.playing = True
        self.btn_start.setEnabled(False)
        self._move_mole()
        self.timer.start(1000)
        self._move_timer.start(self.difficulty or 600)
        self._sync()

    def _move_mole(self):
        if not self.playing:
            return
        for b in self.btns:
            b.setText('🕳️')
        self._mole = random.randint(0, 8)
        self.btns[self._mole].setText('🐹')

    def _hit(self, idx):
        if not self.playing:
            return
        if idx == self._mole:
            self.score += 1
            self._move_mole()
        else:
            self.btns[idx].setText('💥')
            QTimer.singleShot(150, self._move_mole)
        self._sync()

    def _tick(self):
        self.time_left -= 1
        self._sync()
        if self.time_left <= 0:
            self._end()

    def _sync(self):
        self.lb.setText(f'得分 {self.score} ｜ 剩余 {self.time_left}s')

    def _end(self):
        self.playing = False
        self.timer.stop()
        self._move_timer.stop()
        self.btn_start.setEnabled(True)
        win = self.score >= 15
        self._finish(win, f'打了 {self.score} 只地鼠！' + (f'（好感度 +3）' if win else f'（参与 +1）'), self.score)


# ---------- 21 点 ----------
class Blackjack(BaseGame):
    """21 点：和桌宠对赌，谁更接近 21 谁赢"""

    def __init__(self, on_result, parent=None):
        super().__init__('🃏 21 点', on_result, parent)
        self.setFixedWidth(340)
        self.deck = []
        self.phand = []
        self.ehand = []
        self.over = False
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('比 21 点，谁爆谁输，接近者胜', alignment=Qt.AlignCenter))
        self._add_difficulty(lay, {'普通': 17, '高手局': 18})
        self.lb_me = QLabel('你的牌：', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb_me)
        self.lb_enemy = QLabel('桌宠的牌：', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb_enemy)
        row = QHBoxLayout()
        self.btn_hit = QPushButton('🃏 要牌')
        self.btn_hit.clicked.connect(self._hit)
        self.btn_stand = QPushButton('✋ 停牌')
        self.btn_stand.clicked.connect(self._stand)
        row.addWidget(self.btn_hit)
        row.addWidget(self.btn_stand)
        lay.addLayout(row)
        self._sync()

    def _deal(self):
        self.deck = [v for v in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10] for _ in range(4)]
        random.shuffle(self.deck)
        self.phand = [self.deck.pop(), self.deck.pop()]
        self.ehand = [self.deck.pop(), self.deck.pop()]
        self.over = False
        self.btn_hit.setEnabled(True)
        self.btn_stand.setEnabled(True)
        self._sync()
        if self._value(self.phand) == 21:
            self._settle()

    def _value(self, hand):
        v = sum(hand)
        aces = hand.count(1)
        while v <= 11 and aces:
            v += 10
            aces -= 1
        return v

    def _hit(self):
        self.phand.append(self.deck.pop())
        if self._value(self.phand) >= 21:
            self.btn_hit.setEnabled(False)
            QTimer.singleShot(600, self._settle)
        self._sync()

    def _stand(self):
        self.btn_hit.setEnabled(False)
        self.btn_stand.setEnabled(False)
        QTimer.singleShot(600, self._settle)

    def _settle(self):
        pv = self._value(self.phand)
        stop = self.difficulty or 17
        ev = self._value(self.ehand)
        while ev < stop and len(self.ehand) < 5:
            self.ehand.append(self.deck.pop())
            ev = self._value(self.ehand)
        pb = pv > 21
        eb = ev > 21
        if pb and eb:
            self._finish(False, f'都爆了！你 {pv} vs 桌宠 {ev}（平局，参与 +1）')
        elif pb:
            self._finish(False, f'你爆了 {pv}！桌宠 {ev} 赢（参与 +1）')
        elif eb:
            self._finish(True, f'桌宠爆了 {ev}！你 {pv} 赢，好感度 +3')
        elif pv > ev:
            self._finish(True, f'你 {pv} > 桌宠 {ev}，赢了！好感度 +3')
        elif pv < ev:
            self._finish(False, f'你 {pv} < 桌宠 {ev}，输了（参与 +1）')
        else:
            self._finish(False, f'平局 {pv}（参与 +1）')

    def _sync(self):
        self.lb_me.setText('你的牌：' + ' '.join(self._fmt(h) for h in self.phand) + f'（{self._value(self.phand)}）')
        shown = self.ehand[:1] + ['?'] * (len(self.ehand) - 1) if self.ehand else []
        self.lb_enemy.setText('桌宠的牌：' + ' '.join(shown))

    @staticmethod
    def _fmt(v):
        return {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}.get(v, str(v))


# ---------- 游戏注册表 ----------
GAMES = {
    '✊ 石头剪刀布': RockPaperScissors,
    '🔢 猜数字': GuessNumber,
    '⚫ 五子棋': Gomoku,
    '🔢 2048': Game2048,
    '💣 扫雷': Minesweeper,
    '🐍 贪吃蛇': Snake,
    '🃏 记忆翻牌': MemoryMatch,
    '⚫ 井字棋': TicTacToe,
    '🎲 Farkle 骰子': Farkle,
    '🎯 打地鼠': WhackAMole,
    '🃏 21 点': Blackjack,
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
