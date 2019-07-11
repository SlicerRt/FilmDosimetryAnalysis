# This Python file uses the following encoding: utf-8
import os
import unittest
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging
from FilmDosimetryAnalysisLogic import *
import DataProbeLib
from slicer.util import VTKObservationMixin
from vtk.util import numpy_support
import glob
from collections import OrderedDict

#
# Film dosimetry analysis slicelet
#
# Streamlined workflow end-user application based on 3D Slicer and SlicerRT to support
# 3D film-based radiation dosimetry.
#
# The all-caps terms correspond to data objects in the film dosimetry data flow diagram
# https://subversion.assembla.com/svn/slicerrt/trunk/FilmDosimetryAnalysis/doc/FilmDosimetryFlowchart.png
#

#
# FilmDosimetryAnalysisSliceletWidget
#
class FilmDosimetryAnalysisSliceletWidget:
  def __init__(self, parent=None):
    try:
      parent
      self.parent = parent

    except Exception as e:
      import traceback
      traceback.print_exc()
      logging.error("There is no parent to FilmDosimetryAnalysisSliceletWidget")

#
# SliceletMainFrame
#   Handles the event when the slicelet is hidden (its window closed)
#
class SliceletMainFrame(qt.QDialog):
  def setSlicelet(self, slicelet):
    self.slicelet = slicelet

  def hideEvent(self, event):
    self.slicelet.disconnect()

    import gc
    refs = gc.get_referrers(self.slicelet)
    if len(refs) > 1:
      # logging.debug('Stuck slicelet references (' + repr(len(refs)) + '):\n' + repr(refs))
      pass

    slicer.filmDosimetrySliceletInstance = None
    self.slicelet = None
    self.deleteLater()

#
# FilmDosimetryAnalysisSlicelet
#
class FilmDosimetryAnalysisSlicelet(VTKObservationMixin):
  def __init__(self, parent, developerMode=False, widgetClass=None):
    VTKObservationMixin.__init__(self)

    # Set up main frame
    self.parent = parent
    self.parent.setLayout(qt.QHBoxLayout())

    self.layout = self.parent.layout()
    self.layout.setMargin(0)
    self.layout.setSpacing(0)

    self.sliceletPanel = qt.QFrame(self.parent)
    self.sliceletPanelLayout = qt.QVBoxLayout(self.sliceletPanel)
    self.sliceletPanelLayout.setMargin(4)
    self.sliceletPanelLayout.setSpacing(0)
    self.layout.addWidget(self.sliceletPanel,1)

    # For testing only (it is only visible when in developer mode)
    self.selfTestButton = qt.QPushButton("Run self-test")
    self.sliceletPanelLayout.addWidget(self.selfTestButton)
    self.selfTestButton.connect('clicked()', self.onSelfTestButtonClicked)
    self.selfTestButton.setVisible(developerMode)

    # Initiate and group together all panels
    self.step0_layoutSelectionCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_calibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_loadExperimentalDataCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step3_applyCalibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step4_registrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step5_doseComparisonCollapsibleButton = ctk.ctkCollapsibleButton()
    self.stepT1_lineProfileCollapsibleButton = ctk.ctkCollapsibleButton()
    self.testButton = ctk.ctkCollapsibleButton()

    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.step0_layoutSelectionCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step1_calibrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step2_loadExperimentalDataCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step3_applyCalibrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step4_registrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step5_doseComparisonCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.stepT1_lineProfileCollapsibleButton)

    self.collapsibleButtonsGroup.addButton(self.testButton)

    self.step1_calibrationCollapsibleButton.setProperty('collapsed', False)

    # Create module logic
    self.logic = FilmDosimetryAnalysisLogic()

    # Declare member variables (selected at certain steps and then from then on for the workflow)
    self.lastAddedFolder = 0
    self.opticalDensityCurve = None

    # Constants
    self.maxNumberOfCalibrationFilms = 10

    # Set observations
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    self.addObserver(shNode, slicer.vtkMRMLSubjectHierarchyNode.SubjectHierarchyItemAddedEvent, self.onSubjectHierarchyItemAdded)
    self.addObserver(shNode, slicer.vtkMRMLSubjectHierarchyNode.SubjectHierarchyEndResolveEvent, self.onSubjectHierarchyResolveEnded)
    self.addObserver(slicer.mrmlScene, slicer.vtkMRMLScene.NodeAddedEvent, self.onNodeAdded)

    # Turn on slice intersections in 2D viewers
    compositeNodes = slicer.util.getNodes("vtkMRMLSliceCompositeNode*")
    for compositeNode in compositeNodes.values():
      compositeNode.SetSliceIntersectionVisibility(1)

    # Add layout widget
    self.layoutWidget = slicer.qMRMLLayoutWidget()
    self.layoutWidget.setMRMLScene(slicer.mrmlScene)
    self.parent.layout().addWidget(self.layoutWidget,2)
    self.onViewSelect(0)

    # Create slice annotations for scalar bar support
    self.sliceAnnotations = DataProbeLib.SliceAnnotations(self.layoutWidget.layoutManager())
    self.sliceAnnotations.scalarBarEnabled = 0
    self.sliceAnnotations.updateSliceViewFromGUI()

    # Create line profile logic
    self.lineProfileLogic = LineProfileLogic()

    # Set up step panels
    self.setup_Step0_LayoutSelection()
    self.setup_Step1_Calibration()
    self.setup_Step2_LoadExperimentalData()
    self.setup_Step3_ApplyCalibration()
    self.setup_Step4_Registration()
    self.setup_Step5_GammaComparison()
    self.setup_StepT1_lineProfileCollapsibleButton()

    # Set minimum width to the maximum of the size hints to prevent jumping of the left panel which causes a possibly lengthy update of the views layout
    maximumSectionSizeHintWidth = max(self.step0_layoutSelectionCollapsibleButton.sizeHint.width(), self.step1_calibrationCollapsibleButton.sizeHint.width(), self.step2_loadExperimentalDataCollapsibleButton.sizeHint.width(), self.step3_applyCalibrationCollapsibleButton.sizeHint.width(), self.step4_registrationCollapsibleButton.sizeHint.width(), self.step5_doseComparisonCollapsibleButton.sizeHint.width())
    self.sliceletPanel.setMinimumWidth(maximumSectionSizeHintWidth)

    if widgetClass:
      self.widget = widgetClass(self.parent)
    self.parent.show()

  #------------------------------------------------------------------------------
  # Disconnect all connections made to the slicelet to enable the garbage collector to destruct the slicelet object on quit
  def disconnect(self):
    self.selfTestButton.disconnect('clicked()', self.onSelfTestButtonClicked)
    self.step0_viewSelectorComboBox.disconnect('currentIndexChanged(int)', self.onViewSelect)
    self.step1_loadImageFilesButton.disconnect('clicked()', self.onLoadImageFilesButton)
    self.step1_numberOfCalibrationFilmsSpinBox.disconnect('valueChanged(int)', self.onNumberOfCalibrationFilmsSpinBoxValueChanged)
    self.step1_saveCalibrationBatchButton.disconnect('clicked()', self.onSaveCalibrationBatchButton)
    self.step1_loadCalibrationBatchButton.disconnect('clicked()', self.onLoadCalibrationBatchButton)
    self.step1_saveCalibrationFunctionToFileButton.disconnect('clicked()', self.onSaveCalibrationFunctionToFileButton)
    self.step1_addRoiButton.disconnect('clicked()', self.onAddRoiButton)
    self.step1_calibrationCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep1_calibrationCollapsed)
    self.step1_2_performCalibrationCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep1_2_performCalibrationCollapsed)
    self.step1_performCalibrationButton.disconnect('clicked()', self.onPerformCalibrationButton)
    self.step2_loadNonDicomDataButton.disconnect('clicked()', self.onLoadImageFilesButton)
    self.step2_showDicomBrowserButton.disconnect('clicked()', self.onDicomLoad)
    self.step2_experimentalFilmSliceOrientationComboBox.disconnect('currentIndexChanged(QString)', self.onExperimentalFilmSliceOrientationChanged)
    self.step2_experimentalFilmSlicePositionSpinBox.disconnect('valueChanged(double)', self.onExperimentalFilmSlicePositionChanged)
    self.step2_experimentalFilmSpacingLineEdit.disconnect('textChanged(QString)', self.onExperimentalFilmSpacingChanged)
    self.step2_loadExperimentalDataCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_loadExperimentalDataCollapsed)
    self.step3_calibrationFunctionOrder0LineEdit.disconnect('textChanged()', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionOrder1LineEdit.disconnect('textChanged()', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionOrder2LineEdit.disconnect('textChanged()', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionExponentLineEdit.disconnect('textChanged()', self.onCalibrationFunctionLineEditChanged)
    self.step3_applyCalibrationButton.disconnect('clicked()', self.onApplyCalibrationButton)
    self.step3_loadCalibrationButton.disconnect('clicked()', self.onLoadCalibrationFunctionFromFileButton)
    self.step3_applyCalibrationCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep3_ApplyCalibrationCollapsed)
    self.step4_performRegistrationButton.disconnect('clicked()', self.onPerformRegistrationButtonClicked)
    self.step4_registrationCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep4_RegistrationCollapsed)
    self.step4_rotateCcwButton.disconnect('clicked()', self.onStep4_RotateCcw90)
    self.step4_rotateCcwAction_5Degrees.disconnect('triggered()', self.onStep4_RotateCcw5)
    self.step4_rotateCwButton.disconnect('clicked()', self.onStep4_RotateCw90)
    self.step4_rotateCwAction_5Degrees.disconnect('triggered()', self.onStep4_RotateCw5)
    self.step4_flipHorizontalButton.disconnect('clicked()', self.onStep4_FlipHorizontal)
    self.step4_flipVerticalButton.disconnect('clicked()', self.onStep4_FlipVertical)
    self.step4_translationSliders.disconnect('valuesChanged()', self.step4_rotationSliders.resetUnactiveSliders)
    self.step5_doseComparisonCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep5_DoseComparisonCollapsed)
    self.step5_maskSegmentationSelector.disconnect('currentNodeChanged(vtkMRMLNode*)', self.onStep5_MaskSegmentationSelectionChanged)
    self.step5_maskSegmentationSelector.disconnect('currentSegmentChanged(QString)', self.onStep5_MaskSegmentSelectionChanged)
    self.step5_referenceDoseUseMaximumDoseRadioButton.disconnect('toggled(bool)', self.onUseMaximumDoseRadioButtonToggled)
    self.step5_computeGammaButton.disconnect('clicked()', self.onGammaDoseComparison)
    self.step5_showGammaReportButton.disconnect('clicked()', self.onShowGammaReport)
    self.stepT1_lineProfileCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStepT1_LineProfileCollapsed)
    self.stepT1_lineProfileLegendVisibilityCheckbox.disconnect('toggled(bool)', self.onLegendVisibilityToggled)
    self.stepT1_createLineProfileButton.disconnect('clicked(bool)', self.onCreateLineProfileButton)
    self.stepT1_inputRulerSelector.disconnect("currentNodeChanged(vtkMRMLNode*)", self.onSelectLineProfileParameters)
    self.stepT1_exportLineProfilesToCSV.disconnect('clicked()', self.onExportLineProfiles)

    # Remove scene observations
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    self.removeObserver(shNode, slicer.vtkMRMLSubjectHierarchyNode.SubjectHierarchyItemAddedEvent, self.onSubjectHierarchyItemAdded)
    self.removeObserver(shNode, slicer.vtkMRMLSubjectHierarchyNode.SubjectHierarchyEndResolveEvent, self.onSubjectHierarchyResolveEnded)
    self.removeObserver(slicer.mrmlScene, slicer.vtkMRMLScene.NodeAddedEvent, self.onNodeAdded)

  #------------------------------------------------------------------------------
  def setup_Step0_LayoutSelection(self):
    # Layout selection step
    self.step0_layoutSelectionCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step0_layoutSelectionCollapsibleButton.text = "Layout selector"
    # self.step0_layoutSelectionCollapsibleButton.text = "Layout and mode selector"
    self.sliceletPanelLayout.addWidget(self.step0_layoutSelectionCollapsibleButton)
    self.step0_layoutSelectionCollapsibleButtonLayout = qt.QFormLayout(self.step0_layoutSelectionCollapsibleButton)
    self.step0_layoutSelectionCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step0_layoutSelectionCollapsibleButtonLayout.setSpacing(4)

    self.step0_viewSelectorComboBox = qt.QComboBox(self.step0_layoutSelectionCollapsibleButton)
    self.step0_viewSelectorComboBox.addItem("Four-up 3D + 3x2D view")
    self.step0_viewSelectorComboBox.addItem("Conventional 3D + 3x2D view")
    self.step0_viewSelectorComboBox.addItem("3D-only view")
    self.step0_viewSelectorComboBox.addItem("Axial slice only view")
    self.step0_viewSelectorComboBox.addItem("Double 3D view")
    self.step0_viewSelectorComboBox.addItem("Four-up plus plot view")
    self.step0_viewSelectorComboBox.addItem("Plot only view")
    self.step0_layoutSelectionCollapsibleButtonLayout.addRow("Layout: ", self.step0_viewSelectorComboBox)
    self.step0_viewSelectorComboBox.connect('currentIndexChanged(int)', self.onViewSelect)

    # Mode Selector: Radio-buttons
    self.step0_modeSelectorLayout = qt.QGridLayout()
    self.step0_modeSelectorLabel = qt.QLabel('Select mode: ')
    self.step0_modeSelectorLayout.addWidget(self.step0_modeSelectorLabel, 0, 0, 1, 1)
    self.step0_clinicalModeRadioButton = qt.QRadioButton('Clinical optical readout')
    self.step0_clinicalModeRadioButton.setChecked(True)
    self.step0_modeSelectorLayout.addWidget(self.step0_clinicalModeRadioButton, 0, 1)
    self.step0_preclinicalModeRadioButton = qt.QRadioButton('Preclinical MRI readout')
    self.step0_modeSelectorLayout.addWidget(self.step0_preclinicalModeRadioButton, 0, 2)

  #------------------------------------------------------------------------------
  def setup_Step1_Calibration(self):
    # Step 1: Calibration
    self.step1_calibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_calibrationCollapsibleButton.text = "1. Calibration (optional)"
    self.sliceletPanelLayout.addWidget(self.step1_calibrationCollapsibleButton)

    # Step 1 main background layout
    self.step1_calibrationLayout = qt.QVBoxLayout(self.step1_calibrationCollapsibleButton)

    #
    # Step 1.1: Load calibration data
    self.step1_1_loadCalibrationDataCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_1_loadCalibrationDataCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_1_loadCalibrationDataCollapsibleButton.text = "1.1. Load calibration data"
    self.step1_calibrationLayout.addWidget(self.step1_1_loadCalibrationDataCollapsibleButton)

    self.step1_1_loadCalibrationDataLayout = qt.QVBoxLayout(self.step1_1_loadCalibrationDataCollapsibleButton)
    self.step1_1_loadCalibrationDataLayout.setContentsMargins(12,4,4,4)
    self.step1_1_loadCalibrationDataLayout.setSpacing(4)

    #
    # Step 1.1 top sub-layout (the calibration films table needs to be updated within its own layout)
    self.step1_1_topCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_1_loadCalibrationDataLayout.addLayout(self.step1_1_topCalibrationSubLayout)

    # Load data label
    self.step1_CalibrationLabel = qt.QLabel("Load calibration images (can be a new batch of images or a saved batch)")
    self.step1_CalibrationLabel.wordWrap = True
    self.step1_1_topCalibrationSubLayout.addWidget(self.step1_CalibrationLabel)

    # Load image data button
    self.step1_loadImageFilesButton = qt.QPushButton("Load image files")
    self.step1_loadImageFilesButton.toolTip = "Load calibration and flood field images.\nUsed for creating a new calibration batch"
    self.step1_loadImageFilesButton.name = "loadImageFilesButton"
    # Load saved image batch button
    self.step1_loadCalibrationBatchButton = qt.QPushButton("Load calibration batch")
    self.step1_loadCalibrationBatchButton.toolTip = "Load a saved batch of calibration films"
    self.step1_loadCalibrationBatchButton.name = "loadCalibrationFilesButton"
    # Horizontal button layout
    self.step1_loadImageButtonLayout = qt.QHBoxLayout()
    self.step1_loadImageButtonLayout.addWidget(self.step1_loadImageFilesButton)
    self.step1_loadImageButtonLayout.addWidget(self.step1_loadCalibrationBatchButton)

    self.step1_1_topCalibrationSubLayout.addLayout(self.step1_loadImageButtonLayout)

    # Add empty row
    self.step1_1_topCalibrationSubLayout.addWidget(qt.QLabel(''))

    # Assign data label
    self.step1_assignDosesLabel = qt.QLabel("Assign dose levels to films.\nNote: If selection is changed then all the following steps need to be performed again")
    self.step1_assignDosesLabel.wordWrap = True
    self.step1_1_topCalibrationSubLayout.addWidget(self.step1_assignDosesLabel)

    # Number of calibration films node selector
    self.step1_numberOfCalibrationFilmsSelectorLayout = qt.QHBoxLayout()
    self.step1_numberOfCalibrationFilmsSpinBox = qt.QSpinBox()
    self.step1_numberOfCalibrationFilmsSpinBox.value = 5
    self.step1_numberOfCalibrationFilmsSpinBox.minimum = 1
    self.step1_numberOfCalibrationFilmsSpinBox.maximum = 10
    self.step1_numberOfCalibrationFilmsSpinBox.enabled = True
    self.step1_numberOfCalibrationFilmsLabelBefore = qt.QLabel('Number of calibration films: ')
    self.step1_numberOfCalibrationFilmsSelectorLayout.addWidget(self.step1_numberOfCalibrationFilmsLabelBefore)
    self.step1_numberOfCalibrationFilmsSelectorLayout.addWidget(self.step1_numberOfCalibrationFilmsSpinBox)
    self.step1_1_topCalibrationSubLayout.addLayout(self.step1_numberOfCalibrationFilmsSelectorLayout)

    # Choose the flood field image
    self.step1_floodFieldImageSelectorComboBoxLayout = qt.QHBoxLayout()
    self.step1_floodFieldImageSelectorComboBox = slicer.qMRMLNodeComboBox()
    self.step1_floodFieldImageSelectorComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_floodFieldImageSelectorComboBox.addEnabled = True
    self.step1_floodFieldImageSelectorComboBox.removeEnabled = True
    self.step1_floodFieldImageSelectorComboBox.setMRMLScene( slicer.mrmlScene )
    self.step1_floodFieldImageSelectorComboBox.setToolTip( "Choose the flood field image" )
    self.step1_floodFieldImageSelectorComboBoxLabel = qt.QLabel('Flood field image: ')
    self.step1_floodFieldImageSelectorComboBoxLayout.addWidget(self.step1_floodFieldImageSelectorComboBoxLabel)
    self.step1_floodFieldImageSelectorComboBoxLayout.addWidget(self.step1_floodFieldImageSelectorComboBox)
    self.step1_1_topCalibrationSubLayout.addLayout(self.step1_floodFieldImageSelectorComboBoxLayout)

    #
    # Step 1.1 middle sub-layout (the calibration films table needs to be updated within its own layout)
    self.step1_1_middleCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_1_loadCalibrationDataLayout.addLayout(self.step1_1_middleCalibrationSubLayout)

    self.step1_calibrationVolumeLayoutList = []
    self.step1_calibrationVolumeSelectorLabelBeforeList = []
    self.step1_calibrationVolumeSelectorCGySpinBoxList = []
    self.step1_calibrationVolumeSelectorCGyLabelList = []
    self.step1_calibrationVolumeSelectorComboBoxList = []

    # Create calibration films table
    for doseToImageLayoutNumber in range(self.maxNumberOfCalibrationFilms):
      self.step1_doseToImageSelectorRowLayout = qt.QHBoxLayout()
      self.step1_mainCalibrationVolumeSelectorLabelBefore = qt.QLabel('Calibration ')
      self.step1_calibrationVolumeSelectorLabelBeforeList.append(self.step1_mainCalibrationVolumeSelectorLabelBefore)

      self.doseToImageSelectorCGySpinBox = qt.QSpinBox()
      self.doseToImageSelectorCGySpinBox.minimum = 0
      self.doseToImageSelectorCGySpinBox.maximum = 10000
      self.step1_calibrationVolumeSelectorCGySpinBoxList.append(self.doseToImageSelectorCGySpinBox)

      self.doseToImageSelectorLabelMiddle = qt.QLabel(' cGy : ')
      self.step1_calibrationVolumeSelectorCGyLabelList.append(self.doseToImageSelectorLabelMiddle)

      self.doseToImageFilmSelector = slicer.qMRMLNodeComboBox()
      self.doseToImageFilmSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
      self.doseToImageFilmSelector.addEnabled = False
      self.doseToImageFilmSelector.removeEnabled = False
      self.doseToImageFilmSelector.setMRMLScene( slicer.mrmlScene )
      self.doseToImageFilmSelector.setToolTip("Choose the film image corresponding to the dose on the left")
      self.step1_calibrationVolumeSelectorComboBoxList.append(self.doseToImageFilmSelector)

      self.step1_doseToImageSelectorRowLayout.addWidget(self.step1_mainCalibrationVolumeSelectorLabelBefore)
      self.step1_doseToImageSelectorRowLayout.addWidget(self.doseToImageSelectorCGySpinBox)
      self.step1_doseToImageSelectorRowLayout.addWidget(self.doseToImageSelectorLabelMiddle)
      self.step1_doseToImageSelectorRowLayout.addWidget(self.doseToImageFilmSelector)

      self.step1_calibrationVolumeLayoutList.append(self.step1_doseToImageSelectorRowLayout)
      self.step1_1_middleCalibrationSubLayout.addLayout(self.step1_doseToImageSelectorRowLayout)

    #
    # Step 1.1 bottom sub-layout (the calibration films table needs to be updated within its own layout)
    self.step1_1_bottomCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_1_loadCalibrationDataLayout.addLayout(self.step1_1_bottomCalibrationSubLayout)

    # Save batch button
    self.step1_saveCalibrationBatchButton = qt.QPushButton("Save calibration batch")
    self.step1_saveCalibrationBatchButton.toolTip = "Saves current calibration batch"
    self.step1_1_bottomCalibrationSubLayout.addWidget(self.step1_saveCalibrationBatchButton)

    # Add empty row
    self.step1_1_bottomCalibrationSubLayout.addWidget(qt.QLabel(''))

    #
    # Step 1.2: Perform calibration
    self.step1_2_performCalibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_2_performCalibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_2_performCalibrationCollapsibleButton.text = "1.2. Perform calibration"
    self.step1_calibrationLayout.addWidget(self.step1_2_performCalibrationCollapsibleButton)
    self.step1_2_performCalibrationLayout = qt.QVBoxLayout(self.step1_2_performCalibrationCollapsibleButton)
    self.step1_2_performCalibrationLayout.setContentsMargins(12,4,4,4)
    self.step1_2_performCalibrationLayout.setSpacing(4)

    # Add ROI button
    self.step1_addRoiButton = qt.QPushButton("Add region")
    self.step1_addRoiButton.setIcon(qt.QIcon(":/Icons/AnnotationROIWithArrow.png"))
    self.step1_addRoiButton.toolTip = "Add ROI (region of interest) that is considered when measuring dose in the calibration images\n\nOnce activated, click in the center of the region to be used for calibration, then do another click to one of the corners. After that the ROI appears and can be adjusted using the colored handles."
    self.step1_2_performCalibrationLayout.addWidget(self.step1_addRoiButton)

    # Calibration button
    self.step1_performCalibrationButton = qt.QPushButton("Perform calibration")
    self.step1_performCalibrationButton.toolTip = "Finds the calibration function"
    self.step1_2_performCalibrationLayout.addWidget(self.step1_performCalibrationButton)

    # Calibration function
    self.step1_calibrationFunctionLabel = qt.QLabel('Optical density to dose calibration function: ')
    self.step1_2_performCalibrationLayout.addWidget(self.step1_calibrationFunctionLabel)

    self.step1_2_performCalibrationLayout.addWidget(qt.QLabel(''))

    # Dose calibration function label
    self.step1_2_performCalibrationFunctionLabel = qt.QLabel(" ")
    self.step1_2_performCalibrationLayout.addWidget(self.step1_2_performCalibrationFunctionLabel)

    self.step1_2_performCalibrationLayout.addWidget(qt.QLabel(''))

    # Save calibration function button
    self.step1_saveCalibrationFunctionToFileButton = qt.QPushButton("Save calibration function to file")
    self.step1_saveCalibrationFunctionToFileButton.toolTip = "Save calibration function for later use"
    self.step1_2_performCalibrationLayout.addWidget(self.step1_saveCalibrationFunctionToFileButton)

    self.step1_2_performCalibrationLayout.addStretch(1)

    # Step 1 sub button group
    self.step1_calibrationCollapsibleButtonGroup = qt.QButtonGroup()
    self.step1_calibrationCollapsibleButtonGroup.addButton(self.step1_1_loadCalibrationDataCollapsibleButton)
    self.step1_calibrationCollapsibleButtonGroup.addButton(self.step1_2_performCalibrationCollapsibleButton)

    self.step1_1_loadCalibrationDataCollapsibleButton.setProperty('collapsed', False)

    # Update calibration films table to set row visibilities
    self.setNumberOfCalibrationFilmsInTable(self.step1_numberOfCalibrationFilmsSpinBox.value)

    # Connections
    self.step1_loadImageFilesButton.connect('clicked()', self.onLoadImageFilesButton)
    self.step1_saveCalibrationBatchButton.connect('clicked()', self.onSaveCalibrationBatchButton)
    self.step1_loadCalibrationBatchButton.connect('clicked()', self.onLoadCalibrationBatchButton)
    self.step1_numberOfCalibrationFilmsSpinBox.connect('valueChanged(int)', self.onNumberOfCalibrationFilmsSpinBoxValueChanged)
    self.step1_addRoiButton.connect('clicked()', self.onAddRoiButton)
    self.step1_performCalibrationButton.connect('clicked()', self.onPerformCalibrationButton)
    self.step1_saveCalibrationFunctionToFileButton.connect('clicked()', self.onSaveCalibrationFunctionToFileButton)
    self.step1_calibrationCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep1_calibrationCollapsed)
    self.step1_2_performCalibrationCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep1_2_performCalibrationCollapsed)

  #------------------------------------------------------------------------------
  def setup_Step2_LoadExperimentalData(self):
    # Step 2: Load experimental data
    self.step2_loadExperimentalDataCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_loadExperimentalDataCollapsibleButton.text = "2. Load experimental data"
    self.sliceletPanelLayout.addWidget(self.step2_loadExperimentalDataCollapsibleButton)

    self.step2_loadExperimentalDataCollapsibleButtonLayout = qt.QVBoxLayout(self.step2_loadExperimentalDataCollapsibleButton)
    self.step2_loadExperimentalDataCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step2_loadExperimentalDataCollapsibleButtonLayout.setSpacing(4)

    # Load data label
    self.step2_LoadDataLabel = qt.QLabel("Load all data involved in the workflow.\nNote: Can return to this step later if more data needs to be loaded")
    self.step2_LoadDataLabel.wordWrap = True
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(self.step2_LoadDataLabel)

    # Load DICOM data button
    self.step2_showDicomBrowserButton = qt.QPushButton("Load DICOM data")
    self.step2_showDicomBrowserButton.toolTip = "Load planning data (CT, dose, structures)"
    self.step2_showDicomBrowserButton.name = "showDicomBrowserButton"
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(self.step2_showDicomBrowserButton)

    # Load non-DICOM data button
    self.step2_loadNonDicomDataButton = qt.QPushButton("Load experimental film data from file")
    self.step2_loadNonDicomDataButton.toolTip = "Load experimental film image from PNG, etc."
    self.step2_loadNonDicomDataButton.name = "loadNonDicomDataButton"
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(self.step2_loadNonDicomDataButton)

    # Add empty row
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(qt.QLabel(""))

    # Assign loaded data to roles
    self.step2_assignDataLabel = qt.QLabel("Assign loaded data to roles.\nNote: If this selection is changed later then all the following steps need to be performed again")
    self.step2_assignDataLabel.wordWrap = True
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(self.step2_assignDataLabel)

    self.step2_assignDataLayout = qt.QFormLayout(self.step0_layoutSelectionCollapsibleButton)
    self.step2_assignDataLayout.setSpacing(4)

    # Experimental film image selector
    self.step2_experimentalFilmSelectorComboBox = slicer.qMRMLNodeComboBox()
    self.step2_experimentalFilmSelectorComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step2_experimentalFilmSelectorComboBox.addEnabled = False
    self.step2_experimentalFilmSelectorComboBox.removeEnabled = False
    self.step2_experimentalFilmSelectorComboBox.setMRMLScene(slicer.mrmlScene)
    self.step2_experimentalFilmSelectorComboBox.toolTip = "Select the experimental film image"
    self.step2_assignDataLayout.addRow('Experimental film image: ', self.step2_experimentalFilmSelectorComboBox)

    # Experimental film resolution mm/pixel
    self.step2_experimentalFilmSpacingLineEdit = qt.QLineEdit()
    self.step2_experimentalFilmSpacingLineEdit.toolTip = "Experimental film pixel spacing in mm (isotropic)"
    self.step2_assignDataLayout.addRow('  Experimental film resolution (mm/pixel): ', self.step2_experimentalFilmSpacingLineEdit)

    # Experimental film slice position
    self.step2_experimentalFilmSlicePositionWidget = qt.QWidget()
    self.step2_experimentalFilmSlicePositionSpinBox = qt.QDoubleSpinBox()
    self.step2_experimentalFilmSlicePositionSpinBox.value = 0.0
    self.step2_experimentalFilmSlicePositionSpinBox.minimum = -10000.0
    self.step2_experimentalFilmSlicePositionSpinBox.maximum = 10000.0
    self.step2_experimentalFilmSlicePositionSpinBox.singleStep = 10.0
    self.step2_experimentalFilmSliceOrientationLabel = qt.QLabel('mm, orientation: ')
    self.step2_experimentalFilmSliceOrientationComboBox = qt.QComboBox()
    self.step2_experimentalFilmSliceOrientationComboBox.addItem(AXIAL)
    self.step2_experimentalFilmSliceOrientationComboBox.addItem(CORONAL)
    self.step2_experimentalFilmSliceOrientationComboBox.addItem(SAGITTAL)
    self.step2_experimentalFilmSlicePositionWidgetLayout = qt.QHBoxLayout(self.step2_experimentalFilmSlicePositionWidget)
    self.step2_experimentalFilmSlicePositionWidgetLayout.spacing = 4
    self.step2_experimentalFilmSlicePositionWidgetLayout.margin = 0
    self.step2_experimentalFilmSlicePositionWidgetLayout.addWidget(self.step2_experimentalFilmSlicePositionSpinBox)
    self.step2_experimentalFilmSlicePositionWidgetLayout.addWidget(self.step2_experimentalFilmSliceOrientationLabel)
    self.step2_experimentalFilmSlicePositionWidgetLayout.addWidget(self.step2_experimentalFilmSliceOrientationComboBox)
    self.step2_assignDataLayout.addRow('  Experimental film slice position: ', self.step2_experimentalFilmSlicePositionWidget)
    # Set default to CORONAL
    self.step2_experimentalFilmSliceOrientationComboBox.currentIndex = 1
    self.onExperimentalFilmSliceOrientationChanged(CORONAL)

    # Experimental flood field image selector
    self.step2_floodFieldImageSelectorComboBox = slicer.qMRMLNodeComboBox()
    self.step2_floodFieldImageSelectorComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step2_floodFieldImageSelectorComboBox.addEnabled = False
    self.step2_floodFieldImageSelectorComboBox.removeEnabled = False
    self.step2_floodFieldImageSelectorComboBox.setMRMLScene(slicer.mrmlScene)
    self.step2_floodFieldImageSelectorComboBox.toolTip = "Select flood film image for experimental film"
    self.step2_assignDataLayout.addRow('Flood field image (for experimental film): ', self.step2_floodFieldImageSelectorComboBox)

    # Plan dose volume selector
    self.step2_planDoseVolumeSelector = slicer.qMRMLNodeComboBox()
    self.step2_planDoseVolumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step2_planDoseVolumeSelector.addEnabled = False
    self.step2_planDoseVolumeSelector.removeEnabled = False
    self.step2_planDoseVolumeSelector.setMRMLScene(slicer.mrmlScene)
    self.step2_planDoseVolumeSelector.setToolTip("Select the planning dose volume")
    self.step2_assignDataLayout.addRow('Dose volume: ', self.step2_planDoseVolumeSelector)

    self.step2_loadExperimentalDataCollapsibleButtonLayout.addLayout(self.step2_assignDataLayout)

    self.step2_loadExperimentalDataCollapsibleButtonLayout.addStretch(1)

    # Connections
    self.step2_loadNonDicomDataButton.connect('clicked()', self.onLoadImageFilesButton)
    self.step2_showDicomBrowserButton.connect('clicked()', self.onDicomLoad)
    self.step2_experimentalFilmSpacingLineEdit.connect('textChanged(QString)', self.onExperimentalFilmSpacingChanged)
    self.step2_experimentalFilmSlicePositionSpinBox.connect('valueChanged(double)', self.onExperimentalFilmSlicePositionChanged)
    self.step2_experimentalFilmSliceOrientationComboBox.connect('currentIndexChanged(QString)', self.onExperimentalFilmSliceOrientationChanged)
    self.step2_loadExperimentalDataCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep2_loadExperimentalDataCollapsed)

  #------------------------------------------------------------------------------
  def setup_Step3_ApplyCalibration(self):
    # Step 3: Apply calibration
    self.step3_applyCalibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step3_applyCalibrationCollapsibleButton.text = "3. Apply calibration"
    self.sliceletPanelLayout.addWidget(self.step3_applyCalibrationCollapsibleButton)

    self.step3_applyCalibrationCollapsibleButtonLayout = qt.QVBoxLayout(self.step3_applyCalibrationCollapsibleButton)
    self.step3_applyCalibrationCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step3_applyCalibrationCollapsibleButtonLayout.setSpacing(4)

    # Load calibration function button
    self.step3_loadCalibrationButton = qt.QPushButton("Load calibration function from file")
    self.step3_loadCalibrationButton.toolTip = "Loads calibration function \n Function can also be added into text fields"
    self.step3_applyCalibrationCollapsibleButtonLayout.addWidget(self.step3_loadCalibrationButton)

    # Dose calibration function input fields
    self.step3_calibrationFunctionLayout = qt.QGridLayout()
    self.step3_doseLabel = qt.QLabel('Dose (cGy) = ')
    self.step3_calibrationFunctionOrder0LineEdit = qt.QLineEdit()
    self.step3_calibrationFunctionOrder0LineEdit.maximumWidth = 64
    self.step3_calibrationFunctionOrder0Label = qt.QLabel(' + ')
    self.step3_calibrationFunctionOrder1LineEdit = qt.QLineEdit()
    self.step3_calibrationFunctionOrder1LineEdit.maximumWidth = 64
    self.step3_calibrationFunctionOrder1Label = qt.QLabel(' OD + ')
    self.step3_calibrationFunctionOrder2LineEdit = qt.QLineEdit()
    self.step3_calibrationFunctionOrder2LineEdit.maximumWidth = 64
    self.step3_calibrationFunctionOrder2Label = qt.QLabel(' OD ^ ')
    self.step3_calibrationFunctionExponentLineEdit = qt.QLineEdit()
    self.step3_calibrationFunctionExponentLineEdit.maximumWidth = 42

    self.step3_calibrationFunctionLayout.addWidget(self.step3_doseLabel,0,0)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder0LineEdit,0,1)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder0Label,0,2)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder1LineEdit,0,3)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder1Label,0,4)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder2LineEdit,1,1)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder2Label,1,2)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionExponentLineEdit,1,3)
    self.step3_applyCalibrationCollapsibleButtonLayout.addLayout(self.step3_calibrationFunctionLayout)

    # Add empty row
    self.step3_applyCalibrationCollapsibleButtonLayout.addWidget(qt.QLabel(''))

    # Apply calibration button
    self.step3_applyCalibrationButton = qt.QPushButton("Apply calibration on experimental film")
    self.step3_applyCalibrationButton.toolTip = "Apply calibration to experimental film."
    self.step3_applyCalibrationCollapsibleButtonLayout.addWidget(self.step3_applyCalibrationButton)

    # Add empty row
    self.step3_applyCalibrationCollapsibleButtonLayout.addWidget(qt.QLabel(''))
    # Add message label
    self.step3_calibrationMessageLabel = qt.QLabel('')
    self.step3_applyCalibrationCollapsibleButtonLayout.addWidget(self.step3_calibrationMessageLabel)

    self.step3_applyCalibrationCollapsibleButtonLayout.addStretch(1)

    # Connections
    self.step3_applyCalibrationButton.connect('clicked()', self.onApplyCalibrationButton)
    self.step3_loadCalibrationButton.connect('clicked()', self.onLoadCalibrationFunctionFromFileButton)
    self.step3_calibrationFunctionOrder0LineEdit.connect('textChanged(QString)', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionOrder1LineEdit.connect('textChanged(QString)', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionOrder2LineEdit.connect('textChanged(QString)', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionExponentLineEdit.connect('textChanged(QString)', self.onCalibrationFunctionLineEditChanged)
    self.step3_applyCalibrationCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep3_ApplyCalibrationCollapsed)

  #------------------------------------------------------------------------------
  def setup_Step4_Registration(self):
    # Step 4: Registration
    self.step4_registrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step4_registrationCollapsibleButton.text = "4. Register film to plan"
    self.sliceletPanelLayout.addWidget(self.step4_registrationCollapsibleButton)

    self.step4_registrationCollapsibleButtonLayout = qt.QVBoxLayout(self.step4_registrationCollapsibleButton)
    self.step4_registrationCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step4_registrationCollapsibleButtonLayout.setSpacing(4)

    # Registration label
    self.step4_registrationLabel1 = qt.QLabel(
      "1. Slice at specified position is extracted and prepared for registration\n"
      "2. Film and plan dose slice are presented in the slice view for pre-alignment\n"
      "3. Scan setup alignment of film and plan dose slice\n"
      "   (Hint: Change opacity of dose slice in slice view controls or Ctrl + Left button drag)\n")
    self.step4_registrationLabel1.wordWrap = True
    self.step4_registrationCollapsibleButtonLayout.addWidget(self.step4_registrationLabel1)

    #
    # Manual coarse pre-alignment controls
    self.step4_scanSetupAlignmentLayout = qt.QGridLayout()

    # Rotation
    self.step4_rotationLabel = qt.QLabel('Rotation: ')
    self.step4_rotateCcwButton = qt.QToolButton(self.step4_registrationCollapsibleButton)
    self.step4_rotateCcwButton.icon = qt.QIcon(':Icons/Small/SlicerUndo.png')
    self.step4_rotateCcwButton.toolTip = u'Rotate counter-clockwise by 90°'
    self.step4_rotateCcwButton.popupMode = qt.QToolButton.MenuButtonPopup
    self.step4_rotateCcwButton.maximumWidth = 48
    self.step4_rotateCcwButton.minimumWidth = 48
    self.step4_rotateCcwAction_5Degrees = qt.QAction(u'Rotate by 5°', self.step4_rotateCcwButton)
    self.step4_rotateCcwButton.addAction(self.step4_rotateCcwAction_5Degrees)
    self.step4_rotateCwButton = qt.QToolButton(self.step4_registrationCollapsibleButton)
    self.step4_rotateCwButton.icon = qt.QIcon(':Icons/Small/SlicerRedo.png')
    self.step4_rotateCwButton.toolTip = u'Rotate clockwise by 90°'
    self.step4_rotateCwButton.popupMode = qt.QToolButton.MenuButtonPopup
    self.step4_rotateCwButton.maximumWidth = 48
    self.step4_rotateCwButton.minimumWidth = 48
    self.step4_rotateCwAction_5Degrees = qt.QAction(u'Rotate by 5°', self.step4_rotateCwButton)
    self.step4_rotateCwButton.addAction(self.step4_rotateCwAction_5Degrees)
    self.step4_scanSetupAlignmentLayout.addWidget(qt.QLabel(''),0,0)
    self.step4_scanSetupAlignmentLayout.addWidget(self.step4_rotationLabel,0,1)
    self.step4_scanSetupAlignmentLayout.addWidget(self.step4_rotateCcwButton,0,2)
    self.step4_scanSetupAlignmentLayout.addWidget(self.step4_rotateCwButton,0,3)
    self.step4_scanSetupAlignmentLayout.addWidget(qt.QLabel(''),0,4)
    self.step4_scanSetupAlignmentLayout.setColumnStretch(4,2)

    # Flip
    self.step4_flipLabel = qt.QLabel('Flip: ')
    self.step4_flipHorizontalButton = qt.QPushButton(self.step4_registrationCollapsibleButton)
    self.step4_flipHorizontalButton.text = u'↔'
    self.step4_flipHorizontalButton.toolTip = 'Flip film horizontally'
    self.step4_flipHorizontalButton.maximumWidth = 48
    self.step4_flipHorizontalButton.minimumWidth = 48
    self.arrowFont = self.step4_flipHorizontalButton.font
    self.arrowFont.setPointSize(14)
    self.arrowFont.setBold(True)
    self.step4_flipHorizontalButton.font = self.arrowFont
    self.step4_flipVerticalButton = qt.QPushButton(self.step4_registrationCollapsibleButton)
    self.step4_flipVerticalButton.text = u'↕'
    self.step4_flipVerticalButton.toolTip = 'Flip film vertically'
    self.step4_flipVerticalButton.maximumWidth = 48
    self.step4_flipVerticalButton.minimumWidth = 48
    self.step4_flipVerticalButton.font = self.arrowFont
    self.step4_scanSetupAlignmentLayout.addWidget(self.step4_flipLabel,1,1)
    self.step4_scanSetupAlignmentLayout.addWidget(self.step4_flipHorizontalButton,1,2)
    self.step4_scanSetupAlignmentLayout.addWidget(self.step4_flipVerticalButton,1,3)

    self.step4_registrationCollapsibleButtonLayout.addLayout(self.step4_scanSetupAlignmentLayout)

    # Add empty row
    self.step4_registrationCollapsibleButtonLayout.addWidget(qt.QLabel(''))

    self.step4_registrationLabel2 = qt.QLabel(
      "4. Automatic image-based registration to fine-tune the registration\n")
    self.step4_registrationLabel2.wordWrap = True
    self.step4_registrationCollapsibleButtonLayout.addWidget(self.step4_registrationLabel2)

    # Perform registration button
    self.step4_performRegistrationButton = qt.QPushButton("Perform registration")
    self.step4_performRegistrationButton.toolTip = "Fine-tune film to plan dose slice registration after manual coarse alignment\n "
    self.step4_registrationCollapsibleButtonLayout.addWidget(self.step4_performRegistrationButton)

    # Add empty row
    self.step4_registrationCollapsibleButtonLayout.addWidget(qt.QLabel(''))

    # Transform fine-tune controls
    self.step4_transformSlidersInfoLabel = qt.QLabel("If registration result is not satisfactory adjust result registration transform:")
    self.step4_transformSlidersInfoLabel.wordWrap = True
    self.step4_translationSliders = slicer.qMRMLTransformSliders()
    #self.step4_translationSliders.CoordinateReference = slicer.qMRMLTransformSliders.LOCAL # This would make the sliders always start form 0 (then min/max would also not be needed)
    translationGroupBox = slicer.util.findChildren(widget=self.step4_translationSliders, className='ctkCollapsibleGroupBox')[0]
    translationGroupBox.collapsed  = True # Collapse by default
    self.step4_translationSliders.setMRMLScene(slicer.mrmlScene)
    self.step4_rotationSliders = slicer.qMRMLTransformSliders()
    self.step4_rotationSliders.minMaxVisible = False
    self.step4_rotationSliders.TypeOfTransform = slicer.qMRMLTransformSliders.ROTATION
    self.step4_rotationSliders.Title = "Rotation"
    self.step4_rotationSliders.CoordinateReference = slicer.qMRMLTransformSliders.LOCAL
    rotationGroupBox = slicer.util.findChildren(widget=self.step4_rotationSliders, className='ctkCollapsibleGroupBox')[0]
    rotationGroupBox.collapsed  = True # Collapse by default
    # self.step4_rotationSliders.setMRMLScene(slicer.mrmlScene) # If scene is set, then mm appears instead of degrees
    self.step4_registrationCollapsibleButtonLayout.addWidget(self.step4_transformSlidersInfoLabel)
    self.step4_registrationCollapsibleButtonLayout.addWidget(self.step4_translationSliders)
    self.step4_registrationCollapsibleButtonLayout.addWidget(self.step4_rotationSliders)

    self.step4_registrationCollapsibleButtonLayout.addStretch(1)

    # Connections
    self.step4_performRegistrationButton.connect('clicked()', self.onPerformRegistrationButtonClicked)
    self.step4_registrationCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep4_RegistrationCollapsed)
    self.step4_rotateCcwButton.connect('clicked()', self.onStep4_RotateCcw90)
    self.step4_rotateCcwAction_5Degrees.connect('triggered()', self.onStep4_RotateCcw5)
    self.step4_rotateCwButton.connect('clicked()', self.onStep4_RotateCw90)
    self.step4_rotateCwAction_5Degrees.connect('triggered()', self.onStep4_RotateCw5)
    self.step4_flipHorizontalButton.connect('clicked()', self.onStep4_FlipHorizontal)
    self.step4_flipVerticalButton.connect('clicked()', self.onStep4_FlipVertical)
    self.step4_translationSliders.connect('valuesChanged()', self.step4_rotationSliders.resetUnactiveSliders)

  #------------------------------------------------------------------------------
  def setup_Step5_GammaComparison(self):
    # Step 5: Dose comparison and analysis
    self.step5_doseComparisonCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step5_doseComparisonCollapsibleButton.text = "5. Gamma comparison"
    self.sliceletPanelLayout.addWidget(self.step5_doseComparisonCollapsibleButton)

    self.step5_doseComparisonCollapsibleButtonLayout = qt.QFormLayout(self.step5_doseComparisonCollapsibleButton)
    self.step5_doseComparisonCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step5_doseComparisonCollapsibleButtonLayout.setSpacing(4)

    # Info label
    self.step5_doseComparisonReferenceVolumeLabel = qt.QLabel('Need to assign data in step 2!')
    self.step5_doseComparisonReferenceVolumeLabel.wordWrap = True
    self.step5_doseComparisonCollapsibleButtonLayout.addRow('Plan dose slice (reference):', self.step5_doseComparisonReferenceVolumeLabel)
    self.step5_doseComparisonEvaluatedVolumeLabel = qt.QLabel('Need to assign data in step 2!')
    self.step5_doseComparisonEvaluatedVolumeLabel.wordWrap = True
    self.step5_doseComparisonCollapsibleButtonLayout.addRow('Calibrated experimental film (evaluated):', self.step5_doseComparisonEvaluatedVolumeLabel)

    # Mask segmentation selector
    self.step5_maskSegmentationSelector = slicer.qMRMLSegmentSelectorWidget()
    self.step5_maskSegmentationSelector.setMRMLScene(slicer.mrmlScene)
    self.step5_maskSegmentationSelector.noneEnabled = True
    self.step5_doseComparisonCollapsibleButtonLayout.addRow("Mask structure: ", self.step5_maskSegmentationSelector)

    # DTA
    self.step5_dtaDistanceToleranceMmSpinBox = qt.QDoubleSpinBox()
    self.step5_dtaDistanceToleranceMmSpinBox.setValue(3.0)
    self.step5_doseComparisonCollapsibleButtonLayout.addRow('Distance-to-agreement criteria (mm): ', self.step5_dtaDistanceToleranceMmSpinBox)

    # Dose difference tolerance criteria
    self.step5_doseDifferenceToleranceLayout = qt.QHBoxLayout(self.step5_doseComparisonCollapsibleButton)
    self.step5_doseDifferenceToleranceLabelBefore = qt.QLabel('Dose difference criteria is ')
    self.step5_doseDifferenceTolerancePercentSpinBox = qt.QDoubleSpinBox()
    self.step5_doseDifferenceTolerancePercentSpinBox.setValue(3.0)
    self.step5_doseDifferenceToleranceLabelAfter = qt.QLabel('% of:  ')
    self.step5_doseDifferenceToleranceLayout.addWidget(self.step5_doseDifferenceToleranceLabelBefore)
    self.step5_doseDifferenceToleranceLayout.addWidget(self.step5_doseDifferenceTolerancePercentSpinBox)
    self.step5_doseDifferenceToleranceLayout.addWidget(self.step5_doseDifferenceToleranceLabelAfter)

    self.step5_referenceDoseLayout = qt.QVBoxLayout()
    self.step5_referenceDoseUseMaximumDoseRadioButton = qt.QRadioButton('the maximum dose\n(calculated from plan dose volume)')
    self.step5_referenceDoseUseCustomValueLayout = qt.QHBoxLayout(self.step5_doseComparisonCollapsibleButton)
    self.step5_referenceDoseUseCustomValueGyRadioButton = qt.QRadioButton('a custom dose value (cGy):')
    self.step5_referenceDoseCustomValueCGySpinBox = qt.QDoubleSpinBox()
    self.step5_referenceDoseCustomValueCGySpinBox.value = 5.0
    self.step5_referenceDoseCustomValueCGySpinBox.maximum = 99999
    self.step5_referenceDoseCustomValueCGySpinBox.maximumWidth = 48
    self.step5_referenceDoseCustomValueCGySpinBox.enabled = False
    self.step5_referenceDoseUseCustomValueLayout.addWidget(self.step5_referenceDoseUseCustomValueGyRadioButton)
    self.step5_referenceDoseUseCustomValueLayout.addWidget(self.step5_referenceDoseCustomValueCGySpinBox)
    self.step5_referenceDoseUseCustomValueLayout.addStretch(1)
    self.step5_referenceDoseLayout.addWidget(self.step5_referenceDoseUseMaximumDoseRadioButton)
    self.step5_referenceDoseLayout.addLayout(self.step5_referenceDoseUseCustomValueLayout)
    self.step5_doseDifferenceToleranceLayout.addLayout(self.step5_referenceDoseLayout)

    self.step5_doseComparisonCollapsibleButtonLayout.addRow(self.step5_doseDifferenceToleranceLayout)

    # Analysis threshold
    self.step5_analysisThresholdLayout = qt.QHBoxLayout(self.step5_doseComparisonCollapsibleButton)
    self.step5_analysisThresholdLabelBefore = qt.QLabel('Do not calculate gamma values for voxels below ')
    self.step5_analysisThresholdPercentSpinBox = qt.QDoubleSpinBox()
    self.step5_analysisThresholdPercentSpinBox.value = 0.0
    self.step5_analysisThresholdPercentSpinBox.maximumWidth = 48
    self.step5_analysisThresholdLabelAfter = qt.QLabel('% of the maximum dose,')
    self.step5_analysisThresholdLabelAfter.wordWrap = True
    self.step5_analysisThresholdLayout.addWidget(self.step5_analysisThresholdLabelBefore)
    self.step5_analysisThresholdLayout.addWidget(self.step5_analysisThresholdPercentSpinBox)
    self.step5_analysisThresholdLayout.addWidget(self.step5_analysisThresholdLabelAfter)
    self.step5_doseComparisonCollapsibleButtonLayout.addRow(self.step5_analysisThresholdLayout)
    self.step5_doseComparisonCollapsibleButtonLayout.addRow(qt.QLabel('                                            or the custom dose value (depending on selection above).'))

    # Use geometric gamma calculation
    self.step5_useGeometricGammaCalculation = qt.QCheckBox()
    self.step5_useGeometricGammaCalculation.checked = True
    self.step5_useGeometricGammaCalculation.setToolTip('By checking this box, gamma will be calculated according to Ju et al 2008, which finds the point with the minimum gamma value by using the normal vector between the two candidate points.')
    self.step5_doseComparisonCollapsibleButtonLayout.addRow('Use geometric gamma calculation: ', self.step5_useGeometricGammaCalculation)

    # Maximum gamma
    self.step5_maximumGammaSpinBox = qt.QDoubleSpinBox()
    self.step5_maximumGammaSpinBox.setValue(2.0)
    self.step5_doseComparisonCollapsibleButtonLayout.addRow('Upper bound for gamma calculation: ', self.step5_maximumGammaSpinBox)

    # Gamma volume selector
    self.step5_gammaVolumeSelectorLayout = qt.QHBoxLayout(self.step5_doseComparisonCollapsibleButton)
    self.step5_gammaVolumeSelector = slicer.qMRMLNodeComboBox()
    self.step5_gammaVolumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step5_gammaVolumeSelector.addEnabled = True
    self.step5_gammaVolumeSelector.removeEnabled = False
    self.step5_gammaVolumeSelector.setMRMLScene( slicer.mrmlScene )
    self.step5_gammaVolumeSelector.setToolTip( "Select output gamma volume" )
    self.step5_gammaVolumeSelector.setProperty('baseName', 'GammaVolume')
    self.step5_helpLabel = qt.QLabel()
    self.step5_helpLabel.pixmap = qt.QPixmap(':Icons/Help.png')
    self.step5_helpLabel.maximumWidth = 24
    self.step5_helpLabel.toolTip = "A gamma volume must be selected to contain the output. You can create a new volume by selecting 'Create new Volume'"
    self.step5_gammaVolumeSelectorLayout.addWidget(self.step5_gammaVolumeSelector)
    self.step5_gammaVolumeSelectorLayout.addWidget(self.step5_helpLabel)
    self.step5_doseComparisonCollapsibleButtonLayout.addRow("Gamma volume: ", self.step5_gammaVolumeSelectorLayout)

    self.step5_computeGammaButton = qt.QPushButton('Calculate gamma volume')
    self.step5_doseComparisonCollapsibleButtonLayout.addRow(self.step5_computeGammaButton)

    self.step5_gammaStatusLabel = qt.QLabel()
    self.step5_doseComparisonCollapsibleButtonLayout.addRow(self.step5_gammaStatusLabel)

    self.step5_showGammaReportButton = qt.QPushButton('Show report')
    self.step5_showGammaReportButton.enabled = False
    self.step5_doseComparisonCollapsibleButtonLayout.addRow(self.step5_showGammaReportButton)

    # Make sure first panels appear when steps are first opened (done before connections to avoid
    # executing those steps, which are only needed when actually switching there during the workflow)
    self.step5_referenceDoseUseMaximumDoseRadioButton.setChecked(True)

    # Connections
    self.step5_doseComparisonCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep5_DoseComparisonCollapsed)
    self.step5_maskSegmentationSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onStep5_MaskSegmentationSelectionChanged)
    self.step5_maskSegmentationSelector.connect('currentSegmentChanged(QString)', self.onStep5_MaskSegmentSelectionChanged)
    self.step5_referenceDoseUseMaximumDoseRadioButton.connect('toggled(bool)', self.onUseMaximumDoseRadioButtonToggled)
    self.step5_computeGammaButton.connect('clicked()', self.onGammaDoseComparison)
    self.step5_showGammaReportButton.connect('clicked()', self.onShowGammaReport)

  #------------------------------------------------------------------------------
  def setup_StepT1_lineProfileCollapsibleButton(self):
    # Step T1: Line profile tool
    self.stepT1_lineProfileCollapsibleButton.setProperty('collapsedHeight', 4)
    self.stepT1_lineProfileCollapsibleButton.text = "Tool: Line profile"
    self.sliceletPanelLayout.addWidget(self.stepT1_lineProfileCollapsibleButton)
    self.stepT1_lineProfileCollapsibleButtonLayout = qt.QFormLayout(self.stepT1_lineProfileCollapsibleButton)
    self.stepT1_lineProfileCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.stepT1_lineProfileCollapsibleButtonLayout.setSpacing(4)

    # Ruler creator
    self.stepT1_rulerCreationButton = slicer.qSlicerMouseModeToolBar()
    self.stepT1_rulerCreationButton.setApplicationLogic(slicer.app.applicationLogic())
    self.stepT1_rulerCreationButton.setMRMLScene(slicer.app.mrmlScene())
    self.stepT1_rulerCreationButton.setToolTip( "Create ruler (line segment) for line profile" )
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow("Create ruler: ", self.stepT1_rulerCreationButton)

    # Input ruler selector
    self.stepT1_inputRulerSelector = slicer.qMRMLNodeComboBox()
    self.stepT1_inputRulerSelector.nodeTypes = ["vtkMRMLAnnotationRulerNode"]
    self.stepT1_inputRulerSelector.selectNodeUponCreation = True
    self.stepT1_inputRulerSelector.addEnabled = False
    self.stepT1_inputRulerSelector.removeEnabled = False
    self.stepT1_inputRulerSelector.noneEnabled = False
    self.stepT1_inputRulerSelector.showHidden = False
    self.stepT1_inputRulerSelector.showChildNodeTypes = False
    self.stepT1_inputRulerSelector.setMRMLScene( slicer.mrmlScene )
    self.stepT1_inputRulerSelector.setToolTip( "Pick the ruler that defines the sampling line." )
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow("Input ruler: ", self.stepT1_inputRulerSelector)

    # Line sampling resolution in mm
    self.stepT1_lineResolutionMmSliderWidget = ctk.ctkSliderWidget()
    self.stepT1_lineResolutionMmSliderWidget.decimals = 1
    self.stepT1_lineResolutionMmSliderWidget.singleStep = 0.1
    self.stepT1_lineResolutionMmSliderWidget.minimum = 0.1
    self.stepT1_lineResolutionMmSliderWidget.maximum = 2
    self.stepT1_lineResolutionMmSliderWidget.value = 0.5
    self.stepT1_lineResolutionMmSliderWidget.setToolTip("Sampling density along the line in mm")
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow("Line resolution (mm): ", self.stepT1_lineResolutionMmSliderWidget)

    # Show/hide legend checkbox
    self.stepT1_lineProfileLegendVisibilityCheckbox = qt.QCheckBox()
    self.stepT1_lineProfileLegendVisibilityCheckbox.checked = True
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow('Show legend: ', self.stepT1_lineProfileLegendVisibilityCheckbox)

    # Create line profile button
    self.stepT1_createLineProfileButton = qt.QPushButton("Create line profile")
    self.stepT1_createLineProfileButton.toolTip = "Compute and show line profile"
    self.stepT1_createLineProfileButton.enabled = False
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow(self.stepT1_createLineProfileButton)
    self.onSelectLineProfileParameters()

    # Export line profiles to CSV button
    self.stepT1_exportLineProfilesToCSV = qt.QPushButton("Export line profiles to CSV")
    self.stepT1_exportLineProfilesToCSV.toolTip = "Export calculated line profiles to CSV"
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow(self.stepT1_exportLineProfilesToCSV)

    # Hint label
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow(' ', None)
    self.stepT1_lineProfileHintLabel = qt.QLabel("Hint: Full screen plot view is available in the layout selector tab (top one)")
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow(self.stepT1_lineProfileHintLabel)

    # Connections
    self.stepT1_lineProfileCollapsibleButton.connect('contentsCollapsed(bool)', self.onStepT1_LineProfileCollapsed)
    self.stepT1_lineProfileLegendVisibilityCheckbox.connect('toggled(bool)', self.onLegendVisibilityToggled)
    self.stepT1_createLineProfileButton.connect('clicked(bool)', self.onCreateLineProfileButton)
    self.stepT1_inputRulerSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelectLineProfileParameters)
    self.stepT1_exportLineProfilesToCSV.connect('clicked()', self.onExportLineProfiles)

  #
  # -----------------------
  # Event handler functions
  # -----------------------
  #

  #------------------------------------------------------------------------------
  @vtk.calldata_type(vtk.VTK_LONG)
  def onSubjectHierarchyItemAdded(self, caller, event, calldata):
    shNode = caller
    shItemID = calldata

    # If resolving unresolved items (after importing a batch), then save the calibration batch that needs to be parsed
    if shNode.IsItemLevel(shItemID, slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelFolder()):
      self.lastAddedFolder = shItemID

  #------------------------------------------------------------------------------
  @vtk.calldata_type(vtk.VTK_OBJECT)
  def onNodeAdded(self, caller, event, calldata):
    addedNode = calldata

    # When an ROI is added then save it as the ROI to use for calibration
    if addedNode.IsA('vtkMRMLAnnotationROINode'):
      self.logic.lastAddedRoiNode = addedNode

  #------------------------------------------------------------------------------
  def onViewSelect(self, layoutIndex):
    if layoutIndex == 0:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    elif layoutIndex == 1:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
    elif layoutIndex == 2:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
    elif layoutIndex == 3:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutTabbedSliceView)
    elif layoutIndex == 4:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutDual3DView)
    elif layoutIndex == 5:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpPlotView)
    elif layoutIndex == 6:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpPlotView)

  #------------------------------------------------------------------------------
  def onLoadImageFilesButton(self):
    slicer.util.openAddDataDialog()

  #------------------------------------------------------------------------------
  def onDicomLoad(self):
    slicer.modules.dicom.widgetRepresentation()
    slicer.modules.DICOMWidget.enter()

  #------------------------------------------------------------------------------
  # Step 1

  #------------------------------------------------------------------------------
  def onStep1_calibrationCollapsed(self, collapsed):
    if self.logic.lastAddedRoiNode is not None:
      for index in range(self.logic.lastAddedRoiNode.GetNumberOfDisplayNodes()):
        currentDisplayNode = self.logic.lastAddedRoiNode.GetNthDisplayNode(index)
        if currentDisplayNode:
          currentDisplayNode.SetVisibility(not collapsed)

  #------------------------------------------------------------------------------
  def setNumberOfCalibrationFilmsInTable(self, numberOfCalibrationFilms):
    if numberOfCalibrationFilms > self.maxNumberOfCalibrationFilms:
      message = 'Maximum number of calibration films supported: ' + str(self.maxNumberOfCalibrationFilms) + ', requested: ' + str(numberOfCalibrationFilms)
      qt.QMessageBox.critical(None, 'Empty directory must be chosen', message)
      logging.error(message)
      return

    for row in range(numberOfCalibrationFilms):
      self.step1_calibrationVolumeSelectorLabelBeforeList[row].visible = True
      self.step1_calibrationVolumeSelectorCGySpinBoxList[row].visible = True
      self.step1_calibrationVolumeSelectorCGyLabelList[row].visible = True
      self.step1_calibrationVolumeSelectorComboBoxList[row].visible = True

    for row in range(numberOfCalibrationFilms, self.maxNumberOfCalibrationFilms):
      self.step1_calibrationVolumeSelectorLabelBeforeList[row].visible = False
      self.step1_calibrationVolumeSelectorCGySpinBoxList[row].visible = False
      self.step1_calibrationVolumeSelectorCGyLabelList[row].visible = False
      self.step1_calibrationVolumeSelectorComboBoxList[row].visible = False

  #------------------------------------------------------------------------------
  def onNumberOfCalibrationFilmsSpinBoxValueChanged(self):
    self.setNumberOfCalibrationFilmsInTable(self.step1_numberOfCalibrationFilmsSpinBox.value)

  #------------------------------------------------------------------------------
  def collectCalibrationFilms(self):
    calibrationDoseToVolumeNodeMap = OrderedDict()
    for currentCalibrationVolumeIndex in range(self.step1_numberOfCalibrationFilmsSpinBox.value):
      currentCalibrationVolumeNode = self.step1_calibrationVolumeSelectorComboBoxList[currentCalibrationVolumeIndex].currentNode()
      currentCalibrationDose = self.step1_calibrationVolumeSelectorCGySpinBoxList[currentCalibrationVolumeIndex].value
      calibrationDoseToVolumeNodeMap[currentCalibrationDose] = currentCalibrationVolumeNode
    return calibrationDoseToVolumeNodeMap

  #------------------------------------------------------------------------------
  def onSaveCalibrationBatchButton(self):
    # Show folder selector window
    calibrationBatchDirectoryPath = qt.QFileDialog.getExistingDirectory(0, 'Select directory to save calibration batch')

    # Get flood field image node
    floodFieldImageVolumeNode = self.step1_floodFieldImageSelectorComboBox.currentNode()
    # Collect calibration doses and volumes
    calibrationDoseToVolumeNodeMap = self.collectCalibrationFilms()

    # Save calibration batch
    message = self.logic.saveCalibrationBatch(calibrationBatchDirectoryPath, floodFieldImageVolumeNode, calibrationDoseToVolumeNodeMap)
    if message != "":
      qt.QMessageBox.critical(None, 'Error when saving calibration batch', message)
      logging.error(message)
    else:
      qt.QMessageBox.information(None, "Calibration batch saving" , "Calibration batch successfully saved")

  #------------------------------------------------------------------------------
  def onLoadCalibrationBatchButton(self):
    # Show folder selector window
    calibrationBatchDirectoryPath = qt.QFileDialog.getExistingDirectory(0, 'Open directory containing calibration batch')

    mrmlFilesFound = 0
    calibrationBatchMrmlSceneFileName = None
    os.chdir(os.path.normpath(calibrationBatchDirectoryPath))
    for potentialMrmlFileName in glob.glob("*.mrml"):
      mrmlFilesFound += 1
      calibrationBatchMrmlSceneFileName = potentialMrmlFileName

    if mrmlFilesFound > 1:
      qt.QMessageBox.critical(None, 'Error when loading calibration batch', "More than one MRML file found in directory!\n\nThe calibration batch directory must contain exactly one MRML file")
      logging.error("More than one MRML files found in directory " + calibrationBatchDirectoryPath)
      return
    elif mrmlFilesFound < 1:
      qt.QMessageBox.critical(None, 'Error when loading calibration batch', "No MRML file found in directory!\n\nThe calibration batch directory must contain exactly one MRML file")
      logging.error("No MRML file found in directory " + calibrationBatchDirectoryPath)
      return

    # Show wait cursor while loading
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    calibrationBatchMrmlSceneFilePath = os.path.normpath(calibrationBatchDirectoryPath + "/" + calibrationBatchMrmlSceneFileName)
    success = slicer.util.loadScene(calibrationBatchMrmlSceneFilePath)

    # Restore cursor
    qt.QApplication.restoreOverrideCursor()

  #------------------------------------------------------------------------------
  def onSubjectHierarchyResolveEnded(self, caller, event):
    if self.lastAddedFolder is None:
      message = "Invalid saved directory, no subject hierarchy folder is selected to parse"
      qt.QMessageBox.critical(None, 'Error when loading calibration batch', message)
      logging.error(message)
      return message

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

    currentCalibrationFilmIndex = 0
    loadedFloodFieldScalarVolume = None
    lastLoadedCalibrationVolume = None

    # Inspect items under the batch folder item assign them to roles and dose levels
    children = vtk.vtkIdList()
    shNode.GetItemChildren(self.lastAddedFolder, children)
    for i in range(children.GetNumberOfIds()):
      childItemID = children.GetId(i)

      # Flood film image
      if shNode.GetItemAttribute(childItemID, self.logic.calibrationVolumeDoseAttributeName) == self.logic.floodFieldAttributeValue:
        if loadedFloodFieldScalarVolume is None:
          loadedFloodFieldScalarVolume = shNode.GetItemDataNode(childItemID)
          self.step1_floodFieldImageSelectorComboBox.setCurrentNode(loadedFloodFieldScalarVolume)
        else:
          message = "More than one flood field image found"
          qt.QMessageBox.critical(None, 'Error', message)
          logging.error(message)
          return message
      # Calibration film
      else:
        try:
          # Set dose level
          doseLevel_cGy = int( shNode.GetItemAttribute(childItemID, self.logic.calibrationVolumeDoseAttributeName) )
          self.step1_calibrationVolumeSelectorCGySpinBoxList[currentCalibrationFilmIndex].value = doseLevel_cGy

          # Set calibration film for dose level
          loadedCalibrationVolume = shNode.GetItemDataNode(childItemID)
          self.step1_calibrationVolumeSelectorComboBoxList[currentCalibrationFilmIndex].setCurrentNode(loadedCalibrationVolume)

          lastLoadedCalibrationVolume = loadedCalibrationVolume
          currentCalibrationFilmIndex += 1
        except ValueError:
          logging.warning('Invalid calibration film dose attribute "' + repr(shNode.GetItemAttribute(childItemID, self.logic.calibrationVolumeDoseAttributeName)) + '" in inspected item named' + shNode.GetItemName(childItemID))

    # Update calibration films table to set row visibilities
    self.step1_numberOfCalibrationFilmsSpinBox.value = currentCalibrationFilmIndex

    # Reset saved folder item
    self.lastAddedFolder = 0

    if loadedFloodFieldScalarVolume is None:
      message = 'Failed to find flood field image!'
      qt.QMessageBox.critical(None, 'Error during parsing batch', message)
      logging.error(message)

    # Show last loaded film
    if lastLoadedCalibrationVolume is not None:
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      selectionNode.SetActiveVolumeID(lastLoadedCalibrationVolume.GetID())
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()
    else:
      message = 'Failed to find any calibration film image!'
      qt.QMessageBox.critical(None, 'Error during parsing batch', message)
      logging.error(message)

    return ""

  #------------------------------------------------------------------------------
  def onAddRoiButton(self):
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    interactionNode = appLogic.GetInteractionNode()

    # Switch to ROI place mode
    selectionNode.SetReferenceActivePlaceNodeClassName('vtkMRMLAnnotationROINode')
    interactionNode.SwitchToSinglePlaceMode()

  #------------------------------------------------------------------------------
  def onStep1_2_performCalibrationCollapsed(self, collapsed):
    if not collapsed:
      # Fit red slice to calibration film image so that ROI can be added more conveniently
      self.layoutWidget.layoutManager().sliceWidget('Red').sliceController().fitSliceToBackground()

  #------------------------------------------------------------------------------
  def createCalibrationCurvesWindow(self):
    # Set up window to be used for displaying data
    self.calibrationCurveChartView = vtk.vtkContextView()
    self.calibrationCurveChartView.GetRenderer().SetBackground(1,1,1)
    self.calibrationCurveChart = vtk.vtkChartXY()
    self.calibrationCurveChartView.GetScene().AddItem(self.calibrationCurveChart)

  #------------------------------------------------------------------------------
  def showCalibrationCurves(self):
    # Create CALIBRATION dose vs. optical density plot
    self.calibrationCurveDataTable = vtk.vtkTable()
    calibrationNumberOfRows = len(self.logic.measuredOpticalDensityToDoseMap)

    opticalDensityArray = vtk.vtkDoubleArray()
    opticalDensityArray.SetName("Optical Density")
    self.calibrationCurveDataTable.AddColumn(opticalDensityArray)
    dose_cGyCalibrationCurveArray = vtk.vtkDoubleArray()
    dose_cGyCalibrationCurveArray.SetName("Dose (cGy)")
    self.calibrationCurveDataTable.AddColumn(dose_cGyCalibrationCurveArray)
    self.calibrationCurveDataTable.SetNumberOfRows(calibrationNumberOfRows)

    for rowIndex in range(calibrationNumberOfRows):
      self.calibrationCurveDataTable.SetValue(rowIndex, 0, self.logic.measuredOpticalDensityToDoseMap[rowIndex][0])
      self.calibrationCurveDataTable.SetValue(rowIndex, 1, self.logic.measuredOpticalDensityToDoseMap[rowIndex][1])

    if hasattr(self, 'calibrationMeanOpticalAttenuationLine' ):
      self.calibrationCurveChart.RemovePlotInstance(self.calibrationMeanOpticalAttenuationLine)
    self.calibrationMeanOpticalAttenuationLine = self.calibrationCurveChart.AddPlot(vtk.vtkChart.POINTS)
    self.calibrationMeanOpticalAttenuationLine.SetInputData(self.calibrationCurveDataTable, 0, 1)
    self.calibrationMeanOpticalAttenuationLine.SetColor(0, 0, 255, 255)
    self.calibrationMeanOpticalAttenuationLine.SetWidth(2.0)

    # Create and populate the calculated dose/OD curve with function
    opticalDensityList = [round(0 + 0.01*opticalDensityIncrement,2) for opticalDensityIncrement in range(120)] #TODO: Magic number 120? Rounding?
    opticalDensities = []

    for calculatedEntryIndex in range(120):
      newEntry = [opticalDensityList[calculatedEntryIndex], self.logic.applyCalibrationFunctionOnSingleOpticalDensityValue(opticalDensityList[calculatedEntryIndex], self.logic.calibrationCoefficients[0], self.logic.calibrationCoefficients[1], self.logic.calibrationCoefficients[2], self.logic.calibrationCoefficients[3])]
      opticalDensities.append(newEntry)

    # Create plot for dose calibration fitted curve
    self.opticalDensityToDoseFunctionTable = vtk.vtkTable()
    opticalDensityNumberOfRows = len(opticalDensities)
    opticalDensityCalculatedArray = vtk.vtkDoubleArray()
    opticalDensityCalculatedArray.SetName("opticalDensities")
    self.opticalDensityToDoseFunctionTable.AddColumn(opticalDensityCalculatedArray)
    dose_cGyCalculatedArray = vtk.vtkDoubleArray()
    dose_cGyCalculatedArray.SetName("Optical Density")
    self.opticalDensityToDoseFunctionTable.AddColumn(dose_cGyCalculatedArray)

    self.opticalDensityToDoseFunctionTable.SetNumberOfRows(opticalDensityNumberOfRows)
    for opticalDensityIncrement in range(opticalDensityNumberOfRows):
      self.opticalDensityToDoseFunctionTable.SetValue(opticalDensityIncrement, 0, opticalDensities[opticalDensityIncrement][0])
      self.opticalDensityToDoseFunctionTable.SetValue(opticalDensityIncrement, 1, opticalDensities[opticalDensityIncrement][1])

    if hasattr(self, 'calculatedDoseLine'):
      self.calibrationCurveChart.RemovePlotInstance(self.calculatedDoseLine)
    self.calculatedDoseLine = self.calibrationCurveChart.AddPlot(vtk.vtkChart.LINE)
    self.calculatedDoseLine.SetInputData(self.opticalDensityToDoseFunctionTable, 0, 1)
    self.calculatedDoseLine.SetColor(255, 0, 0, 255)
    self.calculatedDoseLine.SetWidth(2.0)

    # Show chart
    self.calibrationCurveChart.GetAxis(1).SetTitle('Optical Density')
    self.calibrationCurveChart.GetAxis(0).SetTitle('Dose (cGy)')
    self.calibrationCurveChart.SetShowLegend(True)
    self.calibrationCurveChart.SetTitle('Dose (cGy) vs. Optical Density')
    self.calibrationCurveChartView.GetInteractor().Initialize()
    self.calibrationCurveChartRenderWindow = self.calibrationCurveChartView.GetRenderWindow()
    self.calibrationCurveChartRenderWindow.SetSize(800,550)
    self.calibrationCurveChartRenderWindow.SetWindowName('Dose (cGy) vs. Optical Density')
    self.calibrationCurveChartRenderWindow.Start()

  #------------------------------------------------------------------------------
  def containsRgbImage(self, input):
    # Input can be dictionary or node
    import types
    if type(input) is OrderedDict:
      for node in input.values():
        if node.IsA('vtkMRMLVectorVolumeNode'):
          return True
      return False
    else:
      try:
        return input.IsA('vtkMRMLVectorVolumeNode')
      except (AttributeError, TypeError) as e:
        return False

  #------------------------------------------------------------------------------
  def onPerformCalibrationButton(self):
    # Get flood field image node
    floodFieldImageVolumeNode = self.step1_floodFieldImageSelectorComboBox.currentNode()
    # Collect calibration doses and volumes
    calibrationDoseToVolumeNodeMap = self.collectCalibrationFilms()

    # Check if the images are RGB and extract red channel if so
    if self.containsRgbImage(calibrationDoseToVolumeNodeMap):
      qt.QMessageBox.information(None, "RGB images detected" , "Loaded data contain RGB images, which are not yet supported.\n\nRed channel will be extracted from those images.")
      # Extract red channel from all calibration images
      calibrationDoseToVolumeNodeMap = self.logic.extractRedChannel(calibrationDoseToVolumeNodeMap)
      # Re-populate comboboxes with new nodes
      for currentCalibrationVolumeIndex in range(self.step1_numberOfCalibrationFilmsSpinBox.value):
        currentCalibrationDose = self.step1_calibrationVolumeSelectorCGySpinBoxList[currentCalibrationVolumeIndex].value
        newCurrentCalibrationVolumeNode = calibrationDoseToVolumeNodeMap[currentCalibrationDose]
        self.step1_calibrationVolumeSelectorComboBoxList[currentCalibrationVolumeIndex].setCurrentNode(newCurrentCalibrationVolumeNode)

      # Extract red channel from flood field image
      floodFieldImageVolumeNode = self.step1_floodFieldImageSelectorComboBox.currentNode()
      newFloodFieldImageVolumeNode = self.logic.extractRedChannel(floodFieldImageVolumeNode)
      self.step1_floodFieldImageSelectorComboBox.setCurrentNode(newFloodFieldImageVolumeNode)
      floodFieldImageVolumeNode = newFloodFieldImageVolumeNode

    # Show wait cursor while processing
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    # Perform calibration
    message = self.logic.performCalibration(floodFieldImageVolumeNode, calibrationDoseToVolumeNodeMap)
    if message != "":
      qt.QMessageBox.critical(None, 'Error when performing calibration', message)
      logging.error(message)

    # Restore cursor
    qt.QApplication.restoreOverrideCursor()

    # Show calibration plot
    self.createCalibrationCurvesWindow()
    self.showCalibrationCurves()

    # Fill calibration entry line edits (so that the rounded values are not written back to the member variable storing the coefficients)
    aText = str(round(self.logic.calibrationCoefficients[0],5))
    bText = str(round(self.logic.calibrationCoefficients[1],5))
    cText = str(round(self.logic.calibrationCoefficients[2],5))
    nText = str(round(self.logic.calibrationCoefficients[3],5))
    self.step3_calibrationFunctionOrder0LineEdit.blockSignals(True)
    self.step3_calibrationFunctionOrder0LineEdit.text = aText
    self.step3_calibrationFunctionOrder0LineEdit.blockSignals(False)
    self.step3_calibrationFunctionOrder1LineEdit.blockSignals(True)
    self.step3_calibrationFunctionOrder1LineEdit.text = bText
    self.step3_calibrationFunctionOrder1LineEdit.blockSignals(False)
    self.step3_calibrationFunctionOrder2LineEdit.blockSignals(True)
    self.step3_calibrationFunctionOrder2LineEdit.text = cText
    self.step3_calibrationFunctionOrder2LineEdit.blockSignals(False)
    self.step3_calibrationFunctionExponentLineEdit.blockSignals(True)
    self.step3_calibrationFunctionExponentLineEdit.text = nText
    self.step3_calibrationFunctionExponentLineEdit.blockSignals(False)

    # Calibration function label
    self.step1_2_performCalibrationFunctionLabel.text = "Dose (cGy) = " + aText + " + " + bText + " * OD + " + cText + " * OD^" + nText

  #------------------------------------------------------------------------------
  def onSaveCalibrationFunctionToFileButton(self):
    outputDir = qt.QFileDialog.getExistingDirectory(0, 'Select directory for saving calibration results')
    self.logic.saveCalibrationFunctionToFile(outputDir)

  #------------------------------------------------------------------------------
  # Step 2

  #------------------------------------------------------------------------------
  def onExperimentalFilmSpacingChanged(self):
    try:
      self.logic.experimentalFilmPixelSpacing = float(self.step2_experimentalFilmSpacingLineEdit.text)
    except ValueError:
      return

  #------------------------------------------------------------------------------
  def onExperimentalFilmSliceOrientationChanged(self, text):
    self.logic.experimentalFilmSliceOrientation = text

  #------------------------------------------------------------------------------
  def onExperimentalFilmSlicePositionChanged(self, position):
    self.logic.experimentalFilmSlicePosition = position

  #------------------------------------------------------------------------------
  def onStep2_loadExperimentalDataCollapsed(self, collapsed):
    if collapsed:
      # Save experimental data selection
      self.saveExperimentalDataSelection()

      # Set auto window/level for dose volume
      self.logic.setAutoWindowLevelToAllDoseVolumes()

      # Disable slice fill and only show outlines for the segmentations
      self.logic.setSliceOutlineOnlyForAllSegmentations()

  #------------------------------------------------------------------------------
  def saveExperimentalDataSelection(self):
    self.logic.experimentalFloodFieldVolumeNode = self.step2_floodFieldImageSelectorComboBox.currentNode()
    self.logic.experimentalFilmVolumeNode = self.step2_experimentalFilmSelectorComboBox.currentNode()
    self.logic.planDoseVolumeNode = self.step2_planDoseVolumeSelector.currentNode()

    return self.logic.experimentalFloodFieldVolumeNode is not None and self.logic.experimentalFilmVolumeNode is not None and self.logic.planDoseVolumeNode is not None

  #------------------------------------------------------------------------------
  # Step 3

  #------------------------------------------------------------------------------
  def onStep3_ApplyCalibrationCollapsed(self, collapsed):
    if not collapsed:
      # Reset calibration message label
      self.step3_calibrationMessageLabel.text = ''

      # Show film and plan dose in the slice views
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      if self.logic.experimentalFilmVolumeNode is not None:
        selectionNode.SetActiveVolumeID(self.logic.experimentalFilmVolumeNode.GetID())
      else:
        selectionNode.SetActiveVolumeID(None)
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()

      # Hide segmentations (large structure sets may slow down the application)
      segmentationDisplayNodes = slicer.util.getNodes('vtkMRMLSegmentationDisplayNode*')
      for displayNode in segmentationDisplayNodes.values():
        displayNode.SetVisibility(0)

  #------------------------------------------------------------------------------
  def onCalibrationFunctionLineEditChanged(self):
    if self.step3_calibrationFunctionOrder0LineEdit.text != '':
      try:
        self.logic.calibrationCoefficients[0] = float(self.step3_calibrationFunctionOrder0LineEdit.text)
      except ValueError:
        logging.error("Invalid numeric value for calibration function coefficient 'A' " + self.step3_calibrationFunctionOrder0LineEdit.text)
    if self.step3_calibrationFunctionOrder1LineEdit.text != '':
      try:
        self.logic.calibrationCoefficients[1] = float(self.step3_calibrationFunctionOrder1LineEdit.text)
      except ValueError:
        logging.error("Invalid numeric value for calibration function coefficient 'B' " + self.step3_calibrationFunctionOrder1LineEdit.text)
    if self.step3_calibrationFunctionOrder2LineEdit.text != '':
      try:
        self.logic.calibrationCoefficients[2] = float(self.step3_calibrationFunctionOrder2LineEdit.text)
      except ValueError:
        logging.error("Invalid numeric value for calibration function coefficient 'C' " + self.step3_calibrationFunctionOrder2LineEdit.text)
    if self.step3_calibrationFunctionExponentLineEdit.text != '':
      try:
        self.logic.calibrationCoefficients[3] = float(self.step3_calibrationFunctionExponentLineEdit.text)
      except ValueError:
        logging.error("Invalid numeric value for calibration function coefficient 'N' " + self.step3_calibrationFunctionExponentLineEdit.text)

  #------------------------------------------------------------------------------
  def onLoadCalibrationFunctionFromFileButton(self):
    filePath = qt.QFileDialog.getOpenFileName(0, 'Open file')
    self.loadCalibrationFunctionFromFile(filePath)

  #------------------------------------------------------------------------------
  def loadCalibrationFunctionFromFile(self, filePath):
    self.logic.loadCalibrationFunctionFromFile(filePath)

    # Display coefficients (rounded to five digits, but the member variable has full accuracy)
    aText = str(round(self.logic.calibrationCoefficients[0],5))
    bText = str(round(self.logic.calibrationCoefficients[1],5))
    cText = str(round(self.logic.calibrationCoefficients[2],5))
    nText = str(round(self.logic.calibrationCoefficients[3],5))
    self.step3_calibrationFunctionOrder0LineEdit.blockSignals(True)
    self.step3_calibrationFunctionOrder0LineEdit.text = aText
    self.step3_calibrationFunctionOrder0LineEdit.blockSignals(False)
    self.step3_calibrationFunctionOrder1LineEdit.blockSignals(True)
    self.step3_calibrationFunctionOrder1LineEdit.text = bText
    self.step3_calibrationFunctionOrder1LineEdit.blockSignals(False)
    self.step3_calibrationFunctionOrder2LineEdit.blockSignals(True)
    self.step3_calibrationFunctionOrder2LineEdit.text = cText
    self.step3_calibrationFunctionOrder2LineEdit.blockSignals(False)
    self.step3_calibrationFunctionExponentLineEdit.blockSignals(True)
    self.step3_calibrationFunctionExponentLineEdit.text = nText
    self.step3_calibrationFunctionExponentLineEdit.blockSignals(False)

  #------------------------------------------------------------------------------
  def onApplyCalibrationButton(self):
    # Check if the experimental image is RGB and extract red channel if so
    if self.containsRgbImage(self.logic.experimentalFloodFieldVolumeNode) or self.containsRgbImage(self.logic.experimentalFilmVolumeNode):
      qt.QMessageBox.information(None, "RGB image detected" , "Experimental data contain RGB images, which are not yet supported.\n\nRed channel will be extracted from those images.")
      self.logic.experimentalFloodFieldVolumeNode = self.logic.extractRedChannel(self.logic.experimentalFloodFieldVolumeNode)
      self.logic.experimentalFilmVolumeNode = self.logic.extractRedChannel(self.logic.experimentalFilmVolumeNode)

    # Show wait cursor while processing
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    # Apply calibration function on experimental image
    message = self.logic.applyCalibrationOnExperimentalFilm()
    if message != '':
      qt.QMessageBox.critical(None, 'Error when applying calibration', message)
      logging.error(message)
      self.step3_calibrationMessageLabel.text = message
    else:
      self.step3_calibrationMessageLabel.text = 'Calibration successfully finished'

    # Restore cursor
    qt.QApplication.restoreOverrideCursor()

    # Show calibrated experimental image
    # (not together with the original film, because the fused image looks strange due to them being inverse of each other)
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(self.logic.calibratedExperimentalFilmVolumeNode.GetID())
    selectionNode.SetSecondaryVolumeID(None)
    appLogic.PropagateVolumeSelection()

  #------------------------------------------------------------------------------
  # Step 4

  #------------------------------------------------------------------------------
  def onStep4_RegistrationCollapsed(self, collapsed):
    if not collapsed:
      # Pre-process volumes for registration (cropping, padding),
      # pre-align film and plan dose slice for scan setup alignment
      message = self.logic.initializeFilmToPlanDoseRegistration()

      if self.logic.paddedCalibratedExperimentalFilmVolumeNode is None or self.logic.paddedPlanDoseSliceVolumeNode is None:
        message = 'Failed to prepare calibrated experimental film and/or plan dose slice for registration\n\n' + message
      if message != '':
        qt.QMessageBox.critical(None, 'Error when initializing registration', message)
        logging.error(message)
        return

      # Show film and plan dose slice
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      selectionNode.SetActiveVolumeID(self.logic.paddedCalibratedExperimentalFilmVolumeNode.GetID())
      selectionNode.SetSecondaryVolumeID(self.logic.paddedPlanDoseSliceVolumeNode.GetID())
      appLogic.PropagateVolumeSelection()
      # Make foreground volume semi-transparent
      layoutManager = slicer.app.layoutManager()
      sliceWidgetNames = ['Red', 'Green', 'Yellow']
      for sliceWidgetName in sliceWidgetNames:
        slice = layoutManager.sliceWidget(sliceWidgetName)
        if slice is None:
          continue
        sliceLogic = slice.sliceLogic()
        compositeNode = sliceLogic.GetSliceCompositeNode()
        compositeNode.SetForegroundOpacity(0.5)

  #------------------------------------------------------------------------------
  def onStep4_RotateCcw90(self):
    self.logic.rotateCalibratedExperimentalFilm(False, 90)

  #------------------------------------------------------------------------------
  def onStep4_RotateCcw5(self):
    self.logic.rotateCalibratedExperimentalFilm(False, 5)

  #------------------------------------------------------------------------------
  def onStep4_RotateCw90(self):
    self.logic.rotateCalibratedExperimentalFilm(True, 90)

  #------------------------------------------------------------------------------
  def onStep4_RotateCw5(self):
    self.logic.rotateCalibratedExperimentalFilm(True, 5)

  #------------------------------------------------------------------------------
  def onStep4_FlipHorizontal(self):
    self.logic.flipCalibratedExperimentalFilm(True)

  #------------------------------------------------------------------------------
  def onStep4_FlipVertical(self):
    self.logic.flipCalibratedExperimentalFilm(False)

  #------------------------------------------------------------------------------
  def onPerformRegistrationButtonClicked(self):
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    # Perform registration
    message = self.logic.registerExperimentalFilmToPlanDose()
    if message != "":
      qt.QMessageBox.critical(None, 'Error when performing calibration', message)
      logging.error(message)

    qt.QApplication.restoreOverrideCursor()

    # Show registered images
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(self.logic.paddedCalibratedExperimentalFilmVolumeNode.GetID())
    selectionNode.SetSecondaryVolumeID(self.logic.paddedPlanDoseSliceVolumeNode.GetID())
    appLogic.PropagateVolumeSelection()

    # Disable pre-alignment controls, because they cannot be used after registration
    self.step4_rotateCcwButton.enabled = False
    self.step4_rotateCwButton.enabled = False
    self.step4_flipHorizontalButton.enabled = False
    self.step4_flipVerticalButton.enabled = False

    # Set transforms to slider widgets
    self.step4_translationSliders.setMRMLTransformNode(self.logic.experimentalFilmToDoseSliceTransformNode)
    self.step4_rotationSliders.setMRMLTransformNode(self.logic.experimentalFilmToDoseSliceTransformNode)

    # Change single step size to 0.5mm in the translation controls
    sliders = slicer.util.findChildren(widget=self.step4_translationSliders, className='qMRMLLinearTransformSlider')
    for slider in sliders:
      slider.singleStep = 0.5

  #------------------------------------------------------------------------------
  # Step 5

  #------------------------------------------------------------------------------
  def onStep5_DoseComparisonCollapsed(self, collapsed):
    # Initialize mask segmentation selector to select plan structures
    # self.step5_maskSegmentationSelector.setCurrentNode(self.planStructuresNode)
    # self.onStep5_MaskSegmentationSelectionChanged(self.planStructuresNode)

    # Turn scalar bar on/off
    if collapsed == False:
      self.sliceAnnotations.scalarBarEnabled = 1
      # Update gamma input selection
      self.refreshDoseComparisonInfoLabel()

      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      if self.logic.calibratedExperimentalFilmVolumeNode:
        selectionNode.SetActiveVolumeID(self.logic.calibratedExperimentalFilmVolumeNode.GetID())
      else:
        selectionNode.SetActiveVolumeID(None)
      if self.logic.croppedPlanDoseSliceVolumeNode:
        selectionNode.SetSecondaryVolumeID(self.logic.croppedPlanDoseSliceVolumeNode.GetID())
      else:
        selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()

    else:
      self.sliceAnnotations.scalarBarEnabled = 0
    self.sliceAnnotations.updateSliceViewFromGUI()
    # Reset 3D view
    self.layoutWidget.layoutManager().threeDWidget(0).threeDView().resetFocalPoint()

  #------------------------------------------------------------------------------
  def onStep5_MaskSegmentationSelectionChanged(self, node):
    # Hide previously selected mask segmentation
    if self.logic.maskSegmentationNode is not None:
      self.logic.maskSegmentationNode.GetDisplayNode().SetVisibility(0)
    # Set new mask segmentation
    self.logic.maskSegmentationNode = node
    self.onStep5_MaskSegmentSelectionChanged(self.step5_maskSegmentationSelector.currentSegmentID())
    # Show new mask segmentation
    if self.logic.maskSegmentationNode is not None:
      self.logic.maskSegmentationNode.GetDisplayNode().SetVisibility(1)

  #------------------------------------------------------------------------------
  def onStep5_MaskSegmentSelectionChanged(self, segmentID):
    if self.logic.maskSegmentationNode is None:
      return
    # Set new mask segment
    self.logic.maskSegmentID = segmentID

    # Hide all segments before showing the selected one
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentIDs = vtk.vtkStringArray()
    self.logic.maskSegmentationNode.GetSegmentation().GetSegmentIDs(segmentIDs)
    for segmentIndex in range(0,segmentIDs.GetNumberOfValues()):
      currentSegmentID = segmentIDs.GetValue(segmentIndex)
      self.logic.maskSegmentationNode.GetDisplayNode().SetSegmentVisibility(currentSegmentID, False)
    # Show only selected segment, make it semi-transparent
    if self.logic.maskSegmentID is not None and self.logic.maskSegmentID != '':
      self.logic.maskSegmentationNode.GetDisplayNode().SetSegmentVisibility(self.logic.maskSegmentID, True)
      self.logic.maskSegmentationNode.GetDisplayNode().SetSegmentOpacity3D(self.logic.maskSegmentID, 0.5)

  #------------------------------------------------------------------------------
  def refreshDoseComparisonInfoLabel(self):
    if self.logic.croppedPlanDoseSliceVolumeNode is None:
      self.step5_doseComparisonReferenceVolumeLabel.text = 'Not selected!'
    else:
      self.step5_doseComparisonReferenceVolumeLabel.text = 'OK'
    if self.logic.calibratedExperimentalFilmVolumeNode is None:
      self.step5_doseComparisonEvaluatedVolumeLabel.text = 'Not selected!'
    else:
      self.step5_doseComparisonEvaluatedVolumeLabel.text = 'OK'

  #------------------------------------------------------------------------------
  def onUseMaximumDoseRadioButtonToggled(self, toggled):
    self.step5_referenceDoseCustomValueCGySpinBox.setEnabled(not toggled)

  #------------------------------------------------------------------------------
  def onGammaDoseComparison(self):
    try:
      slicer.modules.dosecomparison

      if self.step5_gammaVolumeSelector.currentNode() is None:
        qt.QMessageBox.warning(None, 'Warning', 'Gamma volume not selected. If there is no suitable output gamma volume, create one.')
        return
      else:
        self.logic.gammaVolumeNode = self.step5_gammaVolumeSelector.currentNode()

      # Set up gamma computation parameters
      gammaParameterSetNode = slicer.vtkMRMLDoseComparisonNode()
      slicer.mrmlScene.AddNode(gammaParameterSetNode)
      gammaParameterSetNode.SetAndObserveReferenceDoseVolumeNode(self.logic.croppedPlanDoseSliceVolumeNode)
      gammaParameterSetNode.SetAndObserveCompareDoseVolumeNode(self.logic.calibratedExperimentalFilmVolumeNode)
      gammaParameterSetNode.SetAndObserveMaskSegmentationNode(self.logic.maskSegmentationNode)
      if self.logic.maskSegmentID is not None and self.logic.maskSegmentID != '':
        gammaParameterSetNode.SetMaskSegmentID(self.logic.maskSegmentID)
      else:
        gammaParameterSetNode.SetMaskSegmentID(None)
      gammaParameterSetNode.SetAndObserveGammaVolumeNode(self.logic.gammaVolumeNode)
      gammaParameterSetNode.SetDtaDistanceToleranceMm(self.step5_dtaDistanceToleranceMmSpinBox.value)
      gammaParameterSetNode.SetDoseDifferenceTolerancePercent(self.step5_doseDifferenceTolerancePercentSpinBox.value)
      gammaParameterSetNode.SetUseMaximumDose(self.step5_referenceDoseUseMaximumDoseRadioButton.isChecked())
      gammaParameterSetNode.SetUseGeometricGammaCalculation(self.step5_useGeometricGammaCalculation.isChecked())
      gammaParameterSetNode.SetReferenceDoseGy(self.step5_referenceDoseCustomValueCGySpinBox.value / 100.0)
      gammaParameterSetNode.SetAnalysisThresholdPercent(self.step5_analysisThresholdPercentSpinBox.value)
      gammaParameterSetNode.SetDoseThresholdOnReferenceOnly(True)
      gammaParameterSetNode.SetMaximumGamma(self.step5_maximumGammaSpinBox.value)

      # Create progress bar
      from vtkSlicerRtCommonPython import vtkSlicerRtCommon
      doseComparisonLogic = slicer.modules.dosecomparison.logic()
      self.addObserver(doseComparisonLogic, vtkSlicerRtCommon.ProgressUpdated, self.onGammaProgressUpdated)
      self.gammaProgressDialog = qt.QProgressDialog(self.parent)
      self.gammaProgressDialog.setModal(True)
      self.gammaProgressDialog.setMinimumDuration(150)
      self.gammaProgressDialog.labelText = "Computing gamma dose difference..."
      self.gammaProgressDialog.show()
      slicer.app.processEvents()

      # Perform gamma comparison
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      errorMessage = doseComparisonLogic.ComputeGammaDoseDifference(gammaParameterSetNode)

      self.gammaProgressDialog.hide()
      self.gammaProgressDialog = None
      self.removeObserver(doseComparisonLogic, vtkSlicerRtCommon.ProgressUpdated, self.onGammaProgressUpdated)
      qt.QApplication.restoreOverrideCursor()

      if gammaParameterSetNode.GetResultsValid():
        self.step5_gammaStatusLabel.setText('Gamma dose comparison succeeded\nPass fraction: {0:.2f}%'.format(gammaParameterSetNode.GetPassFractionPercent()))
        self.step5_showGammaReportButton.enabled = True
        self.gammaReport = gammaParameterSetNode.GetReportString()
      else:
        self.step5_gammaStatusLabel.setText(errorMessage)
        self.step5_showGammaReportButton.enabled = False

      # Show gamma volume
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      selectionNode.SetActiveVolumeID(self.step5_gammaVolumeSelector.currentNodeID)
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()

      # Show mask structure with some transparency
      if self.logic.maskSegmentationNode:
        self.logic.maskSegmentationNode.GetDisplayNode().SetVisibility(1)
        if self.logic.maskSegmentID:
          self.logic.maskSegmentationNode.GetDisplayNode().SetSegmentVisibility(self.logic.maskSegmentID, True)
          self.logic.maskSegmentationNode.GetDisplayNode().SetSegmentOpacity3D(self.logic.maskSegmentID, 0.5)

      # Show gamma slice in 3D view
      layoutManager = self.layoutWidget.layoutManager()
      sliceViewerWidgetRed = layoutManager.sliceWidget('Red')
      sliceLogicRed = sliceViewerWidgetRed.sliceLogic()
      sliceLogicRed.StartSliceNodeInteraction(slicer.vtkMRMLSliceNode.SliceVisibleFlag)
      sliceLogicRed.GetSliceNode().SetSliceVisible(1)
      sliceLogicRed.EndSliceNodeInteraction()

      # Set gamma window/level
      maximumGamma = self.step5_maximumGammaSpinBox.value
      gammaDisplayNode = self.logic.gammaVolumeNode.GetDisplayNode()
      gammaDisplayNode.AutoWindowLevelOff()
      gammaDisplayNode.SetWindowLevelMinMax(0, maximumGamma)
      gammaDisplayNode.ApplyThresholdOn()
      gammaDisplayNode.AutoThresholdOff()
      gammaDisplayNode.SetLowerThreshold(0.001)

      # Center 3D view
      layoutManager = self.layoutWidget.layoutManager()
      threeDWidget = layoutManager.threeDWidget(0)
      if threeDWidget is not None and threeDWidget.threeDView() is not None:
        threeDWidget.threeDView().resetFocalPoint()

    except Exception as e:
      import traceback
      traceback.print_exc()
      logging.error('Failed to perform gamma dose comparison!')

  #------------------------------------------------------------------------------
  def onGammaProgressUpdated(self, logic, event):
    if self.gammaProgressDialog:
      self.gammaProgressDialog.value = logic.GetProgress() * 100.0
      slicer.app.processEvents()

  #------------------------------------------------------------------------------
  def onShowGammaReport(self):
    if hasattr(self,"gammaReport"):
      qt.QMessageBox.information(None, 'Gamma computation report', self.gammaReport)
    else:
      qt.QMessageBox.information(None, 'Gamma computation report missing', 'No report available!')

  #------------------------------------------------------------------------------
  # Step T1

  #------------------------------------------------------------------------------
  def onStepT1_LineProfileCollapsed(self, collapsed):
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()

    # Change to quantitative view on enter, change back on leave
    if collapsed == False:
      self.currentLayoutIndex = self.step0_viewSelectorComboBox.currentIndex
      self.onViewSelect(5)

      # Switch to place ruler mode
      selectionNode.SetReferenceActivePlaceNodeClassName("vtkMRMLAnnotationRulerNode")
    else:
      self.onViewSelect(self.currentLayoutIndex)

    # Show volumes
    if self.logic.croppedPlanDoseSliceVolumeNode:
      selectionNode.SetActiveVolumeID(self.logic.croppedPlanDoseSliceVolumeNode.GetID())
    if self.logic.calibratedExperimentalFilmVolumeNode:
      selectionNode.SetSecondaryVolumeID(self.logic.calibratedExperimentalFilmVolumeNode.GetID())
    appLogic = slicer.app.applicationLogic()
    appLogic.PropagateVolumeSelection()

  #------------------------------------------------------------------------------
  def onCreateLineProfileButton(self):
    # Create table nodes for the results
    if not hasattr(self, 'lineProfileTableNode'):
      self.lineProfileTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")

    # Set up line profile logic
    self.lineProfileLogic.outputPlotSeriesNodes = {}
    self.lineProfileLogic.outputTableNode = self.lineProfileTableNode
    self.lineProfileLogic.inputRulerNode = self.stepT1_inputRulerSelector.currentNode()
    self.lineProfileLogic.enableAutoUpdate(True)

    rulerLengthMm = self.lineProfileLogic.computeRulerLength(self.lineProfileLogic.inputRulerNode)
    lineResolutionMm = float(self.stepT1_lineResolutionMmSliderWidget.value)
    self.lineProfileLogic.lineResolution = int( (rulerLengthMm / lineResolutionMm) + 0.5 )

    # Get number of samples based on selected sampling density
    self.lineProfileLogic.inputVolumeNodes = []
    if self.logic.croppedPlanDoseSliceVolumeNode:
      self.lineProfileLogic.inputVolumeNodes.append(self.logic.croppedPlanDoseSliceVolumeNode)
      if not hasattr(self, 'croppedPlanDoseSlicePlotSeriesNode'):
        self.croppedPlanDoseSlicePlotSeriesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode")
      self.lineProfileLogic.outputPlotSeriesNodes[self.logic.croppedPlanDoseSliceVolumeNode.GetID()] = self.croppedPlanDoseSlicePlotSeriesNode
    if self.logic.calibratedExperimentalFilmVolumeNode:
      self.lineProfileLogic.inputVolumeNodes.append(self.logic.calibratedExperimentalFilmVolumeNode)
      if not hasattr(self, 'calibratedExperimentalFilmPlotSeriesNode'):
        self.calibratedExperimentalFilmPlotSeriesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode")
      self.lineProfileLogic.outputPlotSeriesNodes[self.logic.calibratedExperimentalFilmVolumeNode.GetID()] = self.calibratedExperimentalFilmPlotSeriesNode
    if self.logic.gammaVolumeNode:
      self.lineProfileLogic.inputVolumeNodes.append(self.logic.gammaVolumeNode)
      if not hasattr(self, 'gammaPlotSeriesNode'):
        self.gammaPlotSeriesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode")
      self.lineProfileLogic.outputPlotSeriesNodes[self.logic.gammaVolumeNode.GetID()] = self.gammaPlotSeriesNode

    self.lineProfileLogic.update()

  #------------------------------------------------------------------------------
  def onLegendVisibilityToggled(self, on):
    if self.lineProfileLogic.plotChartNode is None:
      message = 'Need to create line profile first'
      logging.error(message)
      qt.QMessageBox.critical(None, 'Error', message)
      return

    self.lineProfileLogic.plotChartNode.SetLegendVisibility(on)

  #------------------------------------------------------------------------------
  def onSelectLineProfileParameters(self):
    self.stepT1_createLineProfileButton.enabled = self.logic.croppedPlanDoseSliceVolumeNode and self.logic.calibratedExperimentalFilmVolumeNode and self.stepT1_inputRulerSelector.currentNode()

  #------------------------------------------------------------------------------
  def onExportLineProfiles(self):
    import os

    if not hasattr(self, 'lineProfileTableNode'):
      message = 'Need to create line profile first'
      logging.error(message)
      qt.QMessageBox.critical(None, 'Line profiles values cannot be exported', message)
      return

    self.outputDir = slicer.app.temporaryPath + '/FilmDosimetry'
    if not os.access(self.outputDir, os.F_OK):
      os.mkdir(self.outputDir)

    # Assemble file name for calibration curve points file
    from time import gmtime, strftime
    fileName = self.outputDir + '/' + strftime("%Y%m%d_%H%M%S_", gmtime()) + 'LineProfiles.csv'

    storageNode = self.lineProfileTableNode.CreateDefaultStorageNode()
    storageNode.SetFileName(fileName)
    success = storageNode.WriteData(self.lineProfileTableNode)

    if success == 1:
      message = 'Dose line profiles saved in file\n' + fileName + '\n\n'
      qt.QMessageBox.information(None, 'Line profiles values exported', message)
    else:
      message = 'Failed to save line profile'
      logging.error(message)
      qt.QMessageBox.critical(None, 'Failed to save line profile', message)



  #
  # -------------------------
  # Testing related functions
  # -------------------------
  #
  def onSelfTestButtonClicked(self):
    # Test data
    calibrationBatchMrmlSceneFilePath = "d:/data/RT_Dosimetry/20160624_FilmDosimetry_TestDataset/Batch/20161108_153010_CalibrationBatchScene.mrml"
    experimentalFilmFilePath = 'd:/data/RT_Dosimetry/20160624_FilmDosimetry_TestDataset/20160624_FSRTFilms/experiment.png'
    experimentalFilmSpacing = 0.426
    planDoseVolumeFilePath = "d:/data/RT_Dosimetry/20160624_FilmDosimetry_TestDataset/RD.PYPHANTOMTEST_.dcm"
    floodFieldImageNodeName = 'blank'
    experimentalFilmNodeName = 'experiment'
    planDoseVolumeNodeName = '184: RTDOSE: Eclipse Doses'
    calibrationFunctionFilePath = "d:/data/RT_Dosimetry/20160624_FilmDosimetry_TestDataset/20160804_231433_FilmDosimetryCalibrationFunctionCoefficients.txt"

    # Step 1
    #
    # Load calibration batch
    success = slicer.util.loadScene(calibrationBatchMrmlSceneFilePath)
    print("Batch loaded successfully: " + str(success))

    #TODO: Test perform calibration too

    # Step 2
    #
    # Load experimental film and set spacing
    slicer.util.loadVolume(experimentalFilmFilePath)
    self.step2_experimentalFilmSpacingLineEdit.text = experimentalFilmSpacing
    print("Experimental film loaded")

    # Load plan dose from DICOM
    dicomRtPluginInstance = slicer.modules.dicomPlugins['DicomRtImportExportPlugin']()
    loadables = dicomRtPluginInstance.examineForImport([[planDoseVolumeFilePath]])
    dicomRtPluginInstance.load(loadables[0])
    self.logic.setAutoWindowLevelToAllDoseVolumes()
    print("DICOM loaded")

    # Assign roles
    self.step2_floodFieldImageSelectorComboBox.setCurrentNode(slicer.util.getNode(floodFieldImageNodeName))
    self.step2_experimentalFilmSelectorComboBox.setCurrentNode(slicer.util.getNode(experimentalFilmNodeName))
    self.step2_planDoseVolumeSelector.setCurrentNode(slicer.util.getNode(planDoseVolumeNodeName))

    if not self.saveExperimentalDataSelection():
      logging.error("Experimental data selection invalid")
      return

    # Step 3
    #
    # Load calibration from file
    self.loadCalibrationFunctionFromFile(calibrationFunctionFilePath)

    # Apply calibration
    self.logic.applyCalibrationOnExperimentalFilm()

    # Step 4
    #
    # Perform registration
    self.logic.initializeFilmToPlanDoseRegistration()
    self.logic.registerExperimentalFilmToPlanDose()

    # Show registered images
    # appLogic = slicer.app.applicationLogic()
    # selectionNode = appLogic.GetSelectionNode()
    # selectionNode.SetActiveVolumeID(self.logic.paddedCalibratedExperimentalFilmVolumeNode.GetID())
    # selectionNode.SetSecondaryVolumeID(self.logic.paddedPlanDoseSliceVolumeNode.GetID())
    # appLogic.PropagateVolumeSelection()

    # Step 5
    self.step5_doseComparisonCollapsibleButton.setChecked(True)
    self.step5_maskSegmentationSelector.setCurrentNode(None) #TODO: Use mask
    self.step5_gammaVolumeSelector.addNode()
    self.onGammaDoseComparison()


#
# FilmDosimetryAnalysis
#
class FilmDosimetryAnalysis(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    parent.title = "Film Dosimetry Analysis"
    parent.categories = ["Slicelets"]
    parent.dependencies = ["DicomRtImportExport", "BRAINSFit", "CropVolume", "ResampleScalarVolume", "Annotations", "DataProbe", "DoseComparison"]
    parent.contributors = ["Csaba Pinter (Queen's University), Kevin Alexander (KGH, Queen's University), Alec Robinson (Queen's University)"] # replace with "Firstname Lastname (Org)"
    parent.helpText = "Slicelet for film dosimetry analysis"
    parent.acknowledgementText = """
    This file was originally developed by Kevin Alexander (KGH, Queen's University), Csaba Pinter (Queen's University), and Alec Robinson (Queen's University). Funding was provided by CIHR
    """
    iconPath = os.path.join(os.path.dirname(self.parent.path), 'Resources/Icons', self.moduleName+'.png')
    parent.icon = qt.QIcon(iconPath)


#
# FilmDosimetryAnalysisWidget
#
class FilmDosimetryAnalysisWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)
    slicer.test = self

    # Show slicelet button
    launchSliceletButton = qt.QPushButton("Show slicelet")
    launchSliceletButton.toolTip = "Launch the slicelet"
    self.layout.addWidget(qt.QLabel(' '))
    self.layout.addWidget(launchSliceletButton)
    launchSliceletButton.connect('clicked()', self.onShowSliceletButtonClicked)

    # Add vertical spacer
    self.layout.addStretch(1)

  def onShowSliceletButtonClicked(self):
    mainFrame = SliceletMainFrame()
    mainFrame.minimumWidth = 1200
    mainFrame.windowTitle = "Film dosimetry analysis"
    mainFrame.setWindowFlags(qt.Qt.WindowCloseButtonHint | qt.Qt.WindowMaximizeButtonHint | qt.Qt.WindowTitleHint)
    iconPath = os.path.join(os.path.dirname(slicer.modules.filmdosimetryanalysis.path), 'Resources/Icons', self.moduleName+'.png')
    mainFrame.windowIcon = qt.QIcon(iconPath)
    mainFrame.connect('destroyed()', self.onSliceletClosed)

    slicelet = FilmDosimetryAnalysisSlicelet(mainFrame, self.developerMode)
    mainFrame.setSlicelet(slicelet)

    # Make the slicelet reachable from the Slicer python interactor for testing
    slicer.filmDosimetrySliceletInstance = slicelet

  def onSliceletClosed(self):
    logging.debug('Slicelet closed')

#
# FilmDosimetryAnalysisTest
#
class FilmDosimetryAnalysisTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()

#
# Main
#
if __name__ == "__main__":
  #TODO: access and parse command line arguments
  #   Example: SlicerRt/src/BatchProcessing
  #   Ideally handle --xml

  import sys
  logging.debug( sys.argv )

  mainFrame = qt.QFrame()
  slicelet = FilmDosimetryAnalysisSlicelet(mainFrame)
