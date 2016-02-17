import os
import time
from __main__ import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging
from math import *
import numpy
from vtk.util import numpy_support

#
# GelDosimetryAnalysisLogic
#
class GelDosimetryAnalysisLogic(ScriptedLoadableModuleLogic):
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
    self.obiToPlanTransformName = 'obiToPlanTransform'
    self.obiToMeasuredTransformName = "obiToMeasuredTransform"

    # Declare member variables (mainly for documentation)
    self.pddDataArray = None
    self.calculatedDose = None # Computed from Pdd usinf RDF and Electron MUs
    self.calibrationDataArray = None
    self.calibrationDataAlignedArray = None # Calibration array registered (X shift) to the Pdd curve (for computation)
    self.calibrationDataAlignedToDisplayArray = None # Calibration array registered (X shift, Y scale, Y shift) to the Pdd curve (for visual alignment)
    self.opticalAttenuationVsDoseFunction = None
    self.calibrationPolynomialCoefficients = None # Calibration polynomial coefficients, highest power first

    # Set logic instance to the global variable that supplies it to the calibration curve alignment minimizer function
    global gelDosimetryLogicInstanceGlobal
    gelDosimetryLogicInstanceGlobal = self

  # ---------------------------------------------------------------------------
  # Show and select DICOM browser
  def onDicomLoad(self):
    slicer.modules.dicom.widgetRepresentation()
    slicer.modules.DICOMWidget.enter()

  # ---------------------------------------------------------------------------
  # Use BRAINS registration to register PlanCT to OBI volume
  # and apply the result to the PlanCT and PlanDose
  def registerObiToPlanCt(self, obiVolumeID, planCtVolumeID, planDoseVolumeID, planStructuresID):
    try:
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      parametersRigid = {}
      parametersRigid["fixedVolume"] = obiVolumeID
      parametersRigid["movingVolume"] = planCtVolumeID
      parametersRigid["useRigid"] = True
      parametersRigid["initializeTransformMode"] = "useGeometryAlign"
      parametersRigid["samplingPercentage"] = 0.0005
      parametersRigid["maximumStepLength"] = 15 # Start with long-range translations
      parametersRigid["relaxationFactor"] = 0.8 # Relax quickly
      parametersRigid["translationScale"] = 1000000 # Suppress rotation
      # parametersRigid["backgroundFillValue"] = -1000.0

      # Set output transform
      obiToPlanTransformNode = slicer.util.getNode(self.obiToPlanTransformName)
      if obiToPlanTransformNode == None:
        obiToPlanTransformNode = slicer.vtkMRMLLinearTransformNode()
        slicer.mrmlScene.AddNode(obiToPlanTransformNode)
        obiToPlanTransformNode.SetName(self.obiToPlanTransformName)
      parametersRigid["linearTransform"] = obiToPlanTransformNode.GetID()

      # Runs the brainsfit registration
      brainsFit = slicer.modules.brainsfit
      cliBrainsFitRigidNode = None
      cliBrainsFitRigidNode = slicer.cli.run(brainsFit, None, parametersRigid)

      waitCount = 0
      while cliBrainsFitRigidNode.GetStatusString() != 'Completed' and waitCount < 200:
        self.delayDisplay( "Register PlanCT to OBI using rigid registration... %d" % waitCount )
        waitCount += 1
      self.delayDisplay("Register PlanCT to OBI using rigid registration finished")
      qt.QApplication.restoreOverrideCursor()

      # Invert output transform (planToObi) to get the desired obiToPlan transform
      obiToPlanTransformNode.GetMatrixTransformToParent().Invert()

      # Apply transform to plan CT and plan dose
      planCtVolumeNode = slicer.mrmlScene.GetNodeByID(planCtVolumeID)
      planCtVolumeNode.SetAndObserveTransformNodeID(obiToPlanTransformNode.GetID())
      if planCtVolumeID != planDoseVolumeID:
        planDoseVolumeNode = slicer.mrmlScene.GetNodeByID(planDoseVolumeID)
        planDoseVolumeNode.SetAndObserveTransformNodeID(obiToPlanTransformNode.GetID())
      else:
        logging.warning('The selected nodes are the same for plan CT and plan dose!')
      # The output transform was automatically applied to the moving image (the OBI), undo that
      obiVolumeNode = slicer.mrmlScene.GetNodeByID(obiVolumeID)
      obiVolumeNode.SetAndObserveTransformNodeID(None)
      
      # Apply transform to plan structures
      planStructuresNode = slicer.mrmlScene.GetNodeByID(planStructuresID)
      if planStructuresNode != None:
        planStructuresNode.SetAndObserveTransformNodeID(obiToPlanTransformNode.GetID())
        
      return obiToPlanTransformNode

    except Exception, e:
      import traceback
      traceback.print_exc()
    
  # ---------------------------------------------------------------------------
  def registerObiToMeasured(self, obiFiducialListID, measuredFiducialListID):
    try:
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      parametersFiducial = {}
      parametersFiducial["fixedLandmarks"] = obiFiducialListID
      parametersFiducial["movingLandmarks"] = measuredFiducialListID
      
      # Create linear transform which will store the registration transform
      obiToMeasuredTransformNode = slicer.util.getNode(self.obiToMeasuredTransformName)
      if obiToMeasuredTransformNode == None:
        obiToMeasuredTransformNode = slicer.vtkMRMLLinearTransformNode()
        slicer.mrmlScene.AddNode(obiToMeasuredTransformNode)
        obiToMeasuredTransformNode.SetName(self.obiToMeasuredTransformName)
      parametersFiducial["saveTransform"] = obiToMeasuredTransformNode.GetID()
      parametersFiducial["transformType"] = "Rigid"

      # Run fiducial registration
      fiducialRegistration = slicer.modules.fiducialregistration
      cliFiducialRegistrationRigidNode = None
      cliFiducialRegistrationRigidNode = slicer.cli.run(fiducialRegistration, None, parametersFiducial)

      waitCount = 0
      while cliFiducialRegistrationRigidNode.GetStatusString() != 'Completed' and waitCount < 200:
        self.delayDisplay( "Register MEASURED to OBI using fiducial registration... %d" % waitCount )
        waitCount += 1
      self.delayDisplay("Register MEASURED to OBI using fiducial registration finished")
      qt.QApplication.restoreOverrideCursor()
      
      # Apply transform to MEASURED fiducials
      measuredFiducialsNode = slicer.mrmlScene.GetNodeByID(measuredFiducialListID)
      measuredFiducialsNode.SetAndObserveTransformNodeID(obiToMeasuredTransformNode.GetID())

      return cliFiducialRegistrationRigidNode.GetParameterAsString('rms')
    except Exception, e:
      import traceback
      traceback.print_exc()

  # ---------------------------------------------------------------------------
  def loadPdd(self, fileName):
    if fileName == None or fileName == '':
      logging.error('Empty PDD file name!')
      return False

    readFile = open(fileName, 'r')
    lines = readFile.readlines()
    doseTable = numpy.zeros([len(lines), 2]) # 2 columns

    rowCounter = 0
    for line in lines:
      firstValue, endOfLine = line.partition(',')[::2]
      if endOfLine == '':
        print "ERROR: File formatted incorrectly!"
        return False
      valueOne = float(firstValue)
      doseTable[rowCounter, 1] = valueOne
      secondValue, lineEnd = endOfLine.partition('\n')[::2]
      if (secondValue == ''):
        print "ERROR: Two values are required per line in the file!"
        return False
      valueTwo = float(secondValue)
      doseTable[rowCounter, 0] = secondValue
      # logging.debug('PDD row ' + rowCounter + ': ' + firstValue + ', ' + secondValue) # For testing
      rowCounter += 1

    logging.info("Pdd data successfully loaded from file '" + fileName + "'")
    self.pddDataArray = doseTable
    return True

  # ---------------------------------------------------------------------------
  def getMeanOpticalAttenuationOfCentralCylinder(self, calibrationVolumeNodeID, centralRadiusMm):
    # Format of output array: the following values are provided for each slice:
    #   depth (cm), mean optical attenuation on the slice at depth, std.dev. of optical attenuation
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    calibrationVolume = slicer.util.getNode(calibrationVolumeNodeID)
    calibrationVolumeImageData = calibrationVolume.GetImageData()
    
    # Get image properties needed for the calculation
    calibrationVolumeSliceThicknessCm = calibrationVolume.GetSpacing()[2] / 10.0
    if calibrationVolume.GetSpacing()[0] != calibrationVolume.GetSpacing()[1]:
      logging.warning('Image data X and Y spacing differ! This is not supported, the mean optical attenuation data may be skewed!')
    calibrationVolumeInPlaneSpacing = calibrationVolume.GetSpacing()[0]

    centralRadiusPixel = int(numpy.ceil(centralRadiusMm / calibrationVolumeInPlaneSpacing))
    if centralRadiusPixel != centralRadiusMm / calibrationVolumeInPlaneSpacing:
      logging.info('Central radius has been rounded up to {0} (original radius is {1}mm = {2}px)'.format(centralRadiusPixel, centralRadiusMm, centralRadiusMm / calibrationVolumeInPlaneSpacing))

    numberOfSlices = calibrationVolumeImageData.GetExtent()[5] - calibrationVolumeImageData.GetExtent()[4] + 1
    centerXCoordinate = (calibrationVolumeImageData.GetExtent()[1] - calibrationVolumeImageData.GetExtent()[0])/2
    centerYCoordinate = (calibrationVolumeImageData.GetExtent()[3] - calibrationVolumeImageData.GetExtent()[2])/2

    # Get image data in numpy array
    calibrationVolumeImageDataAsScalars = calibrationVolumeImageData.GetPointData().GetScalars()
    numpyImageDataArray = numpy_support.vtk_to_numpy(calibrationVolumeImageDataAsScalars)
    numpyImageDataArray = numpy.reshape(numpyImageDataArray, (calibrationVolumeImageData.GetExtent()[1]+1, calibrationVolumeImageData.GetExtent()[3]+1, calibrationVolumeImageData.GetExtent()[5]+1), 'F')
    
    opticalAttenuationOfCentralCylinderTable = numpy.zeros((numberOfSlices, 3))
    sliceNumber = 0
    z = calibrationVolumeImageData.GetExtent()[5]
    zMin = calibrationVolumeImageData.GetExtent()[4]
    while z  >= zMin:
      totalPixels = 0
      totalOpticalAttenuation = 0
      listOfOpticalDensities = []
      meanOpticalAttenuation = 0

      for y in xrange(centerYCoordinate - centralRadiusPixel, centerYCoordinate + centralRadiusPixel):
        for x in xrange(centerXCoordinate - centralRadiusPixel, centerXCoordinate + centralRadiusPixel):
          distanceOfX = abs(x - centerXCoordinate)
          distanceOfY = abs(y - centerYCoordinate)
          if ((distanceOfX + distanceOfY) <= centralRadiusPixel) or ((pow(distanceOfX, 2) + pow(distanceOfY, 2)) <= pow(centralRadiusPixel, 2)):
            currentOpticalAttenuation = numpyImageDataArray[x, y, z]
            listOfOpticalDensities.append(currentOpticalAttenuation)
            totalOpticalAttenuation = totalOpticalAttenuation + currentOpticalAttenuation
            totalPixels+=1
      
      meanOpticalAttenuation = totalOpticalAttenuation / totalPixels
      standardDeviationOpticalAttenuation	= 0
      for currentOpticalAttenuationValue in xrange(totalPixels):
        standardDeviationOpticalAttenuation += pow((listOfOpticalDensities[currentOpticalAttenuationValue] - meanOpticalAttenuation), 2)
      standardDeviationOpticalAttenuation = sqrt(standardDeviationOpticalAttenuation / totalPixels)
      opticalAttenuationOfCentralCylinderTable[sliceNumber, 0] = sliceNumber * calibrationVolumeSliceThicknessCm
      opticalAttenuationOfCentralCylinderTable[sliceNumber, 1] = meanOpticalAttenuation
      opticalAttenuationOfCentralCylinderTable[sliceNumber, 2] = standardDeviationOpticalAttenuation
      # logging.debug('Slice (cm): ' + repr(sliceNumber*calibrationVolumeSliceThicknessCm))
      # logging.debug('  Mean: ' + repr(meanOpticalAttenuation) + '  StdDev: ' + repr(standardDeviationOpticalAttenuation))
      sliceNumber += 1
      z -= 1

    qt.QApplication.restoreOverrideCursor()
    logging.info('CALIBRATION data has been successfully parsed with averaging radius {0}mm ({1}px)'.format(centralRadiusMm, centralRadiusPixel))
    self.calibrationDataArray = opticalAttenuationOfCentralCylinderTable
    return True

  # ---------------------------------------------------------------------------
  def alignPddToCalibration(self):
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
    error = -1.0

    # Check the input arrays
    if self.pddDataArray.size == 0 or self.calibrationDataArray.size == 0:
      logging.error('Pdd or calibration data is empty!')
      return error

    # Discard values of 0 from both ends of the data (it is considered invalid)
    self.calibrationDataCleanedArray = self.calibrationDataArray
    calibrationCleanedNumberOfRows = self.calibrationDataCleanedArray.shape[0]
    while self.calibrationDataCleanedArray[0,1] == 0:
      self.calibrationDataCleanedArray = numpy.delete(self.calibrationDataCleanedArray, 0, 0)
    calibrationCleanedNumberOfRows = self.calibrationDataCleanedArray.shape[0]
    while self.calibrationDataCleanedArray[calibrationCleanedNumberOfRows-1,1] == 0:
      self.calibrationDataCleanedArray = numpy.delete(self.calibrationDataCleanedArray, calibrationCleanedNumberOfRows-1, 0)
      calibrationCleanedNumberOfRows = self.calibrationDataCleanedArray.shape[0]

    # Remove outliers from calibration array
    self.calibrationDataCleanedArray = self.removeOutliersFromArray(self.calibrationDataCleanedArray, 5, 10, 0.0075)[0]

    # Do initial scaling of the calibration array based on the maximum values
    maxPdd = self.findMaxValueInArray(self.pddDataArray)
    maxCalibration = self.findMaxValueInArray(self.calibrationDataCleanedArray)
    initialScaling = maxPdd / maxCalibration
    # logging.debug('Initial scaling factor {0:.4f}'.format(initialScaling))

    # Create the working structures
    self.minimizer = vtk.vtkAmoebaMinimizer()
    self.minimizer.SetFunction(curveAlignmentCalibrationFunction)
    self.minimizer.SetParameterValue("xTrans",0)
    self.minimizer.SetParameterScale("xTrans",2)
    self.minimizer.SetParameterValue("yScale",initialScaling)
    self.minimizer.SetParameterScale("yScale",0.1)
    self.minimizer.SetParameterValue("yTrans",0)
    self.minimizer.SetParameterScale("yTrans",0.2)
    self.minimizer.SetMaxIterations(50)

    self.minimizer.Minimize()
    error = self.minimizer.GetFunctionValue()
    xTrans = self.minimizer.GetParameterValue("xTrans")
    yScale = self.minimizer.GetParameterValue("yScale")
    yTrans = self.minimizer.GetParameterValue("yTrans")

    # Create aligned array
    self.createAlignedCalibrationArray(xTrans, yScale, yTrans)

    qt.QApplication.restoreOverrideCursor()
    logging.info('CALIBRATION successfully aligned with PDD with error={0:.2f} and parameters xTrans={1:.2f}, yScale={2:.2f}, yTrans={3:.2f}'.format(error, xTrans, yScale, yTrans))
    return [error, xTrans, yScale, yTrans]

  # ---------------------------------------------------------------------------
  def createAlignedCalibrationArray(self, xTrans, yScale, yTrans):
    # Create aligned array used for computation
    self.calibrationDataAlignedArray = numpy.zeros([self.pddDataArray.shape[0], 2])
    interpolator = vtk.vtkPiecewiseFunction()
    self.populateInterpolatorForParameters(interpolator, xTrans, 1, 0)
    range = interpolator.GetRange()
    sumSquaredDifference = 0.0
    calibrationAlignedRowIndex = -1
    pddNumberOfRows = self.pddDataArray.shape[0]
    for pddRowIndex in xrange(pddNumberOfRows):
      pddCurrentDepth = self.pddDataArray[pddRowIndex, 0]
      if pddCurrentDepth >= range[0] and pddCurrentDepth <= range[1]:
        calibrationAlignedRowIndex += 1
        self.calibrationDataAlignedArray[calibrationAlignedRowIndex, 0] = pddCurrentDepth
        self.calibrationDataAlignedArray[calibrationAlignedRowIndex, 1] = interpolator.GetValue(pddCurrentDepth)
      else:
        # If the Pdd depth value is out of range then delete the last row (it will never be set, but we need to remove the zeros from the end)
        self.calibrationDataAlignedArray = numpy.delete(self.calibrationDataAlignedArray, self.calibrationDataAlignedArray.shape[0]-1, 0)
  
    # Create aligned array used for display (visual alignment)
    self.calibrationDataAlignedToDisplayArray = numpy.zeros([self.pddDataArray.shape[0], 2])
    interpolator = vtk.vtkPiecewiseFunction()
    self.populateInterpolatorForParameters(interpolator, xTrans, yScale, yTrans)
    range = interpolator.GetRange()
    sumSquaredDifference = 0.0
    calibrationAlignedRowIndex = -1
    pddNumberOfRows = self.pddDataArray.shape[0]
    for pddRowIndex in xrange(pddNumberOfRows):
      pddCurrentDepth = self.pddDataArray[pddRowIndex, 0]
      if pddCurrentDepth >= range[0] and pddCurrentDepth <= range[1]:
        calibrationAlignedRowIndex += 1
        self.calibrationDataAlignedToDisplayArray[calibrationAlignedRowIndex, 0] = pddCurrentDepth
        self.calibrationDataAlignedToDisplayArray[calibrationAlignedRowIndex, 1] = interpolator.GetValue(pddCurrentDepth)
      else:
        # If the Pdd depth value is out of range then delete the last row (it will never be set, but we need to remove the zeros from the end)
        self.calibrationDataAlignedToDisplayArray = numpy.delete(self.calibrationDataAlignedToDisplayArray, self.calibrationDataAlignedToDisplayArray.shape[0]-1, 0)

  # ---------------------------------------------------------------------------
  def removeOutliersFromArray(self, arrayToClean, outlierThreshold, maxNumberOfOutlierIterations, minimumMeanDifferenceInFractionOfMaxValueThreshold):
    # Removes outliers starting from the two ends of a function stored in an array
    # The input array has to have two columns, the first column containing the X values, the second the Y values
    # Parameters:
    #   outlierThreshold: Multiplier of mean of differences. If a value is more than this much different
    #     to its neighbor than it is an outlier
    #   minimumMeanDifferenceInFractionOfMaxValueThreshold: The array is considered not to contain outliers
    #     if the mean differences are less than the maximum value multiplied by this value
    numberOfFoundOutliers = -1
    numberOfIterations = 0

    # Compute average difference between two adjacent points. Go from both ends of the curve,
    # and throw away points that have a difference bigger than the computed average multiplied by N.
    # Do this until no points are thrown away in an iteration OR there are no points left (error)
    # OR the average difference is small enough
    numberOfRows = arrayToClean.shape[0]
    while numberOfIterations < maxNumberOfOutlierIterations and numberOfFoundOutliers != 0 and numberOfRows > 0:
      maxValue = self.findMaxValueInArray(arrayToClean)
      meanDifference = self.computeMeanDifferenceOfNeighborsForArray(arrayToClean)
      # logging.debug('Outlier removal iteration {0}: MeanDifference={1:.2f} (fraction of max value: {2:.4f})'.format(numberOfIterations, meanDifference, meanDifference/maxValue))
      # logging.debug('  Difference at edges: first={0:.2f}  last={1:.2f}'.format(abs(arrayToClean[0,1] - arrayToClean[1,1]), abs(arrayToClean[numberOfRows-1,1] - arrayToClean[numberOfRows-2,1])))
      if meanDifference < maxValue * minimumMeanDifferenceInFractionOfMaxValueThreshold:
        # logging.debug('  MaxValue: {0:.2f} ({1:.4f}), finishing outlier search'.format(maxValue,maxValue*minimumMeanDifferenceInFractionOfMaxValueThreshold))
        break
      numberOfFoundOutliers = 0
      # Remove outliers from the beginning
      while abs(arrayToClean[0,1] - arrayToClean[1,1]) > meanDifference * outlierThreshold:
        # logging.debug('  Deleted first: {0:.2f},{0:.2f}  difference={0:.2f}'.format(arrayToClean[0,0], arrayToClean[0,1], abs(arrayToClean[0,1] - arrayToClean[1,1])))
        arrayToClean = numpy.delete(arrayToClean, 0, 0)
        numberOfFoundOutliers += 1
      # Remove outliers from the end        
      numberOfRows = arrayToClean.shape[0]
      while abs(arrayToClean[numberOfRows-1,1] - arrayToClean[numberOfRows-2,1]) > meanDifference * outlierThreshold:
        # logging.debug('  Deleted last: {0:.2f},{0:.2f}  difference={0:.2f}'.format(arrayToClean[numberOfRows-1,0], arrayToClean[numberOfRows-1,1], abs(arrayToClean[numberOfRows-1,1] - arrayToClean[numberOfRows-2,1])))
        arrayToClean = numpy.delete(arrayToClean, numberOfRows-1, 0)
        numberOfRows = arrayToClean.shape[0]
        numberOfFoundOutliers += 1
      numberOfRows = arrayToClean.shape[0]
      numberOfIterations += 1

    return [arrayToClean, numberOfFoundOutliers]

  # ---------------------------------------------------------------------------
  def computeMeanDifferenceOfNeighborsForArray(self, array):
    numberOfValues = array.shape[0]
    sumDifferences = 0
    for index in xrange(numberOfValues-1):
      sumDifferences += abs(array[index, 1] - array[index+1, 1])
    return sumDifferences / (numberOfValues-1)

  # ---------------------------------------------------------------------------
  def findMaxValueInArray(self, array):
    numberOfValues = array.shape[0]
    maximumValue = -1
    for index in xrange(numberOfValues):
      if array[index, 1] > maximumValue:
        maximumValue = array[index, 1]
    return maximumValue

  # ---------------------------------------------------------------------------
  def populateInterpolatorForParameters(self, interpolator, xTrans, yScale, yTrans):
    calibrationNumberOfRows = self.calibrationDataCleanedArray.shape[0]
    for calibrationRowIndex in xrange(calibrationNumberOfRows):
      xTranslated = self.calibrationDataCleanedArray[calibrationRowIndex, 0] + xTrans
      yScaled = self.calibrationDataCleanedArray[calibrationRowIndex, 1] * yScale
      yStretched = yScaled + yTrans
      interpolator.AddPoint(xTranslated, yStretched)

  # ---------------------------------------------------------------------------
  def computeDoseForMeasuredData(self, rdf, monitorUnits):
    self.calculatedDose = numpy.zeros(self.pddDataArray.shape)
    pddNumberOfRows = self.pddDataArray.shape[0]
    for pddRowIndex in xrange(pddNumberOfRows):
      self.calculatedDose[pddRowIndex, 0] = self.pddDataArray[pddRowIndex, 0]
      self.calculatedDose[pddRowIndex, 1] = self.pddDataArray[pddRowIndex, 1] * rdf * monitorUnits / 10000.0
    return True

  # ---------------------------------------------------------------------------
  def createOpticalAttenuationVsDoseFunction(self, pddRangeMin=-1000, pddRangeMax=1000):
    # Create interpolator for aligned calibration function to allow getting the values for the
    # depths present in the calculated dose function
    interpolator = vtk.vtkPiecewiseFunction()
    calibrationAlignedNumberOfRows = self.calibrationDataAlignedArray.shape[0]
    for calibrationRowIndex in xrange(calibrationAlignedNumberOfRows):
      currentDose = self.calibrationDataAlignedArray[calibrationRowIndex, 0]
      currentOpticalAttenuation = self.calibrationDataAlignedArray[calibrationRowIndex, 1]
      interpolator.AddPoint(currentDose, currentOpticalAttenuation)
    interpolatorRange = interpolator.GetRange()

    # Get the optical attenuation and the dose values from the aligned calibration function and the calculated dose
    self.opticalAttenuationVsDoseFunction = numpy.zeros(self.calculatedDose.shape)
    doseNumberOfRows = self.calculatedDose.shape[0]
    for doseRowIndex in xrange(doseNumberOfRows):
      # Reverse the function so that smallest dose comes first (which decreases with depth)
      currentDepth = self.calculatedDose[doseRowIndex, 0]
      if currentDepth >= interpolatorRange[0] and currentDepth <= interpolatorRange[1] and currentDepth >= pddRangeMin and currentDepth <= pddRangeMax:
        self.opticalAttenuationVsDoseFunction[doseNumberOfRows-doseRowIndex-1, 0] = interpolator.GetValue(currentDepth)
        self.opticalAttenuationVsDoseFunction[doseNumberOfRows-doseRowIndex-1, 1] = self.calculatedDose[doseRowIndex, 1]
      else:
        # If the depth value is out of range then delete the last row (it will never be set, but we need to remove the zeros from the end)
        self.opticalAttenuationVsDoseFunction = numpy.delete(self.opticalAttenuationVsDoseFunction, doseNumberOfRows-doseRowIndex-1, 0)

  # ---------------------------------------------------------------------------
  def fitCurveToOpticalAttenuationVsDoseFunctionArray(self, orderOfFittedPolynomial):
    # Fit polynomial on the cleaned OA vs dose function array
    oaVsDoseNumberOfRows = self.opticalAttenuationVsDoseFunction.shape[0]
    opticalAttenuationData = numpy.zeros((oaVsDoseNumberOfRows))
    doseData = numpy.zeros((oaVsDoseNumberOfRows))
    for rowIndex in xrange(oaVsDoseNumberOfRows):
      opticalAttenuationData[rowIndex] = self.opticalAttenuationVsDoseFunction[rowIndex, 0]
      doseData[rowIndex] = self.opticalAttenuationVsDoseFunction[rowIndex, 1]
    fittingResult = numpy.polyfit(opticalAttenuationData, doseData, orderOfFittedPolynomial, None, True)
    self.calibrationPolynomialCoefficients = fittingResult[0]
    self.fittingResiduals = fittingResult[1]
    logging.info('Coefficients of the fitted polynomial (highest order first): ' + repr(self.calibrationPolynomialCoefficients.tolist()))
    logging.info('  Fitting residuals: ' + repr(self.fittingResiduals[0]))
    return self.fittingResiduals

  # ---------------------------------------------------------------------------
  def exportCalibrationToCSV(self):
    import csv
    import os

    self.outputDir = slicer.app.temporaryPath + '/GelDosimetry'
    if not os.access(self.outputDir, os.F_OK):
      os.mkdir(self.outputDir)

    # Assemble file name for calibration curve points file
    from time import gmtime, strftime
    fileName = self.outputDir + '/' + strftime("%Y%m%d_%H%M%S_", gmtime()) + 'oaVsDosePoints.csv'

    # Write calibration curve points CSV file
    message = ''
    if self.opticalAttenuationVsDoseFunction != None:
      message = 'Optical attenuation to dose values saved in file\n' + fileName + '\n\n'
      with open(fileName, 'w') as fp:
        csvWriter = csv.writer(fp, delimiter=',', lineterminator='\n')
        data = [['OpticalAttenuation','Dose']]
        for oaVsDosePoint in self.opticalAttenuationVsDoseFunction:
          data.append(oaVsDosePoint)
        csvWriter.writerows(data)

    # Assemble file name for polynomial coefficients
    if not hasattr(self, 'calibrationPolynomialCoefficients'):
      message += 'Calibration polynomial has not been fitted to the curve yet!\nClick Fit polynomial in step 4/B to do the fitting.\n'
      return message
    fileName = self.outputDir + '/' + strftime("%Y%m%d_%H%M%S_", gmtime()) + 'CalibrationPolynomialCoefficients.csv'

    # Write calibration curve points CSV file
    message += 'Calibration polynomial coefficients saved in file\n' + fileName + '\n'
    with open(fileName, 'w') as fp:
      csvWriter = csv.writer(fp, delimiter=',', lineterminator='\n')
      data = [['Order','Coefficient']]
      numOfOrders = len(self.calibrationPolynomialCoefficients)
      # Highest order first in the coefficients list
      for orderIndex in xrange(numOfOrders):
        data.append([numOfOrders-orderIndex-1, self.calibrationPolynomialCoefficients[orderIndex]])
      if hasattr(self,'fittingResiduals'):
        data.append(['Residuals', self.fittingResiduals[0]])
      csvWriter.writerows(data)
    
    return message

  # ---------------------------------------------------------------------------
  def calibrate(self, measuredVolumeID):
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
    import time
    start = time.time()

    measuredVolume = slicer.util.getNode(measuredVolumeID)
    calibratedVolume = slicer.vtkMRMLScalarVolumeNode()
    calibratedVolumeName = measuredVolume.GetName() + '_Calibrated'
    calibratedVolumeName = slicer.mrmlScene.GenerateUniqueName(calibratedVolumeName)
    calibratedVolume.SetName(calibratedVolumeName)
    slicer.mrmlScene.AddNode(calibratedVolume)
    measuredImageDataCopy = vtk.vtkImageData()
    measuredImageDataCopy.DeepCopy(measuredVolume.GetImageData())
    calibratedVolume.SetAndObserveImageData(measuredImageDataCopy)
    calibratedVolume.CopyOrientation(measuredVolume)
    if measuredVolume.GetParentTransformNode() != None:
      calibratedVolume.SetAndObserveTransformNodeID(measuredVolume.GetParentTransformNode().GetID())

    coefficients = numpy_support.numpy_to_vtk(self.calibrationPolynomialCoefficients)

    import vtkSlicerGelDosimetryAnalysisAlgoModuleLogic
    if slicer.modules.geldosimetryanalysisalgo.logic().ApplyPolynomialFunctionOnVolume(calibratedVolume, coefficients) == False:
      logging.error('Calibration failed!')
      slicer.mrmlScene.RemoveNode(calibratedVolume)
      return None

    end = time.time()
    qt.QApplication.restoreOverrideCursor()
    logging.info('Calibration of MEASURED volume is successful (time: {0})'.format(end - start))
    return calibratedVolume

#
# Function to minimize for the calibration curve alignment
#
def curveAlignmentCalibrationFunction():
  # Get logic instance
  global gelDosimetryLogicInstanceGlobal
  logic = gelDosimetryLogicInstanceGlobal

  # Transform experimental calibration curve with the current values provided by the minimizer and
  # create piecewise function from the transformed calibration curve to be able to compare with the Pdd
  xTrans = logic.minimizer.GetParameterValue("xTrans")
  yScale = logic.minimizer.GetParameterValue("yScale")
  yTrans = logic.minimizer.GetParameterValue("yTrans")
  interpolator = vtk.vtkPiecewiseFunction()
  logic.populateInterpolatorForParameters(interpolator, xTrans, yScale, yTrans)
  interpolatorRange = interpolator.GetRange()
  # Compute similarity between the Pdd and the transformed calibration curve
  pddNumberOfRows = logic.pddDataArray.shape[0]
  sumSquaredDifference = 0.0
  for pddRowIndex in xrange(pddNumberOfRows):
    pddCurrentDepth = logic.pddDataArray[pddRowIndex, 0]
    pddCurrentDose = logic.pddDataArray[pddRowIndex, 1]
    difference = pddCurrentDose - interpolator.GetValue(pddCurrentDepth)
    if pddCurrentDepth < interpolatorRange[0] or pddCurrentDepth > interpolatorRange[1]:
      pass # Don't count the parts outside the range of the actual transformed calibration curve
    else:
      sumSquaredDifference += difference ** 2

  # logging.debug('Iteration: {0:2}  xTrans: {1:6.2f}  yScale: {2:6.2f}  yTrans: {3:6.2f}    error: {4:.2f}'.format(logic.minimizer.GetIterations(), xTrans, yScale, yTrans, sumSquaredDifference))
  logic.minimizer.SetFunctionValue(sumSquaredDifference)

# Global variable holding the logic instance for the calibration curve minimizer function
gelDosimetryLogicInstanceGlobal = None

# Notes:
# Code snippet to reload logic
# GelDosimetryAnalysisLogic = reload(GelDosimetryAnalysisLogic)
