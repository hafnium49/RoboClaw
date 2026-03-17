---
name: embodiment-authoring
description: Workspace-first rules for generating embodied assemblies, deployments, adapters, and simulator assets.
always: true
---

# Embodiment Authoring

## Policy

- Treat `roboclaw/embodied/` as framework code.
- Only edit framework code when changing generic contracts, reusable component manifests, shared runtime logic, or transport/procedure abstractions.
- Do not put user-specific assemblies, deployments, adapters, scenarios, or lab configs under `roboclaw/embodied/`.
- Generate concrete embodiment assets under `~/.roboclaw/workspace/embodied/` for real user setups.

## Workspace-First Flow

1. Read `EMBODIED.md` in the active workspace before creating embodied files.
2. As soon as the user identifies the robot model or class, create or update `embodied/intake/<slug>.md` with what is already known.
3. Reuse built-in robot and sensor ids when they already exist in framework code.
4. Default to the RoboClaw ROS2 path unless the user explicitly asks for a different execution stack.
5. Infer what you can from the repo, framework manifests, workspace, and local environment before asking the user.
6. Ask only the smallest missing setup-specific question needed for the next step.
7. Create or update only the workspace files needed for this setup:
   - `embodied/robots/`
   - `embodied/sensors/`
   - `embodied/assemblies/`
   - `embodied/deployments/`
   - `embodied/adapters/`
   - `embodied/simulators/`
8. Keep ids stable so later chat turns can refine the same setup instead of generating a new one.

## First-Run Success Criteria

Treat the first real run as successful only when the generated workspace assets
are sufficient for RoboClaw to attempt:

- `connect`
- `calibrate` or an explicit unsupported explanation
- `move` with a small safe action
- `debug`
- `reset`

## Boundaries

- `robots/` in framework may contain reusable robot manifests such as supported open-source bodies.
- Attachment placement, ROS2 namespaces, deployment connection params, lab safety limits, and simulator worlds are setup-specific and belong in workspace assets.
- If a setup needs a new robot manifest that is not reusable enough for framework, create it in workspace first.
- The current path is framework contracts plus workspace assets loaded through catalog.
- Do not require a first-time user to choose ROS2 vs SDK, list topics/actions, or provide package paths before intake starts when the framework already implies the default path.
- Do not front-load large questionnaires. Ask one targeted question, then continue.
- For known framework robots, prefer framework-default assumptions over open-ended transport questions.
- For `SO101`, assume the default real setup is ROS2-backed and locally connected through USB/serial unless the user says otherwise.
- For `SO101`, do not start by asking whether it is USB, serial, or IP. Start intake first, then only ask for the concrete serial device path if deployment generation needs it and you cannot infer it.
- If a needed connection fact may be discoverable locally, inspect the environment before asking the user.

## Scaffolding

- Prefer reading and adapting files under `embodied/_templates/` in the workspace instead of inventing structure from scratch.
- The templates are skeletal on purpose. Do not preserve placeholder capability families, mounts, attachment ids, simulator backends, or safety defaults unless intake facts confirm them.
- Use export names that the workspace loader can discover: `ROBOT`, `SENSOR`, `ASSEMBLY`, `DEPLOYMENT`, `ADAPTER`, `WORLD`, `SCENARIO`, or the plural form of each.
- The intake note should record:
  - robot model and embodiment type
  - sensors and mounting points
  - ROS2 packages, nodes, namespaces, topics, actions, services
  - real vs sim targets
  - deployment-specific connection facts
  - safety or calibration constraints

## First-Run Prompting Rules

- Good first-turn user inputs are natural statements like:
  - "我想接入一台真实的机器人，请一步一步带我完成配置。"
  - "我想安装 SO101。"
  - "我想接入一个仿真机械臂。"
- For a known framework robot such as SO101, start intake immediately and assume the framework-default path first.
- Only ask questions the user is realistically expected to know.
- Do not ask for connection details, namespaces, package names, or SDK choices until they are required for the next concrete action.
- For `SO101`, a good next step is something like:
  - "我已经先按 SO101 的默认 ROS2 接入方式为你创建了接入记录。下一步我来检查或记录当前串口设备，再继续生成部署配置。"
  not:
  - "你的 SO101 是通过什么方式连接到电脑的？"
