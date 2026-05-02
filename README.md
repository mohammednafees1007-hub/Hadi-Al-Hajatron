# MapTestCode

MapTestCode is a small robotics mapping project that connects a Python desktop GUI with an Arduino motor controller. The robot explores a grid, reads three IR sensors, marks free and blocked cells, saves the discovered map, and can then plan an A* path through that map.

The project has three main parts:

- `MasterMotorControl_IR.ino`: Arduino motor, encoder, command queue, and IR sensor firmware.
- `MapTest_1.py`: live Tkinter mapping GUI that talks to the Arduino and saves `latest_map.json`.
- `AStarPathPlanner.py`: Tkinter A* planner that loads `latest_map.json`, lets you select start/goal cells, builds movement commands, and can send them to the Arduino.

There is also `sim_3.html`, a browser-based mapping algorithm simulation/demo.

## Project Files

| File | Purpose |
| --- | --- |
| `MasterMotorControl_IR.ino` | Arduino firmware for motor movement, encoder counting, 90 degree turns, IR readings, and serial commands. |
| `MapTest_1.py` | Live frontier-based exploration GUI for a 4x4 grid. Reads IR data from Arduino and updates the map. |
| `AStarPathPlanner.py` | Loads the saved map and calculates a shortest path using A*. Converts the path into `F`, `L`, and `R` Arduino commands. |
| `latest_map.json` | Saved map output from the mapping GUI. It stores the grid, robot position, and robot heading. |
| `sim_3.html` | Standalone HTML simulation for visualizing the mapping algorithm in a browser. |
| `.gitignore` | Keeps Python cache files out of Git. |

## Hardware Overview

The Arduino sketch expects:

- Two DC motors controlled by PWM pins.
- Left and right wheel encoders.
- Three IR obstacle sensors: front, left, and right.
- USB serial connection between the computer and Arduino.

### Arduino Pin Mapping

Motor driver pins:

| Signal | Arduino Pin |
| --- | --- |
| `L_RPWM` | 5 |
| `L_LPWM` | 6 |
| `R_RPWM` | 10 |
| `R_LPWM` | 11 |

Encoder pins:

| Signal | Arduino Pin |
| --- | --- |
| `ENC_L_A` | 2 |
| `ENC_L_B` | 4 |
| `ENC_R_A` | 3 |
| `ENC_R_B` | 7 |

IR sensor pins:

| Sensor | Arduino Pin |
| --- | --- |
| Front IR | 9 |
| Left IR | 8 |
| Right IR | 12 |

The sketch is configured for digital IR sensors by default:

```cpp
const bool IR_USE_ANALOG = false;
const bool IR_OBSTACLE_IS_LOW = true;
```

With this setting, each IR sensor returns:

- `0` = obstacle detected
- `1` = free space

## Arduino Command Protocol

The Python scripts communicate with the Arduino using serial at `115200` baud.

| Command | Meaning |
| --- | --- |
| `F` | Move forward by `FORWARD_DISTANCE_CM`. |
| `R` | Turn right 90 degrees. |
| `L` | Turn left 90 degrees. |
| `S` | Emergency stop and clear command queue. |
| `I` | Return IR readings as `front,left,right`. |

The Arduino accepts both uppercase and lowercase commands. It can also queue combined command strings such as:

```text
FRFFL
```

The Arduino prints movement completion messages like:

```text
DONE: Forward 60.00 cm
DONE: Right 90 degree
DONE: Left 90 degree
```

The Python mapping loop waits for these `DONE:` messages before updating the robot state and requesting the next IR reading.

## Motor Calibration

The Arduino sketch uses calibrated encoder counts for movement:

```cpp
const float FORWARD_DISTANCE_CM = 60.0;
const long LEFT_TARGET_60CM  = 2232;
const long RIGHT_TARGET_60CM = 2175;
const long LEFT_TURN_90  = 734;
const long RIGHT_TURN_90 = 719;
```

Only change `FORWARD_DISTANCE_CM` if you want a different forward step distance. The left/right calibration constants should stay matched to the real robot hardware unless you recalibrate the motors and encoders.

## Python Requirements

The Python scripts use:

- Python 3
- Tkinter
- pyserial

Install pyserial if it is missing:

```powershell
pip install pyserial
```

Tkinter is included with most standard Python installations on Windows.

## Setup

1. Open `MasterMotorControl_IR.ino` in the Arduino IDE.
2. Select the correct Arduino board and COM port.
3. Upload the sketch to the Arduino.
4. Close Arduino Serial Monitor and Serial Plotter before running the Python scripts. Only one program can use the COM port at a time.
5. Keep the Arduino connected by USB.

The Python code auto-detects likely Arduino serial ports. If auto-detection does not choose the correct port, edit this line in the Python file you are running:

```python
SERIAL_PORT = None
```

For example:

```python
SERIAL_PORT = "COM3"
```

## Run The Live Mapping GUI

Run:

```powershell
cd "C:\Users\moham\OneDrive\Desktop\MapTestCode"
python MapTest_1.py
```

What it does:

1. Connects to the Arduino over serial.
2. Shows a 4x4 grid in a Tkinter window.
3. Requests IR readings using the `I` command.
4. Marks cells as unknown, free, or obstacle.
5. Finds frontier cells next to explored free cells.
6. Chooses the nearest frontier.
7. Uses A* to plan a step toward that frontier.
8. Sends one movement command at a time.
9. Waits for Arduino `DONE:` before updating the robot position.
10. Stops when no frontiers remain.
11. Saves the final map to `latest_map.json`.

Grid colors:

| Color | Meaning |
| --- | --- |
| Gray | Unknown cell |
| Green | Free cell |
| Red | Obstacle cell |
| Blue circle | Robot |
| Blue `F` outline | Frontier cell |
| Yellow line | Current planned path |

The robot heading values are:

| Value | Heading |
| --- | --- |
| 0 | North |
| 1 | East |
| 2 | South |
| 3 | West |

## Saved Map Format

`latest_map.json` stores the final map in this shape:

```json
{
  "grid": [
    [0, 0, 1, 0],
    [0, 1, 0, 0],
    [0, 0, 0, 0],
    [1, 0, 0, 1]
  ],
  "bot_position": {
    "x": 3,
    "y": 2
  },
  "bot_heading": 2,
  "bot_heading_name": "South"
}
```

Grid values:

- `0` = free or unknown in the exported planner map
- `1` = obstacle

Coordinates use `(x, y)`:

- `x` = column
- `y` = row
- `(0, 0)` = top-left cell

## Run The A* Path Planner

After `latest_map.json` exists, run:

```powershell
python AStarPathPlanner.py
```

The planner:

1. Loads `latest_map.json`.
2. Uses the robot position from the saved map as the default start.
3. Uses `(3, 3)` as the default goal if it is free.
4. If `(3, 3)` is blocked, chooses the last free cell scanning from bottom-right.
5. Lets you click cells to set a new start or goal.
6. Lets you choose the starting heading.
7. Calculates an A* shortest path.
8. Converts the path into Arduino commands.
9. Can send the command string to the Arduino.

Example command output:

```text
Command array: ['forward', 'right', 'forward']
Arduino command string: FRF
```

Planner grid colors:

| Color | Meaning |
| --- | --- |
| Green | Free cell |
| Red | Obstacle cell |
| Yellow | Planned path |
| `S` marker | Start |
| `G` marker | Goal |

## Run The Browser Simulation

Open this file in a browser:

```text
sim_3.html
```

It is a standalone visual simulation of the mapping algorithm and does not require Python, Arduino, or a server.

## Recommended Workflow

Use this order for the full robot workflow:

1. Upload `MasterMotorControl_IR.ino` to the Arduino.
2. Close Arduino Serial Monitor.
3. Run `python MapTest_1.py`.
4. Let the robot explore until the GUI says mapping is complete.
5. Confirm `latest_map.json` was saved.
6. Run `python AStarPathPlanner.py`.
7. Select or confirm the start, goal, and heading.
8. Review the command string.
9. Click `Send to Arduino` if you want the robot to execute the planned route.

## Troubleshooting

### `pyserial is not installed`

Install it:

```powershell
pip install pyserial
```

### No serial ports found

Check that:

- The Arduino is connected by USB.
- The correct USB cable supports data, not only charging.
- The Arduino driver is installed.
- The board appears in Device Manager.

### Access is denied on COM port

Close anything else using the Arduino serial port:

- Arduino Serial Monitor
- Arduino Serial Plotter
- Another Python window
- Another terminal session

Then run the Python script again.

### Robot does not move correctly

Check:

- Motor wiring direction.
- Encoder wiring.
- Battery voltage.
- Motor driver power.
- Encoder count calibration constants.
- Whether the robot is slipping on the floor.

### IR readings look reversed

If obstacles and free space are inverted, check this Arduino setting:

```cpp
const bool IR_OBSTACLE_IS_LOW = true;
```

Change it only if your sensor outputs the opposite logic.

## GitHub Repository

This project is stored in Git and pushed to:

```text
https://github.com/mohammednafees1007-hub/MapTestCode
```

Useful Git commands:

```powershell
git status
git add README.md
git commit -m "Add project documentation"
git push
```
