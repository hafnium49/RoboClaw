# RoboClaw Installation Guide

## 1. Prerequisites

Start from a clean clone:

```bash
git clone https://github.com/MINT-SJTU/RoboClaw.git
cd RoboClaw
```

## 2. Step 1: Install RoboClaw

Install the package in editable mode:

```bash
pip install -e ".[dev]"
```

After installation, the `roboclaw` command should be available:

```bash
roboclaw --help
```

Expected result:

- commands such as `onboard`, `status`, `agent`, and `provider` are listed

## 3. Step 2: Initialize RoboClaw

Run:

```bash
roboclaw onboard
```

This should create `~/.roboclaw/config.json`, `~/.roboclaw/workspace/`, and the initial embodied workspace scaffold. You can verify it with:

```bash
find ~/.roboclaw -maxdepth 4 -type f | sort
```

You should see at least:

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

## 4. Step 3: Verify Status Output

Run:

```bash
roboclaw status
```

Check that:

- `Config` is shown as `✓`
- `Workspace` is shown as `✓`
- the current `Model` looks correct
- provider status matches the actual state of your machine

## 5. Step 4: Configure the Model Provider

Before testing `roboclaw agent`, make sure the model provider is configured.

First run:

```bash
roboclaw status
```

This tells you which providers are already available on the current machine.

Two common cases:

### 5.1 OAuth provider

If you are using an OAuth-based provider, log in directly.

The current codebase supports:

```bash
roboclaw provider login openai-codex
roboclaw provider login github-copilot
```

### 5.2 API key provider

If you are using an API-key-based provider, edit:

```bash
~/.roboclaw/config.json
```

Fill in the provider key and default model there.

Common API key providers include:

- `openai`
- `anthropic`
- `openrouter`
- `deepseek`
- `gemini`
- `zhipu`
- `dashscope`
- `moonshot`
- `minimax`
- `aihubmix`
- `siliconflow`
- `volcengine`
- `azureOpenai`
- `custom`
- `vllm`

Then run:

```bash
roboclaw status
```

Check that:

- the current `Model` is correct
- the provider you want to use is no longer `not set`

## 6. Step 5: Verify the Basic Model Path

Run one minimal message to confirm that RoboClaw can respond:

```bash
roboclaw agent -m "hello"
```

Check that:

- the agent starts successfully
- the agent returns a normal reply
- failures point clearly to model configuration, provider setup, network, or permissions

## 7. Step 6: Let RoboClaw Start the Robot Setup Flow

Once the basic conversation path works, start the embodied setup flow.

Describe your goal in natural language.

For a real robot:

```bash
roboclaw agent -m "I want to connect a real robot. Please guide me step by step."
```

If you already know it is an arm:

```bash
roboclaw agent -m "I want to connect a real robot arm. Tell me what information you need and guide me step by step."
```

For a simulator:

```bash
roboclaw agent -m "I want to connect a robot simulation environment. Please guide me step by step."
```

At this step, check that:

- RoboClaw understands that this is a first-run robot setup flow
- RoboClaw asks for missing facts instead of assuming them
- RoboClaw asks questions in a way that a normal user can follow
- RoboClaw does not require the user to understand the internal code structure first

If RoboClaw starts guiding you through device information, connection details, sensors, or runtime environment, the embodied entry path is working.

After continuing the conversation, you can check:

```bash
find ~/.roboclaw/workspace/embodied -maxdepth 3 -type f | sort
git status --short
```

Check that:

- new files start appearing under `~/.roboclaw/workspace/embodied/`
- RoboClaw does not write setup-specific content back into the framework source tree

The ideal outcome is:

- the user only describes the goal
- RoboClaw keeps the framework/workspace boundary intact

## 8. Step 7: Verify That Embodied Assets Are Organized Correctly

You do not need every asset to be complete in one pass, but you should verify that the directory semantics are correct.

Pay attention to these paths:

```text
~/.roboclaw/workspace/embodied/intake/
~/.roboclaw/workspace/embodied/robots/
~/.roboclaw/workspace/embodied/sensors/
~/.roboclaw/workspace/embodied/assemblies/
~/.roboclaw/workspace/embodied/deployments/
~/.roboclaw/workspace/embodied/adapters/
~/.roboclaw/workspace/embodied/simulators/
```

Check that:

- intake facts land in `intake/` first
- robot, sensor, and setup assets are written into the right semantic directories
- the resulting layout is understandable and maintainable

The goal here is not to prove that every asset is perfect. The goal is to verify that the path is structured well enough to extend.

## 9. Step 8: If You Have a Real Robot or Simulator, Test the Embodied Flow

Only continue with this section if you actually have a real embodiment or simulator available.

If RoboClaw detects that ROS2 is not installed, do not let it improvise an installation guide. It should read and follow:

```text
roboclaw/templates/embodied/guides/ROS2_INSTALL.md
```

The goal is to:

- prefer a supported platform-specific installation path
- prefer Ubuntu binary installation before source builds
- record the ROS2 result and distro into intake or workspace assets
- continue to deployment and adapter generation only after ROS2 is ready

This is where the core first-plane goal starts to matter:

- connect
- calibrate
- move
- debug
- reset

### 9.1 Connect

For example:

```bash
roboclaw agent -m "Connect my robot and tell me what information is still missing."
```

Check that:

- RoboClaw can distinguish `real` from `sim`
- RoboClaw can identify the embodiment type
- if information is incomplete, it asks instead of guessing
- failure reasons are readable

### 9.2 Calibrate

```bash
roboclaw agent -m "Calibrate this robot if calibration is supported. If not, explain why."
```

Check that:

- RoboClaw can distinguish between supported and unsupported calibration flows
- when calibration is not supported, it does not invent a fake procedure

### 9.3 Move

```bash
roboclaw agent -m "Do one minimal safe movement for verification."
```

Check that:

- RoboClaw prefers the smallest safe motion first
- the movement intent is explained clearly
- on failure, it can say whether the issue is setup, ROS2, adapter, or safety related

### 9.4 Debug

```bash
roboclaw agent -m "Debug the current setup and summarize the most likely blocking issue."
```

Check that:

- RoboClaw produces readable debug output
- the debug result points to a concrete layer, not generic filler

### 9.5 Reset

```bash
roboclaw agent -m "Reset the robot to a known safe state."
```

Check that:

- RoboClaw prioritizes a safe state
- the reset result or failure point is clear

## 10. What to Record During Validation

For each validation run, it is helpful to record:

- the command you ran
- the embodiment type
- whether the target is `real` or `sim`
- the current provider and model state
- which workspace files were generated
- whether the failure point is installation, initialization, workspace, agent, ROS2, adapter, or the embodiment-specific flow

## 11. Final Pass Criteria

The core path is in acceptable shape only when all of the following are true:

- [ ] `pip install -e ".[dev]"` succeeds
- [ ] `roboclaw onboard` succeeds
- [ ] `roboclaw status` succeeds
- [ ] `roboclaw agent -m "hello"` succeeds
- [ ] RoboClaw can write embodied setup assets into `~/.roboclaw/workspace/embodied/`
- [ ] RoboClaw does not directly pollute framework source files
- [ ] if a real robot or simulator is available, RoboClaw can at least enter the `connect` flow and return a reasonable result

If the first four items pass but the later ones fail, the basic startup path works but the embodied entry path is still not strong enough.

If the first four items are unstable, the PR is not yet ready as a first-run external demo path.
