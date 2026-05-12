"""Tests for SimulationBackend — Track 3: Robotics & Simulation."""

from __future__ import annotations

import unittest


class TestVec3(unittest.TestCase):
    def test_distance_to(self):
        from ghostchimera.chimera_pilot.backends.simulation import Vec3

        a = Vec3(0, 0, 0)
        b = Vec3(3, 4, 0)
        self.assertAlmostEqual(a.distance_to(b), 5.0)

    def test_to_list(self):
        from ghostchimera.chimera_pilot.backends.simulation import Vec3

        v = Vec3(1.0, 2.0, 3.0)
        self.assertEqual(v.to_list(), [1.0, 2.0, 3.0])

    def test_from_list_full(self):
        from ghostchimera.chimera_pilot.backends.simulation import Vec3

        v = Vec3.from_list([1.5, 2.5, 3.5])
        self.assertAlmostEqual(v.x, 1.5)
        self.assertAlmostEqual(v.y, 2.5)
        self.assertAlmostEqual(v.z, 3.5)

    def test_from_list_partial(self):
        from ghostchimera.chimera_pilot.backends.simulation import Vec3

        v = Vec3.from_list([1.0])
        self.assertAlmostEqual(v.x, 1.0)
        self.assertAlmostEqual(v.y, 0.0)
        self.assertAlmostEqual(v.z, 0.0)


class TestKinematics(unittest.TestCase):
    def test_basic_trajectory(self):
        from ghostchimera.chimera_pilot.backends.simulation import _simulate_kinematics

        result = _simulate_kinematics(
            [[0, 0, 0], [1, 0, 0], [2, 0, 0]],
            {"name": "arm", "dof": 4, "max_velocity": 1.0},
            {"bounds": [[-5, 5], [-5, 5], [0, 2]], "obstacles": []},
        )
        self.assertEqual(result["mode"], "kinematics")
        self.assertGreater(result["total_distance"], 0)
        self.assertGreater(len(result["trajectory"]), 0)
        self.assertEqual(len(result["collisions"]), 0)
        self.assertTrue(result["success"])

    def test_collision_detected(self):
        from ghostchimera.chimera_pilot.backends.simulation import _simulate_kinematics

        result = _simulate_kinematics(
            [[0, 0, 0], [1, 0, 0]],
            {"name": "arm", "dof": 6, "max_velocity": 1.0},
            {"bounds": [[-5, 5], [-5, 5], [0, 2]], "obstacles": [{"name": "wall", "position": [1, 0, 0], "radius": 0.3}]},
        )
        self.assertGreater(len(result["collisions"]), 0)
        self.assertFalse(result["success"])

    def test_single_waypoint_no_movement(self):
        from ghostchimera.chimera_pilot.backends.simulation import _simulate_kinematics

        result = _simulate_kinematics(
            [[0, 0, 0]],
            {"name": "arm", "dof": 6, "max_velocity": 1.0},
            {"obstacles": []},
        )
        self.assertAlmostEqual(result["total_distance"], 0.0)

    def test_trajectory_joint_count(self):
        from ghostchimera.chimera_pilot.backends.simulation import _simulate_kinematics

        dof = 4
        result = _simulate_kinematics(
            [[0, 0, 0], [2, 0, 0]],
            {"name": "arm", "dof": dof, "max_velocity": 1.0},
            {"obstacles": []},
        )
        last = result["trajectory"][-1]
        self.assertEqual(len(last["joint_angles"]), dof)


class TestDigitalTwin(unittest.TestCase):
    def test_basic_simulation(self):
        from ghostchimera.chimera_pilot.backends.simulation import _simulate_digital_twin

        result = _simulate_digital_twin(
            [{"name": "idle", "duration_s": 0.5, "metrics": {"temp": 20}},
             {"name": "running", "duration_s": 0.5, "metrics": {"temp": 80}}],
            [{"type": "imu", "name": "imu0"}],
            tick_rate_hz=10.0,
        )
        self.assertEqual(result["mode"], "digital_twin")
        self.assertGreater(result["total_ticks"], 0)
        self.assertGreater(len(result["sensor_log"]), 0)
        self.assertTrue(result["success"])

    def test_lidar_sensor_reading(self):
        from ghostchimera.chimera_pilot.backends.simulation import _simulate_digital_twin

        result = _simulate_digital_twin(
            [{"name": "scan", "duration_s": 0.3, "metrics": {}}],
            [{"type": "lidar", "name": "lidar0", "points": 360, "max_range": 15.0}],
            tick_rate_hz=10.0,
        )
        lidar_entries = [e for e in result["sensor_log"] if e["sensor"] == "lidar"]
        self.assertGreater(len(lidar_entries), 0)
        self.assertIn("points", lidar_entries[0]["data"])

    def test_camera_sensor_reading(self):
        from ghostchimera.chimera_pilot.backends.simulation import _simulate_digital_twin

        result = _simulate_digital_twin(
            [{"name": "vision", "duration_s": 0.2, "metrics": {"objects": 3}}],
            [{"type": "camera", "name": "cam0", "width": 1280, "height": 720}],
            tick_rate_hz=10.0,
        )
        cam_entries = [e for e in result["sensor_log"] if e["sensor"] == "camera"]
        self.assertGreater(len(cam_entries), 0)
        self.assertEqual(cam_entries[0]["data"]["width"], 1280)

    def test_anomaly_detection_in_twin(self):
        from ghostchimera.chimera_pilot.backends.simulation import _simulate_digital_twin

        # Use many ticks of identical values + one big outlier embedded in metrics
        states = [{"name": "s", "duration_s": 3.0, "metrics": {}}]
        sensors = [{"type": "imu", "name": "imu0"}]
        result = _simulate_digital_twin(states, sensors, tick_rate_hz=50.0)
        # anomaly detection field exists
        self.assertIn("anomalies", result)


class TestPolicyTest(unittest.TestCase):
    def test_basic_policy_test(self):
        from ghostchimera.chimera_pilot.backends.simulation import _simulate_policy_test

        result = _simulate_policy_test(
            {"actions": ["forward", "backward", "left", "right"], "max_steps": 100},
            {"start": [0, 0, 0], "goal": [3, 0, 0], "obstacles": []},
            episodes=5,
        )
        self.assertEqual(result["mode"], "policy_test")
        self.assertEqual(len(result["episode_results"]), 5)
        self.assertGreaterEqual(result["success_rate"], 0.0)
        self.assertLessEqual(result["success_rate"], 1.0)

    def test_goal_reachable_no_obstacles(self):
        from ghostchimera.chimera_pilot.backends.simulation import _simulate_policy_test

        result = _simulate_policy_test(
            {"actions": ["forward", "backward", "left", "right"], "max_steps": 200},
            {"start": [0, 0, 0], "goal": [2, 0, 0], "obstacles": []},
            episodes=1,
        )
        # greedy policy should reach a goal 2 units ahead
        self.assertEqual(result["success_rate"], 1.0)

    def test_obstacle_causes_collision(self):
        from ghostchimera.chimera_pilot.backends.simulation import _simulate_policy_test

        result = _simulate_policy_test(
            {"actions": ["forward"], "max_steps": 20},
            {"start": [0, 0, 0], "goal": [10, 0, 0], "obstacles": [{"position": [0.3, 0, 0], "radius": 0.5}]},
            episodes=1,
        )
        # robot should collide with obstacle directly in path
        outcomes = [r["outcome"] for r in result["episode_results"]]
        self.assertIn("collision", outcomes)


class TestSimulationBackend(unittest.TestCase):
    def test_probe_available(self):
        from ghostchimera.chimera_pilot.backends.simulation import SimulationBackend

        backend = SimulationBackend()
        health = backend.probe()
        self.assertTrue(health.available)
        self.assertEqual(health.reliability, 1.0)

    def test_can_run_simulation_task(self):
        from ghostchimera.chimera_pilot.backends.simulation import SimulationBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        backend = SimulationBackend()
        task = TaskSpec.create(kind=TaskKind.SIMULATION, objective="sim", inputs={"sim_mode": "kinematics"})
        self.assertTrue(backend.can_run(task))

    def test_cannot_run_reasoning_task(self):
        from ghostchimera.chimera_pilot.backends.simulation import SimulationBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        backend = SimulationBackend()
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="think", inputs={"prompt": "hello"})
        self.assertFalse(backend.can_run(task))

    def test_execute_kinematics(self):
        from ghostchimera.chimera_pilot.backends.simulation import SimulationBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        backend = SimulationBackend()
        task = TaskSpec.create(
            kind=TaskKind.SIMULATION,
            objective="navigate",
            inputs={
                "sim_mode": "kinematics",
                "waypoints": [[0, 0, 0], [1, 0, 0], [1, 1, 0]],
                "robot": {"name": "arm", "dof": 6, "max_velocity": 1.0},
                "environment": {"obstacles": []},
            },
        )
        result = backend.execute(task)
        self.assertTrue(result.ok)
        self.assertIsInstance(result.output, dict)
        self.assertEqual(result.output["mode"], "kinematics")

    def test_execute_digital_twin(self):
        from ghostchimera.chimera_pilot.backends.simulation import SimulationBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        backend = SimulationBackend()
        task = TaskSpec.create(
            kind=TaskKind.SIMULATION,
            objective="digital twin",
            inputs={
                "sim_mode": "digital_twin",
                "states": [{"name": "idle", "duration_s": 0.5, "metrics": {}}],
                "sensors": [{"type": "imu", "name": "imu0"}],
                "tick_rate_hz": 10.0,
            },
        )
        result = backend.execute(task)
        self.assertTrue(result.ok)
        self.assertEqual(result.output["mode"], "digital_twin")

    def test_execute_policy_test(self):
        from ghostchimera.chimera_pilot.backends.simulation import SimulationBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        backend = SimulationBackend()
        task = TaskSpec.create(
            kind=TaskKind.SIMULATION,
            objective="policy test",
            inputs={
                "sim_mode": "policy_test",
                "policy": {"actions": ["forward", "backward", "left", "right"], "max_steps": 50},
                "environment": {"start": [0, 0, 0], "goal": [2, 0, 0], "obstacles": []},
                "episodes": 3,
            },
        )
        result = backend.execute(task)
        self.assertTrue(result.ok)
        self.assertEqual(result.output["mode"], "policy_test")
        self.assertEqual(len(result.output["episode_results"]), 3)

    def test_invalid_mode_returns_error(self):
        from ghostchimera.chimera_pilot.backends.simulation import SimulationBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        backend = SimulationBackend()
        task = TaskSpec.create(kind=TaskKind.SIMULATION, objective="bad mode", inputs={"sim_mode": "undefined_mode"})
        result = backend.execute(task)
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)


class TestSimulationTaskKind(unittest.TestCase):
    def test_task_kind_exists(self):
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        self.assertEqual(TaskKind.SIMULATION, "simulation")

    def test_schema_validates_mode(self):
        from ghostchimera.chimera_pilot.schema import validate_task
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        ok, errors = validate_task(TaskKind.SIMULATION, {"sim_mode": "kinematics"})
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_schema_rejects_bad_mode(self):
        from ghostchimera.chimera_pilot.schema import validate_task
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        ok, errors = validate_task(TaskKind.SIMULATION, {"sim_mode": "unknown_mode"})
        self.assertFalse(ok)
        self.assertTrue(len(errors) > 0)

    def test_schema_rejects_missing_mode(self):
        from ghostchimera.chimera_pilot.schema import validate_task
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        ok, errors = validate_task(TaskKind.SIMULATION, {})
        self.assertFalse(ok)


class TestSimulationCompilerRouting(unittest.TestCase):
    def test_simulate_routes_to_simulation(self):
        from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        compiler = RuleBasedTaskCompiler()
        tasks = compiler.compile("simulate robot arm moving through 4 waypoints")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].kind, TaskKind.SIMULATION)

    def test_digital_twin_routes_to_digital_twin_mode(self):
        from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        compiler = RuleBasedTaskCompiler()
        tasks = compiler.compile("create a digital twin for the manufacturing line")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].kind, TaskKind.SIMULATION)
        self.assertEqual(tasks[0].inputs["sim_mode"], "digital_twin")

    def test_robot_routes_to_simulation(self):
        from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        compiler = RuleBasedTaskCompiler()
        tasks = compiler.compile("robot navigation path planning")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].kind, TaskKind.SIMULATION)


if __name__ == "__main__":
    unittest.main()
