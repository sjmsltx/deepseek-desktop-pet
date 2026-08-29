# -*- coding: utf-8 -*-
"""
pet_minigames.py — 桌宠小游戏（v6.30 Phase2）

注册式游戏框架：新增游戏 = 实现 QDialog 子类 + 注册一行到 GAMES。
游戏结果通过 on_result(win) 回调给主程序 → 触发好感度事件（胜 +3/+6XP，参与 +1/+2XP）。
"""
import random
import time

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
        self.pet_face = None

    def _add_pet_face(self, lay):
        """桌宠表情区：游戏窗口内显示桌宠反应（解决黑箱问题）"""
        self.pet_face = QLabel('', alignment=Qt.AlignCenter)
        self.pet_face.setStyleSheet(
            'color:#9fd0ff; font-size:13px; background:#141b2c;'
            ' border:1px solid #2c3a52; border-radius:8px; padding:6px;')
        lay.addWidget(self.pet_face)

    def _set_pet_face(self, text):
        if self.pet_face is not None:
            self.pet_face.setText(text)

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


    RULES = '石头剪刀布：石头赢剪刀，剪刀赢布，布赢石头。和桌宠猜拳比手气！'
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

    RULES = '猜数字：桌宠心里想了一个 1~100 的数字，你猜它会提示「大了/小了」，直到猜中。'
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


    RULES = '五子棋：你执黑先手，点击棋盘落子，横、竖、斜任意方向连成五子即获胜。难度决定 AI 强弱。'
    def __init__(self, on_result, parent=None):
        super().__init__('⚫ 五子棋', on_result, parent)
        self.board = [[0] * self.SIZE for _ in range(self.SIZE)]  # 0空 1人 2AI
        self.turn = 1
        self.over = False
        self._board_widget = _BoardWidget(self)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('你执黑先手，连成五子获胜', alignment=Qt.AlignCenter))
        self._add_difficulty(lay, {'简单': 0, '普通': 1, '困难': 2})
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
        d = self.difficulty or 1
        if d == 0:
            # 简单：30% 用评分防守，70% 随机
            if random.random() < 0.3:
                x, y = self._best_move()
            else:
                empties = [(x, y) for y in range(self.SIZE) for x in range(self.SIZE) if self.board[y][x] == 0]
                if not empties:
                    return
                x, y = random.choice(empties)
        else:
            x, y = self._best_move(hard=(d >= 2))
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
    def _score_pos(self, x, y, hard=False):
        off = self._line_score(x, y, 1) * (1.35 if hard else 1.0)
        return off + self._line_score(x, y, 2) * 0.9

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

    def _best_move(self, hard=False):
        best = None
        best_score = -1
        for y in range(self.SIZE):
            for x in range(self.SIZE):
                if self.board[y][x] == 0:
                    s = self._score_pos(x, y, hard)
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
    """2048：方向键移动合并，棋盘/目标多档可选"""


    RULES = '2048：用方向键移动所有方块，相同数字相撞会合并翻倍，合成目标数字（2048/4096）获胜。'
    def __init__(self, on_result, parent=None):
        super().__init__('🔢 2048', on_result, parent)
        self.setFixedSize(360, 400)
        self.board = [[0] * 4 for _ in range(4)]
        self.size = 4
        self.goal = 2048
        self.score = 0
        self._spawn()
        self._spawn()
        lay = QVBoxLayout(self)
        self.lb = QLabel('方向键移动，合并数字', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb)
        self._add_difficulty(lay, {'标准 4x4': (4, 2048), '大棋盘 5x5': (5, 2048), '极限 4x4·4096': (4, 4096)})
        self.lb_board = QLabel('', alignment=Qt.AlignCenter)
        self.lb_board.setStyleSheet('font-family:Consolas,monospace; font-size:18px;')
        lay.addWidget(self.lb_board)
        self._render()
        self.setFocusPolicy(Qt.StrongFocus)

    def _spawn(self):
        empty = [(x, y) for y in range(self.size) for x in range(self.size) if self.board[y][x] == 0]
        if empty:
            x, y = random.choice(empty)
            self.board[y][x] = 2 if random.random() < 0.9 else 4

    def _apply_difficulty(self):
        super()._apply_difficulty()
        if self.difficulty:
            self.size, self.goal = self.difficulty
            self.board = [[0] * self.size for _ in range(self.size)]
            self.score = 0
            self._spawn()
            self._spawn()
            if hasattr(self, 'lb_board'):
                self._render()

    def _render(self):
        colors = {0: '#141b2c', 2: '#2a3a55', 4: '#35507a', 8: '#3f6ca8',
                  16: '#4a8ac2', 32: '#5aa7d6', 64: '#e0527a', 128: '#e8739a',
                  256: '#f09ab5', 512: '#f5b8cc', 1024: '#ffd700', 2048: '#ff8c00', 4096: '#ff5555'}
        html = ['<table cellspacing="4" align="center">']
        for y in range(self.size):
            html.append('<tr>')
            for x in range(self.size):
                v = self.board[y][x]
                c = colors.get(v, '#e0527a')
                txt = str(v) if v else ''
                html.append(f'<td width="64" height="64" style="background:{c};border-radius:8px;'
                            f'color:{"#fff" if v >= 8 else "#dce3f0"};font-weight:bold;text-align:center;">'
                            f'{txt}</td>')
            html.append('</tr>')
        html.append('</table>')
        self.lb.setText(f'目标 {self.goal}，方向键移动')
        self.lb_board.setText(''.join(html))

    def _move(self, dx, dy):
        moved = False
        n = self.size
        if dy == 0:
            order_x = range(n - 1, -1, -1) if dx > 0 else range(n)
            for y in range(n):
                line = [self.board[y][x] for x in order_x]
                nl = self._merge(line)
                for i, x in enumerate(order_x):
                    if self.board[y][x] != nl[i]:
                        moved = True
                    self.board[y][x] = nl[i]
        else:
            order_y = range(n - 1, -1, -1) if dy > 0 else range(n)
            for x in range(n):
                line = [self.board[y][x] for y in order_y]
                nl = self._merge(line)
                for i, y in enumerate(order_y):
                    if self.board[y][x] != nl[i]:
                        moved = True
                    self.board[y][x] = nl[i]
        if moved:
            self._spawn()
            self._render()
            if max(max(r) for r in self.board) >= self.goal:
                self._finish(True, f'{self.goal} 达成！得分 {self.score}，好感度 +3', self.score)
            elif not any(0 in r for r in self.board):
                self._finish(False, f'棋盘满了，得分 {self.score}（参与 +1）', self.score)

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
        return merged + [0] * (self.size - len(merged))

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


    RULES = '扫雷：左键翻开格子，右键标记地雷。数字表示周围 8 格的地雷数，排完所有安全格获胜。踩雷即输。'
    def __init__(self, on_result, parent=None):
        super().__init__('💣 扫雷', on_result, parent)
        self.W, self.H, self.MINES = 9, 9, 10
        self.cell = 32
        self.grid = [[0] * self.W for _ in range(self.H)]  # 0-8 数字, 9=雷
        self.revealed = [[False] * self.W for _ in range(self.H)]
        self.flagged = [[False] * self.W for _ in range(self.H)]
        self.started = False
        self.over = False
        self._widget = _MineWidget(self)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('左键翻开 · 右键标雷 · 避开地雷', alignment=Qt.AlignCenter))
        self._add_difficulty(lay, {'初级 9x9': (9, 9, 10), '中级 16x16': (16, 16, 40), '高级 30x16': (30, 16, 99)})
        lay.addWidget(self._widget)
        self._widget.clicked.connect(self._on_click)

    def _apply_difficulty(self):
        super()._apply_difficulty()
        if self._combo is not None:
            w, h, mines = self.difficulty
            self.W, self.H, self.MINES = w, h, mines
            self.cell = max(14, min(32, 320 // w))
            self.grid = [[0] * w for _ in range(h)]
            self.revealed = [[False] * w for _ in range(h)]
            self.flagged = [[False] * w for _ in range(h)]
            self.started = False
            self.over = False
            self._widget.update()
            self._widget.setFixedSize(w * self.cell, h * self.cell)

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
        self.setFixedSize(game.W * game.cell, game.H * game.cell)

    def paintEvent(self, event):
        g = self.game
        p = QPainter(self)
        cell = g.cell
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
        cell = g.cell
        x = int(event.position().x() // cell)
        y = int(event.position().y() // cell)
        if 0 <= x < g.W and 0 <= y < g.H:
            self.clicked.emit(x, y, event.button() == Qt.RightButton)


# ---------- 贪吃蛇 ----------
class Snake(BaseGame):
    """贪吃蛇：方向键控制，吃食物变长"""

    SIZE = 20
    CELL = 15


    RULES = '贪吃蛇：方向键控制蛇移动，吃到食物变长得分。撞墙或撞到自己结束。金色食物 5 秒内吃到 +3 分！'
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
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('方向键控制，吃到食物变长', alignment=Qt.AlignCenter))
        self._add_difficulty(lay, {'慢': 180, '普通': 130, '快': 90})
        lay.addWidget(self._widget)
        self.lb = QLabel('得分 0', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb)
        self.timer.start(self.difficulty or 130)
        self.setFocusPolicy(Qt.StrongFocus)

    def _spawn_food(self):
        # (x, y, is_gold, expire_ts)；20% 概率金苹果（5 秒消失，+3 分）
        gold = random.random() < 0.2
        expire = time.time() + 5 if gold else 0
        while True:
            f = (random.randint(0, self.SIZE - 1), random.randint(0, self.SIZE - 1))
            if f not in self.snake:
                return (f[0], f[1], gold, expire)

    def _step(self):
        if self.over:
            return
        import time as _t
        # 金苹果过期消失
        if self.food[2] and _t.time() > self.food[3]:
            self.food = self._spawn_food()
        head = (self.snake[0][0] + self.dir[0], self.snake[0][1] + self.dir[1])
        if head in self.snake or not (0 <= head[0] < self.SIZE and 0 <= head[1] < self.SIZE):
            self.over = True
            self.timer.stop()
            self._finish(False, f'撞到了！得分 {self.score}（参与 +1）', self.score)
            return
        self.snake.insert(0, head)
        if head == (self.food[0], self.food[1]):
            self.score += 3 if self.food[2] else 1
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


    RULES = '记忆翻牌：翻开两张卡片，图案相同则配对成功。全部 8 对配对完成获胜，用的次数越少越厉害。'
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


    RULES = '井字棋：你执 X 先手，在 3×3 棋盘落子，横竖斜连成一线获胜。难度决定 AI 聪明程度。'
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
    """Farkle：目标分自选，和桌宠轮流掷 6 骰；点击骰子选中保留，先到目标分获胜"""

    TARGETS = [('500', 500), ('1000', 1000), ('1500', 1500), ('2000', 2000),
               ('3000', 3000), ('4000', 4000), ('8000', 8000), ('10000', 10000)]


    RULES = 'KCD 版 Farkle 骰子：先到目标分（500~10000 自选）获胜。\\n计分：单 1=100，单 5=50；三个 1=1000，三个 2~6=点数×100；四个同=×2，五个同=×4，六个同=×8；顺子 123456=1500，12345=500，23456=750。\\n流程：掷骰→点击选中计分骰→保留（得分入回合）→继续掷剩余骰或锁定。全部保留后奖励 6 个新骰。掷出无分骰=Farkle，回合清零。策略：贪心有风险，见好就收！'
    def __init__(self, on_result, parent=None):
        super().__init__('🎲 Farkle 骰子', on_result, parent)
        self.setFixedWidth(400)
        self.pscore = 0
        self.escore = 0
        self.turn = 'player'
        self.turn_score = 0
        self.hand = []          # 手中骰子（可继续掷）
        self.selected = set()   # 选中的骰子索引
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
        self._add_pet_face(lay)
        grid = QGridLayout()
        self.dice_btns = []
        for i in range(6):
            btn = QPushButton('·')
            btn.setFixedSize(52, 52)
            btn.setCheckable(True)
            btn.setStyleSheet(
                'QPushButton { background:#141b2c; color:#dce3f0; border:1px solid #3a4a66;'
                ' border-radius:8px; font-size:20px; }'
                'QPushButton:checked { background:#35507a; border:2px solid #ffd700; color:#fff; }'
                'QPushButton:disabled { color:#445; }')
            btn.clicked.connect(lambda checked, idx=i: self._toggle(idx))
            grid.addWidget(btn, i // 3, i % 3)
            self.dice_btns.append(btn)
        lay.addLayout(grid)
        self.lb_turn = QLabel('点击「掷骰子」开始', alignment=Qt.AlignCenter)
        self.lb_turn.setWordWrap(True)
        lay.addWidget(self.lb_turn)
        self.lb_score = QLabel('你: 0 ｜ 桌宠: 0', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb_score)
        row = QHBoxLayout()
        self.btn_roll = QPushButton('🎲 掷骰子')
        self.btn_roll.clicked.connect(self._roll)
        self.btn_keep = QPushButton('✅ 保留选中')
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
        """KCD 官方计分：单1=100 单5=50；三同=值×100(三个1=1000)；四五六同=×2/×4/×8；
        顺子 123456=1500, 12345=500, 23456=750；无三个对子/双三同组合奖励"""
        from collections import Counter
        n = len(dice)
        s = sorted(dice)
        if n == 6 and s == [1, 2, 3, 4, 5, 6]:
            return 1500, set(range(6))
        if n == 5 and s == [1, 2, 3, 4, 5]:
            return 500, set(range(5))
        if n == 5 and s == [2, 3, 4, 5, 6]:
            return 750, set(range(5))
        counts = Counter(dice)
        score = 0
        usable = set()
        for v, c in counts.items():
            if c >= 3:
                base = 1000 if v == 1 else (500 if v == 5 else v * 100)
                mult = 2 ** (c - 3)
                score += base * mult
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

    # ---------- 玩家操作 ----------
    def _toggle(self, idx):
        if self.over or self.turn != 'player' or idx >= len(self.hand):
            return
        if idx in self.selected:
            self.selected.discard(idx)
        else:
            self.selected.add(idx)
        self._sync_ui()

    def _roll(self):
        if self.over or self.turn != 'player':
            return
        n = 6 if not self.hand else len(self.hand)
        self.hand = [random.randint(1, 6) for _ in range(n)]
        self.selected = set()
        # 骰子滚动动画：先显示 🎲，300ms 后揭示点数
        for btn in self.dice_btns:
            btn.setText('🎲')
            btn.setEnabled(True)
            btn.setChecked(False)
        self._set_pet_face('🎲 掷骰子…' + (' 😏 还敢继续？' if self.turn_score > 0 else ' 🙂'))
        self.btn_roll.setEnabled(False)
        self.btn_keep.setEnabled(False)
        self.btn_lock.setEnabled(False)
        QTimer.singleShot(300, self._reveal_dice)

    def _reveal_dice(self):
        if self.over:
            return
        s, _u = self.score_dice(self.hand)
        if s == 0:
            self.lb_turn.setText('💥 FARKLE！本回合清零')
            self._set_pet_face('😄 桌宠：Farkle！你白掷啦～')
            self.turn_score = 0
            self.hand = []
            self.selected = set()
            self._sync_ui()
            QTimer.singleShot(1500, self._pass_turn)
            return
        self._set_pet_face('😏 桌宠盯着你的骰子…')
        self._sync_ui()

    def _keep(self):
        if self.over or self.turn != 'player' or not self.hand or not self.selected:
            return
        sel_vals = [self.hand[i] for i in sorted(self.selected)]
        s, _u = self.score_dice(sel_vals)
        if s == 0:
            self.lb_turn.setText('选中的骰子没有分哦，点计分骰（1/5/三同）')
            return
        self.turn_score += s
        self.hand = [v for i, v in enumerate(self.hand) if i not in self.selected]
        self.selected = set()
        if not self.hand:
            self.lb_turn.setText(f'全保留了！本回合 {self.turn_score} 分，可继续掷新骰或锁定')
        self._set_pet_face(f'🤔 桌宠：你留下了 {s} 分…')
        self._sync_ui()

    def _lock(self):
        if self.over or self.turn != 'player' or self.turn_score <= 0:
            return
        self.pscore += self.turn_score
        self.turn_score = 0
        self.hand = []
        self.selected = set()
        if self.pscore >= self.target():
            self.over = True
            self._set_pet_face('😭 桌宠：你赢了…')
            self._finish(True, f'你先到 {self.target()} 分！好感度 +3')
            return
        self._set_pet_face('😮 桌宠：锁定了？轮到我了！')
        self.turn = 'enemy'
        self._sync_ui()
        QTimer.singleShot(900, self._enemy_turn)

    def _pass_turn(self):
        self.turn = 'enemy'
        self._sync_ui()
        QTimer.singleShot(900, self._enemy_turn)

    # ---------- 桌宠 AI ----------
    def _enemy_turn(self):
        if self.over:
            return
        self.turn_score = 0
        self.hand = []
        aggro = self.difficulty or 0
        for _round in range(12):
            n = 6 if not self.hand else len(self.hand)
            self.hand = [random.randint(1, 6) for _ in range(n)]
            s, _u = self.score_dice(self.hand)
            if s == 0:
                self.turn_score = 0
                self.hand = []
                self._set_pet_face('😭 桌宠：呜…我 Farkle 了')
                break
            self.turn_score += s
            self.hand = []   # AI 全保留
            lock_at = 200 if aggro == 0 else 350
            if self.turn_score >= lock_at:
                self._set_pet_face(f'🤗 桌宠：{self.turn_score} 分到手！')
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
        for i, btn in enumerate(self.dice_btns):
            if i < len(self.hand):
                btn.setText(str(self.hand[i]))
                btn.setEnabled(True)
                btn.setChecked(i in self.selected)
            else:
                btn.setText('·')
                btn.setEnabled(False)
                btn.setChecked(False)
        if self.hand:
            s, _u = self.score_dice(self.hand)
            hint = f'本回合 {self.turn_score} 分 ｜ 当前可计 {s} 分，点击骰子选中'
        else:
            hint = f'本回合 {self.turn_score} 分'
        who = '你的回合' if self.turn == 'player' else '桌宠回合…'
        self.lb_turn.setText(f'{hint}（{who}）')
        self.lb_score.setText(f'你: {self.pscore} ｜ 桌宠: {self.escore}（目标 {self.target()}）')
        self.btn_roll.setEnabled(self.turn == 'player' and not self.over)
        self.btn_keep.setEnabled(self.turn == 'player' and bool(self.selected) and not self.over)
        self.btn_lock.setEnabled(self.turn == 'player' and self.turn_score > 0 and not self.over)


# ---------- 打地鼠 ----------
class WhackAMole(BaseGame):
    """打地鼠：30 秒内点中随机冒出的地鼠"""


    RULES = '打地鼠：30 秒内点中随机冒出的地鼠，点中 +1 分。速度越快的地鼠越难抓，15 分以上算胜利。'
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


    RULES = '21 点：和桌宠比谁更接近 21。A 可算 1 或 11，J/Q/K 算 10。要牌接近 21，超过 21 爆牌即输，停牌后桌宠补牌比大小。'
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
        self._add_pet_face(lay)
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
        self._deal()

    def _deal(self):
        self.deck = [v for v in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10] for _ in range(4)]
        random.shuffle(self.deck)
        self.phand = [self.deck.pop(), self.deck.pop()]
        self.ehand = [self.deck.pop(), self.deck.pop()]
        self.over = False
        self.btn_hit.setEnabled(True)
        self.btn_stand.setEnabled(True)
        self._set_pet_face('🃏 桌宠：发牌！谁更接近 21？')
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
        self._set_pet_face('😏 桌宠：还敢要？小心爆牌哦')
        self.btn_hit.setEnabled(False)
        QTimer.singleShot(250, self._do_hit)

    def _do_hit(self):
        self.phand.append(self.deck.pop())
        self._sync()
        if self._value(self.phand) >= 21:
            self.btn_hit.setEnabled(False)
            QTimer.singleShot(600, self._settle)
        else:
            self.btn_hit.setEnabled(True)

    def _stand(self):
        self.btn_hit.setEnabled(False)
        self.btn_stand.setEnabled(False)
        self._set_pet_face('🤔 桌宠：看我的！')
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
            self._set_pet_face('😐 桌宠：都爆了…平局')
            self._finish(False, f'都爆了！你 {pv} vs 桌宠 {ev}（平局，参与 +1）')
        elif pb:
            self._set_pet_face('😄 桌宠：你爆啦！')
            self._finish(False, f'你爆了 {pv}！桌宠 {ev} 赢（参与 +1）')
        elif eb:
            self._set_pet_face('😭 桌宠：呜…我爆了')
            self._finish(True, f'桌宠爆了 {ev}！你 {pv} 赢，好感度 +3')
        elif pv > ev:
            self._set_pet_face('😭 桌宠：你赢了…')
            self._finish(True, f'你 {pv} > 桌宠 {ev}，赢了！好感度 +3')
        elif pv < ev:
            self._set_pet_face('😄 桌宠：我赢啦！')
            self._finish(False, f'你 {pv} < 桌宠 {ev}，输了（参与 +1）')
        else:
            self._set_pet_face('😐 桌宠：平局')
            self._finish(False, f'平局 {pv}（参与 +1）')

    def _sync(self):
        self.lb_me.setText('你的牌：' + ' '.join(self._fmt(h) for h in self.phand) + f'（{self._value(self.phand)}）')
        shown = [self._fmt(h) for h in self.ehand[:1]] + ['?'] * (len(self.ehand) - 1) if self.ehand else []
        self.lb_enemy.setText('桌宠的牌：' + ' '.join(shown))

    @staticmethod
    def _fmt(v):
        return {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}.get(v, str(v))


# ---------- 数独 ----------
class Sudoku(BaseGame):
    """数独：9×9，挖空 24/36/48 格三档难度"""


    RULES = '数独：在 9×9 棋盘填入 1~9，保证每行、每列、每个 3×3 宫格内数字不重复。已给出的数字不可改，填完点「检查」。'
    def __init__(self, on_result, parent=None):
        super().__init__('🔢 数独', on_result, parent)
        self.setFixedWidth(420)
        self.solution = None
        self.puzzle = None
        self.cells = []
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('填入 1-9，行列宫不重复', alignment=Qt.AlignCenter))
        self._add_difficulty(lay, {'简单': 24, '普通': 36, '困难': 48})
        grid = QGridLayout()
        self.edits = {}
        for r in range(9):
            for c in range(9):
                ed = QLineEdit()
                ed.setMaxLength(1)
                ed.setFixedSize(38, 38)
                ed.setAlignment(Qt.AlignCenter)
                ed.setStyleSheet(
                    'QLineEdit { background:#141b2c; color:#dce3f0; border:1px solid #2c3a52;'
                    ' border-radius:4px; font-size:16px; }'
                    'QLineEdit[given="true"] { background:#1c2740; color:#7fb2ff; font-weight:bold; }')
                grid.addWidget(ed, r, c)
                self.edits[(r, c)] = ed
                self.cells.append(ed)
        lay.addLayout(grid)
        self.lb = QLabel('', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb)
        row = QHBoxLayout()
        btn_new = QPushButton('🔄 新一局')
        btn_new.clicked.connect(self._new_game)
        btn_check = QPushButton('✅ 检查')
        btn_check.clicked.connect(self._check)
        row.addWidget(btn_new)
        row.addWidget(btn_check)
        lay.addLayout(row)
        self._new_game()

    # ---------- 生成 ----------
    def _new_game(self):
        self.solution = self._gen_solution()
        holes = self.difficulty or 36
        self.puzzle = [row[:] for row in self.solution]
        cells = [(r, c) for r in range(9) for c in range(9)]
        random.shuffle(cells)
        for r, c in cells[:holes]:
            self.puzzle[r][c] = 0
        for (r, c), ed in self.edits.items():
            v = self.puzzle[r][c]
            ed.setText(str(v) if v else '')
            ed.setProperty('given', 'true' if v else 'false')
            ed.setReadOnly(bool(v))
            ed.setStyleSheet(ed.styleSheet())  # 刷新属性样式
        self.lb.setText(f'填 {holes} 个空格，开始吧')

    def _gen_solution(self):
        board = [[0] * 9 for _ in range(9)]
        self._fill(board)
        return board

    def _fill(self, board):
        for r in range(9):
            for c in range(9):
                if board[r][c] == 0:
                    nums = list(range(1, 10))
                    random.shuffle(nums)
                    for n in nums:
                        if self._ok(board, r, c, n):
                            board[r][c] = n
                            if self._fill(board):
                                return True
                            board[r][c] = 0
                    return False
        return True

    @staticmethod
    def _ok(board, r, c, n):
        for i in range(9):
            if board[r][i] == n or board[i][c] == n:
                return False
        br, bc = r // 3 * 3, c // 3 * 3
        for i in range(3):
            for j in range(3):
                if board[br + i][bc + j] == n:
                    return False
        return True

    # ---------- 检查 ----------
    def _check(self):
        for (r, c), ed in self.edits.items():
            t = ed.text().strip()
            if not t.isdigit() or not (1 <= int(t) <= 9):
                self.lb.setText('还有空格或输入不对哦')
                return
            if int(t) != self.solution[r][c]:
                self.lb.setText(f'第 {r + 1} 行第 {c + 1} 列错了')
                return
        self._finish(True, '数独完成！好感度 +3')


# ---------- 俄罗斯方块 ----------
class Tetris(BaseGame):
    """俄罗斯方块：方向键移动/旋转，消行得分，速度三档"""

    SHAPES = [
        [[1, 1, 1, 1]],
        [[1, 1], [1, 1]],
        [[0, 1, 0], [1, 1, 1]],
        [[0, 1, 1], [1, 1, 0]],
        [[1, 1, 0], [0, 1, 1]],
        [[1, 0, 0], [1, 1, 1]],
        [[0, 0, 1], [1, 1, 1]],
    ]
    COLORS = ['#00e5ff', '#ffd700', '#c9a0ff', '#6ecb7a', '#ff8a8a', '#ffa040', '#4a8ac2']
    W, H = 10, 20


    RULES = '俄罗斯方块：←→左右移动，↑旋转，↓加速下落，空格直接落底。方块堆满一行自动消除，一次消多行得分更高。堆到顶部游戏结束。'
    def __init__(self, on_result, parent=None):
        super().__init__('🧱 俄罗斯方块', on_result, parent)
        self.setFixedSize(320, 440)
        self.board = [[0] * self.W for _ in range(self.H)]
        self.score = 0
        self.lines = 0
        self.over = False
        self._widget = _TetrisWidget(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('←→移动 ↑旋转 ↓加速 空格硬降', alignment=Qt.AlignCenter))
        self._add_difficulty(lay, {'慢': 500, '普通': 350, '快': 220})
        lay.addWidget(self._widget)
        self.lb = QLabel('得分 0 ｜ 行 0', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb)
        self.timer.start(self.difficulty or 350)
        self._spawn()
        self.setFocusPolicy(Qt.StrongFocus)

    def _spawn(self):
        i = random.randint(0, 6)
        self.piece = [row[:] for row in self.SHAPES[i]]
        self.px = self.W // 2 - len(self.piece[0]) // 2
        self.py = 0
        self.pcolor = self.COLORS[i]
        if self._collide(self.px, self.py):
            self.over = True
            self.timer.stop()
            self._finish(False, f'游戏结束！得分 {self.score}（参与 +1）', self.score)

    def _collide(self, x, y):
        for r, row in enumerate(self.piece):
            for c, v in enumerate(row):
                if v and (y + r >= self.H or x + c < 0 or x + c >= self.W or self.board[y + r][x + c]):
                    return True
        return False

    def _lock(self):
        for r, row in enumerate(self.piece):
            for c, v in enumerate(row):
                if v:
                    self.board[self.py + r][self.px + c] = 1
        full = [r for r in range(self.H) if all(self.board[r])]
        for r in full:
            del self.board[r]
            self.board.insert(0, [0] * self.W)
        if full:
            self.lines += len(full)
            self.score += [0, 100, 300, 500, 800][min(len(full), 4)]
            self.lb.setText(f'得分 {self.score} ｜ 行 {self.lines}')
        self._spawn()
        self._widget.update()

    def _tick(self):
        if self.over:
            return
        if not self._collide(self.px, self.py + 1):
            self.py += 1
        else:
            self._lock()
        self._widget.update()

    def _rotate(self):
        piece = [list(row) for row in zip(*self.piece[::-1])]
        old = self.piece
        self.piece = piece
        if self._collide(self.px, self.py):
            self.piece = old

    def keyPressEvent(self, e):
        if self.over:
            return
        k = e.key()
        if k == Qt.Key_Left and not self._collide(self.px - 1, self.py):
            self.px -= 1
        elif k == Qt.Key_Right and not self._collide(self.px + 1, self.py):
            self.px += 1
        elif k == Qt.Key_Down and not self._collide(self.px, self.py + 1):
            self.py += 1
        elif k == Qt.Key_Up:
            self._rotate()
        elif k == Qt.Key_Space:
            while not self._collide(self.px, self.py + 1):
                self.py += 1
            self._lock()
        self._widget.update()


class _TetrisWidget(QWidget):
    def __init__(self, game, parent=None):
        super().__init__(parent)
        self.game = game
        cell = 18
        self.setFixedSize(game.W * cell + 4, game.H * cell + 4)
        self.cell = cell

    def paintEvent(self, event):
        g = self.game
        p = QPainter(self)
        cell = self.cell
        p.fillRect(self.rect(), QColor('#0d1320'))
        p.setPen(QPen(QColor('#1c2740')))
        for y in range(g.H):
            for x in range(g.W):
                p.drawRect(x * cell, y * cell, cell, cell)
                if g.board[y][x]:
                    p.fillRect(x * cell + 1, y * cell + 1, cell - 2, cell - 2, QColor('#5aa7d6'))
        # 当前方块
        if not g.over and hasattr(g, 'piece'):
            for r, row in enumerate(g.piece):
                for c, v in enumerate(row):
                    if v:
                        p.fillRect((g.px + c) * cell + 1, (g.py + r) * cell + 1, cell - 2, cell - 2,
                                   QColor(g.pcolor))


# ---------- 华容道（数字滑块） ----------
class SlidingPuzzle(BaseGame):
    """华容道：数字滑块拼图，点击相邻块移动，按步数计成绩"""


    RULES = '华容道：点击数字方块滑到旁边的空格里，目标是把数字按 1~15 顺序排好（空格在右下角）。步数越少越厉害。'
    def __init__(self, on_result, parent=None):
        super().__init__('🧩 华容道', on_result, parent)
        self.setFixedWidth(340)
        self.steps = 0
        self.over = False
        self.buttons = []
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('点击数字移动到空格，按顺序排好获胜', alignment=Qt.AlignCenter))
        self._add_difficulty(lay, {'3×3': 3, '4×4': 4})
        self.lb = QLabel('步数 0', alignment=Qt.AlignCenter)
        lay.addWidget(self.lb)
        self.grid = QGridLayout()
        lay.addLayout(self.grid)
        btn = QPushButton('🔄 重新打乱')
        btn.clicked.connect(self._new_game)
        lay.addWidget(btn)
        self._new_game()

    def _apply_difficulty(self):
        super()._apply_difficulty()
        if hasattr(self, 'lb'):
            self._new_game()

    def _new_game(self):
        n = self.difficulty or 3
        self.n = n
        total = n * n
        # 从完成态随机移动 200 次保证可解
        board = list(range(1, total)) + [0]
        empty = total - 1
        for _ in range(200):
            candidates = []
            if empty // n > 0: candidates.append(empty - n)
            if empty // n < n - 1: candidates.append(empty + n)
            if empty % n > 0: candidates.append(empty - 1)
            if empty % n < n - 1: candidates.append(empty + 1)
            idx = random.choice(candidates)
            board[idx], board[empty] = board[empty], board[idx]
            empty = idx
        self.board = board
        self.steps = 0
        self.over = False
        self.lb.setText('步数 0')
        # 重建网格按钮
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.buttons = []
        for i in range(total):
            btn = QPushButton()
            btn.setFixedSize(64, 64)
            btn.setStyleSheet(
                'QPushButton { background:#2a3a55; color:#dce3f0; border-radius:8px;'
                ' font-size:20px; font-weight:bold; }'
                'QPushButton:hover { background:#35507a; }'
                'QPushButton:disabled { background:#182136; color:#445; }')
            btn.clicked.connect(lambda checked, idx=i: self._move(idx))
            self.grid.addWidget(btn, i // n, i % n)
            self.buttons.append(btn)
        self._render()

    def _render(self):
        for i, btn in enumerate(self.buttons):
            v = self.board[i]
            btn.setText(str(v) if v else '')
            btn.setEnabled(v != 0)

    def _move(self, idx):
        if self.over:
            return
        empty = self.board.index(0)
        same_row = idx // self.n == empty // self.n
        if (abs(idx - empty) == 1 and same_row) or abs(idx - empty) == self.n:
            self.board[idx], self.board[empty] = self.board[empty], self.board[idx]
            self.steps += 1
            self.lb.setText(f'步数 {self.steps}')
            self._render()
            if self.board == list(range(1, self.n * self.n)) + [0]:
                self.over = True
                self._finish(True, f'完成！用了 {self.steps} 步，好感度 +3', self.steps)


# ---------- 西蒙记忆 ----------
class SimonSays(BaseGame):
    """西蒙记忆：记颜色序列，逐步加长，4键/6键"""

    COLORS = [('#e0527a', '红'), ('#6ecb7a', '绿'), ('#4a8ac2', '蓝'), ('#ffd700', '黄'),
              ('#c9a0ff', '紫'), ('#00e5ff', '青')]


    RULES = '西蒙记忆：桌宠会点亮一串颜色（红/绿/蓝/黄…），你要按顺序点击复述。每过一关序列加长一个，记住 8 个以上算记忆超神！'
    def __init__(self, on_result, parent=None):
        super().__init__('🎵 西蒙记忆', on_result, parent)
        self.setFixedWidth(340)
        self.seq = []
        self.replay_idx = 0
        self.playing = False
        self.accept_input = False
        self.over = False
        lay = QVBoxLayout(self)
        self._add_difficulty(lay, {'4 键': 4, '6 键': 6})
        self.lb = QLabel('看桌宠点亮颜色，然后按顺序复述！', alignment=Qt.AlignCenter)
        self.lb.setWordWrap(True)
        lay.addWidget(self.lb)
        grid = QGridLayout()
        self.btns = []
        for i in range(6):
            color, name = self.COLORS[i]
            btn = QPushButton('')
            btn.setFixedSize(90, 90)
            btn.setStyleSheet(f'QPushButton {{ background:{color}; border-radius:12px; }}'
                              f'QPushButton:disabled {{ background:#2a3a55; }}')
            btn.clicked.connect(lambda checked, idx=i: self._press(idx))
            grid.addWidget(btn, i // 3, i % 3)
            self.btns.append(btn)
        lay.addLayout(grid)
        self.btn_start = QPushButton('▶ 开始')
        self.btn_start.clicked.connect(self._start)
        lay.addWidget(self.btn_start)
        self._set_pet_face('🎵 桌宠：跟紧我的节奏！')

    def _apply_difficulty(self):
        super()._apply_difficulty()
        if hasattr(self, 'btns'):
            n = self.difficulty or 4
            for i, btn in enumerate(self.btns):
                btn.setVisible(i < n)

    def _start(self):
        self.seq = []
        self.playing = True
        self.accept_input = False
        self.btn_start.setEnabled(False)
        self._next_round()

    def _next_round(self):
        self.seq.append(random.randint(0, (self.difficulty or 4) - 1))
        self.lb.setText(f'第 {len(self.seq)} 轮，看仔细了！')
        self.replay_idx = 0
        self.accept_input = False
        QTimer.singleShot(600, self._play_next)

    def _play_next(self):
        if self.over:
            return
        if self.replay_idx >= len(self.seq):
            self.accept_input = True
            self.lb.setText(f'轮到你！第 {len(self.seq)} 轮，共 {len(self.seq)} 下')
            return
        idx = self.seq[self.replay_idx]
        self._flash(idx)
        self.replay_idx += 1
        QTimer.singleShot(650, self._play_next)

    def _flash(self, idx):
        btn = self.btns[idx]
        btn.setStyleSheet(f'QPushButton {{ background:#ffffff; border-radius:12px; }}')
        QTimer.singleShot(250, lambda: btn.setStyleSheet(
            f'QPushButton {{ background:{self.COLORS[idx][0]}; border-radius:12px; }}'))

    def _press(self, idx):
        if not self.accept_input or self.over:
            return
        self._flash(idx)
        self._check_input(idx)

    def _check_input(self, idx):
        pos = len(self.seq) - (self.replay_idx - 0)
        # 简化：用 self._input_pos 追踪
        if not hasattr(self, '_input_pos'):
            self._input_pos = 0
        if idx == self.seq[self._input_pos]:
            self._input_pos += 1
            if self._input_pos >= len(self.seq):
                self._input_pos = 0
                self.accept_input = False
                if len(self.seq) >= 8:
                    self.over = True
                    self._finish(True, f'记忆超人！记住 {len(self.seq)} 下，好感度 +3', len(self.seq))
                else:
                    self.lb.setText('漂亮！继续～')
                    QTimer.singleShot(700, self._next_round)
        else:
            self.over = True
            self.accept_input = False
            self._finish(False, f'记错了…坚持了 {len(self.seq)} 下（参与 +1）', len(self.seq))


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
    '🔢 数独': Sudoku,
    '🧱 俄罗斯方块': Tetris,
    '🧩 华容道': SlidingPuzzle,
    '🎵 西蒙记忆': SimonSays,
}


class GameWindow(QDialog):
    """小游戏选择窗口"""

    def __init__(self, on_result, parent=None):
        super().__init__(parent)
        self.on_result = on_result
        self.setWindowTitle('🎮 小游戏')
        self.setFixedWidth(300)
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
            row = QHBoxLayout()
            btn = QPushButton(f'▶ {name}')
            btn.clicked.connect(lambda checked, c=cls: self._open(c))
            row.addWidget(btn)
            rules = getattr(cls, 'RULES', '')
            if rules:
                rbtn = QPushButton('📖 规则')
                rbtn.setFixedWidth(56)
                rbtn.setStyleSheet('font-size:12px; padding:6px;')
                rbtn.clicked.connect(lambda checked, c=cls, r=rules: QMessageBox.information(self, f'{c.__name__} 规则', r))
                row.addWidget(rbtn)
            row.addStretch(1)
            lay.addLayout(row)

    def _open(self, cls):
        self.hide()
        g = cls(self.on_result, self.parent())
        g.exec()
        self.close()
