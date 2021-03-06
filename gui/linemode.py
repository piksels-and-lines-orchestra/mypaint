# This file is part of MyPaint.
# Copyright (C) 2012 by Richard Jones
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.


import stock
import gtk
from gtk import gdk
from gettext import gettext as _
import gobject
import math

# internal name, displayed name, constant, minimum, default, maximum, tooltip
line_mode_settings_list = [
    ['entry_pressure', _('Entrance Pressure'), False, 0.0001, 0.3, 1.0, _("Stroke entrance pressure for line tools")],
    ['midpoint_pressure', _('Midpoint Pressure'), False, 0.0001, 1.0, 1.0, _("Mid-Stroke pressure for line tools")],
    ['exit_pressure', _('Exit Pressure'), False, 0.0001, 0.3, 1.0, _("Stroke exit pressure for line tools")],
    ['line_head', _('Head'), False, 0.0001, 0.25, 1.0, _("Stroke lead-in end")],
    ['line_tail', _('Tail'), False, 0.0001, 0.75, 1.0, _("Stroke trail-off beginning")],
    ]

class LineModeSettings:
    pass

line_mode_settings = []

line_mode_settings_dict = {}
for line_list in line_mode_settings_list:
    l = LineModeSettings()
    l.cname, l.name, l.constant, l.min, l.default, l.max, l.tooltip = line_list
    l.index = len(line_mode_settings)
    line_mode_settings.append(l)
    line_mode_settings_dict[l.cname] = l


class LineMode:

    line_mode = "FreehandMode"
    last_line_data = None
    idle_srcid = None

###
### Toolbar Dialog
###
    def __init__(self, app):
        self.app = app
        self._init_actions()

    def _init_actions(self):
        self.action_group = gtk.ActionGroup('LineModeActions')
        ag = self.action_group
        self.app.add_action_group(ag)
        toggle_actions = [
            # name, stock id, label,
            #   accel, tooltip,
            #   callback, default state
            ('FreehandMode', stock.LINE_MODE_FREEHAND, _("Freehand"),
                None, _("Freehand is the default painting mode"),
                self.line_mode_cb, True),
            ('StraightMode', stock.LINE_MODE_STRAIGHT, _("Straight/Curved Lines"),
                None, _("Draw straight or curved lines.\n\
Constrain angle by holding the Control key.\n\
Add curves to your last line with the Shift key."),
                self.line_mode_cb),
            ('SequenceMode', stock.LINE_MODE_SEQUENCE, _("Sequence of Lines"),
                None, _("Draw a sequence straight or curved lines.\n\
Constrain angle by holding the Control key.\n\
Add curves to your last line with the Shift key."),
                self.line_mode_cb),
            ('EllipseMode', stock.LINE_MODE_ELLIPSE, _("Ellipse"),
                None, _("Draw circles and ellipes.\n\
Constrain shape or roation by holding the Control key.\n\
Rotate holding the Shift key."),
                self.line_mode_cb),
            ]
        ag.add_toggle_actions(toggle_actions)
        self.freehandmode = ag.get_action("FreehandMode")
        self.straightmode = ag.get_action("StraightMode")
        self.sequencemode = ag.get_action("SequenceMode")
        self.ellipsemode = ag.get_action("EllipseMode")

        # Each mode ToggleAction has a corresponding setting
        def attribute(mode, entry):
            mode.line_mode = entry[0]
            mode.stock_id = entry[1]
            mode.label = entry[2]
            mode.tooltip = entry[4]

        for entry in toggle_actions:
            attribute(getattr(self, entry[0].lower()), entry)

        for action in self.action_group.list_actions():
            action.set_draw_as_radio(True)
            # Allows hotkey set in Brush > Line Mode menu
            self.app.kbm.takeover_action(action)

    def line_mode_cb(self, action):
        action_wanted = action.get_active()
        if action_wanted:
            self._cancel_other_modes(action)
            self.line_mode = action.line_mode
        else:
            # Disallow cancelling Freehand mode unless something else
            # has become active.
            other_active =  self.straightmode.get_active()
            other_active |= self.sequencemode.get_active()
            other_active |= self.ellipsemode.get_active()
            if not other_active:
                self.freehandmode.set_active(True)
                self.line_mode = "FreehandMode"

    def _cancel_other_modes(self, action):
        for other_action in self.action_group.list_actions():
            if action is other_action:
                continue
            if other_action.get_active():
                other_action.block_activate()
                other_action.set_active(False)
                other_action.unblock_activate()

    def change_line_setting(self, setting, value):
        if setting in ('entry_pressure', 'midpoint_pressure',
                       'exit_pressure', 'line_head', 'line_tail'):
            if setting in ('line_head', 'line_tail'):
                setting = setting[5:]
            old = getattr(self, setting, None)
            if old == value:
                return
            setattr(self, setting, value)
            self.redraw_with_new_settings()


###
### Redraw last_line when settings are adjusted in Toolbar Dialog
###
    def redraw_with_new_settings(self):
        if self.idle_srcid is None:
            self.idle_srcid = gobject.idle_add(self.idle_cb)

    def redraw_line(self):
        last_line = self.last_line_data
        if last_line is not None:
            last_stroke = self.model.layer.get_last_stroke_info()
            if last_line[1] is last_stroke:
                # ignore slow_tracking
                self.done = True
                self.adj = self.app.brush_adjustment['slow_tracking']
                self.slow_tracking = self.adj.get_value()
                self.adj.set_value(0)
                self.model.undo()
                command = last_line[0]
                self.sx, self.sy = last_line[2], last_line[3]
                self.ex, self.ey = last_line[4], last_line[5]
                x, y = self.ex, self.ey
                if command == "EllipseMode":
                    self.angle = last_line[6]
                    self.dynamic_ellipse(self.ex, self.ey, self.sx, self.sy)
                if command == "CurveLine1":
                    self.dynamic_straight_line(self.ex, self.ey, self.sx, self.sy)
                    command = "StraightMode"
                if command == "CurveLine2":
                    x, y = last_line[6], last_line[7]
                    self.kx, self.ky = last_line[8], last_line[9]
                    if (x, y) == (self.kx, self.ky):
                        self.dynamic_curve_1(x, y, self.sx, self.sy, self.ex, self.ey)
                        command = "CurveLine1"
                    else:
                        self.flip = False
                        self.dynamic_curve_2(x, y, self.sx, self.sy, self.ex, self.ey, self.kx, self.ky)
                self.model.split_stroke()
                self.record_last_stroke(command, x, y)

    def idle_cb(self):
        if self.idle_srcid is not None:
            self.idle_srcid = None
            self.redraw_line()

###
### Draw dynamic Line, Curve, or Ellipse
###

    # Called from dragfunc.py
    def start_command(self, mode, modifier):

        # Check for scratchpad under pointer
        if self.app.scratchpad_doc.tdw.has_pointer:
            self.model = self.app.scratchpad_doc.model
            self.tdw = self.app.scratchpad_doc.tdw
        else:
            self.model = self.app.doc.model
            self.tdw = self.app.doc.tdw

        self.done = False
        self.model.split_stroke() # split stroke here
        self.snapshot = self.model.layer.save_snapshot()

        x, y, kbmods = self.local_mouse_state()
        # ignore the modifier used to start this action (don't make it change the action)
        self.invert_kbmods = modifier
        kbmods ^= self.invert_kbmods # invert using bitwise xor
        ctrl = kbmods & gdk.CONTROL_MASK
        shift = kbmods & gdk.SHIFT_MASK

        # line_mode is the type of line to be drawn eg. "EllipseMode"
        self.mode = self.line_mode
        if self.mode == "FreehandMode":
            # starting with the configured modifier (e.g. Shift for "StraightMode")
            self.mode = mode

        self.undo = False
        # Ignore slow_tracking. There are some other sttings that interfere
        # with the workings of the Line Tools, but slowtracking is the main one.
        self.adj = self.app.brush_adjustment['slow_tracking']
        self.slow_tracking = self.adj.get_value()
        self.adj.set_value(0)

        # Throughout this module these conventions are used:
        # sx, sy = starting point
        # ex, ey = end point
        # kx, ky = curve point from last line
        # lx, ly = last point from DragFunc update
        self.sx, self.sy = x, y
        self.lx, self.ly = x, y

        if self.mode == "EllipseMode":
            # Rotation angle of ellipse.
            self.angle = 90
            # Vector to measure any rotation from. Assigned when ratation begins.
            self.ellipse_vec = None
            return
        # If not Ellipse, command must be Straight Line or Sequence
        # First check if the user intends to Curve an existing Line
        if shift:
            last_line = self.last_line_data
            last_stroke = self.model.layer.get_last_stroke_info()
            if last_line is not None:
                if last_line[1] == last_stroke:
                    self.mode = last_line[0]
                    self.sx, self.sy = last_line[2], last_line[3]
                    self.ex, self.ey = last_line[4], last_line[5]
                    if self.mode == "CurveLine2":
                        length_a = distance(x, y, self.sx, self.sy)
                        length_b = distance(x, y, self.ex, self.ey)
                        self.flip = length_a > length_b
                        if self.flip:
                            self.kx, self.ky = last_line[6], last_line[7]
                        else:
                            self.kx, self.ky = last_line[8], last_line[9]
                    self.model.undo()
                    self.snapshot = self.model.layer.save_snapshot()
                    self.process_line()
                    return

        if self.mode == "SequenceMode":
            if not self.tdw.last_painting_pos:
                return
            else:
                self.sx, self.sy = self.tdw.last_painting_pos

    def update_position(self, x, y):
        self.lx, self.ly = self.tdw.display_to_model(x, y)

    def stop_command(self):
    # End dragfunc
        self.done = True
        x, y = self.process_line()
        self.model.split_stroke()
        cmd = self.mode
        self.record_last_stroke(cmd, x, y)


    def record_last_stroke(self, cmd, x, y):
        last_line = None
        self.tdw.last_painting_pos = x, y # FIXME: should probably not set that from here
        last_stroke = self.model.layer.get_last_stroke_info()
        sx, sy = self.sx, self.sy

        if cmd == "CurveLine1":
            last_line = ["CurveLine2", last_stroke, sx, sy, self.ex, self.ey, x, y, x, y]
            self.tdw.last_painting_pos = self.ex, self.ey

        if cmd == "CurveLine2":
            if self.flip:
                last_line = [cmd, last_stroke, sx, sy, self.ex, self.ey, self.kx, self.ky, x, y]
            else:
                last_line = [cmd, last_stroke, sx, sy, self.ex, self.ey, x, y, self.kx, self.ky]
            self.tdw.last_painting_pos = self.ex, self.ey

        if cmd == "StraightMode" or cmd == "SequenceMode":
            last_line = ["CurveLine1", last_stroke, sx, sy, x, y]

        if cmd == "EllipseMode":
            last_line = [cmd, last_stroke, sx, sy, x, y, self.angle]
            self.tdw.last_painting_pos = sx, sy

        self.last_line_data = last_line
        self.adj.set_value(self.slow_tracking)
        self.model.brush.reset()

    def local_mouse_state(self, last_update=False):
        x, y, kbmods = self.tdw.renderer.window.get_pointer()
        if last_update:
            return self.lx, self.ly, kbmods
        x, y = self.tdw.display_to_model(x, y)
        return x, y, kbmods

    def process_line(self):
        sx, sy = self.sx, self.sy
        x, y, kbmods = self.local_mouse_state(last_update=True)
        kbmods ^= self.invert_kbmods # invert using bitwise xor
        ctrl = kbmods & gdk.CONTROL_MASK
        shift = kbmods & gdk.SHIFT_MASK

        if self.mode == "CurveLine1":
            self.dynamic_curve_1(x, y, sx, sy, self.ex, self.ey)

        elif self.mode == "CurveLine2":
            ex, ey = self.ex, self.ey
            kx, ky = self.kx, self.ky
            if not self.flip:
                self.dynamic_curve_2(x, y, sx, sy, ex, ey, kx, ky)
            else:
                self.dynamic_curve_2(kx, ky, sx, sy, ex, ey, x, y)

        elif self.mode == "EllipseMode":
            constrain = False
            if ctrl:
                x, y = constrain_to_angle(x, y, sx, sy)
                constrain = True
            if shift:
                self.ellipse_rotation_angle(x, y, sx, sy, constrain)
            else:
                self.ellipse_vec = None
            self.dynamic_ellipse(x, y, sx, sy)

        else: # if "StraightMode" or "SequenceMode"
            if ctrl or shift:
                x, y = constrain_to_angle(x, y, sx, sy)
            self.dynamic_straight_line(x, y, sx, sy)
        return x, y

    def ellipse_rotation_angle(self, x, y, sx, sy, constrain):
        x1, y1 = normal(sx, sy, x, y)
        if self.ellipse_vec is None:
            self.ellipse_vec = x1, y1
            self.last_angle = self.angle
        x2, y2 = self.ellipse_vec
        px, py = perpendicular(x2, y2)
        pangle = get_angle(x1, y1, px, py)
        angle = get_angle(x1, y1, x2, y2)
        if pangle > 90.0:
            angle = 360 - angle
        angle += self.last_angle
        if constrain:
            angle = constraint_angle(angle)
        self.angle = angle

###
### Line Functions
###

    # Straight Line
    def dynamic_straight_line(self, x, y, sx, sy):
        self.brush_prep(sx, sy)
        entry_p, midpoint_p, junk, prange2, head, tail = self.line_settings()
        # Beginning
        length, nx, ny = length_and_normal(sx, sy, x, y)
        mx, my = multiply_add(sx, sy, nx, ny, 0.25)
        self.stroke_to(mx, my, entry_p)
        # Middle start
        #length = length/2
        mx, my = multiply_add(sx, sy, nx, ny, head * length)
        self.stroke_to(mx, my, midpoint_p)
        # Middle end
        mx, my = multiply_add(sx, sy, nx, ny, tail * length)
        self.stroke_to(mx, my, midpoint_p)
        # End
        self.stroke_to(x, y, self.exit_pressure)

    # Ellipse
    def dynamic_ellipse(self, x, y, sx, sy):
        points_in_curve = 360
        x1, y1 = difference(sx, sy, x, y)
        x1, y1, sin, cos = starting_point_for_ellipse(x1, y1, self.angle)
        rx, ry = point_in_ellipse(x1, y1, sin, cos, 0)
        self.brush_prep(sx+rx, sy+ry)
        entry_p, midpoint_p, prange1, prange2, h, t = self.line_settings()
        head = points_in_curve * h
        head_range = int(head)+1
        tail = points_in_curve * t
        tail_range = int(tail)+1
        tail_length = points_in_curve - tail
        # Beginning
        px, py = point_in_ellipse(x1, y1, sin, cos, 1)
        length, nx, ny = length_and_normal(rx, ry, px, py)
        mx, my = multiply_add(rx, ry, nx, ny, 0.25)
        self.stroke_to(sx+mx, sy+my, entry_p)
        pressure = abs(1/head * prange1 + entry_p)
        self.stroke_to(sx+px, sy+py, pressure)
        for degree in xrange(2, head_range):
            px, py = point_in_ellipse(x1, y1, sin, cos, degree)
            pressure = abs(degree/head * prange1 + entry_p)
            self.stroke_to(sx+px, sy+py, pressure)
        # Middle
        for degree in xrange(head_range, tail_range):
            px, py = point_in_ellipse(x1, y1, sin, cos, degree)
            self.stroke_to(sx+px, sy+py, midpoint_p)
        # End
        for degree in xrange(tail_range, points_in_curve+1):
            px, py = point_in_ellipse(x1, y1, sin, cos, degree)
            pressure = abs((degree-tail)/tail_length * prange2 + midpoint_p)
            self.stroke_to(sx+px, sy+py, pressure)

    def dynamic_curve_1(self, cx, cy, sx, sy, ex, ey):
        self.brush_prep(sx, sy)
        self.draw_curve_1(cx, cy, sx, sy, ex, ey)

    def dynamic_curve_2(self, cx, cy, sx, sy, ex, ey, kx, ky):
        self.brush_prep(sx, sy)
        self.draw_curve_2(cx, cy, sx, sy, ex, ey, kx, ky)

    # Curve Straight Line
    # Found this page helpful:
    # http://www.caffeineowl.com/graphics/2d/vectorial/bezierintro.html
    def draw_curve_1(self, cx, cy, sx, sy, ex, ey):
        points_in_curve = 100
        entry_p, midpoint_p, prange1, prange2, h, t = self.line_settings()
        mx, my = midpoint(sx, sy, ex, ey)
        length, nx, ny = length_and_normal(mx, my, cx, cy)
        cx, cy = multiply_add(mx, my, nx, ny, length*2)
        x1, y1 = difference(sx, sy, cx, cy)
        x2, y2 = difference(cx, cy, ex, ey)
        head = points_in_curve * h
        head_range = int(head)+1
        tail = points_in_curve * t
        tail_range = int(tail)+1
        tail_length = points_in_curve - tail
        # Beginning
        px, py = point_on_curve_1(1, cx, cy, sx, sy, x1, y1, x2, y2)
        length, nx, ny = length_and_normal(sx, sy, px, py)
        bx, by = multiply_add(sx, sy, nx, ny, 0.25)
        self.stroke_to(bx, by, entry_p)
        pressure = abs(1/head * prange1 + entry_p)
        self.stroke_to(px, py, pressure)
        for i in xrange(2, head_range):
            px, py = point_on_curve_1(i, cx, cy, sx, sy, x1, y1, x2, y2)
            pressure = abs(i/head * prange1 + entry_p)
            self.stroke_to(px, py, pressure)
        # Middle
        for i in xrange(head_range, tail_range):
            px, py = point_on_curve_1(i, cx, cy, sx, sy, x1, y1, x2, y2)
            self.stroke_to(px, py, midpoint_p)
        # End
        for i in xrange(tail_range, points_in_curve+1):
            px, py = point_on_curve_1(i, cx, cy, sx, sy, x1, y1, x2, y2)
            pressure = abs((i-tail)/tail_length * prange2 + midpoint_p)
            self.stroke_to(px, py, pressure)

    def draw_curve_2(self, cx, cy, sx, sy, ex, ey, kx, ky):
        points_in_curve = 100
        self.brush_prep(sx, sy)
        entry_p, midpoint_p, prange1, prange2, h, t = self.line_settings()
        mx, my = (cx+sx+ex+kx)/4.0, (cy+sy+ey+ky)/4.0
        length, nx, ny = length_and_normal(mx, my, cx, cy)
        cx, cy = multiply_add(mx, my, nx, ny, length*2)
        length, nx, ny = length_and_normal(mx, my, kx, ky)
        kx, ky = multiply_add(mx, my, nx, ny, length*2)
        x1, y1 = difference(sx, sy, cx, cy)
        x2, y2 = difference(cx, cy, kx, ky)
        x3, y3 = difference(kx, ky, ex, ey)
        head = points_in_curve * h
        head_range = int(head)+1
        tail = points_in_curve * t
        tail_range = int(tail)+1
        tail_length = points_in_curve - tail
        # Beginning
        px, py = point_on_curve_2(1, cx, cy, sx, sy, kx, ky, x1, y1, x2, y2, x3, y3)
        length, nx, ny = length_and_normal(sx, sy, px, py)
        bx, by = multiply_add(sx, sy, nx, ny, 0.25)
        self.stroke_to(bx, by, entry_p)
        pressure = abs(1/head * prange1 + entry_p)
        self.stroke_to(px, py, pressure)
        for i in xrange(2, head_range):
            px, py = point_on_curve_2(i, cx, cy, sx, sy, kx, ky, x1, y1, x2, y2, x3, y3)
            pressure = abs(i/head * prange1 + entry_p)
            self.stroke_to(px, py, pressure)
        # Middle
        for i in xrange(head_range, tail_range):
            px, py = point_on_curve_2(i, cx, cy, sx, sy, kx, ky, x1, y1, x2, y2, x3, y3)
            self.stroke_to(px, py, midpoint_p)
        # End
        for i in xrange(tail_range, points_in_curve+1):
            px, py = point_on_curve_2(i, cx, cy, sx, sy, kx, ky, x1, y1, x2, y2, x3, y3)
            pressure = abs((i-tail)/tail_length * prange2 + midpoint_p)
            self.stroke_to(px, py, pressure)

    def stroke_to(self, x, y, pressure):
        duration = 0.001
        brush = self.model.brush
        if not self.done:
            # stroke without setting undo
            self.model.layer.stroke_to(brush, x, y, pressure, 0.0, 0.0, duration)
        else:
            self.model.stroke_to(duration, x, y, pressure, 0.0, 0.0)

    def brush_prep(self, sx, sy):
        # Send brush to where the stroke will begin
        self.model.brush.reset()
        brush = self.model.brush
        self.model.layer.stroke_to(brush, sx, sy, 0.0, 0.0, 0.0, 10.0)
        self.model.layer.load_snapshot(self.snapshot)

    def line_settings(self):
        p1 = self.entry_pressure
        p2 = self.midpoint_pressure
        p3 = self.exit_pressure
        if self.head == 0.0001:
            p1 = p2
        prange1 = p2 - p1
        prange2 = p3 - p2
        return p1, p2, prange1, prange2, self.head, self.tail


### Curve Math
def point_on_curve_1(t, cx, cy, sx, sy, x1, y1, x2, y2):
    ratio = t/100.0
    x3, y3 = multiply_add(sx, sy, x1, y1, ratio)
    x4, y4 = multiply_add(cx, cy, x2, y2, ratio)
    x5, y5 = difference(x3, y3, x4, y4)
    x, y = multiply_add(x3, y3, x5, y5, ratio)
    return x, y

def point_on_curve_2(t, cx, cy, sx, sy, kx, ky, x1, y1, x2, y2, x3, y3):
    ratio = t/100.0
    x4, y4 = multiply_add(sx, sy, x1, y1, ratio)
    x5, y5 = multiply_add(cx, cy, x2, y2, ratio)
    x6, y6 = multiply_add(kx, ky, x3, y3, ratio)
    x1, y1 = difference(x4, y4, x5, y5)
    x2, y2 = difference(x5, y5, x6, y6)
    x4, y4 = multiply_add(x4, y4, x1, y1, ratio)
    x5, y5 = multiply_add(x5, y5, x2, y2, ratio)
    x1, y1 = difference(x4, y4, x5, y5)
    x, y = multiply_add(x4, y4, x1, y1, ratio)
    return x, y


### Ellipse Math
def starting_point_for_ellipse(x, y, rotate):
    # Rotate starting point
    r = math.radians(rotate)
    sin = math.sin(r)
    cos = math.cos(r)
    x, y = rotate_ellipse(x, y, cos, sin)
    return x, y, sin, cos

def point_in_ellipse(x, y, r_sin, r_cos, degree):
    # Find point in ellipse
    r2 = math.radians(degree)
    cos = math.cos(r2)
    sin = math.sin(r2)
    x = x * cos
    y = y * sin
    # Rotate Ellipse
    x, y = rotate_ellipse(y, x, r_sin, r_cos)
    return x, y

def rotate_ellipse(x, y, sin, cos):
    x1, y1 = multiply(x, y, sin)
    x2, y2 = multiply(x, y, cos)
    x = x2 - y1
    y = y2 + x1
    return x, y


### Vector Math
def get_angle(x1, y1, x2, y2):
    dot = dot_product(x1, y1, x2, y2)
    if abs(dot) < 1.0:
        angle = math.acos(dot) * 180/math.pi
    else:
        angle = 0.0
    return angle

def constrain_to_angle(x, y, sx, sy):
    length, nx, ny = length_and_normal(sx, sy, x, y)
    # dot = nx*1 + ny*0 therefore nx
    angle = math.acos(nx) * 180/math.pi
    angle = constraint_angle(angle)
    ax, ay = angle_normal(ny, angle)
    x = sx + ax*length
    y = sy + ay*length
    return x, y

def constraint_angle(angle):
    n = angle//15
    n1 = n*15
    rem = angle - n1
    if rem < 7.5:
        angle = n*15.0
    else:
        angle = (n+1)*15.0
    return angle

def angle_normal(ny, angle):
    if ny < 0.0:
        angle = 360.0 - angle
    radians = math.radians(angle)
    x = math.cos(radians)
    y = math.sin(radians)
    return x, y

def length_and_normal(x1, y1, x2, y2):
    x, y = difference(x1, y1, x2, y2)
    length = vector_length(x, y)
    if length == 0.0:
        x, y = 0.0, 0.0
    else:
        x, y = x/length, y/length
    return length, x, y

def normal(x1, y1, x2, y2):
    junk, x, y = length_and_normal(x1, y1, x2, y2)
    return x, y

def vector_length(x, y):
    length = math.sqrt(x*x + y*y)
    return length

def distance(x1, y1, x2, y2):
    x, y = difference(x1, y1, x2, y2)
    length = vector_length(x, y)
    return length

def dot_product(x1, y1, x2, y2):
    return x1*x2 + y1*y2

def multiply_add(x1, y1, x2, y2, d):
    x3, y3 = multiply(x2, y2, d)
    x, y = add(x1, y1, x3, y3)
    return x, y

def multiply(x, y, d):
    # Multiply vector
    x = x*d
    y = y*d
    return x, y

def add(x1, y1, x2, y2):
    # Add vectors
    x = x1+x2
    y = y1+y2
    return x, y

def difference(x1, y1, x2, y2):
    # Difference in x and y between two points
    x = x2-x1
    y = y2-y1
    return x, y

def midpoint(x1, y1, x2, y2):
    # Midpoint between to points
    x = (x1+x2)/2.0
    y = (y1+y2)/2.0
    return x, y

def perpendicular(x1, y1):
    # Swap x and y, then flip one sign to give vector at 90 degree
    x = -y1
    y = x1
    return x, y
