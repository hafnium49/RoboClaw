# RoboClaw Embodied First-Run Checklist

这份文档是给第一次使用 RoboClaw 的用户的实际验证流程。

目标不是一次性验证所有机器人能力，而是系统性检查这次 PR 引入的整条链路是否正常：

- RoboClaw 能否完成首次初始化
- RoboClaw 能否生成具身 workspace
- RoboClaw 能否通过对话收集 setup 信息
- RoboClaw 能否把 setup-specific 资产写到 `~/.roboclaw/workspace/embodied/`
- RoboClaw 能否保持 framework 源码不被污染
- 如果你已经有真实本体或仿真环境，RoboClaw 能否继续进入 `connect / calibrate / move / debug / reset`

## 1. What This PR Should Make Work

在开始之前，先明确这次验证到底在验什么。

这次 PR 的重点不是“已经内置支持了所有机器人”，而是：

1. RoboClaw 首次安装和初始化链路要能工作。
2. RoboClaw 要能创建一套专门给具身接入使用的 workspace scaffold。
3. RoboClaw 要遵守 workspace-first 规则：
   - framework 协议层在仓库里
   - 用户具体 setup 写到 `~/.roboclaw/workspace/embodied/`
   - 不直接改 framework 源码
4. RoboClaw 要能通过自然语言引导用户整理 setup 信息，进入后续本体验证流程。

如果上面 4 点不成立，这个 PR 就不算真的 work。

## 2. Prerequisites

假设你是从零开始：

```bash
git clone https://github.com/MINT-SJTU/RoboClaw.git
cd RoboClaw
```

开始之前确认：

- 你有一个可用的 Python 环境
- 你能在当前 shell 里执行 `pip`
- 如果你要验证真实本体，ROS2、本体驱动和设备连接已经单独准备好

## 3. Step 1: Install RoboClaw

执行：

```bash
pip install -e ".[dev]"
```

你要验证：

- 安装过程没有报错
- 安装完成后 `roboclaw` 命令可用

可以直接检查：

```bash
roboclaw --help
```

预期结果：

- 能看到 `onboard`、`status`、`agent`、`provider` 等命令

如果这一步失败，问题还在 Python 环境或依赖安装，先不要进入后面的具身验证。

## 4. Step 2: Initialize RoboClaw

执行：

```bash
roboclaw onboard
```

这一步是第一次启动的关键检查点。

你要验证：

- RoboClaw 成功创建 `~/.roboclaw/config.json`
- RoboClaw 成功创建 `~/.roboclaw/workspace/`
- RoboClaw 成功创建具身相关 scaffold，而不是只生成通用文件

建议直接检查：

```bash
find ~/.roboclaw -maxdepth 3 -type f | sort
```

至少应该看到这些文件：

```text
~/.roboclaw/config.json
~/.roboclaw/workspace/AGENTS.md
~/.roboclaw/workspace/EMBODIED.md
~/.roboclaw/workspace/HEARTBEAT.md
~/.roboclaw/workspace/SOUL.md
~/.roboclaw/workspace/TOOLS.md
~/.roboclaw/workspace/USER.md
~/.roboclaw/workspace/memory/HISTORY.md
~/.roboclaw/workspace/memory/MEMORY.md
~/.roboclaw/workspace/embodied/README.md
~/.roboclaw/workspace/embodied/intake/README.md
~/.roboclaw/workspace/embodied/robots/README.md
~/.roboclaw/workspace/embodied/sensors/README.md
```

如果这一步失败，这个 PR 最基础的 onboarding 能力就是不成立的。

## 5. Step 3: Verify Status Output

执行：

```bash
roboclaw status
```

你要验证：

- `Config` 显示为 `✓`
- `Workspace` 显示为 `✓`
- 当前 `Model` 显示正常
- provider 状态和你机器上的真实情况一致

如果 `status` 都不正常，就说明初始化后的运行时状态还不稳定。

## 6. Step 4: Make Sure the Model Path Works

执行最小消息：

```bash
roboclaw agent -m "hello"
```

如果你还没有配置模型提供方，这一步可能失败。这是正常的，但错误必须可理解。

如果需要 OAuth 登录，可以执行：

```bash
roboclaw provider login openai-codex
```

或者根据你的环境，直接编辑：

```bash
~/.roboclaw/config.json
```

你要验证：

- agent 能启动
- 如果失败，错误能明确指向模型配置、provider、网络或权限问题
- 配好 provider 后，再次执行 `roboclaw agent -m "hello"` 能正常返回

到这里为止，RoboClaw 的基础启动链路才算真正打通。

## 7. Step 5: Verify the Workspace-First Rule

这一步是这次 PR 的核心。

RoboClaw 现在应该遵守：

- framework 协议和代码在仓库里
- 用户 setup-specific 文件在 `~/.roboclaw/workspace/embodied/`
- RoboClaw 不应该把具身接入内容直接写回 framework 源码

先看当前仓库是否干净：

```bash
git status --short
```

然后让 RoboClaw 进入具身 setup 引导。可以直接给它一个明确任务，例如：

```bash
roboclaw agent -m "I want to set up a real robot in RoboClaw. Help me collect the required embodiment information first, then create the necessary setup files under ~/.roboclaw/workspace/embodied/. Do not modify the framework source code."
```

你要验证：

- RoboClaw 会先收集缺失信息，而不是直接乱写
- RoboClaw 会引用 `EMBODIED.md` 的规则
- RoboClaw 把新文件写到 `~/.roboclaw/workspace/embodied/`
- 仓库内 framework 源码不应该因此产生无关改动

建议检查：

```bash
find ~/.roboclaw/workspace/embodied -maxdepth 3 -type f | sort
git status --short
```

预期结果：

- `~/.roboclaw/workspace/embodied/` 下出现新的 intake 或 setup 文件
- 仓库里的协议层源码没有被 agent 直接改写

如果 agent 把 setup 写进了仓库源码，这个 PR 的核心边界就没有守住。

## 8. Step 6: Verify That Embodied Assets Are Organized Correctly

你不需要一次性生成所有资产，但至少要验证路径语义是对的。

重点检查这些目录是否被正确使用：

```text
~/.roboclaw/workspace/embodied/intake/
~/.roboclaw/workspace/embodied/robots/
~/.roboclaw/workspace/embodied/sensors/
~/.roboclaw/workspace/embodied/assemblies/
~/.roboclaw/workspace/embodied/deployments/
~/.roboclaw/workspace/embodied/adapters/
~/.roboclaw/workspace/embodied/simulators/
```

你要验证：

- intake 信息先进入 `intake/`
- robot/sensor/setup 资产被写入语义正确的目录
- 目录结构没有混乱到看不出边界

这一步的目标不是验证“内容已经完美”，而是验证“这条路径是可维护、可继续扩展的”。

## 9. Step 7: If You Have a Real Robot or Simulator, Test the Embodied Flow

只有在你已经具备真实本体或仿真环境时，才进入这一段。

这里开始验证第一个版图的核心目标：

- 连接
- 校准
- 移动
- debug
- 复位

### 9.1 Connect

让 RoboClaw 帮你进入连接流程，例如：

```bash
roboclaw agent -m "Connect my robot and tell me what information is still missing."
```

你要验证：

- RoboClaw 能识别当前是 `real` 还是 `sim`
- RoboClaw 能识别本体类型
- 如果信息不完整，它会先补问，而不是假设
- 如果失败，失败原因可读

### 9.2 Calibrate

```bash
roboclaw agent -m "Calibrate this robot if calibration is supported. If not, explain why."
```

你要验证：

- RoboClaw 能区分“支持 calibration”和“不支持 calibration”
- 不支持时不会瞎编流程

### 9.3 Move

```bash
roboclaw agent -m "Do one minimal safe movement for verification."
```

你要验证：

- RoboClaw 会优先选择最小安全动作
- 它能清楚说明动作意图
- 失败时能说清是 setup、ROS2、adapter 还是安全限制问题

### 9.4 Debug

```bash
roboclaw agent -m "Debug the current setup and summarize the most likely blocking issue."
```

你要验证：

- RoboClaw 能输出可读的 debug 结果
- debug 不是泛泛而谈，而是能定位到具体层

### 9.5 Reset

```bash
roboclaw agent -m "Reset the robot to a known safe state."
```

你要验证：

- RoboClaw 会优先考虑安全状态
- reset 的结果或失败位置是清楚的

## 10. What to Record During Validation

每次验证都建议记录这几类信息：

- 当前命令
- 当前本体类型
- 当前是 `real` 还是 `sim`
- 当前 provider / model 状态
- 当前生成了哪些 workspace 文件
- 当前失败点是在安装、初始化、workspace、agent、ROS2、adapter 还是具体本体流程

## 11. Final Pass Criteria

当下面这些都成立时，才可以说这次 PR 的核心功能基本可用：

- [ ] `pip install -e ".[dev]"` 成功
- [ ] `roboclaw onboard` 成功
- [ ] `roboclaw status` 成功
- [ ] `roboclaw agent -m "hello"` 成功
- [ ] RoboClaw 能把具身 setup 写到 `~/.roboclaw/workspace/embodied/`
- [ ] RoboClaw 没有直接污染 framework 源码
- [ ] 如果有真实本体或仿真，RoboClaw 至少能进入 `connect` 流程并给出合理反馈

如果前四项都成立，但后面不成立，说明 RoboClaw 基础启动链路是通的，但具身入口链路还不够强。

如果前四项都不稳定，这个 PR 还不能作为对外展示的首跑流程。
