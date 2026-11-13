"""실행: python3 -m unittest discover -s output/week11_timer -v"""
import queue
import time
import unittest

from multifunction_timer import Counter, TimerGUI, TimerTasks


class FakeIO:
    def __init__(self):
        self.displays = []
        self.leds = []

    def write_str(self, value):
        self.displays.append(value)

    def write_led(self, value):
        self.leds.append(value)


class Tests(unittest.TestCase):
    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("Task 출력 대기 시간 초과")
            time.sleep(0.01)

    def test_counter_pause_resume_reset_and_timeout(self):
        counter = Counter(180, True)
        counter.command("left", 0)
        counter.command("left", 10)
        self.assertEqual(counter.text(), "2:50")
        counter.command("left", 100)
        self.assertTrue(counter.advance(270))
        self.assertEqual(counter.text(), "0:00")
        self.assertFalse(counter.advance(271))
        counter.command("left_w", 272)
        self.assertEqual(counter.text(), "3:00")
        self.assertFalse(counter.running)
        stopwatch = Counter(0)
        stopwatch.command("left", 0)
        stopwatch.advance(12.3)
        self.assertEqual(stopwatch.text(), "12:3")
        stopwatch.command("left_w", 13)
        self.assertEqual(stopwatch.text(), "00:0")
        self.assertFalse(stopwatch.running)

    def test_thread_message_flow_background_alarm_reset_and_shutdown(self):
        clock = [0.0]
        io = FakeIO()
        buttons = queue.Queue()
        tasks = TimerTasks(io, buttons, now=lambda: clock[0])
        tasks.start()
        try:
            self.wait_for(lambda: "12:00:00" in io.displays)
            buttons.put("right")
            self.wait_for(lambda: io.displays[-1] == "3:00")
            buttons.put("left")
            # 다음 표시까지 기다려 시작 명령 처리 확인.
            length = len(io.displays)
            self.wait_for(lambda: len(io.displays) > length)
            clock[0] = 1
            self.wait_for(lambda: io.displays[-1] == "2:59")
            buttons.put("right")
            self.wait_for(lambda: io.displays[-1] == "00:0")
            buttons.put("left")
            length = len(io.displays)
            self.wait_for(lambda: len(io.displays) > length)
            clock[0] = 181
            self.wait_for(lambda: io.displays[-1] == "180:0")
            time.sleep(0.15)  # 타이머 Task와 LED Task가 timeout을 전달하도록 대기.
            clock[0] = 182
            self.wait_for(lambda: "blank" in io.leds)
            buttons.put("right")
            self.wait_for(lambda: io.displays[-1] == "12:03:02")
            buttons.put("right")
            self.wait_for(lambda: io.displays[-1] == "0:00")
            buttons.put("left_w")
            self.wait_for(lambda: io.displays[-1] == "3:00" and io.leds[-1] == "green")
            clock[0] = 200
            time.sleep(0.15)
            self.assertEqual(io.displays[-1], "3:00")
            self.assertEqual(io.leds[-1], "green")
        finally:
            tasks.stop()
        self.assertEqual(len(tasks.threads), 6)
        self.assertTrue(all(not thread.is_alive() for thread in tasks.threads))

    def test_double_click_sends_only_reset_and_preserves_input_order(self):
        class Scheduler:
            def after(self, _ms, callback):
                self.callback = callback
                return "pending"

            def after_cancel(self, _identifier):
                self.callback = None

        gui = TimerGUI.__new__(TimerGUI)
        gui.root = Scheduler()
        gui.button_q = queue.Queue()
        gui.pending_click = None
        gui.left_click()
        gui.left_click()
        self.assertEqual(gui.button_q.get_nowait(), "left_w")
        self.assertTrue(gui.button_q.empty())
        gui.left_click()
        gui.right_click()
        self.assertEqual(gui.button_q.get_nowait(), "left")
        self.assertEqual(gui.button_q.get_nowait(), "right")
        self.assertTrue(gui.button_q.empty())


if __name__ == "__main__":
    unittest.main()
