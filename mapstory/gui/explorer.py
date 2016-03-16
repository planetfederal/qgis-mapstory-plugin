# -*- coding: utf-8 -*-
#
# (c) 2016 Boundless, http://boundlessgeo.com
# This code is licensed under the GPL 2.0 license.
#
import os
from PyQt4 import QtGui, QtCore, uic
from qgis.core import *
from qgis.gui import *
from qgis.utils import iface
import sys
from mapstory.tools.utils import *
from PyQt4.QtGui import QTreeWidgetItem
from mapstory.tools.story import Story
from mapstory.gui.executor import execute
from mapstory.tools.animation import addAnimation

def icon(f):
    return QtGui.QIcon(os.path.join(os.path.dirname(__file__), os.pardir, "resources", f))

layerIcon = icon("layer.png")
layersIcon = icon("layer_group.gif")

# Adding so that our UI files can find resources_rc.py
sys.path.append(os.path.dirname(__file__))

pluginPath = os.path.split(os.path.dirname(__file__))[0]
WIDGET, BASE = uic.loadUiType(
    os.path.join(pluginPath, 'ui', 'mapstoryexplorer.ui'))

GEOM_TYPE_MAP = {
    QGis.WKBPoint: 'Point',
    QGis.WKBLineString: 'LineString',
    QGis.WKBPolygon: 'Polygon',
    QGis.WKBMultiPoint: 'MultiPoint',
    QGis.WKBMultiLineString: 'MultiLineString',
    QGis.WKBMultiPolygon: 'MultiPolygon',
}

class MapStoryExplorer(BASE, WIDGET):

    def __init__(self):
        super(MapStoryExplorer, self).__init__(None)

        self.story = None
        self.currentLayerItem = None
        self.setupUi(self)

        self.setAllowedAreas(QtCore.Qt.RightDockWidgetArea | QtCore.Qt.LeftDockWidgetArea)

        self.layersTree.itemClicked.connect(self.treeItemClicked)
        self.layerDescription.setOpenLinks(False)
        self.layerDescription.anchorClicked.connect(self.layerDescriptionLinkClicked)
        self.layerDescription.setFocusPolicy(QtCore.Qt.NoFocus)

        self.storyDescription.setOpenLinks(False)
        self.storyDescription.anchorClicked.connect(self.storyDescriptionLinkClicked)
        self.storyDescription.setFocusPolicy(QtCore.Qt.NoFocus)

        with open(resourceFile("layerdescription.css")) as f:
            sheet = "".join(f.readlines())
        self.layerDescription.document().setDefaultStyleSheet(sheet)
        self.storyDescription.document().setDefaultStyleSheet(sheet)
        self.layersTree.header().setResizeMode(0, QtGui.QHeaderView.Stretch)
        self.layersTree.header().setResizeMode(1, QtGui.QHeaderView.ResizeToContents)

        self.updateCurrentStory(None)


    def storyDescriptionLinkClicked(self, url):
        url = url.toString()
        if url == "search":
            text, ok = QtGui.QInputDialog.getText(self, 'Set story', 'Enter story number id:')
            if ok:
                story = Story.storyFromNumberId(text)
                if story is None:
                    QtGui.QMessageBox.warning(iface.mainWindow(), "MapStory", "Cannot get MapStory data.\nCheck that the provided ID is correct.")
                else:
                    self.updateCurrentStory(story)
        elif url == "download":
            outDir = QtGui.QFileDialog.getExistingDirectory(self,
                                                  self.tr("Select output directory"),
                                                  "."
                                                 )
            if not outDir:
                return

            QtCore.QDir().mkpath(outDir)

            settings = QtCore.QSettings()
            systemEncoding = settings.value('/UI/encoding', 'System')
            startProgressBar(len(self.story.storyLayers()), "Download layers for off-line use:")
            for i, layer in enumerate(self.story.storyLayers()):
                filename = os.path.join(outDir, layer.name() + ".shp")
                uri = "%s?srsname=%s&typename=%s&version=1.0.0&request=GetFeature&service=WFS" % (layer.wfsUrl(), layer.crs(), layer.name())
                qgslayer = QgsVectorLayer(uri, layer.name(), "WFS")
                writer = QgsVectorFileWriter(filename, systemEncoding,
                                             qgslayer.pendingFields(),
                                             qgslayer.dataProvider().geometryType(),
                                             qgslayer.crs())
                for feat in qgslayer.getFeatures():
                    writer.addFeature(feat)
                del writer

                fieldname = self._getTimeField(qgslayer)

                if fieldname is not None:
                    filename = os.path.join(outDir, layer.name() + ".timefield")
                    with open(filename, "w") as f:
                        f.write(fieldname)
                setProgress(i+1)

            closeProgressBar()
            iface.messageBar().pushMessage("MapStory", "Layers have been correctly saved as QGIS project.", level=QgsMessageBar.INFO, duration=3)


    def _getTimeField(self, layer):
        fields = layer.pendingFields()
        for f in fields:
            if f.typeName() == "xsd:dateTime":
                return f.name()

    def layerDescriptionLinkClicked(self, url):
        url = url.toString()
        service, url, name, crs = url.split("|")
        if service == "wms":
            uri = "url=%s&styles=&layers=%s&format=image/png&crs=%s" % (url,name, crs)
            qgslayer = execute(lambda: QgsRasterLayer(uri, name, "wms"))
            if not qgslayer.isValid():
                raise Exception ("Layer at %s is not a valid layer" % uri)
            QgsMapLayerRegistry.instance().addMapLayers([qgslayer])
        elif service == "wfs":
            def f():
                crs = iface.mapCanvas().mapRenderer().destinationCrs()
                uri = "%s?srsname=%s&typename=%s&version=1.0.0&request=GetFeature&service=WFS" % (url, crs.authid(), name)
                qgslayer = QgsVectorLayer(uri, name, "WFS")
                if not qgslayer.isValid():
                    raise Exception ("Layer at %s is not a valid layer" % uri)

                fieldname = self._getTimeField(qgslayer)

                if fieldname is None:
                    QgsMapLayerRegistry.instance().addMapLayers([qgslayer])
                else:
                    memlayer = QgsVectorLayer("%s?crs=%s" % (GEOM_TYPE_MAP[qgslayer.wkbType()], crs.authid()), name, "memory")
                    memlayer.startEditing()
                    for field in qgslayer.pendingFields():
                        memlayer.addAttribute(field)
                    for feat in qgslayer.getFeatures():
                        memlayer.addFeatures([feat])
                    memlayer.commitChanges()
                    QgsMapLayerRegistry.instance().addMapLayers([memlayer])
                    memlayer.setSelectedFeatures([])
                    addAnimation(memlayer, fieldname)
            execute(f)




    def updateCurrentStory(self, story):
        self.layersTree.clear()
        self.currentLayerItem = None
        self.story = story
        if story is None:
            self.storyDescription.setText("No MapStory selected. <a href='search'>[Click to open a MapStory]</a>")
            return

        self.storyDescription.setText(story.description())
        self.layersItem = QTreeWidgetItem()
        self.layersItem.setText(0, "Layers")
        self.layersItem.setIcon(0, layersIcon)
        for layer in story.storyLayers():
            item = LayerItem(layer)
            self.layersItem.addChild(item)

        self.layersTree.addTopLevelItem(self.layersItem)

        self.layersItem.setExpanded(True)


    def treeItemClicked(self, item, i):
        if self.currentLayerItem == item:
            return
        self.currentLayerItem = item
        if isinstance(item, LayerItem):
            self.updateCurrentLayer()


    def updateCurrentLayer(self):
        self.layerDescription.setText(self.currentLayerItem.layer.description())


class LayerItem(QtGui.QTreeWidgetItem):
    def __init__(self, layer):
        QtGui.QTreeWidgetItem.__init__(self)
        self.layer = layer
        self.setText(0, layer.title())
        self.setIcon(0, layerIcon)


explorerInstance = MapStoryExplorer()


