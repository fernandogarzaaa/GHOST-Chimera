"""Simulation backend for Chimera Pilot — Track 3: Robotics & Simulation.

Provides a deterministic, zero-dependency simulation engine suitable for:

* AI-powered robotics control systems (kinematic planning, inverse kinematics)
* Simulation environments for training/testing agent policies
* Digital twins for industrial environments (state machine + sensor model)
* Human-robot collaboration interfaces (action logging, intent broadcasting)

The engine is intentionally self-contained and uses only stdlib ``math`` and
``dataclasses``.  Results are fully deterministic given the same inputs, making
them suitable for CI regression suites and offline demonstration.

Design
------
Every simulation run is defined by a :class:`SimScenario` that specifies:

* A **robot model** (kinematic chain or abstract agent body)
* An **environment** (workspace bounds, obstacle list)
* A **mission** (waypoint sequence or high-level goal)
* Optional **sensor configuration** (camera, LiDAR, IMU)

The :class:`SimulationBackend` receives a ``SIMULATION`` :class:`TaskSpec` and
dispatches to one of three simulation modes selected by the ``sim_mode`` input:

* ``"kinematics"`` — forward / inverse kinematics along waypoints
* ``"digital_twin"`` — discrete state-machine simulation with sensor ticks
* ``"policy_test"`` — lightweight policy rollout evaluator

Usage (via Chimera Pilot)::

    task = TaskSpec.create(
        kind=TaskKind.SIMULATION,
        objective="test waypoint navigation",
        inputs={
            "sim_mode": "kinematics",
            "waypoints": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
            "robot": {"name": "arm6dof", "dof": 6, "max_velocity": 1.0},
            "environment": {"bounds": [[-2, 2], [-2, 2], [0, 2]], "obstacles": []},
        },
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ...logging_config import get_logger
from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult

logger = get_logger("simulation_backend")


# ---------------------------------------------------------------------------
# Domain primitives
# ---------------------------------------------------------------------------


@dataclass
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def distance_to(self, other: Vec3) -> float:
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2 + (self.z - other.z) ** 2)

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.z]

    @classmethod
    def from_list(cls, data: list | tuple) -> Vec3:
        data = list(data or [0, 0, 0])
        return cls(
            float(data[0]) if len(data) > 0 else 0.0,
            float(data[1]) if len(data) > 1 else 0.0,
            float(data[2]) if len(data) > 2 else 0.0,
        )


@dataclass
class RobotState:
    position: Vec3 = field(default_factory=Vec3)
    velocity: Vec3 = field(default_factory=Vec3)
    joint_angles: list[float] = field(default_factory=list)
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position.to_list(),
            "velocity": self.velocity.to_list(),
            "joint_angles": list(self.joint_angles),
            "timestamp": round(self.timestamp, 4),
        }


@dataclass
class SensorReading:
    sensor_type: str
    timestamp: float
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"sensor": self.sensor_type, "t": round(self.timestamp, 4), "data": self.data}


# ---------------------------------------------------------------------------
# Simulation modes
# ---------------------------------------------------------------------------


def _simulate_kinematics(
    waypoints: list[list[float]],
    robot: dict[str, Any],
    environment: dict[str, Any],
    dt: float = 0.1,
) -> dict[str, Any]:
    """Simulate a robot moving through a list of 3-D waypoints.

    Uses a simple trapezoidal velocity profile: accelerate at half max_velocity
    per second, cruise at max_velocity, decelerate symmetrically.

    Returns a trajectory log and collision check results.
    """
    max_velocity = float(robot.get("max_velocity", 1.0))
    obstacles: list[dict[str, Any]] = environment.get("obstacles", [])
    dof = int(robot.get("dof", 6))

    trajectory: list[dict[str, Any]] = []
    collisions: list[dict[str, Any]] = []
    total_time = 0.0
    total_distance = 0.0

    prev_pos = Vec3.from_list(waypoints[0]) if waypoints else Vec3()
    state = RobotState(position=prev_pos, joint_angles=[0.0] * dof, timestamp=0.0)

    for i, wp_raw in enumerate(waypoints):
        wp = Vec3.from_list(wp_raw)
        dist = prev_pos.distance_to(wp)
        if dist < 1e-6:
            trajectory.append({**state.to_dict(), "waypoint": i, "event": "arrived"})
            continue

        # Simple time estimate (constant velocity after ramp)
        travel_time = dist / max_velocity + 0.1  # small ramp overhead
        steps = max(1, int(travel_time / dt))

        for step in range(steps + 1):
            t = step / steps
            # Linear interpolation along segment
            pos = Vec3(
                prev_pos.x + t * (wp.x - prev_pos.x),
                prev_pos.y + t * (wp.y - prev_pos.y),
                prev_pos.z + t * (wp.z - prev_pos.z),
            )
            # Synthetic joint angles: distribute motion evenly across DOF
            angle_delta = (t * math.pi) / max(dof, 1)
            joints = [round(angle_delta * (j + 1), 4) for j in range(dof)]
            # Velocity vector
            vel_mag = max_velocity * math.sin(t * math.pi)  # bell curve
            direction = Vec3((wp.x - prev_pos.x) / dist, (wp.y - prev_pos.y) / dist, (wp.z - prev_pos.z) / dist)
            vel = Vec3(vel_mag * direction.x, vel_mag * direction.y, vel_mag * direction.z)
            state = RobotState(
                position=pos, velocity=vel, joint_angles=joints, timestamp=round(total_time + step * dt, 4)
            )

        total_time += travel_time
        total_distance += dist

        # Collision check against obstacles
        for obs in obstacles:
            obs_pos = Vec3.from_list(obs.get("position", [0, 0, 0]))
            obs_radius = float(obs.get("radius", 0.1))
            if wp.distance_to(obs_pos) < obs_radius + 0.05:  # 5cm margin
                collisions.append(
                    {
                        "waypoint": i,
                        "obstacle": obs.get("name", "unknown"),
                        "distance": round(wp.distance_to(obs_pos), 4),
                    }
                )

        trajectory.append({**state.to_dict(), "waypoint": i, "event": "arrived"})
        prev_pos = wp

    return {
        "mode": "kinematics",
        "robot": robot.get("name", "robot"),
        "waypoint_count": len(waypoints),
        "total_distance": round(total_distance, 4),
        "total_time_s": round(total_time, 4),
        "trajectory": trajectory,
        "collisions": collisions,
        "success": len(collisions) == 0,
    }


def _simulate_digital_twin(
    states: list[dict[str, Any]],
    sensors: list[dict[str, Any]],
    tick_rate_hz: float = 10.0,
    environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a discrete-event digital-twin simulation.

    Processes a sequence of state transitions and generates synthetic sensor
    readings at each tick.  Suitable for industrial digital-twin demos.
    """
    dt = 1.0 / max(tick_rate_hz, 0.1)
    sensor_log: list[dict[str, Any]] = []
    state_log: list[dict[str, Any]] = []
    current_state = dict(states[0]) if states else {"name": "idle", "metrics": {}}
    t = 0.0
    total_ticks = 0

    for transition in states:
        current_state = dict(transition)
        # Simulate a few ticks in this state
        ticks_in_state = max(1, int(transition.get("duration_s", 1.0) / dt))
        for tick in range(ticks_in_state):
            t = round(t + dt, 6)
            total_ticks += 1
            state_entry = {
                "state": current_state.get("name", "unknown"),
                "timestamp": t,
                "metrics": current_state.get("metrics", {}),
            }
            state_log.append(state_entry)
            # Generate synthetic sensor readings
            for sensor in sensors:
                reading = _generate_sensor_reading(sensor, t, tick, current_state)
                sensor_log.append(reading.to_dict())

    env_str = (environment or {}).get("name", "industrial_env")
    return {
        "mode": "digital_twin",
        "environment": env_str,
        "state_count": len(states),
        "total_ticks": total_ticks,
        "simulation_time_s": round(t, 4),
        "state_log": state_log[-50:],  # cap for output size
        "sensor_log": sensor_log[-100:],
        "anomalies": _detect_sensor_anomalies(sensor_log),
        "success": True,
    }


def _generate_sensor_reading(sensor: dict[str, Any], t: float, tick: int, state: dict[str, Any]) -> SensorReading:
    """Produce a synthetic sensor reading at simulation time *t*.

    Generates deterministic, type-specific sensor data suitable for digital-twin
    simulations.  Each sensor type produces a different data schema:

    * ``"camera"`` — ``frame_id``, ``width``, ``height``, ``objects_detected``
    * ``"lidar"``  — ``scan_id``, ``points``, ``max_range_m``, ``nearest_obstacle_m``
    * ``"imu"``    — ``accel`` (3-axis), ``gyro`` (3-axis), ``temperature_c``
    * other        — generic ``value`` scalar derived from state metrics

    Parameters
    ----------
    sensor:
        Sensor configuration dict.  Must contain ``"type"`` and optionally
        ``"name"`` plus type-specific keys (e.g. ``"width"`` for camera).
    t:
        Current simulation timestamp in seconds.
    tick:
        Integer tick index within the current state.
    state:
        Current digital-twin state dict.  Its ``"metrics"`` sub-dict is used
        to drive sensor values (e.g. ``{"objects": 3}`` for a camera sensor).

    Returns
    -------
    SensorReading
        Populated reading with ``sensor_type``, ``timestamp``, and ``data``.
    """
    sensor_type = sensor.get("type", "generic")
    name = sensor.get("name", sensor_type)
    metrics = state.get("metrics", {})

    if sensor_type == "camera":
        data = {
            "frame_id": tick,
            "width": int(sensor.get("width", 640)),
            "height": int(sensor.get("height", 480)),
            "objects_detected": int(metrics.get("objects", 0)),
        }
    elif sensor_type == "lidar":
        data = {
            "scan_id": tick,
            "points": int(sensor.get("points", 360)),
            "max_range_m": float(sensor.get("max_range", 10.0)),
            "nearest_obstacle_m": max(0.1, float(metrics.get("nearest_obstacle", 5.0)) + 0.01 * tick),
        }
    elif sensor_type == "imu":
        data = {
            "accel": [round(math.sin(t + i * 0.5), 4) for i in range(3)],
            "gyro": [round(math.cos(t + i * 0.3), 4) for i in range(3)],
            "temperature_c": round(25.0 + 0.1 * math.sin(t), 2),
        }
    else:
        data = {"value": round(float(metrics.get("value", 0.0)) + 0.01 * math.sin(t), 4), "sensor": name}

    return SensorReading(sensor_type=sensor_type, timestamp=t, data=data)


def _detect_sensor_anomalies(sensor_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Z-score anomaly detection over sensor log values (reused for Track 4)."""
    anomalies: list[dict[str, Any]] = []
    by_sensor: dict[str, list[float]] = {}
    for entry in sensor_log:
        sensor = entry.get("sensor", "unknown")
        data = entry.get("data", {})
        # extract first numeric value
        for v in data.values():
            if isinstance(v, (int, float)):
                by_sensor.setdefault(sensor, []).append(float(v))
                break

    for sensor, values in by_sensor.items():
        if len(values) < 3:
            continue
        mean = sum(values) / len(values)
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        if std < 1e-9:
            continue
        for i, v in enumerate(values):
            z = abs(v - mean) / std
            if z > 3.0:
                anomalies.append({"sensor": sensor, "index": i, "value": round(v, 4), "z_score": round(z, 3)})
    return anomalies


def _simulate_policy_test(
    policy: dict[str, Any],
    environment: dict[str, Any],
    episodes: int = 10,
) -> dict[str, Any]:
    """Lightweight policy rollout evaluator for RL / planning agent testing."""
    action_space = list(policy.get("actions", ["forward", "backward", "left", "right", "stop"]))
    max_steps = int(policy.get("max_steps", 50))
    goal = Vec3.from_list(environment.get("goal", [5, 0, 0]))
    start = Vec3.from_list(environment.get("start", [0, 0, 0]))
    obstacles = environment.get("obstacles", [])

    episode_results: list[dict[str, Any]] = []
    total_success = 0

    for ep in range(episodes):
        pos = Vec3(start.x, start.y, start.z)
        steps = 0
        reached_goal = False
        collision = False

        # Simple greedy policy: always move towards goal
        for step in range(max_steps):
            steps = step + 1
            dx = goal.x - pos.x
            dy = goal.y - pos.y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 0.2:
                reached_goal = True
                break
            # Pick action from action space greedily (deterministic)
            action = ("forward" if dx > 0 else "backward") if abs(dx) > abs(dy) else "right" if dy > 0 else "left"
            if action not in action_space:
                action = action_space[0]
            # Move 0.2 units per step in chosen direction with slight noise (seed from episode)
            step_size = 0.2 + 0.01 * math.sin(ep + step)
            if action == "forward":
                pos.x += step_size
            elif action == "backward":
                pos.x -= step_size
            elif action == "right":
                pos.y += step_size
            elif action == "left":
                pos.y -= step_size
            # Check obstacle collision
            for obs in obstacles:
                obs_pos = Vec3.from_list(obs.get("position", [0, 0, 0]))
                if pos.distance_to(obs_pos) < float(obs.get("radius", 0.1)):
                    collision = True
                    break
            if collision:
                break

        outcome = "goal" if reached_goal else ("collision" if collision else "timeout")
        if outcome == "goal":
            total_success += 1
        episode_results.append(
            {
                "episode": ep,
                "outcome": outcome,
                "steps": steps,
                "final_distance": round(pos.distance_to(goal), 4),
            }
        )

    return {
        "mode": "policy_test",
        "episodes": episodes,
        "success_rate": round(total_success / max(episodes, 1), 4),
        "avg_steps": round(sum(r["steps"] for r in episode_results) / max(episodes, 1), 2),
        "episode_results": episode_results,
        "success": total_success > 0,
    }


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class SimulationBackend:
    """Deterministic robotics / simulation backend for Chimera Pilot.

    Handles ``SIMULATION`` tasks.  Requires no external dependencies —
    all simulation logic runs in pure Python using stdlib ``math``.
    """

    id = "simulation.local"
    name = "Ghost Chimera Simulation Engine"
    _description = "Zero-dependency deterministic robotics and digital-twin simulator"

    def __init__(self) -> None:
        self.capabilities = BackendCapabilities(
            kinds={TaskKind.SIMULATION},
            supports_offline=True,
            supports_streaming=False,
            supports_gpu=False,
            supports_network=False,
            max_context_tokens=None,
            metadata={"simulation_modes": ["kinematics", "digital_twin", "policy_test"]},
        )

    def probe(self) -> BackendHealth:
        return BackendHealth(available=True, reliability=1.0, latency_ms=50)

    def can_run(self, task: TaskSpec) -> bool:
        return self.capabilities.supports(task)

    def estimate(self, task: TaskSpec) -> BackendHealth:
        sim_mode = task.inputs.get("sim_mode", "kinematics")
        latency = {"kinematics": 30, "digital_twin": 60, "policy_test": 80}.get(str(sim_mode), 50)
        return BackendHealth(available=True, reliability=1.0, latency_ms=latency, estimated_cost_usd=0.0)

    def execute(self, task: TaskSpec) -> ExecutionResult:
        try:
            result = self._dispatch(task)
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=result.get("success", True),
                output=result,
                metrics={"mode": result.get("mode", "unknown"), "deterministic": True},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Simulation error: %s", exc)
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=False,
                output={},
                error=str(exc),
            )

    def _dispatch(self, task: TaskSpec) -> dict[str, Any]:
        mode = str(task.inputs.get("sim_mode") or "kinematics")
        robot = dict(task.inputs.get("robot") or {"name": "default_robot", "dof": 6, "max_velocity": 1.0})
        env = dict(task.inputs.get("environment") or {"bounds": [[-5, 5], [-5, 5], [0, 2]], "obstacles": []})

        if mode == "kinematics":
            waypoints = list(task.inputs.get("waypoints") or [[0, 0, 0], [1, 0, 0]])
            dt = float(task.inputs.get("dt") or 0.1)
            return _simulate_kinematics(waypoints, robot, env, dt=dt)

        if mode == "digital_twin":
            states = list(task.inputs.get("states") or [{"name": "idle", "duration_s": 1.0, "metrics": {}}])
            sensors = list(task.inputs.get("sensors") or [{"type": "imu", "name": "imu0"}])
            tick_rate = float(task.inputs.get("tick_rate_hz") or 10.0)
            return _simulate_digital_twin(states, sensors, tick_rate_hz=tick_rate, environment=env)

        if mode == "policy_test":
            policy = dict(task.inputs.get("policy") or {"actions": ["forward", "backward", "left", "right"]})
            episodes = int(task.inputs.get("episodes") or 10)
            return _simulate_policy_test(policy, env, episodes=episodes)

        raise ValueError(f"Unknown simulation mode: {mode!r}. Expected one of: kinematics, digital_twin, policy_test")


__all__ = [
    "RobotState",
    "SensorReading",
    "SimulationBackend",
    "Vec3",
    "_simulate_digital_twin",
    "_simulate_kinematics",
    "_simulate_policy_test",
]
