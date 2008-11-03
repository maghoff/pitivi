# PiTiVi , Non-linear video editor
#
#       pitivi/timeline/objects.py
#
# Copyright (c) 2005, Edward Hervey <bilboed@bilboed.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.

"""
Timeline objects
"""

import weakref
from random import randint
import gst
from pitivi.serializable import Serializable
from pitivi.objectfactory import ObjectFactory
from pitivi.signalinterface import Signallable

(MEDIA_TYPE_NONE,
 MEDIA_TYPE_AUDIO,
 MEDIA_TYPE_VIDEO) = range(3)

## * Object Hierarchy

##   Object
##    |
##    +---- Source
##    |    |
##    |    +---- FileSource
##    |    |
##    |    +---- LiveSource
##    |    |
##    |    +---- Composition
##    |
##    +---- Effect
##         |
##         +---- Simple Effect (1->1)
##         |
##         +---- Transition
##         |
##         +---- Complex Effect (N->1)

class BrotherObjects(Serializable, Signallable):
    """
    Base class for objects that can have a brother and be linked to something else

    Properties:
      _ Linked Object
        _ Can be None
        _ Must have same duration
      _ Brother object
        _ This is the same object but with the other media_type

    Signals:
      _ 'linked-changed' : new linked object

    Save/Load properties:
    * (optional) 'linked' (int) : UID of linked object
    * (optional) 'brother' (int) : UID of brother object
    """

    __data_type__ = "timeline-brother-objects"

    __signals__ = {
        "linked-changed" : ["brother"]
        }

    # UID (int) => object (BrotherObjects) mapping.
    __instances__ = weakref.WeakValueDictionary()

    # dictionnary of objects waiting for pending objects for completion
    # pending UID (int) => objects (list of BrotherObjects and extra field)
    __waiting_for_pending_objects__ = {}

    def __init__(self, **unused_kw):
        self._linked = None
        self._brother = None
        self.uid = -1

    ## properties

    def _get_brother(self):
        return self.getBrother()

    def _set_brother(self, brother):
        self.setBrother(brother)
    brother = property(_get_brother, _set_brother,
                       doc="Brother object")

    ## read-only properties

    @property
    def linked(self):
        """ Linked object """
        return self._linked


    ## public API

    def linkObject(self, obj):
        """
        link another object to this one.
        If there already is a linked object ,it will unlink it
        """
        if self._linked and not self._linked == obj:
            self.unlinkObject()
        self._linkObject(obj)
        self._linked._linkObject(self)

    def unlinkObject(self):
        """
        unlink from the current linked object
        """
        if self._linked:
            self._linked._unlinkObject()
        self._unlinkObject()

    def relinkBrother(self):
        """
        links the object back to it's brother
        """
        # if already linked, unlink from previous
        if self._linked:
            self.unlinkObject()

        # link to brother
        if self._brother:
            self.linkObject(self._brother)

    def getBrother(self, autolink=True):
        """
        returns the brother element if it's possible,
        if autolink, then automatically link it to this element
        """
        if not self._brother:
            self._brother = self._makeBrother()
            if not self._brother:
                return None
        if autolink and not self._linked == self._brother:
            self.relinkBrother()
        return self._brother

    def setBrother(self, brother, autolink=True):
        """
        Force a brother on an object.
        This can be useful if it's the parent of the object that knows
        what his brother is.

        Use with caution !!!
        """
        gst.log("brother:%r , autolink:%r" % (brother, autolink))
        self._brother = brother
        if self._brother:
            # set ourselves as our brother's brother
            self._brother._brother = self
        if autolink:
            self.relinkBrother()

    # private methods

    def _unlinkObject(self):
        # really unlink the objects
        if self._linked:
            self._linked = None
            self.emit("linked-changed", None)

    def _linkObject(self, obj):
        # really do the link
        self._linked = obj
        self.emit("linked-changed", self._linked)

    # methods to override in subclasses

    def _makeBrother(self):
        """
        Make the exact same object for the other media_type
        implemented in subclasses
        """
        raise NotImplementedError

    # Serializable methods

    def toDataFormat(self):
        ret = Serializable.toDataFormat(self)
        ret["uid"] = self.getUniqueID()
        if self._brother:
            ret["brother-uid"] = self._brother.getUniqueID()
        if self._linked:
            ret["linked-uid"] = self._linked.getUniqueID()
        return ret

    def fromDataFormat(self, obj):
        Serializable.fromDataFormat(self, obj)
        self.setUniqueID(obj["uid"])

        if "brother-uid" in obj:
            brother = BrotherObjects.getObjectByUID(obj["brother-uid"])
            if not brother:
                BrotherObjects.addPendingObjectRequest(self, obj["brother-uid"], "brother")
            else:
                self.setBrother(brother)

        if "linked-uid" in obj:
            linked = BrotherObjects.getObjectByUID(obj["linked-uid"])
            if not linked:
                BrotherObjects.addPendingObjectRequest(self, obj["linked-uid"], "linked")
            else:
                self.linkObject(linked)

    def pendingObjectCreated(self, obj, field):
        gst.log("field:%s, obj:%r" % (field, obj))
        if field == "brother":
            self.setBrother(obj, autolink=False)
        elif field == "linked":
            self.linkObject(obj)

    # Unique ID methods

    def getUniqueID(self):
        if self.uid == -1:
            i = randint(0, 2**32)
            while i in BrotherObjects.__instances__:
                i = randint(0, 2 ** 32)
            self.uid = i
            gst.log("Assigned uid %d to %r, adding to __instances__" % (self.uid, self))
            BrotherObjects.__instances__[self.uid] = self
        return self.uid

    def setUniqueID(self, uid):
        if not self.uid == -1:
            raise Exception("Trying to set uid [%d] on an object that already has one [%d]" % (uid, self.uid))
            return

        if uid in BrotherObjects.__instances__:
            raise Exception("Uid [%d] is already in use by another object [%r]" % (uid, BrotherObjects.__instances__[uid]))
            return

        self.uid = uid
        gst.log("Recording __instances__[uid:%d] = %r" % (self.uid, self))
        BrotherObjects.__instances__[self.uid] = self

        # Check if an object needs to be informed of our creation
        self._haveNewID(self.uid)

    @classmethod
    def getObjectByUID(cls, uid):
        """
        Returns the object with the given uid if it exists.
        Returns None if no object with the given uid exist.
        """
        gst.log("uid:%d" % uid)
        if uid in cls.__instances__:
            return cls.__instances__[uid]
        return None

    # Delayed object creation methods

    def _haveNewID(self, uid):
        """
        This method is called when an object gets a new ID.
        It will check to see if any object needs to be informed of the creation
        of this object.
        """
        gst.log("uid:%d" % uid)
        if uid in BrotherObjects.__waiting_for_pending_objects__ and uid in BrotherObjects.__instances__:
            for obj, extra in BrotherObjects.__waiting_for_pending_objects__[uid]:
                # obj is a weakref.Proxy object
                obj.pendingObjectCreated(BrotherObjects.__instances__[uid], extra)
            del BrotherObjects.__waiting_for_pending_objects__[uid]


    @classmethod
    def addPendingObjectRequest(cls, obj, uid, extra=None):
        """
        Ask to be called when the object with the given uid is created.
        obj : calling object
        uid : uid of the object we need to be informed of creation
        extra : extradata with which obj's callback will be called

        The class will call the calling object's when the requested object
        is available using the following method call:
        obj.pendingObjectCreated(new_object, extra)
        """
        if not uid in cls.__waiting_for_pending_objects__:
            cls.__waiting_for_pending_objects__[uid] = []
        cls.__waiting_for_pending_objects__[uid].append((weakref.proxy(obj), extra))




class TimelineObject(BrotherObjects):
    """
    Base class for all timeline objects

    * Properties
      _ Start/Duration Time
      _ Media Type
      _ Gnonlin Object

    * signals
      _ 'start-duration-changed' : start position, duration position

    Save/Load properties
    * 'start' (int) : start position in nanoseconds
    * 'duration' (int) : duration in nanoseconds
    * 'name' (string) : name of the object
    * 'factory' (int) : UID of the objectfactory
    * 'mediatype' (int) : media type of the object
    """

    __data_type__ = "timeline-object"

    # Set this to False in sub-classes that don't require a factory in
    # order to create their gnlobject.
    __requires_factory__ = True

    __signals__ = {
        "start-duration-changed" : ["start", "duration"]
        }

    def __init__(self, factory=None, start=gst.CLOCK_TIME_NONE,
                 duration=0, media_type=MEDIA_TYPE_NONE, name="", **kwargs):
        BrotherObjects.__init__(self, **kwargs)
        self.name = name
        gst.log("new TimelineObject :%s %r" % (name, self))
        self._start = start
        if duration == 0 and factory:
            duration = factory.default_duration
        self._duration = duration
        self._factory = None
        # Set factory and media_type and then create the gnlobject
        self.media_type = media_type
        self.gnlobject = None
        self.factory = factory

    ## properties

    def _get_start(self):
        return self._start

    def _set_start(self, start):
        self.setStartDurationTime(start=start)
    start = property(_get_start, _set_start,
                     doc="Start position of the object in its container (in nanoseconds)")

    def _get_duration(self):
        return self._duration

    def _set_duration(self, duration):
        self.setStartDurationTime(duration=duration)
    duration = property(_get_duration, _set_duration,
                        doc="Duration of the object in its container (in nanoseconds)")

    def _get_factory(self):
        return self._factory

    def _set_factory(self, factory):
        self._setFactory(factory)
    factory = property(_get_factory, _set_factory,
                       doc="ObjectFactory used for this object")


    ## read-only properties

    @property
    def isaudio(self):
        """ Boolean indicating whether the object produces Audio """
        return self.media_type == MEDIA_TYPE_AUDIO

    @property
    def isvideo(self):
        """ Boolean indicating whether the object produces Video """
        return self.media_type == MEDIA_TYPE_VIDEO

    ## public API

    def setStartDurationTime(self, start=gst.CLOCK_TIME_NONE, duration=0):
        """
        Sets the start and/or duration time

        Only use this method when you wish to modify BOTH start and duration at once
        """
        self._setStartDurationTime(start, duration)
        if self._linked:
            self._linked._setStartDurationTime(start, duration)

    ## methods to override in subclasses

    def _makeGnlObject(self):
        """ create and return the gnl_object """
        raise NotImplementedError

    ## private methods

    def __repr__(self):
        if hasattr(self, "name"):
            return "<%s '%s' at 0x%x>" % (type(self).__name__, self.name, id(self))
        return "<%s at 0x%x>" % (type(self).__name__, id(self))

    def _setFactory(self, factory):
        if self._factory:
            gst.warning("Can't set a factory, this object already has one : %r" % self._factory)
            return
        if factory !=None and not isinstance(factory, ObjectFactory):
            raise TypeError, "factory provided is not an ObjectFactory"
        gst.log("factory:%r requires factory:%r" % (factory, self.__requires_factory__))
        self._factory = factory
        if not self.__requires_factory__ or self._factory:
            gst.log("%r Creating associated gnlobject" % self)
            tmpgnl = self._makeGnlObject()
            if tmpgnl == None:
                raise Exception("We didn't get gnlobject for %r" % self)
            self.gnlobject = tmpgnl
            self.gnlobject.log("got gnlobject !")
            self.gnlobject.connect("notify::start", self._startDurationChangedCb)
            self.gnlobject.connect("notify::duration", self._startDurationChangedCb)
            self._setStartDurationTime(self._start, self._duration, force=True)

    def _setStartDurationTime(self, start=gst.CLOCK_TIME_NONE, duration=0, force=False):
        # really modify the start/duration time
        self.gnlobject.info("start:%s , duration:%s" %( gst.TIME_ARGS(start),
                                                        gst.TIME_ARGS(duration)))
        if duration > 0 and (not self._duration == duration or force):
            self._duration = duration
            self.gnlobject.set_property("duration", long(duration))
        if not start == gst.CLOCK_TIME_NONE and (not self._start == start or force):
            self._start = start
            self.gnlobject.set_property("start", long(start))

    def _startDurationChangedCb(self, gnlobject, prop):
        """ start/duration time has changed """
        gst.log("self:%r , gnlobject:%r %r" % (self, gnlobject, self.gnlobject))
        if not gnlobject == self.gnlobject:
            gst.warning("We're receiving signals from an object we dont' control (self.gnlobject:%r, gnlobject:%r)" % (self.gnlobject, gnlobject))
        self.gnlobject.debug("property:%s" % prop.name)
        start = gst.CLOCK_TIME_NONE
        duration = 0
        if prop.name == "start":
            start = gnlobject.get_property("start")
            gst.log("start: %s => %s" % (gst.TIME_ARGS(self._start),
                                         gst.TIME_ARGS(start)))
            if start == self._start:
                start = gst.CLOCK_TIME_NONE
            else:
                self._start = long(start)
        elif prop.name == "duration":
            duration = gnlobject.get_property("duration")
            gst.log("duration: %s => %s" % (gst.TIME_ARGS(self._duration),
                                            gst.TIME_ARGS(duration)))
            if duration == self._duration:
                duration = 0
            else:
                self.gnlobject.debug("duration changed:%s" % gst.TIME_ARGS(duration))
                self._duration = long(duration)
        self.emit("start-duration-changed", self._start, self._duration)


    # Serializable methods

    def toDataFormat(self):
        ret = BrotherObjects.toDataFormat(self)
        ret["start"] = self.start
        ret["duration"] = self._duration
        ret["name"] = self.name
        if self._factory:
            ret["factory-uid"] = self._factory.getUniqueID()
        ret["media_type"] = self.media_type
        return ret

    def fromDataFormat(self, obj):
        BrotherObjects.fromDataFormat(self, obj)
        self._start = obj["start"]
        self._duration = obj["duration"]

        self.name = obj["name"]

        self.media_type = obj["media_type"]

        if "factory-uid" in obj:
            factory = ObjectFactory.getObjectByUID(obj["factory-uid"])
            gst.log("For factory-id %d we got factory %r" % (obj["factory-uid"], factory))
            if not factory:
                ObjectFactory.addPendingObjectRequest(self, obj["factory-uid"], "factory")
            else:
                self._setFactory(factory)

    def pendingObjectCreated(self, obj, field):
        if field == "factory":
            self._setFactory(obj)
        else:
            BrotherObjects.pendingObjectCreated(self, obj, field)
