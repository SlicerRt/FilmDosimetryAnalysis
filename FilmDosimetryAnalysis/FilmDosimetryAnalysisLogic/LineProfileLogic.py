from __main__ import vtk, qt, ctk, slicer
import math

#
# LineProfileLogic
#
class LineProfileLogic:
  """This class should implement all the actual 
  computation done by your module.  The interface 
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget
  """

  def __init__(self):
    self.chartNodeID = None

  def run(self,inputVolume,inputRuler,outputArray,numberOfLineSamples=100):
    """
    Run the actual algorithm
    """

    self.updateOutputArray(inputVolume,inputRuler,outputArray,numberOfLineSamples)
    name = inputVolume.GetName()
    self.updateChart(outputArray,name)

    return True

  def updateOutputArray(self,inputVolume,inputRuler,outputArray,numberOfLineSamples):
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
        print("Cannot handle non-linear transforms - ignoring transform of the input ruler")

    rulerStartPoint_RAS1 = [0,0,0,1]
    rulerEndPoint_RAS1 = [0,0,0,1]
    rulerToRAS.MultiplyPoint(rulerStartPoint_Ruler1,rulerStartPoint_RAS1)
    rulerToRAS.MultiplyPoint(rulerEndPoint_Ruler1,rulerEndPoint_RAS1)        
    
    rulerLengthMm = math.sqrt(vtk.vtkMath.Distance2BetweenPoints(rulerStartPoint_RAS1[0:3],rulerEndPoint_RAS1[0:3]))

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
    rasToIJK.MultiplyPoint(rulerStartPoint_RAS1,rulerStartPoint_IJK1)
    rasToIJK.MultiplyPoint(rulerEndPoint_RAS1,rulerEndPoint_IJK1) 
    
    lineSource = vtk.vtkLineSource()
    lineSource.SetPoint1(rulerStartPoint_IJK1[0],rulerStartPoint_IJK1[1],rulerStartPoint_IJK1[2])
    lineSource.SetPoint2(rulerEndPoint_IJK1[0], rulerEndPoint_IJK1[1], rulerEndPoint_IJK1[2])
    lineSource.SetResolution(numberOfLineSamples-1)

    probeFilter=vtk.vtkProbeFilter()
    probeFilter.SetInputConnection(lineSource.GetOutputPort())
    if vtk.VTK_MAJOR_VERSION <= 5:
      probeFilter.SetSource(inputVolume.GetImageData())
    else:
      probeFilter.SetSourceData(inputVolume.GetImageData())
    probeFilter.Update()

    probedPoints=probeFilter.GetOutput()

    # Create arrays of data  
    a = outputArray.GetArray()
    a.SetNumberOfTuples(probedPoints.GetNumberOfPoints())
    x = xrange(0, probedPoints.GetNumberOfPoints())
    xStep=rulerLengthMm/(probedPoints.GetNumberOfPoints()-1)
    probedPointScalars=probedPoints.GetPointData().GetScalars()
    for i in range(len(x)):
      a.SetComponent(i, 0, x[i]*xStep)
      a.SetComponent(i, 1, probedPointScalars.GetTuple(i)[0])
      a.SetComponent(i, 2, 0)
      
    probedPoints.GetPointData().GetScalars().Modified()

  def updateChart(self,outputArray,name):
    # Get the first ChartView node
    cvn = slicer.util.getNode(pattern='vtkMRMLChartViewNode*')

    # If we already created a chart node and it is still exists then reuse that
    cn = None
    if self.chartNodeID:
      cn = slicer.mrmlScene.GetNodeByID(cvn.GetChartNodeID())
    if not cn:
      cn = slicer.mrmlScene.AddNode(slicer.vtkMRMLChartNode())
      self.chartNodeID = cn.GetID()
      # Configure properties of the Chart
      cn.SetProperty('default', 'title', 'Line profile')
      cn.SetProperty('default', 'xAxisLabel', 'Distance (mm)')
      cn.SetProperty('default', 'yAxisLabel', 'Intensity')  
    
    cn.AddArray(name, outputArray.GetID())
    
    # Set the chart to display
    cvn.SetChartNodeID(cn.GetID())
    cvn.Modified()

  def computeRulerLength(self,inputRuler):
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
        print("Cannot handle non-linear transforms - ignoring transform of the input ruler")

    rulerStartPoint_RAS1 = [0,0,0,1]
    rulerEndPoint_RAS1 = [0,0,0,1]
    rulerToRAS.MultiplyPoint(rulerStartPoint_Ruler1,rulerStartPoint_RAS1)
    rulerToRAS.MultiplyPoint(rulerEndPoint_Ruler1,rulerEndPoint_RAS1)        
    
    return math.sqrt(vtk.vtkMath.Distance2BetweenPoints(rulerStartPoint_RAS1[0:3],rulerEndPoint_RAS1[0:3]))
