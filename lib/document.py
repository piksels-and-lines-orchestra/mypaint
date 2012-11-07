# This file is part of MyPaint.
# Copyright (C) 2007-2008 by Martin Renold <martinxyz@gmx.ch>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os, zipfile, tempfile, time, traceback
join = os.path.join
from cStringIO import StringIO
import xml.etree.ElementTree as ET
from gtk import gdk
import gobject, numpy
from gettext import gettext as _

import helpers, tiledsurface, pixbufsurface, backgroundsurface, mypaintlib
import command, stroke, layer
import brush

N = tiledsurface.N
LOAD_CHUNK_SIZE = 64*1024

from layer import DEFAULT_COMPOSITE_OP, VALID_COMPOSITE_OPS

def send_plo_message(cmd, app=None):

    import liblo

    timeout = int(os.environ.get('PLO_TIMEOUT', '1'))
    server_string = os.environ.get('PLO_SERVER', '10.0.1.23:2342')
    host, port = server_string.split(':')
    port = int(port)

    print host, port

    instrument = 'mypaint'
    action = cmd.__class__.__name__
    description = cmd.display_name

        #try:
    if app and getattr(app, 'brushmanager', None):
        current_brush = app.brushmanager.selected_brush.name
    else:
        current_brush = ''

    # Make a stroke done with different brush have a different string
    if action == 'Stroke' and current_brush:
        action = action + '/' + current_brush

    print action
    target = liblo.Address(host, port)
    try:
        liblo.send(target, "/plo/player/action", instrument, action)
    except Exception, e:
        print e


class SaveLoadError(Exception):
    """Expected errors on loading or saving, like missing permissions or non-existing files."""
    pass

class Document():
    """
    This is the "model" in the Model-View-Controller design.
    (The "view" would be ../gui/tileddrawwidget.py.)
    It represents everything that the user would want to save.


    The "controller" mostly in drawwindow.py.
    It is possible to use it without any GUI attached (see ../tests/)
    """
    # Please note the following difficulty with the undo stack:
    #
    #   Most of the time there is an unfinished (but already rendered)
    #   stroke pending, which has to be turned into a command.Action
    #   or discarded as empty before any other action is possible.
    #   (split_stroke)

    def __init__(self, brushinfo=None, app=None):

        self.app = app #HACK

        if not brushinfo:
            brushinfo = brush.BrushInfo()
            brushinfo.load_defaults()
        self.layers = []
        self.brush = brush.Brush(brushinfo)
        self.brush.brushinfo.observers.append(self.brushsettings_changed_cb)
        self.stroke = None
        self.canvas_observers = []
        self.stroke_observers = [] # callback arguments: stroke, brush (brush is a temporary read-only convenience object)
        self.doc_observers = []
        self.frame_observers = []
        self.command_stack_observers = []
        self.symmetry_observers = []
        self.__symmetry_axis = None
        self.clear(True)

        self._frame = [0, 0, 0, 0]
        self._frame_enabled = False
        # Used by move_frame() to accumulate values
        self._frame_dx = 0.0
        self._frame_dy = 0.0

    def move_current_layer(self, dx, dy):
        layer = self.layers[self.layer_idx]
        layer.translate(dx, dy)

    def get_frame(self):
        return self._frame

    def move_frame(self, dx, dy):
        """Move the frame. Accumulates changes and moves the frame once
        the accumulated change reaches one pixel."""

        def round_to_n(value, n):
            return int(round(value/n)*n)

        x, y, w, h = self.get_frame()

        self._frame_dx += dx
        self._frame_dy += dy
        step_x = int(round(self._frame_dx))
        step_y = int(round(self._frame_dy))

        if step_x:
            self.set_frame(x=x+step_x)
            self._frame_dx -= step_x

        if step_y:
            self.set_frame(y=y+step_y)
            self._frame_dy -= step_y

    def set_frame(self, x=None, y=None, width=None, height=None):
        """Set the size of the frame. Pass None to indicate no-change."""

        for i, var in enumerate([x, y, width, height]):
            if not var is None:
                self._frame[i] = int(var)

        for f in self.frame_observers: f()

    def get_frame_enabled(self):
        return self._frame_enabled

    def set_frame_enabled(self, enabled):
        self._frame_enabled = enabled
        for f in self.frame_observers: f()
    frame_enabled = property(get_frame_enabled)

    def call_doc_observers(self):
        for f in self.doc_observers:
            f(self)
        return True


    def get_symmetry_axis(self):
        """Gets the active painting symmetry X axis value.
        """
        return self.__symmetry_axis


    def set_symmetry_axis(self, x):
        """Sets the active painting symmetry X axis value.

        A value of `None` inactivates symmetrical painting. After setting, all
        registered `symmetry_observers` are called without arguments.
        """
        for layer in self.layers:
            layer.set_symmetry_axis(x)
        self.__symmetry_axis = x
        for func in self.symmetry_observers:
            func()


    def clear(self, init=False):
        self.split_stroke()
        self.set_symmetry_axis(None)
        if not init:
            bbox = self.get_bbox()
        # throw everything away, including undo stack

        self.command_stack = command.CommandStack()
        self.command_stack.stack_observers = self.command_stack_observers
        self.set_background((255, 255, 255))
        self.layers = []
        self.layer_idx = None
        self.add_layer(0)
        # disallow undo of the first layer
        self.command_stack.clear()
        self.unsaved_painting_time = 0.0

        if not init:
            for f in self.canvas_observers:
                f(*bbox)

        self.call_doc_observers()

    def get_current_layer(self):
        return self.layers[self.layer_idx]
    layer = property(get_current_layer)

    def split_stroke(self):
        if not self.stroke: return
        self.stroke.stop_recording()
        if not self.stroke.empty:
            cmd = command.Stroke(self, self.stroke, self.snapshot_before_stroke)
            send_plo_message(cmd, self.app)
            self.command_stack.do(cmd)

            del self.snapshot_before_stroke
            self.unsaved_painting_time += self.stroke.total_painting_time
            for f in self.stroke_observers:
                f(self.stroke, self.brush)
        self.stroke = None

    def brushsettings_changed_cb(self, settings):
        # The brush settings below are expected to change often in
        # mid-stroke eg. by heavy keyboard usage. If only those
        # change, we don't create a new undo step. (And thus als no
        # separate pickable stroke in the strokemap.)
        leightweight_brushsettings = set((
            'radius_logarithmic', 'color_h', 'color_s', 'color_v',
            'opaque', 'hardness', 'slow_tracking', 'slow_tracking_per_dab'
            ))
        if settings - leightweight_brushsettings:
            self.split_stroke()

    def select_layer(self, idx):
        self.do(command.SelectLayer(self, idx))

    def record_layer_move(self, layer, dx, dy):
        layer_idx = self.layers.index(layer)
        self.do(command.MoveLayer(self, layer_idx, dx, dy, True))

    def move_layer(self, was_idx, new_idx, select_new=False):
        self.do(command.ReorderSingleLayer(self, was_idx, new_idx, select_new))

    def duplicate_layer(self, insert_idx=None, name=''):
        self.do(command.DuplicateLayer(self, insert_idx, name))

    def reorder_layers(self, new_layers):
        self.do(command.ReorderLayers(self, new_layers))

    def clear_layer(self):
        if not self.layer.is_empty():
            self.do(command.ClearLayer(self))

    def stroke_to(self, dtime, x, y, pressure, xtilt, ytilt):
        if not self.stroke:
            self.stroke = stroke.Stroke()
            self.stroke.start_recording(self.brush)
            self.snapshot_before_stroke = self.layer.save_snapshot()
        self.stroke.record_event(dtime, x, y, pressure, xtilt, ytilt)

        split = self.layer.stroke_to(self.brush, x, y,
                                pressure, xtilt, ytilt, dtime)

        if split:
            self.split_stroke()

    def redo_last_stroke_with_different_brush(self, brush):
        cmd = self.get_last_command()
        if not isinstance(cmd, command.Stroke):
            return
        cmd = self.undo()
        assert isinstance(cmd, command.Stroke)
        new_stroke = cmd.stroke.copy_using_different_brush(brush)
        snapshot_before = self.layer.save_snapshot()
        new_stroke.render(self.layer._surface)
        self.do(command.Stroke(self, new_stroke, snapshot_before))

    def layer_modified_cb(self, *args):
        # for now, any layer modification is assumed to be visible
        for f in self.canvas_observers:
            f(*args)

    def invalidate_all(self):
        for f in self.canvas_observers:
            f(0, 0, 0, 0)

    def undo(self):
        self.split_stroke()
        while 1:
            cmd = self.command_stack.undo()
            if not cmd or not cmd.automatic_undo:
                return cmd

    def redo(self):
        self.split_stroke()
        while 1:
            cmd = self.command_stack.redo()
            if not cmd or not cmd.automatic_undo:
                return cmd

    def do(self, cmd):
        self.split_stroke()
        send_plo_message(cmd, self.app)
        self.command_stack.do(cmd)

    def get_last_command(self):
        self.split_stroke()
        return self.command_stack.get_last_command()

    def get_bbox(self):
        res = helpers.Rect()
        for layer in self.layers:
            # OPTIMIZE: only visible layers...
            # careful: currently saving assumes that all layers are included
            bbox = layer.get_bbox()
            res.expandToIncludeRect(bbox)
        return res

    def get_effective_bbox(self):
        """Return the effective bounding box of the document.
        If the frame is enabled, this is the bounding box of the frame, 
        else the (dynamic) bounding box of the document."""
        return self.get_frame() if self.frame_enabled else self.get_bbox()

    def blit_tile_into(self, dst_8bit, dst_has_alpha, tx, ty, mipmap_level=0, layers=None, background=None):
        assert dst_has_alpha is False
        if layers is None:
            layers = self.layers
        if background is None:
            background = self.background

        assert dst_8bit.dtype == 'uint8'
        assert dst_8bit.shape[-1] == 4
        dst = numpy.empty((N, N, 4), dtype='uint16')

        background.blit_tile_into(dst, dst_has_alpha, tx, ty, mipmap_level)

        for layer in layers:
            surface = layer._surface
            surface.composite_tile(dst, dst_has_alpha, tx, ty,
                    mipmap_level=mipmap_level,
                    opacity=layer.effective_opacity,
                    mode=layer.compositeop)

        mypaintlib.tile_convert_rgbu16_to_rgbu8(dst, dst_8bit)

    def add_layer(self, insert_idx=None, after=None, name=''):
        self.do(command.AddLayer(self, insert_idx, after, name))

    def remove_layer(self,layer=None):
        if len(self.layers) > 1:
            self.do(command.RemoveLayer(self,layer))
        else:
            self.clear_layer()

    def merge_layer_down(self):
        dst_idx = self.layer_idx - 1
        if dst_idx < 0:
            return False
        self.do(command.MergeLayer(self, dst_idx))
        return True

    def load_layer_from_pixbuf(self, pixbuf, x=0, y=0):
        arr = helpers.gdkpixbuf2numpy(pixbuf)
        s = tiledsurface.Surface()
        bbox = s.load_from_numpy(arr, x, y)
        self.do(command.LoadLayer(self, s))
        return bbox

    def load_layer_from_png(self, filename, x=0, y=0, feedback_cb=None):
        s = tiledsurface.Surface()
        bbox = s.load_from_png(filename, x, y, feedback_cb)
        self.do(command.LoadLayer(self, s))
        return bbox

    def set_layer_visibility(self, visible, layer):
        cmd = self.get_last_command()
        if isinstance(cmd, command.SetLayerVisibility) and cmd.layer is layer:
            self.undo()
        self.do(command.SetLayerVisibility(self, visible, layer))

    def set_layer_locked(self, locked, layer):
        cmd = self.get_last_command()
        if isinstance(cmd, command.SetLayerLocked) and cmd.layer is layer:
            self.undo()
        self.do(command.SetLayerLocked(self, locked, layer))

    def set_layer_opacity(self, opacity, layer=None):
        """Sets the opacity of a layer. If layer=None, works on the current layer"""
        cmd = self.get_last_command()
        if isinstance(cmd, command.SetLayerOpacity):
            self.undo()
        self.do(command.SetLayerOpacity(self, opacity, layer))

    def set_layer_compositeop(self, compositeop, layer=None):
        """Sets the composition-operation of a layer. If layer=None, works on the current layer"""
        if compositeop not in VALID_COMPOSITE_OPS:
            compositeop = DEFAULT_COMPOSITE_OP
        cmd = self.get_last_command()
        if isinstance(cmd, command.SetLayerCompositeOp):
            self.undo()
        self.do(command.SetLayerCompositeOp(self, compositeop, layer))

    def set_background(self, obj):
        # This is not an undoable action. One reason is that dragging
        # on the color chooser would get tons of undo steps.

        if not isinstance(obj, backgroundsurface.Background):
            obj = backgroundsurface.Background(obj)
        self.background = obj

        self.invalidate_all()

    def load_from_pixbuf(self, pixbuf):
        """Load a document from a pixbuf."""
        self.clear()
        bbox = self.load_layer_from_pixbuf(pixbuf)
        self.set_frame(*bbox)

    def is_layered(self):
        count = 0
        for l in self.layers:
            if not l.is_empty():
                count += 1
        return count > 1

    def is_empty(self):
        return len(self.layers) == 1 and self.layer.is_empty()

    def save(self, filename, **kwargs):
        self.split_stroke()
        junk, ext = os.path.splitext(filename)
        ext = ext.lower().replace('.', '')
        save = getattr(self, 'save_' + ext, self.unsupported)
        try:
            save(filename, **kwargs)
        except gobject.GError, e:
            traceback.print_exc()
            if e.code == 5:
                #add a hint due to a very consfusing error message when there is no space left on device
                raise SaveLoadError, _('Unable to save: %s\nDo you have enough space left on the device?') % e.message
            else:
                raise SaveLoadError, _('Unable to save: %s') % e.message
        except IOError, e:
            traceback.print_exc()
            raise SaveLoadError, _('Unable to save: %s') % e.strerror
        self.unsaved_painting_time = 0.0

    def load(self, filename, **kwargs):
        if not os.path.isfile(filename):
            raise SaveLoadError, _('File does not exist: %s') % repr(filename)
        if not os.access(filename,os.R_OK):
            raise SaveLoadError, _('You do not have the necessary permissions to open file: %s') % repr(filename)
        junk, ext = os.path.splitext(filename)
        ext = ext.lower().replace('.', '')
        load = getattr(self, 'load_' + ext, self.unsupported)
        try:
            load(filename, **kwargs)
        except gobject.GError, e:
            traceback.print_exc()
            raise SaveLoadError, _('Error while loading: GError %s') % e
        except IOError, e:
            traceback.print_exc()
            raise SaveLoadError, _('Error while loading: IOError %s') % e
        self.command_stack.clear()
        self.unsaved_painting_time = 0.0
        self.call_doc_observers()

    def unsupported(self, filename, *args, **kwargs):
        raise SaveLoadError, _('Unknown file format extension: %s') % repr(filename)

    def render_as_pixbuf(self, *args, **kwargs):
        return pixbufsurface.render_as_pixbuf(self, *args, **kwargs)

    def render_thumbnail(self):
        t0 = time.time()
        x, y, w, h = self.get_effective_bbox()
        if w == 0 or h == 0:
            # workaround to save empty documents
            x, y, w, h = 0, 0, tiledsurface.N, tiledsurface.N
        mipmap_level = 0
        while mipmap_level < tiledsurface.MAX_MIPMAP_LEVEL and max(w, h) >= 512:
            mipmap_level += 1
            x, y, w, h = x/2, y/2, w/2, h/2

        pixbuf = self.render_as_pixbuf(x, y, w, h, mipmap_level=mipmap_level)
        assert pixbuf.get_width() == w and pixbuf.get_height() == h
        pixbuf = helpers.scale_proportionally(pixbuf, 256, 256)
        print 'Rendered thumbnail in', time.time() - t0, 'seconds.'
        return pixbuf

    def save_png(self, filename, alpha=False, multifile=False, **kwargs):
        doc_bbox = self.get_effective_bbox()
        if multifile:
            self.save_multifile_png(filename, **kwargs)
        else:
            if alpha:
                tmp_layer = layer.Layer()
                for l in self.layers:
                    l.merge_into(tmp_layer)
                tmp_layer.save_as_png(filename, *doc_bbox)
            else:
                pixbufsurface.save_as_png(self, filename, *doc_bbox, alpha=False, **kwargs)

    def save_multifile_png(self, filename, alpha=False, **kwargs):
        prefix, ext = os.path.splitext(filename)
        # if we have a number already, strip it
        l = prefix.rsplit('.', 1)
        if l[-1].isdigit():
            prefix = l[0]
        doc_bbox = self.get_effective_bbox()
        for i, l in enumerate(self.layers):
            filename = '%s.%03d%s' % (prefix, i+1, ext)
            l.save_as_png(filename, *doc_bbox, **kwargs)

    def load_png(self, filename, feedback_cb=None):
        self.clear()
        bbox = self.load_layer_from_png(filename, 0, 0, feedback_cb)
        self.set_frame(*bbox)

    @staticmethod
    def _pixbuf_from_stream(fp, feedback_cb=None):
        loader = gdk.PixbufLoader()
        while True:
            if feedback_cb is not None:
                feedback_cb()
            buf = fp.read(LOAD_CHUNK_SIZE)
            if buf == '':
                break
            loader.write(buf)
        loader.close()
        return loader.get_pixbuf()

    def load_from_pixbuf_file(self, filename, feedback_cb=None):
        fp = open(filename, 'rb')
        pixbuf = self._pixbuf_from_stream(fp, feedback_cb)
        fp.close()
        self.load_from_pixbuf(pixbuf)

    load_jpg = load_from_pixbuf_file
    load_jpeg = load_from_pixbuf_file

    def save_jpg(self, filename, quality=90, **kwargs):
        x, y, w, h = self.get_effective_bbox()
        if w == 0 or h == 0:
            x, y, w, h = 0, 0, N, N # allow to save empty documents
        pixbuf = self.render_as_pixbuf(x, y, w, h, **kwargs)
        pixbuf.save(filename, 'jpeg', options={'quality':str(quality)})

    save_jpeg = save_jpg

    def save_ora(self, filename, options=None, **kwargs):
        print 'save_ora:'
        t0 = time.time()
        tempdir = tempfile.mkdtemp(u'mypaint')
        # use .tmp extension, so we don't overwrite a valid file if there is an exception
        z = zipfile.ZipFile(filename + '.tmpsave', 'w', compression=zipfile.ZIP_STORED)
        # work around a permission bug in the zipfile library: http://bugs.python.org/issue3394
        def write_file_str(filename, data):
            zi = zipfile.ZipInfo(filename)
            zi.external_attr = 0100644 << 16
            z.writestr(zi, data)
        write_file_str('mimetype', 'image/openraster') # must be the first file
        image = ET.Element('image')
        stack = ET.SubElement(image, 'stack')
        x0, y0, w0, h0 = self.get_effective_bbox()
        a = image.attrib
        a['w'] = str(w0)
        a['h'] = str(h0)

        def store_pixbuf(pixbuf, name):
            tmp = join(tempdir, 'tmp.png')
            t1 = time.time()
            pixbuf.save(tmp, 'png')
            print '  %.3fs pixbuf saving %s' % (time.time() - t1, name)
            z.write(tmp, name)
            os.remove(tmp)

        def store_surface(surface, name, rect=[]):
            tmp = join(tempdir, 'tmp.png')
            t1 = time.time()
            surface.save_as_png(tmp, *rect, **kwargs)
            print '  %.3fs surface saving %s' % (time.time() - t1, name)
            z.write(tmp, name)
            os.remove(tmp)

        def add_layer(x, y, opac, surface, name, layer_name, visible=True,
                      locked=False, selected=False,
                      compositeop=DEFAULT_COMPOSITE_OP, rect=[]):
            layer = ET.Element('layer')
            stack.append(layer)
            store_surface(surface, name, rect)
            a = layer.attrib
            if layer_name:
                a['name'] = layer_name
            a['src'] = name
            a['x'] = str(x)
            a['y'] = str(y)
            a['opacity'] = str(opac)
            if compositeop not in VALID_COMPOSITE_OPS:
                compositeop = DEFAULT_COMPOSITE_OP
            a['composite-op'] = compositeop
            if visible:
                a['visibility'] = 'visible'
            else:
                a['visibility'] = 'hidden'
            if locked:
                a['edit-locked'] = 'true'
            if selected:
                a['selected'] = 'true'
            return layer

        for idx, l in enumerate(reversed(self.layers)):
            if l.is_empty():
                continue
            opac = l.opacity
            x, y, w, h = l.get_bbox()
            sel = (idx == self.layer_idx)
            el = add_layer(x-x0, y-y0, opac, l._surface,
                           'data/layer%03d.png' % idx, l.name, l.visible,
                           locked=l.locked, selected=sel,
                           compositeop=l.compositeop, rect=(x, y, w, h))
            # strokemap
            sio = StringIO()
            l.save_strokemap_to_file(sio, -x, -y)
            data = sio.getvalue(); sio.close()
            name = 'data/layer%03d_strokemap.dat' % idx
            el.attrib['mypaint_strokemap_v2'] = name
            write_file_str(name, data)

        # save background as layer (solid color or tiled)
        bg = self.background
        # save as fully rendered layer
        x, y, w, h = self.get_bbox()
        l = add_layer(x-x0, y-y0, 1.0, bg, 'data/background.png', 'background',
                      locked=True, selected=False,
                      compositeop=DEFAULT_COMPOSITE_OP,
                      rect=(x,y,w,h))
        x, y, w, h = bg.get_pattern_bbox()
        # save as single pattern (with corrected origin)
        store_surface(bg, 'data/background_tile.png', rect=(x+x0, y+y0, w, h))
        l.attrib['background_tile'] = 'data/background_tile.png'

        # preview (256x256)
        t2 = time.time()
        print '  starting to render full image for thumbnail...'

        thumbnail_pixbuf = self.render_thumbnail()
        store_pixbuf(thumbnail_pixbuf, 'Thumbnails/thumbnail.png')
        print '  total %.3fs spent on thumbnail' % (time.time() - t2)

        helpers.indent_etree(image)
        xml = ET.tostring(image, encoding='UTF-8')

        write_file_str('stack.xml', xml)
        z.close()
        os.rmdir(tempdir)
        if os.path.exists(filename):
            os.remove(filename) # windows needs that
        os.rename(filename + '.tmpsave', filename)

        print '%.3fs save_ora total' % (time.time() - t0)

        return thumbnail_pixbuf

    @staticmethod
    def __xsd2bool(v):
        v = str(v).lower()
        if v in ['true', '1']: return True
        else: return False

    def load_ora(self, filename, feedback_cb=None):
        """Loads from an OpenRaster file"""
        print 'load_ora:'
        t0 = time.time()
        tempdir = tempfile.mkdtemp(u'mypaint')
        z = zipfile.ZipFile(filename)
        print 'mimetype:', z.read('mimetype').strip()
        xml = z.read('stack.xml')
        image = ET.fromstring(xml)
        stack = image.find('stack')

        w = int(image.attrib['w'])
        h = int(image.attrib['h'])

        def get_pixbuf(filename):
            t1 = time.time()

            try:
                fp = z.open(filename, mode='r')
            except KeyError:
                # support for bad zip files (saved by old versions of the GIMP ORA plugin)
                fp = z.open(filename.encode('utf-8'), mode='r')
                print 'WARNING: bad OpenRaster ZIP file. There is an utf-8 encoded filename that does not have the utf-8 flag set:', repr(filename)

            res = self._pixbuf_from_stream(fp, feedback_cb)
            fp.close()
            print '  %.3fs loading %s' % (time.time() - t1, filename)
            return res

        def get_layers_list(root, x=0,y=0):
            res = []
            for item in root:
                if item.tag == 'layer':
                    if 'x' in item.attrib:
                        item.attrib['x'] = int(item.attrib['x']) + x
                    if 'y' in item.attrib:
                        item.attrib['y'] = int(item.attrib['y']) + y
                    res.append(item)
                elif item.tag == 'stack':
                    stack_x = int( item.attrib.get('x', 0) )
                    stack_y = int( item.attrib.get('y', 0) )
                    res += get_layers_list(item, stack_x, stack_y)
                else:
                    print 'Warning: ignoring unsupported tag:', item.tag
            return res

        self.clear() # this leaves one empty layer
        no_background = True
        self.set_frame(width=w, height=h)

        selected_layer = None
        for layer in get_layers_list(stack):
            a = layer.attrib

            if 'background_tile' in a:
                assert no_background
                try:
                    print a['background_tile']
                    self.set_background(get_pixbuf(a['background_tile']))
                    no_background = False
                    continue
                except backgroundsurface.BackgroundError, e:
                    print 'ORA background tile not usable:', e

            src = a.get('src', '')
            if not src.lower().endswith('.png'):
                print 'Warning: ignoring non-png layer'
                continue
            name = a.get('name', '')
            x = int(a.get('x', '0'))
            y = int(a.get('y', '0'))
            opac = float(a.get('opacity', '1.0'))
            compositeop = str(a.get('composite-op', DEFAULT_COMPOSITE_OP))
            if compositeop not in VALID_COMPOSITE_OPS:
                compositeop = DEFAULT_COMPOSITE_OP
            selected = self.__xsd2bool(a.get("selected", 'false'))
            locked = self.__xsd2bool(a.get("edit-locked", 'false'))

            visible = not 'hidden' in a.get('visibility', 'visible')
            self.add_layer(insert_idx=0, name=name)
            t1 = time.time()

            # extract the png form the zip into a file first
            # the overhead for doing so seems to be neglegible (around 5%)
            z.extract(src, tempdir)
            tmp_filename = join(tempdir, src)
            self.load_layer_from_png(tmp_filename, x, y, feedback_cb)
            os.remove(tmp_filename)

            layer = self.layers[0]

            self.set_layer_opacity(helpers.clamp(opac, 0.0, 1.0), layer)
            self.set_layer_compositeop(compositeop, layer)
            self.set_layer_visibility(visible, layer)
            self.set_layer_locked(locked, layer)
            if selected:
                selected_layer = layer
            print '  %.3fs loading and converting layer png' % (time.time() - t1)
            # strokemap
            fname = a.get('mypaint_strokemap_v2', None)
            if fname:
                if x % N or y % N:
                    print 'Warning: dropping non-aligned strokemap'
                else:
                    sio = StringIO(z.read(fname))
                    layer.load_strokemap_from_file(sio, x, y)
                    sio.close()

        if len(self.layers) == 1:
            # no assertion (allow empty documents)
            print 'Warning: Could not load any layer, document is empty.'

        if len(self.layers) > 1:
            # remove the still present initial empty top layer
            self.select_layer(len(self.layers)-1)
            self.remove_layer()
            # this leaves the topmost layer selected

        if selected_layer is not None:
            for i, layer in zip(range(len(self.layers)), self.layers):
                if layer is selected_layer:
                    self.select_layer(i)
                    break

        z.close()

        # remove empty directories created by zipfile's extract()
        for root, dirs, files in os.walk(tempdir, topdown=False):
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(tempdir)

        print '%.3fs load_ora total' % (time.time() - t0)
