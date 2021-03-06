# mainwindow.py
# The Zoxel main window.
# Copyright (c) 2013, Graham R King
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from PySide import QtCore
from PySide import QtGui
from dialog_about import AboutDialog
from dialog_resize import ResizeDialog
from ui_mainwindow import Ui_MainWindow
from voxel_widget import GLWidget
import json
from palette_widget import PaletteWidget
import os
import webbrowser
import urllib
import sys
import copy
from constants import ZOXEL_TAG
import platform


class MainWindow(QtGui.QMainWindow):

    def __init__(self, parent=None):
        # Initialise the UI
        self.display = None
        super(MainWindow, self).__init__(parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        # Current file
        self._filename = None
        self._filetype = None
        self._last_file_handler = None
        # Importers / Exporters
        self._file_handlers = []
        # Update our window caption
        self._caption = "Zoxel"
        # Our global state + user plugins
        if platform.system() == "Windows":
            appdata = os.path.expandvars("%APPDATA%")
        elif platform.system() == "Darwin":
            appdata = os.path.expanduser("~/Library/Application Support")
        else:
            appdata = os.path.expanduser("~/.local/share")
        self.user_plugins_path = os.path.join(appdata, "Zoxel", "plugins")
        if not os.path.isdir(self.user_plugins_path):
            os.makedirs(self.user_plugins_path, 16877)
        QtCore.QCoreApplication.setOrganizationName("Zoxel")
        QtCore.QCoreApplication.setApplicationName("Zoxel")
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
        QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, appdata)
        self.settings = QtCore.QSettings()
        self.state = {}
        # Our animation timer
        self._timer = QtCore.QTimer(self)
        self.connect(self._timer, QtCore.SIGNAL("timeout()"), self.on_animation_tick)
        self._anim_speed = 200
        # Load our state if possible
        self.load_state()
        # Create our GL Widget
        try:
            glw = GLWidget(self.ui.glparent)
            self.ui.glparent.layout().addWidget(glw)
            self.display = glw
        except Exception as E:
            QtGui.QMessageBox.warning(self, "Initialisation Failed", str(E))
            exit(1)
        # Load default model dimensions
        width = self.get_setting("default_model_width")
        height = self.get_setting("default_model_height")
        depth = self.get_setting("default_model_depth")
        if width:
            self.resize_voxels(width, height, depth)
            # Resize is detected as a change, discard changes
            self.display.voxels.saved()
        # Create our palette widget
        voxels = PaletteWidget(self.ui.palette, RGBvalue=self.ui.paletteRGBvalue)
        self.ui.palette.layout().addWidget(voxels)
        self.color_palette = voxels
        # More UI state
        value = self.get_setting("display_axis_grids")
        if value is not None:
            self.ui.action_axis_grids.setChecked(value)
            self.display.axis_grids = value
        value = self.get_setting("background_color")
        if value is not None:
            self.display.background = QtGui.QColor.fromRgb(*value)
        value = self.get_setting("voxel_edges")
        if value is not None:
            self.display.voxel_edges = value
            self.ui.action_voxel_edges.setChecked(value)
        else:
            self.ui.action_voxel_edges.setChecked(self.display.voxel_edges)
        value = self.get_setting("occlusion")
        if value is None:
            value = True
        self.display.voxels.occlusion = value
        self.ui.action_occlusion.setChecked(value)
        # Connect some signals
        if self.display:
            self.display.voxels.notify = self.on_data_changed
            self.display.mouse_click_event.connect(self.on_tool_mouse_click)
            self.display.start_drag_event.connect(self.on_tool_drag_start)
            self.display.end_drag_event.connect(self.on_tool_drag_end)
            self.display.drag_event.connect(self.on_tool_drag)
        if self.color_palette:
            self.color_palette.changed.connect(self.on_color_changed)
        # Initialise our tools
        self._tool_group = QtGui.QActionGroup(self.ui.toolbar_drawing)
        self._tools = []
        self._tools_priorities = {}
        # Setup window
        self.update_caption()
        self.refresh_actions()
        self.display.ready = True
        # Update Check
        try:
            latest_tag = urllib.urlopen("https://github.com/chrmoritz/zoxel/releases/latest").geturl()
            if not latest_tag.endswith(ZOXEL_TAG):
                responce = QtGui.QMessageBox.question(self, "Outdated Zoxel version",
                                                      "A new version of Zoxel is available! Do you want to update now?",
                                                      buttons=(QtGui.QMessageBox.Yes | QtGui.QMessageBox.No),
                                                      defaultButton=QtGui.QMessageBox.Yes)
                if responce == QtGui.QMessageBox.Yes:
                    webbrowser.open(latest_tag, 2)
                    sys.exit(0)
        except IOError:
            pass

    def on_animation_tick(self):
        self.on_action_anim_next_triggered()

    @QtCore.Slot()
    def on_action_about_triggered(self):
        dialog = AboutDialog(self)
        if dialog.exec_():
            pass

    @QtCore.Slot()
    def on_action_axis_grids_triggered(self):
        self.display.axis_grids = self.ui.action_axis_grids.isChecked()
        self.set_setting("display_axis_grids", self.display.axis_grids)

    @QtCore.Slot()
    def on_action_voxel_edges_triggered(self):
        self.display.voxel_edges = self.ui.action_voxel_edges.isChecked()
        self.set_setting("voxel_edges", self.display.voxel_edges)

    @QtCore.Slot()
    def on_action_zoom_in_triggered(self):
        self.display.zoom_in()

    @QtCore.Slot()
    def on_action_zoom_out_triggered(self):
        self.display.zoom_out()

    @QtCore.Slot()
    def on_action_new_triggered(self):
        if self.display.voxels.changed:
            if not self.confirm_save():
                return
        # Clear our data
        self._filename = None
        self._filetype = None
        self.display.clear()
        self.display.voxels.saved()
        self.update_caption()
        self.refresh_actions()

    @QtCore.Slot()
    def on_action_wireframe_triggered(self):
        self.display.wireframe = self.ui.action_wireframe.isChecked()
        self.set_setting("display_wireframe", self.display.wireframe)

    @QtCore.Slot()
    def on_action_save_triggered(self):
        # Save
        self.save()

    @QtCore.Slot()
    def on_action_saveas_triggered(self):
        # Save
        self.save(True)

    @QtCore.Slot()
    def on_action_open_triggered(self):
        # Load
        self.load()

    @QtCore.Slot()
    def on_action_undo_triggered(self):
        # Undo
        self.display.voxels.undo()
        self.display.refresh()

    @QtCore.Slot()
    def on_action_redo_triggered(self):
        # Redo
        self.display.voxels.redo()
        self.display.refresh()

    @QtCore.Slot()
    def on_action_resize_triggered(self):
        # Resize model dimensions
        dialog = ResizeDialog(self)
        dialog.ui.width.setValue(self.display.voxels.width)
        dialog.ui.height.setValue(self.display.voxels.height)
        dialog.ui.depth.setValue(self.display.voxels.depth)
        if dialog.exec_():
            width = dialog.ui.width.value()
            height = dialog.ui.height.value()
            depth = dialog.ui.depth.value()
            self.resize_voxels(width, height, depth)

    def resize_voxels(self, width, height, depth):
        new_width_scale = float(width) / self.display.voxels.width
        new_height_scale = float(height) / self.display.voxels.height
        new_depth_scale = float(depth) / self.display.voxels.depth
        self.display.voxels.resize(width, height, depth)
        self.display.grids.scale_offsets(new_width_scale, new_height_scale, new_depth_scale)
        self.display.refresh()
        # Remember these dimensions
        self.set_setting("default_model_width", width)
        self.set_setting("default_model_height", height)
        self.set_setting("default_model_depth", depth)

    @QtCore.Slot()
    def on_action_reset_camera_triggered(self):
        self.display.reset_camera()

    @QtCore.Slot()
    def on_action_occlusion_triggered(self):
        self.display.voxels.occlusion = self.ui.action_occlusion.isChecked()
        self.set_setting("occlusion", self.display.voxels.occlusion)
        self.display.refresh()

    @QtCore.Slot()
    def on_action_background_triggered(self):
        # Choose a background color
        color = QtGui.QColorDialog.getColor()
        if color.isValid():
            self.display.background = color
            color = (color.red(), color.green(), color.blue())
            self.set_setting("background_color", color)

    @QtCore.Slot()
    def on_action_anim_add_triggered(self):
        value, res = QtGui.QInputDialog.getInt(self, "Add frame", "Add new frame after:",
                                               self.display.voxels.get_frame_number() + 1, 1,
                                               self.display.voxels.get_frame_count())
        if res:
            self.display.voxels.insert_frame(value, True)
            self.display.refresh()
            self.refresh_actions()

    @QtCore.Slot()
    def on_action_anim_add_empty_triggered(self):
        value, res = QtGui.QInputDialog.getInt(self, "Add frame", "Add new frame after:",
                                               self.display.voxels.get_frame_number() + 1, 1,
                                               self.display.voxels.get_frame_count())
        if res:
            self.display.voxels.insert_frame(value, False)
            self.display.refresh()
            self.refresh_actions()

    @QtCore.Slot()
    def on_action_anim_copy_triggered(self):
        value, res = QtGui.QInputDialog.getInt(self, "Copy frame", "Replace current frame with:", 1, 1,
                                               self.display.voxels.get_frame_count())
        if res:
            self.display.voxels.copy_to_current(value)
            self.display.refresh()
            self.refresh_actions()

    @QtCore.Slot()
    def on_action_anim_delete_triggered(self):
        ret = QtGui.QMessageBox.question(self, "Zoxel", "Do you really want to delete this frame?",
                                         QtGui.QMessageBox.Yes | QtGui.QMessageBox.No)
        if ret == QtGui.QMessageBox.Yes:
            self.display.voxels.delete_frame()
            self.display.refresh()
            self.refresh_actions()

    @QtCore.Slot()
    def on_action_anim_play_triggered(self):
        self._timer.start(self._anim_speed)
        self.refresh_actions()

    @QtCore.Slot()
    def on_action_anim_stop_triggered(self):
        self._timer.stop()
        self.refresh_actions()

    @QtCore.Slot()
    def on_action_anim_next_triggered(self):
        self.display.voxels.select_next_frame()
        self.display.refresh()
        self.refresh_actions()

    @QtCore.Slot()
    def on_action_anim_previous_triggered(self):
        self.display.voxels.select_previous_frame()
        self.display.refresh()
        self.refresh_actions()

    @QtCore.Slot()
    def on_action_anim_settings_triggered(self):
        pass

    @QtCore.Slot()
    def on_action_rotate_x_triggered(self):
        self.display.voxels.rotate_about_axis(self.display.voxels.X_AXIS)
        self.display.refresh()

    @QtCore.Slot()
    def on_action_rotate_y_triggered(self):
        self.display.voxels.rotate_about_axis(self.display.voxels.Y_AXIS)
        self.display.refresh()

    @QtCore.Slot()
    def on_action_rotate_z_triggered(self):
        self.display.voxels.rotate_about_axis(self.display.voxels.Z_AXIS)
        self.display.refresh()

    @QtCore.Slot()
    def on_action_mirror_x_triggered(self):
        self.display.voxels.mirror_in_axis(self.display.voxels.X_AXIS)
        self.display.refresh()

    @QtCore.Slot()
    def on_action_mirror_y_triggered(self):
        self.display.voxels.mirror_in_axis(self.display.voxels.Y_AXIS)
        self.display.refresh()

    @QtCore.Slot()
    def on_action_mirror_z_triggered(self):
        self.display.voxels.mirror_in_axis(self.display.voxels.Z_AXIS)
        self.display.refresh()

    @QtCore.Slot()
    def on_action_voxel_color_triggered(self):
        # Choose a voxel color
        color = QtGui.QColorDialog.getColor()
        if color.isValid():
            self.color_palette.color = color

    @QtCore.Slot()
    def on_paletteRGBvalue_editingFinished(self):
        s = self.ui.paletteRGBvalue.text()
        i = s.find('rgb(')
        if i >= 0:
            c = map(int, s[i+4:s.find(')')].split(','))
            color = QtGui.QColor(c[0], c[1], c[2])
        else:
            color = QtGui.QColor()
            color.setNamedColor(s)
        if color.isValid():
            self.color_palette.color = color

    @QtCore.Slot()
    def on_action_export_image_triggered(self):
        self.display.paintGL()
        png = QtGui.QPixmap(self.display.grabFrameBuffer())
        choices = "PNG Image (*.png);;JPEG Image (*.jpg)"

        # Grab our default location
        directory = self.get_setting("default_directory")
        # grab a filename
        filename, filetype = QtGui.QFileDialog.getSaveFileName(self, caption="Export Image As", filter=choices,
                                                               dir=directory)
        if not filename:
            return

        # Remember the location
        directory = os.path.dirname(filename)
        self.set_setting("default_directory", directory)

        # Save the PNG
        png.save(filename, filetype.split()[0])

    @QtCore.Slot()
    def on_action_export_troxel_triggered(self):
        from base64 import b64encode
        from struct import pack

        data = [self.display.voxels.width, self.display.voxels.height, self.display.voxels.depth, 0, 85, 0, 0]
        vox = []
        for z in xrange(self.display.voxels.depth - 1, -1, -1):
            for y in xrange(self.display.voxels.height):
                for x in xrange(self.display.voxels.width - 1, -1, -1):
                    v = self.display.voxels.get(x, y, z)
                    if v:
                        vox.append(((v & 0xff000000) >> 24, (v & 0xff0000) >> 16, (v & 0xff00) >> 8))
                    else:
                        vox.append(None)
        rcolors = {}
        for v in vox:
            if v:
                hex = v[2] + 256 * v[1] + 65536 * v[0]
                data.extend((0, v[0], v[1], v[2], 255))
                rcolors[hex] = (len(data) - 7) // 5
        data[5] = (len(data) - 7) // 1280
        short = data[5] == 0
        data[6] = (len(data) - 7) // 5 % 256
        i = 0
        length = len(vox)
        while i < length:
            r = 1
            while r < 129:
                if (i + r < length) and (vox[i + r - 1] == vox[i + r]):
                    r += 1
                else:
                    break
            if r > 1:
                data.append(126 + r)
            if vox[i]:
                index = rcolors[vox[i][2] + 256 * vox[i][1] + 65536 * vox[i][0]]
                if short:
                    data.append(index)
                else:
                    data.extend((index // 256, index % 256))
            else:
                if short:
                    data.append(0)
                else:
                    data.extend((0, 0))
            i += r
        webbrowser.open("https://chrmoritz.github.io/Troxel/#m=" + b64encode(pack('B' * len(data), *data)), 2)

    @QtCore.Slot()
    def on_action_copy_selection_to_frame_triggered(self):
        target_frame, res = QtGui.QInputDialog.getInt(self, "Copy selection", "Copy selection to frame:", 1, 1,
                                                      self.display.voxels.get_frame_count())
        if res:
            target_frame -= 1
            original_frame = self.display.voxels.get_frame_number()
            original_selection = copy.deepcopy(self.display.voxels._selection)
            if target_frame != original_frame:
                stamp = []
                for x, y, z in self.display.voxels._selection:
                    col = self.display.voxels.get(x, y, z)
                    stamp.append((x, y, z, col))
                self.display.voxels.select_frame(target_frame)
                btns = QtGui.QMessageBox.StandardButton.Abort | QtGui.QMessageBox.StandardButton.Ignore
                if (self.display.voxels.is_free(stamp) or
                        QtGui.QMessageBox.question(self, "Copy selection",
                                                   "This would override voxel data in the targeted frame!",
                                                   btns) == QtGui.QMessageBox.Ignore):
                    for x, y, z, col in stamp:
                        self.display.voxels.set(x, y, z, col)

            self.display.voxels.select_frame(original_frame)
            self.display.voxels._selection = original_selection
            self.display.refresh()
            self.refresh_actions()

    @QtCore.Slot()
    def on_action_reload_plugins_triggered(self):
        # reset plugin state
        self.ui.toolbar_drawing.clear()
        for a in self._tool_group.actions():
            self._tool_group.removeAction(a)
        self._tools = []
        self._tools_priorities.clear()
        self._file_handlers = []
        self._last_file_handler = None
        # reload default plugins
        from plugins import __all__ as plugins
        from sys import modules
        for p in plugins:
            reload(modules["plugins." + p])
        # reload user plugins
        from imp import load_source
        for p in os.listdir(self.user_plugins_path):
            if p.endswith(".py"):
                load_source(os.path.splitext(p)[0], os.path.join(self.user_plugins_path, p))

    @QtCore.Slot()
    def on_action_manage_plugins_triggered(self):
        webbrowser.open('file://' + self.user_plugins_path)

    def on_tool_mouse_click(self):
        tool = self.get_active_tool()
        if not tool:
            return
        data = self.display.target
        tool.on_mouse_click(data)

    def on_tool_drag_start(self):
        tool = self.get_active_tool()
        if not tool:
            return
        data = self.display.target
        tool.on_drag_start(data)

    def on_tool_drag(self):
        tool = self.get_active_tool()
        if not tool:
            return
        data = self.display.target
        tool.on_drag(data)

    def on_tool_drag_end(self):
        tool = self.get_active_tool()
        if not tool:
            return
        data = self.display.target
        tool.on_drag_end(data)

    # Confirm if user wants to save before doing something drastic.
    # returns True if we should continue
    def confirm_save(self):
        responce = QtGui.QMessageBox.question(self, "Save changes?",
                                              "Save changes before discarding?",
                                              buttons=(QtGui.QMessageBox.Save | QtGui.QMessageBox.Cancel |
                                                       QtGui.QMessageBox.No))
        if responce == QtGui.QMessageBox.StandardButton.Save:
            if not self.save():
                return False
        elif responce == QtGui.QMessageBox.StandardButton.Cancel:
            return False
        return True

    # Voxel data changed signal handler
    def on_data_changed(self):
        self.update_caption()
        self.refresh_actions()

    # Color selection changed handler
    def on_color_changed(self):
        self.display.voxel_color = self.color_palette.color

    # Return a section of our internal config
    def get_setting(self, name):
        if name in self.state:
            return self.state[name]
        return None

    # Set some config.  Value should be a serialisable type
    def set_setting(self, name, value):
        self.state[name] = value

    def closeEvent(self, event):
        # Save state
        self.save_state()
        if self.display.voxels.changed:
            if not self.confirm_save():
                event.ignore()
                return
        event.accept()

    # Save our state
    def save_state(self):
        try:
            state = json.dumps(self.state)
            self.settings.setValue("system/state", state)
        except Exception as E:
            # XXX Fail. Never displays because we're on our way out
            error = QtGui.QErrorMessage(self)
            error.showMessage(str(E))

    # Load our state
    def load_state(self):
        try:
            state = self.settings.value("system/state")
            if state:
                self.state = json.loads(state)
        except Exception as E:
            error = QtGui.QErrorMessage(self)
            error.showMessage(str(E))

    # Update the window caption to reflect the current state
    def update_caption(self):
        caption = "Zoxel"
        if self._filename:
            caption += " - [%s]" % self._filename
        else:
            caption += " - [Unsaved model]"
        if self.display and self.display.voxels.changed:
            caption += " *"
        numframes = self.display.voxels.get_frame_count()
        frame = self.display.voxels.get_frame_number() + 1
        if numframes > 1:
            caption += " - Frame {0} of {1}".format(frame, numframes)
        if caption != self._caption:
            self.setWindowTitle(caption)
        self._caption = caption

    # Save the current data
    def save(self, newfile=False):

        # Find the handlers that support saving
        handlers = [x for x in self._file_handlers if hasattr(x, 'save')]

        saved = False
        filename = self._filename
        filetype = self._filetype
        handler = self._last_file_handler

        # Build list of available types
        choices = []
        for exporter in handlers:
            choices.append("%s (%s)" % (exporter.description, exporter.filetype))
        choices = ";;".join(choices)

        # Grab our default location
        directory = self.get_setting("default_directory")

        # Get a filename if we need one
        if newfile or not filename:
            filename, filetype = QtGui.QFileDialog.getSaveFileName(self, caption="Save As", filter=choices,
                                                                   dir=directory, selectedFilter="Zoxel Files (*.zox)")
            if not filename:
                return
            handler = None

        # Remember the location
        directory = os.path.dirname(filename)
        self.set_setting("default_directory", directory)

        # Find the handler if we need to
        if not handler:
            for exporter in handlers:
                ourtype = "%s (%s)" % (exporter.description, exporter.filetype)
                if filetype == ourtype:
                    handler = exporter

        # Call the save handler
        try:
            handler.save(filename)
            saved = True
        except Exception as Ex:
            QtGui.QMessageBox.warning(self, "Save Failed", str(Ex))

        # If we saved, clear edited state
        if saved:
            self._filename = filename
            self._filetype = filetype
            self._last_file_handler = handler
            self.display.voxels.saved()
            self.update_caption()
        self.refresh_actions()
        return saved

    # Registers an file handler (importer/exporter) with the system
    def register_file_handler(self, handler):
        self._file_handlers.append(handler)

    # load a file
    def load(self):
        # If we have changes, perhaps we should save?
        if self.display.voxels.changed:
            if not self.confirm_save():
                return

        # Find the handlers that support loading
        handler = None
        handlers = [x for x in self._file_handlers if hasattr(x, 'load')]

        # Build list of types we can load
        choices = ["All Files (*)"]
        for importer in handlers:
            choices.append("%s (%s)" % (importer.description, importer.filetype))
        choices = ";;".join(choices)

        # Grab our default location
        directory = self.get_setting("default_directory")

        # Get a filename
        filename, filetype = QtGui.QFileDialog.getOpenFileName(self, caption="Open file", filter=choices,
                                                               dir=directory, selectedFilter="All Files (*)")
        if not filename:
            return
        if filetype == "All Files (*)":
            filetype = None
            for importer in handlers:
                if filename.endswith(importer.filetype[1:]):
                    filetype = "%s (%s)" % (importer.description, importer.filetype)
                    break
        if filetype is None:
            return

        # Remember the location
        directory = os.path.dirname(filename)
        self.set_setting("default_directory", directory)

        # Find the handler
        for importer in handlers:
            ourtype = "%s (%s)" % (importer.description, importer.filetype)
            if filetype == ourtype:
                handler = importer
                self._last_file_handler = handler

        # Load the file
        self.display.clear()
        self.display.voxels.disable_undo()
        self._filename = None
        try:
            handler.load(filename)
            self._filename = filename
            self._filetype = filetype
        except Exception as Ex:
            self.display.voxels.enable_undo()
            QtGui.QMessageBox.warning(self, "Could not load file", str(Ex))

        self.display.build_grids()
        # self.display.voxels.resize()
        self.display.voxels.saved()
        self.display.reset_camera()
        self.update_caption()
        self.refresh_actions()
        self.display.voxels.enable_undo()
        self.display.refresh()

    # Registers a tool in the drawing toolbar
    def register_tool(self, tool, activate=False):
        self._tools.append(tool)
        self._tool_group.addAction(tool.get_action())
        before = None
        bp = 9223372036854775807
        for p, action in self._tools_priorities.iteritems():
            if p > tool.priority and p < bp:
                bp = p
                before = action
        self.ui.toolbar_drawing.insertAction(before, tool.get_action())
        self._tools_priorities[tool.priority] = tool.get_action()
        if activate:
            tool.get_action().setChecked(True)

    # Return the active tool
    def get_active_tool(self):
        action = self._tool_group.checkedAction()
        if not action:
            return None
        # Find who owns this action and activate
        for tool in self._tools:
            if tool.get_action() is action:
                return tool
        return None

    # Load and initialise all plugins
    def load_plugins(self):
        # load default plugins
        from plugins import __all__ as plugins
        from importlib import import_module
        for p in plugins:
            import_module('plugins.' + p)
        # load user plugins
        from imp import load_source
        for p in os.listdir(self.user_plugins_path):
            if p.endswith(".py"):
                load_source(os.path.splitext(p)[0], os.path.join(self.user_plugins_path, p))

    # Update the state of the UI actions
    def refresh_actions(self):
        num_frames = self.display.voxels.get_frame_count()
        self.ui.action_anim_delete.setEnabled(num_frames > 1)
        self.ui.action_anim_previous.setEnabled(num_frames > 1)
        self.ui.action_anim_next.setEnabled(num_frames > 1)
        self.ui.action_anim_play.setEnabled(num_frames > 1 and not self._timer.isActive())
        self.ui.action_anim_stop.setEnabled(self._timer.isActive())
        self.update_caption()
