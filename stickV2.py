import sys, os, json, math, random, time, atexit
import pyautogui
import win32gui
from PyQt5 import QtWidgets, QtCore, QtGui

# -------------------------
# CONFIG
# -------------------------
MEM_FILE = "stickman_memory.json"
SAVE_INTERVAL = 300.0          # 5 minutes
VISION_RADIUS = 200
ARM_REACH = 120               # shorter arm reach
ARM_TIP_RADIUS = 10
HITBOX_W, HITBOX_H = 100, 150

# -------------------------
# MEMORY UTIL
# -------------------------
def load_memory():
    if getattr(sys, 'frozen', False):
        mem_path = os.path.join(os.path.dirname(sys.executable), MEM_FILE)
    else:
        mem_path = MEM_FILE

    default_mem = {
        "clicks": 0,
        "windows_seen": {},
        "websites_seen": {},
        "favorites": [],
        "fav_sites": [],
        "last_mood": "neutral",
        "personality": {
            "curiosity": 0.5,
            "activity": 0.5,
            "focus": 0.5
        },
        "thoughts": [],
        "last_saved": None,
        "_fav_updated": 0,
        "_fav_sites_updated": 0
    }

    mem = {}
    if os.path.exists(mem_path):
        try:
            with open(mem_path, "r", encoding="utf-8") as f:
                mem = json.load(f)
        except Exception as e:
            print("⚠️ Failed to load memory, resetting:", e)
            mem = {}

    # Ensure all default keys exist
    for k, v in default_mem.items():
        if k not in mem:
            mem[k] = v
        elif isinstance(v, dict) and isinstance(mem[k], dict):
            for nk, nv in v.items():
                if nk not in mem[k]:
                    mem[k][nk] = nv

    return mem

def save_memory(mem):
    if getattr(sys, 'frozen', False):
        mem_path = os.path.join(os.path.dirname(sys.executable), MEM_FILE)
    else:
        mem_path = MEM_FILE
    mem["last_saved"] = time.time()
    try:
        with open(mem_path, "w", encoding="utf-8") as f:
            json.dump(mem, f, indent=2)
    except Exception as e:
        print("Failed to save memory:", e)

MEM = load_memory()
atexit.register(lambda: save_memory(MEM))

# -------------------------
# WINDOW UTIL
# -------------------------
def get_window_rect_under_point(x, y):
    try:
        hwnd = win32gui.WindowFromPoint((x, y))
        if hwnd and win32gui.IsWindowVisible(hwnd):
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            cls = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd) or "<no title>"
            if cls not in ["Progman", "WorkerW"] and (r-l) > 50 and (b-t) > 50:
                return (l, t, r, b, title, hwnd)
    except Exception:
        pass
    return None

def rotate_point(px, py, ox, oy, angle_deg):
    a = math.radians(angle_deg)
    s, c = math.sin(a), math.cos(a)
    dx, dy = px - ox, py - oy
    return ox + c*dx - s*dy, oy + s*dx + c*dy

# -------------------------
# STICKMAN CLASS
# -------------------------
class SmartStickman(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        # visuals
        self.color = QtGui.QColor("black")
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.resize(150, 250)

        # physics
        self.vx = random.choice([-5,5])
        self.vy = 0
        self.ay = 0.8

        # AI state
        self.action = 'idle'
        self.frame = 0
        self.last_action_change = 0.0
        self.mood = MEM.get("last_mood", "neutral")

        # dragging
        self.dragging = False
        self.offset_x = 0
        self.offset_y = 0

        # screen and positioning
        screen = QtWidgets.QApplication.desktop().screenGeometry()
        self.screen_left = 0
        self.screen_top = 0
        self.screen_right = screen.width()
        self.screen_bottom = screen.height()
        self.x = screen.width()//2 - self.width()//2
        self.y = screen.height()//2 - self.height()//2
        self.move(self.x, self.y)

        # active window (for clipping) and title tracking
        self.active_rect = (self.screen_left,self.screen_top,self.screen_right,self.screen_bottom)
        self.active_title = "<desktop>"

        # arm tip record
        self.arm_tip = (0,0)
        self.right_arm_angle = 25

        # timers
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_stickman)
        self.timer.start(30)

        self._last_mem_save = time.time()
        self.show()

    # -------------------------
    # Painting
    # -------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(self.color, 6, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
        painter.setPen(pen)

        head_cx, head_cy = 75, 20
        body_top = (75, 32)
        body_bottom = (75, 100)

        painter.drawEllipse(QtCore.QPointF(head_cx, head_cy), 12, 12)
        painter.drawLine(*body_top, *body_bottom)

        t = self.frame / 12.0
        speed_factor = max(1, abs(self.vx))
        if self.action == 'walk':
            swing = 15 * math.sin(t) * speed_factor / 4
        elif self.action == 'wave':
            swing = 0
        else:
            swing = 3 * math.sin(t/2)

        # legs
        leg_length = 50
        left_leg_end = rotate_point(body_bottom[0], body_bottom[1]+leg_length, *body_bottom, -15 + swing)
        right_leg_end = rotate_point(body_bottom[0], body_bottom[1]+leg_length, *body_bottom, 15 - swing)
        painter.drawLine(*body_bottom, *left_leg_end)
        painter.drawLine(*body_bottom, *right_leg_end)

        # arms
        arm_length = 40
        cursor_pos = QtGui.QCursor.pos()
        shoulder_world_x = self.x + body_top[0]
        shoulder_world_y = self.y + body_top[1] + 10
        dx = cursor_pos.x() - shoulder_world_x
        dy = cursor_pos.y() - shoulder_world_y
        dist = math.hypot(dx, dy)

        if dist < ARM_REACH and self.mood in ["curious","happy"]:
            angle = math.degrees(math.atan2(dy, dx))
            self.right_arm_angle = angle - 90
        elif self.action == 'wave':
            self.right_arm_angle = max(0, 40 * math.sin(t))
        else:
            self.right_arm_angle = 25 - swing/2

        left_arm_angle = -25 + swing/2
        left_arm_end = rotate_point(body_top[0], body_top[1]+10+arm_length, *body_top, left_arm_angle)
        right_arm_end = rotate_point(body_top[0], body_top[1]+10+arm_length, *body_top, self.right_arm_angle)

        painter.drawLine(body_top[0], body_top[1]+10, *left_arm_end)
        painter.drawLine(body_top[0], body_top[1]+10, *right_arm_end)

        self.arm_tip = (self.x + right_arm_end[0], self.y + right_arm_end[1])

    # -------------------------
    # Update
    # -------------------------
    def update_stickman(self):
        self.frame += 1
        now = time.time()

        # Track active window under center
        center_x = self.x + self.width()//2
        center_y = self.y + self.height()//2
        rect_info = get_window_rect_under_point(center_x, center_y)
        if rect_info:
            l,t,r,b,title,hwnd = rect_info
            self.active_rect = (l,t,r,b)
            if title:
                MEM["windows_seen"].setdefault(title,0)
                MEM["windows_seen"][title]+=1
                self.active_title = title

        if now - (MEM.get("_fav_updated", 0) or 0) > 30:
            sorted_titles = sorted(MEM.get("windows_seen", {}).items(), key=lambda kv: kv[1], reverse=True)
            MEM["favorites"] = [t for (t, _) in sorted_titles[:3]]
            MEM["_fav_updated"] = now

        # AI Cursor interaction
        cursor_pos = QtGui.QCursor.pos()
        dx = cursor_pos.x() - (self.x + 75)
        dy = cursor_pos.y() - (self.y + 32)
        cursor_dist = math.hypot(dx, dy)

        curious_chance = MEM.get("personality", {}).get("curiosity", 0.5)
        curious = random.random() < curious_chance

        if cursor_dist < VISION_RADIUS and curious:
            if random.random() < 0.01:
                arm_tip_x, arm_tip_y = self.arm_tip
                dist_tip_to_cursor = math.hypot(cursor_pos.x() - arm_tip_x, cursor_pos.y() - arm_tip_y)
                if dist_tip_to_cursor < ARM_TIP_RADIUS:
                    pyautogui.click(button='right')
                    MEM["clicks"] += 1
                if cursor_dist < ARM_REACH:
                    pyautogui.click(button='left')
                    MEM["clicks"] += 1
                self.action = 'tap_left'
                self.vx = 0
            else:
                self.action = 'wave'
                self.vx = 0
        else:
            # Movement & gravity with window standing support
            if not self.dragging and self.active_rect:
                l,t,r,b = self.active_rect
                hit_left = self.x + 75 - HITBOX_W//2
                hit_right = hit_left + HITBOX_W
                hit_top = self.y + 32
                hit_bottom = hit_top + HITBOX_H

                # gravity
                self.vy += self.ay
                self.y += self.vy

                if hit_bottom > b:
                    self.y -= (hit_bottom - b)
                    self.vy = 0
                    if self.action=='walk' and random.random()<0.01:
                        self.vy=-12
                if hit_top < t:
                    self.y += (t - hit_top)
                    self.vy = 0

                # horizontal movement
                self.x += self.vx
                hit_left = self.x + 75 - HITBOX_W//2
                hit_right = hit_left + HITBOX_W
                if hit_left < l:
                    self.x += (l-hit_left)
                    self.vx*=-1
                if hit_right > r:
                    self.x -= (hit_right - r)
                    self.vx*=-1

            # AI decision
            if now - self.last_action_change > 1.2:
                favs = MEM.get("favorites",[])
                explore_prob = 0.2 + 0.1 * len(favs)
                if random.random()<explore_prob and favs:
                    self.action='walk'
                    self.vx=random.choice([-6,-5,5,6])
                else:
                    if random.random()<0.3:
                        self.action='walk'
                        self.vx=random.choice([-6,-5,5,6])
                    else:
                        self.action='idle'
                        self.vx=0
                self.last_action_change = now

        # keep on-screen
        self.x = max(0,min(self.x,self.screen_right - self.width()))
        self.y = max(0,min(self.y,self.screen_bottom - self.height()))
        self.move(int(self.x),int(self.y))
        self.update()

        # save memory periodically
        if time.time() - self._last_mem_save > SAVE_INTERVAL:
            save_memory(MEM)
            self._last_mem_save = time.time()

    # -------------------------
    # Mouse dragging
    # -------------------------
    def mousePressEvent(self,event):
        if event.button() == QtCore.Qt.LeftButton:
            self.dragging = True
            cursor = QtGui.QCursor.pos()
            self.offset_x = cursor.x()-self.x
            self.offset_y = cursor.y()-self.y
            self.vx=0
            self.vy=0

    def mouseMoveEvent(self,event):
        if self.dragging:
            cursor = QtGui.QCursor.pos()
            self.x = cursor.x()-self.offset_x
            self.y = cursor.y()-self.offset_y
            rect_info = get_window_rect_under_point(cursor.x(), cursor.y())
            if rect_info:
                l,t,r,b,title,hwnd = rect_info
                self.active_rect = (l,t,r,b)
                if title:
                    MEM["windows_seen"].setdefault(title,0)
                    MEM["windows_seen"][title]+=1

    def mouseReleaseEvent(self,event):
        if event.button() == QtCore.Qt.LeftButton:
            self.dragging=False
            self.vx=random.choice([-5,5])

# -------------------------
# RUN
# -------------------------
if __name__=="__main__":
    app=QtWidgets.QApplication(sys.argv)
    stick=SmartStickman()
    app.aboutToQuit.connect(lambda: save_memory(MEM))
    sys.exit(app.exec_())
