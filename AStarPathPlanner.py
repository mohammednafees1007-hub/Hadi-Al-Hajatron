import heapq
import json
import os
import tkinter as tk
from tkinter import messagebox
import time

try:
    import serial
except ImportError:
    serial = None

try:
    from serial.tools import list_ports
except Exception:
    list_ports = None


MAP_INPUT_FILE = "latest_map.json"

# Fallback map used only if latest_map.json does not exist yet.
# 0 = free cell, 1 = obstacle
FALLBACK_GRID = [
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
]

# Default coordinates are (x, y), where x is column and y is row.
DEFAULT_START = (0, 0)
DEFAULT_GOAL = (3, 3)

# 0=North, 1=East, 2=South, 3=West
DEFAULT_START_DIRECTION = 1

SERIAL_PORT = None  # Example: "COM3". Leave None to auto-detect.
BAUD_RATE = 115200
SEND_TO_ARDUINO = True
CELL_SIZE = 70


def heading_name(direction):
    return ("North", "East", "South", "West")[direction]


def load_map_from_maptest():
    if not os.path.exists(MAP_INPUT_FILE):
        print(f"{MAP_INPUT_FILE} not found. Using fallback grid.")
        return {
            "grid": FALLBACK_GRID,
            "bot_position": {"x": DEFAULT_START[0], "y": DEFAULT_START[1]},
            "bot_heading": DEFAULT_START_DIRECTION,
        }

    with open(MAP_INPUT_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, list):
        data = {
            "grid": data,
            "bot_position": {"x": DEFAULT_START[0], "y": DEFAULT_START[1]},
            "bot_heading": DEFAULT_START_DIRECTION,
        }

    print(f"Loaded map from {MAP_INPUT_FILE}")
    return data


def find_serial_ports():
    if SERIAL_PORT:
        return [SERIAL_PORT]

    if list_ports is None:
        print("Error: pyserial list_ports is not available.")
        return []

    ports = list(list_ports.comports())
    arduino_keywords = (
        "arduino",
        "ch340",
        "usb serial",
        "usb-serial",
        "cp210",
        "silicon labs",
        "wch",
    )

    preferred_ports = []
    other_ports = []

    for port in ports:
        text = f"{port.device} {port.description} {port.manufacturer} {port.hwid}".lower()
        if any(keyword in text for keyword in arduino_keywords):
            preferred_ports.append(port.device)
        else:
            other_ports.append(port.device)

    return preferred_ports + other_ports


def connect_serial():
    if not SEND_TO_ARDUINO:
        return None

    if serial is None:
        print("Error: pyserial is not installed. Install it with: pip install pyserial")
        return None

    for port in find_serial_ports():
        try:
            connection = serial.Serial(port, BAUD_RATE, timeout=0.2)
            time.sleep(2)
            connection.reset_input_buffer()
            print(f"Connected to Arduino on {port}")
            return connection
        except serial.SerialException as e:
            print(f"Could not open {port}: {e}")

    print("No Arduino serial connection found. Commands were not sent.")
    return None


def validate_grid(grid):
    if not grid or not grid[0]:
        raise ValueError("GRID cannot be empty.")

    cols = len(grid[0])
    for row in grid:
        if len(row) != cols:
            raise ValueError("Every GRID row must have the same length.")
        for cell in row:
            if cell not in (0, 1):
                raise ValueError("GRID can only contain 0 and 1.")


def in_bounds(grid, cell):
    x, y = cell
    return 0 <= y < len(grid) and 0 <= x < len(grid[0])


def is_free(grid, cell):
    x, y = cell
    return grid[y][x] == 0


def neighbors(grid, cell):
    x, y = cell
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nxt = (x + dx, y + dy)
        if in_bounds(grid, nxt) and is_free(grid, nxt):
            yield nxt


def heuristic(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(grid, start, goal):
    validate_grid(grid)

    if not in_bounds(grid, start):
        raise ValueError(f"START {start} is outside the grid.")
    if not in_bounds(grid, goal):
        raise ValueError(f"GOAL {goal} is outside the grid.")
    if not is_free(grid, start):
        raise ValueError(f"START {start} is blocked.")
    if not is_free(grid, goal):
        raise ValueError(f"GOAL {goal} is blocked.")

    queue = [(0, start)]
    came_from = {start: None}
    cost_so_far = {start: 0}

    while queue:
        _, current = heapq.heappop(queue)

        if current == goal:
            path = []
            while current is not None:
                path.append(current)
                current = came_from[current]
            return path[::-1]

        for nxt in neighbors(grid, current):
            new_cost = cost_so_far[current] + 1
            if nxt not in cost_so_far or new_cost < cost_so_far[nxt]:
                cost_so_far[nxt] = new_cost
                priority = new_cost + heuristic(nxt, goal)
                heapq.heappush(queue, (priority, nxt))
                came_from[nxt] = current

    return None


def direction_between(current, nxt):
    cx, cy = current
    nx, ny = nxt

    if ny < cy:
        return 0
    if nx > cx:
        return 1
    if ny > cy:
        return 2
    if nx < cx:
        return 3

    raise ValueError("Path contains the same cell twice in a row.")


def path_to_commands(path, start_direction):
    direction = start_direction
    commands = []

    for current, nxt in zip(path, path[1:]):
        target_direction = direction_between(current, nxt)
        turn = (target_direction - direction) % 4

        if turn == 1:
            commands.append("R")
        elif turn == 2:
            commands.extend(["R", "R"])
        elif turn == 3:
            commands.append("L")

        commands.append("F")
        direction = target_direction

    return commands


def command_words(commands):
    names = {
        "F": "forward",
        "R": "right",
        "L": "left",
    }
    return [names[cmd] for cmd in commands]


def send_commands(connection, command_string):
    if connection is None:
        return

    connection.write(command_string.encode())
    print(f"Sent to Arduino: {command_string}")


class PlannerUi:
    def __init__(self, root):
        self.root = root
        self.root.title("A* Path Planner")

        self.grid = []
        self.start = DEFAULT_START
        self.goal = DEFAULT_GOAL
        self.bot_position = DEFAULT_START
        self.start_direction = DEFAULT_START_DIRECTION
        self.path = None
        self.commands = []
        self.command_string = ""

        self.status_var = tk.StringVar(value="Loading map...")
        self.info_var = tk.StringVar(value="")
        self.commands_var = tk.StringVar(value="")
        self.click_mode = tk.StringVar(value="goal")
        self.start_var = tk.StringVar(value=str(self.start))
        self.goal_var = tk.StringVar(value=str(self.goal))
        self.heading_var = tk.StringVar(value=heading_name(self.start_direction))

        self.canvas = tk.Canvas(root, width=400, height=400, bg="white")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.handle_canvas_click)

        tk.Label(root, textvariable=self.status_var, anchor="w").pack(fill="x")
        tk.Label(root, textvariable=self.info_var, anchor="w").pack(fill="x")
        tk.Label(root, textvariable=self.commands_var, anchor="w", justify="left").pack(fill="x")

        picker_row = tk.Frame(root)
        picker_row.pack(fill="x")

        tk.Radiobutton(picker_row, text="Click sets start", variable=self.click_mode, value="start").pack(
            side="left", padx=4, pady=4
        )
        tk.Radiobutton(picker_row, text="Click sets goal", variable=self.click_mode, value="goal").pack(
            side="left", padx=4, pady=4
        )
        tk.Label(picker_row, textvariable=self.start_var).pack(side="left", padx=8)
        tk.Label(picker_row, textvariable=self.goal_var).pack(side="left", padx=8)
        tk.Label(picker_row, text="Heading").pack(side="left", padx=(12, 2))
        tk.OptionMenu(
            picker_row,
            self.heading_var,
            "North",
            "East",
            "South",
            "West",
            command=self.handle_heading_change,
        ).pack(side="left", padx=4, pady=4)

        button_row = tk.Frame(root)
        button_row.pack(fill="x")

        tk.Button(button_row, text="Reload Map", command=self.reload).pack(side="left", padx=4, pady=4)
        tk.Button(button_row, text="Plan Path", command=self.plan_path).pack(side="left", padx=4, pady=4)
        tk.Button(button_row, text="Send to Arduino", command=self.send_to_arduino).pack(side="left", padx=4, pady=4)

        self.reload()

    def reload(self):
        try:
            map_data = load_map_from_maptest()
            self.grid = map_data["grid"]
            bot_position = map_data.get("bot_position", {})
            self.start = (
                int(bot_position.get("x", DEFAULT_START[0])),
                int(bot_position.get("y", DEFAULT_START[1])),
            )
            self.bot_position = self.start
            self.goal = self.default_goal_for_grid()
            self.start_direction = int(map_data.get("bot_heading", DEFAULT_START_DIRECTION))
            self.update_point_labels()
            self.heading_var.set(heading_name(self.start_direction))
            self.plan_path()
        except Exception as e:
            self.status_var.set(f"Error: {e}")
            messagebox.showerror("Planner Error", str(e))

    def default_goal_for_grid(self):
        if not self.grid:
            return DEFAULT_GOAL

        wanted = DEFAULT_GOAL
        if in_bounds(self.grid, wanted) and is_free(self.grid, wanted):
            return wanted

        for y in range(len(self.grid) - 1, -1, -1):
            for x in range(len(self.grid[0]) - 1, -1, -1):
                if is_free(self.grid, (x, y)):
                    return (x, y)

        return DEFAULT_GOAL

    def update_point_labels(self):
        self.start_var.set(f"Start: {self.start}")
        self.goal_var.set(f"Goal: {self.goal}")

    def handle_heading_change(self, selected_heading):
        self.start_direction = ("North", "East", "South", "West").index(selected_heading)
        self.plan_path()

    def plan_path(self):
        try:
            self.path = astar(self.grid, self.start, self.goal)

            if self.path is None:
                self.commands = []
                self.command_string = ""
                self.status_var.set("No path found.")
            else:
                self.commands = path_to_commands(self.path, self.start_direction)
                self.command_string = "".join(self.commands)
                self.status_var.set(f"A* path ready from {self.start} to {self.goal}.")

            self.print_plan()
            self.draw()
        except Exception as e:
            self.path = None
            self.commands = []
            self.command_string = ""
            self.status_var.set(f"Error: {e}")
            self.commands_var.set("No command array.")
            self.draw()

    def handle_canvas_click(self, event):
        if not self.grid:
            return

        cell = (event.x // CELL_SIZE, event.y // CELL_SIZE)
        if not in_bounds(self.grid, cell):
            return

        if not is_free(self.grid, cell):
            self.status_var.set(f"Cell {cell} is an obstacle. Choose a free cell.")
            return

        if self.click_mode.get() == "start":
            self.start = cell
        else:
            self.goal = cell

        self.update_point_labels()
        self.plan_path()

    def print_plan(self):
        print("Grid:")
        print(self.grid)
        print(f"Start: {self.start} | Goal: {self.goal} | Start heading: {heading_name(self.start_direction)}")

        if self.path is None:
            print("No path found.")
            self.info_var.set(
                f"Start: {self.start} | Goal: {self.goal} | Heading: {heading_name(self.start_direction)}"
            )
            self.commands_var.set("No command array.")
            return

        print(f"A* path: {self.path}")
        print(f"Command array: {command_words(self.commands)}")
        print(f"Arduino command string: {self.command_string}")

        self.info_var.set(
            f"Start: {self.start} | Goal: {self.goal} | Heading: {heading_name(self.start_direction)} | "
            f"Bot after mapping: {self.bot_position} | Path cells: {len(self.path)}"
        )
        self.commands_var.set(
            f"Command array: {command_words(self.commands)}\n"
            f"Arduino command string: {self.command_string}"
        )

    def draw(self):
        self.canvas.delete("all")

        if not self.grid:
            return

        rows = len(self.grid)
        cols = len(self.grid[0])
        width = cols * CELL_SIZE
        height = rows * CELL_SIZE
        self.canvas.config(width=width, height=height)

        path_cells = set(self.path or [])

        for y, row in enumerate(self.grid):
            for x, cell in enumerate(row):
                left = x * CELL_SIZE
                top = y * CELL_SIZE
                right = left + CELL_SIZE
                bottom = top + CELL_SIZE

                if cell == 1:
                    fill = "#e74c3c"
                elif (x, y) in path_cells:
                    fill = "#f7dc6f"
                else:
                    fill = "#2ecc71"

                self.canvas.create_rectangle(left, top, right, bottom, fill=fill, outline="white", width=2)
                self.canvas.create_text(
                    left + CELL_SIZE // 2,
                    top + CELL_SIZE // 2,
                    text=str(cell),
                    fill="#1f2933",
                    font=("Arial", 13, "bold"),
                )

        if self.path and len(self.path) > 1:
            points = []
            for x, y in self.path:
                points.extend((x * CELL_SIZE + CELL_SIZE // 2, y * CELL_SIZE + CELL_SIZE // 2))
            self.canvas.create_line(*points, fill="#1f618d", width=4, arrow=tk.LAST)

        self.draw_marker(self.start, "#145a32", "S")
        self.draw_marker(self.goal, "#922b21", "G")

    def draw_marker(self, cell, color, label):
        x, y = cell
        cx = x * CELL_SIZE + CELL_SIZE // 2
        cy = y * CELL_SIZE + CELL_SIZE // 2
        radius = 17
        self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=color, outline="")
        self.canvas.create_text(cx, cy, text=label, fill="white", font=("Arial", 12, "bold"))

    def send_to_arduino(self):
        if not self.command_string:
            messagebox.showwarning("No Commands", "No command string to send.")
            return

        connection = connect_serial()
        try:
            send_commands(connection, self.command_string)
            self.status_var.set(f"Sent to Arduino: {self.command_string}")
        finally:
            if connection is not None:
                connection.close()


def main():
    root = tk.Tk()
    PlannerUi(root)
    root.mainloop()


if __name__ == "__main__":
    main()
