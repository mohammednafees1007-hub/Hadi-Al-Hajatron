import tkinter as tk
import time
import heapq
import json

try:
    import serial
except ImportError:
    serial = None

# -------- SERIAL --------
SERIAL_PORT = None  # Set to 'COM3', 'COM4', etc. to force a specific port.
BAUD_RATE = 115200
STEP_STOP_DELAY_MS = 5000
IR_DISPLAY_DELAY_MS = 1000
MAP_OUTPUT_FILE = "latest_map.json"
ser = None


def find_serial_ports():
    if SERIAL_PORT:
        return [SERIAL_PORT]

    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
    except Exception as e:
        print("Error: could not list serial ports:", e)
        return None

    if not ports:
        print("Error: no serial ports found. Connect the Arduino and try again.")
        return None

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
    if serial is None:
        print("Error: pyserial is not installed. Install it with: pip install pyserial")
        return None

    ports = find_serial_ports()
    if not ports:
        return None

    for port in ports:
        try:
            connection = serial.Serial(port, BAUD_RATE, timeout=0.2)
            time.sleep(2)
            connection.reset_input_buffer()
            print(f"Connected to Arduino on {port}")
            return connection
        except serial.SerialException as e:
            if "Access is denied" in str(e) or "PermissionError" in str(e):
                print(f"Error: {port} is busy. Close Arduino Serial Monitor/Plotter and other running Python windows.")
            else:
                print(f"Error: could not open {port}: {e}")

    return None


# -------- GRID --------
ROWS, COLS = 4, 4
CELL_SIZE = 60

UNKNOWN, OBSTACLE, FREE = 0, 1, 2
grid = [[UNKNOWN for _ in range(COLS)] for _ in range(ROWS)]

# -------- ROBOT STATE --------
x, y = 0, 0
direction = 1  # 0=N, 1=E, 2=S, 3=W
waiting_for_step_done = False
pending_cmd = None
current_path = []
last_ir = None


def heading_name():
    return ("North", "East", "South", "West")[direction]


def format_cells(cells_list):
    if not cells_list:
        return "none"
    return ", ".join(f"({col},{row})" for row, col in cells_list)


def get_explored_cells():
    explored = []
    for r in range(ROWS):
        for c in range(COLS):
            if grid[r][c] != UNKNOWN:
                explored.append((r, c))
    return explored


def format_grid_as_list():
    return [[1 if cell == OBSTACLE else 0 for cell in row] for row in grid]


def print_final_grid():
    final_grid = format_grid_as_list()
    map_data = {
        "grid": final_grid,
        "bot_position": {"x": x, "y": y},
        "bot_heading": direction,
        "bot_heading_name": heading_name(),
    }
    print("Final grid list (1=obstacle, 0=free/unknown):")
    print(final_grid)
    print(f"Final bot position: ({x},{y})")
    print(f"Final bot heading: {heading_name()} ({direction})")
    with open(MAP_OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(map_data, file, indent=2)
    print(f"Saved final grid to {MAP_OUTPUT_FILE}")

# -------- GUI --------
cell_px = 60
root = tk.Tk()
root.title("Live FBE Mapping")

canvas = tk.Canvas(root, width=COLS*cell_px, height=ROWS*cell_px)
canvas.pack()

status_var = tk.StringVar(value="Starting...")
status_label = tk.Label(root, textvariable=status_var, anchor="w")
status_label.pack(fill="x")

heading_var = tk.StringVar(value=f"Heading: {heading_name()}")
heading_label = tk.Label(root, textvariable=heading_var, anchor="w")
heading_label.pack(fill="x")

ir_var = tk.StringVar(value="IR: F=- L=- R=-")
ir_label = tk.Label(root, textvariable=ir_var, anchor="w")
ir_label.pack(fill="x")

map_var = tk.StringVar(value="Explored: none | Frontiers: none")
map_label = tk.Label(root, textvariable=map_var, anchor="w", justify="left")
map_label.pack(fill="x")

cells = {}
for r in range(ROWS):
    for c in range(COLS):
        rect = canvas.create_rectangle(
            c*cell_px, r*cell_px,
            c*cell_px+cell_px, r*cell_px+cell_px,
            fill="#bdc3c7", outline="white"
        )
        cells[(r, c)] = rect

def draw():
    canvas.delete("robot")
    canvas.delete("path")
    canvas.delete("frontier")
    heading_var.set(f"Heading: {heading_name()} ({direction})")
    if last_ir is None:
        ir_var.set("IR: F=- L=- R=-")
    else:
        F, L, R = last_ir
        ir_var.set(f"IR: F={F} L={L} R={R} (0=obstacle, 1=free)")

    for r in range(ROWS):
        for c in range(COLS):
            val = grid[r][c]
            color = "#bdc3c7" if val == UNKNOWN else "#e74c3c" if val == OBSTACLE else "#2ecc71"
            canvas.itemconfig(cells[(r, c)], fill=color)

    for row, col in get_frontiers():
        canvas.create_rectangle(
            col*cell_px+6, row*cell_px+6,
            col*cell_px+cell_px-6, row*cell_px+cell_px-6,
            outline="#2980b9",
            width=3,
            tags="frontier"
        )
        canvas.create_text(
            col*cell_px + cell_px//2,
            row*cell_px + cell_px//2,
            text="F",
            fill="#2980b9",
            font=("Arial", 14, "bold"),
            tags="frontier"
        )

    if current_path:
        points = []
        for row, col in current_path:
            points.extend((col*cell_px + cell_px//2, row*cell_px + cell_px//2))

        if len(current_path) > 1:
            canvas.create_line(
                *points,
                fill="#f1c40f",
                width=4,
                arrow=tk.LAST,
                arrowshape=(10, 12, 5),
                tags="path"
            )

        for row, col in current_path[1:-1]:
            canvas.create_rectangle(
                col*cell_px+20, row*cell_px+20,
                col*cell_px+40, row*cell_px+40,
                outline="#f39c12",
                width=2,
                tags="path"
            )

        target_row, target_col = current_path[-1]
        canvas.create_oval(
            target_col*cell_px+21, target_row*cell_px+21,
            target_col*cell_px+39, target_row*cell_px+39,
            fill="#f39c12",
            outline="",
            tags="path"
        )

    canvas.create_oval(
        x*cell_px+15, y*cell_px+15,
        x*cell_px+45, y*cell_px+45,
        fill="#3498db", tags="robot"
    )

    center_x = x*cell_px + cell_px//2
    center_y = y*cell_px + cell_px//2
    arrow_offsets = {
        0: (0, -20),
        1: (20, 0),
        2: (0, 20),
        3: (-20, 0),
    }
    dx, dy = arrow_offsets[direction]
    canvas.create_line(
        center_x, center_y,
        center_x + dx, center_y + dy,
        fill="white",
        width=4,
        arrow=tk.LAST,
        arrowshape=(9, 11, 5),
        tags="robot"
    )

# -------- UPDATE GRID --------
def update_grid(F, L, R):
    global x, y, direction

    # Each direction: [Front offset, Left offset, Right offset]
    directions = {
        0: [(-1,0), (0,-1), (0,1)],   # Facing North
        1: [(0,1), (-1,0), (1,0)],    # Facing East
        2: [(1,0), (0,1), (0,-1)],    # Facing South
        3: [(0,-1), (1,0), (-1,0)]    # Facing West
    }

    moves = directions[direction]
    values = [F, L, R]

    for (dy, dx), val in zip(moves, values):
        ny, nx = y + dy, x + dx
        if 0 <= ny < ROWS and 0 <= nx < COLS:
            if val == 0:
                grid[ny][nx] = OBSTACLE
            elif grid[ny][nx] != OBSTACLE:
                grid[ny][nx] = FREE

# -------- FBE --------
def get_frontiers():
    frontiers = []
    for r in range(ROWS):
        for c in range(COLS):
            if grid[r][c] == UNKNOWN:
                for dr, dc in [(0,1),(0,-1),(1,0),(-1,0)]:
                    nr, nc = r+dr, c+dc
                    if 0 <= nr < ROWS and 0 <= nc < COLS:
                        if grid[nr][nc] == FREE:
                            frontiers.append((r, c))
                            break
    return frontiers

# -------- A* --------
def astar(start, goal):
    q = [(0, start)]
    came = {start: None}
    cost = {start: 0}

    while q:
        _, cur = heapq.heappop(q)

        if cur == goal:
            path = []
            while cur:
                path.append(cur)
                cur = came[cur]
            return path[::-1]

        for dr, dc in [(0,1),(0,-1),(1,0),(-1,0)]:
            nr, nc = cur[0]+dr, cur[1]+dc
            if 0 <= nr < ROWS and 0 <= nc < COLS:
                if grid[nr][nc] != OBSTACLE:
                    new_cost = cost[cur] + 1
                    if (nr, nc) not in cost or new_cost < cost[(nr, nc)]:
                        cost[(nr, nc)] = new_cost
                        priority = new_cost + abs(nr-goal[0]) + abs(nc-goal[1])
                        heapq.heappush(q, (priority, (nr, nc)))
                        came[(nr, nc)] = cur
    return None

# -------- DECIDE --------
def decide(next_cell):
    global x, y, direction

    ny, nx = next_cell

    if ny < y:   target = 0  # North
    elif nx > x: target = 1  # East
    elif ny > y: target = 2  # South
    else:        target = 3  # West

    diff = (target - direction) % 4

    if diff == 0:   # Already facing correct direction
        return 'F'
    elif diff == 1: # Need to turn right once
        direction = (direction + 1) % 4
        return 'R'
    elif diff == 3: # Need to turn left once
        direction = (direction - 1) % 4
        return 'L'
    else:           # diff == 2: U-turn, turn right (will complete next step)
        direction = (direction + 1) % 4
        return 'R'

# -------- MOVE FORWARD --------
def move_forward():
    global x, y, direction

    if direction == 0: y -= 1
    elif direction == 1: x += 1
    elif direction == 2: y += 1
    elif direction == 3: x -= 1


def read_step_done():
    if ser is None:
        return False

    try:
        for _ in range(20):
            line = ser.readline().decode(errors="replace").strip()
            if not line:
                return False

            print("Arduino:", line)
            if line.startswith("DONE:"):
                return True
            if "EMERGENCY STOP" in line:
                return True

            status_var.set(line)
    except Exception as e:
        print("Serial read error:", e)
        return False

    return False

# -------- REQUEST IR --------
def get_ir():
    if ser is None:
        return None

    try:
        print(f"Taking IR reading now at position ({x},{y}), heading {heading_name()}...")
        status_var.set(f"Taking IR reading at ({x},{y}) after 5 sec stop...")
        ser.write(b'I')
        for _ in range(12):
            line = ser.readline().decode(errors="replace").strip()
            if not line:
                continue

            try:
                values = [int(value.strip()) for value in line.split(',')]
            except ValueError:
                print(f"Skipping serial line: {line!r}")
                continue

            if len(values) == 3 and all(value in (0, 1) for value in values):
                print(f"IR reading: Front={values[0]} Left={values[1]} Right={values[2]} (0=obstacle, 1=free)")
                return values  # Returns [F, L, R]

            print(f"Skipping serial line: {line!r}")
    except Exception as e:
        print("Serial read error:", e)
        return None

    print("Serial read error: no valid IR data received")
    return None


def send_next_command(cmd, target):
    global waiting_for_step_done, pending_cmd

    if ser is not None:
        ser.write(cmd.encode())

    status_var.set(f"CMD: {cmd} | Pos: ({x},{y}) | Heading: {heading_name()} | Target: {target}")
    print(f"CMD: {cmd} | Pos: ({x},{y}) | Heading: {heading_name()} | Target: {target}")

    if cmd in ('F', 'R', 'L'):
        waiting_for_step_done = True
        pending_cmd = cmd

    draw()
    root.after(500, loop)

# -------- MAIN LOOP --------
def loop():
    global x, y, waiting_for_step_done, pending_cmd, current_path, last_ir

    try:
        # Step 1: Ask for IR — Arduino sends F,L,R
        if waiting_for_step_done:
            if read_step_done():
                if pending_cmd == 'F':
                    move_forward()
                    grid[y][x] = FREE

                waiting_for_step_done = False
                pending_cmd = None
                status_var.set(f"Step complete | Stopping for 5 sec | Pos: ({x},{y}) | Heading: {heading_name()}")
                print(f"Step complete. Robot stopped for 5 sec before next IR reading. Pos: ({x},{y}) Heading: {heading_name()}")
                draw()
                root.after(STEP_STOP_DELAY_MS, loop)
                return

            status_var.set(f"Waiting for {pending_cmd} to finish...")
            draw()
            root.after(200, loop)
            return

        readings = get_ir()
        if readings is None:
            status_var.set("Waiting for serial data...")
            draw()
            root.after(500, loop)
            return

        F, L, R = readings
        last_ir = readings

        # Step 2: Update map
        grid[y][x] = FREE
        update_grid(F, L, R)

        # Step 3: FBE — find frontiers
        frontiers = get_frontiers()
        explored = get_explored_cells()

        print(f"Explored/known cells: {format_cells(explored)}")
        print(f"Frontier cells: {format_cells(frontiers)}")
        map_var.set(f"Explored: {format_cells(explored)} | Frontiers: {format_cells(frontiers)}")

        if not frontiers:
            if ser is not None:
                ser.write(b'S')
            current_path = []
            status_var.set("Mapping complete")
            print("DONE — Mapping complete!")
            print_final_grid()
            draw()
            return

        # Step 4: Choose nearest frontier (Manhattan distance)
        target = min(frontiers, key=lambda f: abs(f[0]-y) + abs(f[1]-x))

        # Step 5: Plan path with A*
        path = astar((y, x), target)
        current_path = path or []

        if path and len(path) > 1:
            cmd = decide(path[1])
        else:
            cmd = 'S'

        # Step 6: Safety — only block forward movement, allow turns
        if F == 0 and cmd == 'F':
            cmd = 'S'

        status_var.set(
            f"IR: F={F} L={L} R={R} | Explored: {len(explored)} | "
            f"Frontiers: {len(frontiers)} | Moving in 1 sec..."
        )
        print(f"Target frontier: ({target[1]},{target[0]}) | Path: {format_cells(path or [])}")
        print("Waiting 1 sec after IR reading before moving...")
        draw()
        root.after(IR_DISPLAY_DELAY_MS, send_next_command, cmd, target)
        return

    except Exception as e:
        status_var.set(f"Error: {e}")
        print("Error:", e)

    root.after(500, loop)

# -------- START --------
ser = connect_serial()
draw()
loop()
root.mainloop()
