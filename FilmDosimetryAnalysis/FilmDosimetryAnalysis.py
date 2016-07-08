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
    self.step1_CalibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_inputExperimentalDataCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step3_applyCalibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step4_CollapsibleButton = ctk.ctkCollapsibleButton()
    self.testButton = ctk.ctkCollapsibleButton()

    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.step0_layoutSelectionCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step1_CalibrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step2_inputExperimentalDataCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step3_applyCalibrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step4_CollapsibleButton)
    

    self.collapsibleButtonsGroup.addButton(self.testButton)

    self.step0_layoutSelectionCollapsibleButton.setProperty('collapsed', False)

    # Create module logic
    self.logic = FilmDosimetryAnalysisLogic.FilmDosimetryAnalysisLogic()

    # Declare member variables (selected at certain steps and then from then on for the workflow)
    self.folderNode = None
    self.batchFolderToParse = None
    self.lastAddedRoiNode = None
    self.calculatedDoseNode = None
    self.calibrationValues = []
    self.measuredOpticalDensities = []
    # Set up constants
    self.saveCalibrationBatchFolderNodeName = "Calibration batch"
    self.calibrationVolumeDoseAttributeName = "Dose"
    self.floodFieldAttributeValue = "FloodField"
    self.floodFieldImageShNodeName = "FloodFieldImage"
    self.calibrationVolumeName = "CalibrationVolume"
    self.exportedSceneFileName = slicer.app.temporaryPath + "/exportMrmlScene.mrml"
    self.savedCalibrationVolumeFolderName = "savedCalibrationVolumes"
    self.calibrationFunctionFileName = "doseVSopticalDensity.txt"
    self.savedFolderPath = slicer.app.temporaryPath + "/" + self.savedCalibrationVolumeFolderName
    self.maxCalibrationVolumeSelectorsInt = 10
    self.fileLoadingSuccessMessageHeader = "Calibration image loading"
    self.floodFieldFailureMessage = "Flood field image failed to load"
    self.calibrationVolumeLoadFailureMessage = "calibration volume failed to load"
    self.opticalDensityCurve = None #where polyfit is stored
    self.bestCoefficients = [0,0,[0,0,0]] #the best coefficients from Kevin's function, [n, [a,b,c]]

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
    self.setup_step1_Calibration()
    self.setup_step2_inputExperimentalData()
    self.setup_step3_applyCalibration()
    self.setup_step4_Registration()


    if widgetClass:
      self.widget = widgetClass(self.parent)
    self.parent.show()

  #------------------------------------------------------------------------------
  # Disconnect all connections made to the slicelet to enable the garbage collector to destruct the slicelet object on quit
  def disconnect(self):
    self.step0_viewSelectorComboBox.disconnect('activated(int)', self.onViewSelect)
    self.step1_loadImageFilesButton.disconnect('clicked()', self.onLoadImageFilesButton)
    self.step1_numberOfCalibrationFilmsSpinBox.disconnect('valueChanged()', self.onNumberOfCalibrationFilmsSpinBoxValueChanged)
    self.step1_saveCalibrationBatchButton.disconnect('clicked()', self.onSaveCalibrationBatchButton)
    self.step1_loadCalibrationBatchButton.disconnect('clicked()', self.onloadCalibrationBatchButton)
    self.step3_calibrationFunctionOrder0LineEdit.disconnect('textChanged()', self.onTextChanged)
    self.step3_calibrationFunctionOrder1LineEdit.disconnect('textChanged()', self.onTextChanged)
    self.step3_calibrationFunctionOrder2LineEdit.disconnect('textChanged()', self.onTextChanged)
    self.step3_calibrationFunctionOrder3LineEdit.disconnect('textChanged()', self.onTextChanged)
    self.step2_loadNonDicomDataButton.disconnect('clicked()', self.onLoadImageFilesButton)
    self.step2_showDicomBrowserButton.disconnect('clicked()', self.onDicomLoad)
    self.step3_applyCalibrationButton.disconnect('clicked()', self.onApplyCalibrationButton)
    self.step3_loadCalibrationButton.disconnect('clicked()', self.onLoadCalibrationFunctionButton)
    

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
  def setup_step1_Calibration(self):
    # Step 1: Load data panel
    self.step1_CalibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_CalibrationCollapsibleButton.text = "1. Calibration"
    self.sliceletPanelLayout.addWidget(self.step1_CalibrationCollapsibleButton)

    # Step 1 main background layout
    self.step1_calibrationLayout = qt.QVBoxLayout(self.step1_CalibrationCollapsibleButton)


    # Step 1.1: Calibration routine (optional)
    self.step1_1_calibrationRoutineCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_1_calibrationRoutineCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_1_calibrationRoutineCollapsibleButton.text = "1.1. Load calibration data (optional)"
    self.step1_calibrationLayout.addWidget(self.step1_1_calibrationRoutineCollapsibleButton)
    self.step1_1_calibrationRoutineLayout = qt.QVBoxLayout(self.step1_1_calibrationRoutineCollapsibleButton)
    self.step1_1_calibrationRoutineLayout.setContentsMargins(12,4,4,4)
    self.step1_1_calibrationRoutineLayout.setSpacing(4)



    # Step 1 top third sub-layout
    self.step1_topCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_1_calibrationRoutineLayout.addLayout(self.step1_topCalibrationSubLayout)

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
    self.step1_1_calibrationRoutineLayout.addLayout(self.step1_middleCalibrationSubLayout)

    self.step1_calibrationVolumeLayoutList = []
    self.step1_calibrationVolumeSelectorLabelBeforeList = []
    self.step1_calibrationVolumeSelector_cGySpinBoxList = []
    self.step1_calibrationVolumeSelector_cGyLabelList = []
    self.step1_calibrationVolumeSelectorComboBoxList = []

    for doseToImageLayoutNumber in xrange(self.maxCalibrationVolumeSelectorsInt):
      self.step1_doseToImageSelectorRowLayout = qt.QHBoxLayout()
      self.step1_mainCalibrationVolumeSelectorLabelBefore = qt.QLabel('Calibration ')
      self.step1_calibrationVolumeSelectorLabelBeforeList.append(self.step1_mainCalibrationVolumeSelectorLabelBefore)

      self.doseToImageSelector_cGySpinBox = qt.QSpinBox()
      self.doseToImageSelector_cGySpinBox.minimum = 0
      self.doseToImageSelector_cGySpinBox.maximum = 10000
      self.step1_calibrationVolumeSelector_cGySpinBoxList.append(self.doseToImageSelector_cGySpinBox)

      self.doseToImageSelectorLabelMiddle = qt.QLabel(' cGy : ')
      self.step1_calibrationVolumeSelector_cGyLabelList.append(self.doseToImageSelectorLabelMiddle)

      self.doseToImageFilmSelector = slicer.qMRMLNodeComboBox()
      self.doseToImageFilmSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
      self.doseToImageFilmSelector.addEnabled = False
      self.doseToImageFilmSelector.removeEnabled = False
      self.doseToImageFilmSelector.setMRMLScene( slicer.mrmlScene )
      self.doseToImageFilmSelector.setToolTip( "Choose the film image corresponding to the dose above" )
      self.step1_calibrationVolumeSelectorComboBoxList.append(self.doseToImageFilmSelector)

      self.step1_doseToImageSelectorRowLayout.addWidget(self.step1_mainCalibrationVolumeSelectorLabelBefore)
      self.step1_doseToImageSelectorRowLayout.addWidget(self.doseToImageSelector_cGySpinBox)
      self.step1_doseToImageSelectorRowLayout.addWidget(self.doseToImageSelectorLabelMiddle)
      self.step1_doseToImageSelectorRowLayout.addWidget(self.doseToImageFilmSelector)

      self.step1_calibrationVolumeLayoutList.append(self.step1_doseToImageSelectorRowLayout)
      self.step1_middleCalibrationSubLayout.addLayout(self.step1_doseToImageSelectorRowLayout)

    self.step1_bottomCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_1_calibrationRoutineLayout.addLayout(self.step1_bottomCalibrationSubLayout)

    self.fillStep1CalibrationPanel(self.step1_numberOfCalibrationFilmsSpinBox.value)

    # Save batch button
    self.step1_saveCalibrationBatchButton = qt.QPushButton("Save calibration batch")
    self.step1_saveCalibrationBatchButton.toolTip = "Saves current calibration batch"
    self.step1_bottomCalibrationSubLayout.addWidget(self.step1_saveCalibrationBatchButton)

    # Add empty row
    self.step1_bottomCalibrationSubLayout.addWidget(qt.QLabel(''))




   # Step 1.2: Calibration routine (optional)
    self.step1_2_calibrationRoutineCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_2_calibrationRoutineCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_2_calibrationRoutineCollapsibleButton.text = "1.2. Perform Calibration"
    self.step1_calibrationLayout.addWidget(self.step1_2_calibrationRoutineCollapsibleButton)
    self.step1_2_calibrationRoutineLayout = qt.QVBoxLayout(self.step1_2_calibrationRoutineCollapsibleButton)
    self.step1_2_calibrationRoutineLayout.setContentsMargins(12,4,4,4)
    self.step1_2_calibrationRoutineLayout.setSpacing(4)

    # Add ROI button
    self.step1_addRoiButton = qt.QPushButton("Add region")
    self.step1_addRoiButton.setIcon(qt.QIcon(":/Icons/AnnotationROIWithArrow.png"))
    self.step1_addRoiButton.toolTip = "Add ROI (region of interest) that is considered when measuring dose in the calibration images\n\nOnce activated, click in the center of the region to be used for calibration, then do another click to one of the corners. After that the ROI appears and can be adjusted using the colored handles."
    self.step1_2_calibrationRoutineLayout.addWidget(self.step1_addRoiButton)

    # Calibration button
    self.step1_performCalibrationButton = qt.QPushButton("Perform calibration")
    self.step1_performCalibrationButton.toolTip = "Finds the calibration function"
    self.step1_2_calibrationRoutineLayout.addWidget(self.step1_performCalibrationButton)

    # Calibration function
    self.step1_calibrationFunctionLabel = qt.QLabel('Optical density to dose calibration function: ')
    self.step1_2_calibrationRoutineLayout.addWidget(self.step1_calibrationFunctionLabel)
    
    self.blankLabel = qt.QLabel('')
    self.step1_2_calibrationRoutineLayout.addWidget(self.blankLabel)
    #dose calibration function label 
    self.step1_2_performCalibrationFunctionLabel = qt.QLabel(" ")
    self.step1_2_calibrationRoutineLayout.addWidget(self.step1_2_performCalibrationFunctionLabel)

    
    self.step1_2_calibrationRoutineLayout.addWidget(self.blankLabel)

    # Save calibration function button
    self.step1_saveCalibrationButton = qt.QPushButton("Save calibration function")
    self.step1_saveCalibrationButton.toolTip = "Save calibration function for later use"
    self.step1_2_calibrationRoutineLayout.addWidget(self.step1_saveCalibrationButton)



    self.step1_bottomCalibrationSubLayout.addStretch(1)

    # Step 1 sub button group
    self.step1_calibrationCollapsibleButtonGroup = qt.QButtonGroup()
    self.step1_calibrationCollapsibleButtonGroup.addButton(self.step1_1_calibrationRoutineCollapsibleButton)
    self.step1_calibrationCollapsibleButtonGroup.addButton(self.step1_2_calibrationRoutineCollapsibleButton)

    # Connections
    self.step1_loadImageFilesButton.connect('clicked()', self.onLoadImageFilesButton)
    self.step1_saveCalibrationBatchButton.connect('clicked()', self.onSaveCalibrationBatchButton)
    self.step1_loadCalibrationBatchButton.connect('clicked()', self.onloadCalibrationBatchButton)
    self.step1_numberOfCalibrationFilmsSpinBox.connect('valueChanged(int)', self.onNumberOfCalibrationFilmsSpinBoxValueChanged)
    self.step1_addRoiButton.connect('clicked()', self.onAddRoiButton)
    self.step1_performCalibrationButton.connect('clicked()', self.onPerformCalibrationButton)


  #------------------------------------------------------------------------------
  def setup_step2_inputExperimentalData(self):
  # Step 2: Load data panel
    self.step2_inputExperimentalDataCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_inputExperimentalDataCollapsibleButton.text = "2. Input experimental film data"
    self.sliceletPanelLayout.addWidget(self.step2_inputExperimentalDataCollapsibleButton)

    self.step2_loadExperimentalDataCollapsibleButtonLayout = qt.QVBoxLayout(self.step2_inputExperimentalDataCollapsibleButton)
    self.step2_loadExperimentalDataCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step2_loadExperimentalDataCollapsibleButtonLayout.setSpacing(4)

    # Load data label
    self.step2_LoadDataLabel = qt.QLabel("Load all DICOM data involved in the workflow.\nNote: Can return to this step later if more data needs to be loaded")
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
    self.step2_AssignDataLabel = qt.QLabel("Assign loaded data to roles.\nNote: If this selection is changed later then all the following steps need to be performed again")
    self.step2_AssignDataLabel.wordWrap = True
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(self.step2_AssignDataLabel)

    # Choose the experimental flood field image
    self.step2_floodFieldImageSelectorComboBoxLayout = qt.QHBoxLayout()
    self.step2_floodFieldImageSelectorComboBox = slicer.qMRMLNodeComboBox()
    self.step2_floodFieldImageSelectorComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step2_floodFieldImageSelectorComboBox.addEnabled = False
    self.step2_floodFieldImageSelectorComboBox.removeEnabled = False
    self.step2_floodFieldImageSelectorComboBox.setMRMLScene( slicer.mrmlScene )
    self.step2_floodFieldImageSelectorComboBox.setToolTip( "--select the flood field image file--" ) 
    self.step2_floodFieldImageSelectorComboBoxLabel = qt.QLabel('Experimental Flood field image: ')
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
    self.step2_planDoseSelectorComboBoxLayout = qt.QHBoxLayout()
    self.step2_planDoseSelector = slicer.qMRMLNodeComboBox()
    self.step2_planDoseSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step2_planDoseSelector.addEnabled = False
    self.step2_planDoseSelector.removeEnabled = False
    self.step2_planDoseSelector.setMRMLScene( slicer.mrmlScene )
    self.step2_planDoseSelector.setToolTip( "Pick the planning dose volume." )
    self.step2_planDoseSelectorComboBoxLabel = qt.QLabel('Dose volume: ') 
    self.step2_planDoseSelectorComboBoxLayout.addWidget(self.step2_planDoseSelectorComboBoxLabel)
    self.step2_planDoseSelectorComboBoxLayout.addWidget(self.step2_planDoseSelector)
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addLayout(self.step2_planDoseSelectorComboBoxLayout)
    
    # Enter plane position
    self.step2_planePositionLabel = qt.QLabel('Plane position :')
    self.step2_planePositionLineEdit = qt.QLineEdit()
    self.step2_planePositionQHBoxLayout = qt.QHBoxLayout()
    self.step2_planePositionQHBoxLayout.addWidget(self.step2_planePositionLabel)
    self.step2_planePositionQHBoxLayout.addWidget(self.step2_planePositionLineEdit)

    # Connections
    self.step2_loadNonDicomDataButton.connect('clicked()', self.onLoadImageFilesButton)
    self.step2_showDicomBrowserButton.connect('clicked()', self.onDicomLoad)
    


  #------------------------------------------------------------------------------
  def setup_step3_applyCalibration(self):
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
    self.step3_calibrationFunctionOrder3LineEdit = qt.QLineEdit()
    self.step3_calibrationFunctionOrder3LineEdit.maximumWidth = 64
    
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder0LineEdit,0,1)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder0Label,0,2)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder1LineEdit,0,3)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder1Label,0,4)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder2LineEdit,0,5)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder2Label,0,6)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder3LineEdit,1,1)
    self.step3_applyCalibrationCollapsibleButtonLayout.addLayout(self.step3_calibrationFunctionLayout)

    
    # Apply calibration button
    self.step3_applyCalibrationButton = qt.QPushButton("Apply calibration function")
    self.step3_applyCalibrationButton.toolTip = "Apply calibration to experimental film."
    self.step3_applyCalibrationCollapsibleButtonLayout.addWidget(self.step3_applyCalibrationButton)

    # Connections
    self.step3_applyCalibrationButton.connect('clicked()', self.onApplyCalibrationButton)
    self.step3_loadCalibrationButton.connect('clicked()', self.onLoadCalibrationFunctionButton)
    self.step3_calibrationFunctionOrder0LineEdit.connect('textChanged(QString)', self.onTextChanged)
    self.step3_calibrationFunctionOrder1LineEdit.connect('textChanged(QString)', self.onTextChanged)
    self.step3_calibrationFunctionOrder2LineEdit.connect('textChanged(QString)', self.onTextChanged)
    self.step3_calibrationFunctionOrder3LineEdit.connect('textChanged(QString)', self.onTextChanged)
    
    
  def setup_step4_Registration(self):
    # Step 2: Load data panel
    self.step4_CollapsibleButton.setProperty('collapsedHeight', 4)
    self.step4_CollapsibleButton.text = "4. Register film to plan"
    self.sliceletPanelLayout.addWidget(self.step4_CollapsibleButton)

    self.step4_CollapsibleButtonLayout = qt.QVBoxLayout(self.step4_CollapsibleButton)
    self.step4_CollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step4_CollapsibleButtonLayout.setSpacing(4)
    self.sliceletPanelLayout.addStretch(1) # TODO this may need to be moved
    
    # Experimental film resolution mm/pixel
    self.step4_resolutionLineEdit = qt.QLineEdit()
    self.step4_resolutionLineEdit.toolTip = "Experimental film resultion (mm/pixel)"
    self.step4_resolutionLabel = qt.QLabel('Resolution (pixel/mm):')
    self.step4_resolutionQHBoxLayout = qt.QHBoxLayout()
    self.step4_resolutionQHBoxLayout.addWidget(self.step4_resolutionLabel)
    self.step4_resolutionQHBoxLayout.addWidget(self.step4_resolutionLineEdit)
    self.step4_CollapsibleButtonLayout.addLayout(self.step4_resolutionQHBoxLayout)
    
    
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

  def onDicomLoad(self):
    slicer.modules.dicom.widgetRepresentation()
    slicer.modules.DICOMWidget.enter()

  #------------------------------------------------------------------------------
  def fillStep1CalibrationPanel(self,CalibrationVolumeQuantity):
    for calibrationLayout in xrange(CalibrationVolumeQuantity):
      self.step1_calibrationVolumeSelectorLabelBeforeList[calibrationLayout].visible = True
      self.step1_calibrationVolumeSelector_cGySpinBoxList[calibrationLayout].visible = True
      self.step1_calibrationVolumeSelector_cGyLabelList[calibrationLayout].visible = True
      self.step1_calibrationVolumeSelectorComboBoxList[calibrationLayout].visible = True

    for calibrationLayout in range(1,self.maxCalibrationVolumeSelectorsInt-CalibrationVolumeQuantity + 1):
      self.step1_calibrationVolumeSelectorLabelBeforeList[-calibrationLayout].visible = False
      self.step1_calibrationVolumeSelector_cGySpinBoxList[-calibrationLayout].visible = False
      self.step1_calibrationVolumeSelector_cGyLabelList[-calibrationLayout].visible = False
      self.step1_calibrationVolumeSelectorComboBoxList[-calibrationLayout].visible = False

  #------------------------------------------------------------------------------
  def onNumberOfCalibrationFilmsSpinBoxValueChanged(self):
    self.fillStep1CalibrationPanel(self.step1_numberOfCalibrationFilmsSpinBox.value)

  #------------------------------------------------------------------------------
  def onSaveCalibrationBatchButton(self):
    self.savedFolderPath = qt.QFileDialog.getExistingDirectory(0, 'Open dir')

    # TODO: Check if folder is empty. If not, warn user that all files be deleted. If they choose yes, remove all files from folder, otherwise return
    
    if glob.glob(f.savedFolderPath + "/*") is not []:
      qt.QMessageBox.critical(None, 'Error', "Directory is not empty, all files will be deleted")
    

    # Create temporary scene for saving
    exportMrmlScene = slicer.vtkMRMLScene()

    # Get folder node (create if not exists)
    exportFolderNode = None
    self.folderNode = slicer.util.getNode(self.saveCalibrationBatchFolderNodeName)
    if self.folderNode is None:
      self.folderNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, None, slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelFolder(), self.saveCalibrationBatchFolderNodeName, None)
    # Clone folder node to export scene
    exportFolderNode = exportMrmlScene.CopyNode(self.folderNode)

    # Get flood field image node
    floodFieldImageVolumeNode = self.step1_floodFieldImageSelectorComboBox.currentNode()
    # Create flood field image subject hierarchy node, add it under folder node
    floodFieldVolumeShNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, self.folderNode, slicer.vtkMRMLSubjectHierarchyConstants.GetDICOMLevelSeries(), self.floodFieldImageShNodeName, floodFieldImageVolumeNode)
    floodFieldVolumeShNode.SetAttribute(self.calibrationVolumeDoseAttributeName, self.floodFieldAttributeValue)
    # Copy both image and SH to exported scene
    exportFloodFieldImageVolumeNode = exportMrmlScene.CopyNode(floodFieldImageVolumeNode)
    exportFloodFieldVolumeShNode = exportMrmlScene.CopyNode(floodFieldVolumeShNode)
    exportFloodFieldVolumeShNode.SetParentNodeID(exportFolderNode.GetID())

    # Export flood field image storage node
    floodFieldStorageNode = floodFieldImageVolumeNode.GetStorageNode()
    exportFloodFieldStorageNode = exportMrmlScene.CopyNode(floodFieldStorageNode)
    exportFloodFieldImageVolumeNode.SetAndObserveStorageNodeID(exportFloodFieldStorageNode.GetID())

    # Export flood field image display node
    floodFieldDisplayNode = floodFieldImageVolumeNode.GetDisplayNode()
    exportFloodFieldDisplayNode = exportMrmlScene.CopyNode(floodFieldDisplayNode)
    exportFloodFieldImageVolumeNode.SetAndObserveDisplayNodeID(exportFloodFieldDisplayNode.GetID())

    # Copy flood field image file to save folder
    shutil.copy(floodFieldStorageNode.GetFileName(), self.savedFolderPath)
    # TODO Change vtkMRMLVolumeArchetypeStorageNode.SetFileName to new file
    print "exportFloodFieldStorageNode file path was", exportFloodFieldStorageNode.GetFileName()
    exportFloodFieldStorageNode.SetFileName(os.path.normpath(self.savedFolderPath + '/' + ntpath.basename(floodFieldStorageNode.GetFileName())))
    print "exportFloodFieldStorageNode file path is now", exportFloodFieldStorageNode.GetFileName()

    for currentCalibrationVolumeIndex in xrange(self.step1_numberOfCalibrationFilmsSpinBox.value):
      # Get current calibration image node
      currentCalibrationVolume = self.step1_calibrationVolumeSelectorComboBoxList[currentCalibrationVolumeIndex].currentNode()
      # Create calibration image subject hierarchy node, add it under folder node
      calibrationVolumeShNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, self.folderNode, slicer.vtkMRMLSubjectHierarchyConstants.GetDICOMLevelSeries(), self.calibrationVolumeName, currentCalibrationVolume)
      doseLevelAttributeValue = self.step1_calibrationVolumeSelector_cGySpinBoxList[currentCalibrationVolumeIndex].value
      calibrationVolumeShNode.SetAttribute(self.calibrationVolumeDoseAttributeName, str(doseLevelAttributeValue))
      # Copy both image and SH to exported scene
      exportCalibrationImageVolumeNode = exportMrmlScene.CopyNode(currentCalibrationVolume)
      exportCalibrationVolumeShNode = exportMrmlScene.CopyNode(calibrationVolumeShNode)
      exportCalibrationVolumeShNode.SetParentNodeID(exportFolderNode.GetID())

      # Export calibration image storage node
      calibrationStorageNode = currentCalibrationVolume.GetStorageNode()
      exportCalibrationStorageNode = exportMrmlScene.CopyNode(calibrationStorageNode)
      exportCalibrationImageVolumeNode.SetAndObserveStorageNodeID(exportCalibrationStorageNode.GetID())

      # Export calibration image display node
      calibrationDisplayNode = currentCalibrationVolume.GetDisplayNode()
      exportCalibrationDisplayNode = exportMrmlScene.CopyNode(calibrationDisplayNode)
      exportCalibrationImageVolumeNode.SetAndObserveDisplayNodeID(exportCalibrationDisplayNode.GetID())

      # Copy calibration image file to save folder, set location of exportCalibrationStorageNode file to new folder
      print "exportCalibrationStorageNode file path was", exportCalibrationStorageNode.GetFileName()
      exportCalibrationStorageNode.SetFileName(os.path.normpath(self.savedFolderPath + '/' + ntpath.basename(calibrationStorageNode.GetFileName())))
      print "exportCalibrationStorageNode file path is now", exportCalibrationStorageNode.GetFileName()
      shutil.copy(calibrationStorageNode.GetFileName(), self.savedFolderPath)

    exportMrmlScene.SetURL(os.path.normpath(self.savedFolderPath + "/exportMrmlScene.mrml" ))
    exportMrmlScene.Commit()

    # Check if scene file has been created
    if os.path.isfile(exportMrmlScene.GetURL()) == True:
      qt.QMessageBox.information(None, "Calibration Volume Saving" , "Calibration volume successfully saved")
    else:
      qt.QMessageBox.information(None, "Calibration Volume Saving" , "Calibration volume save failed")

    exportMrmlScene.Clear(1)

  #------------------------------------------------------------------------------
  def onloadCalibrationBatchButton(self):
    savedFolderPath = qt.QFileDialog.getExistingDirectory(0, 'Open dir')  # TODO have it so it searches for the .mrml file in the saved folder
    #TODO put this all in a try/except
    os.chdir(os.path.normpath(savedFolderPath))
    mrmlFilesFound = 0

    savedMrmlSceneName = None
    for potentialMrmlFile in glob.glob("*.mrml"):
      mrmlFilesFound +=1
      savedMrmlSceneName = potentialMrmlFile

    if mrmlFilesFound >1:
      qt.QMessageBox.critical(None, 'Error', "More than one .mrml file found")
      logging.error("More than one .mrmlScene found in directory")
      return
    elif mrmlFilesFound <1:
      qt.QMessageBox.critical(None, 'Error', "No .mrml files found")
      logging.error("No .mrmlScene in directory")
      return

      #error message


    #savedMrmlSceneName = ntpath.basename(self.exportedSceneFileName)
    savedMrmlScenePath = os.path.normpath(savedFolderPath + "/" + savedMrmlSceneName)
    success = slicer.util.loadScene(savedMrmlScenePath)

    # TODO: Indentify flood field image by this attribute value (for attribute self.calibrationVolumeDoseAttributeName): self.floodFieldAttributeValue

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
    print "onPerformCalibrationButton \n"
    if self.lastAddedRoiNode is None or not hasattr(slicer.modules, 'cropvolume'):
      qt.QMessageBox.critical(None, 'Error', "Missing ROI selector")
      return

    # Get flood field image node
    floodFieldCalibrationVolume = self.step1_floodFieldImageSelectorComboBox.currentNode()
    
    if floodFieldCalibrationVolume is None:
      qt.QMessageBox.critical(None, 'Error', "Flood field image is not selected")
      return 
    
    # Crop flood field volume by last defined ROI
    cropVolumeLogic = slicer.modules.cropvolume.logic()
    cropVolumeLogic.CropVoxelBased(self.lastAddedRoiNode, floodFieldCalibrationVolume, floodFieldCalibrationVolume)

    imageStat = vtk.vtkImageAccumulate()
    imageStat.SetInputData(floodFieldCalibrationVolume.GetImageData())
    imageStat.Update()
    meanValueFloodField = imageStat.GetMean()[0]
    print "meanValueFloodField from imageStat: ", meanValueFloodField
    self.calibrationValues.append([self.floodFieldAttributeValue, meanValueFloodField])
    self.measuredOpticalDensities = []
    #TODO check this OD calculation


    for currentCalibrationVolumeIndex in xrange(self.step1_numberOfCalibrationFilmsSpinBox.value):
      # Get current calibration image node
      currentCalibrationVolume = self.step1_calibrationVolumeSelectorComboBoxList[currentCalibrationVolumeIndex].currentNode()
      currentCalibrationVolumeDose = self.step1_calibrationVolumeSelector_cGySpinBoxList[currentCalibrationVolumeIndex].value

      # Crop calibration images by last defined ROI
      cropVolumeLogic = slicer.modules.cropvolume.logic()
      cropVolumeLogic.CropVoxelBased(self.lastAddedRoiNode, currentCalibrationVolume, currentCalibrationVolume)

      # Measure dose value as average of the cropped calibration images
      #self.calibrationValues[imageDose_cGy] = measuredValueInRoi

      imageStat = vtk.vtkImageAccumulate()
      imageStat.SetInputData(currentCalibrationVolume.GetImageData())
      imageStat.Update()
      meanValue = imageStat.GetMean()[0]

      self.calibrationValues.append([meanValue, currentCalibrationVolumeDose])
      # Optical density calculation
      opticalDensity = math.log10(meanValueFloodField/meanValue)

      if opticalDensity < 0.0:
        opticalDensity = 0.0

      #x = optical density, y = dose
      self.measuredOpticalDensities.append([opticalDensity, currentCalibrationVolumeDose])
      print "meanValue from imageStat: ", meanValue, "associated dose is ", currentCalibrationVolumeDose

    self.measuredOpticalDensities.sort(key=lambda doseODPair: doseODPair[1])

    self.createCalibrationCurvesWindow()
    self.showCalibrationCurves()

    self.step3_calibrationFunctionOrder0LineEdit.text = str(self.bestCoefficients[2][0])
    self.step3_calibrationFunctionOrder1LineEdit.text = str(self.bestCoefficients[2][1])
    self.step3_calibrationFunctionOrder2LineEdit.text = str(self.bestCoefficients[2][2])
    self.step3_calibrationFunctionOrder3LineEdit.text = str(self.bestCoefficients[1])
    
    # Calibration function label
    calibrationFunctionString = "Dose(cGy) = " + str(self.bestCoefficients[2][0]) + " + " + str(self.bestCoefficients[2][1]) + "OD + " + str(self.bestCoefficients[2][2]) + "OD ^" + str(self.bestCoefficients[1])
    
    self.step1_2_performCalibrationFunctionLabel.text = calibrationFunctionString
    
  def cropPlanByROI(self):  #TODO, change to be just (self), get planDose from self.step2_planDoseSelector.currentNode()
    planDose = self.step2_planDoseSelector.currentNode()
    roiNode = slicer.vtkMRMLAnnotationROINode()
    slicer.mrmlScene.AddNode(roiNode)
    planDoseBounds = [0]*6
    planDose.GetRASBounds(planDoseBounds)  
    roiBounds = [0]*6
    planDoseCenter = [(planDoseBounds[0]+planDoseBounds[1])/2, (planDoseBounds[2]+planDoseBounds[3])/2, (planDoseBounds[4]+planDoseBounds[5])/2]
    newRadiusROI = [abs(planDoseBounds[1]-planDoseBounds[0])/2, 0.5*planDose.GetSpacing()[1], abs(planDoseBounds[5]-planDoseBounds[4])/2]
    roiNode.SetXYZ(planDoseCenter)
    roiNode.SetRadiusXYZ(newRadiusROI)
    # TODO why does the cropVolume radius not match ROI radius??
    cropParams = slicer.vtkMRMLCropVolumeParametersNode()
    cropParams.SetInputVolumeNodeID(planDose.GetID())
    cropParams.SetROINodeID(roiNode.GetID())
    cropParams.SetVoxelBased(True)
    cropLogic = slicer.modules.cropvolume.logic()
    cropLogic.Apply(cropParams)

    return croppedNode 

    
#------------------------------------------------------------------------------

  def onTextChanged(self):
    if not (self.step3_calibrationFunctionOrder0LineEdit.text == ''):
      self.bestCoefficients[2][0] = round(float(self.step3_calibrationFunctionOrder0LineEdit.text),5)
    if not (self.step3_calibrationFunctionOrder1LineEdit.text  == ''):
      self.bestCoefficients[2][1] = round(float(self.step3_calibrationFunctionOrder1LineEdit.text),5)
    if not (self.step3_calibrationFunctionOrder2LineEdit.text == ''):
      self.bestCoefficients[2][2] = round(float(self.step3_calibrationFunctionOrder2LineEdit.text),5)
    if not (self.step3_calibrationFunctionOrder3LineEdit.text == ''):
      self.bestCoefficients[1] = round(float(self.step3_calibrationFunctionOrder3LineEdit.text ),5)

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

    if slicer.mrmlScene.IsImporting() and addedNode.IsA("vtkMRMLSubjectHierarchyNode"):
      nodeLevel = addedNode.GetLevel()
      if (nodeLevel == slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelFolder()):# & (slicer.mrmlScene.IsImporting()) :
        self.batchFolderToParse = addedNode

    if addedNode.IsA('vtkMRMLAnnotationROINode'):
      self.lastAddedRoiNode = addedNode

  #------------------------------------------------------------------------------
  def onSceneEndImport(self, caller,event):
    if self.batchFolderToParse == None:
      qt.QMessageBox.critical(None, 'Error', "Wrong directory")
      logging.error("No subjectHierarchy folders in directory, wrong saved directory")
      return

    childrenToParse = vtk.vtkCollection()
    self.batchFolderToParse.GetAssociatedChildrenNodes(childrenToParse)

    calibrationVolumeNumber = childrenToParse.GetNumberOfItems() - 1
    self.fillStep1CalibrationPanel(calibrationVolumeNumber)
    self.step1_numberOfCalibrationFilmsSpinBox.value = calibrationVolumeNumber

    loadedFloodFieldScalarVolume = None

    sHNodeCollection = slicer.mrmlScene.GetNodesByClass('vtkMRMLSubjectHierarchyNode')
    sHNodeCollection.InitTraversal()
    currentNode = sHNodeCollection.GetNextItemAsObject()
    calibrationVolumeIndex = 0

    floodFieldSHFound = False
    CalibrationFilmsSHFound = False
    fileNotFoundError = False

    while currentNode!= None:
      if currentNode.GetAncestorAtLevel('Folder') == self.batchFolderToParse:
        if currentNode.GetAttribute(self.calibrationVolumeDoseAttributeName) == self.floodFieldAttributeValue :
          floodFieldSHFound = True
          if os.path.isfile(currentNode.GetAssociatedNode().GetStorageNode().GetFileName()) == True:
            if loadedFloodFieldScalarVolume is None:
              loadedFloodFieldScalarVolume = slicer.mrmlScene.GetNodeByID(currentNode.GetAssociatedNodeID())
              self.step1_floodFieldImageSelectorComboBox.setCurrentNode(loadedFloodFieldScalarVolume)
            else:
              qt.QMessageBox.critical(None, 'Error', "More than 1 flood field image found")
              logging.error("More than one flood field image found")
              slicer.mrmlScene.Clear(0)
              return
          else:
            fileNotFoundError = True
            logging.error("No flood field image in directory")

        if (self.calibrationVolumeName in currentNode.GetName()):
          CalibrationFilmsSHFound = True

          if os.path.isfile(currentNode.GetAssociatedNode().GetStorageNode().GetFileName()) == True:
            # Setting scalar volume to combobox
            loadedCalibrationVolume = slicer.mrmlScene.GetNodeByID(currentNode.GetAssociatedNodeID())
            self.step1_calibrationVolumeSelectorComboBoxList[calibrationVolumeIndex].setCurrentNode(loadedCalibrationVolume)

            # Setting dose attribute to combobox
            dose = int(currentNode.GetAttribute(self.calibrationVolumeDoseAttributeName))
            self.step1_calibrationVolumeSelector_cGySpinBoxList[calibrationVolumeIndex].value = dose
          else:
            fileNotFoundError = True
            logging.error("No calibration image in directory")

          calibrationVolumeIndex +=1
      currentNode = sHNodeCollection.GetNextItemAsObject()

    self.folderNode = self.batchFolderToParse
    self.batchFolderToParse = None

    result = CalibrationFilmsSHFound and floodFieldSHFound and (not fileNotFoundError)

    self.fileLoadingSuccessMessageHeader = "Calibration image loading"
    self.floodFieldFailureMessage = "Flood field image failed to load"
    self.calibrationVolumeLoadFailureMessage = "calibration volume failed to load"
    self.fileNotFoundFailureMessage = "File not found for 1 or more calibration volumes"

    # TODO fix placement of popup boxes on screen relative to load slider thing

    # Error messages for issues with loading
    if result:
      qt.QMessageBox.information(None,self.fileLoadingSuccessMessageHeader , 'Success! Saved calibration values loaded')
    else:
      qt.QMessageBox.critical(None, 'Error', "Failed to load saved calibration batch.")

    if fileNotFoundError:
      qt.QMessageBox.critical(None, 'Error', "File not found for 1 or more calibration volumes saved")
      slicer.mrmlScene.Clear(0)

    if floodFieldSHFound == False:
      qt.QMessageBox.warning(None, 'Warning', 'No flood field image.')
    if CalibrationFilmsSHFound == False:
      qt.QMessageBox.warning(None, 'Warning', 'No calibration film images.')

  #------------------------------------------------------------------------------
  def createCalibrationCurvesWindow(self):
    # Set up window to be used for displaying data
    self.calibrationCurveChartView = vtk.vtkContextView()
    self.calibrationCurveChartView.GetRenderer().SetBackground(1,1,1)
    self.calibrationCurveChart = vtk.vtkChartXY()
    self.calibrationCurveChartView.GetScene().AddItem(self.calibrationCurveChart)

  def showCalibrationCurves(self):
    # Create CALIBRATION dose vs. optical density plot
    self.calibrationCurveDataTable = vtk.vtkTable()
    calibrationNumberOfRows = len(self.measuredOpticalDensities)

    opticalDensityArray = vtk.vtkcalculatedDoseDoubleArray()
    opticalDensityArray.SetName("optical density")
    self.calibrationCurveDataTable.AddColumn(opticalDensityArray)
    dose_cGyCalibrationCurveArray = vtk.vtkcalculatedDoseDoubleArray()
    dose_cGyCalibrationCurveArray.SetName("dose (cGy) (measured)")
    self.calibrationCurveDataTable.AddColumn(dose_cGyCalibrationCurveArray)
    self.calibrationCurveDataTable.SetNumberOfRows(calibrationNumberOfRows)

    for rowIndex in xrange(calibrationNumberOfRows):
      self.calibrationCurveDataTable.SetValue(rowIndex, 0, self.measuredOpticalDensities[rowIndex][0])
      self.calibrationCurveDataTable.SetValue(rowIndex, 1, self.measuredOpticalDensities[rowIndex][1])

    if hasattr(self, 'calibrationMeanOpticalAttenuationLine' ):
      self.calibrationCurveChart.RemovePlotInstance(self.calibrationMeanOpticalAttenuationLine)
    self.calibrationMeanOpticalAttenuationLine = self.calibrationCurveChart.AddPlot(vtk.vtkChart.POINTS)
    self.calibrationMeanOpticalAttenuationLine.SetInputData(self.calibrationCurveDataTable, 0, 1)
    self.calibrationMeanOpticalAttenuationLine.SetColor(0, 0, 255, 255)
    self.calibrationMeanOpticalAttenuationLine.SetWidth(2.0)

    #-----
    # Create and populate the calculated dose/OD curve with K function
    #call function to find best coefficients



    self.bestCoefficients = self.findBestFunctionCoefficients()

    opticalDensityList = [round(0 + 0.01*opticalDensityIncrement,2) for opticalDensityIncrement in range(120)]
    opticalDensities = []

    for calculatedEntryIndex in xrange(120):
      newEntry = [opticalDensityList[calculatedEntryIndex], self.applyFitFunction(opticalDensityList[calculatedEntryIndex], self.bestCoefficients[1], self.bestCoefficients[2])]
      opticalDensities.append(newEntry)  #AR here

    # Create plot for dose calibration fitted curve
    self.opticalDensityToDoseFunctionTable = vtk.vtkTable()
    opticalDensityNumberOfRows = len(opticalDensities)
    opticalDensityCalculatedArray = vtk.vtkcalculatedDoseDoubleArray()
    opticalDensityCalculatedArray.SetName("opticalDensities")
    self.opticalDensityToDoseFunctionTable.AddColumn(opticalDensityCalculatedArray)
    dose_cGyCalculatedArray = vtk.vtkcalculatedDoseDoubleArray()
    dose_cGyCalculatedArray.SetName("optical density calculated")
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
    self.calibrationCurveChart.GetAxis(1).SetTitle('Optical Density| x - axis')
    self.calibrationCurveChart.GetAxis(0).SetTitle('Dose (cGy)   |y-axis')
    self.calibrationCurveChart.SetShowLegend(True)
    self.calibrationCurveChart.SetTitle('Dose (cGy) vs. Optical Density')
    self.calibrationCurveChartView.GetInteractor().Initialize()
    self.renderWindow = self.calibrationCurveChartView.GetRenderWindow()
    self.renderWindow.SetSize(800,550)
    self.renderWindow.SetWindowName('Dose (cGy) vs. Optical Density chart')
    self.renderWindow.Start()

  #------------------------------------------------------------------------------

  def meanSquaredError(self, n, coeff):
    sumMeanSquaredError = 0
    for i in xrange(len(self.measuredOpticalDensities)):
      newY = self.applyFitFunction(self.measuredOpticalDensities[i][0], n, coeff)
      sumMeanSquaredError += ((self.measuredOpticalDensities[i][1] - newY)**2) 
    return round(sumMeanSquaredError/(len(self.measuredOpticalDensities)),5)

  def applyFitFunction(self, OD, n, coeff):
    return coeff[0] + coeff[1]*OD + coeff[2]*(OD**n)

  def findCoefficients(self,n):
    # Calculate matrix A
    #print "findCoefficients"
    functionTermsMatrix = []
    #opticalDensity
    for row in xrange(len(self.measuredOpticalDensities)):
      opticalDensity = self.measuredOpticalDensities[row][0]
      functionTermsMatrix.append([1,opticalDensity,opticalDensity**n])
    functionTermsMatrix = numpy.asmatrix(functionTermsMatrix)
    #print functionTermsMatrix
    # Calculate constant term coefficient vector
    # functionOpticalDensityTerms
    functionOpticalDensityTerms = []
    for row in xrange(len(self.measuredOpticalDensities)):
      functionOpticalDensityTerms+= [self.measuredOpticalDensities[row][1]]
        #print "functionOpticalDensityTerms is ", functionOpticalDensityTerms
        # Find x
        #functionConstantTerms
    functionConstantTerms = numpy.linalg.lstsq(functionTermsMatrix,functionOpticalDensityTerms)
    coefficients = functionConstantTerms[0].tolist()

    for coefficientIndex in xrange(len(coefficients)):
      coefficients[coefficientIndex] = round(coefficients[coefficientIndex],5)


    return coefficients


  def findBestFunctionCoefficients(self):
    bestN = [] #entries are [MSE, n, answer]

    for n in xrange(1000,4001):
      n/=1000.0
      coeff = self.findCoefficients(n)
      MSE = self.meanSquaredError(n,coeff)
      bestN.append([MSE, n, coeff])

    bestN.sort(key=lambda bestNEntry: bestNEntry[0]) #TODO there is an error in here
    self.bestCoefficients = bestN[0]
    #print "best 10 coefficients are: \n", bestN[0:10]
    print "best coefficients ", bestN[0]

    return bestN[0]

  #------------------------------------------------------------------------------
  def exportCalibrationToCSV(self):

  #TODO change name, create success message
    import csv

    self.outputDir = qt.QFileDialog.getExistingDirectory(0, 'Open dir')
    if not os.access(self.outputDir, os.F_OK):
      os.mkdir(self.outputDir)

    # Assemble file name for calibration curve points file
    from time import gmtime, strftime
    fileName = self.outputDir + '/' + strftime("%Y%m%d_%H%M%S_", gmtime()) + self.calibrationFunctionFileName

    if not os.path.isfile(fileName):
      f = open(fileName, 'w')
      f.close()
    f = open(fileName, 'r+')
    f.seek(0)
    f.truncate()
    self.recSave(f, self.bestCoefficients)
    f.close()

  def recSave(self, f, lis):
    for x in lis:
      if x is not None:
        if type(x) is not list:
          #print x
          f.write(str(x) + '\n')
        else:
          self.recSave(f, x)

  def onLoadCalibrationFunctionButton(self):
    savedFilePath = qt.QFileDialog.getOpenFileName(0, 'Open file')
    self.loadCalibrationFunction(savedFilePath)

  def loadCalibrationFunction(self, fileName):
    print "loadCalibrationFunction"
    f = open(fileName, 'r+')
    content = f.readlines()
    if len(content)!= 5:
      qt.QMessageBox.critical(None, 'Error', "Invalid function file")

    self.bestCoefficients[0] = float(content[0].rstrip())
    self.bestCoefficients[1] = float(content[1].rstrip())
    self.step3_calibrationFunctionOrder3LineEdit.text = content[1].rstrip()
    self.bestCoefficients[2][0] = float(content[2].rstrip())
    self.step3_calibrationFunctionOrder0LineEdit.text = content[2].rstrip()
    self.bestCoefficients[2][1] = float(content[3].rstrip())
    self.step3_calibrationFunctionOrder1LineEdit.text = content[3].rstrip()
    self.bestCoefficients[2][2] = float(content[4].rstrip())
    self.step3_calibrationFunctionOrder2LineEdit.text = content[4].rstrip()

    f.close()

  #------------------------------------------------------------------------------

  def volumeToNumpyArray2D(self, currentVolume):
    volumeData = currentVolume.GetImageData()
    volumeDataScalars = volumeData.GetPointData().GetScalars()
    numpyArrayVolume = numpy_support.vtk_to_numpy(volumeDataScalars)
    volumeArray2D = numpyArrayVolume.reshape(volumeData.GetExtent()[3] + 1 , volumeData.GetExtent()[1] + 1 )
    return volumeArray2D
    
  #do the opposite of this
  def numpyArray2DToVolume(self, oldVolumeArray2D):
    newScalarVolume = slicer.vtkMRMLScalarVolumeNode()
    oldVolumeArray = numpy.ravel(oldVolumeArray2D)
    newVolumeScalars = numpy_support.numpy_to_vtk(oldVolumeArray)
    newVolumeScalarsCopy = vtk.vtkUnsignedShortArray()
    newVolumeScalarsCopy.DeepCopy(newVolumeScalars)
    newImageData = vtk.vtkImageData()
    newImageData.GetPointData().SetScalars(newVolumeScalarsCopy)
    newScalarVolume.SetAndObserveImageData(newImageData)
    #print('Image data converted from numpy: ')
    #print newImageData
    return newScalarVolume
  
  

  def calculateDoseFromFilm(self):
    #TODO this should be done in simpleITK 
    #TODO test to see if images are same size
    experimentalFilmArray2D = self.volumeToNumpyArray2D(self.step2_experimentalFilmSelectorComboBox.currentNode())
    floodFieldArray2D = self.volumeToNumpyArray2D(self.step2_floodFieldImageSelectorComboBox.currentNode())
    doseArray2D = numpy.zeros(shape = floodFieldArray2D.shape)
      
    inexcept = 0
    for rowIndex in xrange(len(experimentalFilmArray2D)):
      for columnIndex in xrange(len(experimentalFilmArray2D[0])):
        opticalDensity = 0
        try:
          opticalDensity = math.log10(floodFieldArray2D[rowIndex][columnIndex]/experimentalFilmArray2D[rowIndex][columnIndex])
        except:
          inexcept+=1
          opticalDensity = 0
        doseArray2D[rowIndex][columnIndex] = self.applyFitFunction(opticalDensity, self.bestCoefficients[1],self.bestCoefficients[2] )
        if doseArray2D[rowIndex][columnIndex] <0.0:
          doseArray2D[rowIndex][columnIndex] = 0.0
  
    return doseArray2D
    

  def onApplyCalibrationButton(self):
    print "onApplyCalibrationButton"

    calculatedDoseDoubleArray = self.calculateDoseFromFilm()
    calculatedDoseDoubleArray = numpy.rint(calculatedDoseDoubleArray)
    calculatedDoseDoubleArray = calculatedDoseDoubleArray.astype(int)
    castIntArrayVolume = self.numpyArray2DToVolume(calculatedDoseDoubleArray)
    castIntArrayVolume.GetImageData().SetExtent(self.step2_experimentalFilmSelectorComboBox.currentNode().GetImageData().GetExtent())
    # Copy orientation 
    castIntArrayVolume.CopyOrientation(self.step2_experimentalFilmSelectorComboBox.currentNode())
    self.calculatedDoseNode = castIntArrayVolume
    slicer.mrmlScene.AddNode(castIntArrayVolume)
    castIntArrayVolume.CreateDefaultDisplayNodes()
    

  def calculateOpticalDensity(self,IFlood, IFilm):
    print "IFlood ", IFlood, "IFilm ", IFilm
    opticalDensity = 0
    try:
      print "in try" 
      opticalDensity = math.log10((IFlood + 0.0)/IFilm)
    except:
      print "internal numerical error"
    
      opticalDensity = 0
    return opticalDensity
    




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
    parent.dependencies = ["DicomRtImportExport", "BRAINSFit", "BRAINSResample", "Markups", "DataProbe", "DoseComparison"]
    parent.contributors = ["Kevin Alexander (KGH, Queen's University), Csaba Pinter (Queen's University)"] # replace with "Firstname Lastname (Org)"
    parent.helpText = "Slicelet for film dosimetry analysis"
    parent.acknowledgementText = """
    This file was originally developed by Kevin Alexander (KGH, Queen's University). Funding was provided by CIHR
    """
    iconPath = os.path.join(os.path.dirname(self.parent.path), 'Resources/Icons', self.moduleName+'.png')
    parent.icon = qt.QIcon(iconPath)


#FilmDosimetryAnalysisWidget

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