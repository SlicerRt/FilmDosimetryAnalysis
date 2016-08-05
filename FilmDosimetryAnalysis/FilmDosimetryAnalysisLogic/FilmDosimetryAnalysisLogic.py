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

#
# FilmDosimetryAnalysisLogic
#
class FilmDosimetryAnalysisLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """ 

  def __init__(self):
    # Define constants
    self.saveCalibrationBatchFolderNodeNamePrefix = "Calibration batch"
    self.calibrationVolumeDoseAttributeName = "Dose"
    self.floodFieldAttributeValue = "FloodField"
    self.calibrationBatchSceneFileNamePostfix = "CalibrationBatchScene"
    self.calibrationFunctionFileNamePostfix = "FilmDosimetryCalibrationFunctionCoefficients"
    self.experimentalFilmDoseVolumeNamePostfix = "_Calibrated"

    # Declare member variables (mainly for documentation)
    self.lastAddedRoiNode = None
    self.calibrationCoefficients = [0,0,0,0] # Calibration coefficients [a,b,c,n] in calibration function dose = a + b*OD + c*OD^n
    self.experimentalFilmPixelSpacing = None
    self.calibratedExperimentalFilmVolumeNode = None 
    self.experimentalFloodFieldImageNode = None
    self.experimentalFilmImageNode = None 
    self.planDoseVolumeNode = None
    self.resampledPlanDoseVolumeNode = None
    self.experimentalToDoseTransform = None #TODO: Needed?
    
    self.measuredOpticalDensityToDoseMap = [] #TODO: Make it a real map (need to sort by key where it is created)

    # Set logic instance to the global variable that supplies it to the calibration curve alignment minimizer function
    global filmDosimetryLogicInstanceGlobal
    filmDosimetryLogicInstanceGlobal = self

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

    # Get folder node (create if not exists)
    exportFolderNode = None
    folderNodeName = self.saveCalibrationBatchFolderNodeNamePrefix + strftime(" %Y.%m.%d. %H:%M", gmtime())
    folderNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, None, slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelFolder(), folderNodeName, None)
    # Clone folder node to export scene
    exportFolderNode = calibrationBatchMrmlScene.CopyNode(folderNode)

    #
    # Flood field image

    # Create flood field image subject hierarchy node, add it under folder node
    floodFieldVolumeShNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, folderNode, slicer.vtkMRMLSubjectHierarchyConstants.GetDICOMLevelSeries(), None, floodFieldImageVolumeNode)
    floodFieldVolumeShNode.SetAttribute(self.calibrationVolumeDoseAttributeName, self.floodFieldAttributeValue)
    # Copy both image and SH to exported scene
    exportFloodFieldImageVolumeNode = calibrationBatchMrmlScene.CopyNode(floodFieldImageVolumeNode)
    exportFloodFieldVolumeShNode = calibrationBatchMrmlScene.CopyNode(floodFieldVolumeShNode)
    exportFloodFieldVolumeShNode.SetParentNodeID(exportFolderNode.GetID())
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
    for currentCalibrationDose in calibrationDoseToVolumeNodeMap.keys():
      # Get current calibration image node
      currentCalibrationVolumeNode = calibrationDoseToVolumeNodeMap[currentCalibrationDose]
      # Create calibration image subject hierarchy node, add it under folder node
      calibrationVolumeShNode = slicer.vtkMRMLSubjectHierarchyNode.CreateSubjectHierarchyNode(slicer.mrmlScene, folderNode, slicer.vtkMRMLSubjectHierarchyConstants.GetDICOMLevelSeries(), None, currentCalibrationVolumeNode)
      calibrationVolumeShNode.SetAttribute(self.calibrationVolumeDoseAttributeName, str(currentCalibrationDose))
      # Copy both image and SH to exported scene
      exportCalibrationImageVolumeNode = calibrationBatchMrmlScene.CopyNode(currentCalibrationVolumeNode)
      exportCalibrationVolumeShNode = calibrationBatchMrmlScene.CopyNode(calibrationVolumeShNode)
      exportCalibrationVolumeShNode.SetParentNodeID(exportFolderNode.GetID())
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
    fileName = strftime("%Y%m%d_%H%M%S_", gmtime()) + "_" + self.calibrationBatchSceneFileNamePostfix + ".mrml"
    calibrationBatchMrmlScene.SetURL( os.path.normpath(calibrationBatchDirectoryPath + "/" + fileName) )
    calibrationBatchMrmlScene.Commit()

    # Check if scene file has been created
    if not os.path.isfile(calibrationBatchMrmlScene.GetURL()):
      return "Failed to save calibration batch to " + calibrationBatchDirectoryPath

    calibrationBatchMrmlScene.Clear(1)
    return ""

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
    cloner = slicer.qSlicerSubjectHierarchyCloneNodePlugin()

    # Crop flood field volume by defined ROI into a cloned volume node
    floodFieldShNode = slicer.vtkMRMLSubjectHierarchyNode.GetAssociatedSubjectHierarchyNode(floodFieldImageVolumeNode)
    floodFieldVolumeNodeNodeCloneName = floodFieldImageVolumeNode.GetName() + '_Cropped'
    croppedFloodFieldShNode = cloner.cloneSubjectHierarchyNode(floodFieldShNode, floodFieldVolumeNodeNodeCloneName)
    croppedFloodFieldVolumeNode = croppedFloodFieldShNode.GetAssociatedNode()
    cropVolumeLogic.CropVoxelBased(self.lastAddedRoiNode, floodFieldImageVolumeNode, croppedFloodFieldVolumeNode)

    # Measure average pixel value of the cropped flood field image
    imageStat = vtk.vtkImageAccumulate()
    imageStat.SetInputData(croppedFloodFieldVolumeNode.GetImageData())
    imageStat.Update()
    meanValueFloodField = imageStat.GetMean()[0]
    logging.info("Mean value for flood field image in ROI = " + str(meanValueFloodField))
    # Remove cropped volume
    slicer.mrmlScene.RemoveNode(croppedFloodFieldShNode)
    
    calibrationValues = [] # [entered dose, measured pixel value]   #TODO: Order is just reversed compared to measuredOpticalDensityToDoseMap
    calibrationValues.append([self.floodFieldAttributeValue, meanValueFloodField])

    self.measuredOpticalDensityToDoseMap = []

    #TODO check this OD calculation

    for currentCalibrationDose in calibrationDoseToVolumeNodeMap.keys():
      # Get current calibration image node
      currentCalibrationVolumeNode = calibrationDoseToVolumeNodeMap[currentCalibrationDose]

      # Crop calibration images by last defined ROI into a cloned volume node
      calibrationShNode = slicer.vtkMRMLSubjectHierarchyNode.GetAssociatedSubjectHierarchyNode(currentCalibrationVolumeNode)
      calibrationVolumeNodeNodeCloneName = currentCalibrationVolumeNode.GetName() + '_Cropped'
      croppedCalibrationFilmShNode = cloner.cloneSubjectHierarchyNode(calibrationShNode, calibrationVolumeNodeNodeCloneName)    
      croppedCalibrationFilmVolumeNode = croppedCalibrationFilmShNode.GetAssociatedNode()
      cropVolumeLogic.CropVoxelBased(self.lastAddedRoiNode, currentCalibrationVolumeNode, croppedCalibrationFilmVolumeNode)

      # Measure average pixel value of the cropped calibration image
      imageStat = vtk.vtkImageAccumulate()
      imageStat.SetInputData(croppedCalibrationFilmVolumeNode.GetImageData())
      imageStat.Update()
      meanValue = imageStat.GetMean()[0]
      calibrationValues.append([meanValue, currentCalibrationDose])
      # Remove cropped volume
      slicer.mrmlScene.RemoveNode(croppedCalibrationFilmShNode)

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
    
    return ""

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
  def volumeToNumpyArray(self, currentVolume):
    volumeData = currentVolume.GetImageData()
    volumeDataScalars = volumeData.GetPointData().GetScalars()
    numpyArrayVolume = numpy_support.vtk_to_numpy(volumeDataScalars)
    return numpyArrayVolume

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
      doseArrayGy[rowIndex] = self.applyCalibrationFunctionOnSingleOpticalDensityValue(opticalDensity, self.calibrationCoefficients[0], self.calibrationCoefficients[1], self.calibrationCoefficients[2], self.calibrationCoefficients[3]) / 100.0

      if doseArrayGy[rowIndex] < 0.0:
        doseArrayGy[rowIndex] = 0.0

    return doseArrayGy

  #------------------------------------------------------------------------------
  def applyCalibrationFunctionOnExperimentalFilm(self, experimentalFilmVolumeNode, experimentalFloodFieldVolumeNode):
    if self.calibrationCoefficients is None or len(self.calibrationCoefficients) != 4:
      return  "Invalid calibration function"

    # Perform calibration
    calculatedDoseDoubleArrayGy = self.calculateDoseFromExperimentalFilmImage(experimentalFilmVolumeNode, experimentalFloodFieldVolumeNode)

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
    calculatedDoseVolumeNode = slicer.vtkMRMLScalarVolumeNode()
    calculatedDoseVolumeNode.SetAndObserveImageData(calculatedDoseImageData)
    calculatedDoseVolumeNode.SetName(experimentalFilmVolumeNode.GetName() + self.experimentalFilmDoseVolumeNamePostfix)
    slicer.mrmlScene.AddNode(calculatedDoseVolumeNode)
    calculatedDoseVolumeNode.CreateDefaultDisplayNodes()
    
    # Set same geometry as experimental film
    calculatedDoseVolumeNode.SetOrigin(experimentalFilmVolumeNode.GetOrigin())
    calculatedDoseVolumeNode.SetSpacing(experimentalFilmVolumeNode.GetSpacing())
    calculatedDoseVolumeNode.CopyOrientation(experimentalFilmVolumeNode)

    self.calibratedExperimentalFilmVolumeNode = calculatedDoseVolumeNode

    # Show calibrated and original experimental images
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(experimentalFilmVolumeNode.GetID())
    selectionNode.SetSecondaryVolumeID(calculatedDoseVolumeNode.GetID())
    appLogic.PropagateVolumeSelection()

    layoutManager = slicer.app.layoutManager()
    sliceWidgetNames = ['Red', 'Green', 'Yellow']
    for sliceWidgetName in sliceWidgetNames:
      slice = layoutManager.sliceWidget(sliceWidgetName)
      if slice is None:
        continue
      sliceLogic = slice.sliceLogic()
      compositeNode = sliceLogic.GetSliceCompositeNode()
      compositeNode.SetForegroundOpacity(0.5)

    return ""

  #------------------------------------------------------------------------------
  def cropDoseByROI(self): #TODO: Rename
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
    self.planDoseVolumeNode = croppedNode
    return croppedNode

  #------------------------------------------------------------------------------
  def registerExperimentalFilmToPlanDose(self): #TODO:
    if self.experimentalFilmPixelSpacing is None:
      return "Invalid mm/pixel resolution for the experimental film must be entered"

    # Set auto window/level for dose volume
    self.step2_doseVolumeSelector.currentNode().GetDisplayNode().AutoWindowLevelOn() #TODO
            
    # Set spacing of the experimental film volume
    if self.calibratedExperimentalFilmVolumeNode is None:
      return "Unable to access calibrated experimental film"
    self.calibratedExperimentalFilmVolumeNode.SetSpacing(self.experimentalFilmPixelSpacing, self.experimentalFilmPixelSpacing, self.planDoseVolumeNode.GetSpacing()[1])
    
    # Crop the dose volume by the ROI
    croppedDoseVolumeNode = self.cropDoseByROI()
    
    # TODO just in case I need the resampling code,
    # # Resample cropped dose volume 
    # self.resampledPlanDoseVolumeNode = slicer.vtkMRMLScalarVolumeNode()
    # self.resampledPlanDoseVolumeNode.SetName(self.resampledPlanDoseVolumeNodeName)
    # slicer.mrmlScene.AddNode(self.resampledPlanDoseVolumeNode)
    # resampleParameters = {'outputPixelSpacing':'2,0.4,2', 'interpolationType':'linear', 'InputVolume':self.planDoseVolumeNode.GetID(), 'OutputVolume':self.resampledPlanDoseVolumeNode.GetID()}
    # slicer.cli.run(slicer.modules.resamplescalarvolume, None, resampleParameters, wait_for_completion=True)
    # self.resampledPlanDoseVolumeNode.SetSpacing(2,2,2)
 
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
    self.resampledPlanDoseVolumeNode = newScalarVolume
    newScalarVolume.CopyOrientation(croppedDoseVolumeNode)
        
    # Set up transform pipeline 
    
    experimentalAxialToCoronalRotationTransform = vtk.vtkTransform()
    experimentalAxialToCoronalRotationTransform.RotateWXYZ(90,[1,0,0])
    experimentalAxialToExperimentalCoronalTransformMRML = slicer.vtkMRMLLinearTransformNode()
    experimentalAxialToExperimentalCoronalTransformMRML.SetName(self.experimentalAxialToExperimentalCoronalTransformName)
    slicer.mrmlScene.AddNode(experimentalAxialToExperimentalCoronalTransformMRML)
    experimentalAxialToExperimentalCoronalTransformMRML.SetMatrixTransformToParent(experimentalAxialToCoronalRotationTransform.GetMatrix())
    self.calibratedExperimentalFilmVolumeNode.SetAndObserveTransformNodeID(experimentalAxialToExperimentalCoronalTransformMRML.GetID())
    
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
    self.calibratedExperimentalFilmVolumeNode.GetRASBounds(expBounds)
    doseBounds = [0]*6
    self.resampledPlanDoseVolumeNode.GetRASBounds(doseBounds)
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
    
    slicer.vtkSlicerTransformLogic.hardenTransform(self.calibratedExperimentalFilmVolumeNode)
    
    # Apply BRAINSFit module 
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
    
    parametersRigid = {}
    parametersRigid["fixedVolume"] = self.resampledPlanDoseVolumeNode # current 
    parametersRigid["movingVolume"] = self.calibratedExperimentalFilmVolumeNode
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



# Global variable holding the logic instance for the calibration curve minimizer function
filmDosimetryLogicInstanceGlobal = None

# Notes:
# Code snippet to reload logic
# FilmDosimetryAnalysisLogic = reload(FilmDosimetryAnalysisLogic)
