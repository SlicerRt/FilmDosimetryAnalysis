from __main__ import vtk, qt, ctk, slicer
import math

#
# LineProfileLogic
#
class LineProfileLogic():

  def __init__(self):
    self.inputVolumeNodes = []
    self.inputRulerNode = None
    self.rulerObservation = None # pair of ruler object and observation ID
    self.lineResolution = 100
    self.outputPlotSeriesNodes = {} # Map from volume node IDs to plot series nodes
    self.outputTableNode = None
    self.plotChartNode = None

  def __del__(self):
    self.enableAutoUpdate(False)

  def update(self):
    self.updateOutputTable(self.inputVolumeNodes, self.inputRulerNode, self.outputTableNode, self.lineResolution)
    self.updatePlot(self.inputVolumeNodes, self.outputTableNode)
    self.showPlot()

  def enableAutoUpdate(self, toggle):
    if self.rulerObservation:
      self.rulerObservation[0].RemoveObserver(self.rulerObservation[1])
      self.rulerObservation = None
    if toggle and (self.inputRulerNode is not None):
      self.rulerObservation = [self.inputRulerNode, self.inputRulerNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onRulerModified)]

  def onRulerModified(self, caller=None, event=None):
    self.update()

  def getArrayFromTable(self, outputTable, arrayName):
    distanceArray = outputTable.GetTable().GetColumnByName(arrayName)
    if distanceArray:
      return distanceArray
    newArray = vtk.vtkDoubleArray()
    newArray.SetName(arrayName)
    outputTable.GetTable().AddColumn(newArray)
    return newArray

  def computeRulerLength(self,inputRuler):
    import math

    rulerStartPoint_Ruler = [0,0,0]
    rulerEndPoint_Ruler = [0,0,0]
    inputRuler.GetPosition1(rulerStartPoint_Ruler)
    inputRuler.GetPosition2(rulerEndPoint_Ruler)
    rulerStartPoint_Ruler1 = [rulerStartPoint_Ruler[0], rulerStartPoint_Ruler[1], rulerStartPoint_Ruler[2], 1.0]
    rulerEndPoint_Ruler1 = [rulerEndPoint_Ruler[0], rulerEndPoint_Ruler[1], rulerEndPoint_Ruler[2], 1.0]

    rulerToRAS = vtk.vtkMatrix4x4()
    rulerTransformNode = inputRuler.GetParentTransformNode()
    if rulerTransformNode:
      if rulerTransformNode.IsTransformToWorldLinear():
        rulerToRAS.DeepCopy(rulerTransformNode.GetMatrixTransformToParent())
      else:
        logging.warning("Cannot handle non-linear transforms - ignoring transform of the input ruler")

    self.rulerStartPoint_RAS1 = [0,0,0,1]
    self.rulerEndPoint_RAS1 = [0,0,0,1]
    rulerToRAS.MultiplyPoint(rulerStartPoint_Ruler1,self.rulerStartPoint_RAS1)
    rulerToRAS.MultiplyPoint(rulerEndPoint_Ruler1,self.rulerEndPoint_RAS1)

    return math.sqrt(vtk.vtkMath.Distance2BetweenPoints(self.rulerStartPoint_RAS1[0:3],self.rulerEndPoint_RAS1[0:3]))

  def updateOutputTable(self, inputVolumes, inputRuler, outputTable, lineResolution):
    rulerLengthMm = self.computeRulerLength(inputRuler)

    distanceArray = self.getArrayFromTable(outputTable, DISTANCE_ARRAY_NAME)

    probedPointsList = []
    intensityArrayList = []
    for inputVolume in inputVolumes:
      # Need to get the start/end point of the line in the IJK coordinate system
      # as VTK filters cannot take into account direction cosines
      rasToIJK = vtk.vtkMatrix4x4()
      parentToIJK = vtk.vtkMatrix4x4()
      rasToParent = vtk.vtkMatrix4x4()
      inputVolume.GetRASToIJKMatrix(parentToIJK)
      transformNode = inputVolume.GetParentTransformNode()
      if transformNode:
        if transformNode.IsTransformToWorldLinear():
          rasToParent.DeepCopy(transformNode.GetMatrixTransformToParent())
          rasToParent.Invert()
        else:
          print ("Cannot handle non-linear transforms - ignoring transform of the input volume")
      vtk.vtkMatrix4x4.Multiply4x4(parentToIJK, rasToParent, rasToIJK)

      rulerStartPoint_IJK1 = [0,0,0,1]
      rulerEndPoint_IJK1 = [0,0,0,1]
      rasToIJK.MultiplyPoint(self.rulerStartPoint_RAS1,rulerStartPoint_IJK1)
      rasToIJK.MultiplyPoint(self.rulerEndPoint_RAS1,rulerEndPoint_IJK1)

      lineSource=vtk.vtkLineSource()
      lineSource.SetPoint1(rulerStartPoint_IJK1[0],rulerStartPoint_IJK1[1],rulerStartPoint_IJK1[2])
      lineSource.SetPoint2(rulerEndPoint_IJK1[0], rulerEndPoint_IJK1[1], rulerEndPoint_IJK1[2])
      lineSource.SetResolution(lineResolution-1)

      probeFilter=vtk.vtkProbeFilter()
      probeFilter.SetInputConnection(lineSource.GetOutputPort())
      probeFilter.SetSourceData(inputVolume.GetImageData())
      probeFilter.Update()

      probedPoints=probeFilter.GetOutput()
      probedPointsList.append(probedPoints)

      intensityArrayName = INTENSITY_ARRAY_NAME + '_' + inputVolume.GetName()
      intensityArrayList.append(self.getArrayFromTable(outputTable, intensityArrayName))

    # Fill tables
    for probeIndex in range(len(probedPointsList)):
      probedPoints = probedPointsList[probeIndex]
      intensityArray = intensityArrayList[probeIndex]

      # Create arrays of data
      outputTable.GetTable().SetNumberOfRows(probedPoints.GetNumberOfPoints())
      x = range(0, probedPoints.GetNumberOfPoints())
      xStep = rulerLengthMm/(probedPoints.GetNumberOfPoints()-1)

      if probeIndex == 0:
        for i in range(len(x)):
          distanceArray.SetValue(i, x[i]*xStep)

      probedPointScalars = probedPoints.GetPointData().GetScalars()
      for i in range(len(x)):
        intensityArray.SetValue(i, probedPointScalars.GetTuple(i)[0])

  def updatePlot(self, inputVolumeNodes, outputTable, name=None):

    genericAnatomyColorNode = slicer.mrmlScene.GetNodeByID("vtkMRMLColorTableNodeFileGenericAnatomyColors.txt")
    colorIndex = 0
    for inputVolume in self.inputVolumeNodes:
      plotSeriesNode = self.outputPlotSeriesNodes[inputVolume.GetID()]
      # Create plot
      if name is None:
        name = inputVolume.GetName()
      else:
        name += ': ' + inputVolume.GetName()
      plotSeriesNode.SetName(name)
      plotSeriesNode.SetAndObserveTableNodeID(outputTable.GetID())
      plotSeriesNode.SetXColumnName(DISTANCE_ARRAY_NAME)
      plotSeriesNode.SetYColumnName(INTENSITY_ARRAY_NAME + '_' + inputVolume.GetName())
      plotSeriesNode.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeLine)
      plotSeriesNode.SetMarkerStyle(slicer.vtkMRMLPlotSeriesNode.MarkerStyleNone)
      color = [0]*4
      genericAnatomyColorNode.GetColor(colorIndex, color)
      plotSeriesNode.SetColor(color[0], color[1], color[2])
      colorIndex += 1

  def showPlot(self):

    # Create chart and add plot
    if not self.plotChartNode:
      plotChartNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode")
      self.plotChartNode = plotChartNode

    self.plotChartNode.SetXAxisTitle(DISTANCE_ARRAY_NAME+" (mm)")
    self.plotChartNode.SetYAxisTitle(INTENSITY_ARRAY_NAME)
    for inputVolume in self.inputVolumeNodes:
      plotSeriesNode = self.outputPlotSeriesNodes[inputVolume.GetID()]
      self.plotChartNode.AddAndObservePlotSeriesNodeID(plotSeriesNode.GetID())

    # Show plot in layout
    slicer.modules.plots.logic().ShowChartInLayout(self.plotChartNode)
    slicer.app.layoutManager().plotWidget(0).plotView().fitToContent()

DISTANCE_ARRAY_NAME = "Distance"
INTENSITY_ARRAY_NAME = "Intensity"
