# YzY - Auto Buff（Windows）

> Power by 小新

`open-flower` 是 YzY - Auto Buff 的 Windows / Python 版本，与 macOS
版 AutoBuff 保持相同的主要功能、配置语义和界面结构。

## 主要功能

- 死花模式：BUFF 到期后离开自由市场、移动并释放 BUFF，随后返回市场。
- 活花模式：在当前地图循环释放 BUFF。
- 每个 BUFF 在最后一次按键成功按下时立即开始独立倒计时。
- 日志显示对应 BUFF 的倒计时和下次释放时间。
- 游戏窗口自动识别、自动恢复焦点。
- 小地图、玩家黄点、蓝色传送门及自由市场按钮检测。
- 手动标记传送门；标记前会确认角色当前处于市场。
- 空闲时坐椅子。
- 配置自动保存。

## 界面与默认设置

- 程序名称：`YzY - Auto Buff`
- 默认显示 3 个 BUFF 配置。
- 支持手动增加或删除 BUFF，最多 8 个。
- BUFF 1 默认：启用、按键 `1`、持续 `200` 秒。
- BUFF 2 默认：启用、按键 `2`、持续 `200` 秒。
- 死花模式默认“出市场后移动方式”为“只向右（骨龙）”。
- 活花模式提供“移动方式 / 提前释放 / 空闲时坐椅子”三列配置。
- 死花模式提供“出市场后移动方式 / 跳跃键 / 空闲时坐椅子”三列配置。
- 运行日志默认折叠显示最后一条记录，可手动展开。

Windows 配置保存在：

```text
%APPDATA%\YzY-Auto-Buff\settings.ini
```

首次启动新版时，如果程序目录存在旧 `settings.ini`，会自动读取旧配置；
后续保存到用户配置目录。旧版六个全空槽位会自动折叠为三个，实际配置过的
附加槽位会保留。

## 环境要求

- Windows 10 / 11
- Python 3.10+
- 建议使用管理员权限运行

安装依赖：

```bash
pip install -r requirements.txt
```

启动：

```bash
python main.py
```

也可以使用：

```text
start_admin.bat
```

## 使用流程

1. 启动游戏和 YzY - Auto Buff。
2. 确认顶部“管理员”和“游戏窗口”状态。
3. 选择死花模式或活花模式。
4. 配置 BUFF 按键、持续时间和模式选项。
5. 点击底部“开始运行”。

运行过程中点击脚本窗口导致游戏失去焦点时，程序会停止当前方向状态、
恢复游戏窗口焦点，再继续移动或释放技能。只有焦点正常时才会把角色不动
判定为移动停滞。

## 死花模式移动方式

- `先右再左`
- `只向左（鱼窝）`
- `只向右（骨龙）`（新安装默认）

## 传送门标记

只有检测到当前处于自由市场时，才允许进入传送门截图标记界面。

- 蓝色标记：自动检测位置。
- 红色标记：手动选择位置。
- 手动坐标会跟随设置持久化保存。

## 项目结构

```text
open-flower/
├── main.py
├── config/
├── ui/
│   ├── modern_main_window.py
│   ├── main_window.py
│   ├── virtual_keyboard.py
│   └── portal_marker_dialog.py
├── workers/
├── detection/
├── automation/
├── models/
├── utils/
├── templates/
├── resources/
└── tests/
```

`ui/main_window.py` 保留原有 Windows 工作流和调试工具；
`ui/modern_main_window.py` 提供当前现代化界面。

## 测试

```bash
PYTHONPYCACHEPREFIX=/tmp/open-flower-pycache \
python3 -m unittest discover -s tests -v

PYTHONPYCACHEPREFIX=/tmp/open-flower-pycache \
python3 -m compileall -q .
```

Windows 上还需要进行以下人工测试：

- 两种模式的真实按键释放。
- 移动中点击脚本窗口后的焦点恢复。
- 市场识别、小地图导航和传送门进入。
- 打包后的管理员权限、图标和模板资源加载。

## 打包

```bash
pyinstaller build.spec
```

输出目录：

```text
dist/YzY-Auto-Buff_v0.2.0/
```

## 注意事项

本项目仅供学习和研究。使用自动化工具可能违反游戏服务条款，请自行判断
并承担相关风险。
