#!/usr/bin/env python

whichUiToUse = 'py_ow'
#whichUiToUse = 'py'
#whichUiToUse = 'ui'


ApplicationStr = "NT DataLogger"
VersionStr = "10. Nov. 2016 v0.34 udp"
IniFileStr = "./NTLoggerTool.ini"


#comments/todos:
# - ImuState filter simply done by repeating value, option with (i) interpolate (ii) reject would be better
#   but carefull: it can happen that a field is not received because it is not in the data stream
#                 or that it is incomplete, both for size issues on teh StorM32 side
#
# - in rec no raw data is safed, thus nothing to store in .cfl, good or bad?
#
# - hsb = self.wDataText.horizontalScrollBar()
#   hsb.setValue(v)
#   doesn't work then wDataText is not visible
#
# - with yAR off, and if a [A] is doen in the plot, when plot is autoranging and yAR off is ignored??
#   does autoRange() also enable auto range?
#   seems so, a disableAutoRange() seems to do the trick
#
# - the whole date version thing needs to be revisted, logItemList should also adapt to NT log file version
#   circumvented currently, by simply adding the required fields, and to set the unsued ones to zero
#XX

import sys
import struct
from math import sqrt, sin, pi
from copy import deepcopy
import re

from PyQt5 import QtCore, QtGui, QtWidgets, QtSerialPort, QtNetwork
from PyQt5.QtCore import pyqtSignal, pyqtSlot, QThread, QFile, Qt, QSettings, QTimer, QIODevice, QMutex
from PyQt5.QtWidgets import (QMainWindow, QApplication, QCheckBox, QColorDialog, QDialog, QWidget,
                             QErrorMessage, QFileDialog, QFontDialog, QFrame, QGridLayout,
                             QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QToolButton,
                             QStyleFactory, QStyle, QListWidgetItem, QTreeWidgetItem, QComboBox)
from PyQt5.QtGui import QPalette, QColor, QFont, QFontInfo, QFontMetrics, QFontDatabase
from PyQt5.QtSerialPort import QSerialPortInfo, QSerialPort
from PyQt5.QtNetwork import (QTcpSocket, QUdpSocket, QHostAddress,
                             QNetworkConfigurationManager, QNetworkConfiguration, QNetworkSession, QNetworkInterface)

#pyuic5 input.ui -o output.py
if( whichUiToUse=='py_ow' ):
    import NTLoggerTool_ui_ow
    wMainWindow = NTLoggerTool_ui_ow.Ui_wWindow
elif( whichUiToUse=='py' ):
    import NTLoggerTool_ui
    wMainWindow = NTLoggerTool_ui.Ui_wWindow
else:
    from PyQt5.uic import loadUiType
    wMainWindow, _ = loadUiType('NTLoggerTool_ui.ui')

import numpy as np
from io import StringIO, BytesIO #this is needed to make np.loadtxt to work
import pyqtgraph as pg

#import cv2


###################################################################
# def __init__(self):
#   super() calls a method of the parent class
#   super(cWorkerThread, self).__init__()
# https://rhettinger.wordpress.com/2011/05/26/super-considered-super/
#   super(self.__class__, self).__init__() #this is to call the init of the paranet class
# http://stackoverflow.com/questions/576169/understanding-python-super-with-init-methods
#   super().__init__() #this is IMHO the best

###################################################################
# general stuff
###################################################################

def trimStrWithCharToLength(s,len_,c):
    while len(s)<len_: s = s + c
    return s

def strwt(s): return str(s)+"\t"

def strwn(s): return str(s)+"\n"

def int_to_u16(i):
    if i<0: i += 65536
    if i>65536-1: i = 65536-1
    return i


'''
#from https://scimusing.wordpress.com/2013/10/25/ring-buffers-in-pythonnumpy/
class cRingBuffer():
    #"A 1D ring buffer using numpy arrays"
    def __init__(self, length):
        self.data = np.zeros(length,  dtype='uint8')#, dtype='f')
        self.index = 0

    def extend(self, x):
        #"adds array x to ring buffer"
        x_index = (self.index + np.arange(x.size)) % self.data.size
        self.data[x_index] = x
        self.index = x_index[-1] + 1

    def get(self):
        #"Returns the first-in-first-out data in the ring buffer"
        idx = (self.index + np.arange(self.data.size)) % self.data.size
        return self.data[idx]

    def clear(self):
        self.data = np.zeros(length)#, dtype='f')
        self.index = 0
'''


class cRingBuffer():
    def __init__(self, size):

        self.writepos = 0
        self.readpos = 0
        self.SIZEMASK = size-1
        self.buf = bytearray(size)
        print("Create ring buffer", len(self.buf))
        #print(self.buf)

    def putc(self, c):
        nextpos = ( self.writepos + 1 ) & self.SIZEMASK
        if nextpos != self.readpos: #fifo not full
            self.buf[self.writepos] = c;
            self.writepos = nextpos
            return 1
        return 0

    def putbuf(self, buf):
        for c in buf: self.putc( c )

    def getc(self):
        if self.writepos != self.readpos: #fifo not empty
            c = self.buf[self.readpos]
            self.readpos = ( self.readpos + 1 ) & self.SIZEMASK
            return c
            
        raise Exception("getc: fifo is empty")    


    def available(self):
        d = self.writepos - self.readpos
        if d < 0: return d + (self.SIZEMASK+1)
        return d

    def free(self):
        d = self.writepos - self.readpos;
        if d < 0: return d + (self.SIZEMASK+1)
        return self.SIZEMASK - d #the maximum is size-1

    def isempty(self):
        if self.writepos == self.readpos: return 1
        return 0

    def isnotfull(self):
        netxpos = ( self.writepos + 1 ) & (selfSIZEMASK)
        if nextpos != self.readpos: return True
        return False

    def flush(self):
        self.writepos = 0
        self.readpos = 0


    def size(self):
        return self.SIZEMASK + 1





###############################################################################
# cSerialPortComboBox
# this is the class to select a serial COM port
#-----------------------------------------------------------------------------#
class cSerialPortComboBox(QComboBox):

    def __init__(self, _networkManager, _cMain, _cScale=1.0):
        super().__init__(_cMain)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.sizePolicy().hasHeightForWidth())
        self.setSizePolicy(sizePolicy)
        self.setMinimumSize(QtCore.QSize(65*_cScale, 21*_cScale))
        self.setMaximumSize(QtCore.QSize(65*_cScale, 21*_cScale))
        self.view().setMinimumWidth(160*_cScale)
        self.networkManager = _networkManager
        self.populateList()

    def key(self,_s):
        return int(_s[3:7])

    def populateList(self):
        availableSerialPortInfoList = QSerialPortInfo().availablePorts()
        availableSerialPortList = []
        for portInfo in availableSerialPortInfoList:
            '''
            print('-')
            print(portInfo)
            print(portInfo.description())
            print(portInfo.portName())
            print(portInfo.serialNumber())
            print(portInfo.productIdentifier())
            print(portInfo.manufacturer())
            print(portInfo.systemLocation()) #unix type port name
            print(portInfo.vendorIdentifier())
            '''
            s = portInfo.portName()
            while len(s)<13: s += ' '
            p = portInfo.description()
            if re.search(r'Virtual COM Port',p):  d = 'Virtual COM Port'
            elif re.search(r'USB Serial Port',p): d = 'USB Serial Port'
            elif re.search(r'Bluetooth',p):       d = 'Bluetooth'
            #elif re.search(r'Standard',p):        d = 'Standard Port'
            else: d = 'Standard'
            availableSerialPortList.append(s+d)
        availableSerialPortList.sort(key=self.key)

        configlist = self.networkManager.allConfigurations()
        for config in configlist:
            #if not re.search( r'WLAN', config.bearerTypeName()): continue
            if re.search( r'ENSYS NT Logger', config.name()):
                availableSerialPortList.append('ENSYS NT Logger')
                break

        self.clear()
        self.addItems(availableSerialPortList)

    def showPopup(self):
        self.populateList()
#XX        super(self.__class__, self).showPopup()
        super().showPopup()

    def currentPort(self):
        pn = self.currentText()
        if re.search(r'^ENSYS',pn):
            return pn
        return re.findall(r'COM\d*',pn)[0]

    def itemPort(self,i):
        pn = self.itemText(i)
        if re.search(r'^ENSYS',pn):
            return pn
        return re.findall(r'COM\d*',pn)[0]

    def setCurrentPort(self,_port):
        for i in range(self.count()):
            if _port==self.itemPort(i):
                self.setCurrentIndex(i)
                return


###################################################################
# some constants
###################################################################

cDATATYPE_U8  = 0
cDATATYPE_U16 = 1
cDATATYPE_U32 = 2
cDATATYPE_U64 = 3
cDATATYPE_Ux  = 7   #Ux is a mask for all U types
cDATATYPE_S8  = 16
cDATATYPE_S16 = 17
cDATATYPE_S32 = 18
cDATATYPE_S64 = 19
cDATATYPE_Sx  = 20  #Sx is a mask for all S types
cDATATYPE_FLOAT = 32


###############################################################################
# class cCFBlackbox
# helper class to generate a BlackBox Explorer compatible .LOG data log file
# it needs a logItemList, from which it infers the indices and rawtypes
#-----------------------------------------------------------------------------#
class cCFBlackbox:

    #if a field is here, it is not destroyed when created again!
    #the consructor should then have a line if len(self.fields)==0:
    #fields = []
    IInterval = 1

    #the list order must be identical to that in class cNTLogFileReader !!!!
    def __init__(self,_logItemList=None):
        self.stdNameIndexTypeDictionary = {}
        if _logItemList: self.stdNameIndexTypeDictionary = _logItemList.getNameIndexTypeDictionary()
        self.fields = []
        self.addField( 'loopIteration', -1,  0) #not in data log file
        self.addField_( 'time',          'Time' )
#        datalog.append( "\tImu1rx\tImu1done\tPIDdone\tMotdone\tImu2rx\tImu2done\tLoopdone" )
        self.addField_( 'Imu1rx',        'Imu1rx' )
        self.addField_( 'Imu1done',      'Imu1done' )
        self.addField_( 'PIDdone',       'PIDdone' )
        self.addField_( 'Motdone',       'Motdone' )
        self.addField_( 'Imu2rx',        'Imu2rx' )
        self.addField_( 'Imu2done',      'Imu2done' )
        self.addField_( 'Logdone',       'Logdone' )
        self.addField_( 'Loopdone',      'Loopdone' )
#        datalog.append( "\tState\tStatus\tStatus2\tErrorCnt\tVoltage" )
        self.addField_( 'State',         'State' )
        self.addField_( 'Status',        'Status' )
        self.addField_( 'Status2',       'Status2' )
        self.addField_( 'ErrorCnt',      'ErrorCnt' )
        self.addField_( 'Voltage',       'Voltage' )
#        datalog.append( "\tax1\tay1\taz1\tgx1\tgy1\tgz1\tT1\tImu1State" )
        self.addField_( 'a1[0]',         'ax1' )
        self.addField_( 'a1[1]',         'ay1' )
        self.addField_( 'a1[2]',         'az1' )
        self.addField_( 'g1[0]',         'gx1' )
        self.addField_( 'g1[1]',         'gy1' )
        self.addField_( 'g1[2]',         'gz1' )
        self.addField_( 'Imu1State',     'Imu1State' )
#        datalog.append( "\tax2\tay2\taz2\tgx2\tgy2\tgz2\tT2\tImu2State" )
        self.addField_( 'a2[0]',         'ax2' )
        self.addField_( 'a2[1]',         'ay2' )
        self.addField_( 'a2[2]',         'az2' )
        self.addField_( 'g2[0]',         'gx2' )
        self.addField_( 'g2[1]',         'gy2' )
        self.addField_( 'g2[2]',         'gz2' )
        self.addField_( 'Imu2State',     'Imu2State' )
#         datalog.append( "\tImu1Pitch\tImu1Roll\tImu1Yaw\tImu2Pitch\tImu2Roll\tImu2Yaw" )
        self.addField_( 'Imu1[0]',       'Imu1Pitch' )
        self.addField_( 'Imu1[1]',       'Imu1Roll' )
        self.addField_( 'Imu1[2]',       'Imu1Yaw' )
        self.addField_( 'Imu2[0]',       'Imu2Pitch' )
        self.addField_( 'Imu2[1]',       'Imu2Roll' )
        self.addField_( 'Imu2[2]',       'Imu2Yaw' )
#        datalog.append( "\tPIDPitch\tPIDRoll\tPIDYaw\tPIDMotPitch\tPIDMotRoll\tPIDMotYaw" )
        self.addField_( 'PID[0]',        'PIDPitch' )
        self.addField_( 'PID[1]',        'PIDRoll' )
        self.addField_( 'PID[2]',        'PIDYaw' )
        self.addField_( 'PIDMot[0]',     'PIDMotPitch' )
        self.addField_( 'PIDMot[1]',     'PIDMotRoll' )
        self.addField_( 'PIDMot[2]',     'PIDMotYaw' )
#        datalog.append( "\tRx1\tRy1\tRz1\tAccAmp1\tAccConf1\tYawTarget2" )
        self.addField_( 'R1[0]',         'Rx1' )
        self.addField_( 'R1[1]',         'Ry1' )
        self.addField_( 'R1[2]',         'Rz1' )
        self.addField_( 'AccAmp1',       'AccAmp1' )
        self.addField_( 'AccConf1',      'AccConf1' )
        #self.addField( 'YawTarget2',     'YawTarget2' )
#        datalog.append( "\tMotFlags\tVmaxPitch\tMotPitch\tVmaxRoll\tMotRoll\tVmaxYaw\tMotYaw" )
        self.addField_( 'MotFlags',      'MotFlags' )
        self.addField_( 'Vmax[0]',       'VmaxPitch' )
        self.addField_( 'Vmax[1]',       'VmaxRoll' )
        self.addField_( 'Vmax[2]',       'VmaxYaw' )
        self.addField_( 'Mot[0]',        'MotPitch' )
        self.addField_( 'Mot[1]',        'MotRoll' )
        self.addField_( 'Mot[2]',        'MotYaw' )
#        datalog.append( "\tax1raw\tay1raw\taz1raw\tgx1raw\tgy1raw\tgz1raw" )
        self.addField_( 'a1raw[0]',      'ax1raw' )
        self.addField_( 'a1raw[1]',      'ay1raw' )
        self.addField_( 'a1raw[2]',      'az1raw' )
        self.addField_( 'g1raw[0]',      'gx1raw' )
        self.addField_( 'g1raw[1]',      'gy1raw' )
        self.addField_( 'g1raw[2]',      'gz1raw' )
        self.addField_( 'T1',            'T1' )
#        datalog.append( "\tax2raw\tay2raw\taz2raw\tgx2raw\tgy2raw\tgz2raw" )
        self.addField_( 'a2raw[0]',      'ax2raw' )
        self.addField_( 'a2raw[1]',      'ay2raw' )
        self.addField_( 'a2raw[2]',      'az2raw' )
        self.addField_( 'g2raw[0]',      'gx2raw' )
        self.addField_( 'g2raw[1]',      'gy2raw' )
        self.addField_( 'g2raw[2]',      'gz2raw' )
        self.addField_( 'T2',            'T2' )
#        datalog.append( "\tax3raw\tay3raw\taz3raw\tgx3raw\tgy3raw\tgz3raw" )
        self.addField_( 'a3raw[0]',      'ax3raw' )
        self.addField_( 'a3raw[1]',      'ay3raw' )
        self.addField_( 'a3raw[2]',      'az3raw' )
        self.addField_( 'g3raw[0]',      'gx3raw' )
        self.addField_( 'g3raw[1]',      'gy3raw' )
        self.addField_( 'g3raw[2]',      'gz3raw' )
        self.addField_( 'T3',            'T3' )

        self.encode1Struct = struct.Struct('B')

    def translate(self,_name):
        return _name

    def addField(self, name, index, signed):
        #self.fields.append( [name, signed, predictorI, encodingI, predictorP, encodingP] )
        if( signed>0 ):
            self.fields.append( [name, index, signed, 0, 0, 0, 0] ) #signed => encode0
        else:
            self.fields.append( [name, index, signed, 0, 1, 0, 1] ) #unsigned => encode1

    def addField_(self, name, stdname):
        #stdname is the name used in cNTLogFileReader
        if not stdname in self.stdNameIndexTypeDictionary: return
        item = self.stdNameIndexTypeDictionary[stdname]
        index = item['index']
        rawtype = item['rawtype']
        if rawtype>=cDATATYPE_S8 and rawtype<=cDATATYPE_Sx:
            self.fields.append( [name, index, 1, 0, 0, 0, 0] ) #signed => encode0
        else:
            self.fields.append( [name, index, 0, 0, 1, 0, 1] ) #unsigned => encode1

    def header(self,_firmwareVersion,_logFileVersion):
        head =  'H Product:Blackbox flight data recorder by Nicholas Sherlock' + '\n'
        head += 'H Firmware type:STorM32' + '\n' #optional
        head += 'H Firmware revision:' + _firmwareVersion + '\n' #optional
        head += 'H Data version:2' + '\n'
        head += 'H Logfile version:' + str(_logFileVersion) + '\n' #addition by myself
        head += 'H I interval:' + str(self.IInterval) + '\n'
        head += 'H P interval:1/1' + '\n'
        head += 'H Field I name:'
        for field in self.fields: head += field[0] + ','
        head = head[:-1] + '\n'
        head += 'H Field I signed:'
        for field in self.fields: head += str(field[2]) + ','
        head = head[:-1] + '\n'
        head += 'H Field I predictor:'
        for field in self.fields: head += str(field[3]) + ','
        head = head[:-1] + '\n'
        head += 'H Field I encoding:'
        for field in self.fields: head += str(field[4]) + ','
        head = head[:-1] + '\n'
        head += 'H Field P predictor:'
        for field in self.fields: head += str(field[5]) + ','
        head = head[:-1] + '\n'
        head += 'H Field P encoding:'
        for field in self.fields: head += str(field[6]) + ','
        head = head[:-1] + '\n'
        return bytes(head,'utf-8')

    def footer(self):
        return b'E\xFFEnd of log\x00'

    def encode0(self,i): #Signed variable byte (0)
        #if( i>65536 ): i = 65536
        #if( i<-65536 ): i = -65536
        if i>524287: i = 524287  #s24 to support extended imu angles
        if i<-524288: i = -524288
        i = (i << 1) ^ (i >> 31)
        return self.encode1(i)

    def encode1(self,i): #Unsigned variable byte (1)
        r = b''
        while i>127:
            msb = (i).to_bytes(10,byteorder='little')[0]
            r += self.encode1Struct.pack( msb|128 )
            i >>= 7
        msb = (i).to_bytes(10,byteorder='little')[0]
        r += self.encode1Struct.pack( msb&127 )
        return r

    def dataIFrame(self, _iter, _dataList):
        data = b'P'
        if _iter%self.IInterval==0: data = b'I'
        data += self.encode1(_iter)
        data += self.encode1( _dataList[0] ) #this is the time, is suposedly positive
        for i in range(2,len(self.fields)):
            ptr = self.fields[i]
            if( ptr[2]>0 ):
                data += self.encode0(_dataList[ptr[1]]) #signed->encode0
            else:
                data += self.encode1(_dataList[ptr[1]]) #unsigned->encode1
        return data

    def dataEBeep(self, _time):
        return b'E\x00' + self.encode1( _time )


###############################################################################
# class cPX4
# helper class to generate a PX4 compatible .bin data log file
#-----------------------------------------------------------------------------#
# removed in v0.19, there is no real reason anymore to use anything else than NTLoggerTool


###############################################################################
# class cVibe
# calculates the vibration level from accelerometer data
# time is in seconds
# acc should be a tupel
#-----------------------------------------------------------------------------#
# removed in v0.31, was really of no use, FFT is much more helpfull


###############################################################################
# cLogItemTranslator
# cStorm32GuiLogItemTranslator(cLogItemTranslator)
# helper class to translate data field names from various source files to
# the standard NTLogger data field names
#-----------------------------------------------------------------------------#
class cLogItemTranslator:

    def translate(self,_name):
        return _name


class cStorm32GuiLogItemTranslator(cLogItemTranslator):

    storm32GuiLogTranslateDict = {
        'Gx':'gx1', 'Gy':'gy1', 'Gz':'gz1',
        'Rx':'Rx1', 'Ry':'Ry1', 'Rz':'Rz1',
        'AccAmp':'AccAmp1', 'AccConf':'AccConf1',
        'Pitch':'Imu1Pitch', 'Roll':'Imu1Roll', 'Yaw':'Imu1Yaw',
        'Pitch2':'Imu2Pitch', 'Roll2':'Imu2Roll', 'Yaw2':'Imu2Yaw',
        'PCntrl':'PIDPitch', 'RCntrl':'PIDRoll', 'YCntrl':'PIDYaw'   }

    def translate(self,_name):
        if _name in self.storm32GuiLogTranslateDict:
            return self.storm32GuiLogTranslateDict[_name]
        return _name


###############################################################################
# cLogItemList
# class to handle the data columns for various data log files
# translates data field names according to the given translator
# organizes the standard NTLogger data field names into catagories
#-----------------------------------------------------------------------------#
class cLogItemList:

    #this is a human-readable list of how to organize the standard NTLogger data field names into catagories
    #is used in getGraphSelectorList()
    dataLoggerGraphSelectorList = [
        ['Performance',["Imu1rx","Imu1done","PIDdone","Motdone","Imu2rx","Imu2done","Logdone","Loopdone"] ],
        ['Imu1 Pitch,Roll,Yaw',["Imu1Pitch","Imu1Roll","Imu1Yaw"] ],
        ['Imu2 Pitch,Roll,Yaw',["Imu2Pitch","Imu2Roll","Imu2Yaw"] ],
        ['PID Pitch,Roll,Yaw',["PIDPitch","PIDRoll","PIDYaw"] ],
        ['Ahrs1',["Rx1","Ry1","Rz1","AccAmp1","AccConf1","YawTarget2"]],
        ['State',['State']],
        ['Error',['ErrorCnt']],
        ['Voltage',['Voltage']],
        ['Acc1',["ax1","ay1","az1"]],
        ['Gyro1',["gx1","gy1","gz1"]],
        ['Acc2',["ax2","ay2","az2"]],
        ['Gyro2',["gx2","gy2","gz2"]],
        ['Imu States',["Imu1State","Imu2State"]],
        ['Acc1 raw',["ax1raw","ay1raw","az1raw"]],
        ['Gyro1 raw',["gx1raw","gy1raw","gz1raw"]],
        ['Acc2 raw',["ax2raw","ay2raw","az2raw"]],
        ['Gyro2 raw',["gx2raw","gy2raw","gz2raw"]],
        ['Acc3 raw',["ax3raw","ay3raw","az3raw"]],
        ['Gyro3 raw',["gx3raw","gy3raw","gz3raw"]],
        ['Temp 1+2+3',["T1","T2","T3"]],
        ['PID Mot Pitch,Roll,Yaw',["PIDMotPitch","PIDMotRoll","PIDMotYaw"]],
        ['Mot Flags',["MotFlags"]],
        ['Mot Pitch,Roll,Yaw',["MotPitch","MotRoll","MotYaw"]],
        ['Vmax Pitch,Roll,Yaw',["VmaxPitch","VmaxRoll","VmaxYaw"]],
        ['Camera',["CameraCmd","CameraPwm"]],
        ]

    def __init__(self,_translator=None):
        self.translator = _translator #cStorm32GuiLogItemTranslator() #cLogItemTranslator()
        self.list = [] #this is the item list of the log file
        self.curIndex = 0
        self.setToStandardNTLoggerItemList()

    def clear(self):
        self.list = []
        self.curIndex = 0

    #adds a data field item to the list
    #needs: name, uint, raw data type (as in the log data stream), data type (as return by the log data reader)
    def addItem(self, _name, _unit, _rawtype, _type):
        self.list.append( {'index':self.curIndex, 'name':_name, 'unit':_unit, 'rawtype':_rawtype, 'type':_type} )
        self.curIndex += 1

    #the list order must be identical to that in class cNTLogFileReader !!!!
    #keeps information which is used for the various data formats
    def setToStandardNTLoggerItemList(self):
        self.clear()
        self.addItem( 'Time', 'ms', cDATATYPE_U64, cDATATYPE_FLOAT )
        self.addItem( 'Imu1rx', 'us', cDATATYPE_U8, cDATATYPE_Ux )
        self.addItem( 'Imu1done', 'us', cDATATYPE_U8, cDATATYPE_Ux )
        self.addItem( 'PIDdone', 'us', cDATATYPE_U8, cDATATYPE_Ux )
        self.addItem( 'Motdone', 'us', cDATATYPE_U8, cDATATYPE_Ux )
        self.addItem( 'Imu2rx', 'us', cDATATYPE_U8, cDATATYPE_Ux )
        self.addItem( 'Imu2done', 'us', cDATATYPE_U8, cDATATYPE_Ux )
        self.addItem( 'Logdone', 'us', cDATATYPE_U8, cDATATYPE_Ux )
        self.addItem( 'Loopdone', 'us', cDATATYPE_U8, cDATATYPE_Ux )

        self.addItem( 'State', 'uint', cDATATYPE_U16, cDATATYPE_Ux )
        self.addItem( 'Status', 'hex', cDATATYPE_U16, cDATATYPE_Ux )
        self.addItem( 'Status2', 'hex', cDATATYPE_U16, cDATATYPE_Ux )
        self.addItem( 'ErrorCnt', 'uint', cDATATYPE_U16, cDATATYPE_Ux )
        self.addItem( 'Voltage', 'V', cDATATYPE_U16, cDATATYPE_FLOAT )

        self.addItem( 'ax1', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'ay1', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'az1', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gx1', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gy1', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gz1', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'Imu1State', 'hex', cDATATYPE_U8, cDATATYPE_Ux )

        self.addItem( 'ax2', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'ay2', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'az2', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gx2', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gy2', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gz2', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'Imu2State', 'hex', cDATATYPE_U8, cDATATYPE_Ux )

        self.addItem( 'Imu1Pitch', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'Imu1Roll', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'Imu1Yaw', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'Imu2Pitch', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'Imu2Roll', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'Imu2Yaw', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )

        self.addItem( 'PIDPitch', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'PIDRoll', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'PIDYaw', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'PIDMotPitch', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'PIDMotRoll', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'PIDMotYaw', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )

        self.addItem( 'Rx1', 'g', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'Ry1', 'g', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'Rz1', 'g', cDATATYPE_S16, cDATATYPE_FLOAT )
        self.addItem( 'AccAmp1', 'g', cDATATYPE_Ux, cDATATYPE_FLOAT ) #injected value
        self.addItem( 'AccConf1', 'uint', cDATATYPE_U16, cDATATYPE_FLOAT )
        self.addItem( 'YawTarget2', 'deg', cDATATYPE_S16, cDATATYPE_FLOAT )

        self.addItem( 'MotFlags', 'hex', cDATATYPE_U8, cDATATYPE_Ux )
        self.addItem( 'VmaxPitch', 'uint', cDATATYPE_U8, cDATATYPE_Ux )
        self.addItem( 'MotPitch', 'uint', cDATATYPE_U16, cDATATYPE_Ux )
        self.addItem( 'VmaxRoll', 'uint', cDATATYPE_U8, cDATATYPE_Ux )
        self.addItem( 'MotRoll', 'uint', cDATATYPE_U16, cDATATYPE_Ux )
        self.addItem( 'VmaxYaw', 'uint', cDATATYPE_U8, cDATATYPE_Ux )
        self.addItem( 'MotYaw', 'uint', cDATATYPE_U16, cDATATYPE_Ux )

        self.addItem( 'ax1raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'ay1raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'az1raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gx1raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gy1raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gz1raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'T1', 'o', cDATATYPE_S16, cDATATYPE_FLOAT )

        self.addItem( 'ax2raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'ay2raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'az2raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gx2raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gy2raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gz2raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'T2', 'o', cDATATYPE_S16, cDATATYPE_FLOAT )

        self.addItem( 'ax3raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'ay3raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'az3raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gx3raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gy3raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'gz3raw', 'int', cDATATYPE_S16, cDATATYPE_Sx )
        self.addItem( 'T3', 'o', cDATATYPE_S16, cDATATYPE_FLOAT )

        self.addItem( 'CameraCmd', 'int', cDATATYPE_U8, cDATATYPE_Ux )
        self.addItem( 'CameraPwm', 'int', cDATATYPE_U16, cDATATYPE_Ux )

    #extracts a data field item list from a string, typically the first&2nd line(s) of a .dat/.txt/.csv file
    def setFromStr(self, _names, _units, _rawtype, _type, _sep):
        nameList = _names.split(_sep)
        unitList = _units.split(_sep)
        self.clear()
        for i in range(len(nameList)):
            if i<len(unitList):
                u = unitList[i].replace("[", "").replace("]", "") #remove brackets
            else:
                u = ''
            self.addItem( nameList[i], u, _rawtype, _type )

    #moves the 'time' axis to position zero, as needed for graphing
    def swapTimeToZeroIndex(self):
        timePosInList = -1
        zeroPosInList = -1
        for i in range(len(self.list)):
            if self.list[i]['name'].lower() == 'time':
                timePosInList = i
            if self.list[i]['index'] == 0:
                zeroPosInList = i
        if timePosInList == -1: return -1 #a Time column doesn't exist
        if timePosInList == zeroPosInList: return 0 #Time column is already at index zero
        self.list[zeroPosInList]['index'] = self.list[timePosInList]['index']
        self.list[timePosInList]['index'] = 0
        return self.list[zeroPosInList]['index'] #return which index Time was before

    def getNamesAsList(self, _translator=None):
        if( not _translator ): _translator = self.translator #use the translator set by __init__
        if( not _translator ): _translator = cLogItemTranslator() #self.stdTranslator #still non edefined, use the std Translator
        l = []
        for item in self.list:
            l.append( _translator.translate(item['name']) )
        return l

    def getNamesAsStr(self, _sep, _translator=None):
        return _sep.join( self.getNamesAsList(_translator) )

    def getUnitsAsStr(self, _sep):
        s = ''
        for item in self.list:
            s += '[' + item['unit'] + ']' + _sep
        s = s[:-len(_sep)]
        return s

    def getNameIndexTypeDictionary(self):
        d = {}
        for item in self.list:
            d[item['name']] = { 'index':item['index'], 'rawtype':item['rawtype'] }
        return d

    #the main function, returns a list, which can be directly used to set the Graph Selector
    # structured as follows: [ ['catergory',[item,item,item]], ['catergory',[item,item,item]], ... ]
    def getGraphSelectorList(self, _translator=None):
        if( not _translator ): _translator = self.translator  #use the translator set by __init__
        if( not _translator ): _translator = cLogItemTranslator()  #self.stdTranslator #still non edefined, use the std Translator
        #populate Selection with items
        l = []  #this is the graphselectorlist to build
        slist = deepcopy(self.list)  #this is a copy, once an entry is used it is taken out
        for gslitem in self.dataLoggerGraphSelectorList:
            il = []
            for item in self.list:
                if _translator.translate(item['name']) in gslitem[1]:
                    il.append(item['index'])
                    slist.remove(item)
            if il: l.append( [gslitem[0], il] )
        #remove items which shall never be shown
        for item in self.list:
            if _translator.translate(item['name']).lower() in ['time','yawtarget1']:
                if item in slist: slist.remove(item)
            if item['unit'].lower() == 'hex':
                if item in slist: slist.remove(item)
        #add not yet consumed items
        for item in slist:
            l.append( [_translator.translate(item['name']), [item['index']]] )
        return l

    def getGraphSelectorDefaultIndex(self,graphSelectorList):
        for i in range(len(graphSelectorList)):
            if graphSelectorList[i][0] == 'Imu1 Pitch,Roll,Yaw': return i
        for i in range(len(graphSelectorList)):
            if graphSelectorList[i][0] == 'Acc1': return i
        return None


###############################################################################
# cNTLogDataFrame
# this is the class to handle and host the data of one frame
#-----------------------------------------------------------------------------#
# NTLogger decodes the data on the NT bus and stores that decoded data on the SD card
# error handling:
#   there are two types of error, (i) a package is incomplete, (ii) a crucial package is not complete
#   self.error is set, depending on the general error type
#   each doXXX returns True or False, so that a parser can determine more detailed error conditions

cNTDATAFRAME_OK = 0
cNTDATAFRAME_CMDERROR = 1
cNTDATAFRAME_SETMOTERROR = 2
cNTDATAFRAME_SETLOGERROR = 4

#this is base class
class cNTDataFrameObject:

    def __init__(self):
        self.logVersion = cLOGVERSION_LATEST #allows to detect different log file versions, latest version as default
        self.Time = 0 #that's the actual time of a data frame
        self.error = cNTDATAFRAME_OK #allows any other class to indicate an error of whatever kind

        self.TimeStamp32 = 0
        self.Imu1received,self.Imu1done,self.PIDdone,self.Motorsdone  = 0,0,0,0
        self.Imu2received,self.Imu2done,self.Logdone,self.Loopdone = 0,0,0,0
        self.State,self.Status,self.Status2,self.ErrorCnt,self.Voltage = 0,0,0,0,0
        self.Imu1AnglePitch,self.Imu1AngleRoll,self.Imu1AngleYaw,self.Imu2AnglePitch,self.Imu2AngleRoll,self.Imu2AngleYaw = 0,0,0,0,0,0

        self.Flags,self.VmaxPitch,self.AnglePitch,self.VmaxRoll,self.AngleRoll,self.VmaxYaw,self.AngleYaw = 0,0,0,0,0,0,0

        self.ax1,self.ay1,self.az1,self.gx1,self.gy1,self.gz1,self.ImuState1 = 0,0,0,0,0,0,0
        self.ax2,self.ay2,self.az2,self.gx2,self.gy2,self.gz2,self.ImuState2 = 0,0,0,0,0,0,0

        self.ax1raw,self.ay1raw,self.az1raw,self.gx1raw,self.gy1raw,self.gz1raw,self.temp1 = 0,0,0,0,0,0,0
        self.ax2raw,self.ay2raw,self.az2raw,self.gx2raw,self.gy2raw,self.gz2raw,self.temp2 = 0,0,0,0,0,0,0
        self.ax3raw,self.ay3raw,self.az3raw,self.gx3raw,self.gy3raw,self.gz3raw,self.temp3 = 0,0,0,0,0,0,0

        self.PIDCntrlPitch,self.PIDCntrlRoll,self.PIDCntrlYaw = 0,0,0
        self.PIDMotorCntrlPitch,self.PIDMotorCntrlRoll,self.PIDMotorCntrlYaw = 0,0,0

        self.Ahrs1Rx,self.Ahrs1Ry,self.Ahrs1Rz,self.Ahrs1AccConfidence,self.Ahrs1YawTarget = 0,0,0,0,0
        self.Ahrs2Rx,self.Ahrs2Ry,self.Ahrs2Rz,self.Ahrs2AccConfidence,self.Ahrs2YawTarget = 0,0,0,0,0

        self.ParameterAdr,self.ParameterValue,self.ParameterFormat,self.ParameterNameStr = 0,0,0,''

        self.CameraFlags,self.CameraModel,self.CameraCmd,self.CameraUnused,self.CameraPwm = 0,0,0,0,0

        #injected values
        self.Time = self.TimeStamp32
        self.ftemp1 = self.temp1/340.0 + 36.53
        self.ftemp2 = self.temp2/340.0 + 36.53
        self.ftemp3 = self.temp3/340.0 + 36.53
        self.fAhrs1AccAmp = 0.0

    def setLogVersion(self,ver):
        self.logVersion = ver

    def getLogVersion(self):
        return self.logVersion

    def clear(self):
        self.TimeStamp32 = 0
        self.Imu1received,self.Imu1done,self.PIDdone,self.Motorsdone  = 0,0,0,0
        self.Imu2received,self.Imu2done,self.Logdone,self.Loopdone = 0,0,0,0
        self.State,self.Status,self.Status2,self.ErrorCnt,self.Voltage = 0,0,0,0,0
        self.Imu1AnglePitch,self.Imu1AngleRoll,self.Imu1AngleYaw,self.Imu2AnglePitch,self.Imu2AngleRoll,self.Imu2AngleYaw = 0,0,0,0,0,0

        self.Flags,self.VmaxPitch,self.AnglePitch,self.VmaxRoll,self.AngleRoll,self.VmaxYaw,self.AngleYaw = 0,0,0,0,0,0,0

        self.ax1,self.ay1,self.az1,self.gx1,self.gy1,self.gz1,self.ImuState1 = 0,0,0,0,0,0,0
        self.ax2,self.ay2,self.az2,self.gx2,self.gy2,self.gz2,self.ImuState2 = 0,0,0,0,0,0,0

        self.ax1raw,self.ay1raw,self.az1raw,self.gx1raw,self.gy1raw,self.gz1raw,self.temp1 = 0,0,0,0,0,0,0
        self.ax2raw,self.ay2raw,self.az2raw,self.gx2raw,self.gy2raw,self.gz2raw,self.temp2 = 0,0,0,0,0,0,0
        self.ax3raw,self.ay3raw,self.az3raw,self.gx3raw,self.gy3raw,self.gz3raw,self.temp3 = 0,0,0,0,0,0,0

        self.PIDCntrlPitch,self.PIDCntrlRoll,self.PIDCntrlYaw = 0,0,0
        self.PIDMotorCntrlPitch,self.PIDMotorCntrlRoll,self.PIDMotorCntrlYaw = 0,0,0

        self.Ahrs1Rx,self.Ahrs1Ry,self.Ahrs1Rz,self.Ahrs1AccConfidence,self.Ahrs1YawTarget = 0,0,0,0,0
        self.Ahrs2Rx,self.Ahrs2Ry,self.Ahrs2Rz,self.Ahrs2AccConfidence,self.Ahrs2YawTarget = 0,0,0,0,0

        self.CameraFlags,self.CameraModel,self.CameraCmd,self.CameraUnused,self.CameraPwm = 0,0,0,0,0

        self.error = cNTDATAFRAME_OK #new frame, new game

    #some default functions to set values
    def setLogger_V0(self,tupel):
        (self.TimeStamp32,
         self.Imu1received,self.Imu1done,self.PIDdone,self.Motorsdone,
         self.Imu2received,self.Imu2done,self.Loopdone,
         self.State,self.Status,self.Status2,self.ErrorCnt,self.Voltage,
         self.Imu1AnglePitch,self.Imu1AngleRoll,self.Imu1AngleYaw,
         self.Imu2AnglePitch,self.Imu2AngleRoll,self.Imu2AngleYaw,
        ) = tupel
    def setLogger_V3(self,tupel):
        (self.TimeStamp32,
         self.Imu1received,self.Imu1done,self.PIDdone,self.Motorsdone,
         self.Imu2done,self.Logdone,self.Loopdone,
         self.State,self.Status,self.Status2,self.ErrorCnt,self.Voltage,
         self.Imu1AnglePitch,self.Imu1AngleRoll,self.Imu1AngleYaw,
         self.Imu2AnglePitch,self.Imu2AngleRoll,self.Imu2AngleYaw,
        ) = tupel

    def setMotorAll(self,tupel):
        (self.Flags,self.VmaxPitch,self.AnglePitch,self.VmaxRoll,self.AngleRoll,self.VmaxYaw,self.AngleYaw) = tupel

    def setCamera(self,tupel):
        (self.CameraFlags,self.CameraModel,self.CameraCmd,self.CameraUnused,self.CameraPwm) = tupel

    def cmdAccGyro1_V2(self,tupel):
        (self.ax1,self.ay1,self.az1,self.gx1,self.gy1,self.gz1,self.ImuState1) = tupel

    def cmdAccGyro2_V2(self,tupel):
        (self.ax2,self.ay2,self.az2,self.gx2,self.gy2,self.gz2,self.ImuState2) = tupel

    def cmdAccGyro1Raw_V2(self,tupel):
        (self.ax1raw,self.ay1raw,self.az1raw,self.gx1raw,self.gy1raw,self.gz1raw,self.temp1) = tupel

    def cmdAccGyro2Raw_V2(self,tupel):
        (self.ax2raw,self.ay2raw,self.az2raw,self.gx2raw,self.gy2raw,self.gz2raw,self.temp2) = tupel

    def cmdAccGyro3Raw_V2(self,tupel):
        (self.ax3raw,self.ay3raw,self.az3raw,self.gx3raw,self.gy3raw,self.gz3raw,self.temp3) = tupel

    def cmdPid(self,tupel):
        (self.PIDCntrlPitch,self.PIDCntrlRoll,self.PIDCntrlYaw,
         self.PIDMotorCntrlPitch,self.PIDMotorCntrlRoll,self.PIDMotorCntrlYaw) = tupel

    def cmdAhrs1(self,tupel):
        (self.Ahrs1Rx,self.Ahrs1Ry,self.Ahrs1Rz,self.Ahrs1AccConfidence,self.Ahrs1YawTarget) = tupel

    def cmdAhrs2(self,tupel):
        (self.Ahrs2Rx,self.Ahrs2Ry,self.Ahrs2Rz,self.Ahrs2AccConfidence,self.Ahrs2YawTarget) = tupel

    def cmdAccGyro_V1(self,tupel):
        (self.ax1,self.ay1,self.az1,self.gx1,self.gy1,self.gz1,self.temp1,self.ImuState1,
         self.ax2,self.ay2,self.az2,self.gx2,self.gy2,self.gz2,self.temp2,self.ImuState2) = tupel

    def cmdAccGyro1Raw_V1(self,tupel):
        (self.ax1raw,self.ay1raw,self.az1raw,self.gx1raw,self.gy1raw,self.gz1raw) = tupel

    def cmdAccGyro2Raw_V1(self,tupel):
        (self.ax2raw,self.ay2raw,self.az2raw,self.gx2raw,self.gy2raw,self.gz2raw) = tupel

    def cmdAccGyro3Raw_V1(self,tupel):
        (self.ax3raw,self.ay3raw,self.az3raw,self.gx3raw,self.gy3raw,self.gz3raw) = tupel

    def cmdParameter(self,tupel):
        (self.ParameterAdr,self.ParameterValue,self.ParameterFormat,self.ParameterNameStr) = tupel
        if self.ParameterFormat==4: #MAV_PARAM_TYPE_INT16 = 4
            if self.ParameterValue>32768: self.ParameterValue -= 65536

    #some default prototypes, are all called by parser
    def doSetLogger(self,payload): return True
    def doSetMotorAll(self,payload): return True
    def doSetCamera(self,payload): return True
    def doCmdAccGyro1_V2(self,payload): return True
    def doCmdAccGyro2_V2(self,payload): return True
    def doCmdAccGyro1Raw_V2(self,payload): return True
    def doCmdAccGyro2Raw_V2(self,payload): return True
    def doCmdAccGyro3Raw_V2(self,payload): return True
    def doCmdPid(self,payload): return True
    def doCmdAhrs1(self,payload): return True
    def doCmdAhrs2(self,payload): return True
    def doCmdAccGyro_V1(self,payload): return True
    def doCmdAccGyro1Raw_V1(self,payload): return True
    def doCmdAccGyro2Raw_V1(self,payload): return True
    def doCmdAccGyro3Raw_V1(self,payload): return True
    def doCmdParameter(self,payload): return True

    def readCmdByte(self): return 255

    def calculateTime(self,datalog_TimeStamp32_start):
        self.Time = self.TimeStamp32 - datalog_TimeStamp32_start

    def calculateInjectedValues(self):
        self.ftemp1 = self.temp1/340.0 + 36.53
        self.ftemp2 = self.temp2/340.0 + 36.53
        self.ftemp3 = self.temp3/340.0 + 36.53
        self.fAhrs1AccAmp = sqrt(self.ax1*self.ax1 + self.ay1*self.ay1 + self.az1*self.az1)*10000.0/8192.0

    #------------------------------------------
    #NTbus data logs: the order must match that of setToDataLoggerItemList()
    def getDataLine(self):
        dataline = ''
        dataline +=  '{:.1f}'.format(0.001*self.Time) + "\t"

        dataline +=  str(10*self.Imu1received) + "\t"
        dataline +=  str(10*self.Imu1done) + "\t"
        dataline +=  str(10*self.PIDdone) + "\t"
        dataline +=  str(10*self.Motorsdone) + "\t"
        dataline +=  str(10*self.Imu2received) + "\t"
        dataline +=  str(10*self.Imu2done) + "\t"
        dataline +=  str(10*self.Logdone) + "\t"
        dataline +=  str(10*self.Loopdone) + "\t"

        dataline +=  str(self.State) + "\t"
        dataline +=  str(self.Status) + "\t"
        dataline +=  str(self.Status2) + "\t"
        dataline +=  str(self.ErrorCnt) + "\t"
        dataline +=  '{:.3f}'.format(0.001 * self.Voltage) + "\t"

        dataline +=  str(self.ax1) + "\t" + str(self.ay1) + "\t" + str(self.az1) + "\t"
        dataline +=  str(self.gx1) + "\t" + str(self.gy1) + "\t" + str(self.gz1) + "\t"
        dataline +=  str(self.ImuState1) + "\t"
        dataline +=  str(self.ax2) + "\t" + str(self.ay2) + "\t" + str(self.az2) + "\t"
        dataline +=  str(self.gx2) + "\t" + str(self.gy2) + "\t" + str(self.gz2) + "\t"
        dataline +=  str(self.ImuState2) + "\t"

        if self.logVersion==cLOGVERSION_V3:
            dataline +=  '{:.3f}'.format( 0.001 * self.Imu1AnglePitch ) + "\t"
            dataline +=  '{:.3f}'.format( 0.001 * self.Imu1AngleRoll ) + "\t"
            dataline +=  '{:.3f}'.format( 0.001 * self.Imu1AngleYaw ) + "\t"
            dataline +=  '{:.3f}'.format( 0.001 * self.Imu2AnglePitch ) + "\t"
            dataline +=  '{:.3f}'.format( 0.001 * self.Imu2AngleRoll ) + "\t"
            dataline +=  '{:.3f}'.format( 0.001 * self.Imu2AngleYaw ) + "\t"
        else:
            dataline +=  '{:.2f}'.format( 0.01 * self.Imu1AnglePitch ) + "\t"
            dataline +=  '{:.2f}'.format( 0.01 * self.Imu1AngleRoll ) + "\t"
            dataline +=  '{:.2f}'.format( 0.01 * self.Imu1AngleYaw ) + "\t"
            dataline +=  '{:.2f}'.format( 0.01 * self.Imu2AnglePitch ) + "\t"
            dataline +=  '{:.2f}'.format( 0.01 * self.Imu2AngleRoll ) + "\t"
            dataline +=  '{:.2f}'.format( 0.01 * self.Imu2AngleYaw ) + "\t"

        dataline +=  '{:.2f}'.format( 0.01 * self.PIDCntrlPitch ) + "\t"
        dataline +=  '{:.2f}'.format( 0.01 * self.PIDCntrlRoll ) + "\t"
        dataline +=  '{:.2f}'.format( 0.01 * self.PIDCntrlYaw ) + "\t"
        dataline +=  '{:.2f}'.format( 0.01 * self.PIDMotorCntrlPitch ) + "\t"
        dataline +=  '{:.2f}'.format( 0.01 * self.PIDMotorCntrlRoll ) + "\t"
        dataline +=  '{:.2f}'.format( 0.01 * self.PIDMotorCntrlYaw ) + "\t"

        dataline +=  '{:.4f}'.format(0.0001 * self.Ahrs1Rx) + "\t"
        dataline +=  '{:.4f}'.format(0.0001 * self.Ahrs1Ry) + "\t"
        dataline +=  '{:.4f}'.format(0.0001 * self.Ahrs1Rz) + "\t"
        dataline +=  '{:.4f}'.format(0.0001 * self.fAhrs1AccAmp) + "\t"
        dataline +=  '{:.4f}'.format(0.0001 * self.Ahrs1AccConfidence) + "\t"
        dataline +=  '{:.2f}'.format(0.01 * self.Ahrs1YawTarget) + "\t"

        dataline +=  str(self.Flags) + "\t"
        dataline +=  str(self.VmaxPitch) + "\t" + str(self.AnglePitch) + "\t"
        dataline +=  str(self.VmaxRoll) + "\t"  + str(self.AngleRoll) + "\t"
        dataline +=  str(self.VmaxYaw) + "\t"   + str(self.AngleYaw) + "\t"

        dataline +=  str(self.ax1raw) + "\t" + str(self.ay1raw) + "\t" + str(self.az1raw) + "\t"
        dataline +=  str(self.gx1raw) + "\t" + str(self.gy1raw) + "\t" + str(self.gz1raw) + "\t"
        dataline +=  '{:.2f}'.format(self.ftemp1) + "\t"

        dataline +=  str(self.ax2raw) + "\t" + str(self.ay2raw) + "\t" + str(self.az2raw) + "\t"
        dataline +=  str(self.gx2raw) + "\t" + str(self.gy2raw) + "\t" + str(self.gz2raw) + "\t"
        dataline +=  '{:.2f}'.format(self.ftemp2) + "\t"

        dataline +=  str(self.ax3raw) + "\t" + str(self.ay3raw) + "\t" + str(self.az3raw) + "\t"
        dataline +=  str(self.gx3raw) + "\t" + str(self.gy3raw) + "\t" + str(self.gz3raw) + "\t"
        dataline +=  '{:.2f}'.format(self.ftemp3) + "\t"

        dataline +=  str(self.CameraCmd) + "\t" + str(self.CameraPwm) + "\n"

        return dataline

    #------------------------------------------
    #NTbus data logs: the order must match that of setToDataLoggerItemList()
    def getRawDataLine(self):
        rawdataline = []
        rawdataline.append(self.Time)

        rawdataline.append(10*self.Imu1received)
        rawdataline.append(10*self.Imu1done)
        rawdataline.append(10*self.PIDdone)
        rawdataline.append(10*self.Motorsdone)
        rawdataline.append(10*self.Imu2received)
        rawdataline.append(10*self.Imu2done)
        rawdataline.append(10*self.Logdone)
        rawdataline.append(10*self.Loopdone)

        rawdataline.append(self.State)
        rawdataline.append(self.Status)
        rawdataline.append(self.Status2)
        rawdataline.append(self.ErrorCnt)
        rawdataline.append(int(self.Voltage))

        rawdataline.append(self.ax1)
        rawdataline.append(self.ay1)
        rawdataline.append(self.az1)
        rawdataline.append(self.gx1)
        rawdataline.append(self.gy1)
        rawdataline.append(self.gz1)
        rawdataline.append(self.ImuState1)
        rawdataline.append(self.ax2)
        rawdataline.append(self.ay2)
        rawdataline.append(self.az2)
        rawdataline.append(self.gx2)
        rawdataline.append(self.gy2)
        rawdataline.append(self.gz2)
        rawdataline.append(self.ImuState2)

        rawdataline.append(self.Imu1AnglePitch)
        rawdataline.append(self.Imu1AngleRoll)
        rawdataline.append(self.Imu1AngleYaw)
        rawdataline.append(self.Imu2AnglePitch)
        rawdataline.append(self.Imu2AngleRoll)
        rawdataline.append(self.Imu2AngleYaw)

        rawdataline.append(self.PIDCntrlPitch)
        rawdataline.append(self.PIDCntrlRoll)
        rawdataline.append(self.PIDCntrlYaw)
        rawdataline.append(self.PIDMotorCntrlPitch)
        rawdataline.append(self.PIDMotorCntrlRoll)
        rawdataline.append(self.PIDMotorCntrlYaw)

        rawdataline.append(self.Ahrs1Rx)
        rawdataline.append(self.Ahrs1Ry)
        rawdataline.append(self.Ahrs1Rz)
        rawdataline.append(int(self.fAhrs1AccAmp))
        rawdataline.append(self.Ahrs1AccConfidence)
        rawdataline.append(self.Ahrs1YawTarget)

        rawdataline.append(self.Flags)
        rawdataline.append(self.VmaxPitch)
        rawdataline.append(self.AnglePitch)
        rawdataline.append(self.VmaxRoll)
        rawdataline.append(self.AngleRoll)
        rawdataline.append(self.VmaxYaw)
        rawdataline.append(self.AngleYaw)

        rawdataline.append(self.ax1raw)
        rawdataline.append(self.ay1raw)
        rawdataline.append(self.az1raw)
        rawdataline.append(self.gx1raw)
        rawdataline.append(self.gy1raw)
        rawdataline.append(self.gz1raw)
        rawdataline.append(self.temp1)

        rawdataline.append(self.ax2raw)
        rawdataline.append(self.ay2raw)
        rawdataline.append(self.az2raw)
        rawdataline.append(self.gx2raw)
        rawdataline.append(self.gy2raw)
        rawdataline.append(self.gz2raw)
        rawdataline.append(self.temp2)

        rawdataline.append(self.ax3raw)
        rawdataline.append(self.ay3raw)
        rawdataline.append(self.az3raw)
        rawdataline.append(self.gx3raw)
        rawdataline.append(self.gy3raw)
        rawdataline.append(self.gz3raw)
        rawdataline.append(self.temp3)

        rawdataline.append(self.CameraCmd)
        rawdataline.append(self.CameraPwm)

        return rawdataline


#this is a child class for handling NT log files
class cNTLogFileDataFrame(cNTDataFrameObject):

    def __init__(self):
        super().__init__()

        #structures of data as stored in NT log files, recorded by a NT Logger
        self.setLoggerStruct_V0 = struct.Struct('=I'+'BBBBBBB'+'HHHHH'+'hhhhhh')
        self.setLoggerStruct_V3 = struct.Struct('=I'+'BBBBBBB'+'HHHHH'+'iiiiii')
        self.setMotorAllStruct = struct.Struct('=BBhBhBh')
        self.setCameraStruct = struct.Struct('=BBBBH')
        self.cmdAccGyroStruct_V1 = struct.Struct('=hhhhhhhB'+'hhhhhhhB')
        self.cmdAccGyroStruct_V2 = struct.Struct('=hhhhhhB')
        self.cmdAccGyroRawStruct_V1 = struct.Struct('=hhhhhh')
        self.cmdAccGyroRawStruct_V2 = struct.Struct('=hhhhhhh')
        self.cmdPidStruct = struct.Struct('=hhhhhh')
        self.cmdAhrsStruct = struct.Struct('=hhhhh')
        self.cmdParameterStruct = struct.Struct('=HHH16s')

    def unpackSetLogger(self,payload):
        if self.logVersion==cLOGVERSION_V3:
            self.setLogger_V3( self.setLoggerStruct_V3.unpack(payload) )
        else:
            self.setLogger_V0( self.setLoggerStruct_V0.unpack(payload) )

    def unpackSetMotorAll(self,payload): #struct.Struct('=BBhBhBh')
        (self.Flags,self.VmaxPitch,self.AnglePitch,self.VmaxRoll,self.AngleRoll,self.VmaxYaw,self.AngleYaw
         ) = self.setMotorAllStruct.unpack(payload)

    def unpackSetCamera(self,payload): #struct.Struct('=BBBH')
        (self.CameraFlags,self.CameraModel,self.CameraCmd,self.CameraUnused,self.CameraPwm
         ) = self.setCameraStruct.unpack(payload)

    def unpackCmdAccGyro1_V2(self,payload): #struct.Struct('=hhhhhhB')
        (self.ax1,self.ay1,self.az1,self.gx1,self.gy1,self.gz1,self.ImuState1
         ) = self.cmdAccGyroStruct_V2.unpack(payload)

    def unpackCmdAccGyro2_V2(self,payload): #struct.Struct('=hhhhhhB')
        (self.ax2,self.ay2,self.az2,self.gx2,self.gy2,self.gz2,self.ImuState2
         ) = self.cmdAccGyroStruct_V2.unpack(payload)

    def unpackCmdAccGyro1Raw_V2(self,payload): #struct.Struct('=hhhhhhh')
        (self.ax1raw,self.ay1raw,self.az1raw,self.gx1raw,self.gy1raw,self.gz1raw,self.temp1
         ) = self.cmdAccGyroRawStruct_V2.unpack(payload)

    def unpackCmdAccGyro2Raw_V2(self,payload): #struct.Struct('=hhhhhhh')
        (self.ax2raw,self.ay2raw,self.az2raw,self.gx2raw,self.gy2raw,self.gz2raw,self.temp2
         ) =  self.cmdAccGyroRawStruct_V2.unpack(payload)

    def unpackCmdAccGyro3Raw_V2(self,payload): #struct.Struct('=hhhhhhh')
        (self.ax3raw,self.ay3raw,self.az3raw,self.gx3raw,self.gy3raw,self.gz3raw,self.temp3
         ) = self.cmdAccGyroRawStruct_V2.unpack(payload)

    def unpackCmdPid(self,payload): #struct.Struct('=hhhhhh')
        (self.PIDCntrlPitch,self.PIDCntrlRoll,self.PIDCntrlYaw,
         self.PIDMotorCntrlPitch,self.PIDMotorCntrlRoll,self.PIDMotorCntrlYaw
         ) = self.cmdPidStruct.unpack(payload)

    def unpackCmdAhrs1(self,payload): #struct.Struct('=hhhhh')
        (self.Ahrs1Rx,self.Ahrs1Ry,self.Ahrs1Rz,self.Ahrs1AccConfidence,self.Ahrs1YawTarget
         ) = self.cmdAhrsStruct.unpack(payload)

    def unpackCmdAhrs2(self,payload): #struct.Struct('=hhhhh')
        (self.Ahrs2Rx,self.Ahrs2Ry,self.Ahrs2Rz,self.Ahrs2AccConfidence,self.Ahrs2YawTarget
         ) = self.cmdAhrsStruct.unpack(payload)

    def unpackCmdAccGyro_V1(self,payload): #struct.Struct('=hhhhhhhB'+'hhhhhhhB')
        (self.ax1,self.ay1,self.az1,self.gx1,self.gy1,self.gz1,self.temp1,self.ImuState1,
         self.ax2,self.ay2,self.az2,self.gx2,self.gy2,self.gz2,self.temp2,self.ImuState2
         ) = self.cmdAccGyroStruct_V1.unpack(payload)

    def unpackCmdAccGyro1Raw_V1(self,payload): #struct.Struct('=hhhhhh')
        (self.ax1raw,self.ay1raw,self.az1raw,self.gx1raw,self.gy1raw,self.gz1raw
         ) = self.cmdAccGyroRawStruct_V1.unpack(payload)

    def unpackCmdAccGyro2Raw_V1(self,payload):
        (self.ax2raw,self.ay2raw,self.az2raw,self.gx2raw,self.gy2raw,self.gz2raw
         ) = self.cmdAccGyroRawStruct_V1.unpack(payload)

    def unpackCmdAccGyro3Raw_V1(self,payload):
        (self.ax3raw,self.ay3raw,self.az3raw,self.gx3raw,self.gy3raw,self.gz3raw
         ) = self.cmdAccGyroRawStruct_V1.unpack(payload)

    def unpackCmdParameter(self,payload):
        (self.ParameterAdr,self.ParameterValue,self.ParameterFormat,self.ParameterNameStr
         ) = self.cmdParameterStruct.unpack(payload)
        if self.ParameterFormat==4: #MAV_PARAM_TYPE_INT16 = 4
            if self.ParameterValue>32768: self.ParameterValue -= 65536

    def doSetLogger(self,payload): self.unpackSetLogger(payload); return True
    def doSetMotorAll(self,payload): self.unpackSetMotorAll(payload); return True
    def doSetCamera(self,payload): self.unpackSetCamera(payload); return True
    def doCmdAccGyro1_V2(self,payload): self.unpackCmdAccGyro1_V2(payload); return True
    def doCmdAccGyro2_V2(self,payload): self.unpackCmdAccGyro2_V2(payload); return True
    def doCmdAccGyro1Raw_V2(self,payload): self.unpackCmdAccGyro1Raw_V2(payload); return True
    def doCmdAccGyro2Raw_V2(self,payload): self.unpackCmdAccGyro2Raw_V2(payload); return True
    def doCmdAccGyro3Raw_V2(self,payload): self.unpackCmdAccGyro3Raw_V2(payload); return True
    def doCmdPid(self,payload): self.unpackCmdPid(payload); return True
    def doCmdAhrs1(self,payload): self.unpackCmdAhrs1(payload); return True
    def doCmdAhrs2(self,payload): self.unpackCmdAhrs2(payload); return True
    def doCmdAccGyro_V1(self,payload): self.unpackCmdAccGyro_V1(payload); return True
    def doCmdAccGyro1Raw_V1(self,payload): self.unpackCmdAccGyro1Raw_V1(payload); return True
    def doCmdAccGyro2Raw_V1(self,payload): self.unpackCmdAccGyro2Raw_V1(payload); return True
    def doCmdAccGyro3Raw_V1(self,payload): self.unpackCmdAccGyro3Raw_V1(payload); return True
    def doCmdParameter(self,payload): self.unpackCmdParameter(payload); return True


cSETLOGGER_V3_DATALEN             = 36
cSETLOGGER_V3_HIGHBITSLEN         = 6
cSETLOGGER_V3_FRAMELEN            = 36 + 6 #+ 1
cSETMOTORALL_DATALEN              = 10
cSETMOTORALL_FRAMELEN             = 10 #10 + 1
cSETCAMERA_DATALEN                = 5
cSETCAMERA_FRAMELEN               = 5 #5 + 1
cCMDACCGYRODATA_V2_DATALEN        = 13
cCMDACCGYRODATA_V2_HIGHBITSLEN    = 2
cCMDACCGYRODATA_V2_FRAMELEN       = 13 + 2 #13 + 2 + 1
cCMDACCGYRORAWDATA_V2_DATALEN     = 14
cCMDACCGYRORAWDATA_V2_HIGHBITSLEN = 2
cCMDACCGYRORAWDATA_V2_FRAMELEN    = 14 + 2 #14 + 2 + 1
cCMDPIDDATA_DATALEN               = 12
cCMDPIDDATA_HIGHBITSLEN           = 2
cCMDPIDDATA_FRAMELEN              = 12 + 2 #12 + 2 + 1
cCMDAHRSDATA_DATALEN              = 10
cCMDAHRSDATA_HIGHBITSLEN          = 2
cCMDAHRSDATA_FRAMELEN             = 10 + 2 #10 + 2 + 1

#this is a child class for handling NT serial data streams
# a frame error must ONLY be thrown, then one of the crucial packages is wrong,
# i.e. SetLogger, SetMotorAll !!
class cNTSerialDataFrame(cNTLogFileDataFrame):

    def __init__(self, _reader):
        super().__init__()
        self.reader = _reader

        #structures of data as transmitted on the NT bus, recorded by a USB-TTL adapter
        # differs for SetMotAll and SetLog from a NT log file
        self.setLoggerStruct_V3_NTbus = struct.Struct('=I'+'BBBBBBB'+'HHHHH'+'hhhhhh'+'BBB')
        self.setCameraStruct_NTBus = struct.Struct('=BBBBB')

        self.setLogVersion(cLOGVERSION_LATEST) #tells its latest version, not needed as done by __init__(), but be explicit

    def doSetLogger(self,payload):
        (b,err) = self.reader.readPayload(cSETLOGGER_V3_FRAMELEN)
        if err or self.crcError(b): self.error |= cNTDATAFRAME_SETLOGERROR #; return !!IT MUST NOT BE REJECTED FOR SETLOG!!
        payload = self.decode(b, cSETLOGGER_V3_DATALEN, cSETLOGGER_V3_HIGHBITSLEN)
        #if payload!=None and not self.checkReaderError(): !!IT MUST NOT BE REJECTED FOR SETLOG!!!
        #self.unpackSetLogger(payload)
        #self.setLogger( self.setLoggerStruct_V3_NTbus.unpack(payload) )
        (self.TimeStamp32,
         self.Imu1received,self.Imu1done,self.PIDdone,self.Motorsdone,
         self.Imu2done,self.Logdone,self.Loopdone,
         self.State,self.Status,self.Status2,self.ErrorCnt,self.Voltage,
         self.Imu1AnglePitch,self.Imu1AngleRoll,self.Imu1AngleYaw,
         self.Imu2AnglePitch,self.Imu2AngleRoll,self.Imu2AngleYaw,
         self.highres1,self.highres2,self.highres3,
        ) = self.setLoggerStruct_V3_NTbus.unpack(payload)
        self.Imu1AnglePitch = self.Imu1AnglePitch*16 + (self.highres1 & 0x0f)
        self.Imu1AngleRoll = self.Imu1AngleRoll*16 + (self.highres2 & 0x0f)
        self.Imu1AngleYaw = self.Imu1AngleYaw*16 + (self.highres3 & 0x0f)
        self.Imu2AnglePitch = self.Imu2AnglePitch*16 + ((self.highres1>>4) & 0x0f)
        self.Imu2AngleRoll = self.Imu2AngleRoll*16 + ((self.highres2>>4) & 0x0f)
        self.Imu2AngleYaw = self.Imu2AngleYaw*16 + ((self.highres3>>4) & 0x0f)
        return True

    def doSetMotorAll(self,payload):
        (b,err) = self.reader.readPayload(cSETMOTORALL_FRAMELEN) #XX THIS NEEDS TO BE DECODED!!!
        if err or self.crcError(b,): self.error |= cNTDATAFRAME_SETMOTERROR; return False
        payload = b
        self.unpackSetMotorAll(payload)
        # p->VmaxPitch <<= 1;//ntbus_buf[1]
        # a = (u16)(ntbus_buf[2]) + ((u16)(ntbus_buf[3]) << 7);
        self.VmaxPitch <<= 1
        self.AnglePitch = self.AnglePitch&0x00ff + ( (self.AnglePitch&0xff00)>>1 )
        self.VmaxRoll <<= 1
        self.AngleRoll = self.AngleRoll&0x00ff + ( (self.AngleRoll&0xff00)>>1 )
        self.VmaxYaw <<= 1
        self.AngleYaw = self.AngleYaw&0x00ff + ( (self.AngleYaw&0xff00)>>1 )
        return True

    def doSetCamera(self,payload):
        (b,err) = self.reader.readPayload(cSETCAMERA_FRAMELEN)
        if err or self.crcError(b): self.error |= cNTDATAFRAME_CMDERROR; return False
        payload = b
        (self.CameraFlags,self.CameraModel,self.CameraCmd,self.CameraUnused,self.CameraPwm
         ) = self.setCameraStruct_NTBus.unpack(payload)
        ##    if( pwm>0 ) pwm = (pwm-1) * 10 + 1000;
        if self.CameraPwm > 0: self.CameraPwm = (self.CameraPwm-1) * 10 + 1000
        return True

    def doCmdAccGyro1_V2(self,payload):
        (b,err) = self.reader.readPayload(cCMDACCGYRODATA_V2_FRAMELEN)
        if err or self.crcError(b): self.error |= cNTDATAFRAME_CMDERROR; return False
        payload = self.decode(b, cCMDACCGYRODATA_V2_DATALEN, cCMDACCGYRODATA_V2_HIGHBITSLEN)
        self.unpackCmdAccGyro1_V2(payload)
        return True

    def doCmdAccGyro2_V2(self,payload):
        (b,err) = self.reader.readPayload(cCMDACCGYRODATA_V2_FRAMELEN)
        if err or self.crcError(b): self.error |= cNTDATAFRAME_CMDERROR; return False
        payload = self.decode(b, cCMDACCGYRODATA_V2_DATALEN, cCMDACCGYRODATA_V2_HIGHBITSLEN)
        self.unpackCmdAccGyro2_V2(payload)
        return True

    def doCmdAccGyro1Raw_V2(self,payload):
        (b,err) = self.reader.readPayload(cCMDACCGYRORAWDATA_V2_FRAMELEN)
        if err or self.crcError(b): self.error |= cNTDATAFRAME_CMDERROR; return False
        payload = self.decode(b, cCMDACCGYRORAWDATA_V2_DATALEN, cCMDACCGYRORAWDATA_V2_HIGHBITSLEN)
        self.unpackCmdAccGyro1Raw_V2(payload)
        return True

    def doCmdAccGyro2Raw_V2(self,payload):
        (b,err) = self.reader.readPayload(cCMDACCGYRORAWDATA_V2_FRAMELEN)
        if err or self.crcError(b): self.error |= cNTDATAFRAME_CMDERROR; return False
        payload = self.decode(b, cCMDACCGYRORAWDATA_V2_DATALEN, cCMDACCGYRORAWDATA_V2_HIGHBITSLEN)
        self.unpackCmdAccGyro2Raw_V2(payload)
        return True

    def doCmdAccGyro3Raw_V2(self,payload):
        (b,err) = self.reader.readPayload(cCMDACCGYRORAWDATA_V2_FRAMELEN)
        if err or self.crcError(b): self.error |= cNTDATAFRAME_CMDERROR; return False
        payload = self.decode(b, cCMDACCGYRORAWDATA_V2_DATALEN, cCMDACCGYRORAWDATA_V2_HIGHBITSLEN)
        self.unpackCmdAccGyro3Raw_V2(payload)
        return True

    def doCmdPid(self,payload):
        (b,err) = self.reader.readPayload(cCMDPIDDATA_FRAMELEN)
        if err or self.crcError(b): self.error |= cNTDATAFRAME_CMDERROR; return False
        payload = self.decode(b, cCMDPIDDATA_DATALEN, cCMDPIDDATA_HIGHBITSLEN)
        self.unpackCmdPid(payload)
        return True

    def doCmdAhrs1(self,payload):
        (b,err) = self.reader.readPayload(cCMDAHRSDATA_FRAMELEN)
        if err or self.crcError(b): self.error |= cNTDATAFRAME_CMDERROR; return False
        payload = self.decode(b, cCMDAHRSDATA_DATALEN, cCMDAHRSDATA_HIGHBITSLEN)
        self.unpackCmdAhrs1(payload)
        return True

    def doCmdAhrs2(self,payload): return False
    def doCmdAccGyro_V1(self,payload): return False
    def doCmdAccGyro1Raw_V1(self,payload): return False
    def doCmdAccGyro2Raw_V1(self,payload): return False
    def doCmdAccGyro3Raw_V1(self,payload): return False
    def doCmdParameter(self,payload): return False

    def readCmdByte(self):
        (b,err) = self.reader.readPayload(1)
        if err: return 255 #hopefully a really invalid CmdByte
        return int(b[0])

    def decode(self,b,datalen,highbitslen): #returns a bytearray of the raw values
        highbits = b[datalen:datalen+highbitslen]
        highbytenr = 0
        bitpos = 0x01
        d = bytearray()
        crc = 0
        for n in range(datalen):
            if bitpos==0x80:
                highbytenr += 1
                bitpos = 0x01
            c = b[n]
            if highbits[highbytenr] & bitpos: c |= 0x80
            d.append(c)
            crc = crc ^ c
            bitpos <<= 1
        return d

    def crcError(self,payload):
        (b,err) = self.reader.readPayload(1)
        if err: return True
        crc = int(b[0])
        crcpayload = 0
        for n in range(len(payload)): crcpayload = crcpayload ^ payload[n]
        if crcpayload != crc: return True
        return False


###############################################################################
# cNTLogParser
# this is the main class to parse a stream of log packets into a cNTDataFrameObject
#-----------------------------------------------------------------------------#
cCMD_RES    = 0x50 #'RES ';
cCMD_SET    = 0x40 #'SET ';
cCMD_GET    = 0x30 #'GET ';
cCMD_TRG    = 0x10 #'TRG ';
cCMD_CMD    = 0x00 #'CMD ';

cID_ALL     = 0  #'ALL  ';
cID_IMU1    = 1  #'IMU1 '
cID_IMU2    = 2  #'IMU2 '
cID_MOTA    = 3  #'MOTA ';
cID_CAMERA  = 7  #'CAM  ';
cID_LOG     = 11 #'LOG  ';
cID_IMU3    = 12 #'IMU3 '

cRESALL     = 0x80 + cCMD_RES + cID_ALL  #0xD0
cTRGALL     = 0x80 + cCMD_TRG + cID_ALL  #0x90
cGETIMU1    = 0x80 + cCMD_GET + cID_IMU1 #0xB1
cGETIMU2    = 0x80 + cCMD_GET + cID_IMU2 #0xB2
cGETIMU3    = 0x80 + cCMD_GET + cID_IMU3 #0xBC
cSETMOTA    = 0x80 + cCMD_SET + cID_MOTA #0xC3
cSETCAMERA  = 0x80 + cCMD_SET + cID_CAMERA
cSETLOG     = 0x80 + cCMD_SET + cID_LOG  #0xCB
cCMDLOG     = 0x80 + cCMD_CMD + cID_LOG  #0x8B

cCMDBYTE_AccGyro1RawData_V1 = 32 #CMD LOG  AccGyro1RawData 32 ###DEPRECATED
cCMDBYTE_AccGyro2RawData_V1 = 33 #CMD LOG  AccGyro2RawData 33 ###DEPRECATED
cCMDBYTE_AccGyroData_V1     = 34 #CMD LOG  AccGyroData 34  ###DEPRECATED
cCMDBYTE_PidData            = 35 #CMD LOG  PidData 35
cCMDBYTE_ParameterData      = 36 #CMD LOG  ParameterData 36
cCMDBYTE_Ahrs1Data          = 37 #CMD LOG  Ahrs1Data 37
cCMDBYTE_Ahrs2Data          = 38 #CMD LOG  Ahrs2Data 38
cCMDBYTE_AccGyro3RawData_V1 = 39 #CMD LOG  AccGyro3RawData 39  ###DEPRECATED

cCMDBYTE_AccGyro1RawData_V2 = 40 #CMD LOG  AccGyro1RawData_V2 40
cCMDBYTE_AccGyro2RawData_V2 = 41 #CMD LOG  AccGyro2RawData_V2 41
cCMDBYTE_AccGyro3RawData_V2 = 42 #CMD LOG  AccGyro3RawData_V2 42

cCMDBYTE_AccGyro1Data_V2    = 43 #CMD LOG  AccGyro1Data_V2 43
cCMDBYTE_AccGyro2Data_V2    = 44 #CMD LOG  AccGyro2Data_V2 44

#the reader must provide a function
# reader.appendDataFrame(frame)
#
# baseTime allows to shift the start time
class cNTLogParser:

    def __init__(self,_frame,_reader,_baseTime=0):
        self.reader = _reader

        self.frame = _frame
        self.frame.clear()

        #the TimeStamp32 CANNOT be 0, so 0 can also be used instead of -1
        self.startTimeStamp32 = 0 #also allows to detect that a first valid data frame was read
        self.lastTimeStamp32 = 0  #is set by a Log packet
        self.TimeStamp32 = 0 #copy of frame.TimeStamp32 for convenience
        self.setLog_received = False #allows to detect that one valid Log was read

        self.logTime_error = False
        self.setLog_counter, self.setMotAll_counter, self.setCamera_counter = 0,0,0
        self.getImu1_counter, self.getImu2_counter, self.getImu3_counter = 0,0,0
        self.cmdLog32_counter, self.cmdLog33_counter, self.cmdLog34_counter, self.cmdLog35_counter = 0,0,0,0
        self.cmdLog37_counter, self.cmdLog38_counter, self.cmdLog39_counter = 0,0,0
        self.cmdLog40_counter, self.cmdLog41_counter, self.cmdLog42_counter = 0,0,0
        self.cmdLog43_counter, self.cmdLog44_counter = 0,0

        self.resAll_counter = 0 #this is used to detect a new log

        self.errorCounts = 0
        self.frameCounts = 0

        self.baseTimeStamp32 = _baseTime #allows to shift the time axis

    def clearForNextDataFrame(self):
        self.frame.clear()
        self.logTime_error = False
        self.setLog_counter, self.setMotAll_counter, self.setCamera_counter = 0,0,0
        self.getImu1_counter, self.getImu2_counter, self.getImu3_counter = 0,0,0
        self.cmdLog32_counter, self.cmdLog33_counter, self.cmdLog34_counter, self.cmdLog35_counter = 0,0,0,0
        self.cmdLog37_counter, self.cmdLog38_counter, self.cmdLog39_counter = 0,0,0
        self.cmdLog40_counter, self.cmdLog41_counter, self.cmdLog42_counter = 0,0,0
        self.cmdLog43_counter, self.cmdLog44_counter = 0,0
        #self.resAll_counter = 0 is cleared by a SetLog

    #------------------------------------------
    #get data from reader, and parse into a cNTLogDataFrameObhject()
    def parse(self,cmdid,cmdbyte=None,payload=None): #cmdid = 0x80 + cmd + idbyte
        if cmdid==cRESALL: #0x50 # 'RES ';
            self.clearForNextDataFrame();
            self.setLog_received = False
            self.resAll_counter += 1 #this is reset by a SetLog

        elif cmdid==cTRGALL: #'TRG ';'ALL  ';
            pass

        elif cmdid==cSETMOTA: #3 #'SET ';'MOTA ';
            self.frame.doSetMotorAll(payload)
            self.setMotAll_counter += 1

        elif cmdid==cSETCAMERA: #3 #'SET ';'CAM  ';
            self.frame.doSetCamera(payload)
            self.setCamera_counter += 1

        elif cmdid==cSETLOG: #11 #'SET ';'LOG  ';
            self.lastTimeStamp32 = self.TimeStamp32

            self.frame.doSetLogger(payload)

            self.TimeStamp32 = self.frame.TimeStamp32 #keep a copy for convenience

            if self.startTimeStamp32<=0:
                self.startTimeStamp32 = self.TimeStamp32

            #check for a new log in the log file
            if self.resAll_counter == 2 and self.TimeStamp32<self.lastTimeStamp32 and self.TimeStamp32<100000: ##5000:
                self.baseTimeStamp32 += self.lastTimeStamp32 + 1000000 #gap of 1sec
            #if a new log is detected, don't throw an error
            elif self.lastTimeStamp32>0 and abs(self.TimeStamp32-self.lastTimeStamp32) > 1700:
                self.logTime_error = True

            self.setLog_counter += 1
            self.resAll_counter = 0
            self.setLog_received = True

        elif cmdid==cGETIMU1: #0x30 #'GET ';
            self.getImu1_counter += 1

        elif cmdid==cGETIMU2:
            self.getImu2_counter += 1

        elif cmdid==cGETIMU3:
            self.getImu3_counter += 1

        elif cmdid==cCMDLOG:
            if cmdbyte==None:
                cmdbyte = self.frame.readCmdByte()
            if cmdbyte==255:
                pass
            elif cmdbyte==cCMDBYTE_PidData: #CMD LOG  PidData 35
                self.frame.doCmdPid(payload)
                self.cmdLog35_counter += 1
            elif cmdbyte==cCMDBYTE_Ahrs1Data:#CMD LOG  Ahrs1Data 37
                self.frame.doCmdAhrs1(payload)
                self.cmdLog37_counter += 1
            elif cmdbyte==cCMDBYTE_Ahrs2Data: #no. 38
                self.frame.doCmdAhrs2(payload)
                self.cmdLog38_counter += 1
            elif cmdbyte==cCMDBYTE_ParameterData: #CMD LOG  ParameterData 36
                self.frame.doCmdParameter(payload)
            #new V2 commands
            elif cmdbyte==cCMDBYTE_AccGyro1RawData_V2: #CMD LOG  AccGyro1RawData_V2 40
                self.frame.doCmdAccGyro1Raw_V2(payload)
                self.cmdLog40_counter += 1
            elif cmdbyte==cCMDBYTE_AccGyro2RawData_V2: #CMD LOG  AccGyro2RawData_V2 41
                self.frame.doCmdAccGyro2Raw_V2(payload)
                self.cmdLog41_counter += 1
            elif cmdbyte==cCMDBYTE_AccGyro3RawData_V2: #CMD LOG  AccGyro3RawData_V2 42
                self.frame.doCmdAccGyro3Raw_V2(payload)
                self.cmdLog42_counter += 1
            elif cmdbyte==cCMDBYTE_AccGyro1Data_V2: #CMD LOG  AccGyro1Data_V2 43
                self.frame.doCmdAccGyro1_V2(payload)
                self.cmdLog43_counter += 1
            elif cmdbyte==cCMDBYTE_AccGyro2Data_V2: #CMD LOG  AccGyro2Data_V2 44
                self.frame.doCmdAccGyro2_V2(payload)
                self.cmdLog44_counter += 1
            #deprectaed V1 commands
            elif cmdbyte==cCMDBYTE_AccGyro1RawData_V1: #no. 32
                self.frame.doCmdAccGyro1Raw_V1(payload)
                self.cmdLog32_counter += 1
            elif cmdbyte==cCMDBYTE_AccGyro2RawData_V1: #no. 33
                self.frame.doCmdAccGyro2Raw_V1(payload)
                self.cmdLog33_counter += 1
            elif cmdbyte==cCMDBYTE_AccGyro3RawData_V1: #no. 39
                self.frame.doCmdAccGyro3Raw_V1(payload)
                self.cmdLog39_counter += 1
            elif cmdbyte==cCMDBYTE_AccGyroData_V1: #no. 34
                self.frame.doCmdAccGyro_V1(payload)
                self.cmdLog34_counter += 1

    #------------------------------------------
    #analyzes the received frame, and appends it if correct
    # stxerror allows the caller to have additional errors considered
    # returns error
    def analyzeAndAppend(self,cmdid,stxerror): #cmdid = 0x80 + cmd + idbyte
        frameError = False
        if cmdid==cTRGALL:

##            if self.TimeStamp32>0: #a SetLog had been received before, so this is the 2nd TrgAll
            if self.setLog_received: #a SetLog had been received before, so this is the 2nd TrgAll
                if stxerror: frameError = True
                elif self.frame.error&cNTDATAFRAME_SETLOGERROR > 0: frameError = True
                elif self.frame.error&cNTDATAFRAME_SETMOTERROR > 0: frameError = True
                elif self.logTime_error: frameError = True
                elif self.setLog_counter != 1: frameError = True
                elif self.getImu1_counter != 1: frameError = True
                elif self.getImu2_counter > 1: frameError = True #was !=1
                elif self.getImu3_counter > 1: frameError = True
                elif self.setMotAll_counter != 1: frameError = True
                elif self.setCamera_counter > 1: frameError = True

                elif self.cmdLog32_counter > 1: frameError = True
                elif self.cmdLog33_counter > 1: frameError = True
                elif self.cmdLog34_counter > 1: frameError = True
                elif self.cmdLog35_counter > 1: frameError = True
                elif self.cmdLog37_counter > 1: frameError = True
                elif self.cmdLog38_counter > 1: frameError = True
                elif self.cmdLog39_counter > 1: frameError = True
                elif self.cmdLog40_counter > 1: frameError = True
                elif self.cmdLog41_counter > 1: frameError = True
                elif self.cmdLog42_counter > 1: frameError = True
                elif self.cmdLog43_counter > 1: frameError = True
                elif self.cmdLog44_counter > 1: frameError = True

                if not frameError:
                    self.frame.calculateTime( self.startTimeStamp32-self.baseTimeStamp32 )
                    self.frame.calculateInjectedValues()
                    # this allows appendDataFrame() to do some additional error checks
                    if self.reader.appendDataFrame(self.frame):
                        frameError = True
                    else:
                        self.frameCounts += 1

            self.clearForNextDataFrame()

        if frameError:
            self.errorCounts += 1
        return frameError


###############################################################################
# cNTLogFileReader
# this is the main class to read in a NTLogger data log file
# it generates a number of data lists, for easier handling in the GUI
#-----------------------------------------------------------------------------#
class cNTLogFileReader:

    def __init__(self):
        self._logVersion = cLOGTYPE_UNINITIALIZED #private

    def readLogFile(self,loadLogThread,fileName,createTraffic):
        try:
            F = open(fileName, 'rb')
        except:
            return '','',''

        #this is the header which preludes each data packet, 1+1+4+1+1+1 = 9 bytes, stx = 'R'
        headerStruct = struct.Struct('=BBIBBB')
        stx,size,timestamp,cmd,idbyte,cmdbyte = 0,0,0,0,0,0

        frame = cNTLogFileDataFrame()
        parser = cNTLogParser(frame, self)

        logItemList = cLogItemList()

        trafficlog = []

        #need to be self so that appendDataFrame() can be called by the parser
        self.datalog = []
        self.datalog.append( logItemList.getNamesAsStr('\t') + '\n' )
        self.datalog.append( logItemList.getUnitsAsStr('\t') + '\n' )

        self.rawdatalog = []

        trgall_timestamp_last = -1
        trafficlog_counter = 0
        stxerror = False

        byte_counter = 0
        byte_max = QFile(fileName).size()
        byte_percentage = 0
        byte_step = 5

        ##FBytesIO = BytesIO(F.read())  //THIS IS NOT FASTER AT ALL!!
        ##header = FBytesIO.read(9)
        ##payload = FBytesIO.read(size-9)
        frame.setLogVersion(cLOGVERSION_V2) #assume <v0.03 as default
        while 1:
            if( loadLogThread.canceled ): break

            header = F.read(9)
            if header == '' or len(header) != 9:
                break
            byte_counter += 9
            stxerror = False

            #------------------------------------------
            #check log start line
            # there should be a check that this is the first line!!! #XX
            if header[0:1] == b'H' and header[2:] == b'STORM32':
                size = int(header[1])
                restofheader = F.read(size-9) # read the rest of the log start line
                frame.setLogVersion(cLOGVERSION_V3) #v0.03
                header = F.read(9)

            #------------------------------------------
            #Header, read header data into proper fields
            stx, size, timestamp, cmd, idbyte, cmdbyte = headerStruct.unpack(header)
            if size<9:
                break;
            if stx != ord('R'):
                cmd, idbyte, cmdbyte = -1, -1, -1
                stxerror = True #NTbus traffic data frame analyzer
            cmdid = 0x80 + cmd + idbyte

            #------------------------------------------
            #Data, read remaining data into proper fields
            payload = F.read(size-9)
            if payload == '' or len(payload) != size-9:
                break
            byte_counter += size-9

            #------------------------------------------
            #read data send with R cmd
            # merged with traffic data frame analyzer
            parser.parse(cmdid, cmdbyte, payload)

            #------------------------------------------
            #NTbus traffic log
            if( createTraffic or trafficlog_counter<500 ):
                tl = str(trafficlog_counter)
                ts = str(timestamp)
                while len(ts)<10: ts = '0'+ts
                trafficlog.append( tl+'\t'+ts+'  ' )

                if cmd==cCMD_RES:   trafficlog.append( 'RES ' )
                elif cmd==cCMD_SET: trafficlog.append( 'SET ' )
                elif cmd==cCMD_GET: trafficlog.append( 'GET ' )
                elif cmd==cCMD_TRG: trafficlog.append( 'TRG ' )
                elif cmd==cCMD_CMD: trafficlog.append( 'CMD ' )
                else: trafficlog.append( '??? ' )

                if idbyte==cID_ALL:
                    trafficlog.append( 'ALL  ' )
                    if cmd==cCMD_TRG:
                        if trgall_timestamp_last >= 0:
                            trafficlog.append( '('+str(timestamp-trgall_timestamp_last)+')' )
                        trgall_timestamp_last = timestamp
                elif idbyte==cID_IMU1: trafficlog.append( 'IMU1 ' )
                elif idbyte==cID_IMU2: trafficlog.append( 'IMU2 ' )
                elif idbyte==cID_MOTA: trafficlog.append( 'MOTA ' )
                elif idbyte==cID_CAMERA: trafficlog.append( 'CAM  ' )
                elif idbyte==cID_LOG:  trafficlog.append( 'LOG  ' )
                elif idbyte==cID_IMU3: trafficlog.append( 'IMU3 ' )
                else: trafficlog.append( '???  ' )

                if stx != ord('R'):
                    trafficlog.append( '\n*******************   ERROR: invalid stx   ****************************************************' )
                elif cmd==cCMD_RES:
                    pass
                elif cmd==cCMD_SET:
                    if idbyte==cID_MOTA:
                        trafficlog.append( '0x'+'{:02X}'.format(frame.Flags) )
                        trafficlog.append( ' '+str(frame.VmaxPitch)+' '+str(frame.AnglePitch) )
                        trafficlog.append( ' '+str(frame.VmaxRoll)+' '+str(frame.AngleRoll) )
                        trafficlog.append( ' '+str(frame.VmaxYaw)+' '+str(frame.AngleYaw) )
                    elif idbyte==cID_CAMERA:
                        trafficlog.append( ' '+str(frame.CameraCmd)+' '+str(frame.CameraPwm) )
                    elif idbyte==cID_LOG:
                        trafficlog.append( str(parser.TimeStamp32) )
                        if parser.TimeStamp32 > 0:
                            trafficlog.append( ' ('+str(parser.TimeStamp32-parser.lastTimeStamp32)+')' )
                            trafficlog.append( ' '+str((parser.TimeStamp32-parser.startTimeStamp32)/1000)+' ms' )
                elif cmd==cCMD_GET:
                    pass
                elif cmd==cCMD_TRG:
                    pass
                elif cmd==cCMD_CMD:
                    trafficlog.append( str(cmdbyte) )
                    if cmdbyte==cCMDBYTE_ParameterData:
                        if frame.ParameterAdr==65535:
                            trafficlog.append( '\t'+str(frame.ParameterNameStr, "utf-8") )
                        else:
                            trafficlog.append( '\t'+str(frame.ParameterAdr) )
                            trafficlog.append( '\t'+str(frame.ParameterNameStr.replace(b'\0',b' '), "utf-8") )
                            trafficlog.append( '\t'+str(frame.ParameterValue) )

                trafficlog.append( '\n' )
                trafficlog_counter += 1

            #------------------------------------------
            #NTbus traffic data frame analyzer
            frameError = parser.analyzeAndAppend(cmdid, stxerror)

            if frameError:
                if( createTraffic or trafficlog_counter<500 ):
                    trafficlog.append( '*******************   ERROR: lost frame(s)   ****************************************************\n' )

            if 95*(byte_counter/byte_max) > byte_percentage:
                loadLogThread.emitProgress(byte_percentage)
                byte_percentage += byte_step

        #end of while 1:
        F.close();
        loadLogThread.emitProgress(95)
        if not (createTraffic or trafficlog_counter<500 ): trafficlog.append( '...\n' )
        trafficlog.append( 'FRAME COUNTS: '+str(parser.frameCounts) + '\n' )
        trafficlog.append( 'ERROR COUNTS: '+str(parser.errorCounts) )
        if( loadLogThread.canceled ):
            trafficlog = []
            self.datalog = []
            self.rawdatalog = []
        self._logVersion = frame.getLogVersion()
        return trafficlog, self.datalog, self.rawdatalog

    #this is called by the parser
    # returns a bool, True if error occured
    def appendDataFrame(self,_frame):
        self.datalog.append( _frame.getDataLine() )
        self.rawdatalog.append( _frame.getRawDataLine() )
        return False

    def getLogVersion(self):
        return self._logVersion


###############################################################################
# cNTSerialReaderThread
# this is the main class to read NT bus data via a serial port
# it generates a data line for each completely received frame
# is a worker thread to avoid GUI blocking
#-----------------------------------------------------------------------------#


class cSerialUARTStream():
    def __init__(self,_portname):
        #super().__init__()
        
        self.port = QSerialPort()

        self.port.setBaudRate(2000000)
        self.port.setDataBits(8)
        self.port.setParity(QSerialPort.NoParity)
        self.port.setStopBits(1)
        self.port.setFlowControl(QSerialPort.NoFlowControl)
        self.port.setReadBufferSize( 256*1024 )
        self.port.setPortName(_portname)
        self.port.open(QIODevice.ReadWrite) #this unfortunatley b?locks the GUI!!!
        
    def close(self):
        self.port.close()

    def isValid(self):
        if self.port.error(): return False
        
        return True

    def bytesAvailable(self):
        return self.port.bytesAvailable()

    def readOneByte(self):
        return self.port.read(1)
    
class cSerialUDPStream():
    def __init__(self,_port):
        #super().__init__()

        self.fifo = cRingBuffer(128*1024)
        
        self.udp = QUdpSocket()
        self.udp.bind(QHostAddress("0.0.0.0"), 7777)
        self.udp.readyRead.connect(self._onUdpReadyRead)
        
        self.tcp = QTcpSocket()
        self.tcp.connected.connect(self._onTcpConnected)
        print("cSerialUDPStream")
        
    def _onTcpConnected(self):
        print("Connected")
        
        
    def _onUdpReadyRead(self):
        while self.udp.hasPendingDatagrams():
            data, host, port = self.udp.readDatagram(8192)
            #print(len(data))
            #print(self.fifo.free())
            if self.fifo.free() < 1400:
                print("fifo overflow")
            self.fifo.putbuf(data)       

    def openPort(self,portname):
        print("open port")
        self.tcp.connectToHost("172.16.0.1", 5050)

    def close(self):
        print("disconnect")
        self.tcp.disconnectFromHost()

    def isValid(self):
        return True

    def bytesAvailable(self):
        return self.fifo.available()

    def readOneByte(self):
        c = chr(self.fifo.getc())
        #print("c", c)
        return bytes([ord(c)])

class cSerialStream():

    def __init__(self,_port):
        #super().__init__()

        self.port = None

    def openPort(self, portname):
        print("open " + portname)
        if "ENSYS" in portname:
            self.port = cSerialUDPStream(portname)
        else:
            self.port = cSerialUARTStream(portname)
            
        self.port.openPort(portname)

    def close(self):
        self.port.close()
        

    def isValid(self):
        if not self.port: return False
        
        return self.port.isValid()        

    def bytesAvailable(self):
        return self.port.bytesAvailable()

    def readOneByte(self):
        return self.port.readOneByte()


class cNTSerialReaderThread(QThread):

    newSerialDataAvailable = pyqtSignal()

    def __init__(self,_serial):
        super().__init__()
        self.canceled = False

        self.serial = _serial

        self.dataline_local = None
        self.dataline = None
        self.mutex = QMutex() #to protect self.dataline
        self.baseTime = 0
        self.lastChar = b''

    def __del__(self):
        self.wait()

    def clear(self):
        self.dataline_local = None
        self.dataline = None
        self.baseTime = 0

    def run(self):
        self.canceled = False
        self.runCallback()

    def cancel(self):
        self.canceled = True
        self.cancelCallback()

    def cancelIfRunning(self):
        if self.isRunning(): self.cancel()

    def cancelCallback(self):
        pass

    #helper function, called before thread is started
    def openSerial(self,currentport):
        self.serial.openPort( currentport )

    #helper function, called after thread is stopped
    def closeSerial(self):
        self.serial.close()

    def runCallback(self):
        #self.port.open(QIODevice.ReadWrite) #this must be done in Main!!
        if not self.serial.isValid(): return
        logItemList = cLogItemList()
        self.dataline_local = ''
        if self.baseTime==0:
            self.dataline_local = logItemList.getNamesAsStr('\t') + '\n'
            self.dataline_local += logItemList.getUnitsAsStr('\t') + '\n'
        self.dataline = ''
        self.time = self.baseTime
        frame = cNTSerialDataFrame(self)
        parser = cNTLogParser(frame, self, self.baseTime)
        self.lastChar = b''
        while 1:
            if self.canceled: break

            while self.serial.bytesAvailable()>512: #digest all data accumulated since the last call
                b = self.readByte()
                c = int(b[0])
                #print(c)
                if c<128: continue #this can't be a cmdid
                parser.parse(c)
                parser.analyzeAndAppend(c, 0) #stxerror = 0
                self.time = frame.Time

            if len(self.dataline_local)>0:
                self.mutex.lock()
                self.dataline += self.dataline_local #this is so that nothing can be missed
                self.mutex.unlock()
                self.dataline_local = ''
                self.emitNewSerialDataAvailable() #it has then 100ms time to process, hopefully enough
                self.baseTime = self.time

            self.msleep(100)

        self.baseTime += 1000000 #add 1sec to make a gap

    def readByte(self):
        if self.lastChar != b'':
            b = self.lastChar
            self.lastChar = b''
        else:
            b = self.serial.readOneByte()
        return b

    #this is called by the NTDataFrame class, so that can backtrack char in case of a STX byte
    # res is forced to have the desired length, but is then padded with nonsense
    def readPayload(self,length):
        res = b''
        err = False
        for i in range(length):
            if self.lastChar != b'': #skip, but fill
                res += b'\x7e'
                err = True
            else:
                b = self.serial.readOneByte()
                if int(b[0]) >= 128: #this is a cmdid
                    self.lastChar = b
                    b = b'\x7f'
                    err = True
                res += b
        return (res,err)

    #this is called by the parser
    # returns a bool, True if error occured
    def appendDataFrame(self,_frame):
        #here one can do some more error checks
        # the crc does a good job in rejecting erroneous packages
        dataError = False
        if _frame.State>100: dataError = True
        elif abs(_frame.Imu1AnglePitch)>200000: dataError = True #these are raw values
        elif abs(_frame.Imu1AngleRoll)>100000: dataError = True
        elif abs(_frame.Imu1AngleYaw)>200000: dataError = True
        elif abs(_frame.Imu2AnglePitch)>200000: dataError = True
        elif abs(_frame.Imu2AngleRoll)>100000: dataError = True
        elif abs(_frame.Imu2AngleYaw)>200000: dataError = True
        if not dataError:
            self.dataline_local += _frame.getDataLine()
        return dataError

    def emitNewSerialDataAvailable(self):
        self.newSerialDataAvailable.emit()

    #this is called by main, serialReaderThreadNewDataAvailable()
    def getDataLine(self):
        self.mutex.lock()
        dataline = self.dataline
        self.dataline = ''
        self.mutex.unlock()
        return dataline

    def getLogVersion(self):
        return cLOGVERSION_LATEST


###################################################################
# MAIN
###################################################################


###############################################################################
# cLogDataContainer
# class to hold and maintain some data
#  traffic and data are actually stored in QT objects
#-----------------------------------------------------------------------------#
cLOGTYPE_UNINITIALIZED = 0
cLOGTYPE_NTLOGGER = 1      #log file created by NTLogger, or by serialReader
cLOGTYPE_STORM32GUI = 2    #log file created by STorM32's GUI o323BGCTool
cLOGTYPE_ASCII = 3    #log file created by STorM32's GUI o323BGCTool
##XX ??? cLOGTYPE_GENERICASCII = 32 #.dat,.txt,.csv
cLOGTYPE_NTIMUDIRECT = 4    #log file created by direct logging of NT Imu

cLOGVERSION_UNINITIALIZED = 0
cLOGVERSION_V2 = 2 #new V2 commands
cLOGVERSION_V3 = 3 #SetLog extended to 0.001?
cLOGVERSION_LATEST = 3 #this is an alias to the latest version

cLOGSOURCE_UNINITIALIZED = 0
cLOGSOURCE_LOAD = 1        #data has be read from a log file, triggered by Load
cLOGSOURCE_RECORD = 2      #data has be obtained from recording, triggered by RecStart

class cLogDataContainer:

    def __init__(self, _wTrafficText, _wDataText):
        self.wTrafficText = _wTrafficText
        self.wDataText = _wDataText

        self.fileName = ''
        self.wTrafficText.setPlainText('')
        self.wDataText.setPlainText('')
        self.wDataText.horizontalScrollBar().setValue(0)
        self.rawData = []
        self.logItemList = cLogItemList() #default itemlist  #None
        self.logType = cLOGTYPE_UNINITIALIZED
        self.logVersion = cLOGVERSION_UNINITIALIZED
        self.logSource = cLOGSOURCE_UNINITIALIZED
        self.recordOn = False
        self.initializeNpArrayAndPlotView()

    def clear(self):
        self.fileName = ''
        self.wTrafficText.setPlainText('')
        self.wDataText.setPlainText('')
        self.wDataText.horizontalScrollBar().setValue(0)
        self.rawData = []
        self.logItemList = cLogItemList() #default itemlist  #None
        self.logType = cLOGTYPE_UNINITIALIZED
        self.logVersion = cLOGVERSION_UNINITIALIZED
        self.logSource = cLOGSOURCE_UNINITIALIZED
        self.recordOn = False
        self.initializeNpArrayAndPlotView()

    def initializeNpArrayAndPlotView(self,length=1):
        if length<0: length = 1
        self._npArrayWidth = len(self.logItemList.list)
        self._npArray = np.zeros((length,self._npArrayWidth))
        self._npArrayPtr = 0
        self._npArrayStep = 1
        self._npPlotView = self._npArray[self._npArrayPtr,:]

    def appendDataLine(self,dataline):
        hsb = self.wDataText.horizontalScrollBar()
        v = hsb.value()
        self.wDataText.appendPlainText( dataline[:-1] )
        hsb.setValue(v)
        for line in dataline.split('\n'):
            a = np.fromstring( line, sep = '\t' )
            if a.size != self._npArrayWidth: continue #something is wrong with that line
            a[0] *= 0.001 #convert time from us to ms
            self._npArray[self._npArrayPtr,:] = a
            self._npArrayPtr += 1
            if self._npArray.shape[0] < 1000:
                self.initializeNpArrayAndPlotView(667*60*5)  #*30 #30 min
            if self._npArrayPtr >= self._npArray.shape[0]:
                tmp = self._npArray
                self._npArray = np.empty( (2*self._npArray.shape[0], self._npArray.shape[1]) )
                self._npArray[:tmp.shape[0],:] = tmp

    def hasData(self):
        #in some functions I had before
        # if self.dataContainer.logSource == cLOGSOURCE_UNINITIALIZED: return
        # if self.dataContainer.logType == cLOGTYPE_UNINITIALIZED: return
        #is this always consistent with npArray=0 ??? seems so, so far
        return self._npArrayPtr

    def setPlotType(self,plotType=''):
        self._npArrayStep = 1
        if plotType == '8khz acc fft':
            self._npArrayStep = 2

    def getNpPlotView(self,plotCount=2): #plotCount is the number of displayed curves
        if self._npArrayPtr:
            n = 0
            if self.recordOn:
                if plotCount<2: plotCount = 2
                n = self._npArrayPtr - self.maxPlotRangeWhileRecording(plotCount)
                if n<0: n = 0
            return self._npArray[n:self._npArrayPtr:self._npArrayStep,:] #this is a view on the buffer!!!
        return None #self._npPlotView #self._npArray[self._npArrayPtr,:]

    def setRecordOn(self,flag):
        self.recordOn = flag

    def dT(self):
        return 0.0015 * self._npArrayStep  #XX 0.0015

    def maxPlotRangeWhileRecording(self,plotCount):
        return 20000/(2*plotCount) #40000 #this is 15sec with 8kHz

    def getMaxTime(self):
        if self._npArrayPtr:
            return self._npArray[self._npArrayPtr-1,0]
        return 0.0

    def getSTorM32FirmwareVersion(self):
        t = self.wTrafficText.toPlainText()[0:2000] #the plain text can contain '\0'!!
        m = re.search( r'STORM32[\0\s]*\d+\s+\d+\s+CMD LOG\s+36\s+([ \w\.]+)', t )
        if m==None:
            return 'vx.xx'
        else:
            return m.group(1)


###############################################################################
# cWorkerThread
# worker thread to avoid GUI blocking when loading/saving files
#-----------------------------------------------------------------------------#
class cWorkerThread(QThread):

    progress = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.progressValue = 0
        self.canceled = False

    def __del__(self):
        self.wait()

    def run(self):
        self.progressValue = 0
        self.canceled = False
        self.runCallback()

    def cancel(self):
        self.canceled = True
        self.cancelCallback()

    def runCallback(self):
        pass

    def cancelCallback(self):
        pass

    def emitProgress(self,progress_value):
        self.progressValue = progress_value
        self.progress.emit()

    def startProgress(self,_step,_length):
        self.progressValue = 0
        self.progressValue_step = _step
        self.index = 0
        self.percentage_step = _length*(_step/100)
        self.percentage = self.percentage_step
        self.emitProgress(0)

    def updateProgress(self):
        self.index += 1
        if self.index > self.percentage:
            self.percentage += self.percentage_step
            self.progressValue += self.progressValue_step
            self.emitProgress(self.progressValue)


class cLoadLogThread(cWorkerThread):

    def __init__(self):
        super().__init__()
        self.createTraffic = False

        #the data is first read into these fields, and only at the end transferred to the main dataContainer
        self.filenName = ''
        self.traffic = ''
        self.data = ''
        self.rawData = []
        self.npArray = np.zeros((0,0)) #None
        self.logItemList = None
        self.logType = cLOGTYPE_UNINITIALIZED
        self.logVersion = cLOGVERSION_UNINITIALIZED

    def setFile(self,_fileName,_createTraffic=False):
        self.fileName = _fileName
        self.createTraffic = _createTraffic
        self.traffic = ''
        self.data = ''
        self.rawData = []
        self.npArray = np.zeros((0,0)) #None
        self.logItemList = None
        self.logType = cLOGTYPE_UNINITIALIZED
        self.logVersion = cLOGVERSION_UNINITIALIZED

    def runCallback(self):
        if self.fileName.lower().endswith('.log'):
            self.loadNTLoggerFile()
        #elif self.fileName.lower().endswith('.dat'):
        #    self.loadSTORM32GUIFile()
        #elif self.fileName.lower().endswith('.csv'):
        #    self.loadSTORM32GUIFile()
        else:
            self.loadSTORM32GUIFile()

    def loadNTLoggerFile(self):
        logReader = cNTLogFileReader()
        traffic, data, self.rawData = logReader.readLogFile(self, self.fileName, self.createTraffic)
        if( self.createTraffic ):
            self.traffic = ''.join(traffic)
        else:
            self.traffic = 'Only first 500 commands were loaded.\n\n' + ''.join(traffic)
        self.data = ''.join(data)
        self.logItemList = cLogItemList()
        self.logType = cLOGTYPE_NTLOGGER
        self.logVersion = logReader.getLogVersion()
        self.createNpArray(2, 0)

    def loadSTORM32GUIFile(self): #this actually reads all sorts of ascii text files
        try: F = open(self.fileName, 'r')
        except IOError: return #pass
        data = []
        sep = None
        oldTimeIndex = -1
        logItemList = cLogItemList(cStorm32GuiLogItemTranslator())
        first = True
        reLine = re.compile(r'^[0-9.+-E\s,]+$')
        isSTorM32DataDisplay = False
        STorM32DataDisplayHeader = r'^i\tTime\tMillis\tGx\tGy\tGz\tRx\tRy\tRz\tAccAmp\tAccConf\tPitch\tRoll\tYaw\tPCntrl\tRCntrl\tYCntrl\tPitch2\tRoll2\tYaw2'
        for line in F:
            line = line.strip()
            if first:
                if re.search(r',', line): sep = ','
                if re.search(r'[a-zA-Z]', line): #this is a header line
                    line = '\t'.join(line.split(sep)) #this is MUCH faster than a regex!  re.sub(r'[\s,]+', '\t', line)
                    if re.search(STorM32DataDisplayHeader, line): isSTorM32DataDisplay = True
                    logItemList.setFromStr(line, '', cDATATYPE_FLOAT, cDATATYPE_FLOAT, '\t')
                    oldTimeIndex = logItemList.swapTimeToZeroIndex()
                    data.append( logItemList.getNamesAsStr('\t') + '\n' )
            if reLine.search(line):
                d = line.split(sep)
                if isSTorM32DataDisplay:
                    d[6]  = '{:.4f}'.format( 0.0001 * float(d[6]) )#Rx
                    d[7]  = '{:.4f}'.format( 0.0001 * float(d[7]) )#Ry
                    d[8]  = '{:.4f}'.format( 0.0001 * float(d[8]) )#Rz
                    d[9]  = '{:.4f}'.format( 0.0001 * float(d[9]) )#AccAmp
                    d[10] = '{:.4f}'.format( 0.0001 * float(d[10]) ) #AccConf
                    d[11] = '{:.2f}'.format( 0.01 * float(d[11]) ) #Pitch
                    d[12] = '{:.2f}'.format( 0.01 * float(d[12]) ) #Roll
                    d[13] = '{:.2f}'.format( 0.01 * float(d[13]) ) #Yaw
                    d[14] = '{:.2f}'.format( 0.01 * float(d[14]) ) #PCntrl
                    d[15] = '{:.2f}'.format( 0.01 * float(d[15]) ) #RCntrl
                    d[16] = '{:.2f}'.format( 0.01 * float(d[16]) ) #YCntrl
                    d[17] = '{:.2f}'.format( 0.01 * float(d[17]) ) #Pitch2
                    d[18] = '{:.2f}'.format( 0.01 * float(d[18]) ) #Roll2
                    d[19] = '{:.2f}'.format( 0.01 * float(d[19]) ) #Yaw2
                data.append( '\t'.join(d) + '\n'  ) #this is MUCH faster than a regex!!!!
#XX do a check that the line is complete!!!
            first = False #only check first line
        F.close()
        self.traffic = 'traffic not available in this log file'
        self.data = ''.join(data)
        self.rawdata = []
        self.logItemList = logItemList
        if isSTorM32DataDisplay:
            self.logType = cLOGTYPE_STORM32GUI
        else:
            self.logType = cLOGTYPE_ASCII
        self.logVersion = cLOGVERSION_UNINITIALIZED #is irrelevant here since its not a NT log
        self.createNpArray(1, oldTimeIndex)

    def createNpArray(self, linesToSkip=1, oldTimeIndex=0):
        try:
            self.npArray = np.loadtxt( StringIO(self.data), delimiter='\t', skiprows=linesToSkip )
            i = oldTimeIndex
            if i>0:
                #self.nparraylog[:,[i, 0]] = self.nparraylog[:,[0,i]]
                self.npArray[:,i], self.npArray[:,0] = self.npArray[:,0], self.npArray[:,i].copy()
            self.npArray[:,0] *= 0.001 #convert time from us to ms
        except:
            self.npArray = np.zeros((0,0)) #None
            self.logType = cLOGTYPE_UNINITIALIZED

    #this can be called by a caller to transfer data to itself
    def copyToDataContainer(self, dataContainer):
        dataContainer.fileName = self.fileName
        self.emitProgress(10)
        dataContainer.wTrafficText.setPlainText( self.traffic )
        self.emitProgress(50)
        dataContainer.wDataText.setPlainText( self.data )
        self.emitProgress(90)
        dataContainer.rawData = self.rawData
        dataContainer._npArray = self.npArray
        dataContainer._npArrayPtr = self.npArray.shape[0]
        #dataContainer.npPlotView = self.npArray #by default plot view is identical to npArray
        dataContainer.logItemList = self.logItemList
        dataContainer.logType = self.logType
        dataContainer.logVersion = self.logVersion
        dataContainer.logSource = cLOGSOURCE_LOAD


class cSaveLogThread(cWorkerThread):

    def __init__(self, _dataContainer):
        super().__init__()
        self.dataContainer = _dataContainer
        self.fileName = ''

    def setFile(self,_fileName):
        self.fileName = _fileName

    def runCallback(self):
        self.emitProgress(0)
        if self.fileName.lower().endswith('.csv'):
            # with open( fileName, 'w') as F: doesn't catch error when a file is used by some other program!!
            try: F = open( self.fileName, 'w')
            except IOError: pass
            else:
                F.write( self.dataContainer.wDataText.toPlainText().replace('\t',',') )
                F.close()
        elif self.fileName.lower().endswith('.cfl'):
            if len(self.dataContainer.rawData)<=0: return #no raw data available
            try: F = open( self.fileName, 'wb')
            except IOError: pass
            else:
                logItemList = cLogItemList()
                CFBlackbox = cCFBlackbox(logItemList)
                fv = self.dataContainer.getSTorM32FirmwareVersion()
                lv = self.dataContainer.logVersion
                F.write( CFBlackbox.header(fv,lv) )
                lastState = -1
                index = 0
                self.startProgress(5, len(self.dataContainer.rawData))
                for data in self.dataContainer.rawData:
                    if( lastState!=6 and data[8]==6 ):
                        F.write( CFBlackbox.dataEBeep( data[0]) )
                    if( lastState>0 and data[8]==0 ):
                        F.write( CFBlackbox.footer() )
                        F.write( CFBlackbox.header() )
                    lastState = data[8]
                    F.write( CFBlackbox.dataIFrame(index, data) )
                    index += 1
                    self.updateProgress()
                F.write( CFBlackbox.footer() )
                F.close()
        else:
            try: F = open( self.fileName, 'w')
            except IOError: pass
            else:
                F.write( self.dataContainer.wDataText.toPlainText() )
                F.close()
        self.emitProgress(100)



###############################################################################
# cMain
# that's the real beef
#-----------------------------------------------------------------------------#
class cMain(QMainWindow,wMainWindow):

    appPalette = 'Fusion'

    def __init__(self, _winScale, _appPalette):
        super().__init__()

        if( whichUiToUse=='py_ow' ):
            self.setupUi(self, _winScale)
        else:
            self.setupUi(self)
        appPalette = _appPalette #this is needed to allow writing into ini file
        self.setAcceptDrops(True)

        self.actionLoad.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.actionSave.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.actionClear.setIcon(self.style().standardIcon(QStyle.SP_DialogDiscardButton))

        self.bLoad.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.bSave.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.bCancelLoad.setIcon(self.style().standardIcon(QStyle.SP_DialogCancelButton))

        self.fileDialogDir = ''

        self.bPlaybackBegin.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipBackward))
        self.bPlaybackSkipBackward.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekBackward))
        self.bPlaybackPlayStop.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.bPlaybackSkipForward.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekForward))
        self.bPlaybackEnd.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipForward))

        self.wPlaybackSpeedFactor.addItems( ['8 x','4 x','2 x','1 x','1/2 x','1/4 x','1/8 x'] )
        self.wPlaybackSpeedFactor.setCurrentIndex( 3 )
        self.wGraphZoomFactor.addItems( ['100 %','10 %','1 %','30 s','10 s','5 s','2 s','1 s','250 ms','100 ms'] )
        self.wGraphZoomFactor.setCurrentIndex( 4 )

        self.bPlaybackBegin.hide()
        self.bPlaybackSkipBackward.hide()
        self.bPlaybackPlayStop.hide()
        self.bPlaybackSkipForward.hide()
        self.bPlaybackEnd.hide()
        self.wPlaybackSpeedFactor.hide()
        self.wPlaybackSpeedFactorLabel.hide()

        #this holds all data and related info
        self.dataContainer = cLogDataContainer(self.wTrafficText, self.wDataText)

        #threads for file load and save operations
        self.loadLogThread = cLoadLogThread()
        self.loadLogThread.finished.connect(self.loadLogFileDone)
        self.loadLogThread.progress.connect(self.loadLogFileProgress)

        self.saveLogThread = cSaveLogThread(self.dataContainer)
        self.saveLogThread.finished.connect(self.saveLogFileDone)
        self.saveLogThread.progress.connect(self.saveLogFileProgress)

        #holds the list of names of the items in the data log
        #holds the list of categories and items, as needed for the selctor tree
        self.logItemNameList = []
        self.graphSelectorList = []
        self.setGraphSelectorTreeFromLogItemList(self.dataContainer.logItemList)
        self.currentGraphIndexes = None #to avoid that indexes needs to be build at each updateGraph()
        self.setCurrentIndexes()

        #add two plot window frames, to host the various plots
        #self.pqGraphicsWindow = pg.GraphicsWindow()
        self.pqGraphicsWindow = pg.GraphicsLayoutWidget() #this is needed instead of selfpqPlotWidget = pg.PlotWidget() for the mouse/vb to work
        self.pqGraphicsWindow.ci.setContentsMargins(3,3,9,3)
        self.pqGraphicsWindow.ci.setSpacing(0)
        #self.pqGraphicsWindow.setBackground(None)
        self.wGraphAreaLayout.addWidget(self.pqGraphicsWindow)
        self.pqGraphicsWindowBottom = self.pqGraphicsWindow.addLayout(row=1, col=0)
        self.pqGraphicsWindowBottom.setContentsMargins(0,0,0,0)

        #add the main data plot window
        self.pqPlotWidget = self.pqGraphicsWindow.addPlot(row=0, col=0)
        self.pqPlotWidget.setLabel('bottom', 'Time', units='s')
        self.pqPlotWidget.showGrid(x=True, y=True, alpha=0.33)
        self.pqPlotWidget.setYRange( 0.0, 1.0 )
        self.pqPlotWidget.setXRange( 0.0, 1.0 )
        self.pgGraphTimeLine = pg.InfiniteLine(angle=90, movable=False)
        colstr = pg.colorStr( pg.mkColor(pg.getConfigOption('foreground')) )[:6]
        self.wGraphCursorFormatStr = "<span style='color: #"+colstr+"'>x = %0.4f, y = %0.4f</span>"
        self.wGraphTimeFormatStr = "<span style='color: #"+colstr+"'>%s</span>"

        #add FFT plot window
        self.pqFftWidget = self.pqGraphicsWindowBottom.addPlot(row=0,col=0)
        self.pqFftWidget.setLabel('bottom', 'Frequency', units='Hz')
        self.pqFftWidget.showGrid(x=True, y=True, alpha=0.33)
        self.pqFftWidget.setYRange( 0.0, 1.0 )
        self.pqFftWidget.setXRange( 0.0, 333.0 )
        self.wGraphFftLength.addItems( ['2048/3.1s','1024/1.5s','512/0.77s','256/0.38s'] )
        self.wGraphFftLength.setCurrentIndex( 1 )
        self.wGraphFftWindow.addItems( ['square','bartlett','blackman','hamming','hanning','kaiser2','kaiser3'] )
        self.wGraphFftWindow.setCurrentIndex( 3 )
        self.wGraphFftOutput.addItems( ['amplitude','psd (lin f)','psd (log f)'] )
        self.wGraphFftOutput.setCurrentIndex( 0 )
        self.wGraphFftPreFilter.addItems( ['none','average','1 Hz','2 Hz','4 Hz'] )
        self.wGraphFftPreFilter.setCurrentIndex( 1 )

        #self.wGraphComment.setText('')
        self.wGraphComment.hide()

        #add Bode plot window
        #removed

        #add com port widget, and associated serial
        self.networkManager = QNetworkConfigurationManager()
        self.wRecordComPort = cSerialPortComboBox(self.networkManager, self.centralwidget, _winScale)
        self.topLayout.addWidget(self.wRecordComPort)

        self.serialStream = cSerialStream(None)
        self.serialReaderThread = cNTSerialReaderThread(self.serialStream)
        self.serialReaderThread.finished.connect(self.serialReaderThreadDone)
        self.serialReaderThread.newSerialDataAvailable.connect(self.serialReaderThreadNewDataAvailable)
        '''
        configlist = self.networkManager.allConfigurations()
        ensysNTLoggerAvailable = False
        for config in configlist:
            if not re.search( r'WLAN', config.bearerTypeName()): continue
            if re.search( r'ENSYS NT Logger', config.name()): ensysNTLoggerAvailable = True
            print('-------------')
            print(config)
            print(config.name())
            print(config.bearerType(), config.bearerTypeFamily(), config.bearerTypeName())
            print(config.type())
            print(config.isValid())
            #print(config.state())
            if config.state() & QNetworkConfiguration.Undefined: print('state Undefined')
            if config.state() & QNetworkConfiguration.Defined: print('state Defined')
            if config.state() & QNetworkConfiguration.Discovered: print('state Discovered')
            if config.state() & QNetworkConfiguration.Active: print('state Active')

        ipAddressesList = QNetworkInterface.allAddresses()
        for ipAddress in ipAddressesList:
            print(ipAddress.toString())
        '''
        self.networkManager.updateConfigurations()

        self.pqGraphicsWindow.scene().sigMouseMoved.connect(self.updateGraphCursorEvent)
        self.pqPlotWidget.sigXRangeChanged.connect(self.updateGraphRangeChangedEvent)
        self.wGraphTimeSlider.valueChanged.connect(self.updateGraphTimeSliderValueChangedEvent)

        self.bScreenShot.clicked.connect(self.doScreenShot)
        self.bAutoRangeAll.clicked.connect(self.doAutoRangeAll)
        self.bXAutoRange.clicked.connect(self.doXAutoRange)
        self.bYAutoRangeFull.clicked.connect(self.doYAutoRangeFull)
        self.bYAutoRangeView.clicked.connect(self.doYAutoRangeView)

        self.bGraphSelectorClear.clicked.connect(self.clearGraphSelection)
        self.wGraphSelectorTree.itemChanged.connect(self.updateGraphOnItemChanged)
        self.bGraphShowFft.clicked.connect(self.showFftClicked)
        self.bGraphShowRecord.clicked.connect(self.showRecordClicked)
        self.bGraphShowPoints.clicked.connect(self.updateGraphOnItemChangedNoAutoRange)

        #self.wGraphFftLength.currentIndexChanged.connect(self.updateGraphOnFftParameterChanged)
        self.wGraphFftLength.activated.connect(self.updateGraphOnFftParameterChanged)
        self.wGraphFftWindow.activated.connect(self.updateGraphOnFftParameterChanged)
        self.wGraphFftOutput.activated.connect(self.updateGraphOnFftParameterChanged)
        self.wGraphFftPreFilter.activated.connect(self.updateGraphOnFftParameterChanged)

        self.bRecordStartStop.clicked.connect(self.doRecordStartStopClicked)
        self.bRecordClear.clicked.connect(self.doRecordClearClicked)

        self.readSettings()

        self.wProgressBar.hide()
        self.bCancelLoad.hide()
        self.pqFftWidget.hide()
        self.wGraphFftLength.hide()
        self.wGraphFftWindow.hide()
        self.wGraphFftOutput.hide()
        self.wGraphFftPreFilter.hide()
        self.bRecordStartStop.hide()
        self.bRecordClear.hide()
        self.wRecordComPort.hide()

        self.clearPlot()
        self.updateGraphTime()

#        self.mainTimer = QTimer(self)
#        self.mainTimer.timeout.connect(self.updateGraphOnTimerTick)
#        self.mainTimer.start(50)
#        self.graphIsRunning = False

#        self.bPlaybackPlayStop.setEnabled(True)
#        self.bPlaybackPlayStop.clicked.connect(self.doPlaybackPlayStopClicked)


    def setGraphSelectorTreeFromLogItemList(self,_logItemList):
        ##self.wGraphSelectorTree.itemChanged.disconnect(self.updateGraphOnItemChanged)
        # it's crucial to avoid that each changed sub level item is called
        self.wGraphSelectorTree.blockSignals(True)
        # clear stuff
        self.wGraphSelectorTree.clear()
        # populate stuff
        self.logItemNameList = _logItemList.getNamesAsList()
        self.graphSelectorList = _logItemList.getGraphSelectorList()
        for entry in self.graphSelectorList:
            item = QTreeWidgetItem(self.wGraphSelectorTree) #also does addTopLevelItem(item)
            item.setText(0, entry[0])
            item.setFlags(item.flags() | Qt.ItemIsTristate | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked) #this is required, since otherwise the item might happen to have no checkbox!
            if len(entry[1])>1:
              for index in entry[1]:
                child = QTreeWidgetItem(item)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setText(0, self.logItemNameList[index])
                child.setCheckState(0, Qt.Unchecked)
        i = _logItemList.getGraphSelectorDefaultIndex(self.graphSelectorList)
        if i:
            self.wGraphSelectorTree.topLevelItem(i).setCheckState(0, QtCore.Qt.Checked)
            self.wGraphSelectorTree.blockSignals(False)
            return
        if len(self.graphSelectorList):
            self.wGraphSelectorTree.topLevelItem(0).setCheckState(0, QtCore.Qt.Checked)
        self.wGraphSelectorTree.blockSignals(False)
        ##self.wGraphSelectorTree.itemChanged.connect(self.updateGraphOnItemChanged)

    #slot for signal clicked from bGraphSelectorClear
    def clearGraphSelection(self,):
        self.wGraphSelectorTree.blockSignals(True)
        for i in range(self.wGraphSelectorTree.topLevelItemCount()):
            self.wGraphSelectorTree.topLevelItem(i).setCheckState(0, QtCore.Qt.Unchecked)
        self.wGraphSelectorTree.blockSignals(False)
        self.setCurrentIndexes()
        self.updateGraph()


    #slot for signal ClearLog File, connection to signals in QTDesigner
    def clearLogFile(self):
        self.setLogSourceToUninitialized(True) #unche all, incl. rec

    #slot for signal progress of cLoadLogThread
    # is called by WorkerThread to update progress bar
    def loadLogFileProgress(self):
        self.wProgressBar.setValue(self.loadLogThread.progressValue)

    #slot for signal progress of cSaveLogThread
    # is called by WorkerThread to update progress bar
    def saveLogFileProgress(self):
        self.wProgressBar.setValue(self.saveLogThread.progressValue)

    def workerThreadPrepare(self, _message):
        self.bLoad.setEnabled(False)
        self.actionLoad.setEnabled(False)
        self.bSave.setEnabled(False)
        self.actionSave.setEnabled(False)
        self.actionClear.setEnabled(False)
        self.bRecordClear.setEnabled(False)
        self.bCancelLoad.show()
        self.wProgressBar.show()
        self.wLogFileName.setText(_message)

    def workerThreadFinish(self):
        self.bLoad.setEnabled(True)
        self.actionLoad.setEnabled(True)
        if self.dataContainer.logType != cLOGTYPE_UNINITIALIZED:
            self.bSave.setEnabled(True)
            self.actionSave.setEnabled(True)
            self.actionClear.setEnabled(True)
            self.bRecordClear.setEnabled(True)
        self.bCancelLoad.hide()
        self.wProgressBar.hide()
        self.wLogFileName.setText(self.dataContainer.fileName)

    def loadLogFileIsAllowed(self):
        if self.loadLogThread.isRunning(): return False
        if self.bLoad.isEnabled() and self.actionLoad.isEnabled(): return True
        return False

    def doLoadLogFile(self,fileName):
        if self.loadLogThread.isRunning(): return
        self.workerThreadPrepare( "Loading... "+fileName )
        createTraffic = False
        if( self.bLoadTraffic.checkState()==QtCore.Qt.Checked ): createTraffic = True
        self.loadLogThread.setFile(fileName, createTraffic)
        self.loadLogThread.start()

    #slot for signal cancel of cLoadLogThread
    # is called then Cancel button is hit
    def loadLogFileCancel(self):
        self.loadLogThread.cancel() #simply cancel all
        self.saveLogThread.cancel()
        self.workerThreadFinish()

    #slot for signal Load Log File, connection to signals in QTDesigner
    # is called then Load button or Load action is hit
    def loadLogFile(self):
        if self.loadLogThread.isRunning():
            return
        fileName, _ = QFileDialog.getOpenFileName(
            self,
            'Load Data Logger file',
            self.fileDialogDir,
            '*.log *.dat *.txt *.csv;;*.log;;*.dat;;*.txt;;*.csv;;All Files (*)'
            )
        if fileName:
            self.doLoadLogFile(fileName)
            #self.workerThreadPrepare( "Loading... "+fileName )
            #createTraffic = False
            #if( self.bLoadTraffic.checkState()==QtCore.Qt.Checked ): createTraffic = True
            #self.loadLogThread.setFile(fileName, createTraffic)
            #self.loadLogThread.start()

    #slot for signal finished of cLoadLogThread
    # is called when WorkerThread finishes
    def loadLogFileDone(self):
        if( self.loadLogThread.canceled ): return
        self.loadLogThread.copyToDataContainer(self.dataContainer)
        self.workerThreadFinish()
        # do the final touches
        self.setLogSourceToLoad() #doesn't do anything if it was already cLOGSOURCE_RECORD before
        self.setGraphSelectorTreeFromLogItemList(self.dataContainer.logItemList)
        self.bGraphShowPoints.setCheckState(QtCore.Qt.Unchecked)
        self.setCurrentIndexes()
        self.updateGraph()

    #slot for signal Save Into File, connection to signals in QTDesigner
    # is called then Save button or Save action is hit
    def saveDataIntoFile(self):
        if self.saveLogThread.isRunning():
            return
        ext = '*.dat;;*.txt;;*.csv'
        if self.dataContainer.logType == cLOGTYPE_NTLOGGER:
            ext += ';;CF-Blackbox (*.cfl)'
        ext += ';;All Files (*)'
        fileName, _ = QFileDialog.getSaveFileName(
            self,
            'Save Data to file',
            self.fileDialogDir,
            ext #'*.dat;;*.txt;;*.csv;;PX4 (*.bin);;CF-Blackbox (*.cfl)'
            )
        if fileName:
            if self.dataContainer.logType != cLOGTYPE_NTLOGGER:
                if fileName.lower().endswith('.cfl'): return
            self.workerThreadPrepare( 'saving... ' )
            self.saveLogThread.setFile(fileName)
            self.saveLogThread.start()

    #slot for signal finished of cSaveLogThread
    # is called when WorkerThread finishes
    def saveLogFileDone(self):
        if( self.saveLogThread.canceled ): return
        self.workerThreadFinish()

    #slot for signal ScreenShot
    def doScreenShot(self):
        #if not self.dataContainer.hasData():
        #    return
        fileName, _ = QFileDialog.getSaveFileName(
            self,
            'Save Screenshot to file',
            self.fileDialogDir,
            '*.jpg'
            )
        if fileName:
            self.wGraphComment.setText(self.dataContainer.fileName)
            self.wGraphComment.show()
            #filename = 'C:/Users/Olli/Desktop/screenshot.jpg'
            p = self.wGraphAreaWidget.grab()
            if not fileName.lower().endswith('.jpg'): fileName += '.jpg'
            p.save(fileName, 'jpg')
            self.wGraphComment.hide()


    def clearData(self):
        self.dataContainer.clear()
        self.wLogFileName.setText(self.dataContainer.fileName)
        self.setGraphSelectorTreeFromLogItemList(self.dataContainer.logItemList)
        self.setCurrentIndexes()

    def clearPlot(self):
        self.updateGraphLegend()
        self.updateGraphCursor()
        self.updateGraphTimeLabel()
        self.updateGraphMaxTimeLabel()
        #self.updateGraphTime()
        self.pqPlotWidget.clear() #?? does this do the other 3 updates? no
        self.pqFftWidget.clear()

    def setFileWidgetsToDefault(self):
        self.bLoad.setEnabled(True)
        self.actionLoad.setEnabled(True)
        # this must be done where the button is shown!
        self.bRecordStartStop.setEnabled(True) #can be done since it doesn't hurt, but helps when button visible
        if self.dataContainer.logType != cLOGTYPE_UNINITIALIZED:
            self.bSave.setEnabled(True)
            self.actionSave.setEnabled(True)
            self.actionClear.setEnabled(True)
            # this must be done where the button is shown!
            self.bRecordClear.setEnabled(True)  #can be done since it doesn't hurt, but helps when button visible
        else:
            self.bSave.setEnabled(False)
            self.actionSave.setEnabled(False)
            self.actionClear.setEnabled(False)
            # this must be done where the button is shown!
            self.bRecordClear.setEnabled(False) #can be done since it doesn't hurt, but helps when button visible
        self.bCancelLoad.hide()
        self.wProgressBar.hide()

    #the following handles the logsource handling
    def setLogSourceToUninitialized(self,uncheckRec=True):
        self.clearData()
        self.clearPlot()
        self.serialReaderThread.clear()
        if uncheckRec:
            self.uncheckShowFftRecord()
        self.setFileWidgetsToDefault()

    def setLogSourceToLoad(self):
        if self.dataContainer.logSource == cLOGSOURCE_LOAD: return
        if self.dataContainer.logSource == cLOGSOURCE_RECORD: print('SHIT (1)!!!!') #this should not happen!!!
        #it has now been verifyed that log source is cLOGSOURCE_UNINITIALIZED
        # switch to cLOGSOURCE_LOAD
        self.bLoad.setEnabled(True)
        self.actionLoad.setEnabled(True)  #we require an explicit clear before we allow to load
        #this must be done where the button is shown:
        # self.bRecordStartStop.setEnabled(False)
        # self.bRecordStartStop.setText('Rec Start')
        self.dataContainer.logSource = cLOGSOURCE_LOAD

    def setLogSourceToRecord(self):
        if self.dataContainer.logSource == cLOGSOURCE_RECORD: return
        if self.dataContainer.logSource == cLOGSOURCE_LOAD: print('SHIT (2)!!!!') #this should not happen!!!
        #it has now been verifyed that log source is cLOGSOURCE_UNINITIALIZED
        # switch to cLOGSOURCE_RECORD
        self.bLoad.setEnabled(False)
        self.actionLoad.setEnabled(False)  #we require an explicit clear before we allow to load
        #this must be done where the button is shown
        # self.bRecordStartStop.setEnabled(True)
        # self.bRecordStartStop.setText('Rec Start')
        self.dataContainer.logSource = cLOGSOURCE_RECORD


    #the following 3 slots handle the fft, bode plot, and rec checkboxes in a radiobutton type way
    def hideFft(self,):
        self.pqGraphicsWindow.ci.setSpacing(0)
        self.pqFftWidget.hide()
        self.wGraphFftLength.hide()
        self.wGraphFftWindow.hide()
        self.wGraphFftOutput.hide()
        self.wGraphFftPreFilter.hide()

    def hideRecord(self,):
        self.bRecordStartStop.hide()
        self.bRecordClear.hide()
        self.wRecordComPort.hide()

    def hideFftRecord(self,):
        self.hideFft()
        self.hideRecord()

    def uncheckShowFft(self,):
        self.bGraphShowFft.setCheckState(QtCore.Qt.Unchecked)
        self.hideFft()

    def uncheckShowRecord(self,):
        self.bGraphShowRecord.setCheckState(QtCore.Qt.Unchecked)
        self.hideRecord()

    def uncheckShowFftRecord(self,):
        self.uncheckShowFft()
        self.uncheckShowRecord()

    def showFftClicked(self,):
        self.serialReaderThread.cancelIfRunning()
        if( self.bGraphShowFft.checkState()==QtCore.Qt.Checked ):
            self.pqGraphicsWindow.ci.setSpacing(3)
            self.pqFftWidget.show()
            self.wGraphFftLength.show()
            self.wGraphFftWindow.show()
            self.wGraphFftOutput.show()
            self.wGraphFftPreFilter.show()
            self.updateFftGraph(True) #False) #for some reason True doesn't work properly ????
        else:
            self.hideFft()

    def showRecordClicked(self,):
        if( self.bGraphShowRecord.checkState()==QtCore.Qt.Checked ):
            self.bRecordStartStop.show()
            self.bRecordClear.show()
            self.wRecordComPort.show()
            #this must be done here, where the buttons are shown:
            if( self.dataContainer.logSource == cLOGSOURCE_UNINITIALIZED or
                self.dataContainer.logSource == cLOGSOURCE_RECORD ):
                self.bRecordStartStop.setEnabled(True)
            else:
                self.bRecordStartStop.setEnabled(False)
            if self.dataContainer.logType != cLOGSOURCE_UNINITIALIZED:
                self.bRecordClear.setEnabled(True)
            else:
                self.bRecordClear.setEnabled(False)
        else:
            self.serialReaderThread.cancelIfRunning()
            self.hideRecord()


    #slot for signal itemChanged from wGraphSelectorTree
    # is called when an Item in the GraphSelector is clicked/unclicked
    # it's crucial to avoid this beeing called for every sub level item
    # this exploits the fact that even then a sub level item is clicked the top level item is changed
    def updateGraphOnItemChanged(self,item):
        if item.parent()==None:
            self.setCurrentIndexes()
            self.updateGraph(False)

    #slot for signal clicked from bGraphShowPoints
    def updateGraphOnItemChangedNoAutoRange(self):
        self.setCurrentIndexes()
        self.updateGraph(None)

    #slot for signal currentIndexChanged from bGraphFftLength
    def updateGraphOnFftParameterChanged(self):
        self.setCurrentIndexes()
        self.updateFftGraph(True)

    def doAutoRangeAll(self):
        bounds = self.pqPlotWidget.vb.childrenBoundingRect(items=None)
        if bounds is not None:
            self.pqPlotWidget.setXRange(bounds.left(), bounds.right())
            self.pqPlotWidget.setYRange(bounds.bottom(), bounds.top())
            #self.pqPlotWidget.autoRange()

    def doXAutoRange(self):
        bounds = self.pqPlotWidget.vb.childrenBoundingRect(items=None)
        if bounds is not None:
            self.pqPlotWidget.setXRange(bounds.left(), bounds.right())

    #slot for signal doYAutoRangeFull from bYAutoRangeFull
    def doYAutoRangeFull(self):
        bounds = self.pqPlotWidget.vb.childrenBoundingRect(items=None)
        if bounds is not None:
            self.pqPlotWidget.setYRange(bounds.bottom(), bounds.top())

    #slot for signal doYAutoRangeView from bYAutoRangeView
    def doYAutoRangeView(self):
        #vb.childrenBoundingRect(items=None): (xmin, ymin, dx, dy) of data set
        #viewRange(): [[xmin,xmax],[ymin,ymax]] of plot area
        #viewRect(): (xmin,ymin,dx,dy) of plot area, same as viewRange just as QRectF
        if not self.dataContainer.hasData(): return
        indexes = self.currentGraphIndexes
        if len(indexes) == 0: return
        nr = len(indexes)
        self.dataContainer.setPlotType()
        npPlotView = self.dataContainer.getNpPlotView(nr)
        x = npPlotView[:,0] #this is a view, i.e. not a duplicate
        # find indices of visible x axis
        xRange = self.pqPlotWidget.viewRange()[0]
        xminIndex = np.searchsorted(x, xRange[0]) - 1
        xmaxIndex = np.searchsorted(x, xRange[1])
        if xminIndex < 0: xminIndex = 0
        if xmaxIndex > x.size: xmaxIndex = x.size
        # determine y range # ymin = np.amin( np.amin(pv, axis=0)[1:] ) would find minimum in all y axes
        pv = npPlotView[xminIndex:xmaxIndex,:]
        ymin = 1.0e300; ymax = -1.0e300
        for i in range(nr):
            p = pv[:,indexes[i]]
            y = np.amin(p)
            if y < ymin: ymin = y
            y = np.amax(p)
            if y > ymax: ymax = y
        self.pqPlotWidget.setYRange(ymin, ymax)

    def getIndexes(self):
        indexes = []
        for n in range(self.wGraphSelectorTree.topLevelItemCount()):
            item = self.wGraphSelectorTree.topLevelItem(n)
            if( item.checkState(0) == QtCore.Qt.Checked ):
                indexes += self.graphSelectorList[n][1]
            elif( item.checkState(0) != QtCore.Qt.Unchecked ):
                for i in range(item.childCount()):
                    if( item.child(i).checkState(0) == QtCore.Qt.Checked ):
                        indexes += [self.graphSelectorList[n][1][i]]
        return indexes

    def setCurrentIndexes(self):
        self.currentGraphIndexes = self.getIndexes()

    def updateGraph(self,doXYAutorange=True): #True: in xy, False: only in y, None: none
        if not self.dataContainer.hasData(): return
        # get data colums to plot   // with( pg.BusyCursor() ):
        indexes = self.currentGraphIndexes
        # clear
        self.pqPlotWidget.clear()
        self.pqPlotWidget.addItem(self.pgGraphTimeLine, ignoreBounds=True)
        #self.pqPlotWidget.setClipToView(True) #not good
        #self.pqPlotWidget.setDownsampling(auto=True) hmhmhmh
        # add selected plots
        nr = len(indexes)
        self.dataContainer.setPlotType()
        npPlotView = self.dataContainer.getNpPlotView(nr)
        x = npPlotView[:,0] #this is a view, i.e. not a duplicate
        if self.bGraphShowPoints.checkState()==QtCore.Qt.Checked:
            for i in range(nr):
                self.pqPlotWidget.plot(x, npPlotView[:,indexes[i]],
                                       pen=(i,nr),
                                       symbol='o', symbolSize=4, symbolBrush=(i,nr), symbolPen=(i,nr) )
        else:
            for i in range(nr):
                self.pqPlotWidget.plot(x, npPlotView[:,indexes[i]], pen=(i,nr) )  ## setting pen=(i,3) automaticaly creates three different-colored pens
        # create label
        self.updateGraphLegend(indexes)
        self.updateGraphMaxTimeLabel(x[-1])
        # handle the time slider
        sliderRange = x[-1]/self.dataContainer.dT() #0.0015
        self.wGraphTimeSlider.setRange( 0, int(sliderRange) )
        self.wGraphTimeSlider.setSingleStep( 10 )
        self.wGraphTimeSlider.setPageStep( int(sliderRange/100.0) )
        # auto range as needed
        # self.pqPlotWidget.autoRange() is equal to
        #   bounds = self.pqPlotWidget.vb.childrenBoundingRect(items=None) #is QRectF
        #   if bounds is not None: self.pqPlotWidget.setRange(bounds, padding=None)
        if( doXYAutorange==None ):
            pass
        elif( doXYAutorange ):
            if( self.bYAutoRangeOff.checkState() == QtCore.Qt.Checked ): #autorange only in x
                self.pqPlotWidget.disableAutoRange()
                self.doXAutoRange()
            else:
                self.pqPlotWidget.autoRange()
        elif( self.bYAutoRangeOff.checkState() != QtCore.Qt.Checked ):
            self.doYAutoRangeFull()
        else:
            self.pqPlotWidget.disableAutoRange()
        # handle FFT window
        self.updateFftGraph(True)

    def calculateFftAmplitude(self,signal,signalLen,winType,win,startPos):
            if winType:
                fft = np.fft.rfft( win*signal, n=signalLen )
            else:
                fft = np.fft.rfft( signal, n=signalLen )
            fftAmplitude = np.abs(fft)/(signalLen/2)
            return fftAmplitude[startPos:]

    def doAutoRange(self,_pqWidget,_doXYAutoRange):
        if _doXYAutoRange:
            if( self.bYAutoRangeOff.checkState() != QtCore.Qt.Checked ):
                _pqWidget.autoRange()
            else:
                _pqWidget.disableAutoRange()

    def updateFftGraph(self,_doXYAutorange=True):
        if not self.dataContainer.hasData(): return
        if not self.pqFftWidget.isVisible(): return
        self.pqFftWidget.clear()
        indexes = self.currentGraphIndexes
        if len(indexes)==0: return
        nr = len(indexes)
        # set some parameters
        self.dataContainer.setPlotType()
        signalLen = 2048
        signalLen = signalLen >> self.wGraphFftLength.currentIndex() #2048,1024,512,256
        signalTimeStep = self.dataContainer.dT() #XX 0.0015
        # determine the data window
        npPlotView = self.dataContainer.getNpPlotView(nr)
        x = npPlotView[:,0]
        time = self.pgGraphTimeLine.getPos()[0]
        timeIndex = np.searchsorted(x, time, side="left")
        startIndex = int(timeIndex - signalLen/2)
        #if startIndex>=len(x): startIndex = len(x)-1
        if startIndex+signalLen>=len(x): startIndex = len(x)-signalLen-1
        if startIndex<0: startIndex = 0
        realSignalLen = len(npPlotView[startIndex:startIndex+signalLen,0])
        # get parameters for fft window
        fftWindow = self.wGraphFftWindow.currentIndex()
        fftOutput = self.wGraphFftOutput.currentText() #0: amplitude, 1: psd
        fftPreFilter = self.wGraphFftPreFilter.currentText() #0: none, 1: average
        # determine the fft window
        if( fftWindow==1):    win = np.bartlett(realSignalLen)
        elif( fftWindow==2 ): win = np.blackman(realSignalLen)
        elif( fftWindow==3 ): win = np.hamming(realSignalLen)
        elif( fftWindow==4 ): win = np.hanning(realSignalLen)
        elif( fftWindow==5 ): win = np.kaiser(realSignalLen, pi*2)
        elif( fftWindow==6 ): win = np.kaiser(realSignalLen, pi*3)
        else: win = None
        # calculate and plot fft curves
        startPos = 0 ##1 #remove f=0
        fftFrequencies = np.fft.rfftfreq( signalLen, d=signalTimeStep )
        if fftOutput=='psd (log f)':
            startPos = np.searchsorted( fftFrequencies, 10.0)-1 #15 #remove f<10
            self.pqFftWidget.setLogMode(x=True)
        else:
            self.pqFftWidget.setLogMode(x=False)
        fftFrequencies = fftFrequencies[startPos:]
        # limit to at most 3 fft curves
        nrRange = nr
        if nrRange>3: nrRange = 3
        for i in range(nrRange):
            signal = npPlotView[startIndex:startIndex+signalLen,indexes[i]]
            #if fftOutput=='amplitude' and fftWindow>0:
            if fftPreFilter=='average':
                signal2 = np.copy(signal)
                signal = signal2
                signal -= signal.mean()
            fftAmplitude = self.calculateFftAmplitude(signal, signalLen, fftWindow, win, startPos)
            if fftPreFilter=='average':
                pass
            elif fftPreFilter=='1 Hz':
                filt = np.ones(len(fftAmplitude))
                fi = 0;
                while fftFrequencies[fi]<=1:
                    filt[fi] = 0;
                    fi += 1
                fftAmplitude = fftAmplitude*filt;
            elif fftPreFilter=='2 Hz':
                filt = np.ones(len(fftAmplitude))
                fi = 0;
                while fftFrequencies[fi]<=2:
                    filt[fi] = 0;
                    fi += 1
                fftAmplitude = fftAmplitude*filt;
            elif fftPreFilter=='4 Hz':
                filt = np.ones(len(fftAmplitude))
                fi = 0;
                while fftFrequencies[fi]<=4:
                    filt[fi] = 0;
                    fi += 1
                fftAmplitude = fftAmplitude*filt;
            if fftOutput=='psd (lin f)':
                fftAmplitude = 40*np.log10(np.clip(fftAmplitude,1.0e-24,1.0e24)) #log(x^2) = 2log(x)
            elif fftOutput=='psd (log f)':
                fftAmplitude = 40*np.log10(np.clip(fftAmplitude,1.0e-24,1.0e24)) #log(x^2) = 2log(x)
            self.pqFftWidget.plot(fftFrequencies, fftAmplitude, pen=(i,nr))
        if( self.bFftAutoRange.checkState()==QtCore.Qt.Checked ):
            self.doAutoRange(self.pqFftWidget, _doXYAutorange)


    def updateGraphLegend(self, indexes=[]): #indexes indicates also if it should be plotted or not
        nr = len(indexes)
        label = ''
        for i in range(nr):
            col = pg.mkColor( (i,nr) )
            colstr = pg.colorStr(col)[:6]
            label += "<span style='color: #"+colstr+"'>"+self.logItemNameList[indexes[i]] + "</span> , "
        self.wGraphLegend.setText( label[:-3] )

    def updateGraphCursor(self, x=0, y=0):
        self.wGraphCursor.setText( self.wGraphCursorFormatStr % (x,y))

    #is also slot for
    def updateGraphCursorEvent(self, event):
        #event is a QPointF
        if( self.pqPlotWidget.sceneBoundingRect().contains(event) ):
            mousePoint = self.pqPlotWidget.vb.mapSceneToView(event)
            self.updateGraphCursor( mousePoint.x(), mousePoint.y() )

    def updateGraphMaxTimeLabel(self,time=0.0):
        if( time<0.0 ): time = 0.0
        if( time>4480.0 ): time = 4480.0
        qtimezero = QtCore.QTime(0,0,0,0)
        qtime = qtimezero.addMSecs(time*1000.0)
        self.wGraphMaxTimeLabel.setText( self.wGraphTimeFormatStr % qtime.toString("mm:ss:zzz") )

    def updateGraphTimeLabel(self,time=0.0):
        if( time<0.0 ): time = 0.0 #this restricts also pos line
        if( time>4480.0 ): time = 4480.0
        maxtime = self.dataContainer.getMaxTime()
        if( time>maxtime ): time = maxtime #this restricts also pos line
        qtimezero = QtCore.QTime(0,0,0,0)
        qtime = qtimezero.addMSecs(time*1000.0)
        self.wGraphTimeLabel.setText( self.wGraphTimeFormatStr % qtime.toString("mm:ss:zzz") )
        self.pgGraphTimeLine.setPos(time)
        self.updateFftGraph(True)

    def updateGraphTimeSlider(self,time=0.0):
        tindex = int(time/self.dataContainer.dT()) #0.0015)
        if( tindex<0 ): tindex = 0
        if( tindex>self.wGraphTimeSlider.maximum() ): tindex = self.wGraphTimeSlider.maximum()
        self.wGraphTimeSlider.blockSignals(True)
        self.wGraphTimeSlider.setValue( tindex ) #emits a updateGraphTimeSliderValueChangedEvent()
        self.wGraphTimeSlider.blockSignals(False)

    def updateGraphTime(self,time=0.0):
        self.updateGraphTimeLabel(time)
        self.updateGraphTimeSlider(time)

    #is also slot for wGraphTimeSlider.valueChanged()
    def updateGraphTimeSliderValueChangedEvent(self,event):
        time = float(event)*self.dataContainer.dT()
        xRange = self.pqPlotWidget.viewRange()[0]
        deltatime = 0.5*( xRange[1] - xRange[0] )
        self.pqPlotWidget.blockSignals(True)
        self.pqPlotWidget.setXRange( time-deltatime, time+deltatime, padding=0.0 ) #emits a updateGraphRangeChangedEvent()
        self.pqPlotWidget.blockSignals(False)
        self.updateGraphTimeLabel(time)

    #is also slot for pqPlotWidget.sigXRangeChanged()
    def updateGraphRangeChangedEvent(self,event):
        xRange = event.viewRange()[0] #is [float,float]
        time = 0.5*( xRange[0] + xRange[1] )
        self.updateGraphTime(time)

    def doGraphZoomFactor(self):
        xRange = self.pqPlotWidget.viewRange()[0]
        time = 0.5*( xRange[0] + xRange[1] )
        bounds = self.pqPlotWidget.vb.childrenBoundingRect(items=None) #is QRectF
        index = self.wGraphZoomFactor.currentText() #['100 %','10 %','1 %','10 s','5 s','1 s','100 ms']
        if(   index == '100 %' ):  deltatime = 0.5*( bounds.right() - bounds.left() )
        elif( index == '10 %' ):   deltatime = 0.05*( bounds.right() - bounds.left() )
        elif( index == '1 %' ):    deltatime = 0.005*( bounds.right() - bounds.left() )
        elif( index == '30 s' ):   deltatime = 15.0
        elif( index == '10 s' ):   deltatime = 5.0
        elif( index == '5 s' ):    deltatime = 2.5
        elif( index == '2 s' ):    deltatime = 1.0
        elif( index == '1 s' ):    deltatime = 0.5
        elif( index == '250 ms' ): deltatime = 0.125
        elif( index == '100 ms' ): deltatime = 0.05
        self.pqPlotWidget.setXRange( time-deltatime, time+deltatime, padding=0.0 ) #emits a signal, which calls updateGraphTime()


    #slot for signal clicked from bRecordClear
    def doRecordClearClicked(self):
        self.setLogSourceToUninitialized(False) #don't uncheck rec

    #slot for signal clicked from bRecordStartStop
    def doRecordStartStopClicked(self):
        if not self.serialReaderThread.isRunning():
            self.setLogSourceToRecord() #doesn't do anything if it was already cLOGSOURCE_RECORD before
            self.bSave.setEnabled(True)
            self.actionSave.setEnabled(True)
            self.actionClear.setEnabled(False)
            self.bRecordClear.setEnabled(False)
            self.bRecordStartStop.setText('Rec Stop')
            self.serialReaderThread.openSerial(self.wRecordComPort.currentPort())
            self.bGraphShowPoints.setCheckState(QtCore.Qt.Unchecked)
            self.uncheckShowFft()  #XX
            self.dataContainer.setRecordOn(True)
            self.serialReaderThread.start()
        else:
            self.serialReaderThread.cancel()

    #slot for signal finished of cSerialThread
    def serialReaderThreadDone(self):
        self.serialReaderThread.closeSerial()
        if (self.dataContainer.logType != cLOGTYPE_UNINITIALIZED) or (not self.dataContainer.hasData()):
            self.actionClear.setEnabled(True)
            self.bRecordClear.setEnabled(True)
        self.bRecordStartStop.setText('Rec Start')
        self.dataContainer.setRecordOn(False)
        if self.dataContainer.hasData():
            self.updateGraph(None)


    def serialReaderThreadNewDataAvailable(self):
        dataline = self.serialReaderThread.getDataLine()
        self.dataContainer.appendDataLine(dataline)
        self.dataContainer.logType = cLOGTYPE_NTLOGGER
        if self.dataContainer.hasData():
            self.updateGraph(True)


    #slot for signal openAbout, connection to signals in QTDesigner
    def openAbout(self):
        QMessageBox.about(self, 'NT DataLogger Tool About',
            "OlliW's NT DataLogger Tool\n\n" +
            "(c) OlliW @ www.olliw.eu\n\n"+VersionStr+"\n\n" +
            "This program is part of the STorM32 gimbal controller project.    \n" +
            "Project web page: http://www.olliw.eu/\n\n"
            )

    def readSettings(self):
        settings = QSettings(IniFileStr, QSettings.IniFormat)
        if int(settings.value('SYSTEM/LoadTraffic',0)):
            self.bLoadTraffic.setCheckState(QtCore.Qt.Checked)
        #if( int(settings.value('SYSTEM/GraphShowPoints',0)) ):
        #    self.bGraphShowPoints.setCheckState(QtCore.Qt.Checked)
        p = settings.value('PORT/Port')
        if p: self.wRecordComPort.setCurrentPort( p )

    def writeSettings(self):
        settings = QSettings(IniFileStr, QSettings.IniFormat)
        if self.bLoadTraffic.checkState()==QtCore.Qt.Checked:
            settings.setValue('SYSTEM/LoadTraffic',1)
        else:
            settings.setValue('SYSTEM/LoadTraffic',0)
        if self.bGraphShowPoints.checkState()==QtCore.Qt.Checked:
            settings.setValue('SYSTEM/GraphShowPoints',1)
        else:
            settings.setValue('SYSTEM/GraphShowPoints',0)
        settings.setValue('SYSTEM/Style',appPalette)
        settings.setValue('PORT/Port',self.wRecordComPort.currentPort())
        settings.sync()

    def closeEvent(self, event):
        self.writeSettings()
        event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat('text/uri-list') and self.loadLogFileIsAllowed():
            t = event.mimeData().text()
            if t.lower().endswith('.log') or t.lower().endswith('.dat') or t.lower().endswith('.txt'):
                event.accept()
                return
        event.ignore()

    def dropEvent(self, event):
        if self.loadLogFileIsAllowed():
            fn =  event.mimeData().text().replace('file:///','').replace('/','\\')
            self.doLoadLogFile(fn)



###################################################################
# Main()
##################################################################
if __name__ == '__main__':

    # as first step set the device pixel ratio, is either 1.0 or 2.0
    #  this is required to make other packages as happy as possible, e.g. pyqtgraph and QMessageBox
    from win32api import GetSystemMetrics   #see also: https://msdn.microsoft.com/en-us/library/windows/desktop/ms724385%28v=vs.85%29.aspx
    winScaledYRes = GetSystemMetrics(1) #returns the diplsay resolution = SM_CYSCREEN
    from ctypes import windll
    dc = windll.user32.GetDC(0)
    winYRes = windll.gdi32.GetDeviceCaps(dc,117) #= DESKTOPVERTRES, see https://msdn.microsoft.com/de-de/library/windows/desktop/dd144877%28v=vs.85%29.aspx
    winScale1 = float(winYRes)/float(winScaledYRes)
    winScaleEnvironment = int(winScale1)
    import os  #os.environment is effective only when called before app is v?created
    os.environ['QT_DEVICE_PIXEL_RATIO'] = str(winScaleEnvironment) #this soehow only takes/allows integer values!!!

    app = QApplication(sys.argv)

    settings = QSettings(IniFileStr, QSettings.IniFormat)
    appPalette = settings.value('SYSTEM/Style','auto')
    #appPalette = 'Standard'
    if( appPalette == 'Fusion' ):
        QApplication.setStyle(QStyleFactory.create('Fusion'))
    elif( appPalette == 'Standard' ):
        QApplication.setPalette(QApplication.style().standardPalette())
    elif( appPalette == 'auto' ):
        if( winScaleEnvironment>1.9 ):
            QApplication.setStyle(QStyleFactory.create('Fusion'))
        else:
            QApplication.setPalette(QApplication.style().standardPalette())
    else:
        QApplication.setPalette(QApplication.style().standardPalette())

    # as second step set the WINSCALE
    #  do this by determining the "real" Windows scale form the fonts, and then corricting for the previously set scale
    #  ratio = app.primaryScreen().devicePixelRatio() #works, gives 1.0 or 2.0
    #  ratio = app.devicePixelRatio() #works, gives 1.0 or 2.0
    winScale = 1.0
    winScaleFont = ( 3.0 * QFontInfo(app.font()).pixelSize() )/( 4.0 * QFontInfo(app.font()).pointSizeF() )
    #winScale = float(winScaleFont)/float(winScaleEnvironment)
    winScale = float(winScaleFont)
    if( winScale<1.0 ): winScale = 1.0

    main = cMain(winScale, appPalette)
    main.show()
    sysexit = app.exec_()
    sys.exit(sysexit)




#QApplication.processEvents()
#QtGui.qApp.processEvents()

#    QApplication.setStyle(QStyleFactory.create('Windows'))
#    QApplication.setStyle(QStyleFactory.create('Fusion'))
#    QApplication.setPalette(QApplication.style().standardPalette())
#    QApplication.setPalette(QApplication.palette())

#https://www.snip2code.com/Snippet/683053/Qt5-Fusion-style-%28dark-color-palette%29
#qApp->setStyle(QStyleFactory::create("fusion"));
#QPalette palette;
#palette.setColor(QPalette::Window, QColor(53,53,53));
#palette.setColor(QPalette::WindowText, Qt::white);
#palette.setColor(QPalette::Base, QColor(15,15,15));
#palette.setColor(QPalette::AlternateBase, QColor(53,53,53));
#palette.setColor(QPalette::ToolTipBase, Qt::white);
#palette.setColor(QPalette::ToolTipText, Qt::white);
#palette.setColor(QPalette::Text, Qt::white);
#palette.setColor(QPalette::Button, QColor(53,53,53));
#palette.setColor(QPalette::ButtonText, Qt::white);
#palette.setColor(QPalette::BrightText, Qt::red);
#palette.setColor(QPalette::Highlight, QColor(142,45,197).lighter());
#palette.setColor(QPalette::HighlightedText, Qt::black);
#qApp->setPalette(palette);


#https://gist.github.com/lschmierer/443b8e21ad93e2a2d7eb
#qApp.setStyle("Fusion")
#dark_palette = QPalette()
#dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
#dark_palette.setColor(QPalette.WindowText, Qt.white)
#dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
#dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
#dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
#dark_palette.setColor(QPalette.ToolTipText, Qt.white)
#dark_palette.setColor(QPalette.Text, Qt.white)
#dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
#dark_palette.setColor(QPalette.ButtonText, Qt.white)
#dark_palette.setColor(QPalette.BrightText, Qt.red)
#dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
#dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
#dark_palette.setColor(QPalette.HighlightedText, Qt.black)
#qApp.setPalette(dark_palette)
#qApp.setStyleSheet("QToolTip { color: #ffffff; background-color: #2a82da; border: 1px solid white; }")

    '''
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)
#    form.setPalette(dark_palette)
    QApplication.setPalette(dark_palette)
    '''

#DevicePixelRatio experiments
'''
ratio = QApplication.primaryScreen().devicePixelRatio()

=> gives always 1.0, independent on Win Scaling
'''

#FONT sizes experiments
'''
str(QFontInfo(appfont).pixelSize()) + ","+
str(QFontInfo(appfont).pointSize()) + ","+
str(QFontInfo(appfont).pointSizeF()) +"\n"+

str(QFontInfo(self.wTab.font()).pixelSize()) + ","+
str(QFontInfo(self.wTab.font()).pointSize()) + ","+
str(QFontInfo(self.wTab.font()).pointSizeF()) +"\n"+

str(QFontInfo(self.wDataText.font()).pixelSize()) + ","+
str(QFontInfo(self.wDataText.font()).pointSize()) + ","+
str(QFontInfo(self.wDataText.font()).pointSizeF())

Win Scaling 100%:
11  8   8.25
11  8   8.25
13  10  9.75
Win Scaling 150%:
13  8   7.8
13  8   7.8
17  10  10.2
Win Scaling 150%:
16  8   8.0
16  8   8.0
20  10  10.0
Win Scaling 200%:
21  8   7.875
21  8   7.875
27  10  10.125
Win Scaling 250%:
27  8   8.1
27  8   8.1
33  10  9.9

=> pixelSize = pointSizeF * 4/3 * WinScaling

=> SCALE = ( 3 * pixelSize )/( 4 * pointSizeF )
'''

'''
    from win32api import GetSystemMetrics   #see also: https://msdn.microsoft.com/en-us/library/windows/desktop/ms724385%28v=vs.85%29.aspx
    winScaledYRes = GetSystemMetrics(1) #returns the diplsay resolution = SM_CYSCREEN
    from ctypes import windll
    dc = windll.user32.GetDC(0)
    winYRes = windll.gdi32.GetDeviceCaps(dc,117) #= DESKTOPVERTRES, see https://msdn.microsoft.com/de-de/library/windows/desktop/dd144877%28v=vs.85%29.aspx
    winScale1 = float(winYRes)/float(winScaledYRes)
    winScaleEnvironment = int(winScale1)
    import os  #os.environment is effective only when called before app is v?created
    os.environ['QT_DEVICE_PIXEL_RATIO'] = str(winScaleEnvironment) #this soehow only takes/allows integer values!!!

    This worked for all except 125%!
    winScale = str(winYRes) + "," + str(winScaledYRes) + "="+str( float(winYRes)/float(winScaledYRes) ) + "!"
    100%    1800,1800=1.0
    125%    1800,1800=1.0
    150%    1800,1200=1.5
    200%    1800,900=2.0
    250%    1800,720=2.5
    '''



#        QMessageBox msgBox
#        msgBox.setText("The document has been modified.")
#        msgBox.setInformativeText("Do you want to save your changes?")
#        msgBox.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
#        msgBox.setDefaultButton(QMessageBox.Save)
#        ret = msgBox.exec_()
#        reply = QMessageBox.question(self, 'Message',
#            "Are you sure to quit?", QMessageBox.Ok, QMessageBox.Ok)





                #swapping numpy columns
                #a) arr[:,[frm, to]] = arr[:,[to, frm]]
                #b) arr[:, 0], arr[:, 1] = arr[:, 1], arr[:, 0].copy()






'''
some facts about the (discrete) FFT:
signal with dt steps a_n -> FFT A_k
i)  signal with dt steps but shifted by one, i.e. a'_n = a_(n+1)
    -> only phase shift of the A_k, FFT A'_k = A_k * exp(-iXX)
ii) signal with dt/2 steps, but zeros in between, i.e. a'_(2n) = a_n, a'_(2n+1) = 0
    -> A'_k gets twice as wide, but spectrum get's duplicated(mirrored) in 2nd half due to periodicity of A_k in k
=>
signal with each data sample doubled produces
* identical spectrum to half the signal with single data sanmples up to half the frequency
* spectrum above half the frequency is mirrored in
=>
4kHz acc signal sampled at 8kHz, only look at spectrum 0-2kHz
'''
