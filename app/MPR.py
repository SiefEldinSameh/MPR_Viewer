import sys
import os
import pydicom
import numpy as np
import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QPushButton,
                             QFileDialog, QWidget, QSlider, QLabel, QGridLayout, QSplitter,
                             QToolBar, QInputDialog, QMessageBox, QComboBox, QSizePolicy)
from PyQt6.QtGui import QIcon, QAction, QImage, QPixmap, QCursor, QPainter, QColor, QPen
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QPointF,QSize

import nibabel as nib
import traceback
import logging
logging.basicConfig(level=logging.DEBUG)


class CrosshairImageLabel(QLabel):
    clicked = pyqtSignal(QLabel, QPointF)
    mouse_moved = pyqtSignal(QLabel, QPointF)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.crosshair_position = QPointF(0, 0)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.pixmap():
            painter = QPainter(self)
            painter.setPen(QPen(QColor(255, 0, 0), 1))  # Red color, 1px width

            # Draw vertical line
            painter.drawLine(QPointF(self.crosshair_position.x(), 0),
                             QPointF(self.crosshair_position.x(), self.height()))

            # Draw horizontal line
            painter.drawLine(QPointF(0, self.crosshair_position.y()),
                             QPointF(self.width(), self.crosshair_position.y()))

    def mousePressEvent(self, event):
        if self.pixmap():
            pos = event.position()
            pixmap_rect = self.pixmap().rect()
            label_rect = self.rect()

            x_offset = (label_rect.width() - pixmap_rect.width()) // 2
            y_offset = (label_rect.height() - pixmap_rect.height()) // 2

            # Check if pixmap dimensions are valid
            if pixmap_rect.width() > 0 and pixmap_rect.height() > 0:
                adjusted_x = (pos.x() - x_offset) / pixmap_rect.width()
                adjusted_y = (pos.y() - y_offset) / pixmap_rect.height()

                normalized_pos = QPointF(max(0, min(1, adjusted_x)), max(0, min(1, adjusted_y)))
                self.clicked.emit(self, normalized_pos)

    def mouseMoveEvent(self, event):
        if self.pixmap():
            pos = event.position()
            pixmap_rect = self.pixmap().rect()
            label_rect = self.rect()

            x_offset = (label_rect.width() - pixmap_rect.width()) // 2
            y_offset = (label_rect.height() - pixmap_rect.height()) // 2

            # Check if pixmap dimensions are valid
            if pixmap_rect.width() > 0 and pixmap_rect.height() > 0:
                adjusted_x = (pos.x() - x_offset) / pixmap_rect.width()
                adjusted_y = (pos.y() - y_offset) / pixmap_rect.height()

                normalized_pos = QPointF(max(0, min(1, adjusted_x)), max(0, min(1, adjusted_y)))
                self.mouse_moved.emit(self, normalized_pos)


class EnhancedMultiViewMedicalImageViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_view = "axial"
        self.setWindowTitle("Enhanced Advanced Multi-View Medical Image Viewer")
        self.setGeometry(100, 100, 1200, 800)
        app_icon = QIcon("../assets/logo.png")
        self.setWindowIcon(app_icon)
        self.image_data = None
        self.current_slices = {"axial": 0, "sagittal": 0, "coronal": 0}
        self.cursor_position = {"axial": QPointF(0.5, 0.5), "sagittal": QPointF(0.5, 0.5), "coronal": QPointF(0.5, 0.5)}
        self.brightness = 1.0
        self.contrast = 1.0
        self.is_dragging = False
        self.pointer_mode = True
        self.last_mouse_pos = None
        self.pinned_points = {"axial": None, "sagittal": None, "coronal": None}
        self.setup_ui()
        self.zoom_factor = 1.0




    def setup_ui(self):
        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.crosshair_position = {"axial": QPoint(0, 0),
                                   "sagittal": QPoint(0, 0),
                                   "coronal": QPoint(0, 0)}
        self.is_dragging = False
        self.create_toolbar()
        self.create_side_panel()
        self.create_view_area()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.side_panel)
        self.splitter.addWidget(self.view_area)
        self.splitter.setSizes([200, 1000])

        self.main_layout.addWidget(self.splitter)

        self.setup_vtk()

    def create_toolbar(self):
        toolbar = QToolBar()
        self.addToolBar(toolbar)
        reset_action = QAction(QIcon("../icons/reset.png"), "Reset", self)
        reset_action.triggered.connect(self.reset_view)
        toolbar.addAction(reset_action)

        load_action = QAction(QIcon("../icons/load.png"), "Load File", self)
        load_action.triggered.connect(self.load_file)
        toolbar.addAction(load_action)

    def reset_view(self):
        # Reset zoom for all views
        self.zoom_factor = 1.0
        for label in [self.axial_view, self.sagittal_view, self.coronal_view]:
            label.resize(label.sizeHint())  # Reset to original size
        # Reset pointer
        self.pointer_mode = True
        self.pointer_hand_button.setChecked(False)
        self.toggle_pointer_hand_mode(False)
        # Reset slice positions
        self.reset_slice_positions()
        # Reset brightness and contrast
        self.brightness_slider.setValue(100)
        self.contrast_slider.setValue(100)
        self.brightness = 1.0
        self.contrast = 1.0
        # Update views
        self.update_2d_views()

    def create_side_panel(self):
        self.side_panel = QWidget()
        self.side_layout = QVBoxLayout(self.side_panel)

        self.pointer_hand_button = QPushButton("Pointer Mode")
        self.pointer_hand_button.setCheckable(True)
        self.pointer_hand_button.toggled.connect(self.toggle_pointer_hand_mode)
        self.side_layout.addWidget(self.pointer_hand_button)

        self.load_button = QPushButton("Load File")
        self.load_button.clicked.connect(self.load_file)
        self.side_layout.addWidget(self.load_button)

        self.create_slice_sliders()
        self.create_brightness_contrast_sliders()
        self.create_cine_controls()

        # Add reset button
        self.reset_button = QPushButton("Reset All")
        self.reset_button.clicked.connect(self.reset_all)
        self.side_layout.addWidget(self.reset_button)

        # Add rotate button for axial view only
        rotate_button = QPushButton("Rotate Views")
        rotate_button.clicked.connect(lambda: self.rotate_view("axial"))
        self.side_layout.addWidget(rotate_button)

        self.side_layout.addStretch(1)  # Add stretch to push everything to the top


    def create_slice_sliders(self):
        self.slice_sliders = {}
        for view in ["axial", "sagittal", "coronal"]:
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setEnabled(False)
            slider.valueChanged.connect(lambda value, v=view: self.update_slice(v, value))
            self.side_layout.addWidget(QLabel(f"{view.capitalize()} Slice:"))
            self.side_layout.addWidget(slider)
            self.slice_sliders[view] = slider

    def create_brightness_contrast_sliders(self):
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(0, 200)
        self.brightness_slider.setValue(100)
        self.brightness_slider.valueChanged.connect(self.update_brightness_contrast)
        self.side_layout.addWidget(QLabel("Brightness:"))
        self.side_layout.addWidget(self.brightness_slider)

        self.contrast_slider = QSlider(Qt.Orientation.Horizontal)
        self.contrast_slider.setRange(0, 200)
        self.contrast_slider.setValue(100)
        self.contrast_slider.valueChanged.connect(self.update_brightness_contrast)
        self.side_layout.addWidget(QLabel("Contrast:"))
        self.side_layout.addWidget(self.contrast_slider)

    def create_view_area(self):
        self.view_area = QWidget()
        self.view_layout = QGridLayout(self.view_area)
        self.view_layout.setSpacing(0)  # Remove spacing between widgets
        self.view_layout.setContentsMargins(0, 0, 0, 0)  # Remove layout margins

        self.axial_view = CrosshairImageLabel()
        self.sagittal_view = CrosshairImageLabel()
        self.coronal_view = CrosshairImageLabel()
        self.view_3d = QVTKRenderWindowInteractor()

        # Set size policies for the image views
        size_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        for view in [self.axial_view, self.sagittal_view, self.coronal_view, self.view_3d]:
            view.setSizePolicy(size_policy)
            view.setMinimumSize(100, 100)  # Set a minimum size to prevent collapse

        # Enable mouse tracking for the labels
        self.axial_view.setMouseTracking(True)
        self.sagittal_view.setMouseTracking(True)
        self.coronal_view.setMouseTracking(True)

        # Connect mouse events and add borders
        for view in [self.axial_view, self.sagittal_view, self.coronal_view]:
            view.clicked.connect(self.handle_view_click)
            view.mouse_moved.connect(self.handle_mouse_move)
            view.setStyleSheet("border: 2px solid white; background-color: black;")
            view.setAlignment(Qt.AlignmentFlag.AlignCenter)  # Center the content

        self.view_layout.addWidget(QLabel("Axial"), 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        self.view_layout.addWidget(self.axial_view, 1, 0)
        self.view_layout.addWidget(QLabel("Sagittal"), 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        self.view_layout.addWidget(self.sagittal_view, 1, 1)
        self.view_layout.addWidget(QLabel("Coronal"), 2, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        self.view_layout.addWidget(self.coronal_view, 3, 0)
        self.view_layout.addWidget(QLabel("3D View"), 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        self.view_layout.addWidget(self.view_3d, 3, 1)

        # Set row and column stretches
        self.view_layout.setRowStretch(1, 1)
        self.view_layout.setRowStretch(3, 1)
        self.view_layout.setColumnStretch(0, 1)
        self.view_layout.setColumnStretch(1, 1)

    def view_mouse_press_event(self, event, view):
        if self.image_data is None:
            return

        self.is_dragging = True
        self.update_cursor_position(event, view)

    def view_mouse_move_event(self, event, view):
        if self.image_data is None:
            return

        if self.is_dragging:
            self.update_cursor_position(event, view)

    def update_cursor_position(self, view_name, x, y):
        if self.image_data is None:
            return

        dim_z, dim_y, dim_x = self.image_data.shape

        # Update cursor position for the clicked view
        self.cursor_position[view_name] = QPointF(x, y)

        # Calculate voxel coordinates
        if view_name == "axial":
            voxel_x = int(x * (dim_x - 1))
            voxel_y = int(y * (dim_y - 1))
            voxel_z = self.current_slices["axial"]
        elif view_name == "sagittal":
            voxel_x = self.current_slices["sagittal"]
            voxel_y = int(x * (dim_y - 1))
            voxel_z = int((1 - y) * (dim_z - 1))  # Invert Y for sagittal view
        elif view_name == "coronal":
            voxel_x = int(x * (dim_x - 1))
            voxel_y = self.current_slices["coronal"]
            voxel_z = int((1 - y) * (dim_z - 1))  # Invert Y for coronal view

        # Update current slices
        self.current_slices["axial"] = voxel_z
        self.current_slices["sagittal"] = voxel_x
        self.current_slices["coronal"] = voxel_y

        # Update cursor positions for other views
        self.cursor_position["axial"] = QPointF(voxel_x / (dim_x - 1), voxel_y / (dim_y - 1))
        self.cursor_position["sagittal"] = QPointF(voxel_y / (dim_y - 1), 1 - (voxel_z / (dim_z - 1)))
        self.cursor_position["coronal"] = QPointF(voxel_x / (dim_x - 1), 1 - (voxel_z / (dim_z - 1)))

        self.update_slice_sliders()
        self.update_2d_views()
    def update_single_view(self, view_name):
        if self.image_data is None:
            return

        if view_name == "axial":
            self.display_2d_image(self.axial_view, self.image_data[self.current_slices["axial"], :, :], "axial")
        elif view_name == "sagittal":
            self.display_2d_image(self.sagittal_view, self.image_data[:, :, self.current_slices["sagittal"]], "sagittal")
        elif view_name == "coronal":
            self.display_2d_image(self.coronal_view, self.image_data[:, self.current_slices["coronal"], :], "coronal")

    def view_mouse_release_event(self, event, view):
        self.is_dragging = False

    def update_crosshair_position(self, label, pos):
        view_name = self.get_view_name(label)
        label.crosshair_position = pos
        self.cursor_position[view_name] = QPointF(pos.x() / label.width(), pos.y() / label.height())
        label.update()

        # Update other views based on the clicked view's position
        self.update_other_views(view_name)


    def get_view_name(self, label):
        if label == self.axial_view:
            return "axial"
        elif label == self.sagittal_view:
            return "sagittal"
        elif label == self.coronal_view:
            return "coronal"

    def update_other_views(self, clicked_view):
        x, y = self.cursor_position[clicked_view].x(), self.cursor_position[clicked_view].y()

        if clicked_view == "axial":
            self.update_slice('sagittal', int(x * (self.image_data.shape[2] - 1)))
            self.update_slice('coronal', int(y * (self.image_data.shape[1] - 1)))
        elif clicked_view == "sagittal":
            self.update_slice('axial', int(y * (self.image_data.shape[0] - 1)))
            self.update_slice('coronal', int(x * (self.image_data.shape[1] - 1)))
        elif clicked_view == "coronal":
            self.update_slice('axial', int(y * (self.image_data.shape[0] - 1)))
            self.update_slice('sagittal', int(x * (self.image_data.shape[2] - 1)))

        self.update_2d_views()


    def setup_vtk(self):
        self.renderer = vtk.vtkRenderer()
        self.view_3d.GetRenderWindow().AddRenderer(self.renderer)
        self.interactor = self.view_3d.GetRenderWindow().GetInteractor()

    def load_file(self):
        file_type, ok = QInputDialog.getItem(self, "Select File Type", "Choose file type:",
                                             ["DICOM", "Other (nii.gz, etc.)"], 0, False)
        if ok:
            if file_type == "DICOM":
                self.load_dicom_folder()
            else:
                self.load_other_file()

    def load_dicom_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select DICOM Folder")
        if folder:
            self.load_dicom_series(folder)

    def load_other_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Image File", "", "Image Files (*.nii *.nii.gz)")
        if file:
            self.load_nifti_file(file)

    def load_dicom_series(self, folder_path):
        dicom_files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if f.endswith('.dcm')]
        dicom_files.sort()

        slices = [pydicom.dcmread(file) for file in dicom_files]
        self.image_data = np.stack([s.pixel_array for s in slices])
        self.initialize_views()

        self.update_slice_sliders()
        self.update_2d_views()
        self.create_3d_view()

    def initialize_views(self):
        if self.image_data is not None:
            for view in ["axial", "sagittal", "coronal"]:
                max_slice = self.image_data.shape[{"axial": 0, "sagittal": 2, "coronal": 1}[view]] - 1
                middle_slice = max_slice // 2
                self.current_slices[view] = middle_slice
                self.slice_sliders[view].setRange(0, max_slice)
                self.slice_sliders[view].setValue(middle_slice)
                self.slice_sliders[view].setEnabled(True)
            self.update_2d_views()
            self.create_3d_view()

    def load_nifti_file(self, file_path):
        try:
            nifti_image = nib.load(file_path)
            self.image_data = nifti_image.get_fdata()

            # Handle incomplete data
            if len(self.image_data.shape) < 3:
                QMessageBox.warning(self, "Incomplete Data", "The NIFTI file appears to be incomplete. Some features may not work as expected.")
                # Pad the data to 3D if necessary
                while len(self.image_data.shape) < 3:
                    self.image_data = np.expand_dims(self.image_data, axis=-1)

            self.update_slice_sliders()
            self.update_2d_views()
            self.create_3d_view()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load NIFTI file: {str(e)}")


    def update_slice_sliders(self):
        if self.image_data is not None:
            for view, slider in self.slice_sliders.items():
                max_slice = self.image_data.shape[{"axial": 0, "sagittal": 2, "coronal": 1}[view]] - 1
                slider.setRange(0, max_slice)
                slider.setValue(self.current_slices[view])
                slider.setEnabled(True)

    def update_slice(self, view, value):
        if self.image_data is not None:
            max_slice = self.image_data.shape[{"axial": 0, "sagittal": 2, "coronal": 1}[view]] - 1
            self.current_slices[view] = max(0, min(value, max_slice))
            self.slice_sliders[view].setValue(self.current_slices[view])
            self.update_single_view(view)

    def update_2d_views(self):
        if self.image_data is not None:
            self.update_single_view("axial")
            self.update_single_view("sagittal")
            self.update_single_view("coronal")

    def display_2d_image(self, label, image, view):
        image = self.apply_brightness_contrast(image)

        # Invert coronal and sagittal views
        if view == "coronal":
            image = np.flipud(image)  # Flip vertically
        elif view == "sagittal":
            image = np.flipud(image)  # Flip both vertically and horizontally

        height, width = image.shape
        bytes_per_line = width

        # Convert the NumPy array to bytes
        image_bytes = image.tobytes()

        q_image = QImage(image_bytes, width, height, bytes_per_line, QImage.Format.Format_Grayscale8)
        pixmap = QPixmap.fromImage(q_image)

        label_size = label.size()
        scaled_size = pixmap.size()
        scaled_size.scale(label_size * self.zoom_factor, Qt.AspectRatioMode.KeepAspectRatio)

        scaled_pixmap = pixmap.scaled(scaled_size, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)

        # Calculate the visible portion of the image based on zoom and cursor position
        visible_width = label_size.width()
        visible_height = label_size.height()

        cursor_x, cursor_y = self.cursor_position[view].x(), self.cursor_position[view].y()

        # Calculate the top-left corner of the visible portion
        x = int((cursor_x * scaled_pixmap.width()) - (visible_width / 2))
        y = int((cursor_y * scaled_pixmap.height()) - (visible_height / 2))

        # Adjust x and y to keep the image within bounds
        x = max(0, min(x, scaled_pixmap.width() - visible_width))
        y = max(0, min(y, scaled_pixmap.height() - visible_height))

        # Crop the pixmap to the visible portion
        cropped_pixmap = scaled_pixmap.copy(x, y, visible_width, visible_height)

        label.setPixmap(cropped_pixmap)
        x_offset = (label_size.width() - scaled_pixmap.width()) // 2
        y_offset = (label_size.height() - scaled_pixmap.height()) // 2

        # Update crosshair position
        cursor_x, cursor_y = self.cursor_position[view].x(), self.cursor_position[view].y()
        label.crosshair_position = QPointF(cursor_x * scaled_pixmap.width() + x_offset,
                                           cursor_y * scaled_pixmap.height() + y_offset)
        label.update()

    def apply_brightness_contrast(self, image):
        """
        Adjust the brightness and contrast using gamma correction.
        - Brightness is applied as a gamma adjustment.
        - Contrast is applied as a scaling factor.
        """
        if np.max(image) != 0:
            image_normalized = image.astype(float) / np.max(image)
        else:
            image_normalized = image.astype(float)

        # Gamma correction for brightness (invert brightness to align with perception)
        gamma = 1 / self.brightness if self.brightness != 0 else 1
        image_bright = np.power(image_normalized, gamma)

        # Scaling for contrast adjustment
        contrast_factor = self.contrast
        image_contrasted = np.clip((image_bright - 0.5) * contrast_factor + 0.5, 0, 1)

        return (image_contrasted * 255).astype(np.uint8)

    def update_brightness_contrast(self):
        self.brightness = self.brightness_slider.value() / 100.0
        self.contrast = self.contrast_slider.value() / 100.0
        self.update_2d_views()

    def create_3d_view(self):
        if self.image_data is not None:
            dataImporter = vtk.vtkImageImport()
            data_string = self.image_data.astype(np.uint8).tobytes()
            dataImporter.CopyImportVoidPointer(data_string, len(data_string))
            dataImporter.SetDataScalarTypeToUnsignedChar()
            dataImporter.SetNumberOfScalarComponents(1)
            dataImporter.SetDataExtent(0, self.image_data.shape[2] - 1, 0, self.image_data.shape[1] - 1, 0,
                                       self.image_data.shape[0] - 1)
            dataImporter.SetWholeExtent(0, self.image_data.shape[2] - 1, 0, self.image_data.shape[1] - 1, 0,
                                        self.image_data.shape[0] - 1)

            volumeMapper = vtk.vtkGPUVolumeRayCastMapper()
            volumeMapper.SetInputConnection(dataImporter.GetOutputPort())

            volumeProperty = vtk.vtkVolumeProperty()
            volumeProperty.ShadeOn()
            volumeProperty.SetInterpolationTypeToLinear()

            compositeOpacity = vtk.vtkPiecewiseFunction()
            compositeOpacity.AddPoint(0.0, 0.0)
            compositeOpacity.AddPoint(80.0, 0.1)
            compositeOpacity.AddPoint(255.0, 0.2)
            volumeProperty.SetScalarOpacity(compositeOpacity)

            color = vtk.vtkColorTransferFunction()
            color.AddRGBPoint(0.0, 0.0, 0.0, 0.0)
            color.AddRGBPoint(64.0, 1.0, 0.0, 0.0)
            color.AddRGBPoint(128.0, 0.0, 0.0, 1.0)
            color.AddRGBPoint(192.0, 0.0, 1.0, 0.0)
            color.AddRGBPoint(255.0, 1.0, 1.0, 1.0)
            volumeProperty.SetColor(color)

            volume = vtk.vtkVolume()
            volume.SetMapper(volumeMapper)
            volume.SetProperty(volumeProperty)

            self.renderer.RemoveAllViewProps()
            self.renderer.AddVolume(volume)
            self.renderer.ResetCamera()

            self.view_3d.GetRenderWindow().Render()



    def handle_view_click(self, label, pos):
        if self.image_data is None:
            return

        view_name = self.get_view_name(label)
        x, y = pos.x(), pos.y()

        if self.pointer_mode:
            self.update_cursor_position(view_name, x, y)
        else:
            self.last_mouse_pos = pos
            self.is_dragging = True

    def handle_mouse_move(self, label, pos):
        if self.image_data is None:
            return

        view_name = self.get_view_name(label)

        if self.pointer_mode:
            if QApplication.mouseButtons() == Qt.MouseButton.LeftButton:
                x, y = pos.x(), pos.y()
                self.update_cursor_position(view_name, x, y)
        elif self.is_dragging:
            if self.last_mouse_pos is not None:
                dx = pos.x() - self.last_mouse_pos.x()
                dy = pos.y() - self.last_mouse_pos.y()
                self.brightness_slider.setValue(self.brightness_slider.value() + int(dx * 100))
                self.contrast_slider.setValue(self.contrast_slider.value() - int(dy * 100))
            self.last_mouse_pos = pos


    def toggle_pointer_hand_mode(self, checked):
        self.pointer_mode = not checked
        self.pointer_hand_button.setText("Hand Mode" if checked else "Pointer Mode")
        cursor = Qt.CursorShape.OpenHandCursor if checked else Qt.CursorShape.CrossCursor
        for view in [self.axial_view, self.sagittal_view, self.coronal_view]:
            view.setCursor(cursor)

        self.update_2d_views()


    def mouseReleaseEvent(self, event):
        self.is_dragging = False



    def create_cine_controls(self):
        cine_layout = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")
        cine_layout.addWidget(self.play_button)
        cine_layout.addWidget(self.pause_button)
        cine_layout.addWidget(self.stop_button)
        self.side_layout.addLayout(cine_layout)

        self.play_button.clicked.connect(self.start_cine)
        self.pause_button.clicked.connect(self.pause_cine)
        self.stop_button.clicked.connect(self.stop_cine)

        self.cine_timer = QTimer()
        self.cine_timer.timeout.connect(self.cine_scroll)

    def start_cine(self):
        if self.image_data is not None:
            self.cine_timer.start(100)  # Adjust speed as needed (100 ms interval)

    def pause_cine(self):
        self.cine_timer.stop()

    def stop_cine(self):
        self.cine_timer.stop()
        self.reset_slice_positions()

    def cine_scroll(self):
        if self.image_data is not None:
            for view in ["axial", "sagittal", "coronal"]:
                current_slice = self.current_slices[view]
                max_slice = self.image_data.shape[{"axial": 0, "sagittal": 2, "coronal": 1}[view]] - 1
                next_slice = (current_slice + 1) % (max_slice + 1)
                self.update_slice(view, next_slice)
            self.update_2d_views()

    def reset_slice_positions(self):
        if self.image_data is not None:
            for view in ["axial", "sagittal", "coronal"]:
                max_slice = self.image_data.shape[{"axial": 0, "sagittal": 2, "coronal": 1}[view]] - 1
                middle_slice = max_slice // 2
                self.update_slice(view, middle_slice)
            self.update_2d_views()

    def wheelEvent(self, event):
        if self.image_data is None:
            return

        delta = event.angleDelta().y()
        focused_view = self.get_focused_view()

        if self.pointer_mode:
            # Slice scrolling behavior for pointer mode
            slice_change = 1 if delta > 0 else -1
            current_slice = self.current_slices[focused_view]
            max_slice = self.image_data.shape[{"axial": 0, "sagittal": 2, "coronal": 1}[focused_view]] - 1
            new_slice = max(0, min(current_slice + slice_change, max_slice))
            self.current_slices[focused_view] = new_slice

            # Update the corresponding slider
            if focused_view in self.slice_sliders:
                self.slice_sliders[focused_view].setValue(new_slice)

            self.update_2d_views()
        else:
            # Zoom behavior for hand mode
            zoom_speed = 0.1  # Adjust this value to control zoom sensitivity
            view_widget = getattr(self, f"{focused_view}_view")

            # Get the cursor position relative to the view widget
            cursor_pos = view_widget.mapFromGlobal(QCursor.pos())

            # Calculate zoom center as a fraction of the widget size
            widget_size = view_widget.size()
            zoom_center = QPointF(cursor_pos.x() / widget_size.width(),
                                  cursor_pos.y() / widget_size.height())

            # Update zoom factor
            old_zoom = self.zoom_factor
            self.zoom_factor *= (1 + zoom_speed * (delta / 120))  # 120 is a typical "step" for mouse wheels
            self.zoom_factor = max(0.1, min(5.0, self.zoom_factor))  # Limit zoom range

            # Adjust cursor position to maintain zoom center
            for view in ["axial", "sagittal", "coronal"]:
                cursor_pos = self.cursor_position[view]
                new_x = (cursor_pos.x() * old_zoom + zoom_center.x() * (self.zoom_factor - old_zoom)) / self.zoom_factor
                new_y = (cursor_pos.y() * old_zoom + zoom_center.y() * (self.zoom_factor - old_zoom)) / self.zoom_factor
                self.cursor_position[view] = QPointF(new_x, new_y)

            # Update the display
            self.update_2d_views()

    def get_view_under_cursor(self, pos):
        for view, label in [("axial", self.axial_view), ("sagittal", self.sagittal_view),
                            ("coronal", self.coronal_view)]:
            if label.geometry().contains(label.mapFromGlobal(self.mapToGlobal(pos.toPoint()))):
                return view
        return None

    def reset_all(self):
        self.reset_view()
        self.reset_slice_positions()
        self.brightness_slider.setValue(100)
        self.contrast_slider.setValue(100)
        self.brightness = 1.0
        self.contrast = 1.0
        self.update_2d_views()

    def rotate_view(self, view):
        if self.image_data is not None:
            if view == "axial":
                self.image_data = np.rot90(self.image_data, axes=(1, 2))
            self.update_slice_sliders()
            self.update_2d_views()


    def get_focused_view(self):
        for view, label in [("axial", self.axial_view), ("sagittal", self.sagittal_view),
                            ("coronal", self.coronal_view)]:
            if label.underMouse():
                return view
        return self.current_view  # Default to axial if no view is focused



    def mouseMoveEvent(self, event):
        if self.image_data is None:
            return


        if not self.pointer_mode and event.buttons() == Qt.MouseButton.LeftButton:
            if self.last_mouse_pos is not None:
                dx = event.position().x() - self.last_mouse_pos.x()
                dy = event.position().y() - self.last_mouse_pos.y()
                self.brightness_slider.setValue(self.brightness_slider.value() + int(dx / 2))
                self.contrast_slider.setValue(self.contrast_slider.value() - int(dy / 2))


        self.last_mouse_pos = event.position()

def exception_hook(exctype, value, tb):
    print(''.join(traceback.format_exception(exctype, value, tb)))
    sys.exit(1)

sys.excepthook = exception_hook

if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        viewer = EnhancedMultiViewMedicalImageViewer()
        viewer.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"An error occurred: {e}")
        print(traceback.format_exc())