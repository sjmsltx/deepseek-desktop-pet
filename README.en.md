# DeepSeek Desktop Pet 🐋⚡

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-6.x-green)
![Stars](https://img.shields.io/github/stars/sjmsltx/deepseek-desktop-pet)
![Last Commit](https://img.shields.io/github/last-commit/sjmsltx/deepseek-desktop-pet)

A Q-style desktop pet living in your computer: chats with you, helps with tasks, and proactively cares about you.

> A desktop AI companion built with PySide6 + DeepSeek API — dual characters, long-term memory, function calling, and a proactive care system.

> ⚠️ This is an independent third-party open-source project, not affiliated with DeepSeek. It only uses their public API. All character artworks are AI-generated and do not represent the official brand.

![AI Chat Demo](screenshots/demo-chat.png)

> **Note**: The UI and conversation are in Chinese by default. This project targets Chinese users, but the architecture is fully generalizable.

**[English](README.en.md) | [中文](README.md)**

## 📸 Screenshots

| AI Chat | Personality Interaction | Idle Animation |
|---------|------------------------|-----------------|
| ![AI Chat](screenshots/demo-chat.png) | ![Interaction](screenshots/demo-interaction.png) | ![Idle](screenshots/demo-idle.png) |

## ✨ Features

### 🎭 Dual Display Modes (v6.31)
- **Static Art Mode** (default): single Q-style illustration with breath/blink animations, lightweight
- **Live2D Mode**: official Mao model (Cubism 4), 30fps continuous animation — head sway / blinking / breathing / gaze tracking / click reactions. Switch anytime via right-click menu, persisted in config
- Transparent OpenGL embedded rendering; all interactions (drag, edge-dock, chat) work in both modes

### 🎭 Dual Characters
| Character | Model | Traits |
|-----------|-------|--------|
| **V4 Flash** ⚡ | `deepseek-v4-flash` | Light-blue kimono mermaid · Quick & efficient |
| **V4 Pro** 🐋 | `deepseek-v4-pro` | Dark-blue maid whale girl · Thoughtful & analytical |

Each character has its own model, conversation history, and long-term memory.

### 🤖 AI Capabilities (function calling)
- **15+ tools**: open apps / weather / reminders / lock screen / volume / process management / file search / clipboard / todo list / memory, etc.
- **Safe PowerShell execution**: dangerous operations (delete/shutdown/format) require user confirmation, with timeout and output truncation
- **Markdown rendering**: tables, code blocks, bold text in chat panel, with streaming typewriter display

### 🧠 Long-term Memory System
- `memorize` tool: AI autonomously recognizes and remembers user preferences/facts (isolated per character)
- Memory injected into system prompt, with importance + soft overwrite + forgetting mechanism
- Conversation summarization for long sessions
- Memory management UI: view / delete / clear

### 💗 Proactive Care System (Chained Wake-up + Follow-up)
- **Chained wake-up**: AI schedules its own next wake-up (clamped 10-360 min), with lightweight no-disturbance judgment (idle detection + quiet hours)
- **Follow-up visits**: mentions of important events (going to eat / exams, etc.) → AI schedules a follow-up and proactively checks in (with state awareness)
- Wake-up judgments use isolated context — never pollutes the main conversation

### 🖥️ Desktop Pet Experience
- Transparent always-on-top window, emotion-based sprite switching (`[emotion:happy]` tags), blink/breathing/hair animations
- Integrated right-click menu: characters / chat / interactions / edge-docking / actions / personality / settings / memory management
- Global hotkey `Ctrl+Alt+P` to summon chat
- System tray, auto-start on boot (Startup folder)
- Edge-docking: drag to screen edge to dock, peek/hidden dual modes
- Chat panel: auto-expanding multi-line input, draggable resizing, timestamps, chat export

## 🚀 Quick Start

```powershell
# 1. Install dependencies
python -m pip install -r requirements.txt
# (Optional) Live2D mode: python -m pip install live2d-py pyopengl

# 2. Prepare config (copy template and fill in your API key)
copy config.example.json config.json
# Edit config.json, fill in deepseek_api_key

# 3. Run
python desktop_pet.py
```

> ⚠️ **You need your own DeepSeek API key** (https://platform.deepseek.com, models `deepseek-v4-flash` / `deepseek-v4-pro`).

## ⚙️ Configuration

`config.json` (see `config.example.json`):

| Field | Description |
|-------|-------------|
| `deepseek_api_key` | DeepSeek API key (required) |
| `model_flash` / `model_pro` | Model ID for each character |
| `personality` | Personality (gentle/tsundere/sarcastic/energetic/cold, or custom) |
| `reply_style` | Reply style (short/normal/detailed) |
| `max_tokens` | Max output tokens per reply (256-64000) |
| `city` | Default weather city |
| `active_chat` | Proactive care toggle |
| `app_aliases` | Custom app quick aliases |

## 🏗️ Architecture

```
┌─────────────────────────────────────────┐
│  PySide6 GUI (transparent window/sprites/chat) │
├─────────────────────────────────────────┤
│  AI Core (DeepSeek API + function calling) │
│  · system prompt: identity/personality/memory/rules │
│  · tool loop: LLM intent JSON → program executes │
│  · 15+ tools (security checks + user confirmation) │
├─────────────────────────────────────────┤
│  Memory system (memory.json, per-character) │
│  Proactive care (chained wake-up + follow-up + state) │
│  System integration (tray/hotkey/autostart/edge/clipboard) │
└─────────────────────────────────────────┘
```

### Proactive Messaging (learning notes)
A detailed write-up of LLM statelessness, Function Calling, and the chained wake-up/follow-up design: `主动消息机制学习笔记.md` (Chinese).

## 📁 Project Structure

```
desktop-pet/
├── desktop_pet.py              # Main program (single file ~4000 lines, sectioned)
├── requirements.txt            # Dependencies (PySide6 + optional live2d)
├── pyproject.toml              # Project metadata / ruff config
├── config.example.json         # Config template
├── 启动桌宠.bat                # Windows one-click launcher
├── tests/
│   └── smoke_test.py           # Smoke tests (import/construct/core functions)
├── assets/                     # Assets
│   ├── flash/                  # V4 Flash state sprites
│   ├── pro/                    # V4 Pro state sprites
│   └── live2d/                 # Live2D model library (drop-in custom models)
├── docs/
│   └── live2d_pipeline.md      # Full Live2D character pipeline (Seedream→PS→Cubism)
├── screenshots/                # README screenshots
├── 主动消息机制学习笔记.md       # AI proactive messaging notes (Chinese)
├── CHANGELOG.md                # Version history
├── CONTRIBUTING.md             # Contribution guide (with source map)
├── SECURITY.md                 # Security policy
├── CODE_OF_CONDUCT.md          # Code of conduct
├── .github/                    # Issue / PR templates
└── README.md
```

### Source Map (where to start reading)

| To learn about | Search in `desktop_pet.py` |
|----------------|---------------------------|
| Tool-calling system | `# ===== Tools` / `def _call_` |
| AI status prediction | `# ===== AI status` |
| Memory system | `# ===== Memory` / `def _save_memory` |
| Proactive wake-up | `# ===== Proactive` / `def _chain_wake` |
| Live2D rendering | `# ===== Live2D` / `def _create_l2d` |
| Semantic app search | `# ===== Semantic` / `def _smart_find_app` |
| i18n (bilingual) | `_TEXT_ZH` / `_TEXT_EN` dicts |
| UI interactions | `def _build_menu` / `def _open_chat_panel` |

## 📦 Packaging as exe

```powershell
python -m PyInstaller --noconfirm --clean --onedir --windowed --name DeepSeekPet `
  --collect-all PySide6 --collect-all shiboken6 `
  --specpath release_build --workpath release_build\build --distpath release_build\dist `
  desktop_pet.py
```

> ⚠️ PyInstaller must be ≥ 6.21 (Python 3.14 support); delete `icu*.dll` from `_internal` after packaging (interferes with Qt6Core; the spec already excludes them).

## 🤝 Contributing / Roadmap

Want to learn from or contribute to this project? Start with [CONTRIBUTING.md](CONTRIBUTING.md) (includes a source-reading map).

- [ ] Foreground window awareness (detect what user is doing)
- [ ] More characters / Live2D skeletal animation
- [ ] Voice interaction (TTS/ASR)
- [ ] Plugin-based tool system

## 📄 License

[MIT](LICENSE)

---

**Disclaimer**: For learning and exchange purposes. Sprites are AI-generated; please comply with the terms of the generating tools.
