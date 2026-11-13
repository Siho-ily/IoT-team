"""11주 다기능 타이머 — PDF 3~8쪽의 DFD / I/O / Task Description 구현.

개별 HCP 도면은 원문에 없으므로 DFD/TD/IO ID로 추적한다.
실행: python3 multifunction_timer.py (Python 3 + Tkinter, 외부 패키지 없음)
"""
import math
import queue
import threading
import time
import tkinter as tk


# IO-01/02: 작업 스레드의 출력은 큐에 넣고 Tk 메인 스레드에서 적용한다.
class TimerGUI:
    def __init__(self, root, button_q):
        self.root = root
        self.button_q = button_q
        self.outputs = queue.Queue()
        self.pending_click = None
        root.title("11주 실습 · 다기능 타이머")
        root.configure(bg="#20242c")
        panel = tk.Frame(root, bg="#20242c", padx=20, pady=25)
        panel.pack()
        self.led = tk.Label(panel, text="시계", width=10, height=3,
                            bg="red", fg="white", font=("Arial", 14, "bold"))
        self.led.pack(side="left", padx=(0, 20))
        self.display = tk.Label(panel, text="12:00:00", width=10,
                                font=("Courier", 48, "bold"), bg="#080b0c", fg="#65ff90")
        self.display.pack(side="left")
        # IO-03: 실제 Tk Button을 원형 배경 이미지로 표시한다.
        circle = tk.PhotoImage(width=90, height=90)
        for y in range(90):
            for x in range(90):
                if (x - 44.5) ** 2 + (y - 44.5) ** 2 <= 43 ** 2:
                    circle.put("#f6cf46", (x, y))
        self.circle = circle
        self.button = tk.Button(panel, image=circle, text="버튼", compound="center",
                                font=("Arial", 15, "bold"), borderwidth=0,
                                highlightthickness=0, bg="#20242c", activebackground="#20242c")
        self.button.pack(side="left", padx=(20, 0))
        self.button.bind("<Button-1>", self.left_click)
        self.button.bind("<Button-3>", self.right_click)
        self.button.bind("<Button-2>", self.right_click)  # macOS 보조 클릭
        self.button.bind("<Control-Button-1>", self.right_click)
        tk.Label(root, text="왼쪽 클릭: 시작 / 정지   ·   더블클릭: 리셋   ·   오른쪽 클릭: 모드 전환",
                 bg="#20242c", fg="white", pady=12).pack()
        self.poll_id = root.after(20, self.poll)

    def left_click(self, _event=None):
        # 구현 보완: 300ms 동안 단일 클릭을 보류해 left + left_w 중복을 방지.
        if self.pending_click is None:
            self.pending_click = self.root.after(300, self.single_click)
        else:
            self.root.after_cancel(self.pending_click)
            self.pending_click = None
            self.button_q.put("left_w")
        return "break"

    def single_click(self):
        self.pending_click = None
        self.button_q.put("left")

    def right_click(self, _event=None):
        # 먼저 누른 단일 클릭이 모드 전환 후의 Task로 전달되지 않게 한다.
        if self.pending_click is not None:
            self.root.after_cancel(self.pending_click)
            self.single_click()
        self.button_q.put("right")
        return "break"

    def write_str(self, text):
        self.outputs.put(("display", text))

    def write_led(self, state):
        self.outputs.put(("led", state))

    def poll(self):
        while True:
            try:
                kind, value = self.outputs.get_nowait()
            except queue.Empty:
                break
            if kind == "display":
                self.display.configure(text=value)
            else:
                labels = {"red": "시계", "green": "타이머", "blue": "스톱워치", "blank": ""}
                self.led.configure(bg="black" if value == "blank" else value, text=labels[value])
        self.poll_id = self.root.after(20, self.poll)

    def close(self):
        self.root.after_cancel(self.poll_id)
        if self.pending_click is not None:
            self.root.after_cancel(self.pending_click)
        self.root.destroy()


# 구현 보완: monotonic 경과시간으로 계산하여 스레드 지연의 누적 오차를 피한다.
class Counter:
    def __init__(self, initial, countdown=False):
        self.initial = initial
        self.countdown = countdown
        self.value = initial
        self.running = False
        self.last = None

    def advance(self, now):
        elapsed = 0 if self.last is None else now - self.last
        self.last = now
        if not self.running:
            return False
        self.value += -elapsed if self.countdown else elapsed
        if self.countdown and self.value <= 0:
            self.value = 0
            self.running = False
            return True
        return False

    def command(self, command, now):
        expired = self.advance(now)
        if command == "left_w":
            self.value = self.initial
            self.running = False  # 사용자 확인: 리셋 후 정지
        elif command == "left" and (not self.countdown or self.value > 0):
            self.running = not self.running
        return expired

    def text(self):
        if self.countdown:
            seconds = math.ceil(round(self.value, 6))
            return f"{seconds // 60}:{seconds % 60:02d}"
        tenths = int(round(self.value, 6) * 10)
        return f"{tenths // 10:02d}:{tenths % 10}"


class TimerTasks:
    def __init__(self, io, button_q, now=time.monotonic):
        self.io = io
        self.now = now
        # DFD-D01~D09: 원도면의 공유 문자열, 이벤트, 7개 메시지 큐.
        self.display_str = "12:00:00"
        self.dsp_event = threading.Event()
        self.button_q = button_q
        self.clock_q = queue.Queue()
        self.timer_q = queue.Queue()
        self.stp_watch_q = queue.Queue()
        self.led_q = queue.Queue()
        self.timeout_q = queue.Queue()
        self.channels = (self.clock_q, self.timer_q, self.stp_watch_q)
        # 구현 보완: 모드 전환 중 이전 Task의 화면 덮어쓰기와 이벤트 유실 방지.
        self.lock = threading.Lock()
        self.mode = 0
        self.stopping = threading.Event()
        self.threads = []
        self.started = now()

    def publish(self, mode, text):
        with self.lock:
            if self.mode == mode:
                self.display_str = text
                self.dsp_event.set()

    # DFD-T01 / TD-01: control_task, PDF 6/8쪽.
    def control_task(self):
        mode = 0
        self.select_mode(mode)
        while not self.stopping.is_set():
            command = self.button_q.get()
            if command is None:
                break
            if command == "right":
                mode = (mode + 1) % 3
                self.select_mode(mode)
            else:
                self.channels[mode].put(command)

    def select_mode(self, mode):
        with self.lock:
            self.mode = mode
            self.dsp_event.clear()
        for index, channel in enumerate(self.channels):
            channel.put("dsp_on" if index == mode else "dsp_off")
        self.led_q.put(("red", "green", "blue")[mode])

    # DFD-T02 / TD-02: 12:00:00 시작, 24시간제, 0.5초마다 표시.
    def clock_task(self):
        display_on = False
        while not self.stopping.is_set():
            try:
                command = self.clock_q.get(timeout=0.5)
            except queue.Empty:
                command = "tick"
            if command is None:
                break
            if command in ("dsp_on", "dsp_off"):
                display_on = command == "dsp_on"
            if display_on:
                seconds = (43200 + int(self.now() - self.started)) % 86400
                self.publish(0, f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}")

    # DFD-T03 / TD-03: 3분 타이머, PDF 4/8쪽.
    def timer_task(self):
        self.run_counter(1, self.timer_q, Counter(180, countdown=True))

    # DFD-T04 / TD-04: 0.1초 단위 초시계, PDF 5/8쪽.
    def stop_watch_task(self):
        self.run_counter(2, self.stp_watch_q, Counter(0))

    # 두 카운터의 공통 실행 기반. 업무별 초기값과 방향은 위 Task에서 지정.
    def run_counter(self, mode, channel, counter):
        display_on = False
        while not self.stopping.is_set():
            try:
                command = channel.get(timeout=0.1)
            except queue.Empty:
                command = "tick"
            if command is None:
                break
            expired = counter.command(command, self.now())
            if mode == 1:
                if expired:
                    self.timeout_q.put("timeout")
                if command == "left_w":
                    self.timeout_q.put("timeout_reset")
            if command in ("dsp_on", "dsp_off"):
                display_on = command == "dsp_on"
            if display_on:
                self.publish(mode, counter.text())

    # DFD-T05 / TD-05: 이벤트 발생 시 공유 문자열을 I/O로 전달.
    def display_task(self):
        while not self.stopping.is_set():
            self.dsp_event.wait()
            if self.stopping.is_set():
                break
            with self.lock:
                if self.dsp_event.is_set():
                    self.dsp_event.clear()
                    self.io.write_str(self.display_str)

    # DFD-T06 / TD-06: 현재 모드 색과 blank를 0.5초 간격으로 교대.
    def led_task(self):
        color, alarm, lit = "red", False, True
        next_flash, previous = 0, None
        while not self.stopping.is_set():
            for channel in (self.led_q, self.timeout_q):
                while True:
                    try:
                        command = channel.get_nowait()
                    except queue.Empty:
                        break
                    if command in ("red", "green", "blue"):
                        color = command
                    elif command == "timeout":
                        alarm, lit = True, True
                        next_flash = self.now() + 0.5
                    elif command == "timeout_reset":
                        alarm, lit = False, True
            if alarm and self.now() >= next_flash:
                lit = not lit
                next_flash = self.now() + 0.5
            state = color if lit else "blank"
            if state != previous:
                self.io.write_led(state)
                previous = state
            self.stopping.wait(0.02)

    # 구현 보완: Task당 Thread 1개, 대기 해제 및 정상 종료.
    def start(self):
        for task in (self.control_task, self.clock_task, self.timer_task,
                     self.stop_watch_task, self.display_task, self.led_task):
            thread = threading.Thread(target=task, name=task.__name__)
            self.threads.append(thread)
            thread.start()

    def stop(self):
        self.stopping.set()
        for channel in (self.button_q, *self.channels):
            channel.put(None)
        self.dsp_event.set()
        for thread in self.threads:
            thread.join()


# MAIN-01: 원문에 Main_Routine HCP 없음. DFD 규칙에 따른 실행 기반.
def main():
    root = tk.Tk()
    button_q = queue.Queue()
    gui = TimerGUI(root, button_q)
    tasks = TimerTasks(gui, button_q)

    def close():
        tasks.stop()
        gui.close()

    root.protocol("WM_DELETE_WINDOW", close)
    tasks.start()
    try:
        root.mainloop()
    finally:
        tasks.stop()


if __name__ == "__main__":
    main()
