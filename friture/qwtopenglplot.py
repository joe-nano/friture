#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""PyQt4 port of the opengl/hellogl example from Qt v4.x"""

import sys

from PyQt4 import QtCore, QtGui, QtOpenGL, Qt
from friture.audiobackend import SAMPLING_RATE
from friture.plotting.scaleWidget import VerticalScaleWidget, HorizontalScaleWidget
from friture.plotting.scaleDivision import ScaleDivision
from friture.plotting.coordinateTransform import CoordinateTransform

try:
    from OpenGL import GL
except ImportError:
    app = QtGui.QApplication(sys.argv)
    QtGui.QMessageBox.critical(None, "OpenGL hellogl",
            "PyOpenGL must be installed to run this example.")
    sys.exit(1)

from numpy import zeros, ones, log10, hstack, array, floor, mean, where, rint, inf
import numpy as np

# The peak decay rates (magic goes here :).
PEAK_DECAY_RATE = 1.0 - 3E-6
# Number of cycles the peak stays on hold before fall-off.
PEAK_FALLOFF_COUNT = 32 # default : 16

class GLPlotWidget(QtGui.QWidget):
    def __init__(self, parent, sharedGLWidget, logger=None):
        super(GLPlotWidget, self).__init__()

        self.peaks_enabled = True
        self.peak = zeros((3,))
        self.peak_int = zeros((3,))
        self.peak_decay = ones((3,))*PEAK_DECAY_RATE
        
        self.x1 = array([0.1, 0.5, 1.])
        self.x2 = array([0.5, 1., 2.])
        self.y = array([0., 0., 0.])

        self.fmax = 1e3
        
        self.transformed_x1 = self.x1
        self.transformed_x2 = self.x2
        
        self.baseline_transformed = False
        self.baseline = 0.

        self.needtransform = False

        self.verticalScaleDivision = ScaleDivision(0, 1, 100)
        self.verticalScaleTransform = CoordinateTransform(0, 1, 100, 0, 0)

        self.verticalScale = VerticalScaleWidget(self, self.verticalScaleDivision, self.verticalScaleTransform)
        self.verticalScale.setTitle("PSD (dB)")

        self.horizontalScaleDivision = ScaleDivision(0, 22000, 100)
        self.horizontalScaleTransform = CoordinateTransform(0, 22000, 100, 0, 0)

        self.horizontalScale = HorizontalScaleWidget(self, self.horizontalScaleDivision, self.horizontalScaleTransform)
        self.horizontalScale.setTitle("Frequency (Hz)")

        self.glWidget = GLWidget(self, sharedGLWidget, self.verticalScaleTransform, self.horizontalScaleTransform)

        plotLayout = QtGui.QGridLayout()
        plotLayout.setSpacing(0)
        plotLayout.setContentsMargins(0, 0, 0, 0)
        plotLayout.addWidget(self.verticalScale, 0, 0)
        plotLayout.addWidget(self.glWidget, 0, 1)
        plotLayout.addWidget(self.horizontalScale, 1, 1)
        
        self.setLayout(plotLayout)

    def setlinfreqscale(self):
        self.logx = False

        self.horizontalScaleTransform.setLinear()
        self.horizontalScaleDivision.setLinear()

        self.needtransform = True
        self.draw()

    def setlogfreqscale(self):
        self.logx = True

        self.horizontalScaleTransform.setLogarithmic()
        self.horizontalScaleDivision.setLogarithmic()

        self.needtransform = True
        self.draw()

    def setfreqrange(self, minfreq, maxfreq):
        self.xmin = minfreq
        self.xmax = maxfreq

        self.horizontalScaleTransform.setRange(minfreq, maxfreq)
        self.horizontalScaleDivision.setRange(minfreq, maxfreq)

        # notify that sizeHint has changed (this should be done with a signal emitted from the scale division to the scale bar)
        self.horizontalScale.scaleBar.updateGeometry()


        self.needtransform = True
        self.draw()

    def setspecrange(self, spec_min, spec_max):
        self.verticalScaleTransform.setRange(spec_min, spec_max)
        self.verticalScaleDivision.setRange(spec_min, spec_max)

        # notify that sizeHint has changed (this should be done with a signal emitted from the scale division to the scale bar)
        self.verticalScale.scaleBar.updateGeometry()

        self.needtransform = True
        self.draw()

    def setweighting(self, weighting):
        if weighting is 0:
            title = "PSD (dB)"
        elif weighting is 1:
            title = "PSD (dB A)"
        elif weighting is 2:
            title = "PSD (dB B)"
        else:
            title = "PSD (dB C)"

        self.verticalScale.setTitle(title)
        self.needtransform = True
        self.draw()
    
    def setShowFreqLabel(self, showFreqLabel):
        self.glWidget.setShowFreqLabel(showFreqLabel)

    def set_peaks_enabled(self, enabled):
        self.peaks_enabled = enabled
    
    def set_baseline_displayUnits(self, baseline):
        self.baseline_transformed = False
        self.baseline = baseline

    def set_baseline_dataUnits(self, baseline):
        self.baseline_transformed = True
        self.baseline = baseline

    def setdata(self, x, y, fmax):
        x1 = zeros(x.shape)
        x2 = zeros(x.shape)
        x1[0] = 1e-10
        x1[1:] = (x[1:] + x[:-1])/2.
        x2[:-1] = x1[1:]
        x2[-1] = float(SAMPLING_RATE/2)
        
        if len(x1) <> len(self.x1):
            self.needtransform = True
            # save data for resizing
            self.x1 = x1
            self.x2 = x2
        
        # save data for resizing
        self.y = y
        self.fmax = fmax
        
        self.draw()
        
        # TODO :
        # - Fix peaks loss when resizing
        # - optimize if further needed

    def pre_tree_rebin(self, x1, x2):
        if len(x2) == 0:
            # enf of recursion !
            return x1, x2, 0
        
        n0 = max(where(x2 - x1 >= 0.5)[0])
        
        # leave untouched the frequency bins that span more than half a pixel
        # and first make sure that what will be left can be decimated by two
        rest = len(x2) - n0 - ((len(x2) - n0)//2)*2
        
        n0 += rest
        
        x1_0 = x1[:n0]
        x2_0 = x2[:n0]
        
        # decimate the rest
        x1_2 = x1[n0::2]
        x2_2 = x2[n0 + 1::2]
        
        # recursive !!
        x1_2, x2_2, n2 = self.pre_tree_rebin(x1_2, x2_2)
        
        if n2 == 0.:
            n = [n0]
        else:
            n = [n0] + [i*2 + n0 for i in n2]
            
        x1 = hstack((x1_0, x1_2))
        x2 = hstack((x2_0, x2_2))
        
        return x1, x2, n

    def tree_rebin(self, y, ns, N):
        y2 = zeros(N)

        n = 0
        for i in range(len(ns)-1):
            y3 = y[ns[i]:ns[i+1]]
            d = 2**i
            l = len(y3)/d
            y3.shape = (l, d)

            # Note: the FFT spectrum is mostly used to identify frequency content
            # ans _peaks_ are particularly interesting (e.g. feedback frequencies)
            # so we display the _max_ instead of the mean of each bin 
            #y3 = mean(y3, axis=1)
            #y3 = (y3[::2] + y3[1::2])*0.5
            
            y3 = np.max(y3, axis=1)

            y2[n:n+len(y3)] = y3
            n += l
        
        return y2

    def draw(self):
        if self.needtransform:
            self.verticalScaleDivision.setLength(self.glWidget.height())
            self.verticalScaleTransform.setLength(self.glWidget.height())
            startBorder, endBorder = self.verticalScale.spacingBorders()
            self.verticalScaleTransform.setBorders(startBorder, endBorder)

            self.verticalScale.update()

            self.horizontalScaleDivision.setLength(self.glWidget.width())
            self.horizontalScaleTransform.setLength(self.glWidget.width())
            startBorder, endBorder = self.horizontalScale.spacingBorders()
            self.horizontalScaleTransform.setBorders(startBorder, endBorder)

            self.horizontalScale.update()

            # transform the coordinates only when needed
            x1 = self.horizontalScaleTransform.toScreen(self.x1)
            x2 = self.horizontalScaleTransform.toScreen(self.x2)
            
            if self.logx:
                self.transformed_x1, self.transformed_x2, n = self.pre_tree_rebin(x1, x2)
                self.n = [0] + n
                self.N = 0
                for i in range(len(self.n)-1):
                    self.N += (self.n[i+1] - self.n[i])/2**i

            else:
                self.transformed_x1 = x1
                self.transformed_x2 = x2
            
            xMajorTick = self.horizontalScaleDivision.majorTicks()
            xMinorTick = self.horizontalScaleDivision.minorTicks()
            yMajorTick = self.verticalScaleDivision.majorTicks()
            yMinorTick = self.verticalScaleDivision.minorTicks()
            self.glWidget.setGrid(self.horizontalScaleTransform.toScreen(array(xMajorTick)),
                                  self.horizontalScaleTransform.toScreen(array(xMinorTick)),
                                  self.verticalScaleTransform.toScreen(array(yMajorTick)),
                                  self.verticalScaleTransform.toScreen(array(yMinorTick))
                                  )

            self.needtransform = False
        
        # for easier reading
        x1 = self.transformed_x1
        x2 = self.transformed_x2
        
        if self.logx:
            y = self.tree_rebin(self.y, self.n, self.N)
        else:
            n = floor(1./(x2[2] - x1[1]))
            if n>0:
                new_len = len(self.y)//n
                rest = len(self.y) - new_len*n
                
                new_y = self.y[:-rest]
                new_y.shape = (new_len, n)
                y = mean(new_y, axis = 1)
                
                x1 = x1[:-rest:n]
                x2 = x2[n::n]
            else:
                y = self.y

        if self.peaks_enabled:
            self.compute_peaks(y)
        
        transformed_y = self.verticalScaleTransform.toScreen(y)
        
        Ones = ones(x1.shape)
        Ones_shaded = Ones #.copy()
        # FIXME : the following would give a satisfying result if the
        # bins were one pixel wide at minimum => Need to to a rounding
        # to pixels
        #w = x2 - x1
        #i = where(w<1.)[0]
        #if len(i)>0:
        #    Ones_shaded[:i[0]:2] = 1.2            
        
        if self.peaks_enabled:
            transformed_peak = self.verticalScaleTransform.toScreen(self.peak)
        
            n = x1.size

            # FIXME should be done conditionally to need_transform
            x1_with_peaks = zeros((2*n))
            x2_with_peaks = zeros((2*n))
            y_with_peaks = zeros((2*n))
            r_with_peaks = zeros((2*n))
            g_with_peaks = zeros((2*n))
            b_with_peaks = zeros((2*n))

            x1_with_peaks[:n] = x1
            x1_with_peaks[n:] = x1

            x2_with_peaks[:n] = x2
            x2_with_peaks[n:] = x2

            y_with_peaks[:n] = transformed_peak
            y_with_peaks[n:] = transformed_y

            r_with_peaks[:n] = 1.*Ones
            r_with_peaks[n:] = 0.*Ones

            g_with_peaks[:n] = 1. - self.peak_int
            g_with_peaks[n:] = 0.5*Ones_shaded

            b_with_peaks[:n] = 1. - self.peak_int
            b_with_peaks[n:] = 0.*Ones
        else:
            x1_with_peaks = x1
            x2_with_peaks = x2
            y_with_peaks = transformed_y
            r_with_peaks = 0.*Ones
            g_with_peaks = 0.5*Ones_shaded
            b_with_peaks = 0.*Ones
        
        if self.baseline_transformed:
            # used for dual channel response measurement
            baseline = self.verticalScaleTransform.toScreen(self.baseline)
        else:
            # used for single channel analysis
            baseline = self.baseline

        xmax = self.horizontalScaleTransform.toScreen(self.fmax)
        self.glWidget.setfmax(xmax, self.fmax)

        self.setQuadData(x1_with_peaks, y_with_peaks, x2_with_peaks - x1_with_peaks, baseline, r_with_peaks, g_with_peaks, b_with_peaks)


    # redraw when the widget is resized to update coordinates transformations
    def resizeEvent(self, event):
        self.needtransform = True
        self.draw()
        
    def compute_peaks(self, y):
        if len(self.peak) <> len(y):
            y_ones = ones(y.shape)
            self.peak = y_ones*(-500.)
            self.peak_int = zeros(y.shape)
            self.peak_decay = y_ones * 20. * log10(PEAK_DECAY_RATE) * 5000

        mask1 = (self.peak < y)
        mask2 = (-mask1)
        mask2_a = mask2 * (self.peak_int < 0.2)
        mask2_b = mask2 * (self.peak_int >= 0.2)

        self.peak[mask1] = y[mask1]
        self.peak[mask2_a] = self.peak[mask2_a] + self.peak_decay[mask2_a]
		
        self.peak_decay[mask1] = 20. * log10(PEAK_DECAY_RATE) * 5000
        self.peak_decay[mask2_a] += 20. * log10(PEAK_DECAY_RATE) * 5000

        self.peak_int[mask1] = 1.
        self.peak_int[mask2_b] *= 0.975
  
    def setQuadData(self, x, y, w, baseline, r, g, b):
        h = y - baseline
        y = baseline
        
        n = x.shape[0]
    
        vertex = zeros((n,4,2))
        vertex[:,0,0] = x
        vertex[:,0,1] = y + h
        vertex[:,1,0] = x + w
        vertex[:,1,1] = y + h
        vertex[:,2,0] = x + w
        vertex[:,2,1] = y
        vertex[:,3,0] = x
        vertex[:,3,1] = y

        color = zeros((n,4,3))
        color[:,0,0] = r
        color[:,1,0] = r
        color[:,2,0] = r
        color[:,3,0] = r
        color[:,0,1] = g
        color[:,1,1] = g
        color[:,2,1] = g
        color[:,3,1] = g
        color[:,0,2] = b
        color[:,1,2] = b
        color[:,2,2] = b
        color[:,3,2] = b
        
        self.glWidget.setQuadData(vertex, color)


class GLWidget(QtOpenGL.QGLWidget):
    def __init__(self, parent, sharedGLWidget, verticalScaleTransform, horizontalScaleTransform):
        super(GLWidget, self).__init__(parent, shareWidget=sharedGLWidget)

        self.lastPos = QtCore.QPoint()
        
        self.vertices = array([])
        self.colors = array([])
        
        self.xMajorTick = array([])
        self.xMinorTick = array([])
        self.yMajorTick = array([])
        self.yMinorTick = array([])

        self.ruler = False
        self.mousex = 0
        self.mousey = 0

        self.showFreqLabel = True
        self.xmax = 0
        self.fmax = 0.
        
        # use a cross cursor to easily select a point on the graph
        self.setCursor(Qt.Qt.CrossCursor)
        
        # instruct OpenGL not to paint a background for the widget
        # when QPainter.begin() is called.
        self.setAutoFillBackground(False)

        # set proper size policy for this widget
        self.setSizePolicy(QtGui.QSizePolicy(QtGui.QSizePolicy.MinimumExpanding, QtGui.QSizePolicy.MinimumExpanding))

        self.gridList = None

        self.horizontalScaleTransform = horizontalScaleTransform
        self.verticalScaleTransform = verticalScaleTransform

    def sizeHint(self):
        return QtCore.QSize(50, 50)

    def initializeGL(self):
        return

    def setfmax(self, xmax, fmax):
        if xmax==inf or xmax==-inf:
            self.xmax = 0
        else:
            self.xmax = int(xmax)
        self.fmax = fmax

    def setShowFreqLabel(self, showFreqLabel):
        self.showFreqLabel = showFreqLabel
        # ask for update so the the label is actually erased or painted
        self.update()

    def setQuadData(self, vertices, colors):
        self.vertices = vertices
        self.colors = colors 

        self.update()

    def setGrid(self, xMajorTick, xMinorTick, yMajorTick, yMinorTick):
        self.xMajorTick = xMajorTick
        self.xMinorTick = xMinorTick
        self.yMajorTick = yMajorTick
        self.yMinorTick = yMinorTick

        self.updateGrid()

    def updateGrid(self):
        if self.gridList == None or self.gridList == 0:
            return

        w = self.width()
        h = self.height()
        
        GL.glNewList(self.gridList, GL.GL_COMPILE)

        self.qglColor(QtGui.QColor(Qt.Qt.gray))
        for x in self.xMajorTick:        
            GL.glBegin(GL.GL_LINES)
            GL.glVertex2f(x, 0)
            GL.glVertex2f(x, h)
            GL.glEnd()
        
        self.qglColor(QtGui.QColor(Qt.Qt.lightGray))
        for x in self.xMinorTick:        
            GL.glBegin(GL.GL_LINES)
            GL.glVertex2f(x, 0)
            GL.glVertex2f(x, h)
            GL.glEnd()
            
        self.qglColor(QtGui.QColor(Qt.Qt.gray))
        for y in self.yMajorTick:        
            GL.glBegin(GL.GL_LINES)
            GL.glVertex2f(0, y)
            GL.glVertex2f(w, y)
            GL.glEnd()
        
        #GL.glColor3f(0.5, 0.5, 0.5)
        #for y in self.yMinorTick:        
        #    GL.glBegin(GL.GL_LINES)
        #    GL.glVertex2f(0, y)
        #    GL.glVertex2f(w, y)
        #    GL.glEnd() 

        GL.glEndList()

    #def paintGL(self):
    def paintEvent(self, event):
        self.makeCurrent()
        
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glPushMatrix()        
        
        GL.glShadeModel(GL.GL_SMOOTH) # for gradient rendering
        #GL.glDepthFunc(GL.GL_LESS) # The Type Of Depth Test To Do
        GL.glDisable(GL.GL_DEPTH_TEST) # we do 2D, we need no depth test !
        GL.glMatrixMode(GL.GL_PROJECTION)
        #GL.glEnable(GL.GL_CULL_FACE)
        
        # Clear The Screen And The Depth Buffer
        GL.glClearColor(1, 1, 1, 0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT) # | GL.GL_DEPTH_BUFFER_BIT)

        # Reset The View        
        self.setupViewport(self.width(), self.height())
        
        self.drawBackground()       
        self.drawGrid()        
        self.drawDataQuads()        
        self.drawRuler()                
        self.drawBorder()

        # revert our changes for cooperation with QPainter
        GL.glShadeModel(GL.GL_FLAT)
        GL.glEnable(GL.GL_DEPTH_TEST)
        
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glPopMatrix()

        painter = QtGui.QPainter(self)
        self.drawTrackerText(painter)
        self.drawFreqMaxText(painter)

        painter.end()

    def drawDataQuads(self):
        # TODO: instead of Arrays, VBOs should be used here, as a large part of
        # the data does not have to be modified on every call (x coordinates,
        # green colored quads)
        
        # TODO: If the arrays could be drawn as SHORTs istead of FLOATs, it
        # could also be dramatically faster

        GL.glVertexPointerd(self.vertices)
        GL.glColorPointerd(self.colors)
        GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
        GL.glEnableClientState(GL.GL_COLOR_ARRAY)
        
        #GL.glDisable(GL.GL_LIGHTING)
        GL.glDrawArrays(GL.GL_QUADS, 0, 4*self.vertices.shape[0])
        #GL.glEnable(GL.GL_LIGHTING)
        
        GL.glDisableClientState(GL.GL_COLOR_ARRAY)
        GL.glDisableClientState(GL.GL_VERTEX_ARRAY)

    def drawFreqMaxText(self, painter):
        if not self.showFreqLabel:
            return

        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if self.fmax < 2e2:
            text = "%.1f Hz" %(self.fmax)
        else:
            text = "%d Hz" %(rint(self.fmax))
        
        # compute tracker bounding rect
        painter.setPen(Qt.Qt.black)
        rect = painter.boundingRect(QtCore.QRect(self.xmax, 0, 0, 0), Qt.Qt.AlignHCenter, text)
        
        # avoid crossing the left and top borders
        dx = - min(rect.x()-2, 0)
        dy = - min(rect.y()-1, 0)
        rect.translate(dx, dy)

        # avoid crossing the right and bottom borders
        dx = - max(rect.right() - self.width() + 2, 0)
        dy = - max(rect.bottom() - self.height() + 1, 0)
        rect.translate(dx, dy)
        
        Hmiddle = (rect.left()+rect.right())/2
        triangleSize = 4

        # draw a white background
        painter.setPen(Qt.Qt.NoPen)
        painter.setBrush(Qt.Qt.white)
        painter.drawRect(rect)

        # draw a little downward-pointing triangle to indicate the frequency
        # triangle fill
        polygon = QtGui.QPolygon()
        polygon << QtCore.QPoint(Hmiddle-triangleSize, rect.bottom()+1)
        polygon << QtCore.QPoint(Hmiddle, rect.bottom()+1+triangleSize)
        polygon << QtCore.QPoint(Hmiddle+triangleSize, rect.bottom()+1)
        painter.drawPolygon(polygon)

        # triangle outline
        painter.setPen(Qt.Qt.black)
        painter.drawLine(rect.left(), rect.bottom()+1, Hmiddle-triangleSize, rect.bottom()+1)
        painter.drawLine(Hmiddle-triangleSize, rect.bottom()+1, Hmiddle, rect.bottom()+1+triangleSize)
        painter.drawLine(Hmiddle, rect.bottom()+1+triangleSize, Hmiddle+triangleSize, rect.bottom()+1)
        painter.drawLine(Hmiddle+triangleSize, rect.bottom()+1, rect.right(), rect.bottom()+1)
        
        # frequency label
        painter.setPen(Qt.Qt.black)
        painter.drawText(rect, Qt.Qt.AlignLeft, text)

    def drawTrackerText(self, painter): 
        if self.ruler:
            painter.setRenderHint(QtGui.QPainter.Antialiasing)

            x = self.horizontalScaleTransform.toPlot(self.mousex)
            y = self.verticalScaleTransform.toPlot(float(self.height() - self.mousey))
            text = "%d Hz, %.1f dB" %(x, y)

            # compute tracker bounding rect
            painter.setPen(Qt.Qt.black)
            rect = painter.boundingRect(QtCore.QRect(self.mousex, self.mousey, 0, 0), Qt.Qt.AlignLeft, text)
            
            # small offset so that it does not touch the rulers
            rect.translate(4, -( rect.height() + 4))
            
            # avoid crossing the top and right borders
            dx = - max(rect.x() + rect.width() - self.width(), 0)
            dy = - min(rect.y(), 0)
            rect.translate(dx, dy)
            
            # avoid crossing the left and bottom borders
            dx = - min(rect.x(), 0)
            dy = - max(rect.y() + rect.height() - self.height(), 0)
            rect.translate(dx, dy)
            
            # draw a white background
            painter.setPen(Qt.Qt.NoPen)
            painter.setBrush(Qt.Qt.white)
            painter.drawRect(rect)
            
            painter.setPen(Qt.Qt.black)
            painter.drawText(rect, Qt.Qt.AlignLeft, text)

    def resizeGL(self, width, height):
        self.setupViewport(self.width(), self.height())
        self.updateGrid()

    def setupViewport(self, width, height):
        GL.glViewport(0, 0, width, height)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        GL.glOrtho(0, width, 0, height, 0, 1)
        # Displacement trick for exact pixelization
        GL.glTranslatef(0.375, 0.375, 0)

    def drawBackground(self):
        w = self.width()
        h = self.height()
        GL.glBegin(GL.GL_QUADS)
        GL.glColor3f(0.85, 0.85, 0.85)
        GL.glVertex2d(0, h)
        GL.glVertex2d(w, h)
        GL.glColor3f(1, 1, 1)
        GL.glVertex2d(w, h/2)
        GL.glVertex2d(0, h/2)
        GL.glEnd()

    def drawGrid(self):
        if self.gridList == None:
            # display list used for the grid
            self.gridList = GL.glGenLists(1)

            if self.gridList == 0 or self.gridList == None:
                raise RuntimeError( """Unable to generate a new display-list, context may not support display lists""")

            self.updateGrid()

        GL.glCallList(self.gridList)

    def drawBorder(self):
        w = self.width()
        h = self.height()
        self.qglColor(QtGui.QColor(Qt.Qt.gray))
        GL.glBegin(GL.GL_LINE_LOOP)
        GL.glVertex2f(0, 0)
        GL.glVertex2f(0, h-1)
        GL.glVertex2f(w-1, h-1)
        GL.glVertex2f(w-1, 0)
        GL.glEnd()

    def drawRuler(self):
        if self.ruler:
            w = self.width()
            h = self.height()
            self.qglColor(QtGui.QColor(Qt.Qt.black))
            GL.glBegin(GL.GL_LINES)
            GL.glVertex2f(self.mousex, 0)
            GL.glVertex2f(self.mousex, h)
            GL.glVertex2f(0, h - self.mousey)
            GL.glVertex2f(w, h - self.mousey)
            GL.glEnd()

    def mousePressEvent(self, event):
        self.lastPos = event.pos()
        self.mousex = event.x()
        self.mousey = event.y()
        self.ruler = True
        # ask for update so the the ruler is actually painted
        self.update()

    def mouseReleaseEvent(self, event):
        self.ruler = False
        # ask for update so the the ruler is actually erased
        self.update()

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton:
            self.mousex = event.x()
            self.mousey = event.y()
            self.update()

