# PiTiVi , Non-linear video editor
#
#       pitivi/pipeline.py
#
# Copyright (c) 2009, Edward Hervey <bilboed@bilboed.com>
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
High-level pipelines
"""
from pitivi.signalinterface import Signallable
from pitivi.factories.base import SourceFactory, SinkFactory
from pitivi.action import ActionError
from pitivi.stream import pad_compatible_stream, get_src_pads_for_stream, \
     get_sink_pads_for_stream, get_stream_for_caps
import gst

(STATE_NULL,
 STATE_READY,
 STATE_PAUSED,
 STATE_PLAYING) = (gst.STATE_NULL, gst.STATE_READY, gst.STATE_PAUSED, gst.STATE_PLAYING)

# FIXME : define/document a proper hierarchy
class PipelineError(Exception):
    pass

# TODO : Add a convenience method to automatically do the following process:
#  * Creating a Pipeline
#  * Creating an Action
#  * Setting the Action on the Pipeline
#  * (optional) Adding producer/consumer factories in the Pipeline
#  * (optional) Setting the producer/consumer on the Action
#  * (optional) Activating the Action
# Maybe that convenience method could be put in a higher-level module, like the
# one that handles all the Pipelines existing in the application.

class Pipeline(object, Signallable):
    """
    A container for all multimedia processing.

    The Pipeline is only responsible for:
     - State changes
     - Position seeking
     - Position Querying
       - Along with an periodic callback (optional)

    You can set L{Action}s on it, which are responsible for choosing which
    C{ObjectFactories} should be used, and how they should be linked.

    Signals:
     - C{action-added} : A new L{Action} was added.
     - C{action-removed} : An L{Action} was removed.
     - C{factory-added} : An L{ObjectFactory} was added.
     - C{factory-removed} : An L{ObjectFactory} was removed.
     - C{state-changed} : The state of the pipeline changed.
     - C{position} : The current position of the pipeline changed.
     - C{unhandled-stream} : A factory produced a stream which wasn't handled
       by any of the L{Action}s.
     - C{eos} : The Pipeline has finished playing.
     - C{error} : An error happened.

    @ivar state: The current state. This is a cached value, use getState() for
    the exact actual C{gst.State} of the L{Pipeline}.
    @type state: C{gst.State}
    @ivar actions: The Action(s) currently used.
    @type actions: List of L{Action}
    @ivar factories: The ObjectFactories handled by the Pipeline.
    @type factories: List of L{ObjectFactory}
    @ivar bins: The gst.Bins used, FOR ACTION USAGE ONLY
    @type bins: Dictionnary of L{ObjectFactory} to L{gst.Bin}
    @ivar tees: The tees used after producers, FOR ACTION USAGE ONLY
    @type tees: Dictionnary of (L{SourceFactory},L{MultimediaStream}) to C{gst.Element}
    @ivar queues: The queues used before consumers, FOR ACTION USAGE ONLY
    @type queues: Dictionnary of (L{SinkFactory},L{MultimediaStream}) to C{gst.Element}
    """

    __signals__ = {
        "action-added" : ["action"],
        "action-removed" : ["action"],
        "factory-added" : ["factory"],
        "factory-removed" : ["factory"],
        "state-changed" : ["state"],
        "position" : ["position"],
        "unhandled-stream" : ["factory", "stream"],
        "eos" : [],
        "error" : ["message", "details"]
        }

    def __init__(self):
        self._pipeline = gst.Pipeline()
        self._bus = self._pipeline.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect("message", self._busMessageCb)
        self.factories = []
        self.bins = {} # factory => gst.Bin
        self.tees = {} # (producerfactory, stream) => gst.Element ("tee")
        self.queues = {} # (consumerfactory, stream) => gst.Element ("queue")
        self.actions = []
        self._state = STATE_NULL
        self._padSigIds = {} # (factory) => (bin,paddaddedsigid,padremovedsigid)
        self._listening = False # for the position handler
        self._listeningInterval = 300 # default 300ms
        self._listeningSigId = 0

    def release(self):
        """
        Release the L{Pipeline} and all used L{ObjectFactory} and
        L{Action}s.

        Call this method when the L{Pipeline} is no longer used. Forgetting to do
        so will result in memory loss.

        @postcondition: The L{Pipeline} will no longer be usable.
        """
        self._pipeline.set_state(STATE_NULL)
        self._listenToPosition(False)
        raise NotImplementedError

    #{ Action-related methods

    def addAction(self, action):
        """
        Add the given L{Action} to the Pipeline.

        @return: The L{Action} that was set
        @rtype: L{Action}
        @raise PipelineError: If the given L{Action} is already set to another
        Pipeline
        """
        gst.debug("action:%r" % action)
        if action in self.actions:
            gst.debug("Action is already used by this Pipeline, returning")
            return action

        if action.pipeline != None:
            raise PipelineError("Action is set to another pipeline (%r)" % action.pipeline)

        action.setPipeline(self)
        gst.debug("Adding action to list of actions")
        self.actions.append(action)
        gst.debug("Emitting 'action-added' signal")
        self.emit("action-added", action)
        gst.debug("Returning")
        return action

    def setAction(self, action):
        """
        Set the given L{Action} on the L{Pipeline}.
        If an L{Action} of the same type already exists in the L{Pipeline} the
        L{Action} will not be set.

        @see: L{addAction}, L{removeAction}

        @param action: The L{Action} to set on the L{Pipeline}
        @type action: L{Action}
        @rtype: L{Action}
        @return: The L{Action} used. Might be different from the one given as
        input.
        """
        gst.debug("action:%r" % action)
        for ac in self.actions:
            if type(action) == type(ac):
                gst.debug("We already have a %r Action : %r" % (type(action), ac))
                return ac
        return self.addAction(action)

    def removeAction(self, action):
        """
        Remove the given L{Action} from the L{Pipeline}.

        @precondition: Can only be done if both:
         - The L{Pipeline} is in READY or NULL
         - The L{Action} is de-activated

        @see: L{addAction}, L{setAction}

        @param action: The L{Action} to remove from the L{Pipeline}
        @type action: L{Action}
        @rtype: L{bool}
        @return: Whether the L{Action} was removed from the L{Pipeline} or not.
        @raise PipelineError: If L{Action} is activated and L{Pipeline} is not
        READY or NULL
        """
        gst.debug("action:%r" % action)
        if not action in self.actions:
            gst.debug("action not controlled by this Pipeline, returning")
            return
        if action.isActive() and self._state in [STATE_PAUSED, STATE_PLAYING]:
            raise PipelineError("Active actions can't be removed from PLAYING or PAUSED Pipeline")
        try:
            action.unsetPipeline()
        except ActionError:
            raise PipelineError("Can't unset Pipeline from Action")
        self.actions.remove(action)
        self.emit('action-removed', action)

    #{ State-related methods

    def setState(self, state):
        """
        Set the L{Pipeline} to the given state.

        @raises PipelineError: If the C{gst.Pipeline} could not be changed to
        the requested state.
        """
        gst.debug("state:%r" % state)
        if self._state == state:
            gst.debug("Already at the required state, returning")
            return
        res = self._pipeline.set_state(state)
        if res == gst.STATE_CHANGE_FAILURE:
            raise PipelineError("Failure changing state of the gst.Pipeline")
        if res == gst.STATE_CHANGE_SUCCESS:
            # the change to the request state was successful and not asynchronous
            self._state = state
            self.emit('state-changed', self._state)
            # update position listener status
            self._listenToPosition(state in [STATE_PAUSED, STATE_PLAYING])

    def getState(self):
        """
        Query the L{Pipeline} for the current state.

        @see: L{setState}

        This will do an actual query to the underlying GStreamer Pipeline.
        @return: The current state.
        @rtype: C{State}
        """
        change, state, pending = self._pipeline.get_state(0)
        gst.debug("change:%r, state:%r, pending:%r" % (change, state, pending))
        if change != gst.STATE_CHANGE_FAILURE and pending == gst.STATE_VOID_PENDING and state != self._state:
            self._state = state
            self.emit('state-changed', self._state)
            # update position listener status
            self._listenToPosition(state in [STATE_PAUSED, STATE_PLAYING])
        gst.debug("Returning %r" % self._state)
        return self._state

    @property
    def state(self):
        """
        The state of the L{Pipeline}.

        @warning: This doesn't query the underlying C{gst.Pipeline} but returns the cached
        state.
        """
        gst.debug("Returning state %r" % self._state)
        return self._state

    def play(self):
        """
        Sets the L{Pipeline} to PLAYING
        """
        self.setState(STATE_PLAYING)

    def pause(self):
        """
        Sets the L{Pipeline} to PAUSED
        """
        self.setState(STATE_PAUSED)

    def stop(self):
        """
        Sets the L{Pipeline} to READY
        """
        self.setState(STATE_READY)

    #{ ObjectFactory-related methods

    def addFactory(self, *factories):
        """
        Adds the given L{ObjectFactory} to be used in the L{Pipeline}.

        @precondition: The L{Pipeline} state must be READY or NULL if you wish to
        add L{SourceFactory} elements.

        @param factories: The L{ObjectFactory}s to add
        @type factories: L{ObjectFactory}
        @raise PipelineError: If the L{Pipeline} isn't in READY or NULL and one
        of the factories is not a L{SinkFactory}
        """
        gst.debug("factories %r" % list(factories))
        if self._state in [STATE_PAUSED, STATE_PLAYING]:
            if [f for f in factories if not isinstance(f, SinkFactory)] != []:
                raise PipelineError("Can't add source factories, Pipeline is not READY or NULL")
        for fact in factories:
            if not fact in self.factories:
                self.factories.append(fact)
                self.emit('factory-added', fact)

    def removeFactory(self, *factories):
        """
        Removes the given L{ObjectFactory}s from the L{Pipeline}.

        @precondition: The L{Pipeline} state must be READY or NULL and the
        L{Action}s controlling those factories must all be deactivated.

        @see: L{addFactory}

        @param factories: The L{ObjectFactory}s to remove.
        @type factories: L{ObjectFactory}
        @raise PipelineError: If the L{Pipeline} isn't in READY or NULL or if
        some of the factories are still used by active L{Action}s.
        """
        gst.debug("factories %r" % list(factories))
        if self._state in [STATE_PAUSED, STATE_PLAYING]:
            raise PipelineError("Can't remove factories, Pipeline is not READY or NULL")
        rfact = [f for f in factories if f in self.factories]
        # we can only remove factories that are used in inactive actions
        for act in [x for x in self.actions if x.isActive()]:
            for f in rfact:
                if f in act.producers or f in act.consumers:
                    raise PipelineError("Some factories belong to still active Action")
        # at this point we can remove the factories
        for f in rfact:
            self._removeFactory(f)

    def _removeFactory(self, factory):
        gst.debug("factory %r" % factory)
        # internal method
        # We should first remove the factory from all used Actions
        for a in self.actions:
            if factory in a.producers:
                a.removeProducers(factory)
            elif factory in a.consumers:
                a.removeConsumers(factory)

        # Then the bin (and not forget to release that bin from the
        # objectfactory)
        gst.debug("Getting corresponding gst.Bin")
        b = self.bins.pop(factory, None)
        if b:
            gst.debug("Really removing %r from gst.Pipeline" % b)
            self._pipeline.remove(b)
            factory.releaseBin(b)

        # And finally remove the factory itself from our list
        self.factories.remove(factory)
        self.emit("factory-removed", factory)

    #{ Position and Seeking methods

    def getPosition(self, format=gst.FORMAT_TIME):
        """
        Get the current position of the L{Pipeline}.

        @param format: The format to return the current position in
        @type format: C{gst.Format}
        @return: The current position or gst.CLOCK_TIME_NONE
        @rtype: L{long}
        @raise PipelineError: If the position couldn't be obtained.
        """
        gst.log("format %r" % format)
        try:
            cur, format = self._pipeline.query_position(format)
        except:
            raise PipelineError("Couldn't get position")
        gst.log("Got position %s" % gst.TIME_ARGS(cur))
        return cur

    def activatePositionListener(self, interval=300):
        """
        Activate the position listener.

        When activated, the Pipeline will emit the 'position' signal at the
        specified interval when it is the PLAYING or PAUSED state.

        @see: L{deactivatePositionListener}
        @param interval: Interval between position queries in milliseconds
        @type interval: L{int} milliseconds
        @return: Whether the position listener was activated or not
        @rtype: L{bool}
        """
        if self._listening == True:
            return True
        self._listening = True
        # if we're in paused or playing, switch it on
        self._listenToPosition(self.getState() in [STATE_PAUSED, STATE_PLAYING])
        return True

    def deactivatePositionListener(self):
        """
        De-activates the position listener.

        @see: L{activatePositionListener}
        """
        self._listenToPosition(False)
        self._listening = False

    def _positionListenerCb(self):
        cur = self.getPosition()
        if cur != gst.CLOCK_TIME_NONE:
            self.emit('position', cur)
        return True

    def _listenToPosition(self, listen=True):
        # stupid and dumm method, not many checks done
        # i.e. it does NOT check for current state
        if listen == True:
            if self._listening == True and self._listeningSigId == 0:
                self._listeningSigId = gobject.timeout_add(self._listeningInterval,
                                                           self._positionListenerCb)
        elif self._listeningSigId != 0:
            gobject.source_remove(self._listeningSigId)
            self._listeningSigId = 0

    def seek(self, position, format=gst.FORMAT_TIME):
        """
        Seeks in the L{Pipeline} to the given position.

        @param position: Position to seek to
        @type position: L{long}
        @param format: The C{Format} of the seek position
        @type format: C{gst.Format}
        @raise PipelineError: If seek failed
        """
        if format == gst.FORMAT_TIME:
            gst.debug("position : %s" % gst.TIME_ARGS (position))
        else:
            gst.debug("position : %d , format:%d" % (position, format))
        # FIXME : temporarily deactivate position listener
        self._listenToPosition(False)

        res = self._pipeline.seek(1.0, format, gst.SEEK_FLAG_FLUSH,
                                  gst.SEEK_TYPE_SET, position,
                                  gst.SEEK_TYPE_NONE, -1)
        if not res:
            raise PipelineError("seek failed")
        gst.debug("seeking succesfull")
        self.emit('position', position)

    #{ GStreamer object methods (For Action usage only)

    def getBinForFactory(self, factory, automake=False):
        """
        Fetches the L{gst.Bin} currently used in the C{gst.Pipeline} for the
        given L{ObjectFactory}.

        @param factory: The factory to search.
        @type factory: L{ObjectFactory}
        @param automake: If set to True, then if there is not a L{gst.Bin}
        already created for the given factory, one will be created, added to the
        list of controlled bins and added to the C{gst.Pipeline}.
        @raise PipelineError: If the factory isn't used in this pipeline.
        @raise PipelineError: If a source L{gst.Bin} needed to be created and the
        L{Pipeline} was not in the READY or NULL state.
        @raise PipelineError: If a L{gst.Bin} needed to be created but the
        creation of that c{gst.Bin} failed.
        @return: The bin corresponding to the given factory or None if there
        are none for the given factory.
        @rtype: L{gst.Bin}
        """
        gst.debug("factory:%r , automake:%r" % (factory, automake))
        if not factory in self.factories:
            raise PipelineError("Given ObjectFactory isn't handled by this Pipeline")
        res = self.bins.get(factory, None)
        if (res != None) or (automake == False):
            gst.debug("Returning %r" % res)
            return res
        # we need to create one
        if self._state not in [STATE_NULL, STATE_READY] and isinstance(factory, SourceFactory):
            raise PipelineError("Pipeline not in NULL/READY, can not create source bin")
        # create the bin (will raise exceptions if it fails)
        return self._makeBin(factory)

    def getTeeForFactoryStream(self, factory, stream=None, automake=False):
        """
        Fetches the C{Tee} currently used in the C{gst.Pipeline} for the given
        L{SourceFactory}.

        @param factory: The factory to search.
        @type factory: L{SourceFactory}
        @param stream: The stream of the factory to use. If not specified, then
        a random stream from that factory will be used.
        @type stream: L{MultimediaStream}
        @param automake: If set to True, then if there is not a C{Tee}
        already created for the given factory/stream, one will be created, added
        to the list of controlled tees and added to the C{gst.Pipeline}.
        @raise PipelineError: If the factory isn't used in this pipeline.
        @raise PipelineError: If the factory isn't a L{SourceFactory}.
        @raise PipelineError: If a C{Tee} needed to be created but the
        creation of that C{Tee} failed.
        @return: The C{Tee} corresponding to the given factory/stream or None if
        there are none for the given factory.
        @rtype: C{gst.Element}
        """
        gst.debug("factory:%r , stream:%r, automake:%r" % (factory, stream, automake))
        if not factory in self.factories:
            raise PipelineError("Given ObjectFactory isn't handled by this Pipeline")
        if not isinstance(factory, SourceFactory):
            raise PipelineError("Given ObjectFactory isn't a SourceFactory")
        res = self.tees.get((factory,stream), None)
        if (res != None) or (automake == False):
            gst.debug("Returning %r" % res)
            return res
        # create the tee
        return self._makeTee(factory, stream)

    def releaseTeeForFactoryStream(self, factory, stream):
        """
        Release the tee associated with the given source factory and stream.
        If this was the last action to release the given (factory,stream), then the
        tee will be removed.

        This should be called by Actions when they deactivate, after having called
        releaseQueueForFactoryStream() for the consumers.

        @see: L{getTeeForFactoryStream}

        @param factory: The factory
        @type factory: L{SinkFactory}
        @param stream: The stream
        @type stream: L{MultimediaStream}
        @raise PipelineError: If the Pipeline isn't in NULL or READY.
        """
        gst.debug("factory:%r, stream:%r" % (factory, stream))
        if self._state not in [STATE_NULL, STATE_READY]:
            raise PipelineError("Pipeline not in NULL/READY, can not release queue")
        # release the tee for the given factory/stream
        # When nobody is using the tee => remove/free it
        # if no more tees are connected for a given factory/stream, remove
        # the signal handlers
        t = self.tees.get((factory,stream), None)
        gst.debug("Found tee %r" % t)
        if t:
            #figure out if people are still using it (i.e. srcpads != [])
            if list(t.src_pads()) == []:
                gst.debug("Nobody is using the tee anymore, releasing it")
                src = self.bins[factory]
                # FIXME : This might fail if it's not linked
                src.unlink(t)
                self._pipeline.remove(t)
                # remove that tee from ourselves
                del self.tees[(factory,stream)]

                # figure out if there are remaining tees for that factory
                if factory in self._padSigIds.keys() and [f for f,s in self.tees.keys() if f == factory] == []:
                    gst.debug("Nobody is using %s anymore, removing signal handlers" % src)
                    bin, addsig, removesig = self._padSigIds.pop(factory)
                    src.disconnect(addsig)
                    src.disconnect(removesig)
            else:
                gst.debug("Tee is still being used %r" % list(t.src_pads()))

    def getQueueForFactoryStream(self, factory, stream=None, automake=False):
        """
        Fetches the C{Queue} currently used in the C{gst.Pipeline} for the given
        L{SinkFactory}.

        @param factory: The factory to search.
        @type factory: L{SinkFactory}
        @param stream: The stream of the factory to use. If not specified, then
        a random stream from that factory will be used.
        @type stream: L{MultimediaStream}
        @param automake: If set to True, then if there is not a C{Queue}
        already created for the given factory/stream, one will be created, added
        to the list of controlled queues and added to the C{gst.Pipeline}.
        @raise PipelineError: If the factory isn't used in this pipeline.
        @raise PipelineError: If the factory isn't a L{SinkFactory}.
        @raise PipelineError: If a C{Queue} needed to be created but the
        creation of that C{Queue} failed.
        @return: The C{Queue} corresponding to the given factory/stream or None if
        there are none for the given factory.
        @rtype: C{gst.Element}
        """
        gst.debug("factory:%r , stream:%r, automake:%r" % (factory, stream, automake))
        if not factory in self.factories:
            raise PipelineError("Given ObjectFactory isn't handled by this Pipeline")
        if not isinstance(factory, SinkFactory):
            raise PipelineError("Given ObjectFactory isn't a SinkFactory")
        res = self.queues.get((factory,stream), None)
        if (res != None) or (automake == False):
            gst.debug("Returning %r" % res)
            return res
        # create the queue
        return self._makeQueue(factory, stream)

    def releaseQueueForFactoryStream(self, factory, stream):
        """
        Release the queue associated with the given source factory and stream.

        The queue object will be internally removed from the gst.Pipeline, along
        with the link with tee.

        This should be called by Actions when they deactivate.

        @see: L{getQueueForFactoryStream}

        @param factory: The factory
        @type factory: L{SinkFactory}
        @param stream: The stream
        @type stream: L{MultimediaStream}
        @raise PipelineError: If the Pipeline isn't in NULL or READY.
        """
        gst.debug("factory:%r, stream:%r" % (factory, stream))
        if self._state not in [STATE_NULL, STATE_READY]:
            raise PipelineError("Pipeline not in NULL/READY, can not release queue")
        # release the queue for the given factory/stream
        q = self.queues.pop((factory,stream), None)
        if q:
            gst.debug("Found a corresponding queue, unlink it from the consumer")
            # unlink it from the sink bin
            sink = self.bins[factory]
            q.unlink(sink)

            gst.debug("Unlinking it from the tee, if present")
            qpad = q.get_pad("sink")
            # figure out the peerpad
            tpad = qpad.get_peer()
            if tpad:
                tee = tpad.get_parent()
                tpad.unlink(qpad)
                tee.release_request_pad(tpad)
            gst.debug("Removing from gst.Pipeline")
            self._pipeline.remove(q)


    #}
    ## Private methods

    def _busMessageCb(self, unused_bus, message):
        gst.info("%s [%r]" % (message.type, message.src))
        if message.type == gst.MESSAGE_EOS:
            self.emit('eos')
        elif message.type == gst.MESSAGE_STATE_CHANGED and message.src == self._pipeline:
            prev, new, pending = message.parse_state_changed()
            gst.debug("Pipeline change state prev:%r, new:%r, pending:%r" % (prev, new, pending))
            if pending == gst.STATE_VOID_PENDING and self._state != new:
                self._state = new
                self._listenToPosition(self._state in [STATE_PAUSED, STATE_PLAYING])
                self.emit('state-changed', self._state)
        elif message.type == gst.MESSAGE_ERROR:
            error, detail = message.parse_error()
            self._handleErrorMessage(error, detail, message.src)

    def _makeBin(self, factory):
        """
        - Create a L{gst.Bin} from the given factory,
        - Add it to the list of controlled bins,
        - Put it in the gst.Pipeline.
        - Listen for newly created pads.

        @precondition: checks for the factory to be valid should be done before.
        """
        # FIXME : Who brings the newly created elements to the current pipeline
        # state ?
        # FIXME : How do we figure out for which streams we need to create the
        # Bin.
        # Ex : There could be one action wanting one stream from a given bin, and
        # another action wanting another stream.
        # ==> It should figure out from all Actions what streams are being used
        if factory in self.bins.keys():
            raise PipelineError("Bin for factory already exists !")
        gst.debug("factory %r" % factory)
        b = factory.makeBin()
        # listen to newly created pads
        self._listenToPads(b, factory)
        gst.debug("adding newly created bin [%r] to gst.Pipeline" % b)
        self._pipeline.add(b)
        gst.debug("Adding newly created bin to list of controlled bins")
        self.bins[factory] = b
        return b

    def _binPadAddedCb(self, bin, pad, factory):
        gst.debug("bin:%r, pad:%r" % (bin, pad))
        f = None
        for fact, b in self.bins.iteritems():
            if b == bin:
                f = fact
        if f == None:
            raise PipelineError("New pad on an element we don't control ??")
        stream = get_stream_for_caps(pad.get_caps(), pad)
        # ask all actions using this producer if they handle it
        handled = False
        for action in [x for x in self.actions if f in x.producers]:
            handled |= action.handleNewStream(f, stream)
        if handled == False:
            gst.debug("No action handled this Stream")
            self.emit('unhandled-stream', stream)

    def _binPadRemovedCb(self, bin, pad, factory):
        gst.debug("bin:%r, pad:%r" % (bin, pad))
        raise NotImplementedError

    def _listenToPads(self, bin, factory):
        gst.debug("bin:%r, factory:%r" % (bin, factory))
        # Listen on the given bin for pads being added/removed
        if not factory is self._padSigIds.keys():
            padaddedsigid = bin.connect('pad-added', self._binPadAddedCb,
                                        factory)
            padremovedsigid = bin.connect('pad-removed', self._binPadAddedCb,
                                          factory)
            self._padSigIds[factory] = (bin, padaddedsigid, padremovedsigid)

    def _makeTee(self, factory, stream):
        """
        - Create a C{Tee} for the given factory and stream
        - Add it to the list of controlled tees,
        - Add it to the gst.Pipeline,
        - Link the bin to the tee
          - If the bin doesn't have the corresponding pad yet, put a async
          handler.

        @precondition: checks for the factory and stream to be valid should be
        done before, including it's existence in the list of controlled tees.
        @raise PipelineError: If we can't figure out which pad to use from the
        source bin.
        """
        gst.debug("factory: %r, stream: %r" % (factory, stream))
        b = self.bins[factory]
        # find the source pads compatible with the given stream
        pads = get_src_pads_for_stream(b, stream)
        if len(pads) > 1:
            raise PipelineError("Can't figure out which source pad to use !")
        if pads == []:
            # if the pad isn't available yet, connect a 'pad-added' and
            # 'pad-removed' handler.
            gst.debug("No available pads, we assume it will produce a pad later on")
            return None

        t = gst.element_factory_make("tee")
        self._pipeline.add(t)
        gst.debug("Linking pad %r to tee" % pads[0])
        pads[0].link(t.get_pad("sink"))
        gst.debug("Adding newly created bin to list of controlled tees")
        self.tees[(factory, stream)] = t
        return t

    def _makeQueue(self, factory, stream):
        """
        - Create a C{Queue} for the given factory and stream
        - Add it to the list of controlled queues,
        - Add it to the gst.Pipeline,
        - Link the bin to the queue
          - If the bin doesn't have the corresponding pad yet, put a async
          handler.

        @precondition: checks for the factory and stream to be valid should be
        done before, including it's existence in the list of controlled queues.
        @raise PipelineError: If we can't figure out which pad to use from the
        source bin.
        """
        gst.debug("factory: %r, stream: %r" % (factory, stream))

        b = self.bins[factory]
        # find the source pads compatible with the given stream
        pads = get_sink_pads_for_stream(b, stream)
        gst.debug("Got pads %r" % pads)
        if len(pads) > 1:
            raise PipelineError("Can't figure out which sink pad to use !")
        if pads == []:
            # FIXME : Maybe it's a request pad ?
            raise PipelineError("No compatible sink pads !")

        q = gst.element_factory_make("queue")
        self._pipeline.add(q)

        gst.debug("Linking pad %r to queue" % pads[0])
        q.get_pad("src").link(pads[0])
        gst.debug("Adding newly created bin to list of controlled queues")
        self.queues[(factory, stream)] = q
        return q
