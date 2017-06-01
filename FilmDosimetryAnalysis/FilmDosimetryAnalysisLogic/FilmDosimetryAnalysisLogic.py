import os
import time
from __main__ import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
from vtk.util import numpy_support
import logging
import numpy
import SimpleITK as sitk
import shutil
import ntpath
import math
from collections import OrderedDict

#
# FilmDosimetryAnalysisLogic
#
class FilmDosimetryAnalysisLogic(ScriptedLoadableModuleLogic):
  """ Film dosimetry logic.
      Contains functions for film batch load/save, calibration, registration, etc.
  """

  def __init__(self):
    # Define constants
    self.saveCalibrationBatchFolderItemNamePrefix = "Calibration batch"
    self.calibrationVolumeDoseAttributeName = "Dose"
    self.floodFieldAttributeValue = "FloodField"
    self.calibrationBatchSceneFileNamePostfix = "CalibrationBatchScene"
    self.calibrationFunctionFileNamePostfix = "FilmDosimetryCalibrationFunctionCoefficients"
    self.calibratedExperimentalFilmVolumeNamePostfix = "_Calibrated"
    self.croppedPlanDoseVolumeNamePostfix = "_Slice"
    self.paddedForRegistrationVolumeNamePostfix = "_ForRegistration"
    self.numberOfSlicesToPad = 5
    self.experimentalFilmPreAlignmentTransformName = "ExperimentalFilmPreAlignmentTransform"
    self.experimentalFilmScanSetupAligmentTransformName = "ExperimentalFilmScanSetupAligmentTransform"
    self.experimentalFilmToDoseSliceInitializationTransformName = "ExperimentalFilmToDoseSliceInitializationTransform"
    self.experimentalFilmToDoseSliceTransformName = "ExperimentalFilmToDoseSliceTransform"

    # Declare member variables (mainly for documentation)
    self.lastAddedRoiNode = None
    self.calibrationCoefficients = [0,0,0,0] # Calibration coefficients [a,b,c,n] in calibration function dose = a + b*OD + c*OD^n
    self.experimentalFloodFieldVolumeNode = None
    self.experimentalFilmVolumeNode = None
    self.experimentalFilmPixelSpacing = None
    self.experimentalFilmSliceOrientation = ''
    self.experimentalFilmSlicePosition = 0
    self.calculatedDoseDoubleArrayGy = None
    self.calibratedExperimentalFilmVolumeNode = None
    self.paddedCalibratedExperimentalFilmVolumeNode = None
    self.planDoseVolumeNode = None
    self.croppedPlanDoseSliceVolumeNode = None
    self.paddedPlanDoseSliceVolumeNode = None
    self.experimentalFilmPreAlignmentTransformNode = None
    self.experimentalFilmScanSetupAligmentTransformNode = None
    self.experimentalFilmToDoseSliceInitializationTransformNode = None
    self.experimentalFilmToDoseSliceTransformNode = None
    self.maskSegmentationNode = None
    self.maskSegmentID = None
    self.gammaVolumeNode = None

    self.measuredOpticalDensityToDoseMap = [] #TODO: Make it a real map (need to sort by key where it is created)

  # ---------------------------------------------------------------------------
  def setAutoWindowLevelToAllDoseVolumes(self):
    import vtkSlicerRtCommonPython as vtkSlicerRtCommon

    nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLScalarVolumeNode")
    nodes.UnRegister(slicer.mrmlScene)
    for index in range(nodes.GetNumberOfItems()):
      currentVolumeNode = nodes.GetItemAsObject(index)
      if vtkSlicerRtCommon.SlicerRtCommon.IsDoseVolumeNode(currentVolumeNode):
        if currentVolumeNode.GetDisplayNode() is not None:
          currentVolumeNode.GetDisplayNode().AutoWindowLevelOn()
      currentVolumeNode = slicer.mrmlScene.GetNextNodeByClass("vtkMRMLScalarVolumeNode")

  # ---------------------------------------------------------------------------
  def setSliceOutlineOnlyForAllSegmentations(self):
    nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLSegmentationNode")
    nodes.UnRegister(slicer.mrmlScene)
    for index in range(nodes.GetNumberOfItems()):
      currentSegmentationNode = nodes.GetItemAsObject(index)
      if currentSegmentationNode.GetDisplayNode() is not None:
        currentSegmentationNode.GetDisplayNode().SetVisibility2DFill(False)
        currentSegmentationNode.GetDisplayNode().SetVisibility2DOutline(True)
      currentSegmentationNode = slicer.mrmlScene.GetNextNodeByClass("vtkMRMLSegmentationNode")

  #------------------------------------------------------------------------------
  # Step 1

  # ---------------------------------------------------------------------------
  def saveCalibrationBatch(self, calibrationBatchDirectoryPath, floodFieldImageVolumeNode, calibrationDoseToVolumeNodeMap):
    from time import gmtime, strftime

    calibrationBatchDirectoryFileList = os.listdir(calibrationBatchDirectoryPath)
    if len(calibrationBatchDirectoryFileList) > 0:
      return 'Directory is not empty, please choose an empty one'

    if floodFieldImageVolumeNode is None:
      return "Flood field image is not selected!"
    if len(calibrationDoseToVolumeNodeMap) < 1:
      return "Empty calibration does to film map!"

    # Create temporary scene for saving
    calibrationBatchMrmlScene = slicer.vtkMRMLScene()
    calibrationBatchShNode = slicer.vtkMRMLSubjectHierarchyNode()
    calibrationBatchMrmlScene.AddNode(calibrationBatchShNode)

    # Get folder item (create if not exists)
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    exportFolderItem = 0
    folderItemName = self.saveCalibrationBatchFolderItemNamePrefix + strftime(" %Y.%m.%d. %H:%M", gmtime())
    folderItemID = shNode.CreateFolderItem(shNode.GetSceneItemID(), folderItemName)

    # Create folder item in export scene
    exportFolderItemID = calibrationBatchShNode.CreateFolderItem(calibrationBatchShNode.GetSceneItemID(), folderItemName)
    calibrationBatchShNode.SetItemOwnerPluginName(exportFolderItemID, shNode.GetItemOwnerPluginName(folderItemID))

    #
    # Flood field image

    # Setup flood field image subject hierarchy item, add it under folder item
    floodFieldVolumeItemID = shNode.CreateItem(folderItemID, floodFieldImageVolumeNode)
    shNode.SetItemAttribute(floodFieldVolumeItemID, self.calibrationVolumeDoseAttributeName, self.floodFieldAttributeValue)
    # Copy image to exported scene
    exportFloodFieldImageVolumeNode = calibrationBatchMrmlScene.CopyNode(floodFieldImageVolumeNode)
    # Create flood field image item in exported scene
    exportFloodFieldVolumeItemID = calibrationBatchShNode.CreateItem(exportFolderItemID, exportFloodFieldImageVolumeNode)
    calibrationBatchShNode.SetItemAttribute(exportFloodFieldVolumeItemID, self.calibrationVolumeDoseAttributeName, self.floodFieldAttributeValue)
    calibrationBatchShNode.SetItemOwnerPluginName(exportFloodFieldVolumeItemID, shNode.GetItemOwnerPluginName(floodFieldVolumeItemID))
    # Storage node
    floodFieldStorageNode = floodFieldImageVolumeNode.GetStorageNode()
    exportFloodFieldStorageNode = calibrationBatchMrmlScene.CopyNode(floodFieldStorageNode)
    exportFloodFieldImageVolumeNode.SetAndObserveStorageNodeID(exportFloodFieldStorageNode.GetID())
    # Display node
    floodFieldDisplayNode = floodFieldImageVolumeNode.GetDisplayNode()
    exportFloodFieldDisplayNode = calibrationBatchMrmlScene.CopyNode(floodFieldDisplayNode)
    exportFloodFieldImageVolumeNode.SetAndObserveDisplayNodeID(exportFloodFieldDisplayNode.GetID())

    # Copy flood field image file to save folder
    shutil.copy(floodFieldStorageNode.GetFileName(), calibrationBatchDirectoryPath)
    logging.info('Flood field image copied from' + exportFloodFieldStorageNode.GetFileName() + ' to ' + calibrationBatchDirectoryPath)
    exportFloodFieldStorageNode.SetFileName(os.path.normpath(calibrationBatchDirectoryPath + '/' + ntpath.basename(floodFieldStorageNode.GetFileName())))

    #
    # Calibration films
    for currentCalibrationDose in calibrationDoseToVolumeNodeMap:
      # Get current calibration image node
      currentCalibrationVolumeNode = calibrationDoseToVolumeNodeMap[currentCalibrationDose]
      # Setup calibration image subject hierarchy item, add it under folder item
      calibrationVolumeItemID = shNode.CreateItem(folderItemID, currentCalibrationVolumeNode)
      shNode.SetItemAttribute(calibrationVolumeItemID, self.calibrationVolumeDoseAttributeName, str(currentCalibrationDose))
      # Copy image to exported scene
      exportCalibrationImageVolumeNode = calibrationBatchMrmlScene.CopyNode(currentCalibrationVolumeNode)
      # Create calibration image item in exported scene
      exportCalibrationVolumeItemID = calibrationBatchShNode.CreateItem(exportFolderItemID, exportCalibrationImageVolumeNode)
      calibrationBatchShNode.SetItemAttribute(exportCalibrationVolumeItemID, self.calibrationVolumeDoseAttributeName, str(currentCalibrationDose))
      calibrationBatchShNode.SetItemOwnerPluginName(exportCalibrationVolumeItemID, shNode.GetItemOwnerPluginName(calibrationVolumeItemID))
      # Storage node
      calibrationStorageNode = currentCalibrationVolumeNode.GetStorageNode()
      exportCalibrationStorageNode = calibrationBatchMrmlScene.CopyNode(calibrationStorageNode)
      exportCalibrationImageVolumeNode.SetAndObserveStorageNodeID(exportCalibrationStorageNode.GetID())
      # Display node
      calibrationDisplayNode = currentCalibrationVolumeNode.GetDisplayNode()
      exportCalibrationDisplayNode = calibrationBatchMrmlScene.CopyNode(calibrationDisplayNode)
      exportCalibrationImageVolumeNode.SetAndObserveDisplayNodeID(exportCalibrationDisplayNode.GetID())

      # Copy calibration image file to save folder, set location of exportCalibrationStorageNode file to new folder
      shutil.copy(calibrationStorageNode.GetFileName(), calibrationBatchDirectoryPath)
      logging.info('Calibration image copied from' + exportCalibrationStorageNode.GetFileName() + ' to ' + calibrationBatchDirectoryPath)
      exportCalibrationStorageNode.SetFileName(os.path.normpath(calibrationBatchDirectoryPath + '/' + ntpath.basename(calibrationStorageNode.GetFileName())))

    # Save calibration batch scene
    fileName = strftime("%Y%m%d_%H%M%S_", gmtime()) + self.calibrationBatchSceneFileNamePostfix + ".mrml"
    calibrationBatchMrmlScene.SetURL( os.path.normpath(calibrationBatchDirectoryPath + "/" + fileName) )
    calibrationBatchMrmlScene.Commit()

    # Check if scene file has been created
    if not os.path.isfile(calibrationBatchMrmlScene.GetURL()):
      return "Failed to save calibration batch to " + calibrationBatchDirectoryPath

    calibrationBatchMrmlScene.Clear(1)
    return ""

  #------------------------------------------------------------------------------
  def extractRedChannelScalarVolumeFromVectorVolume(self, vectorVolumeNode):
    if vectorVolumeNode is None or not vectorVolumeNode.IsA('vtkMRMLVectorVolumeNode'):
      return vectorVolumeNode

    # Create single-channel volume
    scalarVolumeNode = slicer.vtkMRMLScalarVolumeNode()
    scalarVolumeNode.SetName(vectorVolumeNode.GetName() + "_Red")
    slicer.mrmlScene.AddNode(scalarVolumeNode)

    # Exchange RGB image for single-channel image in subject hierarchy
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    vectorVolumeItemID = shNode.GetItemByDataNode(vectorVolumeNode)
    if vectorVolumeItemID:
      # Move vector volume's item to top level, and add the scalar volume's item under its former parent
      parentItemID = shNode.GetItemParent(vectorVolumeItemID)
      scalarVolumeItemID = shNode.GetItemByDataNode(scalarVolumeNode)
      shNode.SetItemParent(scalarVolumeItemID, parentItemID)
      shNode.SetItemParent(vectorVolumeItemID, shNode.GetSceneItemID)

    # Setup channel extraction
    extract = vtk.vtkImageExtractComponents()
    extract.SetComponents(0) # Red
    extract.SetInputConnection(vectorVolumeNode.GetImageDataConnection())
    # Set single channel image to volume node
    extract.Update()

    scalarVolumeNode.SetAndObserveImageData(extract.GetOutput())
    scalarVolumeNode.SetOrigin(vectorVolumeNode.GetOrigin())
    scalarVolumeNode.SetSpacing(vectorVolumeNode.GetSpacing())
    scalarVolumeNode.CopyOrientation(vectorVolumeNode)

    # Remove RGB image from scene
    slicer.mrmlScene.RemoveNode(vectorVolumeNode)

    return scalarVolumeNode

  #------------------------------------------------------------------------------
  def extractRedChannel(self, input):
    # Input can be dictionary or node
    import types
    if type(input) is OrderedDict:
      newDictionary = {}
      for dose in input:
        newDictionary[dose] = self.extractRedChannelScalarVolumeFromVectorVolume(input[dose])
      return newDictionary
    else:
      return self.extractRedChannelScalarVolumeFromVectorVolume(input)

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
    logging.info("Optimized calibration function coefficients: A=" + str(round(self.calibrationCoefficients[0],4)) + ", B=" + str(round(self.calibrationCoefficients[1],4)) + ", C=" + str(round(self.calibrationCoefficients[2],4)) + ", N=" + str(round(self.calibrationCoefficients[3],4)) + " (mean square error: "  + str(round(bestN[0][0],4)) + ")")

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
  def meanSquaredError(self, a, b, c, n):
    sumMeanSquaredError = 0.0
    for i in xrange(len(self.measuredOpticalDensityToDoseMap)):
      calculatedDose = self.applyCalibrationFunctionOnSingleOpticalDensityValue(self.measuredOpticalDensityToDoseMap[i][0], a, b, c, n)
      sumMeanSquaredError += ((self.measuredOpticalDensityToDoseMap[i][1] - calculatedDose)**2)
    return sumMeanSquaredError / float(len(self.measuredOpticalDensityToDoseMap))

  #------------------------------------------------------------------------------
  def applyCalibrationFunctionOnSingleOpticalDensityValue(self, OD, a, b, c, n):
    return a + b*OD + c*(OD**n)

  # ---------------------------------------------------------------------------
  def performCalibration(self, floodFieldImageVolumeNode, calibrationDoseToVolumeNodeMap):
    if not hasattr(slicer.modules, 'cropvolume'):
      return "Crop Volume module missing!"
    if self.lastAddedRoiNode is None:
      return 'No ROI created for calibration!'
    if floodFieldImageVolumeNode is None:
      return "Flood field image is not selected!"
    if len(calibrationDoseToVolumeNodeMap) < 1:
      return "Empty calibration does to film map!"

    cropVolumeLogic = slicer.modules.cropvolume.logic()

    # Crop flood field volume by defined ROI into a cloned volume node
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    floodFieldItemID = shNode.GetItemByDataNode(floodFieldImageVolumeNode)
    floodFieldVolumeNodeNodeCloneName = floodFieldImageVolumeNode.GetName() + '_Cropped'
    croppedFloodFieldItemID = slicer.vtkSlicerSubjectHierarchyModuleLogic.CloneSubjectHierarchyItem(shNode, floodFieldItemID, floodFieldVolumeNodeNodeCloneName)
    croppedFloodFieldVolumeNode = shNode.GetItemDataNode(croppedFloodFieldItemID)
    cropVolumeLogic.CropVoxelBased(self.lastAddedRoiNode, floodFieldImageVolumeNode, croppedFloodFieldVolumeNode)

    # Measure average pixel value of the cropped flood field image
    imageStat = vtk.vtkImageAccumulate()
    imageStat.SetInputData(croppedFloodFieldVolumeNode.GetImageData())
    imageStat.Update()
    meanValueFloodField = imageStat.GetMean()[0]
    logging.info("Calibration: Mean value for flood field image in ROI = " + str(round(meanValueFloodField,4)))
    # Remove cropped volume
    slicer.mrmlScene.RemoveNode(croppedFloodFieldVolumeNode)

    calibrationValues = [] # [entered dose, measured pixel value]   #TODO: Order is just reversed compared to measuredOpticalDensityToDoseMap
    calibrationValues.append([self.floodFieldAttributeValue, meanValueFloodField])

    self.measuredOpticalDensityToDoseMap = []

    #TODO check this OD calculation

    for currentCalibrationDose in calibrationDoseToVolumeNodeMap:
      # Get current calibration image node
      currentCalibrationVolumeNode = calibrationDoseToVolumeNodeMap[currentCalibrationDose]

      # Crop calibration images by last defined ROI into a cloned volume node
      calibrationFilmItemID = shNode.GetItemByDataNode(currentCalibrationVolumeNode)
      calibrationVolumeNodeNodeCloneName = currentCalibrationVolumeNode.GetName() + '_Cropped'
      croppedCalibrationFilmItemID = slicer.vtkSlicerSubjectHierarchyModuleLogic.CloneSubjectHierarchyItem(shNode, calibrationFilmItemID, calibrationVolumeNodeNodeCloneName)
      croppedCalibrationFilmVolumeNode = shNode.GetItemDataNode(croppedCalibrationFilmItemID)
      cropVolumeLogic.CropVoxelBased(self.lastAddedRoiNode, currentCalibrationVolumeNode, croppedCalibrationFilmVolumeNode)

      # Measure average pixel value of the cropped calibration image
      imageStat = vtk.vtkImageAccumulate()
      imageStat.SetInputData(croppedCalibrationFilmVolumeNode.GetImageData())
      imageStat.Update()
      meanValue = imageStat.GetMean()[0]
      calibrationValues.append([meanValue, currentCalibrationDose])
      # Remove cropped volume
      slicer.mrmlScene.RemoveNode(croppedCalibrationFilmVolumeNode)

      # Optical density calculation
      opticalDensity = math.log10(float(meanValueFloodField)/meanValue)
      if opticalDensity < 0.0:
        opticalDensity = 0.0

      # x = optical density, y = dose
      self.measuredOpticalDensityToDoseMap.append([opticalDensity, currentCalibrationDose])
      logging.info("Calibration: Mean value for calibration image for " + str(round(currentCalibrationDose,4)) + " cGy in ROI = " + str(round(meanValue,4)) + ", OD = " + str(round(opticalDensity,4)))

    self.measuredOpticalDensityToDoseMap.sort(key=lambda doseODPair: doseODPair[1])

    # Perform calibration of OD to dose
    self.findBestFittingCalibrationFunctionCoefficients()

    return ""

  #------------------------------------------------------------------------------
  # Step 3

  #------------------------------------------------------------------------------
  def saveCalibrationFunctionToFile(self, directoryPath):
    # Create directory if does not exist
    if not os.access(directoryPath, os.F_OK):
      os.mkdir(directoryPath)

    # Assemble file name for calibration curve points file
    from time import gmtime, strftime
    fileName = directoryPath + '/' + strftime("%Y%m%d_%H%M%S_", gmtime()) + self.calibrationFunctionFileNamePostfix + ".txt"

    file = open(fileName, 'w')
    file.write('# Film dosimetry calibration function coefficients (' + strftime("%Y.%m.%d. %H:%M:%S", gmtime()) + ')\n')
    file.write('# Coefficients in order: A, B, C, N\n')
    for coefficient in self.calibrationCoefficients:
      file.write(str(coefficient) + '\n')
    file.close()

  #------------------------------------------------------------------------------
  def loadCalibrationFunctionFromFile(self, filePath):
    file = open(filePath, 'r+')
    lines = file.readlines()
    if len(lines) != 6:
      message = "Invalid calibration coefficients file!"
      logging.error(message)
      qt.QMessageBox.critical(None, 'Error', message)
      return

    # Store coefficients
    self.calibrationCoefficients[0] = float(lines[2].rstrip())
    self.calibrationCoefficients[1] = float(lines[3].rstrip())
    self.calibrationCoefficients[2] = float(lines[4].rstrip())
    self.calibrationCoefficients[3] = float(lines[5].rstrip())

    file.close()

  #------------------------------------------------------------------------------
  def applyCalibrationOnExperimentalFilm(self):
    if self.experimentalFilmVolumeNode is None:
      message = "Invalid experimental film selection!"
      logging.error(message)
      return message
    if self.experimentalFloodFieldVolumeNode is None:
      message = "Invalid experimental flood field image selection!"
      logging.error(message)
      return message
    if self.calibrationCoefficients is None or len(self.calibrationCoefficients) != 4:
      message = "Invalid calibration function"
      logging.error(message)
      return message

    experimentalFilmExtent = self.experimentalFilmVolumeNode.GetImageData().GetExtent()

    # Perform calibration
    self.calculatedDoseDoubleArrayGy = self.calculateDoseFromExperimentalFilmImage(self.experimentalFilmVolumeNode, self.experimentalFloodFieldVolumeNode)

    # Convert numpy array to VTK image data
    calculatedDoseVolumeScalarsGy = numpy_support.numpy_to_vtk(self.calculatedDoseDoubleArrayGy,1)
    calculatedDoseImageData = vtk.vtkImageData()
    calculatedDoseImageData.GetPointData().SetScalars(calculatedDoseVolumeScalarsGy)
    calculatedDoseImageData.SetExtent(experimentalFilmExtent[0],experimentalFilmExtent[1], experimentalFilmExtent[2],experimentalFilmExtent[3], 0,0)
    # Create scalar volume node for calibrated film
    self.calibratedExperimentalFilmVolumeNode = slicer.vtkMRMLScalarVolumeNode()
    self.calibratedExperimentalFilmVolumeNode.SetName(self.experimentalFilmVolumeNode.GetName() + self.calibratedExperimentalFilmVolumeNamePostfix)
    slicer.mrmlScene.AddNode(self.calibratedExperimentalFilmVolumeNode)
    self.calibratedExperimentalFilmVolumeNode.CreateDefaultDisplayNodes()
    self.calibratedExperimentalFilmVolumeNode.SetAndObserveImageData(calculatedDoseImageData)
    # Set same geometry as experimental film
    self.calibratedExperimentalFilmVolumeNode.SetOrigin(self.experimentalFilmVolumeNode.GetOrigin())
    self.calibratedExperimentalFilmVolumeNode.SetSpacing(self.experimentalFilmVolumeNode.GetSpacing())
    self.calibratedExperimentalFilmVolumeNode.CopyOrientation(self.experimentalFilmVolumeNode)

    return ""

  #------------------------------------------------------------------------------
  def calculateDoseFromExperimentalFilmImage(self, experimentalFilmVolumeNode, experimentalFloodFieldVolumeNode):
    #TODO: This should be done in SimpleITK
    experimentalFilmArray = self.volumeToNumpyArray(experimentalFilmVolumeNode)
    floodFieldArray = self.volumeToNumpyArray(experimentalFloodFieldVolumeNode)

    if len(experimentalFilmArray) != len(floodFieldArray):
      message = "Experimental and flood field images must be the same size! (Experimental: " + str(len(experimentalFilmArray)) + ", FloodField: " + str(len(floodFieldArray))
      logging.error(message)
      qt.QMessageBox.critical(None, 'Error', message)
      return

    doseArray_cGy = numpy.zeros(len(floodFieldArray))
    for index in xrange(len(experimentalFilmArray)):
      opticalDensity = 0.0
      try:
        opticalDensity = math.log10(float(floodFieldArray[index])/experimentalFilmArray[index])
      except:
        logging.error('Failure when calculating optical density for experimental film image. Failing values: FloodField=' + str(floodFieldArray[index]) + ', PixelValue=' + str(experimentalFilmArray[index]))
        opticalDensity = 0.0
      if opticalDensity <= 0.0:
        opticalDensity = 0.0
      doseArray_cGy[index] = self.applyCalibrationFunctionOnSingleOpticalDensityValue(opticalDensity, self.calibrationCoefficients[0], self.calibrationCoefficients[1], self.calibrationCoefficients[2], self.calibrationCoefficients[3]) / 100.0
      if doseArray_cGy[index] < 0.0:
        doseArray_cGy[index] = 0.0
      # if index%1000==0: # Debugging snippet
        # print('DEBUG: ExpFilm=' + str(experimentalFilmArray[index]) + ', Flood=' + str(floodFieldArray[index]) + ', OD=' + str(opticalDensity) + ', Dose=' + str(doseArray_cGy[index]))

    return doseArray_cGy

  #------------------------------------------------------------------------------
  def volumeToNumpyArray(self, currentVolume):
    volumeData = currentVolume.GetImageData()
    volumeDataScalars = volumeData.GetPointData().GetScalars()
    numpyArrayVolume = numpy_support.vtk_to_numpy(volumeDataScalars)
    return numpyArrayVolume

  #------------------------------------------------------------------------------
  # Step 4

  #------------------------------------------------------------------------------
  def initializeFilmToPlanDoseRegistration(self):
    if self.experimentalFilmPixelSpacing is None:
      return "Invalid mm/pixel resolution for the experimental film must be entered"

    # Set spacing of the experimental film volume
    if self.calibratedExperimentalFilmVolumeNode is None:
      return "Unable to access calibrated experimental film"
    if self.experimentalFilmSliceOrientation == AXIAL:
      self.calibratedExperimentalFilmVolumeNode.SetSpacing(self.experimentalFilmPixelSpacing, self.experimentalFilmPixelSpacing, self.planDoseVolumeNode.GetSpacing()[0])
    elif self.experimentalFilmSliceOrientation == CORONAL:
      self.calibratedExperimentalFilmVolumeNode.SetSpacing(self.experimentalFilmPixelSpacing, self.planDoseVolumeNode.GetSpacing()[1], self.experimentalFilmPixelSpacing)
    elif self.experimentalFilmSliceOrientation == SAGITTAL:
      self.calibratedExperimentalFilmVolumeNode.SetSpacing(self.planDoseVolumeNode.GetSpacing()[2], self.experimentalFilmPixelSpacing, self.experimentalFilmPixelSpacing)

    # Crop the dose volume to the specified slice in the specified orientation
    message = self.cropPlanDoseVolumeToSlice()
    if message != '' or self.croppedPlanDoseSliceVolumeNode is None:
      logging.error("Failed to crop plan dose volume")
      return message

    # Prepare plan dose slice for registration by padding into 5 slices
    message = self.padPlanDoseSliceForRegistration()
    if message != '' or self.paddedPlanDoseSliceVolumeNode is None:
      logging.error("Failed to prepare plan dose volume for registration")
      return message

    # Pre-align calibrated film to plan dose slice
    message = self.preAlignCalibratedFilmWithPlanDoseSlice()
    if message != '':
      logging.error("Failed to pre-align calibrated film with plan dose volume")
      return message

    # Initialize scan setup alignment transform
    message = self.initializeScanSetupAlignmentTransform()
    if message != '':
      logging.error("Failed to initialize scan setup alignment transform for calibrated film")
      return message

    return ''

  #------------------------------------------------------------------------------
  def cropPlanDoseVolumeToSlice(self):
    if self.croppedPlanDoseSliceVolumeNode is not None:
      # Cropping already took place
      return ""

    if self.planDoseVolumeNode is None:
      message = "No plan dose volume is selected!"
      logging.error(message)
      return message

    # Create ROI for cropping dose volume to selected slice
    roiNode = slicer.vtkMRMLAnnotationROINode()
    roiNode.SetName("CropPlanDoseVolumeROI")
    slicer.mrmlScene.AddNode(roiNode)

    #TODO: Support non-axis-aligned volumes too
    bounds = [0]*6
    self.planDoseVolumeNode.GetRASBounds(bounds)
    cropCenter = [(bounds[0]+bounds[1])/2, (bounds[2]+bounds[3])/2, (bounds[4]+bounds[5])/2]
    cropRadius = [abs(bounds[1]-bounds[0])/2, abs(bounds[3]-bounds[2])/2, abs(bounds[5]-bounds[4])/2]
    if self.experimentalFilmSliceOrientation == AXIAL:
      cropCenter[2] = self.experimentalFilmSlicePosition
      cropRadius[2] = 0.5*self.planDoseVolumeNode.GetSpacing()[2]
    elif self.experimentalFilmSliceOrientation == CORONAL:
      cropCenter[1] = self.experimentalFilmSlicePosition
      cropRadius[1] = 0.5*self.planDoseVolumeNode.GetSpacing()[1]
    elif self.experimentalFilmSliceOrientation == SAGITTAL:
      cropCenter[0] = self.experimentalFilmSlicePosition
      cropRadius[0] = 0.5*self.planDoseVolumeNode.GetSpacing()[0]
    roiNode.SetXYZ(cropCenter)
    roiNode.SetRadiusXYZ(cropRadius)

    # Perform cropping
    cropVolumeParameterNode = slicer.vtkMRMLCropVolumeParametersNode()
    slicer.mrmlScene.AddNode(cropVolumeParameterNode)
    cropVolumeParameterNode.SetInputVolumeNodeID(self.planDoseVolumeNode.GetID())
    cropVolumeParameterNode.SetROINodeID(roiNode.GetID())
    cropVolumeParameterNode.SetVoxelBased(False)
    cropLogic = slicer.modules.cropvolume.logic()

    cropLogic.Apply(cropVolumeParameterNode)
    self.croppedPlanDoseSliceVolumeNode = slicer.mrmlScene.GetNodeByID(cropVolumeParameterNode.GetOutputVolumeNodeID())
    croppedPlanDoseVolumeName = slicer.mrmlScene.GenerateUniqueName(self.planDoseVolumeNode.GetName() + self.croppedPlanDoseVolumeNamePostfix)
    self.croppedPlanDoseSliceVolumeNode.SetName(croppedPlanDoseVolumeName)

    # Delete ROI and parameter nodes (comment out only for debugging)
    slicer.mrmlScene.RemoveNode(roiNode)
    slicer.mrmlScene.RemoveNode(cropVolumeParameterNode)

    return ""

  #------------------------------------------------------------------------------
  def padPlanDoseSliceForRegistration(self):
    if self.paddedPlanDoseSliceVolumeNode is not None and self.paddedCalibratedExperimentalFilmVolumeNode is not None:
      # Padding already took place
      return ""

    if self.planDoseVolumeNode is None or self.croppedPlanDoseSliceVolumeNode is None:
      message = "No plan dose volume is selected or cropping to slice failed"
      logging.error(message)
      return message

    # Expand the calibrated image to multiple slices for registration
    paddedCalculatedDoseVolumeArrayGy = numpy.tile(self.calculatedDoseDoubleArrayGy, self.numberOfSlicesToPad)

    # Make film images have the orientation of the dose slice so that processing can be done on the same plane
    experimentalFilmExtent = self.experimentalFilmVolumeNode.GetImageData().GetExtent() # Axial volume, so extent elements 4 and 5 will be 0 and 1, respectively
    croppedPlanDoseExtent = self.croppedPlanDoseSliceVolumeNode.GetImageData().GetExtent()
    croppedDoseSliceDimensions = self.croppedPlanDoseSliceVolumeNode.GetImageData().GetDimensions()
    message = ""
    if self.experimentalFilmSliceOrientation == AXIAL:
      if croppedPlanDoseExtent[4] == croppedPlanDoseExtent[5]:
        # Pad cropped dose volume slice into multiple slices in coronal orientation
        croppedPlanDoseArray = self.volumeToNumpyArray(self.croppedPlanDoseSliceVolumeNode)
        paddedPlanDoseArray = numpy.tile(croppedPlanDoseArray, self.numberOfSlicesToPad)
        paddedPlanDoseImageScalars = numpy_support.numpy_to_vtk(paddedPlanDoseArray, 1)
        paddedPlanDoseImageDataExtent = [0,croppedDoseSliceDimensions[0]-1, 0,croppedDoseSliceDimensions[1]-1, 0,self.numberOfSlicesToPad-1]
      else:
        message = "Invalid cropped axial plan dose slice"

    elif self.experimentalFilmSliceOrientation == CORONAL:
      if croppedPlanDoseExtent[2] != croppedPlanDoseExtent[3]:
        message = "Invalid cropped coronal plan dose slice"
      else:
        # Rotate calibrated experimental film image data to coronal
        coronalExperimentalFilmExtent = [experimentalFilmExtent[0],experimentalFilmExtent[1],0,0,experimentalFilmExtent[2],experimentalFilmExtent[3]]
        calculatedDoseDoubleArrayGy3D = self.calculatedDoseDoubleArrayGy.reshape(1, experimentalFilmExtent[3]-experimentalFilmExtent[2]+1, experimentalFilmExtent[1]-experimentalFilmExtent[0]+1)
        coronalCalculatedDoseDoubleArrayGy3D = numpy.swapaxes(calculatedDoseDoubleArrayGy3D,0,1)
        coronalCalculatedDoseDoubleArrayGy = numpy.ravel(coronalCalculatedDoseDoubleArrayGy3D)
        calibratedExperimentalFilmImageData = self.calibratedExperimentalFilmVolumeNode.GetImageData()
        calibratedExperimentalFilmImageData.GetPointData().SetScalars(numpy_support.numpy_to_vtk(coronalCalculatedDoseDoubleArrayGy,1))
        calibratedExperimentalFilmImageData.SetExtent(coronalExperimentalFilmExtent)
        self.calibratedExperimentalFilmVolumeNode.SetAndObserveImageData(calibratedExperimentalFilmImageData)

        # Rotate padded calibrated experimental film image data to coronal
        paddedCoronalExperimentalFilmExtent = [experimentalFilmExtent[0],experimentalFilmExtent[1],0,self.numberOfSlicesToPad-1,experimentalFilmExtent[2],experimentalFilmExtent[3]]
        paddedCalculatedDoseVolumeArrayGy3D = paddedCalculatedDoseVolumeArrayGy.reshape(self.numberOfSlicesToPad, experimentalFilmExtent[3]-experimentalFilmExtent[2]+1, experimentalFilmExtent[1]-experimentalFilmExtent[0]+1)
        coronalPaddedCalculatedDoseVolumeArrayGy3D = numpy.swapaxes(paddedCalculatedDoseVolumeArrayGy3D,0,1)
        coronalPaddedCalculatedDoseVolumeArrayGy = numpy.ravel(coronalPaddedCalculatedDoseVolumeArrayGy3D)
        paddedCalibratedExperimentalFilmImageData = vtk.vtkImageData()
        paddedCalibratedExperimentalFilmImageData.GetPointData().SetScalars(numpy_support.numpy_to_vtk(coronalPaddedCalculatedDoseVolumeArrayGy,1))
        paddedCalibratedExperimentalFilmImageData.SetExtent(paddedCoronalExperimentalFilmExtent)

        # Pad cropped dose volume slice into multiple slices in coronal orientation
        self.croppedPlanDoseSliceVolumeNode.GetImageData().SetExtent(croppedPlanDoseExtent[0],croppedPlanDoseExtent[1], croppedPlanDoseExtent[4],croppedPlanDoseExtent[5], 0,0) # Set extent to axial so that padding works properly
        croppedPlanDoseArray = self.volumeToNumpyArray(self.croppedPlanDoseSliceVolumeNode)
        paddedPlanDoseArray = numpy.tile(croppedPlanDoseArray, self.numberOfSlicesToPad)
        paddedPlanDoseArrayGy3D = paddedPlanDoseArray.reshape(self.numberOfSlicesToPad, croppedPlanDoseExtent[5]-croppedPlanDoseExtent[4]+1, croppedPlanDoseExtent[1]-croppedPlanDoseExtent[0]+1)
        coronalPaddedPlanDoseArrayGy3D = numpy.swapaxes(paddedPlanDoseArrayGy3D,0,1)
        coronalPaddedPlanDoseArrayGy = numpy.ravel(coronalPaddedPlanDoseArrayGy3D)
        paddedPlanDoseImageScalars = numpy_support.numpy_to_vtk(coronalPaddedPlanDoseArrayGy, 1)
        paddedPlanDoseImageDataExtent = [0,croppedDoseSliceDimensions[0]-1, 0,self.numberOfSlicesToPad-1, 0,croppedDoseSliceDimensions[2]-1]
        self.croppedPlanDoseSliceVolumeNode.GetImageData().SetExtent(croppedPlanDoseExtent) # Restore extent for further processing

    elif self.experimentalFilmSliceOrientation == SAGITTAL:
      if croppedPlanDoseExtent[0] != croppedPlanDoseExtent[1]:
        message = "Invalid cropped sagittal plan dose slice"
      else:
        # Rotate calibrated experimental film image data to sagittal
        sagittalExperimentalFilmExtent = [0,0,experimentalFilmExtent[0],experimentalFilmExtent[1],experimentalFilmExtent[2],experimentalFilmExtent[3]]
        calculatedDoseDoubleArrayGy3D = self.calculatedDoseDoubleArrayGy.reshape(1, experimentalFilmExtent[3]-experimentalFilmExtent[2]+1, experimentalFilmExtent[1]-experimentalFilmExtent[0]+1)
        sagittalCalculatedDoseDoubleArrayGy3D = numpy.swapaxes(numpy.swapaxes(calculatedDoseDoubleArrayGy3D,0,1),1,2)
        sagittalCalculatedDoseDoubleArrayGy = numpy.ravel(sagittalCalculatedDoseDoubleArrayGy3D)
        calibratedExperimentalFilmImageData = self.calibratedExperimentalFilmVolumeNode.GetImageData()
        calibratedExperimentalFilmImageData.GetPointData().SetScalars(numpy_support.numpy_to_vtk(sagittalCalculatedDoseDoubleArrayGy,1))
        calibratedExperimentalFilmImageData.SetExtent(sagittalExperimentalFilmExtent)
        self.calibratedExperimentalFilmVolumeNode.SetAndObserveImageData(calibratedExperimentalFilmImageData)

        # Rotate padded calibrated experimental film image data to sagittal
        paddedSagittalExperimentalFilmExtent = [0,self.numberOfSlicesToPad-1,experimentalFilmExtent[0],experimentalFilmExtent[1],experimentalFilmExtent[2],experimentalFilmExtent[3]]
        paddedCalculatedDoseVolumeArrayGy3D = paddedCalculatedDoseVolumeArrayGy.reshape(self.numberOfSlicesToPad, experimentalFilmExtent[3]-experimentalFilmExtent[2]+1, experimentalFilmExtent[1]-experimentalFilmExtent[0]+1)
        sagittalPaddedCalculatedDoseVolumeArrayGy3D = numpy.swapaxes(numpy.swapaxes(paddedCalculatedDoseVolumeArrayGy3D,0,1),1,2)
        sagittalPaddedCalculatedDoseVolumeArrayGy = numpy.ravel(sagittalPaddedCalculatedDoseVolumeArrayGy3D)
        paddedCalibratedExperimentalFilmImageData = vtk.vtkImageData()
        paddedCalibratedExperimentalFilmImageData.GetPointData().SetScalars(numpy_support.numpy_to_vtk(sagittalPaddedCalculatedDoseVolumeArrayGy,1))
        paddedCalibratedExperimentalFilmImageData.SetExtent(paddedSagittalExperimentalFilmExtent)

        # Pad cropped dose volume slice into multiple slices in sagittal orientation
        self.croppedPlanDoseSliceVolumeNode.GetImageData().SetExtent(croppedPlanDoseExtent[0],croppedPlanDoseExtent[1], croppedPlanDoseExtent[4],croppedPlanDoseExtent[5], 0,0) # Set extent to axial so that padding works properly
        croppedPlanDoseArray = self.volumeToNumpyArray(self.croppedPlanDoseSliceVolumeNode)
        paddedPlanDoseArray = numpy.tile(croppedPlanDoseArray, self.numberOfSlicesToPad)
        paddedPlanDoseArrayGy3D = paddedPlanDoseArray.reshape(self.numberOfSlicesToPad, croppedPlanDoseExtent[5]-croppedPlanDoseExtent[4]+1, croppedPlanDoseExtent[3]-croppedPlanDoseExtent[2]+1)
        sagittalPaddedPlanDoseArrayGy3D = numpy.swapaxes(numpy.swapaxes(paddedPlanDoseArrayGy3D,0,1),1,2)
        sagittalPaddedPlanDoseArrayGy = numpy.ravel(sagittalPaddedPlanDoseArrayGy3D)
        paddedPlanDoseImageScalars = numpy_support.numpy_to_vtk(sagittalPaddedPlanDoseArrayGy, 1)
        paddedPlanDoseImageDataExtent = [0,self.numberOfSlicesToPad-1, 0,croppedDoseSliceDimensions[1]-1, 0,croppedDoseSliceDimensions[2]-1]
        self.croppedPlanDoseSliceVolumeNode.GetImageData().SetExtent(croppedPlanDoseExtent) # Restore extent for further processing

    if message != "":
      logging.error(message)
      return message

    # Create scalar volume node for padded calibrated film
    self.paddedCalibratedExperimentalFilmVolumeNode = slicer.vtkMRMLScalarVolumeNode()
    self.paddedCalibratedExperimentalFilmVolumeNode.SetAndObserveImageData(paddedCalibratedExperimentalFilmImageData)
    self.paddedCalibratedExperimentalFilmVolumeNode.SetName(self.experimentalFilmVolumeNode.GetName() + self.paddedForRegistrationVolumeNamePostfix)
    slicer.mrmlScene.AddNode(self.paddedCalibratedExperimentalFilmVolumeNode)
    self.paddedCalibratedExperimentalFilmVolumeNode.CreateDefaultDisplayNodes()
    # Set same geometry as experimental film
    self.paddedCalibratedExperimentalFilmVolumeNode.SetOrigin(self.calibratedExperimentalFilmVolumeNode.GetOrigin())
    self.paddedCalibratedExperimentalFilmVolumeNode.SetSpacing(self.calibratedExperimentalFilmVolumeNode.GetSpacing())
    self.paddedCalibratedExperimentalFilmVolumeNode.CopyOrientation(self.calibratedExperimentalFilmVolumeNode)
    # Auto window-level
    self.paddedCalibratedExperimentalFilmVolumeNode.CreateDefaultDisplayNodes()
    self.paddedCalibratedExperimentalFilmVolumeNode.GetDisplayNode().AutoWindowLevelOn()

    # Set padded scalars into image data
    paddedPlanDoseImageData = vtk.vtkImageData()
    paddedPlanDoseImageData.GetPointData().SetScalars(paddedPlanDoseImageScalars)
    paddedPlanDoseImageData.SetExtent(paddedPlanDoseImageDataExtent)
    # Create padded dose slice volume
    self.paddedPlanDoseSliceVolumeNode = slicer.vtkMRMLScalarVolumeNode()
    paddedPlanDoseSliceVolumeName = slicer.mrmlScene.GenerateUniqueName(self.planDoseVolumeNode.GetName() + self.paddedForRegistrationVolumeNamePostfix)
    self.paddedPlanDoseSliceVolumeNode.SetName(paddedPlanDoseSliceVolumeName)
    slicer.mrmlScene.AddNode(self.paddedPlanDoseSliceVolumeNode)
    self.paddedPlanDoseSliceVolumeNode.SetAndObserveImageData(paddedPlanDoseImageData)
    self.paddedPlanDoseSliceVolumeNode.CopyOrientation(self.croppedPlanDoseSliceVolumeNode)
    self.paddedPlanDoseSliceVolumeNode.CreateDefaultDisplayNodes()
    self.paddedPlanDoseSliceVolumeNode.GetDisplayNode().AutoWindowLevelOn()
    self.paddedPlanDoseSliceVolumeNode.GetDisplayNode().SetAndObserveColorNodeID(self.croppedPlanDoseSliceVolumeNode.GetDisplayNode().GetColorNodeID())

    return ""

  #------------------------------------------------------------------------------
  def preAlignCalibratedFilmWithPlanDoseSlice(self):
    if self.experimentalFilmPreAlignmentTransformNode is None:
      # Create node for pre-alignment transform if does not exist
      self.experimentalFilmPreAlignmentTransformNode = slicer.vtkMRMLLinearTransformNode()
      self.experimentalFilmPreAlignmentTransformNode.SetName(self.experimentalFilmPreAlignmentTransformName)
      slicer.mrmlScene.AddNode(self.experimentalFilmPreAlignmentTransformNode)
      # Create pre-alignment transform
      experimentalFilmPreAlignmentTransform = vtk.vtkTransform()
    else:
      # Get transform object and if transform node exists
      experimentalFilmPreAlignmentTransform = self.experimentalFilmPreAlignmentTransformNode.GetTransformToParent()

    # Reset transform
    experimentalFilmPreAlignmentTransform.PostMultiply()
    experimentalFilmPreAlignmentTransform.Identity()

    # Align film image center to dose slice center
    expBounds = [0]*6
    self.paddedCalibratedExperimentalFilmVolumeNode.GetRASBounds(expBounds)
    doseBounds = [0]*6
    self.paddedPlanDoseSliceVolumeNode.GetRASBounds(doseBounds)
    doseCenter = [(doseBounds[0]+doseBounds[1])/2, (doseBounds[2]+doseBounds[3])/2, (doseBounds[4]+doseBounds[5])/2]
    expCenter = [(expBounds[0]+expBounds[1])/2, (expBounds[2]+expBounds[3])/2, (expBounds[4]+expBounds[5])/2]
    exp2DoseTranslation = [doseCenter[x] - expCenter[x] for x in xrange(len(doseCenter))]
    experimentalFilmPreAlignmentTransform.Translate(exp2DoseTranslation)

    # Transform calibrated and padded experimental films
    self.experimentalFilmPreAlignmentTransformNode.SetMatrixTransformToParent(experimentalFilmPreAlignmentTransform.GetMatrix())
    self.paddedCalibratedExperimentalFilmVolumeNode.SetAndObserveTransformNodeID(self.experimentalFilmPreAlignmentTransformNode.GetID())
    self.calibratedExperimentalFilmVolumeNode.SetAndObserveTransformNodeID(self.experimentalFilmPreAlignmentTransformNode.GetID())

    return ""

  #------------------------------------------------------------------------------
  def initializeScanSetupAlignmentTransform(self):
    if self.experimentalFilmPreAlignmentTransformNode is None:
      message = "Experimental film pre-alignment transform has not been created"
      logging.error(message)
      return message

    # Create scan setup alignment transform if needed
    if self.experimentalFilmScanSetupAligmentTransformNode is None:
      self.experimentalFilmScanSetupAligmentTransformNode = slicer.vtkMRMLLinearTransformNode()
      self.experimentalFilmScanSetupAligmentTransformNode.SetName(self.experimentalFilmScanSetupAligmentTransformName)
      slicer.mrmlScene.AddNode(self.experimentalFilmScanSetupAligmentTransformNode)

    # Build transform hierarchy
    self.experimentalFilmPreAlignmentTransformNode.SetAndObserveTransformNodeID(self.experimentalFilmScanSetupAligmentTransformNode.GetID())

    # Set pre-alignment and scan setup alignment transform to volumes
    # (in case registration already took place, but needed to be performed again)
    self.paddedCalibratedExperimentalFilmVolumeNode.SetAndObserveTransformNodeID(self.experimentalFilmPreAlignmentTransformNode.GetID())
    self.calibratedExperimentalFilmVolumeNode.SetAndObserveTransformNodeID(self.experimentalFilmPreAlignmentTransformNode.GetID())

    return ""

  #------------------------------------------------------------------------------
  def rotateCalibratedExperimentalFilm(self, clockwise, angleDegrees):
    if self.experimentalFilmScanSetupAligmentTransformNode is None:
      logging.error('Scan setup alignment transform has not been initialized')
      return

    if not clockwise:
      angleDegrees = -1.0 * angleDegrees

    experimentalFilmScanSetupAligmentTransform = self.experimentalFilmScanSetupAligmentTransformNode.GetTransformToParent()
    experimentalFilmScanSetupAligmentTransform.PostMultiply()

    if self.experimentalFilmSliceOrientation == AXIAL:
      # Rotate around the IS axis
      experimentalFilmScanSetupAligmentTransform.RotateWXYZ(angleDegrees,[0,0,1])
    elif self.experimentalFilmSliceOrientation == CORONAL:
      # Rotate around the AP axis
      experimentalFilmScanSetupAligmentTransform.RotateWXYZ(angleDegrees,[0,1,0])
    elif self.experimentalFilmSliceOrientation == SAGITTAL:
      # Rotate around the LR axis
      experimentalFilmScanSetupAligmentTransform.RotateWXYZ(angleDegrees,[1,0,0])

    self.experimentalFilmScanSetupAligmentTransformNode.Modified()

  #------------------------------------------------------------------------------
  def flipCalibratedExperimentalFilm(self, horizontal):
    experimentalFilmScanSetupAligmentTransform = self.experimentalFilmScanSetupAligmentTransformNode.GetTransformToParent()
    experimentalFilmScanSetupAligmentTransform.PostMultiply()

    if self.experimentalFilmSliceOrientation == AXIAL:
      if horizontal:
        # Flip film image in LR direction.
        experimentalFilmScanSetupAligmentTransform.Scale(-1, 1, 1)
      else:
        # Flip film image in AP direction.
        experimentalFilmScanSetupAligmentTransform.Scale(1, -1, 1)
    elif self.experimentalFilmSliceOrientation == CORONAL:
      if horizontal:
        # Flip film image in LR direction.
        experimentalFilmScanSetupAligmentTransform.Scale(-1, 1, 1)
      else:
        # Flip film image in IS direction.
        experimentalFilmScanSetupAligmentTransform.Scale(1, 1, -1)
    elif self.experimentalFilmSliceOrientation == SAGITTAL:
      if horizontal:
        # Flip film image in AP direction.
        experimentalFilmScanSetupAligmentTransform.Scale(1, -1, 1)
      else:
        # Flip film image in IS direction.
        experimentalFilmScanSetupAligmentTransform.Scale(1, 1, -1)

    self.experimentalFilmScanSetupAligmentTransformNode.Modified()

  #------------------------------------------------------------------------------
  def registerExperimentalFilmToPlanDose(self):
    # Setup initialization transform
    if self.experimentalFilmToDoseSliceInitializationTransformNode is None:
      self.experimentalFilmToDoseSliceInitializationTransformNode = slicer.vtkMRMLLinearTransformNode()
      self.experimentalFilmToDoseSliceInitializationTransformNode.SetName(self.experimentalFilmToDoseSliceInitializationTransformName)
      slicer.mrmlScene.AddNode(self.experimentalFilmToDoseSliceInitializationTransformNode)
    preAlignmentInitializationTransformMatrix = vtk.vtkMatrix4x4()
    self.experimentalFilmPreAlignmentTransformNode.GetMatrixTransformToWorld(preAlignmentInitializationTransformMatrix)
    self.experimentalFilmToDoseSliceInitializationTransformNode.SetAndObserveMatrixTransformToParent(preAlignmentInitializationTransformMatrix)

    # Harden initialization transform on the film images. It is necessary to harden, and not
    # simply use the "initialTransform" registration parameter, because it is not taken into account
    # correctly (rotation takes place).
    self.paddedCalibratedExperimentalFilmVolumeNode.SetAndObserveTransformNodeID(self.experimentalFilmToDoseSliceInitializationTransformNode.GetID())
    slicer.vtkSlicerTransformLogic.hardenTransform(self.paddedCalibratedExperimentalFilmVolumeNode)
    self.calibratedExperimentalFilmVolumeNode.SetAndObserveTransformNodeID(self.experimentalFilmToDoseSliceInitializationTransformNode.GetID())
    slicer.vtkSlicerTransformLogic.hardenTransform(self.calibratedExperimentalFilmVolumeNode)

    # Create output transform node
    self.experimentalFilmToDoseSliceTransformNode = slicer.vtkMRMLLinearTransformNode()
    slicer.mrmlScene.AddNode(self.experimentalFilmToDoseSliceTransformNode)
    self.experimentalFilmToDoseSliceTransformNode.SetName(self.experimentalFilmToDoseSliceTransformName)

    # Perform registration with BRAINS
    parametersRigid = {}
    parametersRigid["fixedVolume"] = self.paddedPlanDoseSliceVolumeNode
    parametersRigid["movingVolume"] = self.paddedCalibratedExperimentalFilmVolumeNode
    parametersRigid["useRigid"] = True
    parametersRigid["samplingPercentage"] = 0.05
    parametersRigid["maximumStepLength"] = 15 # Start with long-range translations
    parametersRigid["relaxationFactor"] = 0.8 # Relax quickly
    parametersRigid["translationScale"] = 10000000 # Suppress rotation
    parametersRigid["linearTransform"] = self.experimentalFilmToDoseSliceTransformNode.GetID()

    # Runs the registration
    cliBrainsFitRigidNode = slicer.cli.run(slicer.modules.brainsfit, None, parametersRigid)
    waitCount = 0
    while cliBrainsFitRigidNode.GetStatusString() != 'Completed' and waitCount < 20:
      self.delayDisplay( "Register experimental film to dose using rigid registration... %d" % waitCount )
      waitCount += 1
    self.delayDisplay("Register experimental film to dose using rigid registration finished")

    logging.info("Registration status: " + cliBrainsFitRigidNode.GetStatusString())

    # Set transform to calibrated experimental film
    self.calibratedExperimentalFilmVolumeNode.SetAndObserveTransformNodeID(self.experimentalFilmToDoseSliceTransformNode.GetID())

    # Make sure calibrated film origin is at specified location (in case the pre-alignment transform took it out of plane due to different direction matrices)
    origin = self.calibratedExperimentalFilmVolumeNode.GetOrigin()
    if self.experimentalFilmSliceOrientation == AXIAL:
      self.calibratedExperimentalFilmVolumeNode.SetOrigin(origin[0], origin[1], self.experimentalFilmSlicePosition)
    elif self.experimentalFilmSliceOrientation == CORONAL:
      self.calibratedExperimentalFilmVolumeNode.SetOrigin(origin[0], self.experimentalFilmSlicePosition, origin[2])
    elif self.experimentalFilmSliceOrientation == SAGITTAL:
      self.calibratedExperimentalFilmVolumeNode.SetOrigin(self.experimentalFilmSlicePosition, origin[1], origin[2])

    #TODO: Check AP translation and rotation parameters, warn if transform takes slice off-plane

    return ""



#
# Constants
#
AXIAL = 'Axial'
CORONAL = 'Coronal'
SAGITTAL = 'Sagittal'



# Notes:
# Code snippet to reload logic
# FilmDosimetryAnalysisLogic = reload(FilmDosimetryAnalysisLogic)
