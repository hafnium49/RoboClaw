# RoboClaw

**RoboClaw** is an open, co-created framework for embodied AI assistants.

It is inspired by OpenClaw, but it is not "OpenClaw for robots".

RoboClaw is organized around four layers:

- `Assistant Layer`: users, sessions, agent orchestration, tool routing, and remote access
- `Embodiment Layer`: embodiment modeling, spatial organization, capability abstraction, familiarization, calibration, training assistance, emergency-stop judgment, and recovery support
- `Execution Layer`: ROS2-based execution middleware for controllers, messaging, services, actions, safety supervision, and state return
- `Carrier Layer`: simulator and real-robot connection, deployment, validation, and feedback

## Why RoboClaw

Embodied AI needs more than a stronger model. It needs a reusable architecture that can organize bodies, sensors, actions, execution, and deployment into one coherent system.

RoboClaw tries to avoid three common mistakes:

1. Turning everything into robot-specific glue code
2. Treating raw ROS interfaces as the final abstraction
3. Relying on prompting alone to handle embodiment differences

## System Path

`goal -> planner -> semantic skill -> supervisor -> execution layer -> carrier layer`

RoboClaw prefers semantic actions and bounded supervision over raw low-level motor control from the model.

## Principles

- Explicit interfaces over hidden coupling
- Semantic actions over raw joint commands
- Supervisors over unconstrained model behavior
- Framework quality over demo-specific shortcuts

## Status

RoboClaw is still early. The direction is clear, but the implementation is intentionally narrow.

Not yet claimed:

- A full embodied runtime
- A stable multi-robot abstraction
- A complete deployment and validation stack

## Co-Create With Us

We welcome contributions around architecture, embodiment modeling, execution interfaces, simulator integration, real robot adapters, validation, and documentation.

For Chinese, see [README.zh.md](README.zh.md).

## WeChat Group

<img src="wechat/wechat_group.jpg" alt="RoboClaw WeChat Group" width="300" />
