import os
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
    self.testButton = ctk.ctkCollapsibleButton()

    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.step0_layoutSelectionCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step1_CalibrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.testButton)

    self.step0_layoutSelectionCollapsibleButton.setProperty('collapsed', False)

    # Create module logic
    self.logic = FilmDosimetryAnalysisLogic.FilmDosimetryAnalysisLogic()

    # Declare member variables (selected at certain steps and then from then on for the workflow)
    self.folderNode = None
    self.batchFolderToParse = None
    self.lastAddedRoiNode = None
    # Set up constants
    self.saveCalibrationBatchFolderNodeName = "Calibration batch"
    self.calibrationVolumeDoseAttributeName = "Dose"
    self.floodFieldAttributeValue = "FloodField"
    self.floodFieldImageShNodeName = "FloodFieldImage"
    self.calibrationVolumeName = "CalibrationVolume"
    self.exportedSceneFileName = slicer.app.temporaryPath + "/exportMrmlScene.mrml"
    self.savedCalibrationVolumeFolderName = "savedCalibrationVolumes"
    self.savedFolderPath = slicer.app.temporaryPath + "/" + self.savedCalibrationVolumeFolderName

    self.maxCalibrationVolumeSelectorsInt = 10
    self.fileLoadingSuccessMessageHeader = "Calibration image loading"
    self.floodFieldFailureMessage = "Flood field image failed to load"
    self.calibrationVolumeLoadFailureMessage = "calibration volume failed to load"

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
    self.step1_CalibrationCollapsibleButton.text = "1. Calibration (optional)"
    self.sliceletPanelLayout.addWidget(self.step1_CalibrationCollapsibleButton)

    # Step 1 main background layout
    self.step1_calibrationLayout = qt.QVBoxLayout(self.step1_CalibrationCollapsibleButton)

    # Step 1 top third sub-layout
    self.step1_topCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_calibrationLayout.addLayout(self.step1_topCalibrationSubLayout)

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
    self.step1_floodFieldImageSelectorComboBox.addEnabled = False
    self.step1_floodFieldImageSelectorComboBox.removeEnabled = False
    self.step1_floodFieldImageSelectorComboBox.setMRMLScene( slicer.mrmlScene )
    self.step1_floodFieldImageSelectorComboBox.setToolTip( "--pick the flood field image file-- CHANGE THIS." ) #TODO
    self.step1_floodFieldImageSelectorComboBoxLabel = qt.QLabel('Flood field image: ')
    self.step1_floodFieldImageSelectorComboBoxLayout.addWidget(self.step1_floodFieldImageSelectorComboBoxLabel)
    self.step1_floodFieldImageSelectorComboBoxLayout.addWidget(self.step1_floodFieldImageSelectorComboBox)
    self.step1_topCalibrationSubLayout.addLayout(self.step1_floodFieldImageSelectorComboBoxLayout)

    self.step1_middleCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_calibrationLayout.addLayout(self.step1_middleCalibrationSubLayout)

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
    self.step1_calibrationLayout.addLayout(self.step1_bottomCalibrationSubLayout)

    self.fillStep1CalibrationPanel(self.step1_numberOfCalibrationFilmsSpinBox.value)

    # Save batch button
    self.step1_saveCalibrationBatchButton = qt.QPushButton("Save calibration batch")
    self.step1_saveCalibrationBatchButton.toolTip = "Saves current calibration batch"
    self.step1_bottomCalibrationSubLayout.addWidget(self.step1_saveCalibrationBatchButton)

    # Add empty row
    self.step1_bottomCalibrationSubLayout.addWidget(qt.QLabel(''))

    # Add ROI button
    self.step1_addRoiButton = qt.QPushButton("Add region")
    self.step1_addRoiButton.setIcon(qt.QIcon(":/Icons/AnnotationROIWithArrow.png"))
    self.step1_addRoiButton.toolTip = "Add ROI (region of interest) that is considered when measuring dose in the calibration images\n\nOnce activated, click in the center of the region to be used for calibration, then do another click to one of the corners. After that the ROI appears and can be adjusted using the colored handles."
    self.step1_bottomCalibrationSubLayout.addWidget(self.step1_addRoiButton)
    
    # Calibration button
    self.step1_performCalibrationButton = qt.QPushButton("Perform calibration")
    self.step1_performCalibrationButton.toolTip = "Finds the calibration function"
    self.step1_bottomCalibrationSubLayout.addWidget(self.step1_performCalibrationButton)

    self.step1_bottomCalibrationSubLayout.addStretch(1)

    # Connections
    self.step1_loadImageFilesButton.connect('clicked()', self.onLoadImageFilesButton)
    self.step1_saveCalibrationBatchButton.connect('clicked()', self.onSaveCalibrationBatchButton)
    self.step1_loadCalibrationBatchButton.connect('clicked()', self.onloadCalibrationBatchButton)
    self.step1_numberOfCalibrationFilmsSpinBox.connect('valueChanged(int)', self.onNumberOfCalibrationFilmsSpinBoxValueChanged)
    self.step1_addRoiButton.connect('clicked()', self.onAddRoiButton)

    self.sliceletPanelLayout.addStretch(1)

  #------------------------------------------------------------------------------
  def setup_step2_CalculateDose(self):
    pass #TODO: Implement

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
    import glob
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
