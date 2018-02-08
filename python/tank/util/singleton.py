# Copyright (c) 2016 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

from __future__ import with_statement
import threading


class Threaded(object):
    """
    Threaded base class that contains a threading.Lock member and an
    'exclusive' function decorator that implements exclusive access
    to the contained code using the lock
    """
    def __init__(self):
        """
        Construction
        """
        self._lock = threading.Lock()

    @staticmethod
    def exclusive(func):
        """
        Static method intended to be used as a function decorator in derived
        classes.  Use it by doing:

            @Threaded.exclusive
            def my_method(self, ...):
                ...

        :param func:    Function to decorate/wrap
        :returns:       Wrapper function that executes the function inside the acquired lock
        """
        def wrapper(self, *args, **kwargs):
            """
            Internal wrapper method that executes the function with the specified arguments
            inside the acquired lock

            :param *args:       The function parameters
            :param **kwargs:    The function named parameters
            :returns:           The result of the function call
            """
            self._lock.acquire()
            try:
                return func(self, *args, **kwargs)
            finally:
                self._lock.release()

        return wrapper


class Singleton(object):
    """
    Thread-safe base class for singletons. Derived classes must implement _init_singleton.
    """

    __lock = threading.Lock()
    def __new__(cls, *args, **kwargs):
        """
        Create the singleton instance if it hasn't been created already. Once instantiated,
        the object will be cached and never be instantiated again for performance
        reasons.
        """

        # Check if the instance has been created before taking the lock for performance
        # reason.
        if not hasattr(cls, "_instance") or cls._instance is None:
            # Take the lock.
            with cls.__lock:
                # Check the instance again, it might have been created between the
                # if and the lock.
                if hasattr(cls, "_instance") and cls._instance:
                    return cls._instance

                # Create and init the instance.
                instance = super(Singleton, cls).__new__(
                    cls,
                    *args,
                    **kwargs
                )
                instance._init_singleton()

                # remember the instance so that no more are created
                cls._instance = instance

        return cls._instance

    @classmethod
    def clear_singleton(cls):
        """
        Clears the internal singleton instance.
        """
        cls._instance = None
