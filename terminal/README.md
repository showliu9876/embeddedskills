# terminal

Claude Code skill，用于嵌入式调试中的双向交互终端会话：串口终端、SSH 交互 Shell、本地 Shell、设备 CLI、AT 命令和菜单式控制台。

## 功能

- 启动后台交互会话，并通过会话名持续读写
- 支持串口、SSH、本地 Shell 三种后端
- 向会话发送文本或 Hex 数据
- 读取并清空会话输出缓冲
- 前台行模式接入会话
- 停止会话并清理 `.embeddedskills/state.json` 状态

## 环境要求

- Python 3.x
- 串口后端：`pyserial`，可用 `pip install pyserial` 安装
- SSH 后端：OpenSSH 客户端 `ssh`
- 本地后端：默认使用 `$SHELL`，未设置时回退到 `/bin/sh`

## 配置

### 环境级配置 (`config.json`)

terminal skill 的环境级配置目前为空对象：

```json
{}
```

交互终端的关键参数通常和具体会话绑定，应在 `start` 命令中显式传入，避免误连设备或误用凭据。

### 会话状态 (`.embeddedskills/state.json`)

工作区下的 `.embeddedskills/state.json` 保存当前后台会话：

```json
{
  "terminal_sessions": {
    "board": {
      "session_id": "board",
      "backend": "serial",
      "tcp_port": 23145,
      "pid": 1234,
      "log_file": ".embeddedskills/logs/terminal/board.log"
    }
  }
}
```

### 日志目录

后台进程日志保存到：

```text
.embeddedskills/logs/terminal/
```

### 参数优先级

1. **CLI 参数** (`--port`, `--baudrate`, `--host`, `--name` 等) - 最高优先级
2. **会话状态** (`.embeddedskills/state.json` 中已启动的 `terminal_sessions`)
3. **默认值** - 最低优先级

## 常用命令

命令示例均以当前 skill 目录为基准。

### 启动串口终端

```bash
python scripts/terminal_session.py start serial --port /dev/ttyUSB0 --baudrate 115200 --name board
```

### 启动 SSH 终端

`--host` 使用 `~/.ssh/config` 中的 Host 别名：

```bash
python scripts/terminal_session.py start ssh --host 1380-P904 --name devboard
```

首次连接可信设备时可追加：

```bash
--accept-new-host-key
--known-hosts-file <临时known_hosts路径>
```

### 启动本地 Shell

```bash
python scripts/terminal_session.py start local --name local-shell
```

### 发送命令

```bash
python scripts/terminal_session.py send board "help" --crlf
```

发送 Hex：

```bash
python scripts/terminal_session.py send board "01 03 00 00 00 02" --hex
```

### 读取输出

```bash
python scripts/terminal_session.py read board --timeout 1
```

### 前台行模式接入

```bash
python scripts/terminal_session.py attach board
```

### 查询与停止

```bash
python scripts/terminal_session.py list
python scripts/terminal_session.py status board
python scripts/terminal_session.py stop board
```

## 操作边界

- 只在需要保持交互状态时使用 terminal。
- 一次性远程命令、文件传输、端口转发仍优先使用 `ssh` skill。
- 串口扫描、日志记录、Hex 监控仍优先使用 `serial` skill。
- 未明确用途时，不主动发送会改变设备状态的命令。
- `attach` 是行模式，不等同于完整 TTY/raw 模式；全屏程序、vim、top、交互式密码输入应使用真实终端工具。
- 完成调试后执行 `stop`，避免后台会话占用串口、SSH 连接或本地 Shell。

## 故障排查

优先检查：

1. `python scripts/terminal_session.py list`
2. `python scripts/terminal_session.py status <会话名>`
3. `.embeddedskills/logs/terminal/<会话名>.log`
4. 串口是否被占用，波特率是否正确
5. SSH Host 别名是否能被 `ssh -G <别名>` 解析
6. 是否缺少 `pyserial` 或 OpenSSH 客户端
