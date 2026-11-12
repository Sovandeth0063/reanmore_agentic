import threading
import unittest
from datetime import datetime, timedelta, timezone

from agent.memory import SessionStore


class MemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.store.create("session-1")

    def tearDown(self) -> None:
        self.store.close()

    def test_state_turns_tools_and_delete(self) -> None:
        self.store.update(
            "session-1", chosen_exercise="A1", current_step=1, attempts=2,
            last_answer="15", last_confidence=0.95, placement_confirmed=True,
        )
        self.store.append_turn("session-1", "student", "check my answer")
        self.store.append_tool_call("session-1", "calculator.check_answer")
        state = self.store.get("session-1")
        self.assertEqual(state.chosen_exercise, "A1")
        self.assertEqual(state.attempts, 2)
        self.assertTrue(state.placement_confirmed)
        self.assertIn("exercise=A1", self.store.state_block("session-1"))
        self.assertIn("placement=confirmed", self.store.state_block("session-1"))
        self.assertEqual(len(state.turns), 1)
        self.store.delete("session-1")
        self.assertIsNone(self.store.get("session-1"))

    def test_placement_confirmed_defaults_false_and_updates(self) -> None:
        state = self.store.get("session-1")
        self.assertFalse(state.placement_confirmed)
        self.assertIn("placement=pending", self.store.state_block("session-1"))

        updated = self.store.update("session-1", placement_confirmed=True)

        self.assertTrue(updated.placement_confirmed)
        self.assertTrue(self.store.get("session-1").placement_confirmed)

    def test_mutating_calls_are_thread_safe(self) -> None:
        def worker(number: int) -> None:
            for _ in range(5):
                self.store.append_tool_call(
                    "session-1", f"test.tool.{number}"
                )

        threads = [
            threading.Thread(target=worker, args=(number,))
            for number in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        count = self.store.connection.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE session_id = ?",
            ("session-1",),
        ).fetchone()[0]
        self.assertEqual(count, 20)


class RetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.store.create("old-session")
        self.store.create("new-session")
        self.store.append_turn("old-session", "student", "check my answer")
        self.store.append_turn("new-session", "student", "start A1")
        self.store.append_tool_call("old-session", "vision.parse_worksheet")
        self.store.append_tool_call("new-session", "vision.parse_worksheet")

    def tearDown(self) -> None:
        self.store.close()

    def backdate(self, session_id: str, hours: int) -> None:
        stamp = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        self.store.connection.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (stamp, session_id),
        )
        self.store.connection.commit()

    def rows(self, table: str, session_id: str) -> int:
        return self.store.connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = ?", (session_id,)
        ).fetchone()[0]

    def test_prune_removes_only_old_sessions(self) -> None:
        self.backdate("old-session", hours=48)

        deleted = self.store.prune(max_age_hours=24)

        self.assertEqual(deleted, 1)
        self.assertIsNone(self.store.get("old-session"))
        self.assertIsNotNone(self.store.get("new-session"))
        for table in ("turns", "tool_calls"):
            with self.subTest(table=table):
                self.assertEqual(self.rows(table, "old-session"), 0)
                self.assertEqual(self.rows(table, "new-session"), 1)

    def test_prune_keeps_sessions_inside_the_window(self) -> None:
        self.backdate("old-session", hours=2)

        self.assertEqual(self.store.prune(max_age_hours=24), 0)
        self.assertIsNotNone(self.store.get("old-session"))

    def test_prune_returns_zero_when_empty(self) -> None:
        store = SessionStore("sqlite:///:memory:")
        try:
            self.assertEqual(store.prune(), 0)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
