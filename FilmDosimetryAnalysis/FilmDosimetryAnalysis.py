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
    self.step1_loadDataCollapsibleButton = ctk.ctkCollapsibleButton()
    self.testButton = ctk.ctkCollapsibleButton()

    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.step0_layoutSelectionCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step1_loadDataCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.testButton)

    self.step0_layoutSelectionCollapsibleButton.setProperty('collapsed', False)

    # Create module logic
    self.logic = FilmDosimetryAnalysisLogic.FilmDosimetryAnalysisLogic()

    # Declare member variables (selected at certain steps and then from then on for the workflow)
    self.folderNode = None
    self.batchFolderToParse = None
    # Set up constants
    self.saveCalibrationBatchFolderNodeName = "Calibration batch"
    self.saveDoseCalibrationVolumesName = "Dose calibration volumes"
    self.saveDoseCalibrationImageName = ["Film " + str(maxNumberCalibrationFilms + 1) for maxNumberCalibrationFilms in range(10)]
    self.calibrationVolumeDoseAttributeName = "Dose"
    self.floodFieldAttributeValue = "FloodField"
    self.floodFieldImageShNodeName = "FloodFieldImage"
    self.calibrationVolumeName = "CalibrationVolume"
    self.exportedSceneFileName = slicer.app.temporaryPath + "/exportMrmlScene.mrml"
    self.savedCalibrationVolumeFolderName = "savedCalibrationVolumes"
    self.savedFolderPath = slicer.app.temporaryPath + "/" + self.savedCalibrationVolumeFolderName

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
    self.setup_Step1_LoadData()


    if widgetClass:
      self.widget = widgetClass(self.parent)
    self.parent.show()

  # Disconnect all connections made to the slicelet to enable the garbage collector to destruct the slicelet object on quit
  def disconnect(self):

    self.step0_viewSelectorComboBox.disconnect('activated(int)', self.onViewSelect)
    self.step1_loadImageFilesButton.disconnect('clicked()', self.onLoadImageFilesButton)
    self.step1_numberOfCalibrationFilmsSpinBox.disconnect('valueChanged()', self.onstep1_numberOfCalibrationFilmsSpinBoxValueChanged)
    self.step1_saveCalibrationBatchButton.disconnect('clicked()', self.onSaveCalibrationBatchButton)


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


  def setup_Step1_LoadData(self):
    # Step 1: Load data panel
    self.step1_loadDataCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_loadDataCollapsibleButton.text = "1. Load data"
    self.sliceletPanelLayout.addWidget(self.step1_loadDataCollapsibleButton)

    #Step 1 main background layout
    self.step1_backgroundLayout = qt.QVBoxLayout(self.step1_loadDataCollapsibleButton)



    # step1_topBackgroundSubLayout
    self.step1_topBackgroundSubLayout = qt.QVBoxLayout()
    self.step1_backgroundLayout.addLayout(self.step1_topBackgroundSubLayout)


    # Load data label
    self.step1_loadDataLabel = qt.QLabel("Load all image data involved in the workflow.\nCan either be a new batch of image files, or a saved image batch")
    self.step1_loadDataLabel.wordWrap = True
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


    self.step1_topBackgroundSubLayout.addLayout(self.step1_loadImageButtonLayout)


    # Assign data label
    self.step1_AssignDataLabel = qt.QLabel("Assign loaded data to roles.\nNote: If this selection is changed later then all the following steps need to be performed again")
    self.step1_AssignDataLabel.wordWrap = True
    self.step1_topBackgroundSubLayout.addWidget(self.step1_AssignDataLabel)

    # number of calibration films node selector
    self.step1_numberOfCalibrationFilmsSelectorLayout = qt.QHBoxLayout()
    self.step1_numberOfCalibrationFilmsSpinBox = qt.QSpinBox()
    self.step1_numberOfCalibrationFilmsSpinBox.value = 5
    self.step1_numberOfCalibrationFilmsSpinBox.maximum = 10
    self.step1_numberOfCalibrationFilmsSpinBox.minimum = 0
    self.step1_numberOfCalibrationFilmsSpinBox.enabled = True
    self.step1_numberOfCalibrationFilmsLabelBefore = qt.QLabel('Number of calibration films is: ')
    self.step1_numberOfCalibrationFilmsSelectorLayout.addWidget(self.step1_numberOfCalibrationFilmsLabelBefore)
    self.step1_numberOfCalibrationFilmsSelectorLayout.addWidget(self.step1_numberOfCalibrationFilmsSpinBox)
    self.step1_topBackgroundSubLayout.addLayout(self.step1_numberOfCalibrationFilmsSelectorLayout)


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

    self.step1_middleBackgroundSubLayout = qt.QVBoxLayout()
    self.step1_backgroundLayout.addLayout(self.step1_middleBackgroundSubLayout)


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


      self.step1_calibrationVolumeLayoutList.append(self.step1_doseToImageSelectorRowLayout)
      self.step1_middleBackgroundSubLayout.addLayout(self.step1_doseToImageSelectorRowLayout)


    self.step1_bottomBackgroundSubLayout = qt.QVBoxLayout()
    self.step1_backgroundLayout.addLayout(self.step1_bottomBackgroundSubLayout)

    #calibration button
    self.step1_performCalibrationButton = qt.QPushButton("Perform calibration")
    self.step1_performCalibrationButton.toolTip = "Finds the calibration function"
    self.step1_bottomBackgroundSubLayout.addWidget(self.step1_performCalibrationButton)

    #Save batch button
    self.step1_saveCalibrationBatchButton = qt.QPushButton("Save calibration batch")
    self.step1_saveCalibrationBatchButton.toolTip = "Saves current calibration batch"
    self.step1_bottomBackgroundSubLayout.addWidget(self.step1_saveCalibrationBatchButton)



    self.step1_bottomBackgroundSubLayout.addStretch(1)

    # # Connections
    self.step1_loadImageFilesButton.connect('clicked()', self.onLoadImageFilesButton)
    self.step1_saveCalibrationBatchButton.connect('clicked()', self.onSaveCalibrationBatchButton)
    self.step1_loadSavedImageBatchButton.connect('clicked()', self.onLoadSavedImageBatchButton)

    self.step1_loadImageFilesButton.connect('clicked()', self.onLoadImageFilesButton)
    #TODO add connection for step1_numberOfCalibrationFilmsSpinBox , add disconnect
    self.step1_numberOfCalibrationFilmsSpinBox.connect('valueChanged(int)', self.onstep1_numberOfCalibrationFilmsSpinBoxValueChanged)

    self.sliceletPanelLayout.addStretch(1)


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


  def onLoadImageFilesButton(self):
    slicer.util.openAddDataDialog()


  def fillStep1CalibrationPanel(self,CalibrationVolumeQuantity):

    for doseToImageFormLayout in xrange(len(self.step1_calibrationVolumeLayoutList)-1,-1,-1):

      if self.step1_calibrationVolumeLayoutList[doseToImageFormLayout] != None:
        self.step1_calibrationVolumeLayoutList[doseToImageFormLayout].deleteLater()
        self.step1_calibrationVolumeLayoutList.pop()
      
      if self.step1_calibrationVolumeSelectorLabelBeforeList[doseToImageFormLayout] != None:
        self.step1_calibrationVolumeSelectorLabelBeforeList[doseToImageFormLayout].deleteLater()
        self.step1_calibrationVolumeSelectorLabelBeforeList.pop()
      
      if self.step1_calibrationVolumeSelector_cGySpinBoxList[doseToImageFormLayout] != None:
        self.step1_calibrationVolumeSelector_cGySpinBoxList[doseToImageFormLayout].deleteLater()
        self.step1_calibrationVolumeSelector_cGySpinBoxList.pop()
      
      if self.step1_calibrationVolumeSelector_cGyLabelList[doseToImageFormLayout] != None: 
        self.step1_calibrationVolumeSelector_cGyLabelList[doseToImageFormLayout].deleteLater()
        self.step1_calibrationVolumeSelector_cGyLabelList.pop()
      
      if self.step1_calibrationVolumeSelectorComboBoxList[doseToImageFormLayout] != None:       
        self.step1_calibrationVolumeSelectorComboBoxList[doseToImageFormLayout].deleteLater()
        self.step1_calibrationVolumeSelectorComboBoxList.pop()

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
      
      self.step1_middleBackgroundSubLayout.addLayout(self.step1_doseToImageFormLayout)

      self.step1_calibrationVolumeLayoutList.append(self.step1_doseToImageFormLayout)



  def onstep1_numberOfCalibrationFilmsSpinBoxValueChanged(self):
    self.fillStep1CalibrationPanel(self.step1_numberOfCalibrationFilmsSpinBox.value)

  #------------------------------------------------
  def onSaveCalibrationBatchButton(self):
    self.savedFolderPath = qt.QFileDialog.getExistingDirectory(0, 'Open dir')

    #TODO: Check if folder is empty. If not, warn user that all files be deleted. If they choose yes, remove all files from folder, otherwise return

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

    for currentCalibrationVolumeIndex in xrange(len(self.step1_calibrationVolumeSelectorComboBoxList)):
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

      # Copy calibration image file to save folder
      shutil.copy(calibrationStorageNode.GetFileName(), self.savedFolderPath)

    exportMrmlScene.SetURL(os.path.normpath(self.savedFolderPath + "/exportMrmlScene.mrml" ))
    exportMrmlScene.Commit()

    # Check if scene file has been created
    if os.path.isfile(exportMrmlScene.GetURL()) == True:
      savedSuccessfullyLabel = qt.QLabel( "Calibration volume successfully saved")
      self.step1_bottomBackgroundSubLayout.addWidget(savedSuccessfullyLabel) #TODO: Add label in setup function, here just set text to the label
    else:
      savedUnsuccessfullyLabel = qt.QLabel( "Calibration volume save failed")
      self.step1_bottomBackgroundSubLayout.addWidget(savedUnsuccessfullyLabel) #TODO: Add label in setup function, here just set text to the label

    exportMrmlScene.Clear(1)

  def onLoadSavedImageBatchButton(self):
    savedFolderPath = qt.QFileDialog.getExistingDirectory(0, 'Open dir')  #TODO have it so it searches for the .mrml file in the saved folder

    savedMrmlSceneName = ntpath.basename(self.exportedSceneFileName)
    savedMrmlScenePath = os.path.normpath(savedFolderPath + "/" + savedMrmlSceneName)
    success = slicer.util.loadScene(savedMrmlScenePath)

    #TODO: Indentify flood field image by this attribute value (for attribute self.calibrationVolumeDoseAttributeName): self.floodFieldAttributeValue

  @vtk.calldata_type(vtk.VTK_OBJECT)
  def onNodeAdded(self, caller, event, calldata):
    addedNode = calldata
    if addedNode.IsA("vtkMRMLSubjectHierarchyNode"):
      nodeLevel = addedNode.GetLevel()
      #print "level is ", nodeLevel
      if nodeLevel == slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelFolder():
        self.batchFolderToParse = addedNode
        print "ZZZ batchFolderToParse is ", self.batchFolderToParse


  def onSceneEndImport(self, caller,event):
    print "onSceneEndImport"

    importedNodeCollection = vtk.vtkCollection()

    #importedNodeCollection = slicer.mrmlScene.GetNodes()
    #print "there are ", importedNodeCollection.GetNumberOfItems(), " nodes in the Scene"
    
    self.batchFolderToParse.GetAssociatedChildrenNodes(importedNodeCollection)
    #arrange the GUI to "look loaded" 
    #TODO why do those two give errors? 
    self.fillStep1CalibrationPanel(importedNodeCollection.GetNumberOfItems()-1)
    self.step1_numberOfCalibrationFilmsSpinBox.value = importedNodeCollection.GetNumberOfItems()-1
    
    sHNodeCollection = slicer.mrmlScene.GetNodesByClass('vtkMRMLSubjectHierarchyNode')
    sHNodeCollection.InitTraversal()
    currentNode = sHNodeCollection.GetNextItemAsObject()
    
    while currentNode!= None:
      if (currentNode.GetName() == self.floodFieldImageShNodeName):
        print "flood field"
      
      
      
      currentNode = sHNodeCollection.GetNextItemAsObject()
    
    
    #slicer.util.getNode(self.saveCalibrationBatchFolderNodeName)
    
    
    

  #
  # -------------------------
  # Testing related functions
  # -------------------------
  #


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