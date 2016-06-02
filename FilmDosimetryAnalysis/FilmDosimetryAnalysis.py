import os
import shutil 
import unittest
import numpy
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging
import FilmDosimetryAnalysisLogic
import DataProbeLib
from slicer.util import VTKObservationMixin

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
    self.selfTestButton.connect('clicked()', self.onSelfTestButtonClicked)
    if not developerMode:
      self.selfTestButton.setVisible(False)

    # Initiate and group together all panels
    self.step0_layoutSelectionCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_loadDataCollapsibleButton = ctk.ctkCollapsibleButton()
    self.testButton = ctk.ctkCollapsibleButton()
    #self.step3_doseCalibrationCollapsibleButton = ctk.ctkCollapsibleButton()
   # self.step4_doseComparisonCollapsibleButton = ctk.ctkCollapsibleButton()
    #self.stepT1_lineProfileCollapsibleButton = ctk.ctkCollapsibleButton()

    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.step0_layoutSelectionCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step1_loadDataCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.testButton)
    #self.collapsibleButtonsGroup.addButton(self.step3_doseCalibrationCollapsibleButton)
    #self.collapsibleButtonsGroup.addButton(self.step4_doseComparisonCollapsibleButton)
   # self.collapsibleButtonsGroup.addButton(self.stepT1_lineProfileCollapsibleButton)

    self.step0_layoutSelectionCollapsibleButton.setProperty('collapsed', False)
    
    # Create module logic
    print('ZZZ 1')#TODO:
    self.logic = FilmDosimetryAnalysisLogic.FilmDosimetryAnalysisLogic()
    print('ZZZ 2')#TODO:

    # Set up constants
    #self.obiMarkupsFiducialNodeName = "OBI fiducials"
    # self.measuredMarkupsFiducialNodeName = "MEASURED fiducials"
    self.saveCalibrationBatchFolderNodeName = "Calibration batch" 
    self.saveDoseCalibrationVolumesName = "Dose calibration volumes"
    
    self.saveDoseCalibrationImageName = ["Film " + str(maxNumberCalibrationFilms + 1) for maxNumberCalibrationFilms in range(10)]
    
    self.saveSelectedImageValues_cGyName = "Save image values"
    
    self.extraMRMLScene = slicer.mrmlScene.NewInstance() 
    
    
	
    # Declare member variables (selected at certain steps and then from then on for the workflow)
    self.mode = None
    
    #TODO add constant for the volume 
    
    #selectedImageValues_cGy = [] #AR constant for dose selection in film/dose saving 
    
    #exportMrmlScene = slicer.vtkMRMLScene() #scene for saving - replace with self.exportMrmlScene
    
    
    self.planCtVolumeNode = None
    self.planDoseVolumeNode = None
    self.planStructuresNode = None
    self.obiVolumeNode = None
    self.measuredVolumeNode = None
    self.calibrationVolumeNode = None

    self.obiMarkupsFiducialNode = None
    self.measuredMarkupsFiducialNode = None
    self.calibratedMeasuredVolumeNode = None
    self.maskSegmentationNode = None
    self.maskSegmentID = None
    self.gammaVolumeNode = None

    # Get markups logic
    self.markupsLogic = slicer.modules.markups.logic()
    
    # Create or get fiducial nodes
    # self.obiMarkupsFiducialNode = slicer.util.getNode(self.obiMarkupsFiducialNodeName)
    # if self.obiMarkupsFiducialNode is None:
      # obiFiducialsNodeId = self.markupsLogic.AddNewFiducialNode(self.obiMarkupsFiducialNodeName)
      # self.obiMarkupsFiducialNode = slicer.mrmlScene.GetNodeByID(obiFiducialsNodeId)
    # self.measuredMarkupsFiducialNode = slicer.util.getNode(self.measuredMarkupsFiducialNodeName)
    # if self.measuredMarkupsFiducialNode is None:
      # measuredFiducialsNodeId = self.markupsLogic.AddNewFiducialNode(self.measuredMarkupsFiducialNodeName)
      # self.measuredMarkupsFiducialNode = slicer.mrmlScene.GetNodeByID(measuredFiducialsNodeId)
    # #measuredFiducialsDisplayNode = self.measuredMarkupsFiducialNode.GetDisplayNode()
    # #measuredFiducialsDisplayNode.SetSelectedColor(0, 0.9, 0)
    
    #create folder node
    self.folderNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, None, slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelFolder(), self.saveCalibrationBatchFolderNodeName, None)
    self.calibrationVolumeDoseAttributeName = "Dose"
    self.floodFieldImageShNodeName = "FloodFieldImage"
    self.calibrationVolumeName = "CalibrationVolume" 
    self.exportedSceneFileName = slicer.app.temporaryPath + "/exportMrmlScene.mrml" 
    self.savedCalibrationVolumeFolderName = "savedCalibrationVolumes"
    self.savedFolderPath = slicer.app.temporaryPath + "/" + self.savedCalibrationVolumeFolderName
   
    
    #calibrationVolumeShNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, self.folderNode, slicer.vtkMRMLSubjectHierarchyConstants.GetDICOMLevelSeries(), volumeNode.GetName(), volumeNode)

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
    self.setup_Step1_LoadData()
    #self.setup_Step2_Registration()  
    #self.setup_step3_DoseCalibration()  
    #self.setup_Step4_DoseComparison()
    #self.setup_StepT1_lineProfileCollapsibleButton()

    if widgetClass:
      self.widget = widgetClass(self.parent)
    self.parent.show()

  # Disconnect all connections made to the slicelet to enable the garbage collector to destruct the slicelet object on quit
  def disconnect(self):
    self.selfTestButton.disconnect('clicked()', self.onSelfTestButtonClicked)
    self.step0_viewSelectorComboBox.disconnect('activated(int)', self.onViewSelect)
    self.step0_clinicalModeRadioButton.disconnect('toggled(bool)', self.onClinicalModeSelect)
    self.step0_preclinicalModeRadioButton.disconnect('toggled(bool)', self.onPreclinicalModeSelect)
    #self.step2_1_registerObiToPlanCtButton.disconnect('clicked()', self.onObiToPlanCTRegistration) 
    #self.step2_1_translationSliders.disconnect('valuesChanged()', self.step2_1_rotationSliders.resetUnactiveSliders()) 
    #self.step1_2_doseToFilmCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_2_MeasuredDoseToObiRegistrationSelected) 
    #self.step2_2_1_obiFiducialSelectionCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_2_1_ObiFiducialCollectionSelected) 
    #self.step2_2_2_measuredFiducialSelectionCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_2_2_MeasuredFiducialCollectionSelected) 
    self.step1_loadImageFilesButton.disconnect('clicked()', self.onLoadNonDicomData)
    self.step1_numberOfCalibrationFilmsSpinBox.disconnect('valueChanged()', self.onstep1_numberOfCalibrationFilmsSpinBoxValueChanged)
    self.step1_saveCalibrationBatchButton.disconnect('clicked()', self.onSaveCalibrationBatchButton)
    #self.step2_2_3_registerMeasuredToObiButton.disconnect('clicked()', self.onMeasuredToObiRegistration) 
    #self.step3_1_pddLoadDataButton.disconnect('clicked()', self.onLoadPddDataRead)    
    #self.step3_1_alignCalibrationCurvesButton.disconnect('clicked()', self.onAlignCalibrationCurves)  
    #self.step3_1_xTranslationSpinBox.disconnect('valueChanged(double)', self.onAdjustAlignmentValueChanged)  
    #self.step3_1_yScaleSpinBox.disconnect('valueChanged(double)', self.onAdjustAlignmentValueChanged) 
    #self.step3_1_yTranslationSpinBox.disconnect('valueChanged(double)', self.onAdjustAlignmentValueChanged) 
    #self.step3_1_computeDoseFromPddButton.disconnect('clicked()', self.onComputeDoseFromPdd) 
    #self.step3_1_calibrationRoutineCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep3_1_CalibrationRoutineSelected) 
    #self.step3_1_showOpticalAttenuationVsDoseCurveButton.disconnect('clicked()', self.onShowOpticalAttenuationVsDoseCurve) 
    #self.step3_1_removeSelectedPointsFromOpticalAttenuationVsDoseCurveButton.disconnect('clicked()', self.onRemoveSelectedPointsFromOpticalAttenuationVsDoseCurve) 
    #self.step3_2_exportCalibrationToCSV.disconnect('clicked()', self.onExportCalibration) 
    #self.step3_2_applyCalibrationButton.disconnect('clicked()', self.onApplyCalibration) 
    #self.step4_doseComparisonCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep4_DoseComparisonSelected) 
    #self.step4_maskSegmentationSelector.disconnect('currentNodeChanged(vtkMRMLNode*)', self.onStep4_MaskSegmentationSelectionChanged) 
    #self.step4_maskSegmentationSelector.disconnect('currentSegmentChanged(QString)', self.onStep4_MaskSegmentSelectionChanged)  
    #self.step4_1_referenceDoseUseMaximumDoseRadioButton.disconnect('toggled(bool)', self.onUseMaximumDoseRadioButtonToggled)  
    #self.step4_1_computeGammaButton.disconnect('clicked()', self.onGammaDoseComparison) 
    #self.step4_1_showGammaReportButton.disconnect('clicked()', self.onShowGammaReport) 
    #self.stepT1_lineProfileCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStepT1_LineProfileSelected)
   # self.stepT1_createLineProfileButton.disconnect('clicked(bool)', self.onCreateLineProfileButton)
    #self.stepT1_inputRulerSelector.disconnect("currentNodeChanged(vtkMRMLNode*)", self.onSelectLineProfileParameters)
    #self.stepT1_exportLineProfilesToCSV.disconnect('clicked()', self.onExportLineProfiles)

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
    #TODO: Uncomment when preclinical mode works #601
    # self.step0_layoutSelectionCollapsibleButtonLayout.addRow(self.step0_modeSelectorLayout)
    self.step0_clinicalModeRadioButton.connect('toggled(bool)', self.onClinicalModeSelect)
    self.step0_preclinicalModeRadioButton.connect('toggled(bool)', self.onPreclinicalModeSelect)

  def setup_Step1_LoadData(self):
    # Step 1: Load data panel
    self.step1_loadDataCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_loadDataCollapsibleButton.text = "1. Load data"
    self.sliceletPanelLayout.addWidget(self.step1_loadDataCollapsibleButton)
    #self.step1_loadDataCollapsibleButtonLayout = qt.QFormLayout(self.step1_loadDataCollapsibleButton)  #changed QFormLayout to QVBoxLayout
    #self.step1_loadDataCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    #self.step1_loadDataCollapsibleButtonLayout.setSpacing(4)

    #self.step1_loadDataFromDirectoryLayout = qt.QHBoxLayout(self.step1_loadDataCollapsibleButtonLayout)
    
    #Step 1 main background layout
    self.step1_backgroundLayout = qt.QVBoxLayout(self.step1_loadDataCollapsibleButton)
    
    
    
    ######## step1_topBackgroundSubLayout
    self.step1_topBackgroundSubLayout = qt.QVBoxLayout()
    #add to step1_backgroundLayout
    self.step1_backgroundLayout.addLayout(self.step1_topBackgroundSubLayout)
    
    
    # Load data label
    self.step1_loadDataLabel = qt.QLabel("Load all image data involved in the workflow.\nCan either be a new batch of image files, or a saved image batch")
    self.step1_loadDataLabel.wordWrap = True
    #self.step1_loadDataCollapsibleButtonLayout.addRow(self.step1_loadDataLabel)
    self.step1_topBackgroundSubLayout.addWidget(self.step1_loadDataLabel)
    
   
    # Load image data button
    self.step1_loadImageFilesButton = qt.QPushButton("Load image files")
    self.step1_loadImageFilesButton.toolTip = "Load png film images."
    self.step1_loadImageFilesButton.name = "loadImageFilesButton"
    #load saved image batch button
    self.step1_loadSavedImageBatchButton = qt.QPushButton("Load saved image batch")
    self.step1_loadSavedImageBatchButton.toolTip = "Load a batch of films with assigned doses."
    self.step1_loadSavedImageBatchButton.name = "loadSavedImageFilesButton"
    #horizontal button layout
    self.step1_loadImageButtonLayout = qt.QHBoxLayout()
    self.step1_loadImageButtonLayout.addWidget(self.step1_loadImageFilesButton)
    self.step1_loadImageButtonLayout.addWidget(self.step1_loadSavedImageBatchButton)

    
    #self.step1_topBackgroundSubLayout.addWidget(self.step1_loadImageFilesButton)
    self.step1_topBackgroundSubLayout.addLayout(self.step1_loadImageButtonLayout)

    
    # Assign data label
    self.step1_AssignDataLabel = qt.QLabel("Assign loaded data to roles.\nNote: If this selection is changed later then all the following steps need to be performed again")
    self.step1_AssignDataLabel.wordWrap = True
    self.step1_topBackgroundSubLayout.addWidget(self.step1_AssignDataLabel)

    # number of calibration films node selector
    self.step1_numberOfCalibrationFilmsSelectorLayout = qt.QHBoxLayout()   #TODO add parent in parentheses, needed?
    self.step1_numberOfCalibrationFilmsSpinBox = qt.QSpinBox()
    self.step1_numberOfCalibrationFilmsSpinBox.value = 5
    self.step1_numberOfCalibrationFilmsSpinBox.maximum = 10
    self.step1_numberOfCalibrationFilmsSpinBox.minimum = 0
    self.step1_numberOfCalibrationFilmsSpinBox.enabled = True
    self.step1_numberOfCalibrationFilmsLabelBefore = qt.QLabel('Number of calibration films is: ')
    self.step1_numberOfCalibrationFilmsSelectorLayout.addWidget(self.step1_numberOfCalibrationFilmsLabelBefore)
    self.step1_numberOfCalibrationFilmsSelectorLayout.addWidget(self.step1_numberOfCalibrationFilmsSpinBox)
    self.step1_topBackgroundSubLayout.addLayout(self.step1_numberOfCalibrationFilmsSelectorLayout)


    #TODO continue changing names to have step1_

    ##choose the flood field image
    self.step1_floodFieldImageSelectorComboBoxLayout = qt.QHBoxLayout()
    self.step1_floodFieldImageSelectorComboBox = slicer.qMRMLNodeComboBox()
    self.step1_floodFieldImageSelectorComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_floodFieldImageSelectorComboBox.addEnabled = False
    self.step1_floodFieldImageSelectorComboBox.removeEnabled = False
    self.step1_floodFieldImageSelectorComboBox.setMRMLScene( slicer.mrmlScene )
    self.step1_floodFieldImageSelectorComboBox.setToolTip( "--pick the flood field image file-- CHANGE THIS." ) #TODO
    self.step1_floodFieldImageSelectorComboBoxLabel = qt.QLabel('Flood field image: ')

    self.step1_floodFieldImageSelectorComboBoxLayout.addWidget(self.step1_floodFieldImageSelectorComboBoxLabel)
    self.step1_floodFieldImageSelectorComboBoxLayout.addWidget(self.step1_floodFieldImageSelectorComboBox)

    self.step1_topBackgroundSubLayout.addLayout(self.step1_floodFieldImageSelectorComboBoxLayout)

    #self.step1_topBackgroundSubLayout.addRow('Flood field image: ', self.step1_floodFieldImageSelectorComboBox) #TODO what is this?

    ##

    self.step1_middleBackgroundSubLayout = qt.QVBoxLayout()
    #add to step1_backgroundLayout
    self.step1_backgroundLayout.addLayout(self.step1_middleBackgroundSubLayout)
    
    # self.middleTest = qt.QLabel('testmiddlebackground')
    # self.step1_middleBackgroundSubLayout.addWidget(self.middleTest)
     
     
     
    # #TODO put loop in a layout, add handler function (search for "connect" - valueChanged(int) equivalent of clicked(), look at line 748

    self.step1_calibrationVolumeLayoutList = []
    self.step1_calibrationVolumeSelectorLabelBeforeList = []
    self.step1_calibrationVolumeSelector_cGySpinBoxList = []
    self.step1_calibrationVolumeSelector_cGyLabelList = []
    self.step1_calibrationVolumeSelectorComboBoxList = []
    
    
    for doseToImageLayoutNumber in xrange(self.step1_numberOfCalibrationFilmsSpinBox.value):
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

      #self.step1_loadDataCollapsibleButtonLayout.addRow(self.step1_doseToImageSelectorRowLayout)
      
      self.step1_calibrationVolumeLayoutList.append(self.step1_doseToImageSelectorRowLayout)
      
      self.step1_middleBackgroundSubLayout.addLayout(self.step1_doseToImageSelectorRowLayout)
      #self.step1_1_doseToImageSelectionButtonLayout.addRow(self.step1_doseToImageSelectorRowLayout)

      
    self.step1_bottomBackgroundSubLayout = qt.QVBoxLayout()
    #add to step1_backgroundLayout
    self.step1_backgroundLayout.addLayout(self.step1_bottomBackgroundSubLayout)
      
    #calibration button
    self.step1_performCalibrationButton = qt.QPushButton("Perform calibration")
    self.step1_performCalibrationButton.toolTip = "Finds the calibration function"
    self.step1_bottomBackgroundSubLayout.addWidget(self.step1_performCalibrationButton)
    
    #Save batch button
    self.step1_saveCalibrationBatchButton = qt.QPushButton("Save calibration batch")
    self.step1_saveCalibrationBatchButton.toolTip = "Saves current calibration batch"
    self.step1_bottomBackgroundSubLayout.addWidget(self.step1_saveCalibrationBatchButton)
    
    
    
    self.step1_bottomBackgroundSubLayout.addStretch(1)  #TODO fix main layout when addStretch is added

    # # Connections
    #self.step4_maskSegmentationSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onStep4_MaskSegmentationSelectionChanged)
    self.step1_loadImageFilesButton.connect('clicked()', self.onLoadNonDicomData)
    self.step1_saveCalibrationBatchButton.connect('clicked()', self.onSaveCalibrationBatchButton)
    self.step1_loadSavedImageBatchButton.connect('clicked()', self.onLoadSavedImageBatchButton)
    
    #self.step1_showDicomBrowserButton.connect('clicked()', self.logic.onDicomLoad)
    self.step1_loadImageFilesButton.connect('clicked()', self.onLoadNonDicomData)
    self.step1_loadDataCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep1_LoadDataCollapsed)
    #TODO add connection for step1_numberOfCalibrationFilmsSpinBox , add disconnect
    self.step1_numberOfCalibrationFilmsSpinBox.connect('valueChanged(int)', self.onstep1_numberOfCalibrationFilmsSpinBoxValueChanged)

    self.sliceletPanelLayout.addStretch(1)  #AR current   
    
    ################
    
# ###step 2 button for testing

 # # Step 2: Registration step
   

  # def setup_step3_DoseCalibration(self):
    
    
    
    
    
  # def setup_Step4_DoseComparison(self):
    

  # def setup_StepT1_lineProfileCollapsibleButton(self):
    

  #
  # -----------------------
  # Event handler functions
  # -----------------------
  #
  
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

  def onClinicalModeSelect(self, toggled):
    if self.step0_clinicalModeRadioButton.isChecked() == True:
      self.mode = 'Clinical'
            
      # Step 3.1. Label for plot visibility
      self.step3_1_showOpticalAttenuationVsDoseCurveButton.setText("Plot optical attenuation vs dose")
      self.step3_1_showOpticalAttenuationVsDoseCurveButton.toolTip = "Show optical attenuation vs. Dose curve to determine the order of polynomial to fit."
  
  def onPreclinicalModeSelect(self, toggled):
    if self.step0_preclinicalModeRadioButton.isChecked() == True:
      self.mode = 'Preclinical'
            
      # Step 3.1. Label for plot visibility
      self.step3_1_showOpticalAttenuationVsDoseCurveButton.setText("Plot R1 vs dose")
      self.step3_1_showOpticalAttenuationVsDoseCurveButton.toolTip = "Show Relaxation Rates vs. Dose curve to determine the order of polynomial to fit."
    
  def onLoadNonDicomData(self):
    slicer.util.openAddDataDialog()
    
  #TODO current add connection event here
  
  def fillStep1CalibrationPanel(self,CalibrationVolumeQuantity):
    print "fillStep1CalibrationPanel()"
    for doseToImageFormLayout in xrange(len(self.step1_calibrationVolumeLayoutList)-1,-1,-1):
      
      #print "deleting", " widget: " 
      #print self.step1_calibrationVolumeLayoutList[doseToImageFormLayout]
      self.step1_calibrationVolumeLayoutList[doseToImageFormLayout].deleteLater()
      self.step1_calibrationVolumeLayoutList.pop()
      self.step1_calibrationVolumeSelectorLabelBeforeList[doseToImageFormLayout].deleteLater()
      self.step1_calibrationVolumeSelectorLabelBeforeList.pop()
      self.step1_calibrationVolumeSelector_cGySpinBoxList[doseToImageFormLayout].deleteLater()
      self.step1_calibrationVolumeSelector_cGySpinBoxList.pop()
      self.step1_calibrationVolumeSelector_cGyLabelList[doseToImageFormLayout].deleteLater()
      self.step1_calibrationVolumeSelector_cGyLabelList.pop()
      self.step1_calibrationVolumeSelectorComboBoxList[doseToImageFormLayout].deleteLater()
      self.step1_calibrationVolumeSelectorComboBoxList.pop()
      
      
    
    
    #TODO get it to delete labels
   
    
    self.step1_doseToImageRowLabelMiddle = qt.QLabel(' cGy :')
    
    for doseToImageLayoutNumber in xrange (CalibrationVolumeQuantity):
      self.step1_doseToImageRowLabelBefore = qt.QLabel('Calibration ')
      self.step1_calibrationVolumeSelectorLabelBeforeList.append(self.step1_doseToImageRowLabelBefore)
      
      self.step1_doseToImageRowSpinBox = qt.QSpinBox()
      self.step1_doseToImageRowSpinBox.minimum = 0
      self.step1_doseToImageRowSpinBox.maximum = 1000
      self.step1_calibrationVolumeSelector_cGySpinBoxList.append(self.step1_doseToImageRowSpinBox)
      
      self.step1_doseToImage_cGyLabel = qt.QLabel(' cGy : ')
      self.step1_calibrationVolumeSelector_cGyLabelList.append(self.step1_doseToImage_cGyLabel)
      
      
      self.step1_doseToImageSelectorComboBox = slicer.qMRMLNodeComboBox()
      self.step1_doseToImageSelectorComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
      self.step1_doseToImageSelectorComboBox.addEnabled = False
      self.step1_doseToImageSelectorComboBox.removeEnabled = False
      self.step1_doseToImageSelectorComboBox.setMRMLScene( slicer.mrmlScene )
      self.step1_doseToImageSelectorComboBox.setToolTip( "Choose the film image corresponding to the dose above" )
      self.step1_calibrationVolumeSelectorComboBoxList.append(self.step1_doseToImageSelectorComboBox)
      
      
      self.step1_doseToImageFormLayout = qt.QHBoxLayout()
      self.step1_doseToImageFormLayout.addWidget(self.step1_doseToImageRowLabelBefore)
      self.step1_doseToImageFormLayout.addWidget(self.step1_doseToImageRowSpinBox)
      self.step1_doseToImageFormLayout.addWidget(self.step1_doseToImage_cGyLabel)
      self.step1_doseToImageFormLayout.addWidget(self.step1_doseToImageSelectorComboBox)
      self.step1_calibrationVolumeLayoutList.append(self.step1_doseToImageFormLayout)
      
      
      self.step1_middleBackgroundSubLayout.addLayout(self.step1_doseToImageFormLayout)
    
  
  
  
  def onstep1_numberOfCalibrationFilmsSpinBoxValueChanged(self):
    self.fillStep1CalibrationPanel(self.step1_numberOfCalibrationFilmsSpinBox.value)
  
      
  
  def onSaveCalibrationBatchButton(self):
    import os
    import ntpath
    
    self.savedFolderPath = qt.QFileDialog.getExistingDirectory(0, 'Open dir')
    
    # # Create temporary scene for saving
    exportMrmlScene = slicer.vtkMRMLScene()     
    
    # if (os.path.isdir(self.exportedSceneFileName) == False):
      # os.mkdir(self.savedFolderPath)
    
    exportMrmlScene.AddNode(self.folderNode)
    
    
    floodFieldImageVolumeNode = self.step1_floodFieldImageSelectorComboBox.currentNode()
    floodFieldVolumeShNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, self.folderNode, slicer.vtkMRMLSubjectHierarchyConstants.GetDICOMLevelSeries(), self.floodFieldImageShNodeName, floodFieldImageVolumeNode)
    #floodFieldVolumeShNode.SetAttribute(self.calibrationVolumeDoseAttributeName, None)
    exportMrmlScene.AddNode(floodFieldImageVolumeNode)
    exportMrmlScene.CopyNode(floodFieldVolumeShNode)
    
    #volume storage node saving 
    floodFieldStorageNode = slicer.util.getNode(floodFieldImageVolumeNode.GetStorageNodeID())
    exportMrmlScene.CopyNode(floodFieldStorageNode)
    
    #display node saving
    floodFieldDisplayNode = slicer.util.getNode(floodFieldImageVolumeNode.GetDisplayNodeID())
    exportMrmlScene.CopyNode(floodFieldDisplayNode)
    
    
    
    shutil.copy(floodFieldStorageNode.GetFileName(), self.savedFolderPath)
    
    for currentCalibrationVolumeIndex in xrange(len(self.step1_calibrationVolumeSelectorComboBoxList)):
      #subject hierarchy
      currentCalibrationVolume = self.step1_calibrationVolumeSelectorComboBoxList[currentCalibrationVolumeIndex].currentNode()
      calibrationVolumeShNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, self.folderNode, slicer.vtkMRMLSubjectHierarchyConstants.GetDICOMLevelSeries(), self.calibrationVolumeName, currentCalibrationVolume)
      calibrationVolumeShNode.SetAttribute(self.calibrationVolumeDoseAttributeName, str(self.step1_calibrationVolumeSelector_cGySpinBoxList[currentCalibrationVolumeIndex].value)) #TODO change to real name
      exportMrmlScene.AddNode(currentCalibrationVolume) 
      exportMrmlScene.CopyNode(calibrationVolumeShNode) 
     
      #volumeStorageNode saving 
      volumeStorageNode = slicer.util.getNode(currentCalibrationVolume.GetStorageNodeID())
      exportMrmlScene.CopyNode(volumeStorageNode)
      
      #displayNode saving 
      volumeDisplayNode = slicer.util.getNode(currentCalibrationVolume.GetDisplayNodeID())
      exportMrmlScene.CopyNode(volumeDisplayNode)
      
      
      
      
      #TODO why change the file storage url to something that doesn't exist? 
      #volumeStorageNode.SetFileName(self.calibrationVolumeName + ntpath.basename(volumeStorageNode.GetFileName())) #formerly known as ???
      
      #print "calibration volume name is ", self.calibrationVolumeName, "storage node basename is ", ntpath.basename(volumeStorageNode.GetFileName()
      #print "file stored at ", volumeStorageNode.GetFileName()
      
      calibrationVolumeSavingPath = os.path.normpath(self.savedFolderPath + "/" + ntpath.basename(volumeStorageNode.GetFileName()))
      if os.path.isfile(calibrationVolumeSavingPath):
        print "it already exists"
      
      shutil.copy(volumeStorageNode.GetFileName(), self.savedFolderPath)
      #TODO should file name be reset to the saved directory? 

    #+ "/exportMrmlScene.mrml" 
    
    
    
    exportMrmlScene.SetURL(os.path.normpath(self.savedFolderPath + "/exportMrmlScene.mrml" ))  #TODO uncomment/change
    exportMrmlScene.Commit()  #TODO uncomment
    # # Check if scene file has been created
    

    if os.path.isfile(exportMrmlScene.GetURL()) == True:
      savedSuccessfullyLabel = qt.QLabel( "Calibration volume successfully saved")
      self.step1_bottomBackgroundSubLayout.addWidget(savedSuccessfullyLabel)
      print "Calibration volume successfully saved"
    else:
      print "Calibration volume not successfully saved" 
      savedUnsuccessfullyLabel = qt.QLabel( "Calibration volume save failed")
      self.step1_bottomBackgroundSubLayout.addWidget(savedUnsuccessfullyLabel)
    
    # import os
    # #os.file...... #python file operators
    
    
    exportMrmlScene.Clear(1)
   
    
    
    
  def onLoadSavedImageBatchButton(self):
    print "empty function"
    # # # # #slicer.mrmlScene = self.folderNode.GetScene()
    # print "onLoadSavedImageBatchButton pressed" 
    
    # extraMRMLScene = slicer.mrmlScene
    # slicer.mrmlScene.Clear(0)
    
    # slicer.mrmlScene = exportMrmlScene
    
    # #set contents of extra scene to present scene 
    
    # savedCalibrationVolumes = []
    
    # v = vtk.vtkCollection()
    # v = slicer.mrmlScene.GetNodes()
    # v.InitTraversal()
    # nn = v.GetNextItemAsObject()
    
    # while nn!=None:
      
      
      
      # if (self.floodFieldImageShNodeName in nn.GetName()):
      
        # print "this is the flood field image"
        
      # if (self.calibrationVolumeName in nn.GetName()):
        # print "this is a calibration volume"
        # savedCalibrationVolumes.append(nn)
  
      # nn = v.GetNextItemAsObject()
      
    # print "there are ", len(savedCalibrationVolumes), " items"
    
    # self.fillStep1CalibrationPanel(len(savedCalibrationVolumes))
    
    # print savedCalibrationVolumes
    
    # c = vtk.vtkCollection()
    
    # savedCalibrationVolumes[0].GetAssociatedChildrenNodes(c)
    # print c.GetNumberOfItems()
    
    # # for savedCalibrationVolumeIndex in xrange(len(self.step1_calibrationVolumeSelectorComboBoxList)):
      # #TODO fix problem line
      # # #self.step1_calibrationVolumeSelectorComboBoxList[savedCalibrationVolumeIndex].setCurrentNode(savedCalibrationVolumes[savedCalibrationVolumeIndex].currentNode()) 
      # # currentCalibrationVolumeComboBox = self.step1_calibrationVolumeSelectorComboBoxList[savedCalibrationVolumeIndex]
    
    
    
  
  
  
  def onStep1_LoadDataCollapsed(self, collapsed):
    # Save selections to member variables when switching away from load data step
    if collapsed == True:
      self.planCtVolumeNode = self.doseToImageFilmSelector.currentNode()
      self.planDoseVolumeNode = self.step1_floodFieldImageSelectorComboBox.currentNode()
      self.obiVolumeNode = self.obiSelector.currentNode()
      self.planStructuresNode = self.planStructuresSelector.currentNode()
      self.measuredVolumeNode = self.measuredVolumeSelector.currentNode()
      self.calibrationVolumeNode = self.numberOfCalibrationFilmsSelector.currentNode()

  # def onStep2_2_MeasuredDoseToObiRegistrationSelected(self, collapsed):    
    # # Make sure the functions handling entering the fiducial selection panels are called when entering the outer panel
    # if collapsed == False: 
      # # if self.step2_2_1_obiFiducialSelectionCollapsibleButton.collapsed == False:    to 995
        # # self.onStep2_2_1_ObiFiducialCollectionSelected(False)
      # # elif self.step2_2_2_measuredFiducialSelectionCollapsibleButton.collapsed == False:
        # # self.onStep2_2_2_MeasuredFiducialCollectionSelected(False)

  # def onStep2_2_1_ObiFiducialCollectionSelected(self, collapsed):
    # appLogic = slicer.app.applicationLogic()
    # selectionNode = appLogic.GetSelectionNode()
    # interactionNode = appLogic.GetInteractionNode()

    # if collapsed == False:
      # # Turn on persistent fiducial placement mode
      # interactionNode.SwitchToPersistentPlaceMode()

      # # Select OBI fiducials node
      # self.step2_2_1_obiFiducialList.setCurrentNode(self.obiMarkupsFiducialNode)
      # self.step2_2_1_obiFiducialList.activate()

      # # Automatically show OBI volume (show nothing if not present)
      # if self.obiVolumeNode is not None:
        # selectionNode.SetActiveVolumeID(self.obiVolumeNode.GetID())
      # else:
        # selectionNode.SetActiveVolumeID(None)
        # slicer.util.errorDisplay('OBI volume not selected!\nPlease return to first step and make the assignment')
      # selectionNode.SetSecondaryVolumeID(None)
      # appLogic.PropagateVolumeSelection()
    # else:
      # # Turn off fiducial place mode
      # interactionNode.SwitchToViewTransformMode()

  # def onStep2_2_2_MeasuredFiducialCollectionSelected(self, collapsed):
    # appLogic = slicer.app.applicationLogic()
    # selectionNode = appLogic.GetSelectionNode()
    # interactionNode = appLogic.GetInteractionNode()

    # if collapsed == False:
      # # Turn on persistent fiducial placement mode
      # interactionNode.SwitchToPersistentPlaceMode()

      # # Select MEASURED fiducials node
      # self.step2_2_2_measuredFiducialList.setCurrentNode(self.measuredMarkupsFiducialNode)
      # self.step2_2_2_measuredFiducialList.activate()

      # # Automatically show MEASURED volume (show nothing if not present)
      # if self.measuredVolumeNode is not None:
        # selectionNode.SetActiveVolumeID(self.measuredVolumeNode.GetID())
      # else:
        # selectionNode.SetActiveVolumeID(None)
        # slicer.util.errorDisplay('Gel dosimeter volume not selected!\nPlease return to first step and make the assignment')
      # selectionNode.SetSecondaryVolumeID(None)
      # appLogic.PropagateVolumeSelection() 
    # else:
      # # Turn off fiducial place mode
      # interactionNode.SwitchToViewTransformMode()

  def onObiToPlanCTRegistration(self):
    # Start registration
    obiVolumeID = self.obiVolumeNode.GetID()
    planCTVolumeID = self.planCtVolumeNode.GetID()
    planDoseVolumeID = self.planDoseVolumeNode.GetID()
    planStructuresID = self.planStructuresNode.GetID()
    obiToPlanTransformNode = self.logic.registerObiToPlanCt(obiVolumeID, planCTVolumeID, planDoseVolumeID, planStructuresID)

    # Show the two volumes for visual evaluation of the registration
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(planCTVolumeID)
    selectionNode.SetSecondaryVolumeID(obiVolumeID)
    appLogic.PropagateVolumeSelection() 
    # Set color to the OBI volume
    obiVolumeDisplayNode = self.obiVolumeNode.GetDisplayNode()
    colorNode = slicer.util.getNode('Green')
    obiVolumeDisplayNode.SetAndObserveColorNodeID(colorNode.GetID())
    # Set transparency to the OBI volume
    compositeNodes = slicer.util.getNodes("vtkMRMLSliceCompositeNode*")
    for compositeNode in compositeNodes.values():
      compositeNode.SetForegroundOpacity(0.5)
    # Hide structures for sake of speed
    if self.planStructuresNode is not None:
      self.planStructuresNode.GetDisplayNode().SetVisibility(0)
    # Hide beam models
    beamModelsParent = slicer.util.getNode('*_BeamModels_SubjectHierarchy')
    if beamModelsParent is not None:
      beamModelsParent.SetDisplayVisibilityForBranch(0)
      
    # Set transforms to slider widgets
    #step2_1_translationSliders.setMRMLTransformNode(obiToPlanTransformNode) 
    #self.step2_1_rotationSliders.setMRMLTransformNode(obiToPlanTransformNode)

    # Change single step size to 0.5mm in the translation controls
    #sliders = slicer.util.findChildren(widget=self.step2_1_translationSliders, className='qMRMLLinearTransformSlider') 
    for slider in sliders:
      slider.singleStep = 0.5

  # def onMeasuredToObiRegistration(self):
    # errorRms = self.logic.registerObiToMeasured(self.obiMarkupsFiducialNode.GetID(), self.measuredMarkupsFiducialNode.GetID())
    
    # # Show registration error on GUI
    # self.step2_2_3_measuredToObiFiducialRegistrationErrorLabel.setText(str(errorRms) + ' mm')

    # # Apply transform to MEASURED volume
    # obiToMeasuredTransformNode = slicer.util.getNode(self.logic.obiToMeasuredTransformName)
    # self.measuredVolumeNode.SetAndObserveTransformNodeID(obiToMeasuredTransformNode.GetID())

    # # Show both volumes in the 2D views
    # appLogic = slicer.app.applicationLogic()
    # selectionNode = appLogic.GetSelectionNode()
    # selectionNode.SetActiveVolumeID(self.obiVolumeNode.GetID())
    # selectionNode.SetSecondaryVolumeID(self.measuredVolumeNode.GetID())
    # appLogic.PropagateVolumeSelection() 

  def onLoadPddDataRead(self):  #TODO this is the thing to turn into the PNG
    fileName = qt.QFileDialog.getOpenFileName(0, 'Open PDD data file', '', 'CSV with COMMA ( *.csv )')
    if fileName is not None and fileName != '':
      success = self.logic.loadPdd(fileName)
      if success == True:
        self.logic.delayDisplay('PDD loaded successfully')
      else:
        slicer.util.errorDisplay('PDD loading failed!')

  def onStep3_1_CalibrationRoutineSelected(self, collapsed):
    if collapsed == False:
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      if self.measuredVolumeNode is not None:
        selectionNode.SetActiveVolumeID(self.measuredVolumeNode.GetID())
      else:
        selectionNode.SetActiveVolumeID(None)
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection() 

  def parseCalibrationVolume(self):
    radiusOfCentreCircleText = self.step3_1_radiusMmFromCentrePixelLineEdit.text
    radiusOfCentreCircleFloat = 0
    if radiusOfCentreCircleText.isnumeric():
      radiusOfCentreCircleFloat = float(radiusOfCentreCircleText)
    else:
      slicer.util.errorDisplay('Invalid averaging radius!')
      return False

    success = self.logic.getMeanOpticalAttenuationOfCentralCylinder(self.calibrationVolumeNode.GetID(), radiusOfCentreCircleFloat)
    if success == False:
      slicer.util.errorDisplay('Calibration volume parsing failed!')
    return success

  def createCalibrationCurvesWindow(self):
    # Set up window to be used for displaying data
    self.calibrationCurveChartView = vtk.vtkContextView()
    self.calibrationCurveChartView.GetRenderer().SetBackground(1,1,1)
    self.calibrationCurveChart = vtk.vtkChartXY()
    self.calibrationCurveChartView.GetScene().AddItem(self.calibrationCurveChart)
    
  def showCalibrationCurves(self):
    # Create CALIBRATION mean optical attenuation plot
    self.calibrationCurveDataTable = vtk.vtkTable()
    calibrationNumberOfRows = self.logic.calibrationDataArray.shape[0]

    calibrationDepthArray = vtk.vtkDoubleArray()
    calibrationDepthArray.SetName("Depth (cm)")
    self.calibrationCurveDataTable.AddColumn(calibrationDepthArray)
    calibrationMeanOpticalAttenuationArray = vtk.vtkDoubleArray()
    calibrationMeanOpticalAttenuationArray.SetName("Calibration data (mean optical attenuation, cm^-1)")
    self.calibrationCurveDataTable.AddColumn(calibrationMeanOpticalAttenuationArray)

    self.calibrationCurveDataTable.SetNumberOfRows(calibrationNumberOfRows)
    for rowIndex in xrange(calibrationNumberOfRows):
      self.calibrationCurveDataTable.SetValue(rowIndex, 0, self.logic.calibrationDataArray[rowIndex, 0])
      self.calibrationCurveDataTable.SetValue(rowIndex, 1, self.logic.calibrationDataArray[rowIndex, 1])
      # self.calibrationCurveDataTable.SetValue(rowIndex, 2, self.logic.calibrationDataArray[rowIndex, 2])

    if hasattr(self, 'calibrationMeanOpticalAttenuationLine'):
      self.calibrationCurveChart.RemovePlotInstance(self.calibrationMeanOpticalAttenuationLine)
    self.calibrationMeanOpticalAttenuationLine = self.calibrationCurveChart.AddPlot(vtk.vtkChart.LINE)
    self.calibrationMeanOpticalAttenuationLine.SetInputData(self.calibrationCurveDataTable, 0, 1)
    self.calibrationMeanOpticalAttenuationLine.SetColor(255, 0, 0, 255)
    self.calibrationMeanOpticalAttenuationLine.SetWidth(2.0)

    # Create Pdd plot
    self.pddDataTable = vtk.vtkTable()
    pddNumberOfRows = self.logic.pddDataArray.shape[0]
    pddDepthArray = vtk.vtkDoubleArray()
    pddDepthArray.SetName("Depth (cm)")
    self.pddDataTable.AddColumn(pddDepthArray)
    pddValueArray = vtk.vtkDoubleArray()
    pddValueArray.SetName("PDD (percent depth dose)")
    self.pddDataTable.AddColumn(pddValueArray)

    self.pddDataTable.SetNumberOfRows(pddNumberOfRows)
    for pddDepthCounter in xrange(pddNumberOfRows):
      self.pddDataTable.SetValue(pddDepthCounter, 0, self.logic.pddDataArray[pddDepthCounter, 0])
      self.pddDataTable.SetValue(pddDepthCounter, 1, self.logic.pddDataArray[pddDepthCounter, 1])

    if hasattr(self, 'pddLine'):
      self.calibrationCurveChart.RemovePlotInstance(self.pddLine)
    self.pddLine = self.calibrationCurveChart.AddPlot(vtk.vtkChart.LINE)
    self.pddLine.SetInputData(self.pddDataTable, 0, 1)
    self.pddLine.SetColor(0, 0, 255, 255)
    self.pddLine.SetWidth(2.0)

    # Add aligned curve to the graph
    self.calibrationDataAlignedTable = vtk.vtkTable()
    calibrationDataAlignedNumberOfRows = self.logic.calibrationDataAlignedToDisplayArray.shape[0]
    calibrationDataAlignedDepthArray = vtk.vtkDoubleArray()
    calibrationDataAlignedDepthArray.SetName("Depth (cm)")
    self.calibrationDataAlignedTable.AddColumn(calibrationDataAlignedDepthArray)
    calibrationDataAlignedValueArray = vtk.vtkDoubleArray()
    calibrationDataAlignedValueArray.SetName("Aligned calibration data")
    self.calibrationDataAlignedTable.AddColumn(calibrationDataAlignedValueArray)

    self.calibrationDataAlignedTable.SetNumberOfRows(calibrationDataAlignedNumberOfRows)
    for calibrationDataAlignedDepthCounter in xrange(calibrationDataAlignedNumberOfRows):
      self.calibrationDataAlignedTable.SetValue(calibrationDataAlignedDepthCounter, 0, self.logic.calibrationDataAlignedToDisplayArray[calibrationDataAlignedDepthCounter, 0])
      self.calibrationDataAlignedTable.SetValue(calibrationDataAlignedDepthCounter, 1, self.logic.calibrationDataAlignedToDisplayArray[calibrationDataAlignedDepthCounter, 1])

    if hasattr(self, 'calibrationDataAlignedLine'):
      self.calibrationCurveChart.RemovePlotInstance(self.calibrationDataAlignedLine)
    self.calibrationDataAlignedLine = self.calibrationCurveChart.AddPlot(vtk.vtkChart.LINE)
    self.calibrationDataAlignedLine.SetInputData(self.calibrationDataAlignedTable, 0, 1)
    self.calibrationDataAlignedLine.SetColor(0, 212, 0, 255)
    self.calibrationDataAlignedLine.SetWidth(2.0)

    # # Show chart
    # self.calibrationCurveChart.GetAxis(1).SetTitle('Depth (cm) - select region using right mouse button to be considered for calibration')
    # self.calibrationCurveChart.GetAxis(0).SetTitle('Percent Depth Dose / Optical Attenuation')
    # self.calibrationCurveChart.SetShowLegend(True)
    # self.calibrationCurveChart.SetTitle('PDD vs Calibration data')
    # self.calibrationCurveChartView.GetInteractor().Initialize()
    # self.calibrationCurveChartView.GetRenderWindow().SetSize(800,550)
    # self.calibrationCurveChartView.GetRenderWindow().SetWindowName('PDD vs Calibration data chart')
    # self.calibrationCurveChartView.GetRenderWindow().Start()

  def onAlignCalibrationCurves(self):
    if self.logic.pddDataArray is None or self.logic.pddDataArray.size == 0:
      slicer.util.errorDisplay('PDD data not loaded!')
      return

    # Parse calibration volume (average optical densities along central cylinder)
    success = self.parseCalibrationVolume()
    if not success:
      return

    # Align PDD data and "experimental" (CALIBRATION) data. Allow for horizontal shift
    # and vertical scale (max PDD Y value/max CALIBRATION Y value).
    result = self.logic.alignPddToCalibration()
    
    # Set alignment results to manual controls
    self.step3_1_xTranslationSpinBox.blockSignals(True)
    self.step3_1_xTranslationSpinBox.setValue(result[1])
    self.step3_1_xTranslationSpinBox.blockSignals(False)
    self.step3_1_yScaleSpinBox.blockSignals(True)
    self.step3_1_yScaleSpinBox.setValue(result[2])
    self.step3_1_yScaleSpinBox.blockSignals(False)
    self.step3_1_yTranslationSpinBox.blockSignals(True)
    self.step3_1_yTranslationSpinBox.setValue(result[3])
    self.step3_1_yTranslationSpinBox.blockSignals(False)

    # Show plots
    self.createCalibrationCurvesWindow()
    self.showCalibrationCurves()

  def onAdjustAlignmentValueChanged(self, value):
    self.logic.createAlignedCalibrationArray(self.step3_1_xTranslationSpinBox.value, self.step3_1_yScaleSpinBox.value, self.step3_1_yTranslationSpinBox.value)
    self.showCalibrationCurves()
    
    
  

  def onComputeDoseFromPdd(self):
    try:
      monitorUnitsFloat = float(self.step3_1_monitorUnitsLineEdit.text)
      rdfFloat = float(self.step3_1_rdfLineEdit.text)
    except ValueError:
      slicer.util.errorDisplay('Invalid monitor units or RDF!')
      return

    # Calculate dose information: calculatedDose = (PddDose * MonitorUnits * RDF) / 10000
    if self.logic.computeDoseForMeasuredData(rdfFloat, monitorUnitsFloat) == True:
      self.logic.delayDisplay('Dose successfully calculated from PDD')
    else:
      slicer.util.errorDisplay('Dose calculation from PDD failed!')

  def onShowOpticalAttenuationVsDoseCurve(self):
    # Get selection from PDD vs Calibration chart
    selection = self.pddLine.GetSelection()
    if selection is not None and selection.GetNumberOfTuples() > 0:
      pddRangeMin = self.pddDataTable.GetValue(selection.GetValue(0), 0)
      pddRangeMax = self.pddDataTable.GetValue(selection.GetValue(selection.GetNumberOfTuples()-1), 0)
    else:
      pddRangeMin = -1000
      pddRangeMax = 1000
    logging.info('Selected Pdd range: {0} - {1}'.format(pddRangeMin,pddRangeMax))

    # Create optical attenuation vs dose function
    self.logic.createOpticalAttenuationVsDoseFunction(pddRangeMin, pddRangeMax)

    self.oaVsDoseChartView = vtk.vtkContextView()
    self.oaVsDoseChartView.GetRenderer().SetBackground(1,1,1)
    self.oaVsDoseChart = vtk.vtkChartXY()
    self.oaVsDoseChartView.GetScene().AddItem(self.oaVsDoseChart)

    # Create optical attenuation vs dose plot
    self.oaVsDoseDataTable = vtk.vtkTable()
    oaVsDoseNumberOfRows = self.logic.opticalAttenuationVsDoseFunction.shape[0]

    opticalAttenuationArray = vtk.vtkDoubleArray()
    opticalAttenuationArray.SetName("Optical attenuation (cm^-1)")
    self.oaVsDoseDataTable.AddColumn(opticalAttenuationArray)
    doseArray = vtk.vtkDoubleArray()
    doseArray.SetName("Dose (GY)")
    self.oaVsDoseDataTable.AddColumn(doseArray)

    self.oaVsDoseDataTable.SetNumberOfRows(oaVsDoseNumberOfRows)
    for rowIndex in xrange(oaVsDoseNumberOfRows):
      self.oaVsDoseDataTable.SetValue(rowIndex, 0, self.logic.opticalAttenuationVsDoseFunction[rowIndex, 0])
      self.oaVsDoseDataTable.SetValue(rowIndex, 1, self.logic.opticalAttenuationVsDoseFunction[rowIndex, 1])

    self.oaVsDoseLinePoint = self.oaVsDoseChart.AddPlot(vtk.vtkChart.POINTS)
    self.oaVsDoseLinePoint.SetInputData(self.oaVsDoseDataTable, 0, 1)
    self.oaVsDoseLinePoint.SetColor(0, 0, 255, 255)
    self.oaVsDoseLinePoint.SetMarkerSize(10)
    self.oaVsDoseLineInnerPoint = self.oaVsDoseChart.AddPlot(vtk.vtkChart.POINTS)
    self.oaVsDoseLineInnerPoint.SetInputData(self.oaVsDoseDataTable, 0, 1)
    self.oaVsDoseLineInnerPoint.SetColor(255, 255, 255, 223)
    self.oaVsDoseLineInnerPoint.SetMarkerSize(8)

    # Show chart
    self.oaVsDoseChart.GetAxis(1).SetTitle('Optical attenuation (cm^-1)')
    self.oaVsDoseChart.GetAxis(0).SetTitle('Dose (GY)')
    self.oaVsDoseChart.SetTitle('Optical attenuation vs Dose')
    self.oaVsDoseChartView.GetInteractor().Initialize()
    self.oaVsDoseChartView.GetRenderWindow().SetSize(800,550)
    self.oaVsDoseChartView.GetRenderWindow().SetWindowName('Optical attenuation vs Dose chart')
    self.oaVsDoseChartView.GetRenderWindow().Start()

  def onRemoveSelectedPointsFromOpticalAttenuationVsDoseCurve(self):
    outlierSelection = self.oaVsDoseLineInnerPoint.GetSelection()
    if outlierSelection is None:
      outlierSelection = self.oaVsDoseLinePoint.GetSelection()
    if outlierSelection is not None and outlierSelection.GetNumberOfTuples() > 0:
      # Get outlier indices in descending order
      outlierIndices = []
      for outlierSelectionIndex in xrange(outlierSelection.GetNumberOfTuples()):
        outlierIndex = outlierSelection.GetValue(outlierSelectionIndex)
        outlierIndices.append(outlierIndex)
      outlierIndices.sort()
      outlierIndices.reverse()
      for outlierIndex in outlierIndices:
        self.oaVsDoseDataTable.RemoveRow(outlierIndex)
        self.logic.opticalAttenuationVsDoseFunction = numpy.delete(self.logic.opticalAttenuationVsDoseFunction, outlierIndex, 0)

      # De-select former points
      emptySelectionArray = vtk.vtkIdTypeArray()
      self.oaVsDoseLinePoint.SetSelection(emptySelectionArray)
      self.oaVsDoseLineInnerPoint.SetSelection(emptySelectionArray)
      if hasattr(self, 'polynomialLine') and self.polynomialLine is not None:
        self.polynomialLine.SetSelection(emptySelectionArray)
      # Update chart view
      self.oaVsDoseDataTable.Modified()
      self.oaVsDoseChartView.Render()
    
  def onFitPolynomialToOpticalAttenuationVsDoseCurve(self):
    orderSelectionComboboxCurrentIndex = self.step3_1_selectOrderOfPolynomialFitButton.currentIndex
    maxOrder = int(self.step3_1_selectOrderOfPolynomialFitButton.itemText(orderSelectionComboboxCurrentIndex))
    residuals = self.logic.fitCurveToOpticalAttenuationVsDoseFunctionArray(maxOrder)
    p = self.logic.calibrationPolynomialCoefficients

    # Clear line edits
    for order in xrange(5):
      exec("self.step3_2_calibrationFunctionOrder{0}LineEdit.text = ''".format(order))
    # Show polynomial on GUI (highest order first in the coefficients list)
    for orderIndex in xrange(maxOrder+1):
      order = maxOrder-orderIndex
      exec("self.step3_2_calibrationFunctionOrder{0}LineEdit.text = {1:.6f}".format(order,p[orderIndex]))
    # Show residuals
    self.step3_1_fitPolynomialResidualsLabel.text = "Residuals of the least-squares fit of the polynomial: {0:.3f}".format(residuals[0])

    # Compute points to display for the fitted polynomial
    oaVsDoseNumberOfRows = self.logic.opticalAttenuationVsDoseFunction.shape[0]
    minOA = self.logic.opticalAttenuationVsDoseFunction[0, 0]
    maxOA = self.logic.opticalAttenuationVsDoseFunction[oaVsDoseNumberOfRows-1, 0]
    minPolynomial = minOA - (maxOA-minOA)*0.2
    maxPolynomial = maxOA + (maxOA-minOA)*0.2

    # Create table to display polynomial
    self.polynomialTable = vtk.vtkTable()
    polynomialXArray = vtk.vtkDoubleArray()
    polynomialXArray.SetName("X")
    self.polynomialTable.AddColumn(polynomialXArray)
    polynomialYArray = vtk.vtkDoubleArray()
    polynomialYArray.SetName("Y")
    self.polynomialTable.AddColumn(polynomialYArray)
    # The displayed polynomial is 4 times as dense as the OA VS dose curve
    polynomialNumberOfRows = oaVsDoseNumberOfRows * 4
    self.polynomialTable.SetNumberOfRows(polynomialNumberOfRows)
    for rowIndex in xrange(polynomialNumberOfRows):
      x = minPolynomial + (maxPolynomial-minPolynomial)*rowIndex/polynomialNumberOfRows
      self.polynomialTable.SetValue(rowIndex, 0, x)
      y = 0
      # Highest order first in the coefficients list
      for orderIndex in xrange(maxOrder+1):
        y += p[orderIndex] * x ** (maxOrder-orderIndex)
      self.polynomialTable.SetValue(rowIndex, 1, y)

    if hasattr(self, 'polynomialLine') and self.polynomialLine is not None:
      self.oaVsDoseChart.RemovePlotInstance(self.polynomialLine)

    self.polynomialLine = self.oaVsDoseChart.AddPlot(vtk.vtkChart.LINE)
    self.polynomialLine.SetInputData(self.polynomialTable, 0, 1)
    self.polynomialLine.SetColor(192, 0, 0, 255)
    self.polynomialLine.SetWidth(2)

  def setCalibrationFunctionCoefficientsToLogic(self):
    # Determine the number of orders based on the input fields
    maxOrder = 0
    for order in xrange(5):
      exec("lineEditText = self.step3_2_calibrationFunctionOrder{0}LineEdit.text".format(order))
      try:
        coefficient = float(lineEditText)
        if coefficient != 0:
          maxOrder = order
      except:
        pass
    # Initialize all coefficients to zero in the coefficients list
    self.logic.calibrationPolynomialCoefficients = numpy.zeros(maxOrder+1)
    for order in xrange(maxOrder+1):
      exec("lineEditText = self.step3_2_calibrationFunctionOrder{0}LineEdit.text".format(order))
      try:
        self.logic.calibrationPolynomialCoefficients[maxOrder-order] = float(lineEditText)
      except:
        pass

  def onExportCalibration(self):
    # Set calibration polynomial coefficients from input fields to logic
    self.setCalibrationFunctionCoefficientsToLogic()

    # Export
    result = self.logic.exportCalibrationToCSV()
    qt.QMessageBox.information(None, 'Calibration values exported', result)

  def onApplyCalibration(self):
    # Set calibration polynomial coefficients from input fields to logic
    self.setCalibrationFunctionCoefficientsToLogic()

    # Perform calibration
    self.calibratedMeasuredVolumeNode = self.logic.calibrate(self.measuredVolumeNode.GetID())
    if self.calibratedMeasuredVolumeNode is not None:
      self.step3_2_applyCalibrationStatusLabel.setText('Calibration successfully performed')
    else:
      self.step3_2_applyCalibrationStatusLabel.setText('Calibration failed!')
      return

    # Show calibrated volume
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(self.planDoseVolumeNode.GetID())
    selectionNode.SetSecondaryVolumeID(self.calibratedMeasuredVolumeNode.GetID())
    appLogic.PropagateVolumeSelection() 

    # Set window/level options for the calibrated dose
    if self.logic.opticalAttenuationVsDoseFunction is not None:
      calibratedVolumeDisplayNode = self.calibratedMeasuredVolumeNode.GetDisplayNode()
      oaVsDoseNumberOfRows = self.logic.opticalAttenuationVsDoseFunction.shape[0]
      minDose = self.logic.opticalAttenuationVsDoseFunction[0, 1]
      maxDose = self.logic.opticalAttenuationVsDoseFunction[oaVsDoseNumberOfRows-1, 1]
      minWindowLevel = minDose - (maxDose-minDose)*0.2
      maxWindowLevel = maxDose + (maxDose-minDose)*0.2
      calibratedVolumeDisplayNode.AutoWindowLevelOff();
      calibratedVolumeDisplayNode.SetWindowLevelMinMax(minWindowLevel, maxWindowLevel);

    # Set calibrated dose to dose comparison step input
    self.refreshDoseComparisonInfoLabel()
    
  def refreshDoseComparisonInfoLabel(self):
    if self.planDoseVolumeNode is None:
      self.step4_doseComparisonReferenceVolumeLabel.text = 'Invalid plan dose volume!'
    else:
      self.step4_doseComparisonReferenceVolumeLabel.text = self.planDoseVolumeNode.GetName()
    if self.calibratedMeasuredVolumeNode is None:
      self.step4_doseComparisonEvaluatedVolumeLabel.text = 'Invalid calibrated gel dosimeter volume!'
    else:
      self.step4_doseComparisonEvaluatedVolumeLabel.text = self.calibratedMeasuredVolumeNode.GetName()

  def onStep4_DoseComparisonSelected(self, collapsed):
    # Initialize mask segmentation selector to select plan structures
    #self.step4_maskSegmentationSelector.setCurrentNode(self.planStructuresNode) 
    #self.onStep4_MaskSegmentationSelectionChanged(self.planStructuresNode)   
    # Turn scalar bar on/off
    if collapsed == False:
      self.sliceAnnotations.scalarBarEnabled = 1
    else:
      self.sliceAnnotations.scalarBarEnabled = 0
    self.sliceAnnotations.updateSliceViewFromGUI()
    # Reset 3D view
    self.layoutWidget.layoutManager().threeDWidget(0).threeDView().resetFocalPoint()

  def onStep4_MaskSegmentationSelectionChanged(self, node):
    # Hide previously selected mask segmentation
    if self.maskSegmentationNode is not None:
      self.maskSegmentationNode.GetDisplayNode().SetVisibility(0)
    # Set new mask segmentation
    self.maskSegmentationNode = node
    #self.onStep4_MaskSegmentSelectionChanged(self.step4_maskSegmentationSelector.currentSegmentID()) #
    # Show new mask segmentation
    if self.maskSegmentationNode is not None:
      self.maskSegmentationNode.GetDisplayNode().SetVisibility(1)

  def onStep4_MaskSegmentSelectionChanged(self, segmentID):
    if self.maskSegmentationNode is None:
      return
    # Set new mask segment
    self.maskSegmentID = segmentID
    # Show new mask segment
    if self.maskSegmentID is not None and self.maskSegmentID != '':
      # Hide other segments
      import vtkSegmentationCore
      segmentIDs = vtk.vtkStringArray()
      self.maskSegmentationNode.GetSegmentation().GetSegmentIDs(segmentIDs)
      for segmentIndex in xrange(0,segmentIDs.GetNumberOfValues()):
        currentSegmentID = segmentIDs.GetValue(segmentIndex)
        self.maskSegmentationNode.GetDisplayNode().SetSegmentVisibility(currentSegmentID, False)
      # Show only selected segment, make it semi-transparent
      self.maskSegmentationNode.GetDisplayNode().SetSegmentVisibility(self.maskSegmentID, True)
      self.maskSegmentationNode.GetDisplayNode().SetSegmentPolyDataOpacity(self.maskSegmentID, 0.5)
    
  def onUseMaximumDoseRadioButtonToggled(self, toggled):
    self.step4_1_referenceDoseCustomValueCGySpinBox.setEnabled(not toggled)

  def onGammaDoseComparison(self):
    try:
      slicer.modules.dosecomparison
      import vtkSlicerDoseComparisonModuleLogic

      if self.step4_1_gammaVolumeSelector.currentNode() is None:
        qt.QMessageBox.warning(None, 'Warning', 'Gamma volume not selected. If there is no suitable output gamma volume, create one.')
        return
      else:
        self.gammaVolumeNode = self.step4_1_gammaVolumeSelector.currentNode()

      # Set up gamma computation parameters
      self.gammaParameterSetNode = vtkSlicerDoseComparisonModuleLogic.vtkMRMLDoseComparisonNode()
      slicer.mrmlScene.AddNode(self.gammaParameterSetNode)
      self.gammaParameterSetNode.SetAndObserveReferenceDoseVolumeNode(self.planDoseVolumeNode)
      self.gammaParameterSetNode.SetAndObserveCompareDoseVolumeNode(self.calibratedMeasuredVolumeNode)
      self.gammaParameterSetNode.SetAndObserveMaskSegmentationNode(self.maskSegmentationNode)
      if self.maskSegmentID is not None and self.maskSegmentID != '':
        self.gammaParameterSetNode.SetMaskSegmentID(self.maskSegmentID)
      self.gammaParameterSetNode.SetAndObserveGammaVolumeNode(self.gammaVolumeNode)
      self.gammaParameterSetNode.SetDtaDistanceToleranceMm(self.step4_1_dtaDistanceToleranceMmSpinBox.value)
      self.gammaParameterSetNode.SetDoseDifferenceTolerancePercent(self.step1_doseToImageIntegerSpinbox.value)
      #self.gammaParameterSetNode.SetUseMaximumDose(self.step4_1_referenceDoseUseMaximumDoseRadioButton.isChecked()) 
      self.gammaParameterSetNode.SetUseLinearInterpolation(self.step4_1_useLinearInterpolationCheckBox.isChecked())
      self.gammaParameterSetNode.SetReferenceDoseGy(self.step4_1_referenceDoseCustomValueCGySpinBox.value / 100.0)
      self.gammaParameterSetNode.SetAnalysisThresholdPercent(self.step4_1_analysisThresholdPercentSpinBox.value)
      self.gammaParameterSetNode.SetDoseThresholdOnReferenceOnly(True)
      self.gammaParameterSetNode.SetMaximumGamma(self.step4_1_maximumGammaSpinBox.value)

      # Create progress bar
      from vtkSlicerRtCommon import SlicerRtCommon
      doseComparisonLogic = slicer.modules.dosecomparison.logic()
      self.addObserver(doseComparisonLogic, SlicerRtCommon.ProgressUpdated, self.onGammaProgressUpdated)
      self.gammaProgressDialog = qt.QProgressDialog(self.parent)
      self.gammaProgressDialog.setModal(True)
      self.gammaProgressDialog.setMinimumDuration(150)
      self.gammaProgressDialog.labelText = "Computing gamma dose difference..."
      self.gammaProgressDialog.show()
      slicer.app.processEvents()
      
      # Perform gamma comparison
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      doseComparisonLogic.SetAndObserveDoseComparisonNode(self.gammaParameterSetNode)
      errorMessage = doseComparisonLogic.ComputeGammaDoseDifference()
      
      self.gammaProgressDialog.hide()
      self.gammaProgressDialog = None
      self.removeObserver(doseComparisonLogic, SlicerRtCommon.ProgressUpdated, self.onGammaProgressUpdated)
      qt.QApplication.restoreOverrideCursor()

      if self.gammaParameterSetNode.GetResultsValid():
        self.step4_1_gammaStatusLabel.setText('Gamma dose comparison succeeded\nPass fraction: {0:.2f}%'.format(self.gammaParameterSetNode.GetPassFractionPercent()))
        self.step4_1_showGammaReportButton.enabled = True
        self.gammaReport = self.gammaParameterSetNode.GetReportString()
      else:
        self.step4_1_gammaStatusLabel.setText(errorMessage)
        self.step4_1_showGammaReportButton.enabled = False

      # Show gamma volume
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      selectionNode.SetActiveVolumeID(self.step4_1_gammaVolumeSelector.currentNodeID)
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()

      # Show mask structure with some transparency
      if self.maskSegmentationNode:
        self.maskSegmentationNode.GetDisplayNode().SetVisibility(1)
        if self.maskSegmentID:
          self.maskSegmentationNode.GetDisplayNode().SetSegmentVisibility(self.maskSegmentID, True)
          self.maskSegmentationNode.GetDisplayNode().SetSegmentPolyDataOpacity(self.maskSegmentID, 0.5)

      # Show gamma slice in 3D view
      layoutManager = self.layoutWidget.layoutManager()
      sliceViewerWidgetRed = layoutManager.sliceWidget('Red')
      sliceLogicRed = sliceViewerWidgetRed.sliceLogic()
      sliceLogicRed.StartSliceNodeInteraction(slicer.vtkMRMLSliceNode.SliceVisibleFlag)
      sliceLogicRed.GetSliceNode().SetSliceVisible(1)
      sliceLogicRed.EndSliceNodeInteraction()

      # Set gamma window/level
      maximumGamma = self.step4_1_maximumGammaSpinBox.value
      gammaDisplayNode = self.gammaVolumeNode.GetDisplayNode()
      gammaDisplayNode.AutoWindowLevelOff()
      gammaDisplayNode.SetWindowLevel(maximumGamma/2, maximumGamma/2)
      gammaDisplayNode.ApplyThresholdOn()
      gammaDisplayNode.AutoThresholdOff()
      gammaDisplayNode.SetLowerThreshold(0.001)

      # Center 3D view
      layoutManager = self.layoutWidget.layoutManager()
      threeDWidget = layoutManager.threeDWidget(0)
      if threeDWidget is not None and threeDWidget.threeDView() is not None:
        threeDWidget.threeDView().resetFocalPoint()
      
    except Exception, e:
      import traceback
      traceback.print_exc()
      logging.error('Failed to perform gamma dose comparison!')

  def onGammaProgressUpdated(self, logic, event):
    if self.gammaProgressDialog:
      self.gammaProgressDialog.value = logic.GetProgress() * 100.0
      slicer.app.processEvents()

  def onShowGammaReport(self):
    if hasattr(self,"gammaReport"):
      qt.QMessageBox.information(None, 'Gamma computation report', self.gammaReport)
    else:
      qt.QMessageBox.information(None, 'Gamma computation report missing', 'No report available!')
    
  def onStepT1_LineProfileSelected(self, collapsed):
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

    # Show dose volumes
    if self.planDoseVolumeNode:
      selectionNode.SetActiveVolumeID(self.planDoseVolumeNode.GetID())
    if self.calibratedMeasuredVolumeNode:
      selectionNode.SetSecondaryVolumeID(self.calibratedMeasuredVolumeNode.GetID())
    appLogic = slicer.app.applicationLogic()
    appLogic.PropagateVolumeSelection()

  def onCreateLineProfileButton(self):
    # Create array nodes for the results
    if not hasattr(self, 'planDoseLineProfileArrayNode'):
      self.planDoseLineProfileArrayNode = slicer.vtkMRMLDoubleArrayNode()
      slicer.mrmlScene.AddNode(self.planDoseLineProfileArrayNode)
    if not hasattr(self, 'calibratedMeasuredDoseLineProfileArrayNode'):
      self.calibratedMeasuredDoseLineProfileArrayNode = slicer.vtkMRMLDoubleArrayNode()
      slicer.mrmlScene.AddNode(self.calibratedMeasuredDoseLineProfileArrayNode)
    if self.gammaVolumeNode and not hasattr(self, 'gammaLineProfileArrayNode'):
      self.gammaLineProfileArrayNode = slicer.vtkMRMLDoubleArrayNode()
      slicer.mrmlScene.AddNode(self.gammaLineProfileArrayNode)

    lineProfileLogic = FilmDosimetryAnalysisLogic.LineProfileLogic()
    lineResolutionMm = float(self.stepT1_lineResolutionMmSliderWidget.value)
    selectedRuler = self.stepT1_inputRulerSelector.currentNode()
    rulerLengthMm = lineProfileLogic.computeRulerLength(selectedRuler)
    numberOfLineSamples = int( (rulerLengthMm / lineResolutionMm) + 0.5 )

    # Get number of samples based on selected sampling density
    if self.planDoseVolumeNode:
      lineProfileLogic.run(self.planDoseVolumeNode, selectedRuler, self.planDoseLineProfileArrayNode, numberOfLineSamples)
    if self.calibratedMeasuredVolumeNode:
      lineProfileLogic.run(self.calibratedMeasuredVolumeNode, selectedRuler, self.calibratedMeasuredDoseLineProfileArrayNode, numberOfLineSamples)
    if self.gammaVolumeNode:
      lineProfileLogic.run(self.gammaVolumeNode, selectedRuler, self.gammaLineProfileArrayNode, numberOfLineSamples)

  def onSelectLineProfileParameters(self):
    self.stepT1_createLineProfileButton.enabled = self.planDoseVolumeNode and self.measuredVolumeNode and self.stepT1_inputRulerSelector.currentNode()

  def onExportLineProfiles(self):
    import csv
    import os

    self.outputDir = slicer.app.temporaryPath + '/FilmDosimetry'
    if not os.access(self.outputDir, os.F_OK):
      os.mkdir(self.outputDir)
    if not hasattr(self, 'planDoseLineProfileArrayNode') and not hasattr(self, 'calibratedMeasuredDoseLineProfileArrayNode'):
      return 'Dose line profiles not computed yet!\nClick Create line profile\n'

    # Assemble file name for calibration curve points file
    from time import gmtime, strftime
    fileName = self.outputDir + '/' + strftime("%Y%m%d_%H%M%S_", gmtime()) + 'LineProfiles.csv'

    # Write calibration curve points CSV file
    with open(fileName, 'w') as fp:
      csvWriter = csv.writer(fp, delimiter=',', lineterminator='\n')

      planDoseLineProfileArray = self.planDoseLineProfileArrayNode.GetArray()
      calibratedDoseLineProfileArray = self.calibratedMeasuredDoseLineProfileArrayNode.GetArray()
      gammaLineProfileArray = None
      if hasattr(self, 'gammaLineProfileArrayNode'):
        data = [['PlanDose','CalibratedMeasuredDose','Gamma']]
        gammaLineProfileArray = self.gammaLineProfileArrayNode.GetArray()
      else:
        data = [['PlanDose','CalibratedMeasuredDose']]

      numOfSamples = planDoseLineProfileArray.GetNumberOfTuples()
      for index in xrange(numOfSamples):
        planDoseSample = planDoseLineProfileArray.GetTuple(index)[1]
        calibratedDoseSample = calibratedDoseLineProfileArray.GetTuple(index)[1]
        if gammaLineProfileArray:
          gammaSample = gammaLineProfileArray.GetTuple(index)[1]
          samples = [planDoseSample, calibratedDoseSample, gammaSample]
        else:
          samples = [planDoseSample, calibratedDoseSample]
        data.append(samples)
      csvWriter.writerows(data)

    message = 'Dose line profiles saved in file\n' + fileName + '\n\n'
    qt.QMessageBox.information(None, 'Line profiles values exported', message)

  #
  # -------------------------
  # Testing related functions
  # -------------------------
  #
  def onSelfTestButtonClicked(self):
    #TODO_ForTesting: Choose the testing method here
    self.performSelfTestFromScratch()
    # self.performSelfTestFromSavedScene()

  def performSelfTestFromScratch(self):
    ### 1. Load test data
    self.mode = 'Clinical'
    self.step1_loadDataCollapsibleButton.setChecked(True)
    planCtSeriesInstanceUid = '1.2.246.352.71.2.1706542068.3448830.20131009141316'
    obiSeriesInstanceUid = '1.2.246.352.61.2.5257103442752107062.11507227178299854732'
    planDoseSeriesInstanceUid = '1.2.246.352.71.2.876365306.7756.20140123124241'
    structureSetSeriesInstanceUid = '1.2.246.352.71.2.876365306.7755.20140122163851'
    seriesUIDList = [planCtSeriesInstanceUid, obiSeriesInstanceUid, planDoseSeriesInstanceUid, structureSetSeriesInstanceUid]
    dicomWidget = slicer.modules.dicom.widgetRepresentation().self()
    dicomWidget.detailsPopup.offerLoadables(seriesUIDList, 'SeriesUIDList')
    dicomWidget.detailsPopup.examineForLoading()
    dicomWidget.detailsPopup.loadCheckedLoadables()

    slicer.app.processEvents()
    self.logic.delayDisplay('Wait for the slicelet to catch up', 300)

    # Load non-DICOM data
    slicer.util.loadNodeFromFile('d:/devel/_Images/RT/20140123_FilmDosimetry_StructureSetIncluded/VFFs/LCV01_HR_plan.vff', 'VffFile', {})
    slicer.util.loadNodeFromFile('d:/devel/_Images/RT/20140123_FilmDosimetry_StructureSetIncluded/VFFs/LCV02_HR_calib.vff', 'VffFile', {})

    # Assign roles
    planCTVolumeName = '47: ARIA RadOnc Images - Verification Plan Phantom'
    planDoseVolumeName = '53: RTDOSE: Eclipse Doses: VMAT XM1 LCV'
    obiVolumeName = '0: Unknown'
    structureSetNodeName = '52: RTSTRUCT: CT_1'
    measuredVolumeName = 'lcv01_hr.vff'
    #calibrationVolumeName = 'lcv02_hr.vff'

    planCTVolume = slicer.util.getNode(planCTVolumeName)
    self.doseToImageFilmSelector.setCurrentNode(planCTVolume)
    planDoseVolume = slicer.util.getNode(planDoseVolumeName)
    self.step1_floodFieldImageSelectorComboBox.setCurrentNode(planDoseVolume)
    obiVolume = slicer.util.getNode(obiVolumeName)
    self.obiSelector.setCurrentNode(obiVolume)
    structureSetNode = slicer.util.getNode(structureSetNodeName)
    self.planStructuresSelector.setCurrentNode(structureSetNode)
    measuredVolume = slicer.util.getNode(measuredVolumeName)
    self.measuredVolumeSelector.setCurrentNode(measuredVolume)
    #calibrationVolume = slicer.util.getNode(calibrationVolumeName)
    self.numberOfCalibrationFilmsSelector.setCurrentNode(calibrationVolume)
    slicer.app.processEvents()

    ### 2. Register
    self.testButton.setChecked(True)
    self.onObiToPlanCTRegistration()
    slicer.app.processEvents()

    # Select fiducials
    #self.step1_2_doseToFilmCollapsibleButton.setChecked(True) 
    # obiFiducialsNode = slicer.util.getNode(self.obiMarkupsFiducialNodeName)
    # obiFiducialsNode.AddFiducial(76.4, 132.1, -44.8)
    # obiFiducialsNode.AddFiducial(173, 118.4, -44.8)
    # obiFiducialsNode.AddFiducial(154.9, 163.5, -44.8)
    # obiFiducialsNode.AddFiducial(77.4, 133.6, 23.9)
    # obiFiducialsNode.AddFiducial(172.6, 118.9, 23.9)
    # obiFiducialsNode.AddFiducial(166.5, 151.3, 23.9)
    # self.step2_2_2_measuredFiducialSelectionCollapsibleButton.setChecked(True)
    # measuredFiducialsNode = slicer.util.getNode(self.measuredMarkupsFiducialNodeName)
    # measuredFiducialsNode.AddFiducial(-92.25, -25.9, 26.2)
    # measuredFiducialsNode.AddFiducial(-31.9, -100.8, 26.2)
    # measuredFiducialsNode.AddFiducial(-15, -55.2, 26.2)
    # measuredFiducialsNode.AddFiducial(-92, -26.7, 94)
    # measuredFiducialsNode.AddFiducial(-32.7, -101, 94)
    # measuredFiducialsNode.AddFiducial(-15, -73.6, 94)

    # Perform fiducial registration
    self.step2_2_3_measuredToObiRegistrationCollapsibleButton.setChecked(True)
    self.onMeasuredToObiRegistration()

    # ### 4. Calibration
    # self.step3_doseCalibrationCollapsibleButton.setChecked(True)
    # self.logic.loadPdd('d:/devel/_Images/RT/20140123_FilmDosimetry_StructureSetIncluded/12MeV.csv')

    # # Parse calibration volume
    # self.step3_1_radiusMmFromCentrePixelLineEdit.setText('5')

    # # Align calibration curves
    # self.onAlignCalibrationCurves()
    # self.step3_1_xTranslationSpinBox.setValue(1)
    # self.step3_1_yScaleSpinBox.setValue(1.162)
    # self.step3_1_yTranslationSpinBox.setValue(1.28)

    # # Generate dose information
    # self.step3_doseCalibrationCollapsibleButton.setChecked(True)
    # self.step3_1_rdfLineEdit.setText('0.989')
    # self.step3_1_monitorUnitsLineEdit.setText('1850')
    # self.onComputeDoseFromPdd()
    # # Show optical attenuation VS dose curve
    # self.step3_1_calibrationRoutineCollapsibleButton.setChecked(True)
    # self.onShowOpticalAttenuationVsDoseCurve()
    # # Fit polynomial on OA VS dose curve
    # self.onFitPolynomialToOpticalAttenuationVsDoseCurve()
    # # Calibrate
    # self.onApplyCalibration()

    # # 5. Dose comparison
    # slicer.app.processEvents()
    # self.logic.delayDisplay('Wait for the slicelet to catch up', 300)
    # self.step4_doseComparisonCollapsibleButton.setChecked(True)
    # self.step4_1_gammaVolumeSelector.addNode()
    # maskSegmentationNodeID = 'vtkMRMLSegmentationNode1'
    # maskSegmentID = 'Jar_crop'
    # self.step4_maskSegmentationSelector.setCurrentNodeID(maskSegmentationNodeID)
    # self.step4_maskSegmentationSelector.setCurrentSegmentID(maskSegmentID)
    # self.onGammaDoseComparison()

  def performSelfTestFromSavedScene(self):
    #TODO: Update saved scene to one with segmentations
    return
    # Set variables. Only this section needs to be changed when testing new dataset
    scenePath = 'c:/Slicer_Data/20140820_FilmDosimetry_StructureSetIncluded/2014-08-20-Scene.mrml'
    planCtVolumeNodeName = '*ARIA RadOnc Images - Verification Plan Phantom'
    obiVolumeNodeName = '0: Unknown'
    planDoseVolumeNodeName = '53: RTDOSE: Eclipse Doses: '
    planStructuresNodeName = '52: RTSTRUCT: CT_1'
    measuredVolumeNodeName = 'lcv01_hr.vff'
    calibrationVolumeNodeName = 'lcv02_hr.vff'
    radiusMmFromCentrePixelMm = '5'
    pddFileName = 'd:/devel/_Images/RT/20140123_FilmDosimetry_StructureSetIncluded/12MeV.csv'
    rdf = '0.989'
    monitorUnits = '1850'
    maskSegmentationNodeID = 'vtkMRMLSegmentationNode1'
    maskSegmentID = 'Jar_crop'
    xTranslationSpinBoxValue = 1
    yScaleSpinBoxValue = 1.162
    yTranslationSpinBoxValue = 1.28
    
    # Start test
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    # Load scene
    slicer.util.loadScene(scenePath)

    # Set member variables for the loaded scene
    self.mode = 'Clinical'
    self.planCtVolumeNode = slicer.util.getNode(planCtVolumeNodeName)
    self.obiVolumeNode = slicer.util.getNode(obiVolumeNodeName)
    self.planDoseVolumeNode = slicer.util.getNode(planDoseVolumeNodeName)
    self.planStructuresNode = slicer.util.getNode(planStructuresNodeName)
    self.planStructuresNode.GetDisplayNode().SetVisibility(0)
    self.measuredVolumeNode = slicer.util.getNode(measuredVolumeNodeName)
    self.calibrationVolumeNode = slicer.util.getNode(calibrationVolumeNodeName)

    # Calibration
    self.logic.loadPdd(pddFileName)

    self.step3_1_radiusMmFromCentrePixelLineEdit.setText(radiusMmFromCentrePixelMm)

    self.onAlignCalibrationCurves()
    self.step3_1_xTranslationSpinBox.setValue(xTranslationSpinBoxValue)
    self.step3_1_yScaleSpinBox.setValue(yScaleSpinBoxValue)
    self.step3_1_yTranslationSpinBox.setValue(yTranslationSpinBoxValue)

    self.step3_1_rdfLineEdit.setText(rdf)
    self.step3_1_monitorUnitsLineEdit.setText(monitorUnits)
    self.onComputeDoseFromPdd()

    self.onShowOpticalAttenuationVsDoseCurve()
    self.onFitPolynomialToOpticalAttenuationVsDoseCurve()

    slicer.app.processEvents()
    self.onApplyCalibration()

    self.step3_doseCalibrationCollapsibleButton.setChecked(True)
    #self.step3_1_calibrationRoutineCollapsibleButton.setChecked(True)

    # Dose comparison
    self.step4_doseComparisonCollapsibleButton.setChecked(True)
    self.step4_1_gammaVolumeSelector.addNode()
    #self.step4_maskSegmentationSelector.setCurrentNodeID(maskSegmentationNodeID) 
    #self.step4_maskSegmentationSelector.setCurrentSegmentID(maskSegmentID)  
    self.onGammaDoseComparison()
    
    qt.QApplication.restoreOverrideCursor()

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
