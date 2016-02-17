import os
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
    self.step2_registrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step3_doseCalibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step4_doseComparisonCollapsibleButton = ctk.ctkCollapsibleButton()
    self.stepT1_lineProfileCollapsibleButton = ctk.ctkCollapsibleButton()

    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.step0_layoutSelectionCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step1_loadDataCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step2_registrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step3_doseCalibrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step4_doseComparisonCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.stepT1_lineProfileCollapsibleButton)

    self.step0_layoutSelectionCollapsibleButton.setProperty('collapsed', False)
    
    # Create module logic
    print('ZZZ 1')#TODO:
    self.logic = FilmDosimetryAnalysisLogic.FilmDosimetryAnalysisLogic()
    print('ZZZ 2')#TODO:

    # Set up constants
    self.obiMarkupsFiducialNodeName = "OBI fiducials"
    self.measuredMarkupsFiducialNodeName = "MEASURED fiducials"
	
    # Declare member variables (selected at certain steps and then from then on for the workflow)
    self.mode = None

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
    self.obiMarkupsFiducialNode = slicer.util.getNode(self.obiMarkupsFiducialNodeName)
    if self.obiMarkupsFiducialNode is None:
      obiFiducialsNodeId = self.markupsLogic.AddNewFiducialNode(self.obiMarkupsFiducialNodeName)
      self.obiMarkupsFiducialNode = slicer.mrmlScene.GetNodeByID(obiFiducialsNodeId)
    self.measuredMarkupsFiducialNode = slicer.util.getNode(self.measuredMarkupsFiducialNodeName)
    if self.measuredMarkupsFiducialNode is None:
      measuredFiducialsNodeId = self.markupsLogic.AddNewFiducialNode(self.measuredMarkupsFiducialNodeName)
      self.measuredMarkupsFiducialNode = slicer.mrmlScene.GetNodeByID(measuredFiducialsNodeId)
    measuredFiducialsDisplayNode = self.measuredMarkupsFiducialNode.GetDisplayNode()
    measuredFiducialsDisplayNode.SetSelectedColor(0, 0.9, 0)

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
    self.setup_Step2_Registration()
    self.setup_step3_DoseCalibration()
    self.setup_Step4_DoseComparison()
    self.setup_StepT1_lineProfileCollapsibleButton()

    if widgetClass:
      self.widget = widgetClass(self.parent)
    self.parent.show()

  # Disconnect all connections made to the slicelet to enable the garbage collector to destruct the slicelet object on quit
  def disconnect(self):
    self.selfTestButton.disconnect('clicked()', self.onSelfTestButtonClicked)
    self.step0_viewSelectorComboBox.disconnect('activated(int)', self.onViewSelect)
    self.step0_clinicalModeRadioButton.disconnect('toggled(bool)', self.onClinicalModeSelect)
    self.step0_preclinicalModeRadioButton.disconnect('toggled(bool)', self.onPreclinicalModeSelect)
    self.step1_showDicomBrowserButton.disconnect('clicked()', self.logic.onDicomLoad)
    self.step2_1_registerObiToPlanCtButton.disconnect('clicked()', self.onObiToPlanCTRegistration)
    self.step2_1_translationSliders.disconnect('valuesChanged()', self.step2_1_rotationSliders.resetUnactiveSliders())
    self.step2_2_measuredDoseToObiRegistrationCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_2_MeasuredDoseToObiRegistrationSelected)
    self.step2_2_1_obiFiducialSelectionCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_2_1_ObiFiducialCollectionSelected)
    self.step2_2_2_measuredFiducialSelectionCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_2_2_MeasuredFiducialCollectionSelected)
    self.step1_loadNonDicomDataButton.disconnect('clicked()', self.onLoadNonDicomData)
    self.step2_2_3_registerMeasuredToObiButton.disconnect('clicked()', self.onMeasuredToObiRegistration)
    self.step3_1_pddLoadDataButton.disconnect('clicked()', self.onLoadPddDataRead)
    self.step3_1_alignCalibrationCurvesButton.disconnect('clicked()', self.onAlignCalibrationCurves)
    self.step3_1_xTranslationSpinBox.disconnect('valueChanged(double)', self.onAdjustAlignmentValueChanged)
    self.step3_1_yScaleSpinBox.disconnect('valueChanged(double)', self.onAdjustAlignmentValueChanged)
    self.step3_1_yTranslationSpinBox.disconnect('valueChanged(double)', self.onAdjustAlignmentValueChanged)
    self.step3_1_computeDoseFromPddButton.disconnect('clicked()', self.onComputeDoseFromPdd)
    self.step3_1_calibrationRoutineCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep3_1_CalibrationRoutineSelected)
    self.step3_1_showOpticalAttenuationVsDoseCurveButton.disconnect('clicked()', self.onShowOpticalAttenuationVsDoseCurve)
    self.step3_1_removeSelectedPointsFromOpticalAttenuationVsDoseCurveButton.disconnect('clicked()', self.onRemoveSelectedPointsFromOpticalAttenuationVsDoseCurve)
    self.step3_1_fitPolynomialToOpticalAttenuationVsDoseCurveButton.disconnect('clicked()', self.onFitPolynomialToOpticalAttenuationVsDoseCurve)
    self.step3_2_exportCalibrationToCSV.disconnect('clicked()', self.onExportCalibration)
    self.step3_2_applyCalibrationButton.disconnect('clicked()', self.onApplyCalibration)
    self.step4_doseComparisonCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep4_DoseComparisonSelected)
    self.step4_maskSegmentationSelector.disconnect('currentNodeChanged(vtkMRMLNode*)', self.onStep4_MaskSegmentationSelectionChanged)
    self.step4_maskSegmentationSelector.disconnect('currentSegmentChanged(QString)', self.onStep4_MaskSegmentSelectionChanged)
    self.step4_1_referenceDoseUseMaximumDoseRadioButton.disconnect('toggled(bool)', self.onUseMaximumDoseRadioButtonToggled)
    self.step4_1_computeGammaButton.disconnect('clicked()', self.onGammaDoseComparison)
    self.step4_1_showGammaReportButton.disconnect('clicked()', self.onShowGammaReport)
    self.stepT1_lineProfileCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStepT1_LineProfileSelected)
    self.stepT1_createLineProfileButton.disconnect('clicked(bool)', self.onCreateLineProfileButton)
    self.stepT1_inputRulerSelector.disconnect("currentNodeChanged(vtkMRMLNode*)", self.onSelectLineProfileParameters)
    self.stepT1_exportLineProfilesToCSV.disconnect('clicked()', self.onExportLineProfiles)

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
    self.step1_loadDataCollapsibleButtonLayout = qt.QFormLayout(self.step1_loadDataCollapsibleButton)
    self.step1_loadDataCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step1_loadDataCollapsibleButtonLayout.setSpacing(4)

    # Load data label
    self.step1_LoadDataLabel = qt.QLabel("Load all DICOM data involved in the workflow.\nNote: Can return to this step later if more data needs to be loaded")
    self.step1_LoadDataLabel.wordWrap = True
    self.step1_loadDataCollapsibleButtonLayout.addRow(self.step1_LoadDataLabel)

    # Load DICOM data button
    self.step1_showDicomBrowserButton = qt.QPushButton("Load DICOM data")
    self.step1_showDicomBrowserButton.toolTip = "Load planning data (CT, dose, structures)"
    self.step1_showDicomBrowserButton.name = "showDicomBrowserButton"
    self.step1_loadDataCollapsibleButtonLayout.addRow(self.step1_showDicomBrowserButton)

    # Load non-DICOM data button
    self.step1_loadNonDicomDataButton = qt.QPushButton("Load non-DICOM data from file")
    self.step1_loadNonDicomDataButton.toolTip = "Load optical CT files from VFF, NRRD, etc."
    self.step1_loadNonDicomDataButton.name = "loadNonDicomDataButton"
    self.step1_loadDataCollapsibleButtonLayout.addRow(self.step1_loadNonDicomDataButton)
    
    # Add empty row
    self.step1_loadDataCollapsibleButtonLayout.addRow(' ', None)
    
    # Assign data label
    self.step1_AssignDataLabel = qt.QLabel("Assign loaded data to roles.\nNote: If this selection is changed later then all the following steps need to be performed again")
    self.step1_AssignDataLabel.wordWrap = True
    self.step1_loadDataCollapsibleButtonLayout.addRow(self.step1_AssignDataLabel)

    # PLANCT node selector
    self.planCTSelector = slicer.qMRMLNodeComboBox()
    self.planCTSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.planCTSelector.addEnabled = False
    self.planCTSelector.removeEnabled = False
    self.planCTSelector.setMRMLScene( slicer.mrmlScene )
    self.planCTSelector.setToolTip( "Pick the planning CT volume" )
    self.step1_loadDataCollapsibleButtonLayout.addRow('Planning CT volume: ', self.planCTSelector)

    # PLANDOSE node selector
    self.planDoseSelector = slicer.qMRMLNodeComboBox()
    self.planDoseSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.planDoseSelector.addEnabled = False
    self.planDoseSelector.removeEnabled = False
    self.planDoseSelector.setMRMLScene( slicer.mrmlScene )
    self.planDoseSelector.setToolTip( "Pick the planning dose volume." )
    self.step1_loadDataCollapsibleButtonLayout.addRow('Plan dose volume: ', self.planDoseSelector)

    # PLANSTRUCTURES node selector
    self.planStructuresSelector = slicer.qMRMLNodeComboBox()
    self.planStructuresSelector.nodeTypes = ["vtkMRMLSegmentationNode"]
    self.planStructuresSelector.noneEnabled = True
    self.planStructuresSelector.addEnabled = False
    self.planStructuresSelector.removeEnabled = False
    self.planStructuresSelector.setMRMLScene( slicer.mrmlScene )
    self.planStructuresSelector.setToolTip( "Pick the planning structure set." )
    self.step1_loadDataCollapsibleButtonLayout.addRow('Structures: ', self.planStructuresSelector)

    # OBI node selector
    self.obiSelector = slicer.qMRMLNodeComboBox()
    self.obiSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.obiSelector.addEnabled = False
    self.obiSelector.removeEnabled = False
    self.obiSelector.setMRMLScene( slicer.mrmlScene )
    self.obiSelector.setToolTip( "Pick the OBI volume." )
    self.step1_loadDataCollapsibleButtonLayout.addRow('OBI volume: ', self.obiSelector)

    # MEASURED node selector
    self.measuredVolumeSelector = slicer.qMRMLNodeComboBox()
    self.measuredVolumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.measuredVolumeSelector.addEnabled = False
    self.measuredVolumeSelector.removeEnabled = False
    self.measuredVolumeSelector.setMRMLScene( slicer.mrmlScene )
    self.measuredVolumeSelector.setToolTip( "Pick the measured gel dosimeter volume." )
    self.step1_loadDataCollapsibleButtonLayout.addRow('Measured gel dosimeter volume: ', self.measuredVolumeSelector)

    # CALIBRATION node selector
    self.calibrationVolumeSelector = slicer.qMRMLNodeComboBox()
    self.calibrationVolumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.calibrationVolumeSelector.noneEnabled = True
    self.calibrationVolumeSelector.addEnabled = False
    self.calibrationVolumeSelector.removeEnabled = False
    self.calibrationVolumeSelector.setMRMLScene( slicer.mrmlScene )
    self.calibrationVolumeSelector.setToolTip( "Pick the calibration gel dosimeter volume for registration.\nNote: Only needed if calibration function is not entered, but calculated based on calibration gel volume and PDD data" )
    self.step1_loadDataCollapsibleButtonLayout.addRow('Calibration gel volume (optional): ', self.calibrationVolumeSelector)

    # Connections
    self.step1_showDicomBrowserButton.connect('clicked()', self.logic.onDicomLoad)
    self.step1_loadNonDicomDataButton.connect('clicked()', self.onLoadNonDicomData)
    self.step1_loadDataCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep1_LoadDataCollapsed)

  def setup_Step2_Registration(self):
    # Step 2: Registration step
    self.step2_registrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_registrationCollapsibleButton.text = "2. Registration"
    self.sliceletPanelLayout.addWidget(self.step2_registrationCollapsibleButton)
    self.step2_registrationCollapsibleButtonLayout = qt.QFormLayout(self.step2_registrationCollapsibleButton)
    self.step2_registrationCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step2_registrationCollapsibleButtonLayout.setSpacing(4)

    # Step 2.1: OBI to PLANCT registration panel    
    self.step2_1_obiToPlanCtRegistrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_1_obiToPlanCtRegistrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_1_obiToPlanCtRegistrationCollapsibleButton.text = "2.1. Register planning CT to OBI"
    self.step2_registrationCollapsibleButtonLayout.addWidget(self.step2_1_obiToPlanCtRegistrationCollapsibleButton)
    self.step2_1_obiToPlanCtRegistrationLayout = qt.QFormLayout(self.step2_1_obiToPlanCtRegistrationCollapsibleButton)
    self.step2_1_obiToPlanCtRegistrationLayout.setContentsMargins(12,4,4,4)
    self.step2_1_obiToPlanCtRegistrationLayout.setSpacing(4)

    # Registration label
    self.step2_1_registrationLabel = qt.QLabel("Automatically register the OBI volume to the planning CT.\nIt should take several seconds.")
    self.step2_1_registrationLabel.wordWrap = True
    self.step2_1_obiToPlanCtRegistrationLayout.addRow(self.step2_1_registrationLabel)

    # OBI to PLANCT registration button
    self.step2_1_registerObiToPlanCtButton = qt.QPushButton("Perform registration")
    self.step2_1_registerObiToPlanCtButton.toolTip = "Register planning CT volume to OBI volume"
    self.step2_1_registerObiToPlanCtButton.name = "step2_1_registerObiToPlanCtButton"
    self.step2_1_obiToPlanCtRegistrationLayout.addRow(self.step2_1_registerObiToPlanCtButton)

    # Add empty row
    self.step2_1_obiToPlanCtRegistrationLayout.addRow(' ', None)

    # Transform fine-tune controls
    self.step2_1_transformSlidersInfoLabel = qt.QLabel("If registration result is not satisfactory, a simple re-run of the registration may solve it.\nOtherwise adjust result registration transform if needed:")
    self.step2_1_transformSlidersInfoLabel.wordWrap = True
    self.step2_1_translationSliders = slicer.qMRMLTransformSliders()
    #self.step2_1_translationSliders.CoordinateReference = slicer.qMRMLTransformSliders.LOCAL # This would make the sliders always start form 0 (then min/max would also not be needed)
    translationGroupBox = slicer.util.findChildren(widget=self.step2_1_translationSliders, className='ctkCollapsibleGroupBox')[0]
    translationGroupBox.collapsed  = True # Collapse by default
    self.step2_1_translationSliders.setMRMLScene(slicer.mrmlScene)
    self.step2_1_rotationSliders = slicer.qMRMLTransformSliders()
    self.step2_1_rotationSliders.minMaxVisible = False
    self.step2_1_rotationSliders.TypeOfTransform = slicer.qMRMLTransformSliders.ROTATION
    self.step2_1_rotationSliders.Title = "Rotation"
    self.step2_1_rotationSliders.CoordinateReference = slicer.qMRMLTransformSliders.LOCAL
    rotationGroupBox = slicer.util.findChildren(widget=self.step2_1_rotationSliders, className='ctkCollapsibleGroupBox')[0]
    rotationGroupBox.collapsed  = True # Collapse by default
    # self.step2_1_rotationSliders.setMRMLScene(slicer.mrmlScene) # If scene is set, then mm appears instead of degrees
    self.step2_1_obiToPlanCtRegistrationLayout.addRow(self.step2_1_transformSlidersInfoLabel)
    self.step2_1_obiToPlanCtRegistrationLayout.addRow(self.step2_1_translationSliders)
    self.step2_1_obiToPlanCtRegistrationLayout.addRow(self.step2_1_rotationSliders)

    # Step 2.2: Gel CT scan to cone beam CT registration panel
    self.step2_2_measuredDoseToObiRegistrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_2_measuredDoseToObiRegistrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_2_measuredDoseToObiRegistrationCollapsibleButton.text = "2.2. Register gel dosimeter volume to OBI"
    self.step2_registrationCollapsibleButtonLayout.addWidget(self.step2_2_measuredDoseToObiRegistrationCollapsibleButton)
    self.step2_2_measuredDoseToObiRegistrationLayout = qt.QVBoxLayout(self.step2_2_measuredDoseToObiRegistrationCollapsibleButton)
    self.step2_2_measuredDoseToObiRegistrationLayout.setContentsMargins(12,4,4,4)
    self.step2_2_measuredDoseToObiRegistrationLayout.setSpacing(4)

    # Step 2.2.1: Select OBI fiducials on OBI volume
    self.step2_2_1_obiFiducialSelectionCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_2_1_obiFiducialSelectionCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_2_1_obiFiducialSelectionCollapsibleButton.text = "2.2.1 Select OBI fiducial points"
    self.step2_2_measuredDoseToObiRegistrationLayout.addWidget(self.step2_2_1_obiFiducialSelectionCollapsibleButton)
    self.step2_2_1_obiFiducialSelectionLayout = qt.QFormLayout(self.step2_2_1_obiFiducialSelectionCollapsibleButton)
    self.step2_2_1_obiFiducialSelectionLayout.setContentsMargins(12,4,4,4)
    self.step2_2_1_obiFiducialSelectionLayout.setSpacing(4)

    # Create instructions label
    self.step2_2_1_instructionsLayout = qt.QHBoxLayout(self.step2_2_1_obiFiducialSelectionCollapsibleButton)
    self.step2_2_1_obiFiducialSelectionInfoLabel = qt.QLabel("Locate image plane of the OBI fiducials, then click the 'Place fiducials' button (blue arrow with red dot). Next, select the fiducial points in the displayed image plane.")
    self.step2_2_1_obiFiducialSelectionInfoLabel.wordWrap = True
    self.step2_2_1_helpLabel = qt.QLabel()
    self.step2_2_1_helpLabel.pixmap = qt.QPixmap(':Icons/Help.png')
    self.step2_2_1_helpLabel.maximumWidth = 24
    self.step2_2_1_helpLabel.toolTip = "Hint: Use Shift key for '3D cursor' navigation."
    self.step2_2_1_instructionsLayout.addWidget(self.step2_2_1_obiFiducialSelectionInfoLabel)
    self.step2_2_1_instructionsLayout.addWidget(self.step2_2_1_helpLabel)
    self.step2_2_1_obiFiducialSelectionLayout.addRow(self.step2_2_1_instructionsLayout)

    # OBI fiducial selector simple markups widget
    self.step2_2_1_obiFiducialList = slicer.qSlicerSimpleMarkupsWidget()
    self.step2_2_1_obiFiducialList.setMRMLScene(slicer.mrmlScene)
    self.step2_2_1_obiFiducialSelectionLayout.addRow(self.step2_2_1_obiFiducialList)

    # Step 2.2.2: Select MEASURED fiducials on MEASURED dose volume
    self.step2_2_2_measuredFiducialSelectionCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_2_2_measuredFiducialSelectionCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_2_2_measuredFiducialSelectionCollapsibleButton.text = "2.2.2 Select measured gel dosimeter fiducial points"
    self.step2_2_measuredDoseToObiRegistrationLayout.addWidget(self.step2_2_2_measuredFiducialSelectionCollapsibleButton)
    self.step2_2_2_measuredFiducialSelectionLayout = qt.QFormLayout(self.step2_2_2_measuredFiducialSelectionCollapsibleButton)
    self.step2_2_2_measuredFiducialSelectionLayout.setContentsMargins(12,4,4,4)
    self.step2_2_2_measuredFiducialSelectionLayout.setSpacing(4)

    # Create instructions label
    self.step2_2_2_instructionsLayout = qt.QHBoxLayout(self.step2_2_2_measuredFiducialSelectionCollapsibleButton)
    self.step2_2_2_measuredFiducialSelectionInfoLabel = qt.QLabel("Select the fiducial points in the gel dosimeter volume in the same order as the OBI fiducials were selected.")
    self.step2_2_2_measuredFiducialSelectionInfoLabel.wordWrap = True
    self.step2_2_2_helpLabel = qt.QLabel()
    self.step2_2_2_helpLabel.pixmap = qt.QPixmap(':Icons/Help.png')
    self.step2_2_2_helpLabel.maximumWidth = 24
    self.step2_2_2_helpLabel.toolTip = "Hint: Use Shift key for '3D cursor' navigation.\nHint: If gel dosimeter volume is too dark or low contrast, press left mouse button on the image and drag it to change window/level"
    self.step2_2_2_instructionsLayout.addWidget(self.step2_2_2_measuredFiducialSelectionInfoLabel)
    self.step2_2_2_instructionsLayout.addWidget(self.step2_2_2_helpLabel)
    self.step2_2_2_measuredFiducialSelectionLayout.addRow(self.step2_2_2_instructionsLayout)

    # Measured fiducial selector simple markups widget
    self.step2_2_2_measuredFiducialList = slicer.qSlicerSimpleMarkupsWidget()
    self.step2_2_2_measuredFiducialList.setMRMLScene(slicer.mrmlScene)
    self.step2_2_2_measuredFiducialSelectionLayout.addRow(self.step2_2_2_measuredFiducialList)

    # Step 2.2.3: Perform registration
    self.step2_2_3_measuredToObiRegistrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_2_3_measuredToObiRegistrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_2_3_measuredToObiRegistrationCollapsibleButton.text = "2.2.3 Perform registration"
    measuredToObiRegistrationCollapsibleButtonLayout = qt.QFormLayout(self.step2_2_3_measuredToObiRegistrationCollapsibleButton)
    measuredToObiRegistrationCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    measuredToObiRegistrationCollapsibleButtonLayout.setSpacing(4)
    self.step2_2_measuredDoseToObiRegistrationLayout.addWidget(self.step2_2_3_measuredToObiRegistrationCollapsibleButton)

    # Registration button - register MEASURED to OBI with fiducial registration
    self.step2_2_3_registerMeasuredToObiButton = qt.QPushButton("Register gel volume to OBI")
    self.step2_2_3_registerMeasuredToObiButton.toolTip = "Perform fiducial registration between measured gel dosimeter volume and OBI"
    self.step2_2_3_registerMeasuredToObiButton.name = "registerMeasuredToObiButton"
    measuredToObiRegistrationCollapsibleButtonLayout.addRow(self.step2_2_3_registerMeasuredToObiButton)

    # Fiducial error label
    self.step2_2_3_measuredToObiFiducialRegistrationErrorLabel = qt.QLabel('[Not yet performed]')
    measuredToObiRegistrationCollapsibleButtonLayout.addRow('Fiducial registration error: ', self.step2_2_3_measuredToObiFiducialRegistrationErrorLabel)

    # Add empty row
    measuredToObiRegistrationCollapsibleButtonLayout.addRow(' ', None)

    # Note label about fiducial error
    self.step2_2_3_NoteLabel = qt.QLabel("Note: Typical registration error is < 3mm")
    measuredToObiRegistrationCollapsibleButtonLayout.addRow(self.step2_2_3_NoteLabel)
    
    # Add substeps in button groups
    self.step2_2_registrationCollapsibleButtonGroup = qt.QButtonGroup()
    self.step2_2_registrationCollapsibleButtonGroup.addButton(self.step2_1_obiToPlanCtRegistrationCollapsibleButton)
    self.step2_2_registrationCollapsibleButtonGroup.addButton(self.step2_2_measuredDoseToObiRegistrationCollapsibleButton)

    self.step2_2_measuredToObiRegistrationCollapsibleButtonGroup = qt.QButtonGroup()
    self.step2_2_measuredToObiRegistrationCollapsibleButtonGroup.addButton(self.step2_2_1_obiFiducialSelectionCollapsibleButton)
    self.step2_2_measuredToObiRegistrationCollapsibleButtonGroup.addButton(self.step2_2_2_measuredFiducialSelectionCollapsibleButton)
    self.step2_2_measuredToObiRegistrationCollapsibleButtonGroup.addButton(self.step2_2_3_measuredToObiRegistrationCollapsibleButton)

    # Make sure first panels appear when steps are first opened (done before connections to avoid
    # executing those steps, which are only needed when actually switching there during the workflow)
    self.step2_2_1_obiFiducialSelectionCollapsibleButton.setProperty('collapsed', False)
    self.step2_1_obiToPlanCtRegistrationCollapsibleButton.setProperty('collapsed', False)

    # Connections
    self.step2_1_registerObiToPlanCtButton.connect('clicked()', self.onObiToPlanCTRegistration)
    self.step2_1_translationSliders.connect('valuesChanged()', self.step2_1_rotationSliders.resetUnactiveSliders)
    self.step2_2_measuredDoseToObiRegistrationCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep2_2_MeasuredDoseToObiRegistrationSelected)
    self.step2_2_1_obiFiducialSelectionCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep2_2_1_ObiFiducialCollectionSelected)
    self.step2_2_2_measuredFiducialSelectionCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep2_2_2_MeasuredFiducialCollectionSelected)
    self.step2_2_3_registerMeasuredToObiButton.connect('clicked()', self.onMeasuredToObiRegistration)

  def setup_step3_DoseCalibration(self):
    # Step 3: Calibration step
    self.step3_doseCalibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step3_doseCalibrationCollapsibleButton.text = "3. Dose calibration"
    self.sliceletPanelLayout.addWidget(self.step3_doseCalibrationCollapsibleButton)
    self.step3_doseCalibrationCollapsibleButtonLayout = qt.QVBoxLayout(self.step3_doseCalibrationCollapsibleButton)
    self.step3_doseCalibrationCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step3_doseCalibrationCollapsibleButtonLayout.setSpacing(4)
    
    # Step 3.1: Calibration routine (optional)
    self.step3_1_calibrationRoutineCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step3_1_calibrationRoutineCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step3_1_calibrationRoutineCollapsibleButton.text = "3.1. Perform calibration routine (optional)"
    self.step3_doseCalibrationCollapsibleButtonLayout.addWidget(self.step3_1_calibrationRoutineCollapsibleButton)
    self.step3_1_calibrationRoutineLayout = qt.QFormLayout(self.step3_1_calibrationRoutineCollapsibleButton)
    self.step3_1_calibrationRoutineLayout.setContentsMargins(12,4,4,4)
    self.step3_1_calibrationRoutineLayout.setSpacing(4)

    # Info label
    self.step3_1_calibrationRoutineLayout.addRow(qt.QLabel('Hint: Skip this step if calibration function is already available'))

    # Load Pdd data
    self.step3_1_pddLoadDataButton = qt.QPushButton("Load reference percent depth dose (PDD) data from CSV file")
    self.step3_1_pddLoadDataButton.toolTip = "Load PDD data file from CSV"
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_pddLoadDataButton)

    # Relative dose factor
    self.step3_1_rdfLineEdit = qt.QLineEdit()
    self.step3_1_calibrationRoutineLayout.addRow('Relative dose factor (RDF): ', self.step3_1_rdfLineEdit)

    # Empty row
    self.step3_1_calibrationRoutineLayout.addRow(' ', None)

    # Monitor units
    self.step3_1_monitorUnitsLineEdit = qt.QLineEdit()
    self.step3_1_calibrationRoutineLayout.addRow("Delivered monitor units (MU's): ", self.step3_1_monitorUnitsLineEdit)

    # Averaging radius
    self.step3_1_radiusMmFromCentrePixelLineEdit = qt.QLineEdit()
    self.step3_1_radiusMmFromCentrePixelLineEdit.toolTip = "Radius of the cylinder that is extracted around central axis to get optical attenuation values per depth"
    self.step3_1_calibrationRoutineLayout.addRow('Averaging radius (mm): ', self.step3_1_radiusMmFromCentrePixelLineEdit)

    # Align Pdd data and CALIBRATION data based on region of interest selected
    self.step3_1_alignCalibrationCurvesButton = qt.QPushButton("Plot reference and gel PDD data")
    self.step3_1_alignCalibrationCurvesButton.toolTip = "Align PDD data optical attenuation values with experimental optical attenuation values (coming from calibration gel volume)"
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_alignCalibrationCurvesButton)

    # Controls to adjust alignment
    self.step3_1_adjustAlignmentControlsLayout = qt.QHBoxLayout(self.step3_1_calibrationRoutineCollapsibleButton)
    self.step3_1_adjustAlignmentLabel = qt.QLabel('Manual adjustment: ')
    self.step3_1_xTranslationLabel = qt.QLabel('  X shift:')
    self.step3_1_xTranslationSpinBox = qt.QDoubleSpinBox()
    self.step3_1_xTranslationSpinBox.decimals = 2
    self.step3_1_xTranslationSpinBox.singleStep = 0.01
    self.step3_1_xTranslationSpinBox.value = 0
    self.step3_1_xTranslationSpinBox.minimum = -10.0
    self.step3_1_xTranslationSpinBox.maximumWidth = 48
    self.step3_1_yScaleLabel = qt.QLabel('  Y scale:')
    self.step3_1_yScaleSpinBox = qt.QDoubleSpinBox()
    self.step3_1_yScaleSpinBox.decimals = 3
    self.step3_1_yScaleSpinBox.singleStep = 0.01
    self.step3_1_yScaleSpinBox.value = 1
    self.step3_1_yScaleSpinBox.minimum = 0
    self.step3_1_yScaleSpinBox.maximum = 100000
    self.step3_1_yScaleSpinBox.maximumWidth = 60
    self.step3_1_yTranslationLabel = qt.QLabel('  Y shift:')
    self.step3_1_yTranslationSpinBox = qt.QDoubleSpinBox()
    self.step3_1_yTranslationSpinBox.decimals = 2
    self.step3_1_yTranslationSpinBox.singleStep = 0.1
    self.step3_1_yTranslationSpinBox.value = 0
    self.step3_1_yTranslationSpinBox.minimum = -99.9
    self.step3_1_yTranslationSpinBox.maximumWidth = 48
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_adjustAlignmentLabel)
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_xTranslationLabel)
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_xTranslationSpinBox)
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_yScaleLabel)
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_yScaleSpinBox)
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_yTranslationLabel)
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_yTranslationSpinBox)
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_adjustAlignmentControlsLayout)

    # Add empty row
    self.step3_1_calibrationRoutineLayout.addRow(' ', None)

    # Create dose information button
    self.step3_1_computeDoseFromPddButton = qt.QPushButton("Calculate dose from reference PDD")
    self.step3_1_computeDoseFromPddButton.toolTip = "Compute dose from PDD data based on RDF and MUs"
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_computeDoseFromPddButton)

    # Empty row
    self.step3_1_calibrationRoutineLayout.addRow(' ', None)

    # Show chart of optical attenuation vs. dose curve and remove selected points
    self.step3_1_oaVsDoseCurveControlsLayout = qt.QHBoxLayout(self.step3_1_calibrationRoutineCollapsibleButton)
    self.step3_1_showOpticalAttenuationVsDoseCurveButton = qt.QPushButton("Plot optical attenuation vs dose")
    self.step3_1_showOpticalAttenuationVsDoseCurveButton.toolTip = "Show optical attenuation vs. Dose curve to determine the order of polynomial to fit."
    self.step3_1_removeSelectedPointsFromOpticalAttenuationVsDoseCurveButton = qt.QPushButton("Optional: Remove selected points from plot")
    self.step3_1_removeSelectedPointsFromOpticalAttenuationVsDoseCurveButton.toolTip = "Removes the selected points (typically outliers) from the OA vs Dose curve so that they are omitted during polynomial fitting.\nTo select points, hold down the right mouse button and draw a selection rectangle in the chart view."
    self.step3_1_helpLabel = qt.QLabel()
    self.step3_1_helpLabel.pixmap = qt.QPixmap(':Icons/Help.png')
    self.step3_1_helpLabel.maximumWidth = 24
    self.step3_1_helpLabel.toolTip = "To select points in the plot, hold down the right mouse button and draw a selection rectangle in the chart view."
    self.step3_1_oaVsDoseCurveControlsLayout.addWidget(self.step3_1_showOpticalAttenuationVsDoseCurveButton)
    self.step3_1_oaVsDoseCurveControlsLayout.addWidget(self.step3_1_removeSelectedPointsFromOpticalAttenuationVsDoseCurveButton)
    self.step3_1_oaVsDoseCurveControlsLayout.addWidget(self.step3_1_helpLabel)
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_oaVsDoseCurveControlsLayout)
    
    # Add empty row
    self.step3_1_calibrationRoutineLayout.addRow(' ', None)

    # Find polynomial fit
    self.step3_1_selectOrderOfPolynomialFitButton = qt.QComboBox()
    self.step3_1_selectOrderOfPolynomialFitButton.addItem('1')
    self.step3_1_selectOrderOfPolynomialFitButton.addItem('2')
    self.step3_1_selectOrderOfPolynomialFitButton.addItem('3')
    self.step3_1_selectOrderOfPolynomialFitButton.addItem('4')
    self.step3_1_calibrationRoutineLayout.addRow('Fit with what order polynomial function:', self.step3_1_selectOrderOfPolynomialFitButton)
    
    self.step3_1_fitPolynomialToOpticalAttenuationVsDoseCurveButton = qt.QPushButton("Fit data and determine calibration function")
    self.step3_1_fitPolynomialToOpticalAttenuationVsDoseCurveButton.toolTip = "Finds the line of best fit based on the data and polynomial order provided"
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_fitPolynomialToOpticalAttenuationVsDoseCurveButton)

    self.step3_1_fitPolynomialResidualsLabel = qt.QLabel()
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_fitPolynomialResidualsLabel)

    # Step 3.2: Apply calibration
    self.step3_2_applyCalibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step3_2_applyCalibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step3_2_applyCalibrationCollapsibleButton.text = "3.2. Apply calibration"
    self.step3_doseCalibrationCollapsibleButtonLayout.addWidget(self.step3_2_applyCalibrationCollapsibleButton)
    self.step3_2_applyCalibrationLayout = qt.QFormLayout(self.step3_2_applyCalibrationCollapsibleButton)
    self.step3_2_applyCalibrationLayout.setContentsMargins(12,4,4,4)
    self.step3_2_applyCalibrationLayout.setSpacing(4)

    # Calibration function label
    self.step3_2_calibrationFunctionLabel = qt.QLabel("Calibration function:\n(either determined from step 3.1., or can be manually input/altered)")
    self.step3_2_calibrationFunctionLabel.wordWrap = True
    self.step3_2_applyCalibrationLayout.addRow(self.step3_2_calibrationFunctionLabel)

    # Dose calibration function input fields
    self.step3_2_calibrationFunctionLayout = qt.QGridLayout(self.step3_1_calibrationRoutineCollapsibleButton)
    self.step3_2_doseLabel = qt.QLabel('Dose (Gy) = ')
    self.step3_2_calibrationFunctionOrder0LineEdit = qt.QLineEdit()
    self.step3_2_calibrationFunctionOrder0LineEdit.maximumWidth = 64
    self.step3_2_calibrationFunctionOrder0Label = qt.QLabel(' OA<span style=" font-size:8pt; vertical-align:super;">0</span> + ')
    self.step3_2_calibrationFunctionOrder1LineEdit = qt.QLineEdit()
    self.step3_2_calibrationFunctionOrder1LineEdit.maximumWidth = 64
    self.step3_2_calibrationFunctionOrder1Label = qt.QLabel(' OA<span style=" font-size:8pt; vertical-align:super;">1</span> + ')
    self.step3_2_calibrationFunctionOrder2LineEdit = qt.QLineEdit()
    self.step3_2_calibrationFunctionOrder2LineEdit.maximumWidth = 64
    self.step3_2_calibrationFunctionOrder2Label = qt.QLabel(' OA<span style=" font-size:8pt; vertical-align:super;">2</span> + ')
    self.step3_2_calibrationFunctionOrder3LineEdit = qt.QLineEdit()
    self.step3_2_calibrationFunctionOrder3LineEdit.maximumWidth = 64
    self.step3_2_calibrationFunctionOrder3Label = qt.QLabel(' OA<span style=" font-size:8pt; vertical-align:super;">3</span> + ')
    self.step3_2_calibrationFunctionOrder4LineEdit = qt.QLineEdit()
    self.step3_2_calibrationFunctionOrder4LineEdit.maximumWidth = 64
    self.step3_2_calibrationFunctionOrder4Label = qt.QLabel(' OA<span style=" font-size:8pt; vertical-align:super;">4</span>')
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_doseLabel,0,0)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder0LineEdit,0,1)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder0Label,0,2)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder1LineEdit,0,3)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder1Label,0,4)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder2LineEdit,0,5)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder2Label,0,6)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder3LineEdit,1,1)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder3Label,1,2)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder4LineEdit,1,3)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder4Label,1,4)
    self.step3_2_applyCalibrationLayout.addRow(self.step3_2_calibrationFunctionLayout)

    # Export calibration polynomial coefficients to CSV
    self.step3_2_exportCalibrationToCSV = qt.QPushButton("Optional: Export calibration points to a CSV file")
    self.step3_2_exportCalibrationToCSV.toolTip = "Export optical attenuation to dose calibration plot points (if points were removed, those are not exported).\nIf polynomial fitting has been done, export the coefficients as well."
    self.step3_2_applyCalibrationLayout.addRow(self.step3_2_exportCalibrationToCSV)
    
    # Empty row
    self.step3_1_calibrationRoutineLayout.addRow(' ', None)

    # Apply calibration button
    self.step3_2_applyCalibrationButton = qt.QPushButton("Apply calibration")
    self.step3_2_applyCalibrationButton.toolTip = "Apply fitted polynomial on MEASURED volume"
    self.step3_2_applyCalibrationLayout.addRow(self.step3_2_applyCalibrationButton)

    self.step3_2_applyCalibrationStatusLabel = qt.QLabel()
    self.step3_2_applyCalibrationLayout.addRow(' ', self.step3_2_applyCalibrationStatusLabel)

    # Add substeps in a button group
    self.step3_calibrationCollapsibleButtonGroup = qt.QButtonGroup()
    self.step3_calibrationCollapsibleButtonGroup.addButton(self.step3_1_calibrationRoutineCollapsibleButton)
    self.step3_calibrationCollapsibleButtonGroup.addButton(self.step3_2_applyCalibrationCollapsibleButton)

    # Make sure first panels appear when steps are first opened (done before connections to avoid
    # executing those steps, which are only needed when actually switching there during the workflow)
    self.step3_1_calibrationRoutineCollapsibleButton.setProperty('collapsed', False)

    # Connections
    self.step3_1_pddLoadDataButton.connect('clicked()', self.onLoadPddDataRead)
    self.step3_1_alignCalibrationCurvesButton.connect('clicked()', self.onAlignCalibrationCurves)
    self.step3_1_xTranslationSpinBox.connect('valueChanged(double)', self.onAdjustAlignmentValueChanged)
    self.step3_1_yScaleSpinBox.connect('valueChanged(double)', self.onAdjustAlignmentValueChanged)
    self.step3_1_yTranslationSpinBox.connect('valueChanged(double)', self.onAdjustAlignmentValueChanged)
    self.step3_1_computeDoseFromPddButton.connect('clicked()', self.onComputeDoseFromPdd)
    self.step3_1_calibrationRoutineCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep3_1_CalibrationRoutineSelected)
    self.step3_1_showOpticalAttenuationVsDoseCurveButton.connect('clicked()', self.onShowOpticalAttenuationVsDoseCurve)
    self.step3_1_removeSelectedPointsFromOpticalAttenuationVsDoseCurveButton.connect('clicked()', self.onRemoveSelectedPointsFromOpticalAttenuationVsDoseCurve)
    self.step3_1_fitPolynomialToOpticalAttenuationVsDoseCurveButton.connect('clicked()', self.onFitPolynomialToOpticalAttenuationVsDoseCurve)
    self.step3_2_exportCalibrationToCSV.connect('clicked()', self.onExportCalibration)
    self.step3_2_applyCalibrationButton.connect('clicked()', self.onApplyCalibration)
    
  def setup_Step4_DoseComparison(self):
    # Step 4: Dose comparison and analysis
    self.step4_doseComparisonCollapsibleButton.setProperty('collapsedHeight', 4)
    # self.step4_doseComparisonCollapsibleButton.text = "4. 3D dose comparison"
    self.step4_doseComparisonCollapsibleButton.text = "4. 3D gamma dose comparison" #TODO: Switch to line above when more dose comparisons are added
    self.sliceletPanelLayout.addWidget(self.step4_doseComparisonCollapsibleButton)
    self.step4_doseComparisonCollapsibleButtonLayout = qt.QFormLayout(self.step4_doseComparisonCollapsibleButton)
    self.step4_doseComparisonCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step4_doseComparisonCollapsibleButtonLayout.setSpacing(4)

    # Info label
    self.step4_doseComparisonReferenceVolumeLabel = qt.QLabel('Calibration has not been performed!')
    self.step4_doseComparisonReferenceVolumeLabel.wordWrap = True
    self.step4_doseComparisonCollapsibleButtonLayout.addRow('Plan dose volume (reference):', self.step4_doseComparisonReferenceVolumeLabel)
    self.step4_doseComparisonEvaluatedVolumeLabel = qt.QLabel('Calibration has not been performed!')
    self.step4_doseComparisonEvaluatedVolumeLabel.wordWrap = True
    self.step4_doseComparisonCollapsibleButtonLayout.addRow('Calibrated gel volume (evaluated):', self.step4_doseComparisonEvaluatedVolumeLabel)

    # Mask segmentation selector
    from qSlicerSegmentationsModuleWidgetsPythonQt import qMRMLSegmentSelectorWidget
    self.step4_maskSegmentationSelector = qMRMLSegmentSelectorWidget()
    self.step4_maskSegmentationSelector.setMRMLScene(slicer.mrmlScene)
    self.step4_maskSegmentationSelector.noneEnabled = True
    self.step4_doseComparisonCollapsibleButtonLayout.addRow("Mask structure: ", self.step4_maskSegmentationSelector)

    # Collapsible buttons for substeps
    self.step4_1_gammaDoseComparisonCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step4_1_gammaDoseComparisonCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step4_1_gammaDoseComparisonCollapsibleButton.setVisible(False) # TODO:
    self.step4_2_chiDoseComparisonCollapsibleButton = ctk.ctkCollapsibleButton() #TODO:
    self.step4_2_chiDoseComparisonCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step4_2_chiDoseComparisonCollapsibleButton.setVisible(False) # TODO:
    self.step4_3_doseDifferenceComparisonCollapsibleButton = ctk.ctkCollapsibleButton() #TODO:
    self.step4_3_doseDifferenceComparisonCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step4_3_doseDifferenceComparisonCollapsibleButton.setVisible(False) # TODO:

    self.collapsibleButtonsGroupForDoseComparisonAndAnalysis = qt.QButtonGroup()
    self.collapsibleButtonsGroupForDoseComparisonAndAnalysis.addButton(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.collapsibleButtonsGroupForDoseComparisonAndAnalysis.addButton(self.step4_2_chiDoseComparisonCollapsibleButton)
    self.collapsibleButtonsGroupForDoseComparisonAndAnalysis.addButton(self.step4_3_doseDifferenceComparisonCollapsibleButton)

    # 4.1. Gamma dose comparison
    self.step4_1_gammaDoseComparisonCollapsibleButton.text = "4.1. Gamma dose comparison"
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout = qt.QFormLayout(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.step4_doseComparisonCollapsibleButtonLayout.addRow(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.setSpacing(4)

    # Temporarily assign main layout to 4.1. gamma layout until more dose comparisons are added
    #TODO: Remove when more dose comparisons are added
    self.step4_1_gammaDoseComparisonCollapsibleButton = self.step4_doseComparisonCollapsibleButton
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout = self.step4_doseComparisonCollapsibleButtonLayout

    # DTA
    self.step4_1_dtaDistanceToleranceMmSpinBox = qt.QDoubleSpinBox()
    self.step4_1_dtaDistanceToleranceMmSpinBox.setValue(3.0)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow('Distance-to-agreement criteria (mm): ', self.step4_1_dtaDistanceToleranceMmSpinBox)

    # Dose difference tolerance criteria
    self.step4_1_doseDifferenceToleranceLayout = qt.QHBoxLayout(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.step4_1_doseDifferenceToleranceLabelBefore = qt.QLabel('Dose difference criteria is ')
    self.step4_1_doseDifferenceTolerancePercentSpinBox = qt.QDoubleSpinBox()
    self.step4_1_doseDifferenceTolerancePercentSpinBox.setValue(3.0)
    self.step4_1_doseDifferenceToleranceLabelAfter = qt.QLabel('% of:  ')
    self.step4_1_doseDifferenceToleranceLayout.addWidget(self.step4_1_doseDifferenceToleranceLabelBefore)
    self.step4_1_doseDifferenceToleranceLayout.addWidget(self.step4_1_doseDifferenceTolerancePercentSpinBox)
    self.step4_1_doseDifferenceToleranceLayout.addWidget(self.step4_1_doseDifferenceToleranceLabelAfter)

    self.step4_1_referenceDoseLayout = qt.QVBoxLayout()
    self.step4_1_referenceDoseUseMaximumDoseRadioButton = qt.QRadioButton('the maximum dose\n(calculated from plan dose volume)')
    self.step4_1_referenceDoseUseCustomValueLayout = qt.QHBoxLayout(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.step4_1_referenceDoseUseCustomValueGyRadioButton = qt.QRadioButton('a custom dose value (cGy):')
    self.step4_1_referenceDoseCustomValueCGySpinBox = qt.QDoubleSpinBox()
    self.step4_1_referenceDoseCustomValueCGySpinBox.value = 5.0
    self.step4_1_referenceDoseCustomValueCGySpinBox.maximum = 99999
    self.step4_1_referenceDoseCustomValueCGySpinBox.maximumWidth = 48
    self.step4_1_referenceDoseCustomValueCGySpinBox.enabled = False
    self.step4_1_referenceDoseUseCustomValueLayout.addWidget(self.step4_1_referenceDoseUseCustomValueGyRadioButton)
    self.step4_1_referenceDoseUseCustomValueLayout.addWidget(self.step4_1_referenceDoseCustomValueCGySpinBox)
    self.step4_1_referenceDoseUseCustomValueLayout.addStretch(1) 
    self.step4_1_referenceDoseLayout.addWidget(self.step4_1_referenceDoseUseMaximumDoseRadioButton)
    self.step4_1_referenceDoseLayout.addLayout(self.step4_1_referenceDoseUseCustomValueLayout)
    self.step4_1_doseDifferenceToleranceLayout.addLayout(self.step4_1_referenceDoseLayout)

    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow(self.step4_1_doseDifferenceToleranceLayout)

    # Analysis threshold
    self.step4_1_analysisThresholdLayout = qt.QHBoxLayout(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.step4_1_analysisThresholdLabelBefore = qt.QLabel('Do not calculate gamma values for voxels below ')
    self.step4_1_analysisThresholdPercentSpinBox = qt.QDoubleSpinBox()
    self.step4_1_analysisThresholdPercentSpinBox.value = 0.0
    self.step4_1_analysisThresholdPercentSpinBox.maximumWidth = 48
    self.step4_1_analysisThresholdLabelAfter = qt.QLabel('% of the maximum dose,')
    self.step4_1_analysisThresholdLabelAfter.wordWrap = True
    self.step4_1_analysisThresholdLayout.addWidget(self.step4_1_analysisThresholdLabelBefore)
    self.step4_1_analysisThresholdLayout.addWidget(self.step4_1_analysisThresholdPercentSpinBox)
    self.step4_1_analysisThresholdLayout.addWidget(self.step4_1_analysisThresholdLabelAfter)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow(self.step4_1_analysisThresholdLayout)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow(qt.QLabel('                                            or the custom dose value (depending on selection above).'))

    # Use linear interpolation
    self.step4_1_useLinearInterpolationCheckBox = qt.QCheckBox()
    self.step4_1_useLinearInterpolationCheckBox.checked = True
    self.step4_1_useLinearInterpolationCheckBox.setToolTip('Flag determining whether linear interpolation is used when resampling the compare dose volume to reference grid. Nearest neighbour is used if unchecked.')
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow('Use linear interpolation: ', self.step4_1_useLinearInterpolationCheckBox)

    # Maximum gamma
    self.step4_1_maximumGammaSpinBox = qt.QDoubleSpinBox()
    self.step4_1_maximumGammaSpinBox.setValue(2.0)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow('Upper bound for gamma calculation: ', self.step4_1_maximumGammaSpinBox)

    # Gamma volume selector
    self.step4_1_gammaVolumeSelectorLayout = qt.QHBoxLayout(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.step4_1_gammaVolumeSelector = slicer.qMRMLNodeComboBox()
    self.step4_1_gammaVolumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step4_1_gammaVolumeSelector.addEnabled = True
    self.step4_1_gammaVolumeSelector.removeEnabled = False
    self.step4_1_gammaVolumeSelector.setMRMLScene( slicer.mrmlScene )
    self.step4_1_gammaVolumeSelector.setToolTip( "Select output gamma volume" )
    self.step4_1_gammaVolumeSelector.setProperty('baseName', 'GammaVolume')
    self.step4_1_helpLabel = qt.QLabel()
    self.step4_1_helpLabel.pixmap = qt.QPixmap(':Icons/Help.png')
    self.step4_1_helpLabel.maximumWidth = 24
    self.step4_1_helpLabel.toolTip = "A gamma volume must be selected to contain the output. You can create a new volume by selecting 'Create new Volume'"
    self.step4_1_gammaVolumeSelectorLayout.addWidget(self.step4_1_gammaVolumeSelector)
    self.step4_1_gammaVolumeSelectorLayout.addWidget(self.step4_1_helpLabel)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow("Gamma volume: ", self.step4_1_gammaVolumeSelectorLayout)

    self.step4_1_computeGammaButton = qt.QPushButton('Calculate gamma volume')
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow(self.step4_1_computeGammaButton)

    self.step4_1_gammaStatusLabel = qt.QLabel()
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow(self.step4_1_gammaStatusLabel)

    self.step4_1_showGammaReportButton = qt.QPushButton('Show report')
    self.step4_1_showGammaReportButton.enabled = False
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow(self.step4_1_showGammaReportButton)

    # 4.2. Chi dose comparison
    self.step4_2_chiDoseComparisonCollapsibleButton.text = "4.2. Chi dose comparison"
    self.step4_2_chiDoseComparisonCollapsibleButtonLayout = qt.QFormLayout(self.step4_2_chiDoseComparisonCollapsibleButton)
    self.step4_doseComparisonCollapsibleButtonLayout.addRow(self.step4_2_chiDoseComparisonCollapsibleButton)
    self.step4_2_chiDoseComparisonCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step4_2_chiDoseComparisonCollapsibleButtonLayout.setSpacing(4)

    # 4.3. Dose difference comparison
    self.step4_3_doseDifferenceComparisonCollapsibleButton.text = "4.3. Dose difference comparison"
    self.step4_3_doseDifferenceComparisonCollapsibleButtonLayout = qt.QFormLayout(self.step4_3_doseDifferenceComparisonCollapsibleButton)
    self.step4_doseComparisonCollapsibleButtonLayout.addRow(self.step4_3_doseDifferenceComparisonCollapsibleButton)
    self.step4_3_doseDifferenceComparisonCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step4_3_doseDifferenceComparisonCollapsibleButtonLayout.setSpacing(4)

    # Make sure first panels appear when steps are first opened (done before connections to avoid
    # executing those steps, which are only needed when actually switching there during the workflow)
    #self.step4_1_gammaDoseComparisonCollapsibleButton.setProperty('collapsed',False) #TODO: Uncomment when adding more dose comparisons
    self.step4_1_referenceDoseUseMaximumDoseRadioButton.setChecked(True)

    # Connections
    self.step4_doseComparisonCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep4_DoseComparisonSelected)
    self.step4_maskSegmentationSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onStep4_MaskSegmentationSelectionChanged)
    self.step4_maskSegmentationSelector.connect('currentSegmentChanged(QString)', self.onStep4_MaskSegmentSelectionChanged)
    self.step4_1_referenceDoseUseMaximumDoseRadioButton.connect('toggled(bool)', self.onUseMaximumDoseRadioButtonToggled)
    self.step4_1_computeGammaButton.connect('clicked()', self.onGammaDoseComparison)
    self.step4_1_showGammaReportButton.connect('clicked()', self.onShowGammaReport)

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
    self.stepT1_lineProfileCollapsibleButton.connect('contentsCollapsed(bool)', self.onStepT1_LineProfileSelected)
    self.stepT1_createLineProfileButton.connect('clicked(bool)', self.onCreateLineProfileButton)
    self.stepT1_inputRulerSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelectLineProfileParameters)
    self.stepT1_exportLineProfilesToCSV.connect('clicked()', self.onExportLineProfiles)

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

  def onStep1_LoadDataCollapsed(self, collapsed):
    # Save selections to member variables when switching away from load data step
    if collapsed == True:
      self.planCtVolumeNode = self.planCTSelector.currentNode()
      self.planDoseVolumeNode = self.planDoseSelector.currentNode()
      self.obiVolumeNode = self.obiSelector.currentNode()
      self.planStructuresNode = self.planStructuresSelector.currentNode()
      self.measuredVolumeNode = self.measuredVolumeSelector.currentNode()
      self.calibrationVolumeNode = self.calibrationVolumeSelector.currentNode()

  def onStep2_2_MeasuredDoseToObiRegistrationSelected(self, collapsed):
    # Make sure the functions handling entering the fiducial selection panels are called when entering the outer panel
    if collapsed == False:
      if self.step2_2_1_obiFiducialSelectionCollapsibleButton.collapsed == False:
        self.onStep2_2_1_ObiFiducialCollectionSelected(False)
      elif self.step2_2_2_measuredFiducialSelectionCollapsibleButton.collapsed == False:
        self.onStep2_2_2_MeasuredFiducialCollectionSelected(False)

  def onStep2_2_1_ObiFiducialCollectionSelected(self, collapsed):
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    interactionNode = appLogic.GetInteractionNode()

    if collapsed == False:
      # Turn on persistent fiducial placement mode
      interactionNode.SwitchToPersistentPlaceMode()

      # Select OBI fiducials node
      self.step2_2_1_obiFiducialList.setCurrentNode(self.obiMarkupsFiducialNode)
      self.step2_2_1_obiFiducialList.activate()

      # Automatically show OBI volume (show nothing if not present)
      if self.obiVolumeNode is not None:
        selectionNode.SetActiveVolumeID(self.obiVolumeNode.GetID())
      else:
        selectionNode.SetActiveVolumeID(None)
        slicer.util.errorDisplay('OBI volume not selected!\nPlease return to first step and make the assignment')
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()
    else:
      # Turn off fiducial place mode
      interactionNode.SwitchToViewTransformMode()

  def onStep2_2_2_MeasuredFiducialCollectionSelected(self, collapsed):
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    interactionNode = appLogic.GetInteractionNode()

    if collapsed == False:
      # Turn on persistent fiducial placement mode
      interactionNode.SwitchToPersistentPlaceMode()

      # Select MEASURED fiducials node
      self.step2_2_2_measuredFiducialList.setCurrentNode(self.measuredMarkupsFiducialNode)
      self.step2_2_2_measuredFiducialList.activate()

      # Automatically show MEASURED volume (show nothing if not present)
      if self.measuredVolumeNode is not None:
        selectionNode.SetActiveVolumeID(self.measuredVolumeNode.GetID())
      else:
        selectionNode.SetActiveVolumeID(None)
        slicer.util.errorDisplay('Gel dosimeter volume not selected!\nPlease return to first step and make the assignment')
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection() 
    else:
      # Turn off fiducial place mode
      interactionNode.SwitchToViewTransformMode()

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
    self.step2_1_translationSliders.setMRMLTransformNode(obiToPlanTransformNode)
    self.step2_1_rotationSliders.setMRMLTransformNode(obiToPlanTransformNode)

    # Change single step size to 0.5mm in the translation controls
    sliders = slicer.util.findChildren(widget=self.step2_1_translationSliders, className='qMRMLLinearTransformSlider')
    for slider in sliders:
      slider.singleStep = 0.5

  def onMeasuredToObiRegistration(self):
    errorRms = self.logic.registerObiToMeasured(self.obiMarkupsFiducialNode.GetID(), self.measuredMarkupsFiducialNode.GetID())
    
    # Show registration error on GUI
    self.step2_2_3_measuredToObiFiducialRegistrationErrorLabel.setText(str(errorRms) + ' mm')

    # Apply transform to MEASURED volume
    obiToMeasuredTransformNode = slicer.util.getNode(self.logic.obiToMeasuredTransformName)
    self.measuredVolumeNode.SetAndObserveTransformNodeID(obiToMeasuredTransformNode.GetID())

    # Show both volumes in the 2D views
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(self.obiVolumeNode.GetID())
    selectionNode.SetSecondaryVolumeID(self.measuredVolumeNode.GetID())
    appLogic.PropagateVolumeSelection() 

  def onLoadPddDataRead(self):
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

    # Show chart
    self.calibrationCurveChart.GetAxis(1).SetTitle('Depth (cm) - select region using right mouse button to be considered for calibration')
    self.calibrationCurveChart.GetAxis(0).SetTitle('Percent Depth Dose / Optical Attenuation')
    self.calibrationCurveChart.SetShowLegend(True)
    self.calibrationCurveChart.SetTitle('PDD vs Calibration data')
    self.calibrationCurveChartView.GetInteractor().Initialize()
    self.calibrationCurveChartView.GetRenderWindow().SetSize(800,550)
    self.calibrationCurveChartView.GetRenderWindow().SetWindowName('PDD vs Calibration data chart')
    self.calibrationCurveChartView.GetRenderWindow().Start()

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
    self.step4_maskSegmentationSelector.setCurrentNode(self.planStructuresNode)
    self.onStep4_MaskSegmentationSelectionChanged(self.planStructuresNode)
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
    self.onStep4_MaskSegmentSelectionChanged(self.step4_maskSegmentationSelector.currentSegmentID())
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
      self.gammaParameterSetNode.SetDoseDifferenceTolerancePercent(self.step4_1_doseDifferenceTolerancePercentSpinBox.value)
      self.gammaParameterSetNode.SetUseMaximumDose(self.step4_1_referenceDoseUseMaximumDoseRadioButton.isChecked())
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
    calibrationVolumeName = 'lcv02_hr.vff'

    planCTVolume = slicer.util.getNode(planCTVolumeName)
    self.planCTSelector.setCurrentNode(planCTVolume)
    planDoseVolume = slicer.util.getNode(planDoseVolumeName)
    self.planDoseSelector.setCurrentNode(planDoseVolume)
    obiVolume = slicer.util.getNode(obiVolumeName)
    self.obiSelector.setCurrentNode(obiVolume)
    structureSetNode = slicer.util.getNode(structureSetNodeName)
    self.planStructuresSelector.setCurrentNode(structureSetNode)
    measuredVolume = slicer.util.getNode(measuredVolumeName)
    self.measuredVolumeSelector.setCurrentNode(measuredVolume)
    calibrationVolume = slicer.util.getNode(calibrationVolumeName)
    self.calibrationVolumeSelector.setCurrentNode(calibrationVolume)
    slicer.app.processEvents()

    ### 2. Register
    self.step2_registrationCollapsibleButton.setChecked(True)
    self.onObiToPlanCTRegistration()
    slicer.app.processEvents()

    # Select fiducials
    self.step2_2_measuredDoseToObiRegistrationCollapsibleButton.setChecked(True)
    obiFiducialsNode = slicer.util.getNode(self.obiMarkupsFiducialNodeName)
    obiFiducialsNode.AddFiducial(76.4, 132.1, -44.8)
    obiFiducialsNode.AddFiducial(173, 118.4, -44.8)
    obiFiducialsNode.AddFiducial(154.9, 163.5, -44.8)
    obiFiducialsNode.AddFiducial(77.4, 133.6, 23.9)
    obiFiducialsNode.AddFiducial(172.6, 118.9, 23.9)
    obiFiducialsNode.AddFiducial(166.5, 151.3, 23.9)
    self.step2_2_2_measuredFiducialSelectionCollapsibleButton.setChecked(True)
    measuredFiducialsNode = slicer.util.getNode(self.measuredMarkupsFiducialNodeName)
    measuredFiducialsNode.AddFiducial(-92.25, -25.9, 26.2)
    measuredFiducialsNode.AddFiducial(-31.9, -100.8, 26.2)
    measuredFiducialsNode.AddFiducial(-15, -55.2, 26.2)
    measuredFiducialsNode.AddFiducial(-92, -26.7, 94)
    measuredFiducialsNode.AddFiducial(-32.7, -101, 94)
    measuredFiducialsNode.AddFiducial(-15, -73.6, 94)

    # Perform fiducial registration
    self.step2_2_3_measuredToObiRegistrationCollapsibleButton.setChecked(True)
    self.onMeasuredToObiRegistration()

    ### 4. Calibration
    self.step3_doseCalibrationCollapsibleButton.setChecked(True)
    self.logic.loadPdd('d:/devel/_Images/RT/20140123_FilmDosimetry_StructureSetIncluded/12MeV.csv')

    # Parse calibration volume
    self.step3_1_radiusMmFromCentrePixelLineEdit.setText('5')

    # Align calibration curves
    self.onAlignCalibrationCurves()
    self.step3_1_xTranslationSpinBox.setValue(1)
    self.step3_1_yScaleSpinBox.setValue(1.162)
    self.step3_1_yTranslationSpinBox.setValue(1.28)

    # Generate dose information
    self.step3_doseCalibrationCollapsibleButton.setChecked(True)
    self.step3_1_rdfLineEdit.setText('0.989')
    self.step3_1_monitorUnitsLineEdit.setText('1850')
    self.onComputeDoseFromPdd()
    # Show optical attenuation VS dose curve
    self.step3_1_calibrationRoutineCollapsibleButton.setChecked(True)
    self.onShowOpticalAttenuationVsDoseCurve()
    # Fit polynomial on OA VS dose curve
    self.onFitPolynomialToOpticalAttenuationVsDoseCurve()
    # Calibrate
    self.onApplyCalibration()

    # 5. Dose comparison
    slicer.app.processEvents()
    self.logic.delayDisplay('Wait for the slicelet to catch up', 300)
    self.step4_doseComparisonCollapsibleButton.setChecked(True)
    self.step4_1_gammaVolumeSelector.addNode()
    maskSegmentationNodeID = 'vtkMRMLSegmentationNode1'
    maskSegmentID = 'Jar_crop'
    self.step4_maskSegmentationSelector.setCurrentNodeID(maskSegmentationNodeID)
    self.step4_maskSegmentationSelector.setCurrentSegmentID(maskSegmentID)
    self.onGammaDoseComparison()

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
    self.step3_1_calibrationRoutineCollapsibleButton.setChecked(True)

    # Dose comparison
    self.step4_doseComparisonCollapsibleButton.setChecked(True)
    self.step4_1_gammaVolumeSelector.addNode()
    self.step4_maskSegmentationSelector.setCurrentNodeID(maskSegmentationNodeID)
    self.step4_maskSegmentationSelector.setCurrentSegmentID(maskSegmentID)
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

#
# FilmDosimetryAnalysisWidget
#
class FilmDosimetryAnalysisWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self) 

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

# ---------------------------------------------------------------------------
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
