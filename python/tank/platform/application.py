# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Defines the base class for all Tank Apps.

"""

import os
import sys
import copy

from ..util.loader import load_plugin
from . import constants
from . import validation
from .framework import setup_frameworks
from .bundle import TankBundle
from .errors import TankContextChangeNotSupportedError
from ..util.metrics import EventMetric

class Application(TankBundle):
    """
    Base class for all Applications (Apps) running in Toolkit.
    """

    def __init__(self, tk, instance_name, descriptor, context, env, settings, engine):
        """
        Application instances are constructed by the toolkit launch process
        and various factory methods such as :meth:`start_engine`.

        :param engine: The engine instance to connect this app to
        :param app_name: The short name of this app (e.g. tk-nukepublish)
        :param settings: a settings dictionary for this app
        """
        self.__engine = engine

        # create logger for this app
        # log will be parented in a sgtk.env.environment_name.engine_instance_name.app_instance_name hierarchy
        logger = self.__engine.get_child_logger(instance_name)

        # init base class
        TankBundle.__init__(self, tk, instance_name, descriptor, context, env, settings, logger)

        # set up any frameworks defined
        setup_frameworks(engine, self, context, env, descriptor)

        self.log_debug("App init: Instantiating %s" % self)

        # now if a folder named python is defined in the app, add it to the pythonpath
        app_path = os.path.dirname(sys.modules[self.__module__].__file__)
        python_path = os.path.join(app_path, constants.BUNDLE_PYTHON_FOLDER)
        if os.path.exists(python_path):
            # only append to python path if __init__.py does not exist
            # if __init__ exists, we should use the special tank import instead
            init_path = os.path.join(python_path, "__init__.py")
            if not os.path.exists(init_path):
                self.log_debug("Appending to PYTHONPATH: %s" % python_path)
                sys.path.append(python_path)

    def __repr__(self):
        return "<Sgtk App 0x%08x: %s, engine: %s>" % (id(self), self.instance_name, self.engine)

    def _destroy_frameworks(self):
        """
        Called on destroy, prior to calling destroy_app
        """
        for fw in self.frameworks.values():
            # don't destroy shared frameworks
            # the engine is responsible for this
            if not fw.is_shared:
                fw._destroy_framework()

    ##########################################################################################
    # properties

    @property
    def shotgun(self):
        """
        Returns a Shotgun API handle associated with the currently running
        environment. This method is a convenience method that calls out
        to :meth:`~sgtk.Tank.shotgun`.

        :returns: Shotgun API handle
        """
        # pass on information to the user agent manager which bundle is returning
        # this sg handle. This information will be passed to the web server logs
        # in the shotgun data centre and makes it easy to track which app and engine versions
        # are being used by clients
        try:
            self.tank.shotgun.tk_user_agent_handler.set_current_app(self.name,
                                                                    self.version,
                                                                    self.engine.name,
                                                                    self.engine.version)
        except AttributeError:
            # looks like this sg instance for some reason does not have a
            # tk user agent handler associated.
            pass

        return self.tank.shotgun

    @property
    def engine(self):
        """
        The engine that this app is connected to.
        """
        return self.__engine

    def get_metrics_properties(self):
        """
        Returns a dictionary with properties to use when emitting a metric event
        for this application in the current engine.

        The dictionary contains information about this application, about the
        current engine, and about the application hosting the engine. For each of
        them, a name and a version string are available::

            {
                'Host App': 'Maya',
                'Host App Version': '2017',
                'Engine': 'tk-maya',
                'Engine Version': 'v0.4.1',
                'App': 'tk-multi-about',
                'App Version': '1.2.3'
            }

        :returns: Dictionary with info per above.
        """
        properties = self.engine.get_metrics_properties()
        properties.update({
            EventMetric.KEY_APP: self.name,
            EventMetric.KEY_APP_VERSION: self.version
        })
        return properties

    ##########################################################################################
    # init, destroy, and context changing

    def init_app(self):
        """
        Implemented by deriving classes in order to initialize the app
        Called by the engine as it loads the app.
        """
        pass

    def post_engine_init(self):
        """
        Implemented by deriving classes in order to run code after the engine
        has completely finished initializing itself and all its apps.
        At this point, the engine has a fully populated apps dictionary and
        all loaded apps have been fully initialized and validated.
        """
        pass

    def destroy_app(self):
        """
        Implemented by deriving classes in order to tear down the app
        Called by the engine as it is being destroyed.
        """
        pass

    def change_context(self, new_context):
        """
        Called when the application is being asked to change contexts. This
        will only be allowed if the app explicitly supports on-the-fly
        context changes by way of its context_change_allowed property. Any
        apps that do not support context changing will be restarted instead.
        Custom behavior at the application level should be handled by overriding
        one or both of pre_context_change and post_context_change methods.

        :param new_context:     The context to change to.
        :type new_context: :class:`~sgtk.Context`
        """
        super(Application, self).change_context(new_context)

        # Use the current context as the old context
        old_context = self.context

        if new_context == old_context:
            return

        # Now that we're certain we can perform a context change,
        # we can tell the environment what the new context is, and update
        # our own context property.
        from .engine import get_environment_from_context
        new_env = get_environment_from_context(self.sgtk, new_context)
        new_descriptor = new_env.get_app_descriptor(self.engine.instance_name, self.instance_name)
        new_settings = new_env.get_app_settings(self.engine.instance_name, self.instance_name)

        # Make sure that the engine in the target context is the same as the current
        # engine. In the case of git or app_store descriptors, the equality check
        # is an "is" check to see if they're references to the same object due to the
        # fact that those descriptor types are singletons. For dev descriptors, the
        # check is going to compare the paths of the descriptors to see if they're
        # referencing the same data on disk, in which case they are equivalent.
        if new_descriptor != self.descriptor:
            self.log_debug("Application %r does not match descriptors between %r and %r." % (
                self,
                old_context,
                new_context
            ))
            raise TankContextChangeNotSupportedError

        # make sure the current operating system platform is supported
        validation.validate_platform(new_descriptor)

        # validate that the context contains all the info that the app needs
        if self.engine.name != constants.SHOTGUN_ENGINE_NAME: 
            # special case! The shotgun engine is special and does not have a 
            # context until you actually run a command, so disable the validation.
            validation.validate_context(new_descriptor, new_context)

        # Validate the new settings for the application
        validation.validate_settings(
            self.instance_name,
            self.sgtk,
            new_context,
            new_descriptor.configuration_schema,
            new_settings,
            True,
            self
        )

        self.log_debug("Changing from %r to %r." % (old_context, new_context))

        from .engine import _CoreContextChangeHookGuard
        with _CoreContextChangeHookGuard(self.sgtk, old_context, new_context):
            # Run the pre_context_change method to allow for any app-specific
            # prep work to happen.
            self.log_debug("Executing pre_context_change for app %r." % self)
            self.pre_context_change(old_context, new_context)
            self.log_debug("Execution of pre_context_change for app %r is complete." % self)

            self._env = new_env
            self._descriptor = new_descriptor
            self._context = new_context
            self._settings = new_settings

            # Make sure our frameworks are up and running properly for the new context.
            setup_frameworks(self.engine, self, new_context, new_env, new_descriptor)

            # Call the post_context_change method to allow for any engine
            # specific post-change logic to be run.
            self.log_debug("Executing post_context_change for %r." % self)
            self.post_context_change(old_context, new_context)
            self.log_debug("Execution of post_context_change for app %r is complete." % self)

    ##########################################################################################
    # public methods

    def get_setting_for_env(self, key, env, default=None):
        """
        Get a value from the item's settings given the specified environment::

            >>> app.get_setting_for_env('entity_types', env_obj)
            ['Sequence', 'Shot', 'Asset', 'Task']

        :param key: config name
        :param env: The :class:`~Environment` object
        :param default: default value to return
        :returns: Value from the specified environment configuration
        """
        app_settings = env.get_app_settings(self.engine.instance_name, self.instance_name)
        return self.get_setting_from(app_settings, key, default)


    ##########################################################################################
    # event handling

    def event_engine(self, event):
        """
        Called when the parent engine emits an event. This method
        is intended to be overridden by deriving classes in order to
        implement event-specific behavior.

        .. note:: This method is called for all engine event types. If
                  overriding this method to implement an event handler
                  in a specific app, the event object received will need
                  to be checked via isinstance (or via its event_type
                  property) to know what event has been triggered. As
                  there are also type specific event handlers available,
                  it is considered best practice to use those in all
                  cases except those where a generic handler is absolutely
                  required.

        .. warning:: It is possible that events will be triggered quite
                     frequently. It is important to keep performance in
                     mind when writing an event handler.

        :param event:   The event object that was emitted.
        :type event:    :class:`~sgtk.platform.events.EngineEvent`
        """
        pass

    def event_file_open(self, event):
        """
        Called when the parent engine emits a file-open event. This method
        is intended to be overridden by deriving classes.

        .. warning:: It is possible that events will be triggered quite
                     frequently. It is important to keep performance in
                     mind when writing an event handler.

        :param event:   The event object that was emitted.
        :type event:    :class:`~sgtk.platform.events.FileOpenEvent`
        """
        pass

    def event_file_close(self, event):
        """
        Called when the parent engine emits a file-close event. This method
        is intended to be overridden by deriving classes.

        .. warning:: It is possible that events will be triggered quite
                     frequently. It is important to keep performance in
                     mind when writing an event handler.

        :param event:   The event object that was emitted.
        :type event:    :class:`~sgtk.platform.events.FileCloseEvent`
        """
        pass

    ##########################################################################################
    # logging methods

    def log_debug(self, msg):
        """
        Logs a debug message.

        .. deprecated:: 0.18
            Use :meth:`Engine.logger` instead.

        :param msg: Message to log.
        """
        self.logger.debug(msg)

    def log_info(self, msg):
        """
        Logs an info message.

        .. deprecated:: 0.18
            Use :meth:`Engine.logger` instead.

        :param msg: Message to log.
        """
        self.logger.info(msg)

    def log_warning(self, msg):
        """
        Logs an warning message.

        .. deprecated:: 0.18
            Use :meth:`Engine.logger` instead.

        :param msg: Message to log.
        """
        self.logger.warning(msg)

    def log_error(self, msg):
        """
        Logs an error message.

        .. deprecated:: 0.18
            Use :meth:`Engine.logger` instead.

        :param msg: Message to log.
        """
        self.logger.error(msg)

    def log_exception(self, msg):
        """
        Logs an exception message.

        .. deprecated:: 0.18
            Use :meth:`Engine.logger` instead.

        :param msg: Message to log.
        """
        self.logger.exception(msg)


def load_application(engine_obj, context, env, instance_name):
    """
    Validates, loads and initializes an application.

    :param engine_obj:          The engine instance to use when loading the application
    :param env:                 The environment containing the framework instance to load
    :param instance_name:       The instance name of the application (e.g. tk-multi-foo)
    :returns:                   An initialized application object.
    :raises:                    TankError if the application can't be found, has an invalid
                                configuration or fails to initialize.
    """

    # get the application descriptor
    descriptor = env.get_app_descriptor(engine_obj.instance_name, instance_name)
    if not descriptor.exists_local():
        raise TankError("Cannot start app! %s does not exist on disk." % descriptor)

    # for multi engine apps, make sure our engine is supported
    supported_engines = descriptor.supported_engines
    if supported_engines and engine_obj.name not in supported_engines:
        raise TankError("The app could not be loaded since it only supports "
                        "the following engines: %s. Your current engine has been "
                        "identified as '%s'" % (supported_engines, self.name))

    # get the application settings and validate
    settings = env.get_app_settings(engine_obj.instance_name, instance_name)

    # get path to framework code
    app_folder = descriptor.get_path()

    return get_application(engine_obj, app_folder, descriptor, settings, instance_name, env, context)

def get_application(engine_obj, app_folder, descriptor, settings, instance_name, env, context=None):
    """
    Internal helper method. 
    (Removed from the engine base class to make it easier to run unit tests).
    Returns an application object given an engine and app settings.
    
    :param engine: the engine this app should run in
    :param app_folder: the folder on disk where the app is located
    :param descriptor: descriptor for the app
    :param settings: a settings dict to pass to the app
    :param instance_name: the instance name of the application (e.g. tk-multi-foo)
    :param env: the environment containing the framework instance to load
    """

    # The context is an optional param, so use the engine's context if not specified
    context = context or engine_obj.context

    # First see if the engine has a matching app instance
    if instance_name in engine_obj.apps:
        app_obj = engine_obj.apps[instance_name]
        if app_obj.env == env and \
           app_obj.context == context and \
           app_obj.descriptor == descriptor and \
           app_obj.settings == settings:
            return app_obj

    plugin_file = os.path.join(app_folder, constants.APP_FILE)

    # Instantiate the app
    class_obj = load_plugin(plugin_file, Application)
    app_obj = class_obj(engine_obj.sgtk, instance_name, descriptor, context, env, settings, engine_obj)
    return app_obj
