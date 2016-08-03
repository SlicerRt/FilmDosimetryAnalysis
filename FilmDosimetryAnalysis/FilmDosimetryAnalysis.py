import os
import math
import ntpath
import shutil
import unittest
import numpy
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging
import FilmDosimetryAnalysisLogic
import DataProbeLib
from slicer.util import VTKObservationMixin
from vtk.util import numpy_support
import glob


#
# Film dosimetry analysis slicelet
#
# Streamlined workflow end-user application based on 3D Slicer and SlicerRT to support
# 3D film-based radiation dosimetry.
#
# The all-caps terms correspond to data objects in the film dosimetry data flow diagram
# https://subversion.assembla.com/svn/slicerrt/trunk/FilmDosimetryAnalysis/doc/FilmDosimetryFlowchart.pdf
#

#
# FilmDosimetryAnalysisSliceletWidget
#
class FilmDosimetryAnalysisSliceletWidget:
  def __init__(self, parent=None):
    try:
      parent
      self.parent = parent

    except Exception, e:
      import traceback
      traceback.print_exc()
      logging.error("There is no parent to FilmDosimetryAnalysisSliceletWidget!")

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

    if not developerMode:
      self.selfTestButton.setVisible(False)

    # Initiate and group together all panels
    self.step0_layoutSelectionCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_calibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_loadExperimentalDataCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step3_applyCalibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step4_CollapsibleButton = ctk.ctkCollapsibleButton()
    self.step5_CollapsibleButton = ctk.ctkCollapsibleButton()
    self.testButton = ctk.ctkCollapsibleButton()

    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.step0_layoutSelectionCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step1_calibrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step2_loadExperimentalDataCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step3_applyCalibrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step4_CollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step5_CollapsibleButton)   

    self.collapsibleButtonsGroup.addButton(self.testButton)

    self.step1_calibrationCollapsibleButton.setProperty('collapsed', False)

    # Create module logic
    # self.logic = FilmDosimetryAnalysisLogic.FilmDosimetryAnalysisLogic() #TODO (include as well)

    # Declare member variables (selected at certain steps and then from then on for the workflow)
    self.folderNode = None #TODO: Not needed
    self.batchFolderToParse = None
    self.lastAddedRoiNode = None
    self.calculatedDoseNode = None
    self.experimentalFilmDoseVolume = None 
    self.experimentalFilmDoseVolumeNamePostfix = "_Calibrated"
    self.inputDICOMDoseVolume = None
    self.dosePlanVolume = None 
    self.dosePlanVolumeName = "Dose plan resampled"
    self.experimentalToDoseTransform = None 
    
    self.experimentalFloodFieldImageNode = None
    self.experimentalFilmImageNode = None 
    
    self.measuredOpticalDensityToDoseMap = [] #TODO: Make it a real map (need to sort by key where it is created)

    # Set up constants
    self.saveCalibrationBatchFolderNodeNamePrefix = "Calibration batch"
    self.calibrationVolumeDoseAttributeName = "Dose"
    self.floodFieldAttributeValue = "FloodField"
    self.floodFieldImageShNodeName = "FloodFieldImage" #TODO: Do not rename node, and use the attribute to identify
    self.calibrationVolumeName = "CalibrationVolume" #TODO: Do not rename node, and use the attribute to identify
    self.calibrationBatchSceneFileName = "CalibrationBatchScene.mrml"
    self.calibrationFunctionFileName = "FilmDosinetryCalibrationFunctionCoefficients"
    self.experimentalCenter2DoseCenterTransformName = "Experimental to dose translation"
    self.experimentalAxialToExperimentalCoronalTransformName = "Experimental film axial to coronal transform"
    self.experimentalRotate90APTransformName = "Experimental rotate 90 around AP axis"
    self.cropDoseByROIName = "crop dose ROI" 
    self.experimentalToDoseTransformName = "Experimental film to dose transform"
    
    self.maxNumberOfCalibrationVolumes = 10
    self.opticalDensityCurve = None # Polyfit
    self.calibrationCoefficients = [0,0,0,0] # Calibration coefficients [a,b,c,n] in calibration function dose = a + b*OD + c*OD^n
    self.resolutionMM_ToPixel = None

    # Set observations
    self.addObserver(slicer.mrmlScene, slicer.vtkMRMLScene.NodeAddedEvent, self.onNodeAdded)
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndImportEvent, self.onSceneEndImport)

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

    # Set up step panels
    self.setup_Step0_LayoutSelection()
    self.setup_Step1_Calibration()
    self.setup_Step2_LoadExperimentalData()
    self.setup_Step3_ApplyCalibration()
    self.setup_Step4_Registration()
    self.setup_Step5_GammaComparison()

    if widgetClass:
      self.widget = widgetClass(self.parent)
    self.parent.show()

  #------------------------------------------------------------------------------
  # Disconnect all connections made to the slicelet to enable the garbage collector to destruct the slicelet object on quit
  def disconnect(self):
    self.step0_viewSelectorComboBox.disconnect('activated(int)', self.onViewSelect)
    self.step1_loadImageFilesButton.disconnect('clicked()', self.onLoadImageFilesButton)
    self.step1_numberOfCalibrationFilmsSpinBox.disconnect('valueChanged(int)', self.onNumberOfCalibrationFilmsSpinBoxValueChanged)
    self.step1_saveCalibrationBatchButton.disconnect('clicked()', self.onSaveCalibrationBatchButton)
    self.step1_loadCalibrationBatchButton.disconnect('clicked()', self.onLoadCalibrationBatchButton)
    self.step1_saveCalibrationButton.disconnect('clicked()', self.exportCalibrationResultToFile)
    self.step1_addRoiButton.disconnect('clicked()', self.onAddRoiButton)
    self.step1_performCalibrationButton.disconnect('clicked()', self.onPerformCalibrationButton)
    self.step2_loadNonDicomDataButton.disconnect('clicked()', self.onLoadImageFilesButton)
    self.step2_showDicomBrowserButton.disconnect('clicked()', self.onDicomLoad)
    self.step2_loadExperimentalDataCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onstep2_loadExperimentalDataCollapsed)
    self.step3_calibrationFunctionOrder0LineEdit.disconnect('textChanged()', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionOrder1LineEdit.disconnect('textChanged()', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionOrder2LineEdit.disconnect('textChanged()', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionExponentLineEdit.disconnect('textChanged()', self.onCalibrationFunctionLineEditChanged)
    self.step3_applyCalibrationButton.disconnect('clicked()', self.onApplyCalibrationButton)
    self.step3_loadCalibrationButton.disconnect('clicked()', self.onLoadCalibrationFunctionButton)
    self.step4_resolutionLineEdit.disconnect('textChanged(QString)', self.onResolutionLineEditTextChanged)
    self.step4_performRegistrationButton.disconnect('clicked()', self.onPerformRegistrationButtonClicked)

  #------------------------------------------------------------------------------
  def setup_Step0_LayoutSelection(self):
    # Layout selection step
    self.step0_layoutSelectionCollapsibleButton.setProperty('collapsedHeight', 4)
    #TODO: Change back if there are more modes
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
    self.step0_viewSelectorComboBox.connect('activated(int)', self.onViewSelect)

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
    # Step 1: Load data panel
    self.step1_calibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_calibrationCollapsibleButton.text = "1. Calibration (optional)"
    self.sliceletPanelLayout.addWidget(self.step1_calibrationCollapsibleButton)

    # Step 1 main background layout
    self.step1_calibrationLayout = qt.QVBoxLayout(self.step1_calibrationCollapsibleButton)

    # Step 1.1: Load calibration data
    self.step1_1_loadCalibrationDataCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_1_loadCalibrationDataCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_1_loadCalibrationDataCollapsibleButton.text = "1.1. Load calibration data"
    self.step1_calibrationLayout.addWidget(self.step1_1_loadCalibrationDataCollapsibleButton)

    self.step1_1_loadCalibrationDataLayout = qt.QVBoxLayout(self.step1_1_loadCalibrationDataCollapsibleButton)
    self.step1_1_loadCalibrationDataLayout.setContentsMargins(12,4,4,4)
    self.step1_1_loadCalibrationDataLayout.setSpacing(4)

    # Step 1 top third sub-layout
    self.step1_topCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_1_loadCalibrationDataLayout.addLayout(self.step1_topCalibrationSubLayout)

    # Load data label
    self.step1_CalibrationLabel = qt.QLabel("Load all image data involved in the workflow.\nCan either be a new batch of image files, or a saved image batch")
    self.step1_CalibrationLabel.wordWrap = True
    self.step1_topCalibrationSubLayout.addWidget(self.step1_CalibrationLabel)

    # Load image data button
    self.step1_loadImageFilesButton = qt.QPushButton("Load image files")
    self.step1_loadImageFilesButton.toolTip = "Load png film images."
    self.step1_loadImageFilesButton.name = "loadImageFilesButton"
    # Load saved image batch button
    self.step1_loadCalibrationBatchButton = qt.QPushButton("Load calibration batch")
    self.step1_loadCalibrationBatchButton.toolTip = "Load a batch of films with assigned doses."
    self.step1_loadCalibrationBatchButton.name = "loadCalibrationFilesButton"
    # Horizontal button layout
    self.step1_loadImageButtonLayout = qt.QHBoxLayout()
    self.step1_loadImageButtonLayout.addWidget(self.step1_loadImageFilesButton)
    self.step1_loadImageButtonLayout.addWidget(self.step1_loadCalibrationBatchButton)

    self.step1_topCalibrationSubLayout.addLayout(self.step1_loadImageButtonLayout)

    # Assign data label
    self.step1_AssignDataLabel = qt.QLabel("Assign loaded data to roles.\nNote: If this selection is changed later then all the following steps need to be performed again")
    self.step1_AssignDataLabel.wordWrap = True
    self.step1_topCalibrationSubLayout.addWidget(self.step1_AssignDataLabel)

    # Number of calibration films node selector
    self.step1_numberOfCalibrationFilmsSelectorLayout = qt.QHBoxLayout()
    self.step1_numberOfCalibrationFilmsSpinBox = qt.QSpinBox()
    self.step1_numberOfCalibrationFilmsSpinBox.value = 5
    self.step1_numberOfCalibrationFilmsSpinBox.maximum = 10
    self.step1_numberOfCalibrationFilmsSpinBox.minimum = 0
    self.step1_numberOfCalibrationFilmsSpinBox.enabled = True
    self.step1_numberOfCalibrationFilmsLabelBefore = qt.QLabel('Number of calibration films is: ')
    self.step1_numberOfCalibrationFilmsSelectorLayout.addWidget(self.step1_numberOfCalibrationFilmsLabelBefore)
    self.step1_numberOfCalibrationFilmsSelectorLayout.addWidget(self.step1_numberOfCalibrationFilmsSpinBox)
    self.step1_topCalibrationSubLayout.addLayout(self.step1_numberOfCalibrationFilmsSelectorLayout)

    # Choose the flood field image
    self.step1_floodFieldImageSelectorComboBoxLayout = qt.QHBoxLayout()
    self.step1_floodFieldImageSelectorComboBox = slicer.qMRMLNodeComboBox()
    self.step1_floodFieldImageSelectorComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_floodFieldImageSelectorComboBox.addEnabled = True
    self.step1_floodFieldImageSelectorComboBox.removeEnabled = True
    self.step1_floodFieldImageSelectorComboBox.setMRMLScene( slicer.mrmlScene )
    self.step1_floodFieldImageSelectorComboBox.setToolTip( "--choose the flood field image file-- ." )
    self.step1_floodFieldImageSelectorComboBoxLabel = qt.QLabel('Flood field image: ')
    self.step1_floodFieldImageSelectorComboBoxLayout.addWidget(self.step1_floodFieldImageSelectorComboBoxLabel)
    self.step1_floodFieldImageSelectorComboBoxLayout.addWidget(self.step1_floodFieldImageSelectorComboBox)
    self.step1_topCalibrationSubLayout.addLayout(self.step1_floodFieldImageSelectorComboBoxLayout)

    self.step1_middleCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_1_loadCalibrationDataLayout.addLayout(self.step1_middleCalibrationSubLayout)

    self.step1_calibrationVolumeLayoutList = []
    self.step1_calibrationVolumeSelectorLabelBeforeList = []
    self.step1_calibrationVolumeSelectorCGySpinBoxList = []
    self.step1_calibrationVolumeSelectorCGyLabelList = []
    self.step1_calibrationVolumeSelectorComboBoxList = []

    for doseToImageLayoutNumber in xrange(self.maxNumberOfCalibrationVolumes):
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
      self.doseToImageFilmSelector.setToolTip( "Choose the film image corresponding to the dose above" )
      self.step1_calibrationVolumeSelectorComboBoxList.append(self.doseToImageFilmSelector)

      self.step1_doseToImageSelectorRowLayout.addWidget(self.step1_mainCalibrationVolumeSelectorLabelBefore)
      self.step1_doseToImageSelectorRowLayout.addWidget(self.doseToImageSelectorCGySpinBox)
      self.step1_doseToImageSelectorRowLayout.addWidget(self.doseToImageSelectorLabelMiddle)
      self.step1_doseToImageSelectorRowLayout.addWidget(self.doseToImageFilmSelector)

      self.step1_calibrationVolumeLayoutList.append(self.step1_doseToImageSelectorRowLayout)
      self.step1_middleCalibrationSubLayout.addLayout(self.step1_doseToImageSelectorRowLayout)

    self.step1_bottomCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_1_loadCalibrationDataLayout.addLayout(self.step1_bottomCalibrationSubLayout)

    self.updateStep1CalibrationPanel(self.step1_numberOfCalibrationFilmsSpinBox.value)

    # Save batch button
    self.step1_saveCalibrationBatchButton = qt.QPushButton("Save calibration batch")
    self.step1_saveCalibrationBatchButton.toolTip = "Saves current calibration batch"
    self.step1_bottomCalibrationSubLayout.addWidget(self.step1_saveCalibrationBatchButton)

    # Add empty row
    self.step1_bottomCalibrationSubLayout.addWidget(qt.QLabel(''))

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

    #TODO:
    self.blankLabel = qt.QLabel('')
    self.step1_2_performCalibrationLayout.addWidget(self.blankLabel)
    # Dose calibration function label
    self.step1_2_performCalibrationFunctionLabel = qt.QLabel(" ")
    self.step1_2_performCalibrationLayout.addWidget(self.step1_2_performCalibrationFunctionLabel)

    self.step1_2_performCalibrationLayout.addWidget(self.blankLabel)

    # Save calibration function button
    self.step1_saveCalibrationButton = qt.QPushButton("Save calibration function")
    self.step1_saveCalibrationButton.toolTip = "Save calibration function for later use"
    self.step1_2_performCalibrationLayout.addWidget(self.step1_saveCalibrationButton)

    self.step1_bottomCalibrationSubLayout.addStretch(1)

    # Step 1 sub button group
    self.step1_calibrationCollapsibleButtonGroup = qt.QButtonGroup()
    self.step1_calibrationCollapsibleButtonGroup.addButton(self.step1_1_loadCalibrationDataCollapsibleButton)
    self.step1_calibrationCollapsibleButtonGroup.addButton(self.step1_2_performCalibrationCollapsibleButton)

    self.step1_1_loadCalibrationDataCollapsibleButton.setProperty('collapsed', False)

    # Connections
    self.step1_loadImageFilesButton.connect('clicked()', self.onLoadImageFilesButton)
    self.step1_saveCalibrationBatchButton.connect('clicked()', self.onSaveCalibrationBatchButton)
    self.step1_loadCalibrationBatchButton.connect('clicked()', self.onLoadCalibrationBatchButton)
    self.step1_numberOfCalibrationFilmsSpinBox.connect('valueChanged(int)', self.onNumberOfCalibrationFilmsSpinBoxValueChanged)
    self.step1_addRoiButton.connect('clicked()', self.onAddRoiButton)
    self.step1_performCalibrationButton.connect('clicked()', self.onPerformCalibrationButton)
    self.step1_saveCalibrationButton.connect('clicked()', self.exportCalibrationResultToFile)

  #------------------------------------------------------------------------------
  def setup_Step2_LoadExperimentalData(self):
  # Step 2: Load data panel
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
    self.step2_emptyLabel = qt.QLabel("   ")
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(self.step2_emptyLabel)

    # Assign loaded data to roles
    self.step2_assignDataLabel = qt.QLabel("Assign loaded data to roles.\nNote: If this selection is changed later then all the following steps need to be performed again")
    self.step2_assignDataLabel.wordWrap = True
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(self.step2_assignDataLabel)

    # Choose the experimental flood field image
    self.step2_floodFieldImageSelectorComboBoxLayout = qt.QHBoxLayout()
    self.step2_floodFieldImageSelectorComboBox = slicer.qMRMLNodeComboBox()
    self.step2_floodFieldImageSelectorComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step2_floodFieldImageSelectorComboBox.addEnabled = False
    self.step2_floodFieldImageSelectorComboBox.removeEnabled = False
    self.step2_floodFieldImageSelectorComboBox.setMRMLScene( slicer.mrmlScene )
    self.step2_floodFieldImageSelectorComboBox.setToolTip( "--select the flood field image file--" )
    self.step2_floodFieldImageSelectorComboBoxLabel = qt.QLabel('Flood field image (experimental): ')
    self.step2_floodFieldImageSelectorComboBoxLayout.addWidget(self.step2_floodFieldImageSelectorComboBoxLabel)
    self.step2_floodFieldImageSelectorComboBoxLayout.addWidget(self.step2_floodFieldImageSelectorComboBox)
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addLayout(self.step2_floodFieldImageSelectorComboBoxLayout)

    # Choose the experimental film image
    self.step2_experimentalFilmSelectorComboBoxLayout = qt.QHBoxLayout()
    self.step2_experimentalFilmSelectorComboBox = slicer.qMRMLNodeComboBox()
    self.step2_experimentalFilmSelectorComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step2_experimentalFilmSelectorComboBox.addEnabled = False
    self.step2_experimentalFilmSelectorComboBox.removeEnabled = False
    self.step2_experimentalFilmSelectorComboBox.setMRMLScene( slicer.mrmlScene )
    self.step2_experimentalFilmSelectorComboBox.setToolTip( "--select the experimental film image file--" )
    self.step2_experimentalFilmSelectorComboBoxLabel = qt.QLabel('Experimental film image: ')
    self.step2_experimentalFilmSelectorComboBoxLayout.addWidget(self.step2_experimentalFilmSelectorComboBoxLabel)
    self.step2_experimentalFilmSelectorComboBoxLayout.addWidget(self.step2_experimentalFilmSelectorComboBox)
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addLayout(self.step2_experimentalFilmSelectorComboBoxLayout)

    # PLANDOSE node selector
    self.step2_doseVolumeSelectorComboBoxLayout = qt.QHBoxLayout()
    self.step2_doseVolumeSelector = slicer.qMRMLNodeComboBox()
    self.step2_doseVolumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step2_doseVolumeSelector.addEnabled = False
    self.step2_doseVolumeSelector.removeEnabled = False
    self.step2_doseVolumeSelector.setMRMLScene( slicer.mrmlScene )
    self.step2_doseVolumeSelector.setToolTip( "Pick the planning dose volume." )
    self.step2_doseVolumeSelectorComboBoxLabel = qt.QLabel('Dose volume: ')
    self.step2_doseVolumeSelectorComboBoxLayout.addWidget(self.step2_doseVolumeSelectorComboBoxLabel)
    self.step2_doseVolumeSelectorComboBoxLayout.addWidget(self.step2_doseVolumeSelector)
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addLayout(self.step2_doseVolumeSelectorComboBoxLayout)

    # Enter plane position
    self.step2_planePositionLabel = qt.QLabel('Plane position :')
    self.step2_planePositionLineEdit = qt.QLineEdit()
    self.step2_planePositionQHBoxLayout = qt.QHBoxLayout()
    self.step2_planePositionQHBoxLayout.addWidget(self.step2_planePositionLabel)
    self.step2_planePositionQHBoxLayout.addWidget(self.step2_planePositionLineEdit)

    # Connections
    self.step2_loadNonDicomDataButton.connect('clicked()', self.onLoadImageFilesButton)
    self.step2_showDicomBrowserButton.connect('clicked()', self.onDicomLoad)
    self.step2_loadExperimentalDataCollapsibleButton.connect('contentsCollapsed(bool)', self.onstep2_loadExperimentalDataCollapsed)

  #------------------------------------------------------------------------------
  def setup_Step3_ApplyCalibration(self):
  # Step 2: Load data panel
    self.step3_applyCalibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step3_applyCalibrationCollapsibleButton.text = "3. Apply calibration"
    self.sliceletPanelLayout.addWidget(self.step3_applyCalibrationCollapsibleButton)

    self.step3_applyCalibrationCollapsibleButtonLayout = qt.QVBoxLayout(self.step3_applyCalibrationCollapsibleButton)
    self.step3_applyCalibrationCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step3_applyCalibrationCollapsibleButtonLayout.setSpacing(4)

    # Load calibration function button
    self.step3_loadCalibrationButton = qt.QPushButton("Load calibration function")
    self.step3_loadCalibrationButton.toolTip = "Loads calibration function \n Function can also be added into text fields"
    self.step3_applyCalibrationCollapsibleButtonLayout.addWidget(self.step3_loadCalibrationButton)

    # Dose calibration function input fields
    self.step3_calibrationFunctionLayout = qt.QGridLayout()
    self.step1_doseLabel = qt.QLabel('Dose (Gy) = ')
    self.step3_applyCalibrationCollapsibleButtonLayout.addWidget(self.step1_doseLabel)

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
    self.step3_calibrationFunctionExponentLineEdit.maximumWidth = 64

    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder0LineEdit,0,1)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder0Label,0,2)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder1LineEdit,0,3)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder1Label,0,4)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder2LineEdit,0,5)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder2Label,0,6)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionExponentLineEdit,1,1)
    self.step3_applyCalibrationCollapsibleButtonLayout.addLayout(self.step3_calibrationFunctionLayout)


    # Apply calibration button
    self.step3_applyCalibrationButton = qt.QPushButton("Apply calibration function")
    self.step3_applyCalibrationButton.toolTip = "Apply calibration to experimental film."
    self.step3_applyCalibrationCollapsibleButtonLayout.addWidget(self.step3_applyCalibrationButton)

    # Connections
    self.step3_applyCalibrationButton.connect('clicked()', self.onApplyCalibrationButton)
    self.step3_loadCalibrationButton.connect('clicked()', self.onLoadCalibrationFunctionButton)
    self.step3_calibrationFunctionOrder0LineEdit.connect('textChanged(QString)', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionOrder1LineEdit.connect('textChanged(QString)', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionOrder2LineEdit.connect('textChanged(QString)', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionExponentLineEdit.connect('textChanged(QString)', self.onCalibrationFunctionLineEditChanged)

  #------------------------------------------------------------------------------
  def setup_Step4_Registration(self):
    # Step 2: Load data panel
    self.step4_CollapsibleButton.setProperty('collapsedHeight', 4)
    self.step4_CollapsibleButton.text = "4. Register film to plan"
    self.sliceletPanelLayout.addWidget(self.step4_CollapsibleButton)

    self.step4_CollapsibleButtonLayout = qt.QVBoxLayout(self.step4_CollapsibleButton)
    self.step4_CollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step4_CollapsibleButtonLayout.setSpacing(4)
    #self.sliceletPanelLayout.addStretch(1) # TODO this may need to be moved

    # Experimental film resolution mm/pixel
    self.step4_resolutionLineEdit = qt.QLineEdit()
    self.step4_resolutionLineEdit.toolTip = "Experimental film resultion (mm/pixel)"
    self.step4_resolutionLabel = qt.QLabel('Experimental Film Resolution (mm/pixel):')
    self.step4_resolutionQHBoxLayout = qt.QHBoxLayout()
    self.step4_resolutionQHBoxLayout.addWidget(self.step4_resolutionLabel)
    self.step4_resolutionQHBoxLayout.addWidget(self.step4_resolutionLineEdit)
    self.step4_CollapsibleButtonLayout.addLayout(self.step4_resolutionQHBoxLayout)
    
    # Perform registration button
    self.step4_performRegistrationButton = qt.QPushButton("Perform registration")
    self.step4_performRegistrationButton.toolTip = "Registers dose volume to the experimental output \n "
    self.step4_CollapsibleButtonLayout.addWidget(self.step4_performRegistrationButton)
    
    # Connections 
    self.step4_resolutionLineEdit.connect('textChanged(QString)', self.onResolutionLineEditTextChanged)
    self.step4_performRegistrationButton.connect('clicked()', self.onPerformRegistrationButtonClicked)

  #------------------------------------------------------------------------------
  def setup_Step5_GammaComparison(self):
  # TODO add to collapsible buttons group
    # Step 2: Load data panel
    self.step5_CollapsibleButton.setProperty('collapsedHeight', 4)
    self.step5_CollapsibleButton.text = "5. Gamma comparison"
    self.sliceletPanelLayout.addWidget(self.step5_CollapsibleButton)

    self.step5_CollapsibleButtonLayout = qt.QVBoxLayout(self.step5_CollapsibleButton)
    self.step5_CollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step5_CollapsibleButtonLayout.setSpacing(4)
    self.sliceletPanelLayout.addStretch(1) # TODO this may need to be moved
    
    # TODO follow onGammaDoseComparison in Gel 
    
    
  #
  # -----------------------
  # Event handler functions
  # -----------------------
  #

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
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpQuantitativeView)
    elif layoutIndex == 6:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpQuantitativeView)

  #------------------------------------------------------------------------------
  def onLoadImageFilesButton(self):
    slicer.util.openAddDataDialog()

  #------------------------------------------------------------------------------
  def onDicomLoad(self):
    slicer.modules.dicom.widgetRepresentation()
    slicer.modules.DICOMWidget.enter()

  #------------------------------------------------------------------------------
  def updateStep1CalibrationPanel(self, numberOfCalibrationFilms):
    for calibrationLayout in xrange(numberOfCalibrationFilms):
      self.step1_calibrationVolumeSelectorLabelBeforeList[calibrationLayout].visible = True
      self.step1_calibrationVolumeSelectorCGySpinBoxList[calibrationLayout].visible = True
      self.step1_calibrationVolumeSelectorCGyLabelList[calibrationLayout].visible = True
      self.step1_calibrationVolumeSelectorComboBoxList[calibrationLayout].visible = True

    for calibrationLayout in xrange(1,self.maxNumberOfCalibrationVolumes-numberOfCalibrationFilms + 1):
      self.step1_calibrationVolumeSelectorLabelBeforeList[-calibrationLayout].visible = False
      self.step1_calibrationVolumeSelectorCGySpinBoxList[-calibrationLayout].visible = False
      self.step1_calibrationVolumeSelectorCGyLabelList[-calibrationLayout].visible = False
      self.step1_calibrationVolumeSelectorComboBoxList[-calibrationLayout].visible = False

  #------------------------------------------------------------------------------
  def onstep2_loadExperimentalDataCollapsed(self, collapsed): #TODO:
    print 'onstep2_loadExperimentalDataCollapsed'
    self.experimentalFloodFieldImageNode = self.step2_floodFieldImageSelectorComboBox.currentNode() #TODO:
    self.experimentalFilmImageNode = self.step2_experimentalFilmSelectorComboBox.currentNode()
    self.inputDICOMDoseVolume = self.step2_doseVolumeSelector.currentNode()
  
  #------------------------------------------------------------------------------
  def onNumberOfCalibrationFilmsSpinBoxValueChanged(self):
    self.updateStep1CalibrationPanel(self.step1_numberOfCalibrationFilmsSpinBox.value)

  #------------------------------------------------------------------------------
  def onSaveCalibrationBatchButton(self):
    from time import gmtime, strftime

    calibrationBatchDirectoryPath = qt.QFileDialog.getExistingDirectory(0, 'Select directory to save calibration batch')
    
    calibrationBatchDirectoryFileList = os.listdir(calibrationBatchDirectoryPath)
    if len(calibrationBatchDirectoryFileList) > 0:
      message = 'Directory is not empty, please choose an empty one'
      qt.QMessageBox.critical(None, 'Empty directory must be chosen', message)
      logging.error(message)
      return

    # Create temporary scene for saving
    calibrationBatchMrmlScene = slicer.vtkMRMLScene()

    # Get folder node (create if not exists)
    exportFolderNode = None
    folderNodeName = self.saveCalibrationBatchFolderNodeNamePrefix + strftime("%Y%m%d %H%M%S", gmtime())
    self.folderNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, None, slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelFolder(), folderNodeName, None)
    # Clone folder node to export scene
    exportFolderNode = calibrationBatchMrmlScene.CopyNode(self.folderNode)

    # Get flood field image node
    floodFieldImageVolumeNode = self.step1_floodFieldImageSelectorComboBox.currentNode()
    # Create flood field image subject hierarchy node, add it under folder node
    floodFieldVolumeShNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, self.folderNode, slicer.vtkMRMLSubjectHierarchyConstants.GetDICOMLevelSeries(), self.floodFieldImageShNodeName, floodFieldImageVolumeNode)
    floodFieldVolumeShNode.SetAttribute(self.calibrationVolumeDoseAttributeName, self.floodFieldAttributeValue)
    # Copy both image and SH to exported scene
    exportFloodFieldImageVolumeNode = calibrationBatchMrmlScene.CopyNode(floodFieldImageVolumeNode)
    exportFloodFieldVolumeShNode = calibrationBatchMrmlScene.CopyNode(floodFieldVolumeShNode)
    exportFloodFieldVolumeShNode.SetParentNodeID(exportFolderNode.GetID())

    # Export flood field image storage node
    floodFieldStorageNode = floodFieldImageVolumeNode.GetStorageNode()
    exportFloodFieldStorageNode = calibrationBatchMrmlScene.CopyNode(floodFieldStorageNode)
    exportFloodFieldImageVolumeNode.SetAndObserveStorageNodeID(exportFloodFieldStorageNode.GetID())

    # Export flood field image display node
    floodFieldDisplayNode = floodFieldImageVolumeNode.GetDisplayNode()
    exportFloodFieldDisplayNode = calibrationBatchMrmlScene.CopyNode(floodFieldDisplayNode)
    exportFloodFieldImageVolumeNode.SetAndObserveDisplayNodeID(exportFloodFieldDisplayNode.GetID())

    # Copy flood field image file to save folder
    shutil.copy(floodFieldStorageNode.GetFileName(), calibrationBatchDirectoryPath)
    logging.info('Flood field image copied from' + exportFloodFieldStorageNode.GetFileName() + ' to ' + calibrationBatchDirectoryPath)
    exportFloodFieldStorageNode.SetFileName(os.path.normpath(calibrationBatchDirectoryPath + '/' + ntpath.basename(floodFieldStorageNode.GetFileName())))

    for currentCalibrationVolumeIndex in xrange(self.step1_numberOfCalibrationFilmsSpinBox.value):
      # Get current calibration image node
      currentCalibrationVolume = self.step1_calibrationVolumeSelectorComboBoxList[currentCalibrationVolumeIndex].currentNode()
      # Create calibration image subject hierarchy node, add it under folder node
      calibrationVolumeShNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, self.folderNode, slicer.vtkMRMLSubjectHierarchyConstants.GetDICOMLevelSeries(), self.calibrationVolumeName, currentCalibrationVolume)
      doseLevelAttributeValue = self.step1_calibrationVolumeSelectorCGySpinBoxList[currentCalibrationVolumeIndex].value
      calibrationVolumeShNode.SetAttribute(self.calibrationVolumeDoseAttributeName, str(doseLevelAttributeValue))
      # Copy both image and SH to exported scene
      exportCalibrationImageVolumeNode = calibrationBatchMrmlScene.CopyNode(currentCalibrationVolume)
      exportCalibrationVolumeShNode = calibrationBatchMrmlScene.CopyNode(calibrationVolumeShNode)
      exportCalibrationVolumeShNode.SetParentNodeID(exportFolderNode.GetID())

      # Export calibration image storage node
      calibrationStorageNode = currentCalibrationVolume.GetStorageNode()
      exportCalibrationStorageNode = calibrationBatchMrmlScene.CopyNode(calibrationStorageNode)
      exportCalibrationImageVolumeNode.SetAndObserveStorageNodeID(exportCalibrationStorageNode.GetID())

      # Export calibration image display node
      calibrationDisplayNode = currentCalibrationVolume.GetDisplayNode()
      exportCalibrationDisplayNode = calibrationBatchMrmlScene.CopyNode(calibrationDisplayNode)
      exportCalibrationImageVolumeNode.SetAndObserveDisplayNodeID(exportCalibrationDisplayNode.GetID())

      # Copy calibration image file to save folder, set location of exportCalibrationStorageNode file to new folder
      shutil.copy(calibrationStorageNode.GetFileName(), calibrationBatchDirectoryPath)
      logging.info('Calibration image copied from' + exportCalibrationStorageNode.GetFileName() + ' to ' + calibrationBatchDirectoryPath)
      exportCalibrationStorageNode.SetFileName(os.path.normpath(calibrationBatchDirectoryPath + '/' + ntpath.basename(calibrationStorageNode.GetFileName())))

    # Save calibration batch scene
    fileName = strftime("%Y%m%d_%H%M%S_", gmtime()) + "_" + self.calibrationBatchSceneFileName
    calibrationBatchMrmlScene.SetURL( os.path.normpath(calibrationBatchDirectoryPath + "/" + fileName) )
    calibrationBatchMrmlScene.Commit()

    # Check if scene file has been created
    if os.path.isfile(calibrationBatchMrmlScene.GetURL()) == True:
      qt.QMessageBox.information(None, "Calibration batch saving" , "Calibration batch successfully saved")
    else:
      qt.QMessageBox.information(None, "Calibration batch saving" , "Calibration batch save failed!\n\nPlease see error log for details")

    calibrationBatchMrmlScene.Clear(1)

  #------------------------------------------------------------------------------
  def onLoadCalibrationBatchButton(self):
    calibrationBatchDirectoryPath = qt.QFileDialog.getExistingDirectory(0, 'Open directory containing calibration batch')  
    #TODO put this all in a try/except
    os.chdir(os.path.normpath(calibrationBatchDirectoryPath))
    mrmlFilesFound = 0

    calibrationBatchMrmlSceneFileName = None
    for potentialMrmlFileName in glob.glob("*.mrml"):
      mrmlFilesFound += 1
      calibrationBatchMrmlSceneFileName = potentialMrmlFileName

    if mrmlFilesFound > 1:
      qt.QMessageBox.critical(None, 'Error', "More than one MRML file found in directory!\n\nThe calibration batch directory must contain exactly one MRML file")
      logging.error("More than one MRML files found in directory" + calibrationBatchDirectoryPath)
      return
    elif mrmlFilesFound < 1:
      qt.QMessageBox.critical(None, 'Error', "No MRML file found in directory!\n\nThe calibration batch directory must contain exactly one MRML file")
      logging.error("No MRML file found in directory" + calibrationBatchDirectoryPath)
      return

    calibrationBatchMrmlSceneFilePath = os.path.normpath(calibrationBatchDirectoryPath + "/" + calibrationBatchMrmlSceneFileName)
    success = slicer.util.loadScene(calibrationBatchMrmlSceneFilePath)

    # TODO: Indentify flood field image by this attribute value (for attribute self.calibrationVolumeDoseAttributeName): self.floodFieldAttributeValue
    
    # TODO: set a calibration volume to be visible so an ROI can be clicked from the slicelet 

  #------------------------------------------------------------------------------
  def onAddRoiButton(self):
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    interactionNode = appLogic.GetInteractionNode()

    # Switch to ROI place mode
    selectionNode.SetReferenceActivePlaceNodeClassName('vtkMRMLAnnotationROINode')
    interactionNode.SwitchToSinglePlaceMode()

  #------------------------------------------------------------------------------
  def onPerformCalibrationButton(self):
    if not hasattr(slicer.modules, 'cropvolume'):
      message = "Crop Volume module missing!"
      qt.QMessageBox.critical(None, 'Error', message)
      logging.error(message)    
    if self.lastAddedRoiNode is None:
      message = 'No ROI created for calibration!'
      qt.QMessageBox.critical(None, 'Error', message)
      logging.error(message)
      return

    # Get flood field image node
    floodFieldCalibrationVolumeNode = self.step1_floodFieldImageSelectorComboBox.currentNode()

    if floodFieldCalibrationVolumeNode is None:
      message = "Flood field image is not selected"
      qt.QMessageBox.critical(None, 'Error', message)
      logging.error(message)
      return

    # Show wait cursor while processing
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    cropVolumeLogic = slicer.modules.cropvolume.logic()
    cloner = slicer.qSlicerSubjectHierarchyCloneNodePlugin()

    # Crop flood field volume by defined ROI into a cloned volume node
    floodFieldShNode = slicer.vtkMRMLSubjectHierarchyNode.GetAssociatedSubjectHierarchyNode(floodFieldCalibrationVolumeNode)
    floodFieldVolumeNodeNodeCloneName = floodFieldCalibrationVolumeNode.GetName() + '_Cropped'
    croppedFloodFieldVolumeShNode = cloner.cloneSubjectHierarchyNode(floodFieldShNode, floodFieldVolumeNodeNodeCloneName)    
    cropVolumeLogic.CropVoxelBased(self.lastAddedRoiNode, floodFieldCalibrationVolumeNode, croppedFloodFieldVolumeShNode.GetAssociatedNode())

    imageStat = vtk.vtkImageAccumulate()
    imageStat.SetInputData(floodFieldCalibrationVolumeNode.GetImageData())
    imageStat.Update()
    meanValueFloodField = imageStat.GetMean()[0]
    logging.info("Mean value for flood field image in ROI = " + str(meanValueFloodField))
    
    calibrationValues = [] # [entered dose, measured pixel value]   #TODO: Order is just reversed compared to measuredOpticalDensityToDoseMap
    calibrationValues.append([self.floodFieldAttributeValue, meanValueFloodField])

    self.measuredOpticalDensityToDoseMap = []

    #TODO check this OD calculation

    for currentCalibrationVolumeIndex in xrange(self.step1_numberOfCalibrationFilmsSpinBox.value):
      # Get current calibration image node
      currentCalibrationVolumeNode = self.step1_calibrationVolumeSelectorComboBoxList[currentCalibrationVolumeIndex].currentNode()
      currentCalibrationDose = self.step1_calibrationVolumeSelectorCGySpinBoxList[currentCalibrationVolumeIndex].value

      # Crop calibration images by last defined ROI into a cloned volume node
      calibrationShNode = slicer.vtkMRMLSubjectHierarchyNode.GetAssociatedSubjectHierarchyNode(floodFieldCalibrationVolumeNode)
      calibrationVolumeNodeNodeCloneName = currentCalibrationVolumeNode.GetName() + '_Cropped'
      croppedCalibrationVolumeShNode = cloner.cloneSubjectHierarchyNode(calibrationShNode, calibrationVolumeNodeNodeCloneName)    
      cropVolumeLogic.CropVoxelBased(self.lastAddedRoiNode, currentCalibrationVolumeNode, croppedCalibrationVolumeShNode.GetAssociatedNode())

      # Measure dose value as average of the cropped calibration images
      #calibrationValues[imageDose_cGy] = measuredValueInRoi #TODO:
      imageStat = vtk.vtkImageAccumulate()
      imageStat.SetInputData(currentCalibrationVolumeNode.GetImageData())
      imageStat.Update()
      meanValue = imageStat.GetMean()[0]
      calibrationValues.append([meanValue, currentCalibrationDose])

      # Optical density calculation
      opticalDensity = math.log10(float(meanValueFloodField)/meanValue) 
      if opticalDensity < 0.0:
        opticalDensity = 0.0

      # x = optical density, y = dose
      self.measuredOpticalDensityToDoseMap.append([opticalDensity, currentCalibrationDose])
      logging.info("Mean value for calibration image for " + str(currentCalibrationDose) + " cGy in ROI = " + str(meanValue))

    self.measuredOpticalDensityToDoseMap.sort(key=lambda doseODPair: doseODPair[1])

    # Perform calibration of OD to dose
    self.findBestFittingCalibrationFunctionCoefficients()

    # Restore cursor
    qt.QApplication.restoreOverrideCursor()

    # Show calibration plot
    self.createCalibrationCurvesWindow()
    self.showCalibrationCurves()

    # Calibration entry line edits
    aText = str(round(self.calibrationCoefficients[0],5))
    bText = str(round(self.calibrationCoefficients[1],5))
    cText = str(round(self.calibrationCoefficients[2],5))
    nText = str(round(self.calibrationCoefficients[3],5))
    self.step3_calibrationFunctionOrder0LineEdit.text = aText
    self.step3_calibrationFunctionOrder1LineEdit.text = bText
    self.step3_calibrationFunctionOrder2LineEdit.text = cText
    self.step3_calibrationFunctionExponentLineEdit.text = nText

    # Calibration function label
    self.step1_2_performCalibrationFunctionLabel.text = "Dose (cGy) = " + aText + " + " + bText + " * OD + " + cText + " * OD^" + nText

  #------------------------------------------------------------------------------
  def cropDoseByROI(self): 
    doseVolume = self.step2_doseVolumeSelector.currentNode()
    if doseVolume is None:
      logging.error()

    roiNode = slicer.vtkMRMLAnnotationROINode()
    roiNode.SetName(self.cropDoseByROIName)
    slicer.mrmlScene.AddNode(roiNode)
    doseVolumeBounds = [0]*6
    doseVolume.GetRASBounds(doseVolumeBounds)  
    roiBounds = [0]*6
    doseVolumeCenter = [(doseVolumeBounds[0]+doseVolumeBounds[1])/2, (doseVolumeBounds[2]+doseVolumeBounds[3])/2, (doseVolumeBounds[4]+doseVolumeBounds[5])/2]
    #print "center of the ROI - doseVolumeCenter: ", doseVolumeCenter 
    newRadiusROI = [abs(doseVolumeBounds[1]-doseVolumeBounds[0])/2, 0.5*doseVolume.GetSpacing()[1], abs(doseVolumeBounds[5]-doseVolumeBounds[4])/2]
    #print "newRadiusROI : ", newRadiusROI
    
    roiNode.SetXYZ(doseVolumeCenter)
    roiNode.SetRadiusXYZ(newRadiusROI)
    # TODO why does the cropVolume radius not match ROI radius??
    cropParams = slicer.vtkMRMLCropVolumeParametersNode()
    cropParams.SetInputVolumeNodeID(doseVolume.GetID())
    cropParams.SetROINodeID(roiNode.GetID())
    cropParams.SetVoxelBased(False) 
    cropLogic = slicer.modules.cropvolume.logic()
    cropLogic.Apply(cropParams)
    croppedNode = slicer.mrmlScene.GetNodeByID( cropParams.GetOutputVolumeNodeID() )
    self.inputDICOMDoseVolume = croppedNode
    return croppedNode

  #------------------------------------------------------------------------------
  def onCalibrationFunctionLineEditChanged(self):
    if self.step3_calibrationFunctionOrder0LineEdit.text != '':
      try:
        self.calibrationCoefficients[0] = float(self.step3_calibrationFunctionOrder0LineEdit.text)
      except ValueError:
        logging.error("Invalid numeric value for calibration function coefficient 'A' " + self.step3_calibrationFunctionOrder0LineEdit.text)
    if self.step3_calibrationFunctionOrder1LineEdit.text != '':
      try:
        self.calibrationCoefficients[1] = float(self.step3_calibrationFunctionOrder1LineEdit.text)
      except ValueError:
        logging.error("Invalid numeric value for calibration function coefficient 'B' " + self.step3_calibrationFunctionOrder1LineEdit.text)
    if self.step3_calibrationFunctionOrder2LineEdit.text != '':
      try:
        self.calibrationCoefficients[2] = float(self.step3_calibrationFunctionOrder2LineEdit.text)
      except ValueError:
        logging.error("Invalid numeric value for calibration function coefficient 'C' " + self.step3_calibrationFunctionOrder2LineEdit.text)
    if self.step3_calibrationFunctionExponentLineEdit.text != '':
      try:
        self.calibrationCoefficients[3] = float(self.step3_calibrationFunctionExponentLineEdit.text)
      except ValueError:
        logging.error("Invalid numeric value for calibration function coefficient 'N' " + self.step3_calibrationFunctionExponentLineEdit.text)

  #------------------------------------------------------------------------------
  def fitOpticalDensityFunction(self, doseVSOpticalDensityNestedList):
    print "fitOpticalDensityFunction"
    x = [ODEntry[0] for ODEntry in doseVSOpticalDensityNestedList]
    y = [ODEntry[1] for ODEntry in doseVSOpticalDensityNestedList]
    self.opticalDensityCurve = numpy.polyfit(x,y,3)
    opticalDensityToDosePolynomialFunction = numpy.poly1d(self.opticalDensityCurve)
    return opticalDensityToDosePolynomialFunction

  #------------------------------------------------------------------------------
  @vtk.calldata_type(vtk.VTK_OBJECT)
  def onNodeAdded(self, caller, event, calldata):
    addedNode = calldata

    # If importing a scene then save the calibration batch that needs to be parsed
    if slicer.mrmlScene.IsImporting() and addedNode.IsA("vtkMRMLSubjectHierarchyNode"):
      nodeLevel = addedNode.GetLevel()
      if nodeLevel == slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelFolder():
        self.batchFolderToParse = addedNode

    # When an ROI is added then save it as the ROI to use for calibration
    if addedNode.IsA('vtkMRMLAnnotationROINode'):
      self.lastAddedRoiNode = addedNode

    # Set auto window/level for loaded dose volumes
    import vtkSlicerRtCommonPython as vtkSlicerRtCommon
    if vtkSlicerRtCommon.SlicerRtCommon.IsDoseVolumeNode(addedNode):
      print('ZZZ dose added ' + addedNode.GetName()) #TODO:
      if addedNode.GetDisplayNode() is not None:
        addedNode.GetDisplayNode().AutoWindowLevelOn()
        print('ZZZ display OK')

  #------------------------------------------------------------------------------
  def onSceneEndImport(self, caller, event): #TODO: Rely on attributes and not node names (which are duplicate!) + variable names etc.
    if self.batchFolderToParse is None:
      message = "Invalid saved directory, no subject hierarchy folder is selected to parse!"
      qt.QMessageBox.critical(None, 'Error', message)
      logging.error(message)
      return

    childrenToParse = vtk.vtkCollection()
    self.batchFolderToParse.GetAssociatedChildrenNodes(childrenToParse)

    calibrationVolumeNumber = childrenToParse.GetNumberOfItems() - 1
    self.updateStep1CalibrationPanel(calibrationVolumeNumber)
    self.step1_numberOfCalibrationFilmsSpinBox.value = calibrationVolumeNumber

    loadedFloodFieldScalarVolume = None

    sHNodeCollection = slicer.mrmlScene.GetNodesByClass('vtkMRMLSubjectHierarchyNode')
    sHNodeCollection.InitTraversal()
    currentNode = sHNodeCollection.GetNextItemAsObject()
    calibrationVolumeIndex = 0

    floodFieldSHFound = False
    CalibrationFilmsSHFound = False
    fileNotFoundError = False
    lastLoadedCalibrationVolume = None

    while currentNode != None:
      if currentNode.GetAncestorAtLevel('Folder') == self.batchFolderToParse:
        if currentNode.GetAttribute(self.calibrationVolumeDoseAttributeName) == self.floodFieldAttributeValue :
          floodFieldSHFound = True
          if os.path.isfile(currentNode.GetAssociatedNode().GetStorageNode().GetFileName()) == True:
            if loadedFloodFieldScalarVolume is None:
              loadedFloodFieldScalarVolume = slicer.mrmlScene.GetNodeByID(currentNode.GetAssociatedNodeID())
              self.step1_floodFieldImageSelectorComboBox.setCurrentNode(loadedFloodFieldScalarVolume)
            else:
              message = "More than one flood field image found"
              qt.QMessageBox.critical(None, 'Error', message)
              logging.error(message)
              slicer.mrmlScene.Clear(0)
              return
          else:
            fileNotFoundError = True
            logging.error("No flood field image in directory")

        if self.calibrationVolumeName in currentNode.GetName():
          CalibrationFilmsSHFound = True

          if os.path.isfile(currentNode.GetAssociatedNode().GetStorageNode().GetFileName()) == True:
            # Setting scalar volume to combobox
            loadedCalibrationVolume = slicer.mrmlScene.GetNodeByID(currentNode.GetAssociatedNodeID())
            lastLoadedCalibrationVolume = loadedCalibrationVolume
            self.step1_calibrationVolumeSelectorComboBoxList[calibrationVolumeIndex].setCurrentNode(loadedCalibrationVolume)

            # Setting dose attribute to combobox
            dose = int(currentNode.GetAttribute(self.calibrationVolumeDoseAttributeName))
            self.step1_calibrationVolumeSelectorCGySpinBoxList[calibrationVolumeIndex].value = dose
          else:
            fileNotFoundError = True
            logging.error("No calibration image in directory")

          calibrationVolumeIndex +=1
      currentNode = sHNodeCollection.GetNextItemAsObject()

    self.folderNode = self.batchFolderToParse
    self.batchFolderToParse = None

    result = CalibrationFilmsSHFound and floodFieldSHFound and (not fileNotFoundError)

    # TODO fix placement of popup boxes on screen relative to load slider thing

    # Error messages for issues with loading
    if not result:
      message = "Failed to load saved calibration batch"
      qt.QMessageBox.critical(None, 'Error', message)
      logging.error(message)
      return
    if fileNotFoundError:
      qt.QMessageBox.critical(None, 'Error', "File not found for flood file image or calibration image(s)")
      slicer.mrmlScene.Clear(0)
      return
    if floodFieldSHFound == False:
      qt.QMessageBox.warning(None, 'Warning', 'No flood field image.')
    if CalibrationFilmsSHFound == False:
      qt.QMessageBox.warning(None, 'Warning', 'No calibration film images.')

    # Show last loaded film
    if lastLoadedCalibrationVolume is not None:
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      selectionNode.SetActiveVolumeID(lastLoadedCalibrationVolume.GetID())
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()

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
    calibrationNumberOfRows = len(self.measuredOpticalDensityToDoseMap)

    opticalDensityArray = vtk.vtkDoubleArray()
    opticalDensityArray.SetName("Optical Density")
    self.calibrationCurveDataTable.AddColumn(opticalDensityArray)
    dose_cGyCalibrationCurveArray = vtk.vtkDoubleArray()
    dose_cGyCalibrationCurveArray.SetName("Dose (cGy)")
    self.calibrationCurveDataTable.AddColumn(dose_cGyCalibrationCurveArray)
    self.calibrationCurveDataTable.SetNumberOfRows(calibrationNumberOfRows)

    for rowIndex in xrange(calibrationNumberOfRows):
      self.calibrationCurveDataTable.SetValue(rowIndex, 0, self.measuredOpticalDensityToDoseMap[rowIndex][0])
      self.calibrationCurveDataTable.SetValue(rowIndex, 1, self.measuredOpticalDensityToDoseMap[rowIndex][1])

    if hasattr(self, 'calibrationMeanOpticalAttenuationLine' ):
      self.calibrationCurveChart.RemovePlotInstance(self.calibrationMeanOpticalAttenuationLine)
    self.calibrationMeanOpticalAttenuationLine = self.calibrationCurveChart.AddPlot(vtk.vtkChart.POINTS)
    self.calibrationMeanOpticalAttenuationLine.SetInputData(self.calibrationCurveDataTable, 0, 1)
    self.calibrationMeanOpticalAttenuationLine.SetColor(0, 0, 255, 255)
    self.calibrationMeanOpticalAttenuationLine.SetWidth(2.0)

    # Create and populate the calculated dose/OD curve with function
    opticalDensityList = [round(0 + 0.01*opticalDensityIncrement,2) for opticalDensityIncrement in xrange(120)] #TODO: Magic number 120?
    opticalDensities = []

    for calculatedEntryIndex in xrange(120):
      newEntry = [opticalDensityList[calculatedEntryIndex], self.applyCalibrationFunction(opticalDensityList[calculatedEntryIndex], self.calibrationCoefficients[0], self.calibrationCoefficients[1], self.calibrationCoefficients[2], self.calibrationCoefficients[3])]
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
    for opticalDensityIncrement in xrange(opticalDensityNumberOfRows):
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
    self.renderWindow = self.calibrationCurveChartView.GetRenderWindow()
    self.renderWindow.SetSize(800,550)
    self.renderWindow.SetWindowName('Dose (cGy) vs. Optical Density')
    self.renderWindow.Start()

  #------------------------------------------------------------------------------
  def meanSquaredError(self, a, b, c, n):
    sumMeanSquaredError = 0.0
    for i in xrange(len(self.measuredOpticalDensityToDoseMap)):
      calculatedDose = self.applyCalibrationFunction(self.measuredOpticalDensityToDoseMap[i][0], a, b, c, n)
      sumMeanSquaredError += ((self.measuredOpticalDensityToDoseMap[i][1] - calculatedDose)**2)
    return sumMeanSquaredError / float(len(self.measuredOpticalDensityToDoseMap))

  #------------------------------------------------------------------------------
  def applyCalibrationFunction(self, OD, a, b, c, n):
    return a + b*OD + c*(OD**n)

  #------------------------------------------------------------------------------
  def findCoefficientsForExponent(self,n):
    # Calculate matrix A
    functionTermsMatrix = []

    # Optical density
    for row in xrange(len(self.measuredOpticalDensityToDoseMap)):
      opticalDensity = self.measuredOpticalDensityToDoseMap[row][0]
      functionTermsMatrix.append([1,opticalDensity,opticalDensity**n])
    functionTermsMatrix = numpy.asmatrix(functionTermsMatrix)

    # Calculate constant term coefficient vector
    functionDoseTerms = []
    for row in xrange(len(self.measuredOpticalDensityToDoseMap)):
      functionDoseTerms += [self.measuredOpticalDensityToDoseMap[row][1]]
    functionConstantTerms = numpy.linalg.lstsq(functionTermsMatrix,functionDoseTerms)
    coefficients = functionConstantTerms[0].tolist()

    for coefficientIndex in xrange(len(coefficients)):
      coefficients[coefficientIndex] = coefficients[coefficientIndex]

    return coefficients

  #------------------------------------------------------------------------------
  def findBestFittingCalibrationFunctionCoefficients(self):
    bestN = [] # Entries are [MSE, n, coefficients]

    for n in xrange(1000,4001):
      n/=1000.0
      coeffs = self.findCoefficientsForExponent(n)
      MSE = self.meanSquaredError(coeffs[0],coeffs[1],coeffs[2],n)
      bestN.append([MSE, n, coeffs])

    bestN.sort(key=lambda bestNEntry: bestNEntry[0]) 
    self.calibrationCoefficients = [ bestN[0][2][0], bestN[0][2][1], bestN[0][2][2], bestN[0][1] ]
    logging.info("Best fitting calibration function coefficients: A,B,C=" + str(bestN[0][2]) + ", N=" + str(bestN[0][1]) + " (mean square error: "  + str(bestN[0][0]))

  #------------------------------------------------------------------------------
  def exportCalibrationResultToFile(self):
    outputDir = qt.QFileDialog.getExistingDirectory(0, 'Select directory for saving calibration results')
    if not os.access(outputDir, os.F_OK):
      os.mkdir(outputDir)

    # Assemble file name for calibration curve points file
    from time import gmtime, strftime
    fileName = outputDir + '/' + strftime("%Y%m%d_%H%M%S_", gmtime()) + self.calibrationFunctionFileName + ".txt"

    file = open(fileName, 'w')
    file.write('# Film dosimetry calibration function coefficients (' + strftime("%Y.%m.%d. %H:%M:%S", gmtime()) + ')')
    file.write('# Coefficients in order: A, B, C, N')
    for coefficient in self.calibrationCoefficients:
      file.write(str(coefficient) + '\n')
    file.close()

  #------------------------------------------------------------------------------
  def onLoadCalibrationFunctionButton(self):
    savedFilePath = qt.QFileDialog.getOpenFileName(0, 'Open file')

    file = open(savedFilePath, 'r+')
    lines = file.readlines()
    if len(lines) != 6:
      message = "Invalid calibration coefficients file!"
      logging.error(message)
      qt.QMessageBox.critical(None, 'Error', message)
      return

    self.calibrationCoefficients[0] = float(lines[2].rstrip())
    self.step3_calibrationFunctionOrder0LineEdit.text = lines[2].rstrip()
    self.calibrationCoefficients[1] = float(lines[3].rstrip())
    self.step3_calibrationFunctionOrder1LineEdit.text = lines[3].rstrip()
    self.calibrationCoefficients[2] = float(lines[4].rstrip())
    self.step3_calibrationFunctionOrder2LineEdit.text = lines[4].rstrip()
    self.calibrationCoefficients[3] = float(lines[5].rstrip())
    self.step3_calibrationFunctionExponentLineEdit.text = lines[5].rstrip()

    file.close()

  #------------------------------------------------------------------------------
  def volumeToNumpyArray(self, currentVolume):
    volumeData = currentVolume.GetImageData()
    volumeDataScalars = volumeData.GetPointData().GetScalars()
    numpyArrayVolume = numpy_support.vtk_to_numpy(volumeDataScalars)
    return numpyArrayVolume
    
  #------------------------------------------------------------------------------
  def calculateDoseFromExperimentalFilmImage(self):
    #TODO: This should be done in SimpleITK

    experimentalFilmArray = self.volumeToNumpyArray(self.step2_experimentalFilmSelectorComboBox.currentNode())  
    floodFieldArray = self.volumeToNumpyArray(self.step2_floodFieldImageSelectorComboBox.currentNode())

    if len(experimentalFilmArray) != len(floodFieldArray):
      message = "Experimental and flood field images must be the same size! (Experimental: " + str(len(experimentalFilmArray)) + ", FloodField: " + str(len(floodFieldArray))
      logging.error(message)
      qt.QMessageBox.critical(None, 'Error', message)
      return 

    doseArrayGy = numpy.zeros(len(floodFieldArray))
    for rowIndex in xrange(len(experimentalFilmArray)):
      opticalDensity = 0.0
      try:
        opticalDensity = math.log10(float(floodFieldArray[rowIndex])/experimentalFilmArray[rowIndex])
      except:
        logging.error('Failure when calculating optical density for experimental film image. Failing values: FloodField=' + str(floodFieldArray[rowIndex]) + ', PixelValue=' + str(experimentalFilmArray[rowIndex]))
        opticalDensity = 0.0
      if opticalDensity <= 0.0:
        opticalDensity = 0.0
      doseArrayGy[rowIndex] = self.applyCalibrationFunction(opticalDensity, self.calibrationCoefficients[0], self.calibrationCoefficients[1], self.calibrationCoefficients[2], self.calibrationCoefficients[3]) / 100.0

      if doseArrayGy[rowIndex] < 0.0:
        doseArrayGy[rowIndex] = 0.0

    return doseArrayGy

  #------------------------------------------------------------------------------
  def onApplyCalibrationButton(self):
    if self.calibrationCoefficients is None or len(self.calibrationCoefficients) != 4:
      message = "Invalid calibration function"
      qt.QMessageBox.critical(None, 'Error', message)
      logging.error(message)
      return 

    experimentalFilmVolumeNode = self.step2_experimentalFilmSelectorComboBox.currentNode()
    if experimentalFilmVolumeNode is None:
      logging.error("Invalid experimental film selection!")
      return

    # Perform calibration
    calculatedDoseDoubleArrayGy = self.calculateDoseFromExperimentalFilmImage()

    # Expand the calibrated image to 5 slices (for registration)
    calculatedDoseVolumeArrayGy = numpy.tile(calculatedDoseDoubleArrayGy,5)

    # Convert numpy array to VTK image data
    calculatedDoseVolumeScalarsGy = numpy_support.numpy_to_vtk(calculatedDoseVolumeArrayGy)
    calculatedDoseVolumeScalarsGyCopy = vtk.vtkDoubleArray()
    calculatedDoseVolumeScalarsGyCopy.DeepCopy(calculatedDoseVolumeScalarsGy)
    calculatedDoseImageData = vtk.vtkImageData()
    calculatedDoseImageData.GetPointData().SetScalars(calculatedDoseVolumeScalarsGyCopy)
    calculatedDoseImageData.SetDimensions(experimentalFilmVolumeNode.GetImageData().GetDimensions()[0:2] + (5,)) #TODO: doesn't look too stable

    # Create scalar volume node for calibrated film
    calculatedDoseVolume = slicer.vtkMRMLScalarVolumeNode()
    calculatedDoseVolume.SetAndObserveImageData(calculatedDoseImageData)
    calculatedDoseVolume.SetName(experimentalFilmVolumeNode.GetName() + self.experimentalFilmDoseVolumeNamePostfix)
    slicer.mrmlScene.AddNode(calculatedDoseVolume)
    calculatedDoseVolume.CreateDefaultDisplayNodes()
    self.experimentalFilmDoseVolume = calculatedDoseVolume

    qt.QMessageBox.information(None, "Calibration" , "Calibration successfully finished!")
    
  #------------------------------------------------------------------------------
  def onResolutionLineEditTextChanged(self):
    self.resolutionMM_ToPixel = float(self.step4_resolutionLineEdit.text)
        
  #------------------------------------------------------------------------------
  def onPerformRegistrationButtonClicked(self):
    # TODO merge step 3 and step 4
    print "onPerformRegistrationButtonClicked"
    
    if self.resolutionMM_ToPixel is None:
      message = "A mm/pixel resolution for the experimental film must be entered"
      qt.QMessageBox.critical(None, 'Error', message)
      logging.error(message)
      return

    # Set auto window/level for dose volume
    self.step2_doseVolumeSelector.currentNode().GetDisplayNode().AutoWindowLevelOn() #TODO
            
    # Set spacing of the experimental film volume
    if self.experimentalFilmDoseVolume is None:
      qt.QMessageBox.critical(None, 'Error', "Step 3 must be performed before Step 4")
      return
    self.experimentalFilmDoseVolume.SetSpacing(self.resolutionMM_ToPixel, self.resolutionMM_ToPixel, self.inputDICOMDoseVolume.GetSpacing()[1])
    
    # Crop the dose volume by the ROI
    croppedDoseVolumeNode = self.cropDoseByROI()
    
    # TODO just in case I need the resampling code,
    # # Resample cropped dose volume 
    # self.dosePlanVolume = slicer.vtkMRMLScalarVolumeNode()
    # self.dosePlanVolume.SetName(self.dosePlanVolumeName)
    # slicer.mrmlScene.AddNode(self.dosePlanVolume)
    # resampleParameters = {'outputPixelSpacing':'2,0.4,2', 'interpolationType':'linear', 'InputVolume':self.inputDICOMDoseVolume.GetID(), 'OutputVolume':self.dosePlanVolume.GetID()}
    # slicer.cli.run(slicer.modules.resamplescalarvolume, None, resampleParameters, wait_for_completion=True)
    # self.dosePlanVolume.SetSpacing(2,2,2)
 
    doseArray = self.volumeToNumpyArray(croppedDoseVolumeNode)
    doseArrayList = []
    #doseArray = doseArray.reshape(151,106)
    doseArray = doseArray.reshape(croppedDoseVolumeNode.GetImageData().GetExtent()[5]+1, croppedDoseVolumeNode.GetImageData().GetExtent()[1]+1)
    for x in xrange(len(doseArray)):
      doseArrayList.append(numpy.tile(doseArray[x],5).tolist())
      
    doseArrayList = numpy.asarray(doseArrayList)
    doseArrayList = numpy.ravel(doseArrayList)
    newScalarVolume = slicer.vtkMRMLScalarVolumeNode()
    new3dScalars = numpy_support.numpy_to_vtk(doseArrayList)
    new3dScalarsCopy = vtk.vtkDoubleArray()
    new3dScalarsCopy.DeepCopy(new3dScalars)
    new3dImageData = vtk.vtkImageData()
    new3dImageData.GetPointData().SetScalars(new3dScalarsCopy)
    newExtent = croppedDoseVolumeNode.GetImageData().GetExtent()
    newExtent = newExtent[0:3] +(4,) + newExtent[4:]
    new3dImageData.SetExtent(newExtent) #TODO replace with SetDimensions
    newScalarVolume.SetAndObserveImageData(new3dImageData)
    newScalarVolume.SetName("Dose volume for registration")
    slicer.mrmlScene.AddNode(newScalarVolume)
    self.dosePlanVolume = newScalarVolume
    newScalarVolume.CopyOrientation(croppedDoseVolumeNode)
        
    # Set up transform pipeline 
    
    experimentalAxialToCoronalRotationTransform = vtk.vtkTransform()
    experimentalAxialToCoronalRotationTransform.RotateWXYZ(90,[1,0,0])
    experimentalAxialToExperimentalCoronalTransformMRML = slicer.vtkMRMLLinearTransformNode()
    experimentalAxialToExperimentalCoronalTransformMRML.SetName(self.experimentalAxialToExperimentalCoronalTransformName)
    slicer.mrmlScene.AddNode(experimentalAxialToExperimentalCoronalTransformMRML)
    experimentalAxialToExperimentalCoronalTransformMRML.SetMatrixTransformToParent(experimentalAxialToCoronalRotationTransform.GetMatrix())
    self.experimentalFilmDoseVolume.SetAndObserveTransformNodeID(experimentalAxialToExperimentalCoronalTransformMRML.GetID())
    
    # Rotate 90 degrees about [0,1,0]

    rotate90APTransform = vtk.vtkTransform()
    rotate90APTransform.RotateWXYZ(-90,[0,1,0])
    # TODO this may be a 90 or -90 rotation, it is unclear what orientation the films should be in 
    rotate90APTransformMRML = slicer.vtkMRMLLinearTransformNode()
    rotate90APTransformMRML.SetMatrixTransformToParent(rotate90APTransform.GetMatrix())
    rotate90APTransformMRML.SetName(self.experimentalRotate90APTransformName)    
    slicer.mrmlScene.AddNode(rotate90APTransformMRML)
    experimentalAxialToExperimentalCoronalTransformMRML.SetAndObserveTransformNodeID(rotate90APTransformMRML.GetID())

    # Translate to center of the dose volume 
    expBounds = [0]*6
    self.experimentalFilmDoseVolume.GetRASBounds(expBounds)
    doseBounds = [0]*6
    self.dosePlanVolume.GetRASBounds(doseBounds)
    doseVolumeCenter = [(doseBounds[0]+doseBounds[1])/2, (doseBounds[2]+doseBounds[3])/2, (doseBounds[4]+doseBounds[5])/2]
    expCenter = [(expBounds[0]+expBounds[1])/2, (expBounds[2]+expBounds[3])/2, (expBounds[4]+expBounds[5])/2]
    exp2DoseTranslation = [doseVolumeCenter[x] - expCenter[x] for x in xrange(len(doseVolumeCenter))]
    
    # TODO test transformation chain on asymmetrical image 
    
    ExperimentalCenterToDoseCenterTransform = vtk.vtkTransform()
    ExperimentalCenterToDoseCenterTransform.Translate(exp2DoseTranslation)
    ExperimentalCenterToDoseCenterTransformMRML = slicer.vtkMRMLLinearTransformNode()
    ExperimentalCenterToDoseCenterTransformMRML.SetName(self.experimentalCenter2DoseCenterTransformName)
    ExperimentalCenterToDoseCenterTransformMRML.SetMatrixTransformToParent(ExperimentalCenterToDoseCenterTransform.GetMatrix())
    slicer.mrmlScene.AddNode(ExperimentalCenterToDoseCenterTransformMRML)
    rotate90APTransformMRML.SetAndObserveTransformNodeID(ExperimentalCenterToDoseCenterTransformMRML.GetID())
    
    slicer.vtkSlicerTransformLogic.hardenTransform(self.experimentalFilmDoseVolume)
    
    # Apply BRAINSFit module 
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
    
    parametersRigid = {}
    parametersRigid["fixedVolume"] = self.dosePlanVolume # current 
    parametersRigid["movingVolume"] = self.experimentalFilmDoseVolume
    parametersRigid["useRigid"] = True
    parametersRigid["samplingPercentage"] = 0.05
    parametersRigid["maximumStepLength"] = 15 # Start with long-range translations
    parametersRigid["relaxationFactor"] = 0.8 # Relax quickly
    parametersRigid["translationScale"] = 1000000 # Suppress rotation
    self.experimentalToDoseTransform = slicer.vtkMRMLLinearTransformNode()
    slicer.mrmlScene.AddNode(self.experimentalToDoseTransform)
    self.experimentalToDoseTransform.SetName(self.experimentalToDoseTransformName)
    parametersRigid["linearTransform"] = self.experimentalToDoseTransform.GetID()

    # Runs the brainsfit registration
    brainsFit = slicer.modules.brainsfit
    cliBrainsFitRigidNode = None
    cliBrainsFitRigidNode = slicer.cli.run(brainsFit, None, parametersRigid)
    
    print "registration : \n"
    self.brainsFit = cliBrainsFitRigidNode # TODO this is just for testing purposes 
    
    waitCount = 0
    while cliBrainsFitRigidNode.GetStatusString() != 'Completed' and waitCount < 200:
      #self.delayDisplay( "Register experimental film to dose using rigid registration... %d" % waitCount )
      # TODO implement the delayDisplay function 
      waitCount += 1
    #self.delayDisplay("Register experimental film to dose using rigid registration finished")
    print cliBrainsFitRigidNode.GetStatusString()
    qt.QApplication.restoreOverrideCursor()
    # TODO have success message pop up
 
  #
  # -------------------------
  # Testing related functions
  # -------------------------
  #
  def onSelfTestButtonClicked(self):
    pass #TODO: Add test

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

# # ---------------------------------------------------------------------------
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
